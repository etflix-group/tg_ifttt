import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { addEdge, applyEdgeChanges, applyNodeChanges, reconnectEdge, useReactFlow } from "@xyflow/react";
import yaml from "js-yaml";
import {
  ArrowRight,
  ArrowUUpLeft,
  ArrowUUpRight,
  BracketsCurly,
  Broadcast,
  Check,
  CheckCircle,
  CircleNotch,
  Copy,
  DownloadSimple,
  Gear,
  GitBranch,
  Key,
  Lightning,
  LockKey,
  PlayCircle,
  Plus,
  PlugsConnected,
  Trash,
  UploadSimple,
  WarningCircle,
  X,
} from "@phosphor-icons/react";

import { WorkflowCanvas } from "./WorkflowCanvas.jsx";
import { WorkflowEdge } from "./WorkflowEdge.jsx";
import { Field, ScheduleConfig, TextInput } from "./WorkflowInspector.jsx";
import { WorkflowNode } from "./WorkflowNode.jsx";
import { documentToFlow, duplicateWorkflowDocument, flowToDocument, insertNodeOnEdge, nodeExecutionStates, normalizeWorkflowDocument, removeSelectedElements, renameFlowNode, runExecutionState, TARGET_SESSION_NODE_TYPES, validateConnection, validateNodeConfig } from "./flowModel.js";
import { clone, defaultConfig, EMPTY_WORKFLOW, libraryEntry, NODE_LIBRARY } from "./nodeLibrary.js";
import { createHistory, redoHistory, recordHistory, undoHistory } from "./workflowHistory.js";

const DRAFT_KEY = "tg-ifttt.workflow.draft";
const TERMINAL_RUN_STATUSES = new Set(["success", "failed", "cancelled", "timeout", "needs_review"]);
const RUN_STATUS_LABELS = { queued: "排队中", running: "运行中", waiting: "等待事件", success: "已完成", failed: "失败", cancelled: "已取消", timeout: "已超时", needs_review: "需检查" };

function runStatusLabel(status) {
  return RUN_STATUS_LABELS[status] || "未运行";
}

function edgeExecutionState(edge, nodeStates) {
  const source = nodeStates[edge.source];
  const target = nodeStates[edge.target];
  if (target === "failed") return "failed";
  if (target === "waiting") return "waiting";
  if (target === "running") return "running";
  if (source === "success" && target === "success") return "success";
  return "idle";
}

function readDraft() {
  try { return normalizeWorkflowDocument(JSON.parse(localStorage.getItem(DRAFT_KEY)) || clone(EMPTY_WORKFLOW)); } catch { return clone(EMPTY_WORKFLOW); }
}

function uniqueNodeId(type, nodes) {
  const base = type.replace("telegram.", "").replaceAll("_", "-");
  const stamp = Date.now().toString(36).slice(-5);
  let id = `${base}-${stamp}`;
  let suffix = 2;
  while (nodes.some((node) => node.id === id)) id = `${base}-${stamp}-${suffix++}`;
  return id;
}

function edgeId() {
  return `edge-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}

function uniqueWorkflowId(sourceId, workflows) {
  const used = new Set(workflows.map((workflow) => workflow.workflow_id));
  let nextId = `${sourceId}-copy`;
  let suffix = 2;
  while (used.has(nextId)) nextId = `${sourceId}-copy-${suffix++}`;
  return nextId;
}

function WorkflowEditor({
  document,
  accounts,
  nodes,
  edges,
  selectedNode,
  selectedEdge,
  selectionCount,
  canonicalDocument,
  mode,
  setMode,
  paletteFilter,
  setPaletteFilter,
  visiblePalette,
  loading,
  setImportText,
  setImportFormat,
  setDrawer,
  run,
  canvasRef,
  onDrop,
  addNodeFromPalette,
  clearSelection,
  setFlowInstance,
  canvasNodes,
  canvasEdges,
  nodeTypes,
  edgeTypes,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onReconnect,
  isValidConnection,
  onNodeDragStart,
  onNodeDragStop,
  selectNode,
  selectEdge,
  onNodeContextMenu,
  onEdgeContextMenu,
  onPaneContextMenu,
  closeContextMenu,
  onMoveEnd,
  zoom,
  zoomIn,
  zoomOut,
  resetZoom,
  fitView,
  showMinimap,
  setShowMinimap,
  updateSelectedConfig,
  renameSelected,
  deleteSelected,
  updateSelectedEdge,
  pendingAdd,
  setPendingAdd,
  commandPaletteOpen,
  setCommandPaletteOpen,
  commands,
  contextMenu,
  contextActions,
  canUndo,
  canRedo,
  setDocument,
  onScheduleChange,
  executionState,
}) {
  const executionLabel = { idle: "未运行", running: "运行中", waiting: "等待事件", success: "最近成功", failed: "最近失败" }[executionState] || "未运行";
  return <main className="editor-main">
    <section className="editor-header"><div><span className="eyebrow">VISUAL ORCHESTRATOR / 01</span><h1>{document.workflow.name}</h1><p>像 n8n 一样拖拽节点、连接路径；保存后位置和流程一起恢复。</p></div><div className="editor-header-actions"><div className={`execution-pill ${executionState}`}><span className="status-dot" />{executionLabel}</div><button type="button" className="outline-button" onClick={() => { setImportText(yaml.dump(canonicalDocument, { noRefs: true, lineWidth: -1 })); setImportFormat("yaml"); setDrawer("import"); }}><BracketsCurly size={17} />配置文件</button><button type="button" className="primary-button" onClick={run} disabled={loading}><PlayCircle size={17} />手动运行</button></div></section>
    <section className="meta-strip"><Field label="流程名称"><TextInput value={document.workflow.name} onChange={(value) => setDocument((current) => ({ ...current, workflow: { ...current.workflow, name: value } }))} /></Field><Field label="流程 ID"><TextInput value={document.workflow.id} mono onChange={(value) => setDocument((current) => ({ ...current, workflow: { ...current.workflow, id: value } }))} /></Field><Field label="默认目标会话" hint="Telegram 节点默认继承；节点可单独覆盖"><TextInput value={document.workflow.target || ""} mono placeholder="@bot 或 numeric peer" onChange={(value) => setDocument((current) => ({ ...current, workflow: { ...current.workflow, target: value } }))} /></Field><Field label="执行账号" hint="每条流程可独立选择账号"><select className="select" value={document.workflow.account || ""} onChange={(event) => setDocument((current) => ({ ...current, workflow: { ...current.workflow, account: event.target.value } }))}><option value="">未选择 / 由运行请求指定</option>{accounts.map((account) => <option key={account.account_id} value={account.account_id}>{account.display_name} · {account.account_id}</option>)}</select></Field><div className="meta-status"><span className="status-dot live" />已启用<span className="divider" />v{document.version}</div></section>
    <ScheduleConfig triggers={document.triggers} onChange={onScheduleChange} />
    <WorkflowCanvas document={document} nodes={nodes} edges={edges} selectedNode={selectedNode} selectedEdge={selectedEdge} selectionCount={selectionCount} canonicalDocument={canonicalDocument} mode={mode} setMode={setMode} paletteFilter={paletteFilter} setPaletteFilter={setPaletteFilter} visiblePalette={visiblePalette} setImportText={setImportText} setImportFormat={setImportFormat} canvasRef={canvasRef} onDrop={onDrop} addNodeFromPalette={addNodeFromPalette} clearSelection={clearSelection} setFlowInstance={setFlowInstance} canvasNodes={canvasNodes} canvasEdges={canvasEdges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} onReconnect={onReconnect} isValidConnection={isValidConnection} onNodeDragStart={onNodeDragStart} onNodeDragStop={onNodeDragStop} selectNode={selectNode} selectEdge={selectEdge} onNodeContextMenu={onNodeContextMenu} onEdgeContextMenu={onEdgeContextMenu} onPaneContextMenu={onPaneContextMenu} closeContextMenu={closeContextMenu} onMoveEnd={onMoveEnd} zoom={zoom} zoomIn={zoomIn} zoomOut={zoomOut} resetZoom={resetZoom} fitView={fitView} showMinimap={showMinimap} setShowMinimap={setShowMinimap} updateSelectedConfig={updateSelectedConfig} renameSelected={renameSelected} deleteSelected={deleteSelected} updateSelectedEdge={updateSelectedEdge} pendingAdd={pendingAdd} setPendingAdd={setPendingAdd} commandPaletteOpen={commandPaletteOpen} setCommandPaletteOpen={setCommandPaletteOpen} commands={commands} contextMenu={contextMenu} contextActions={contextActions} canUndo={canUndo} canRedo={canRedo} />
  </main>;
}

function LoginPanel({ onAuthenticated }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault(); setError("");
    try { const response = await fetch("/api/capabilities", { headers: { Authorization: `Bearer ${token}` } }); if (!response.ok) throw new Error("令牌无效，或服务尚未启动"); onAuthenticated(token); }
    catch (caught) { setError(caught.message); }
  };
  return <div className="login-shell"><div className="login-mark"><Lightning size={26} weight="fill" /></div><span className="eyebrow">PRIVATE CONTROL PLANE</span><h1>把 Telegram 动作<br /><em>连成一条可靠的线。</em></h1><p>单用户自部署控制台。会话、流程版本和运行检查点都保存在你的数据卷里。</p><form onSubmit={submit} className="login-form"><Field label="管理令牌" hint="不会写入浏览器本地存储"><div className="input-with-icon"><LockKey size={16} /><input className="input" type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder="TG_IFTTT_ADMIN_TOKEN" /></div></Field><button type="submit" className="primary-button wide"><Key size={17} />进入控制台<ArrowRight size={17} /></button>{error ? <div className="error-banner"><WarningCircle size={18} />{error}</div> : null}</form><div className="login-foot"><span><span className="status-dot live" />本地 API 等待连接</span><span>v0.1 / single user</span></div></div>;
}

function App() {
  const initialDocumentRef = useRef(null);
  if (!initialDocumentRef.current) initialDocumentRef.current = readDraft();
  const initialDocument = initialDocumentRef.current;
  const [token, setToken] = useState("");
  const [activeView, setActiveView] = useState("editor");
  const [document, setDocument] = useState(initialDocument);
  const [history, setHistory] = useState(() => createHistory(documentToFlow(initialDocument)));
  const [selectedNodeIds, setSelectedNodeIds] = useState(history.present.nodes[0]?.id ? [history.present.nodes[0].id] : []);
  const [selectedEdgeId, setSelectedEdgeId] = useState(null);
  const [workflows, setWorkflows] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [runs, setRuns] = useState([]);
  const [mode, setMode] = useState("canvas");
  const [paletteFilter, setPaletteFilter] = useState("");
  const [importText, setImportText] = useState("");
  const [importFormat, setImportFormat] = useState("yaml");
  const [drawer, setDrawer] = useState(null);
  const [notice, setNotice] = useState({ kind: "", text: "" });
  const [loading, setLoading] = useState(false);
  const [executionState, setExecutionState] = useState("idle");
  const [trackedRunId, setTrackedRunId] = useState(null);
  const [flowInstance, setFlowInstance] = useState(null);
  const [showMinimap, setShowMinimap] = useState(true);
  const [zoom, setZoom] = useState(initialDocument.ui?.viewport?.zoom || 1);
  const [pendingAdd, setPendingAdd] = useState(null);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [contextMenu, setContextMenu] = useState(null);
  const [clipboard, setClipboard] = useState(null);
  const clipboardRef = useRef(null);
  const canvasRef = useRef(null);
  const flowRef = useRef(history.present);
  const dragSnapshotRef = useRef(null);
  const { fitView, zoomIn, zoomOut, setViewport } = useReactFlow();
  const flow = history.present;
  flowRef.current = flow;
  const nodes = flow.nodes;
  const edges = flow.edges;
  const latestRun = useMemo(() => runs.find((run) => run.workflow_id === document.workflow.id) || null, [document.workflow.id, runs]);
  const selectedNode = nodes.find((node) => node.id === selectedNodeIds.at(-1)) || null;
  const selectedEdge = edges.find((edge) => edge.id === selectedEdgeId) || null;
  const visiblePalette = useMemo(() => { const query = paletteFilter.trim().toLowerCase(); return query ? NODE_LIBRARY.filter((entry) => `${entry.label} ${entry.type} ${entry.hint}`.toLowerCase().includes(query)) : NODE_LIBRARY; }, [paletteFilter]);
  const nodeTypes = useMemo(() => ({ workflow: WorkflowNode }), []);
  const edgeTypes = useMemo(() => ({ workflowEdge: WorkflowEdge }), []);
  const canonicalDocument = useMemo(() => flowToDocument(nodes, edges, document.workflow, document.triggers, document.ui), [document.triggers, document.ui, document.workflow, edges, nodes]);
  const canUndo = history.past.length > 0;
  const canRedo = history.future.length > 0;

  const authHeaders = useCallback(() => ({ Authorization: `Bearer ${token}`, "Content-Type": "application/json" }), [token]);
  const request = useCallback(async (path, options = {}) => { const response = await fetch(path, { ...options, headers: { ...authHeaders(), ...(options.headers || {}) } }); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(Array.isArray(body.detail) ? body.detail.join("; ") : body.detail || `请求失败 (${response.status})`); return body; }, [authHeaders]);
  useEffect(() => { window.__tgIftttRequest = request; return () => { delete window.__tgIftttRequest; }; }, [request]);
  const refreshData = useCallback(async () => { if (!token) return; try { const [workflowList, accountList, runList] = await Promise.all([request("/api/workflows"), request("/api/accounts").catch(() => []), request("/api/runs?limit=12")]); setWorkflows(workflowList); setAccounts(accountList); setRuns(runList); } catch (error) { setNotice({ kind: "error", text: error.message }); } }, [request, token]);
  useEffect(() => { if (token) refreshData(); }, [refreshData, token]);
  useEffect(() => { if (!loading && !trackedRunId) setExecutionState(runExecutionState(latestRun)); }, [latestRun, loading, trackedRunId]);
  useEffect(() => { if (!loading && !trackedRunId && latestRun && ["queued", "running", "waiting"].includes(latestRun.status)) setTrackedRunId(latestRun.run_id); }, [latestRun, loading, trackedRunId]);
  useEffect(() => {
    if (!token || !trackedRunId) return undefined;
    let cancelled = false;
    const syncRun = async () => {
      try {
        const next = await request(`/api/runs/${encodeURIComponent(trackedRunId)}`);
        if (cancelled) return;
        setRuns((current) => {
          const index = current.findIndex((run) => run.run_id === next.run_id);
          if (index < 0) return [next, ...current].slice(0, 12);
          return current.map((run, currentIndex) => currentIndex === index ? next : run);
        });
        setExecutionState(runExecutionState(next));
        if (TERMINAL_RUN_STATUSES.has(next.status)) {
          setTrackedRunId(null);
          const detail = next.error?.message;
          setNotice({ kind: next.status === "success" ? "success" : "error", text: `运行 ${next.run_id.slice(0, 8)}：${runStatusLabel(next.status)}${detail ? `：${detail}` : ""}` });
        }
      } catch (error) {
        if (!cancelled) setNotice({ kind: "error", text: `运行状态同步失败：${error.message}` });
      }
    };
    syncRun();
    const timer = setInterval(syncRun, 1000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [request, token, trackedRunId]);
  useEffect(() => { try { localStorage.setItem(DRAFT_KEY, JSON.stringify(canonicalDocument)); } catch { /* private browsing */ } }, [canonicalDocument]);
  useEffect(() => { if (notice.text) { const timer = setTimeout(() => setNotice({ kind: "", text: "" }), 4200); return () => clearTimeout(timer); } }, [notice]);
  useEffect(() => { if (!flowInstance) return; const viewport = document.ui?.viewport || { x: 0, y: 0, zoom: 1 }; setViewport(viewport, { duration: 0 }); setZoom(viewport.zoom || 1); }, [document.workflow.id, flowInstance, setViewport]);

  const updatePresent = useCallback((updater) => setHistory((current) => ({ ...current, present: updater(current.present) })), []);
  const commitFlow = useCallback((updater, previous = null) => setHistory((current) => { const next = updater(current.present); return recordHistory(current, next, previous || current.present); }), []);
  const resetSelection = useCallback(() => { setSelectedNodeIds([]); setSelectedEdgeId(null); }, []);
  const selectNode = useCallback((nodeId, event = {}) => { const additive = event.shiftKey || event.metaKey || event.ctrlKey; setSelectedNodeIds((current) => additive ? (current.includes(nodeId) ? current.filter((id) => id !== nodeId) : [...current, nodeId]) : [nodeId]); setSelectedEdgeId(null); setContextMenu(null); }, []);
  const selectEdge = useCallback((edgeValue) => { setSelectedEdgeId(edgeValue); setSelectedNodeIds([]); setContextMenu(null); }, []);
  const clearSelection = useCallback(() => { resetSelection(); setContextMenu(null); setPendingAdd(null); }, [resetSelection]);
  const loadDocument = useCallback((loaded) => { const nextDocument = normalizeWorkflowDocument(loaded); setDocument(nextDocument); setHistory(createHistory(documentToFlow(nextDocument))); setSelectedNodeIds(nextDocument.nodes[0]?.id ? [nextDocument.nodes[0].id] : []); setSelectedEdgeId(null); setZoom(nextDocument.ui?.viewport?.zoom || 1); setExecutionState("idle"); setTrackedRunId(null); setPendingAdd(null); }, []);
  const updateSelectedConfig = useCallback((config) => { const nodeId = selectedNodeIds.length === 1 ? selectedNodeIds[0] : null; if (!nodeId) return; commitFlow((current) => ({ ...current, nodes: current.nodes.map((node) => node.id === nodeId ? { ...node, data: { ...node.data, config } } : node) })); }, [commitFlow, selectedNodeIds]);
  const renameSelected = useCallback((name) => { const nodeId = selectedNodeIds.length === 1 ? selectedNodeIds[0] : null; if (!nodeId || typeof name !== "string") return; commitFlow((current) => ({ ...current, nodes: renameFlowNode(current.nodes, nodeId, name) })); }, [commitFlow, selectedNodeIds]);
  const deleteSelected = useCallback(() => { if (!selectedNodeIds.length && !selectedEdgeId) return; commitFlow((current) => removeSelectedElements(current.nodes, current.edges, { nodeIds: selectedNodeIds, edgeId: selectedEdgeId })); resetSelection(); }, [commitFlow, resetSelection, selectedEdgeId, selectedNodeIds]);
  const deleteNodeById = useCallback((nodeId) => { commitFlow((current) => removeSelectedElements(current.nodes, current.edges, { nodeIds: [nodeId] })); setSelectedNodeIds((current) => current.filter((id) => id !== nodeId)); setSelectedEdgeId(null); }, [commitFlow]);
  const deleteEdgeById = useCallback((edgeValue) => { commitFlow((current) => removeSelectedElements(current.nodes, current.edges, { edgeId: edgeValue })); setSelectedEdgeId((current) => current === edgeValue ? null : current); }, [commitFlow]);
  const updateSelectedEdge = useCallback((condition) => { if (!selectedEdgeId) return; commitFlow((current) => ({ ...current, edges: current.edges.map((edge) => edge.id === selectedEdgeId ? { ...edge, label: condition, data: { ...(edge.data || {}), condition } } : edge) })); }, [commitFlow, selectedEdgeId]);
  const copyNodes = useCallback((ids, announce = true) => { const selected = nodes.filter((node) => ids.includes(node.id)); if (!selected.length) return false; const idSet = new Set(ids); const nextClipboard = { nodes: clone(selected), edges: clone(edges.filter((edge) => idSet.has(edge.source) && idSet.has(edge.target))) }; clipboardRef.current = nextClipboard; setClipboard(nextClipboard); if (announce) setNotice({ kind: "success", text: `已复制 ${selected.length} 个节点` }); return true; }, [edges, nodes]);
  const pasteNodes = useCallback(() => { const source = clipboardRef.current || clipboard; if (!source?.nodes?.length) return; const used = new Set(nodes.map((node) => node.id)); const idMap = new Map(); const pastedNodes = source.nodes.map((node) => { let nextId = `${node.id}-copy`; let suffix = 2; while (used.has(nextId)) nextId = `${node.id}-copy-${suffix++}`; used.add(nextId); idMap.set(node.id, nextId); return { ...clone(node), id: nextId, position: { x: (node.position?.x || 0) + 48, y: (node.position?.y || 0) + 48 }, data: { ...clone(node.data), label: typeof node.data?.label === "string" ? node.data.label : libraryEntry(node.data?.nodeType).label } }; }); const pastedEdges = source.edges.map((edge) => ({ ...clone(edge), id: edgeId(), source: idMap.get(edge.source), target: idMap.get(edge.target) })); commitFlow((current) => ({ nodes: [...current.nodes, ...pastedNodes], edges: [...current.edges, ...pastedEdges] })); setSelectedNodeIds(pastedNodes.map((node) => node.id)); setSelectedEdgeId(null); setNotice({ kind: "success", text: `已粘贴 ${pastedNodes.length} 个节点` }); }, [clipboard, commitFlow, nodes]);
  const duplicateNode = useCallback((nodeId) => { if (copyNodes([nodeId], false)) pasteNodes(); }, [copyNodes, pasteNodes]);
  const addNode = useCallback((type, position, sourceId = null, replaceEdgeId = null) => { const nodeId = uniqueNodeId(type, flow.nodes); const config = defaultConfig(type); if (document.workflow.target && TARGET_SESSION_NODE_TYPES.has(type)) delete config.target; const node = { id: nodeId, type: "workflow", position: { x: Math.round(position.x), y: Math.round(position.y) }, data: { nodeType: type, config, label: libraryEntry(type).label } }; let next = { nodes: [...flow.nodes, node], edges: flow.edges }; if (replaceEdgeId) next = insertNodeOnEdge(flow.nodes, flow.edges, replaceEdgeId, node); else if (sourceId) next.edges = addEdge({ id: edgeId(), source: sourceId, target: node.id, type: "workflowEdge", label: "", data: { condition: "" } }, flow.edges); commitFlow(() => next); setSelectedNodeIds([node.id]); setSelectedEdgeId(null); setPendingAdd(null); }, [commitFlow, document.workflow.target, flow]);
  const addNodeFromPalette = useCallback((type) => { if (pendingAdd?.sourceId) { const source = nodes.find((node) => node.id === pendingAdd.sourceId); if (source) return addNode(type, { x: source.position.x + 300, y: source.position.y }, source.id); } if (pendingAdd?.edgeId) { const edge = edges.find((candidate) => candidate.id === pendingAdd.edgeId); const source = edge && nodes.find((node) => node.id === edge.source); const target = edge && nodes.find((node) => node.id === edge.target); if (edge && source && target) return addNode(type, { x: (source.position.x + target.position.x) / 2, y: (source.position.y + target.position.y) / 2 }, null, edge.id); } if (!flowInstance || !canvasRef.current) return addNode(type, { x: 220, y: 120 }); const bounds = canvasRef.current.getBoundingClientRect(); addNode(type, flowInstance.screenToFlowPosition({ x: bounds.left + bounds.width / 2 - 100, y: bounds.top + bounds.height / 2 - 40 })); }, [addNode, edges, flowInstance, nodes, pendingAdd]);
  const onDrop = useCallback((event) => { event.preventDefault(); const type = event.dataTransfer.getData("application/tg-ifttt-node"); if (type && flowInstance) addNode(type, flowInstance.screenToFlowPosition({ x: event.clientX, y: event.clientY })); }, [addNode, flowInstance]);
  const onNodesChange = useCallback((changes) => { updatePresent((current) => ({ ...current, nodes: applyNodeChanges(changes.filter((change) => change.type !== "select"), current.nodes) })); const removed = new Set(changes.filter((change) => change.type === "remove").map((change) => change.id)); if (removed.size) setSelectedNodeIds((current) => current.filter((id) => !removed.has(id))); }, [updatePresent]);
  const onEdgesChange = useCallback((changes) => { updatePresent((current) => ({ ...current, edges: applyEdgeChanges(changes.filter((change) => change.type !== "select"), current.edges) })); if (changes.some((change) => change.type === "remove" && change.id === selectedEdgeId)) setSelectedEdgeId(null); }, [selectedEdgeId, updatePresent]);
  const onConnect = useCallback((connection) => { const result = validateConnection(connection, edges); if (!result.valid) return setNotice({ kind: "error", text: result.reason }); const nextEdge = { ...connection, id: edgeId(), type: "workflowEdge", label: "", data: { condition: "" } }; commitFlow((current) => ({ ...current, edges: addEdge(nextEdge, current.edges) })); selectEdge(nextEdge.id); }, [commitFlow, edges, selectEdge]);
  const isValidConnection = useCallback((connection) => validateConnection(connection, flowRef.current.edges).valid, []);
  const onReconnect = useCallback((oldEdge, connection) => { const result = validateConnection(connection, edges, oldEdge.id); if (!result.valid) return setNotice({ kind: "error", text: result.reason }); commitFlow((current) => { const original = current.edges.find((edge) => edge.id === oldEdge.id); return original ? { ...current, edges: reconnectEdge(original, connection, current.edges, { shouldReplaceId: false }) } : current; }); }, [commitFlow, edges]);
  const onNodeDragStart = useCallback(() => { dragSnapshotRef.current = clone(flowRef.current); }, []);
  const onNodeDragStop = useCallback(() => { if (dragSnapshotRef.current) setHistory((current) => recordHistory(current, current.present, dragSnapshotRef.current)); dragSnapshotRef.current = null; }, []);
  const onMoveEnd = useCallback((_, viewport) => { setZoom(viewport.zoom); setDocument((current) => ({ ...current, ui: { ...(current.ui || {}), viewport } })); }, []);
  const resetZoom = useCallback(() => { const viewport = { x: 0, y: 0, zoom: 1 }; setViewport(viewport, { duration: 220 }); setZoom(1); setDocument((current) => ({ ...current, ui: { ...(current.ui || {}), viewport } })); }, [setViewport]);
  const openNodePickerAfter = useCallback((nodeId) => setPendingAdd({ sourceId: nodeId, edgeId: null }), []);
  const openNodePickerOnEdge = useCallback((edgeValue) => setPendingAdd({ sourceId: null, edgeId: edgeValue }), []);
  const executeNode = useCallback((nodeId) => { selectNode(nodeId); setNotice({ kind: "success", text: "当前 API 只支持运行整条流程；已选中该节点供检查器编辑" }); }, [selectNode]);
  const save = useCallback(async () => { const errors = nodes.flatMap((node) => validateNodeConfig(node, document.workflow.target).map((error) => `${node.id}：${error}`)); if (errors.length) return setNotice({ kind: "error", text: `请先修正：${errors[0]}` }); setLoading(true); try { const saved = await request(`/api/workflows/${encodeURIComponent(canonicalDocument.workflow.id)}`, { method: "PUT", body: JSON.stringify(canonicalDocument) }); setDocument(canonicalDocument); setNotice({ kind: "success", text: `已保存版本 ${saved.version_id}` }); await refreshData(); } catch (error) { setNotice({ kind: "error", text: error.message }); } finally { setLoading(false); } }, [canonicalDocument, document.workflow.target, nodes, refreshData, request]);
  const run = useCallback(async () => { setLoading(true); setTrackedRunId(null); setExecutionState("running"); try { const result = await request(`/api/workflows/${encodeURIComponent(canonicalDocument.workflow.id)}/run`, { method: "POST", body: JSON.stringify({ account_id: canonicalDocument.workflow.account, trigger_payload: { source: "console" } }) }); const runRecord = result.run || {}; const state = runExecutionState(runRecord.status || result.result); setExecutionState(state); if (runRecord.run_id && !TERMINAL_RUN_STATUSES.has(runRecord.status)) setTrackedRunId(runRecord.run_id); const detail = runRecord.error?.message; const text = state === "waiting" ? `运行 ${runRecord.run_id.slice(0, 8)}：等待 Telegram 事件` : `运行 ${runRecord.run_id.slice(0, 8)}：${runStatusLabel(runRecord.status || result.result)}${detail ? `：${detail}` : ""}`; setNotice({ kind: state === "failed" ? "error" : state === "waiting" ? "info" : "success", text }); await refreshData(); } catch (error) { setTrackedRunId(null); setExecutionState("failed"); setNotice({ kind: "error", text: error.message }); } finally { setLoading(false); } }, [canonicalDocument, refreshData, request]);
  const openNodeRed = useCallback(async () => { window.open("/nodered/", "_blank", "noopener,noreferrer"); setLoading(true); try { const result = await request(`/api/workflows/${encodeURIComponent(canonicalDocument.workflow.id)}/nodered`); const text = JSON.stringify(result.flow, null, 2); setImportText(text); setImportFormat("json"); setDrawer("nodered"); let copied = false; try { if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); copied = true; } } catch { /* clipboard permission is optional */ } setNotice({ kind: "success", text: copied ? "Node-RED Flow 已复制；在编辑器中使用 Import 粘贴。" : "Node-RED Flow 已准备好；在弹窗中复制后使用 Import。" }); } catch (error) { setNotice({ kind: "error", text: error.message }); } finally { setLoading(false); } }, [canonicalDocument.workflow.id, request]);
  const copyNodeRed = useCallback(async () => { try { await navigator.clipboard.writeText(importText); setNotice({ kind: "success", text: "Node-RED Flow 已复制到剪贴板。" }); } catch (error) { setNotice({ kind: "error", text: `复制失败：${error.message}` }); } }, [importText]);
  const syncNodeRed = useCallback(async () => { setLoading(true); try { const flowDocument = JSON.parse(importText); const saved = await request(`/api/workflows/${encodeURIComponent(canonicalDocument.workflow.id)}/nodered`, { method: "PUT", body: JSON.stringify({ flow: flowDocument }) }); loadDocument(saved.document); setDrawer(null); setNotice({ kind: "success", text: `Node-RED Flow 已同步，保存版本 ${saved.version_id}` }); await refreshData(); } catch (error) { setNotice({ kind: "error", text: `同步失败：${error.message}` }); } finally { setLoading(false); } }, [canonicalDocument.workflow.id, importText, loadDocument, refreshData, request]);
  const duplicateWorkflow = useCallback(async (workflowId = document.workflow.id) => { setLoading(true); try { const source = workflowId === canonicalDocument.workflow.id ? canonicalDocument : await request(`/api/workflows/${encodeURIComponent(workflowId)}`); const nextId = uniqueWorkflowId(source.workflow.id, workflows); const next = duplicateWorkflowDocument(source, nextId, `${source.workflow.name} 副本`); const saved = await request("/api/workflows", { method: "POST", body: JSON.stringify(next) }); loadDocument(saved.document); await refreshData(); setNotice({ kind: "success", text: `已复制流程：${saved.document.workflow.name}` }); } catch (error) { setNotice({ kind: "error", text: `复制失败：${error.message}` }); } finally { setLoading(false); } }, [canonicalDocument, document.workflow.id, loadDocument, refreshData, request, workflows]);
  const deleteWorkflow = useCallback(async (workflowId) => { const item = workflows.find((workflow) => workflow.workflow_id === workflowId); if (!item || !window.confirm(`确定删除流程“${item.name}”吗？此操作不会删除运行记录。`)) return; setLoading(true); try { await request(`/api/workflows/${encodeURIComponent(workflowId)}`, { method: "DELETE" }); const remaining = workflows.filter((workflow) => workflow.workflow_id !== workflowId); if (workflowId === document.workflow.id) { if (remaining[0]) loadDocument(await request(`/api/workflows/${encodeURIComponent(remaining[0].workflow_id)}`)); else { const next = clone(EMPTY_WORKFLOW); next.workflow.id = `workflow-${Date.now().toString(36).slice(-4)}`; loadDocument(next); } } await refreshData(); setNotice({ kind: "success", text: `已删除流程：${item.name}` }); } catch (error) { setNotice({ kind: "error", text: `删除失败：${error.message}` }); } finally { setLoading(false); } }, [document.workflow.id, loadDocument, refreshData, request, workflows]);
  const importDocument = useCallback(() => { try { const parsed = importFormat === "yaml" ? yaml.load(importText) : JSON.parse(importText); if (!parsed?.workflow || !Array.isArray(parsed.nodes)) throw new Error("缺少 workflow 或 nodes"); loadDocument(parsed); setDrawer(null); setNotice({ kind: "success", text: "已导入草稿，尚未保存到服务端" }); } catch (error) { setNotice({ kind: "error", text: `导入失败：${error.message}` }); } }, [importFormat, importText, loadDocument]);
  const exportDocument = useCallback(() => { setImportText(importFormat === "yaml" ? yaml.dump(canonicalDocument, { noRefs: true, lineWidth: -1 }) : JSON.stringify(canonicalDocument, null, 2)); setDrawer("import"); }, [canonicalDocument, importFormat]);
  const commands = useMemo(() => [
    { id: "add-node", label: "添加节点", shortcut: "N", icon: <Plus size={14} />, run: () => setPendingAdd({ sourceId: null, edgeId: null }) },
    { id: "save", label: "保存版本", shortcut: "⌘S", icon: <Check size={14} />, run: save },
    { id: "run", label: "运行流程", shortcut: "⌘↵", icon: <PlayCircle size={14} />, run },
    { id: "undo", label: "撤销", shortcut: "⌘Z", icon: <ArrowUUpLeft size={14} />, run: () => { setHistory(undoHistory); resetSelection(); } },
    { id: "redo", label: "重做", shortcut: "⇧⌘Z", icon: <ArrowUUpRight size={14} />, run: () => { setHistory(redoHistory); resetSelection(); } },
    { id: "select-all", label: "选择全部", shortcut: "⌘A", icon: <Copy size={14} />, run: () => setSelectedNodeIds(nodes.map((node) => node.id)) },
    { id: "fit", label: "适配画布", shortcut: "F", icon: <GitBranch size={14} />, run: () => fitView({ padding: 0.22, duration: 350 }) },
    { id: "clear", label: "清除选择", shortcut: "ESC", icon: <X size={14} />, run: resetSelection },
  ], [fitView, nodes, resetSelection, run, save]);
  const contextActions = useMemo(() => { if (!contextMenu) return []; const actions = [{ id: "add-node", label: "添加节点", shortcut: "N", icon: <Plus size={14} />, run: () => setPendingAdd({ sourceId: null, edgeId: null }) }]; if (contextMenu.target === "node") actions.push({ id: "duplicate", label: "复制节点", shortcut: "⌘D", icon: <Copy size={14} />, run: () => duplicateNode(contextMenu.id) }, { id: "delete", label: "删除节点", shortcut: "Delete", icon: <Trash size={14} />, run: () => deleteNodeById(contextMenu.id) }); if (contextMenu.target === "edge") actions.push({ id: "insert", label: "在连线中添加节点", shortcut: "+", icon: <Plus size={14} />, run: () => openNodePickerOnEdge(contextMenu.id) }, { id: "delete", label: "删除连线", shortcut: "Delete", icon: <Trash size={14} />, run: () => deleteEdgeById(contextMenu.id) }); actions.push({ id: "clear", label: "清除选择", shortcut: "ESC", icon: <X size={14} />, run: resetSelection }); return actions; }, [contextMenu, deleteEdgeById, deleteNodeById, duplicateNode, openNodePickerOnEdge, resetSelection]);
  const onNodeContextMenu = useCallback((event, nodeId) => { event.preventDefault(); selectNode(nodeId); setContextMenu({ x: event.clientX, y: event.clientY, target: "node", id: nodeId }); }, [selectNode]);
  const onEdgeContextMenu = useCallback((event, edgeValue) => { event.preventDefault(); selectEdge(edgeValue.id); setContextMenu({ x: event.clientX, y: event.clientY, target: "edge", id: edgeValue.id }); }, [selectEdge]);
  const onPaneContextMenu = useCallback((event) => { event.preventDefault(); clearSelection(); setContextMenu({ x: event.clientX, y: event.clientY, target: "pane" }); }, [clearSelection]);
  const closeContextMenu = useCallback(() => setContextMenu(null), []);
  useEffect(() => {
    const handleKeyDown = (event) => {
      if (activeView !== "editor" || drawer) return;
      if (event.target.closest?.("input, textarea, select, [contenteditable=\"true\"]")) return;
      const mod = event.metaKey || event.ctrlKey; const key = event.key.toLowerCase();
      if (event.key === "Escape") { setCommandPaletteOpen(false); setPendingAdd(null); setContextMenu(null); resetSelection(); return; }
      if ((event.key === "Delete" || event.key === "Backspace") && (selectedNodeIds.length || selectedEdgeId)) { event.preventDefault(); deleteSelected(); return; }
      if (mod && key === "z") { event.preventDefault(); if (event.shiftKey) setHistory(redoHistory); else setHistory(undoHistory); resetSelection(); return; }
      if (mod && key === "y") { event.preventDefault(); setHistory(redoHistory); resetSelection(); return; }
      if (mod && key === "c") { event.preventDefault(); copyNodes(selectedNodeIds); return; }
      if (mod && key === "v") { event.preventDefault(); pasteNodes(); return; }
      if (mod && key === "d") { event.preventDefault(); if (selectedNodeIds.length) { copyNodes(selectedNodeIds, false); pasteNodes(); } return; }
      if (mod && key === "a") { event.preventDefault(); setSelectedNodeIds(nodes.map((node) => node.id)); return; }
      if (mod && key === "k") { event.preventDefault(); setCommandPaletteOpen(true); return; }
      if (mod && key === "s") { event.preventDefault(); save(); }
    };
    window.addEventListener("keydown", handleKeyDown); return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activeView, copyNodes, deleteSelected, drawer, nodes, pasteNodes, resetSelection, save, selectedEdgeId, selectedNodeIds]);

  const openNodeMenu = useCallback((event, nodeId) => { const anchor = event?.currentTarget?.getBoundingClientRect?.(); const menuWidth = 214; const menuHeight = 190; const gap = 10; const x = anchor ? (anchor.right + gap + menuWidth <= window.innerWidth ? anchor.right + gap : Math.max(12, anchor.left - menuWidth - gap)) : Math.max(12, window.innerWidth / 2 - menuWidth / 2); const y = anchor ? Math.min(Math.max(12, anchor.top), Math.max(12, window.innerHeight - menuHeight - 12)) : 120; setContextMenu({ x, y, target: "node", id: nodeId }); }, []);
  if (!token) return <LoginPanel onAuthenticated={setToken} />;
  const nodeStates = nodeExecutionStates(nodes, latestRun);
  const canvasNodes = nodes.map((node) => ({ ...node, selected: selectedNodeIds.includes(node.id), data: { ...node.data, validationErrors: validateNodeConfig(node, document.workflow.target), executionState: nodeStates[node.id], executionError: latestRun?.error?.node_id === node.id ? latestRun.error.message : "", onAddAfter: () => openNodePickerAfter(node.id), onDuplicate: () => duplicateNode(node.id), onDelete: () => deleteNodeById(node.id), onExecute: () => executeNode(node.id), onMore: (event) => openNodeMenu(event, node.id) } }));
  const canvasEdges = edges.map((edge) => ({ ...edge, type: "workflowEdge", selected: edge.id === selectedEdgeId, label: edge.data?.condition || "", data: { ...(edge.data || {}), condition: edge.data?.condition || "", executionState: edgeExecutionState(edge, nodeStates), onAddNode: () => openNodePickerOnEdge(edge.id), onDelete: () => deleteEdgeById(edge.id) } }));
  return <div className="app-shell">
    <header className="topbar"><div className="brand"><div className="brand-mark"><Lightning size={17} weight="fill" /></div><span>tg<span className="brand-accent">·</span>ifttt</span></div><div className="crumb"><span className="crumb-muted">WORKFLOWS</span><ArrowRight size={14} /><strong>{document.workflow.name}</strong><span className="draft-pill"><span className="status-dot" />本地草稿</span></div><div className="top-actions"><button type="button" className="ghost-button" onClick={() => setToken("")}><LockKey size={16} />退出</button><button type="button" className="primary-button" onClick={save} disabled={loading}><Check size={16} />保存版本</button></div></header>
    <div className="workspace"><aside className="sidebar"><div className="side-heading"><span className="eyebrow">CONTROL PLANE</span><button type="button" className="icon-button" aria-label="设置"><Gear size={18} /></button></div><nav className="main-nav"><button type="button" className={activeView === "editor" ? "nav-item active" : "nav-item"} onClick={() => setActiveView("editor")}><GitBranch size={18} />流程编辑器</button><button type="button" className={activeView === "runs" ? "nav-item active" : "nav-item"} onClick={() => setActiveView("runs")}><PlayCircle size={18} />运行记录<span className="nav-count">{runs.length}</span></button><button type="button" className={activeView === "accounts" ? "nav-item active" : "nav-item"} onClick={() => setActiveView("accounts")}><PlugsConnected size={18} />Telegram 账号<span className="nav-count">{accounts.length}</span></button></nav><div className="sidebar-section"><div className="section-label"><span>我的流程 <span>{workflows.length}</span></span><button type="button" className="section-action" onClick={() => duplicateWorkflow()} disabled={loading || !document.workflow.id} title="复制当前流程" aria-label="复制当前流程"><Copy size={14} /></button></div>{workflows.map((item) => <div className={`workflow-list-row ${item.workflow_id === document.workflow.id ? "selected" : ""}`} key={item.workflow_id}><button type="button" className={`workflow-list-item ${item.workflow_id === document.workflow.id ? "selected" : ""}`} onClick={async () => { try { loadDocument(await request(`/api/workflows/${item.workflow_id}`)); } catch (error) { setNotice({ kind: "error", text: error.message }); } }}><span className="list-status" /><span className="workflow-list-name">{item.name}</span><span className="list-arrow">→</span></button><span className="workflow-list-actions"><button type="button" className="workflow-list-action" onClick={() => duplicateWorkflow(item.workflow_id)} disabled={loading} title="复制流程" aria-label={`复制流程 ${item.name}`}><Copy size={14} /></button><button type="button" className="workflow-list-action danger" onClick={() => deleteWorkflow(item.workflow_id)} disabled={loading} title="删除流程" aria-label={`删除流程 ${item.name}`}><Trash size={14} /></button></span></div>)}</div><button type="button" className="new-workflow" onClick={() => { const next = clone(EMPTY_WORKFLOW); next.workflow.id = `workflow-${Date.now().toString(36).slice(-4)}`; loadDocument(next); }}><Plus size={17} />新建流程</button><div className="sidebar-footer"><div className="connection"><span className="status-dot live" /><div><strong>API 已连接</strong><span>SQLite / durable</span></div></div><div className="footer-note">SESSION ENCRYPTED<br />CHECKPOINTS ENABLED</div></div></aside>{activeView === "editor" ? <WorkflowEditor document={document} accounts={accounts} nodes={nodes} edges={edges} selectedNode={selectedNode} selectedEdge={selectedEdge} selectionCount={selectedNodeIds.length} canonicalDocument={canonicalDocument} mode={mode} setMode={setMode} paletteFilter={paletteFilter} setPaletteFilter={setPaletteFilter} visiblePalette={visiblePalette} loading={loading} setImportText={setImportText} setImportFormat={setImportFormat} setDrawer={setDrawer} run={run} canvasRef={canvasRef} onDrop={onDrop} addNodeFromPalette={addNodeFromPalette} clearSelection={clearSelection} setFlowInstance={setFlowInstance} canvasNodes={canvasNodes} canvasEdges={canvasEdges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} onReconnect={onReconnect} isValidConnection={isValidConnection} onNodeDragStart={onNodeDragStart} onNodeDragStop={onNodeDragStop} selectNode={selectNode} selectEdge={selectEdge} onNodeContextMenu={onNodeContextMenu} onEdgeContextMenu={onEdgeContextMenu} onPaneContextMenu={onPaneContextMenu} closeContextMenu={closeContextMenu} onMoveEnd={onMoveEnd} zoom={zoom} zoomIn={zoomIn} zoomOut={zoomOut} resetZoom={resetZoom} fitView={fitView} showMinimap={showMinimap} setShowMinimap={setShowMinimap} updateSelectedConfig={updateSelectedConfig} renameSelected={renameSelected} deleteSelected={deleteSelected} updateSelectedEdge={updateSelectedEdge} pendingAdd={pendingAdd} setPendingAdd={setPendingAdd} commandPaletteOpen={commandPaletteOpen} setCommandPaletteOpen={setCommandPaletteOpen} commands={commands} contextMenu={contextMenu} contextActions={contextActions} canUndo={canUndo} canRedo={canRedo} setDocument={setDocument} onScheduleChange={(triggers) => setDocument((current) => ({ ...current, triggers }))} executionState={executionState} /> : <main className="secondary-main">{activeView === "runs" ? <RunView runs={runs} /> : <AccountView accounts={accounts} />}</main>}</div>
    {notice.text ? <div className={`toast ${notice.kind}`}><span className="toast-icon">{notice.kind === "error" ? <WarningCircle size={18} /> : notice.kind === "info" ? <Broadcast size={18} /> : <CheckCircle size={18} />}</span>{notice.text}<button type="button" className="icon-button" onClick={() => setNotice({ kind: "", text: "" })} aria-label="关闭提示"><X size={15} /></button></div> : null}
    {drawer === "import" || drawer === "nodered" ? <div className="modal-backdrop" onClick={() => setDrawer(null)}><div className="import-modal" onClick={(event) => event.stopPropagation()}><div className="modal-heading"><div><span className="eyebrow">{drawer === "nodered" ? "NODE-RED BRIDGE" : "PORTABLE WORKFLOW"}</span><h2>{drawer === "nodered" ? "Node-RED Flow 导入 / 导出" : "配置文件导入 / 导出"}</h2></div><button type="button" className="icon-button" onClick={() => setDrawer(null)} aria-label="关闭"><X size={18} /></button></div>{drawer === "import" ? <div className="format-tabs"><button type="button" className={importFormat === "yaml" ? "format-tab active" : "format-tab"} onClick={() => setImportFormat("yaml")}>YAML</button><button type="button" className={importFormat === "json" ? "format-tab active" : "format-tab"} onClick={() => setImportFormat("json")}>JSON</button></div> : <p className="modal-note">已打开 Node-RED 编辑器。把下方 Flow 粘贴到 Node-RED 的 Import 对话框，编辑后再粘贴回来同步。</p>}<textarea className="import-editor" value={importText} onChange={(event) => setImportText(event.target.value)} spellCheck="false" /><div className="modal-actions">{drawer === "nodered" ? <><button type="button" className="outline-button" onClick={copyNodeRed}><DownloadSimple size={17} />复制 Flow</button><button type="button" className="primary-button" onClick={syncNodeRed}><UploadSimple size={17} />同步回 Python</button></> : <><button type="button" className="ghost-button" onClick={openNodeRed}><GitBranch size={16} />Node-RED 兼容</button><button type="button" className="outline-button" onClick={exportDocument}><DownloadSimple size={17} />刷新导出</button><button type="button" className="primary-button" onClick={importDocument}><UploadSimple size={17} />导入为草稿</button></>}</div><p className="modal-note"><LockKey size={15} />凭据、session 和 Bot Token 永远不进入流程配置文件。</p></div></div> : null}
  </div>;
}

function RunView({ runs }) { return <section className="secondary-content"><div className="editor-header"><div><span className="eyebrow">OBSERVABILITY / 02</span><h1>运行记录</h1><p>每个节点完成后写入 SQLite 检查点，服务重启后可从当前位置继续。</p></div></div><div className="run-table"><div className="run-row run-head"><span>RUN ID</span><span>WORKFLOW</span><span>ACCOUNT</span><span>STATUS</span><span>CHECKPOINT</span></div>{runs.length ? runs.map((run) => <div className="run-row" key={run.run_id}><span className="mono">{run.run_id.slice(0, 12)}</span><span>{run.workflow_id}</span><span className="mono">{run.account_id}</span><span><span className={`run-status ${run.status}`}>{runStatusLabel(run.status)}</span></span><span className="mono">{run.checkpoint_seq}</span></div>) : <div className="empty-table"><PlayCircle size={26} /><strong>还没有运行记录</strong><span>从流程编辑器点击“手动运行”开始。</span></div>}</div></section>; }

function AccountView({ accounts }) {
  const request = window.__tgIftttRequest;
  const [open, setOpen] = useState(false); const [method, setMethod] = useState("qr"); const [form, setForm] = useState({ account_id: "", display_name: "", phone: "", code: "", password: "" }); const [login, setLogin] = useState(null); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  useEffect(() => { if (!login?.login_id || login.status === "ready" || method !== "qr") return undefined; const timer = setInterval(async () => { try { const next = await request(`/api/accounts/login/qr/${login.login_id}`); setLogin(next); if (next.status === "ready") window.dispatchEvent(new Event("tg-ifttt-refresh")); } catch (caught) { setError(caught.message); } }, 1800); return () => clearInterval(timer); }, [login, method, request]);
  const update = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const beginQr = async () => { setBusy(true); setError(""); try { setLogin(await request("/api/accounts/login/qr", { method: "POST", body: JSON.stringify({ account_id: form.account_id, display_name: form.display_name }) })); } catch (caught) { setError(caught.message); } finally { setBusy(false); } };
  const beginPhone = async () => { setBusy(true); setError(""); try { setLogin(await request("/api/accounts/login/phone", { method: "POST", body: JSON.stringify({ account_id: form.account_id, phone: form.phone }) })); } catch (caught) { setError(caught.message); } finally { setBusy(false); } };
  const submitCode = async () => { setBusy(true); setError(""); try { setLogin(await request(`/api/accounts/login/${login.login_id}/code`, { method: "POST", body: JSON.stringify({ code: form.code }) })); } catch (caught) { setError(caught.message); } finally { setBusy(false); } };
  const submitPassword = async () => { setBusy(true); setError(""); try { setLogin(await request(`/api/accounts/login/${login.login_id}/2fa`, { method: "POST", body: JSON.stringify({ password: form.password }) })); } catch (caught) { setError(caught.message); } finally { setBusy(false); } };
  const close = () => { setOpen(false); setLogin(null); setError(""); setForm({ account_id: "", display_name: "", phone: "", code: "", password: "" }); };
  return <section className="secondary-content"><div className="editor-header"><div><span className="eyebrow">IDENTITIES / 03</span><h1>Telegram 账号</h1><p>普通用户账号的加密 session 独立保存；同一组 API ID / API Hash 可以用于多个账号。</p></div><button type="button" className="primary-button" onClick={() => setOpen(true)}><Plus size={17} />添加账号</button></div><div className="account-grid">{accounts.length ? accounts.map((account) => <div className="account-line" key={account.account_id}><div className="account-avatar"><PlugsConnected size={20} /></div><div><strong>{account.display_name}</strong><span>{account.account_id} · {account.phone || "phone hidden"}</span></div><span className={`run-status ${account.status}`}>{account.status}</span></div>) : <div className="account-empty"><Key size={28} /><strong>还没有连接账号</strong><span>添加普通用户后，流程可以逐条选择执行身份。</span><button type="button" className="outline-button" onClick={() => setOpen(true)}><Plus size={16} />开始登录</button></div>}</div>{open ? <div className="modal-backdrop" onClick={close}><div className="import-modal login-modal" onClick={(event) => event.stopPropagation()}><div className="modal-heading"><div><span className="eyebrow">ACCOUNT AUTHORIZATION</span><h2>添加普通用户账号</h2></div><button type="button" className="icon-button" onClick={close} aria-label="关闭"><X size={18} /></button></div>{!login ? <><div className="format-tabs"><button type="button" className={method === "qr" ? "format-tab active" : "format-tab"} onClick={() => setMethod("qr")}>QR 扫码</button><button type="button" className={method === "phone" ? "format-tab active" : "format-tab"} onClick={() => setMethod("phone")}>手机号验证码</button></div><div className="login-fields"><Field label="账号 ID"><TextInput value={form.account_id} onChange={(value) => update("account_id", value)} placeholder="account-main" mono /></Field><Field label="显示名称"><TextInput value={form.display_name} onChange={(value) => update("display_name", value)} placeholder="工作账号" /></Field>{method === "phone" ? <Field label="手机号" hint="仅用于发送一次性验证码"><TextInput value={form.phone} onChange={(value) => update("phone", value)} placeholder="+8613800000000" mono /></Field> : null}</div><button type="button" className="primary-button wide" disabled={busy} onClick={method === "qr" ? beginQr : beginPhone}>{busy ? <CircleNotch className="spin" size={17} /> : <Key size={17} />}{method === "qr" ? "生成二维码登录" : "发送验证码"}</button></> : <div className="login-state">{login.status === "pending_qr" ? <><div className="qr-placeholder"><Broadcast size={31} /><span>请在 Telegram 客户端扫描</span><code>{login.url}</code></div><p>二维码短时有效；此页面会自动轮询登录状态。</p></> : null}{login.status === "code_required" ? <><Field label="Telegram 验证码"><TextInput value={form.code} onChange={(value) => update("code", value)} placeholder="12345" mono /></Field><button type="button" className="primary-button wide" onClick={submitCode} disabled={busy}>确认验证码</button></> : null}{login.status === "password_required" ? <><Field label="两步验证密码" hint="密码仅在本次请求内使用，不写入存储"><TextInput value={form.password} onChange={(value) => update("password", value)} mono type="password" /></Field><button type="button" className="primary-button wide" onClick={submitPassword} disabled={busy}>完成登录</button></> : null}{login.status === "ready" ? <div className="terminal-note"><CheckCircle size={19} />账号已授权并写入加密 session。</div> : null}{login.status === "failed" || login.status === "expired" ? <div className="error-banner"><WarningCircle size={18} />{login.message || "登录未完成，请重新开始。"}</div> : null}</div>}{error ? <div className="error-banner"><WarningCircle size={18} />{error}</div> : null}<p className="modal-note"><LockKey size={15} />API ID / API Hash 是部署级配置；每个账号仅保存独立 session。</p></div></div> : null}</section>;
}

export default App;
