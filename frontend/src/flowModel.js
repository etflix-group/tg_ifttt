import { libraryEntry } from "./nodeLibrary.js";

const DEFAULT_POSITION = { x: 110, y: 70 };

export const TARGET_SESSION_NODE_TYPES = new Set([
  "telegram.send_message",
  "telegram.wait_message",
  "telegram.click_button",
  "telegram.read_messages",
]);

export const DEFAULT_SCHEDULE = {
  type: "schedule",
  interval_days: 1,
  hour: 9,
  minute: 0,
  second: 0,
  random_seconds: false,
};

const clone = (value) => structuredClone(value);

export function getNodeTarget(node, workflowTarget = "") {
  const config = node?.data?.config || node?.config || {};
  const localTarget = typeof config.target === "string" ? config.target.trim() : "";
  return localTarget || (typeof workflowTarget === "string" ? workflowTarget.trim() : "");
}

export function inferWorkflowTarget(document) {
  const explicitTarget = typeof document?.workflow?.target === "string" ? document.workflow.target.trim() : "";
  if (explicitTarget) return explicitTarget;
  const targets = (document?.nodes || [])
    .filter((node) => TARGET_SESSION_NODE_TYPES.has(node.type))
    .map((node) => typeof node.config?.target === "string" ? node.config.target.trim() : "")
    .filter(Boolean);
  return targets.length && new Set(targets).size === 1 ? targets[0] : "";
}

export function normalizeWorkflowDocument(document) {
  const target = inferWorkflowTarget(document);
  if (!target || document.workflow?.target === target) return document;
  return { ...document, workflow: { ...document.workflow, target } };
}

export function duplicateWorkflowDocument(document, workflowId, workflowName) {
  const duplicated = clone(document);
  duplicated.workflow = { ...duplicated.workflow, id: workflowId, name: workflowName };
  return duplicated;
}

export function getScheduleTrigger(triggers = []) {
  return triggers.find((trigger) => trigger?.type === "schedule") || null;
}

export function setScheduleTrigger(triggers = [], schedule = null) {
  const remaining = triggers.filter((trigger) => trigger?.type !== "schedule");
  return schedule ? [...remaining, { ...DEFAULT_SCHEDULE, ...structuredClone(schedule), type: "schedule" }] : (remaining.length ? remaining : [{ type: "manual" }]);
}

function finiteNumber(value, fallback) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function positionFor(layout, nodeId, index) {
  const saved = layout?.nodes?.[nodeId];
  const fallback = {
    x: DEFAULT_POSITION.x + (index % 3) * 300,
    y: DEFAULT_POSITION.y + Math.floor(index / 3) * 165,
  };
  return {
    x: finiteNumber(saved?.x, fallback.x),
    y: finiteNumber(saved?.y, fallback.y),
  };
}

export function documentToFlow(document) {
  const layout = document.ui || {};
  const nodes = document.nodes.map((node, index) => ({
    id: node.id,
    type: "workflow",
    position: positionFor(layout, node.id, index),
    data: { nodeType: node.type, config: structuredClone(node.config || {}), label: typeof node.name === "string" ? node.name : libraryEntry(node.type).label },
  }));
  const edges = document.edges.map((edge, index) => ({
    id: `edge-${index}-${edge.from}-${edge.to}`,
    source: edge.from,
    target: edge.to,
    label: edge.condition || "",
    data: { condition: edge.condition || "" },
    type: "smoothstep",
  }));
  return { nodes, edges };
}

export function flowToDocument(nodes, edges, metadata, triggers, ui = {}) {
  const nodeLayout = Object.fromEntries(nodes.map((node) => [
    node.id,
    {
      x: Math.round(node.position?.x || 0),
      y: Math.round(node.position?.y || 0),
    },
  ]));
  return {
    version: 1,
    workflow: { ...metadata, account: metadata.account || "" },
    triggers: structuredClone(triggers || [{ type: "manual" }]),
    nodes: nodes.map((node) => ({ id: node.id, name: node.data.label ?? "", type: node.data.nodeType, config: structuredClone(node.data.config || {}) })),
    edges: edges.map((edge) => {
      const condition = edge.data?.condition ?? edge.label ?? "";
      return { from: edge.source, to: edge.target, ...(condition ? { condition } : {}) };
    }),
    ui: { ...structuredClone(ui || {}), nodes: nodeLayout },
  };
}

export function renameFlowNode(nodes, nodeId, name) {
  return nodes.map((node) => node.id === nodeId ? { ...node, data: { ...node.data, label: name } } : node);
}

export function removeSelectedElement(nodes, edges, selection) {
  return removeSelectedElements(nodes, edges, selection);
}

export function removeSelectedElements(nodes, edges, selection) {
  const nodeIds = new Set(selection?.nodeIds || (selection?.kind === "node" && selection.id ? [selection.id] : []));
  const edgeId = selection?.edgeId || (selection?.kind === "edge" ? selection.id : null);
  if (!nodeIds.size && !edgeId) return { nodes, edges };
  return {
    nodes: nodes.filter((node) => !nodeIds.has(node.id)),
    edges: edges.filter((edge) => !nodeIds.has(edge.source) && !nodeIds.has(edge.target) && edge.id !== edgeId),
  };
}

export function validateConnection(connection, edges = [], ignoredEdgeId = null) {
  const source = connection?.source;
  const target = connection?.target;
  if (!source || !target) return { valid: false, reason: "连接需要来源和目标节点" };
  if (source === target) return { valid: false, reason: "不能连接节点自身" };
  if (edges.some((edge) => edge.id !== ignoredEdgeId && edge.source === source && edge.target === target)) {
    return { valid: false, reason: "这两个节点之间已经存在连线" };
  }
  return { valid: true };
}

export function insertNodeOnEdge(nodes, edges, edgeId, node) {
  const edge = edges.find((candidate) => candidate.id === edgeId);
  if (!edge || !node?.id) return { nodes, edges };
  const condition = edge.data?.condition ?? edge.label ?? "";
  const base = { type: edge.type || "smoothstep", animated: edge.animated, style: edge.style };
  const incoming = {
    ...base,
    id: `${edge.id}-in`,
    source: edge.source,
    target: node.id,
    label: condition,
    data: { ...(edge.data || {}), condition },
  };
  const outgoing = {
    ...base,
    id: `${edge.id}-out`,
    source: node.id,
    target: edge.target,
    label: "",
    data: { ...(edge.data || {}), condition: "" },
  };
  return {
    nodes: [...nodes, clone(node)],
    edges: edges.flatMap((candidate) => candidate.id === edgeId ? [incoming, outgoing] : [candidate]),
  };
}

export function validateNodeConfig(node, workflowTarget = "") {
  const type = node?.data?.nodeType || node?.type;
  const config = node?.data?.config || node?.config || {};
  const errors = [];
  if (TARGET_SESSION_NODE_TYPES.has(type) && !getNodeTarget(node, workflowTarget)) errors.push("目标会话不能为空");
  if (type === "telegram.send_message" && !String(config.text || "").trim()) errors.push("消息内容不能为空");
  if (type === "telegram.wait_message" || type === "telegram.read_messages") {
    if (!Number.isInteger(config.limit) || config.limit < 1) errors.push("读取条数必须是正整数");
  }
  if (type === "telegram.click_button" && !String(config.match?.value ?? "").trim()) errors.push("按钮匹配值不能为空");
  if (type === "set_variable" && !/^[A-Za-z_][A-Za-z0-9_]*$/.test(String(config.name || ""))) errors.push("变量名必须是安全标识符");
  if (type === "condition" && !String(config.expression || "").trim()) errors.push("条件表达式不能为空");
  if (type === "delay" && (!Number.isFinite(Number(config.seconds)) || Number(config.seconds) < 0)) errors.push("等待秒数必须是非负数");
  return errors;
}

export function runExecutionState(run) {
  const status = typeof run === "string" ? run : run?.status;
  if (status === "waiting") return "waiting";
  if (status === "queued" || status === "running") return "running";
  if (status === "success" || status === "failed") return status;
  return "idle";
}

export function nodeExecutionStates(nodes, run) {
  const states = Object.fromEntries(nodes.map((node) => [node.id, "idle"]));
  if (!run) return states;
  Object.keys(run.node_outputs || {}).forEach((nodeId) => {
    if (nodeId in states) states[nodeId] = "success";
  });
  const activeNodeId = run.current_node_id;
  if (run.status === "failed") {
    const failedNodeId = run.error?.node_id || activeNodeId;
    if (failedNodeId in states) states[failedNodeId] = "failed";
  } else if ((run.status === "waiting" || run.status === "queued" || run.status === "running") && activeNodeId && activeNodeId in states) {
    states[activeNodeId] = run.status === "waiting" ? "waiting" : "running";
  }
  return states;
}
