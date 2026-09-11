import assert from "node:assert/strict";
import test from "node:test";

import {
  documentToFlow,
  duplicateWorkflowDocument,
  flowToDocument,
  normalizeWorkflowDocument,
  nodeExecutionStates,
  insertNodeOnEdge,
  removeSelectedElement,
  runExecutionState,
  validateConnection,
  validateNodeConfig,
} from "../src/flowModel.js";

const document = {
  version: 1,
  workflow: { id: "daily", name: "Daily", enabled: true, account: "main" },
  triggers: [{ type: "manual" }],
  nodes: [
    { id: "send", type: "telegram.send_message", config: { target: "@bot", text: "/start" } },
    { id: "check", type: "condition", config: { expression: "variables.ok == true" } },
    { id: "end", type: "end", config: {} },
  ],
  edges: [
    { from: "send", to: "check" },
    { from: "check", to: "end", condition: "variables.ok == true" },
  ],
  ui: {
    viewport: { x: -42, y: 18, zoom: 0.86 },
    nodes: {
      send: { x: 120, y: 90 },
      check: { x: 430, y: 90 },
      end: { x: 760, y: 90 },
    },
  },
};

test("documentToFlow restores the saved canvas layout", () => {
  const flow = documentToFlow(document);

  assert.deepEqual(flow.nodes.map((node) => node.position), [
    { x: 120, y: 90 },
    { x: 430, y: 90 },
    { x: 760, y: 90 },
  ]);
  assert.deepEqual(flow.edges[1].data, { condition: "variables.ok == true" });
});

test("flowToDocument persists node positions and the viewport", () => {
  const flow = documentToFlow(document);
  flow.nodes[1].position = { x: 512.4, y: 133.8 };

  const next = flowToDocument(flow.nodes, flow.edges, document.workflow, document.triggers, {
    ...document.ui,
    viewport: { x: -10, y: 24, zoom: 1.1 },
  });

  assert.deepEqual(next.ui, {
    viewport: { x: -10, y: 24, zoom: 1.1 },
    nodes: {
      send: { x: 120, y: 90 },
      check: { x: 512, y: 134 },
      end: { x: 760, y: 90 },
    },
  });
});

test("removeSelectedElement removes only the selected edge", () => {
  const flow = documentToFlow(document);
  const next = removeSelectedElement(flow.nodes, flow.edges, { kind: "edge", id: flow.edges[1].id });

  assert.equal(next.nodes.length, 3);
  assert.equal(next.edges.length, 1);
  assert.equal(next.edges[0].source, "send");
});

test("validateConnection rejects self links and duplicate links", () => {
  const flow = documentToFlow(document);

  assert.deepEqual(validateConnection({ source: "send", target: "send" }, flow.edges), {
    valid: false,
    reason: "不能连接节点自身",
  });
  assert.deepEqual(validateConnection({ source: "send", target: "check" }, flow.edges), {
    valid: false,
    reason: "这两个节点之间已经存在连线",
  });
});

test("insertNodeOnEdge preserves the branch condition on the incoming edge", () => {
  const flow = documentToFlow(document);
  const next = insertNodeOnEdge(flow.nodes, flow.edges, flow.edges[1].id, {
    id: "delay-1",
    type: "workflow",
    position: { x: 600, y: 90 },
    data: { nodeType: "delay", config: { seconds: 2 }, label: "delay-1" },
  });

  assert.deepEqual(next.edges.map((edge) => [edge.source, edge.target, edge.data?.condition || ""]), [
    ["send", "check", ""],
    ["check", "delay-1", "variables.ok == true"],
    ["delay-1", "end", ""],
  ]);
});

test("validateNodeConfig reports required Telegram values", () => {
  assert.deepEqual(validateNodeConfig({
    data: { nodeType: "telegram.send_message", config: { target: "", text: "" } },
  }), ["目标会话不能为空", "消息内容不能为空"]);
});

test("validateNodeConfig accepts a workflow-level target session", () => {
  assert.deepEqual(validateNodeConfig({
    data: { nodeType: "telegram.send_message", config: { text: "/start" } },
  }, "@shared_chat"), []);
});

test("normalizeWorkflowDocument promotes one shared node target to workflow metadata", () => {
  const documentWithRepeatedTargets = {
    ...document,
    workflow: { ...document.workflow },
    nodes: document.nodes.map((node) => node.type.startsWith("telegram.")
      ? { ...node, config: { ...node.config, target: "@shared_chat" } }
      : node),
  };

  const normalized = normalizeWorkflowDocument(documentWithRepeatedTargets);

  assert.equal(normalized.workflow.target, "@shared_chat");
  assert.equal(documentWithRepeatedTargets.workflow.target, undefined);
});

test("duplicateWorkflowDocument changes only workflow identity and deep clones the flow", () => {
  const duplicated = duplicateWorkflowDocument(document, "daily-copy", "Daily 副本");

  assert.deepEqual(duplicated.workflow, { ...document.workflow, id: "daily-copy", name: "Daily 副本" });
  assert.deepEqual(duplicated.nodes, document.nodes);
  assert.deepEqual(duplicated.edges, document.edges);
  assert.notEqual(duplicated.nodes, document.nodes);
  duplicated.nodes[0].config.target = "@other";
  assert.equal(document.nodes[0].config.target, "@bot");
});

test("run status maps waiting to the active next node without marking it failed", () => {
  const nodes = documentToFlow(document).nodes;
  const run = {
    status: "waiting",
    current_node_id: "check",
    node_outputs: { send: { message_id: 1 } },
    waiting: { kind: "action_barrier", node_id: "send" },
  };

  assert.equal(runExecutionState(run), "waiting");
  assert.deepEqual(nodeExecutionStates(nodes, run), { send: "success", check: "waiting", end: "idle" });
});

test("run status marks only the failed node and preserves completed steps", () => {
  const nodes = documentToFlow(document).nodes;
  const run = {
    status: "failed",
    current_node_id: "check",
    node_outputs: { send: { message_id: 1 } },
    error: { node_id: "check", message: "failed" },
  };

  assert.deepEqual(nodeExecutionStates(nodes, run), { send: "success", check: "failed", end: "idle" });
});
