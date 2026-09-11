import { useEffect, useState } from "react";
import {
  ArrowsOut,
  Code,
  Command,
  Copy,
  Crosshair,
  GitBranch,
  LockKey,
  MagnifyingGlass,
  MapTrifold,
  Minus,
  Mouse,
  Plus,
  ArrowUUpLeft,
  ArrowUUpRight,
  Trash,
  X,
} from "@phosphor-icons/react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  SelectionMode,
} from "@xyflow/react";
import { NODE_LIBRARY } from "./nodeLibrary.js";
import { WorkflowInspector } from "./WorkflowInspector.jsx";

function NodePalette({ paletteFilter, setPaletteFilter, visiblePalette, onAdd, onDropStart, onClose }) {
  return <aside id="node-palette" className="node-palette">
    <div className="panel-title"><span>动作节点</span><span className="panel-kicker">DRAG TO CANVAS</span><button type="button" className="panel-close" onClick={onClose} aria-label="关闭节点面板"><X size={16} /></button></div>
    <p className="panel-subtitle">拖入画布，或点击添加到中心。</p>
    <div className="palette-search"><MagnifyingGlass size={14} /><input aria-label="搜索节点" value={paletteFilter} onChange={(event) => setPaletteFilter(event.target.value)} placeholder="搜索节点" /></div>
    <div className="palette-list">
      {visiblePalette.map((entry) => {
        const Icon = entry.icon;
        return <button type="button" className="palette-item" key={entry.type} draggable onDragStart={(event) => onDropStart(event, entry.type)} onClick={() => onAdd(entry.type)}><span className={`palette-icon ${entry.tone}`}><Icon size={17} /></span><span><strong>{entry.label}</strong><small>{entry.hint}</small></span><Plus size={16} className="palette-add" /></button>;
      })}
    </div>
    {visiblePalette.length === 0 ? <div className="palette-empty">没有匹配的内置节点</div> : null}
    <div className="safe-note"><LockKey size={16} /><div><strong>安全节点</strong><span>仅内置动作与安全表达式<br />不执行任意脚本。</span></div></div>
  </aside>;
}

function NodePicker({ pendingAdd, onSelect, onClose }) {
  const [query, setQuery] = useState("");
  useEffect(() => setQuery(""), [pendingAdd]);
  const visible = NODE_LIBRARY.filter((entry) => `${entry.label} ${entry.type} ${entry.hint}`.toLowerCase().includes(query.trim().toLowerCase()));
  return <div className="node-picker" role="dialog" aria-modal="true" aria-label="添加节点" onClick={(event) => event.stopPropagation()}>
    <div className="node-picker-heading"><div><span className="eyebrow">ADD NODE</span><strong>{pendingAdd?.edgeId ? "插入到连线" : "接在当前节点后"}</strong></div><button type="button" className="icon-button" onClick={onClose} aria-label="关闭添加节点"><X size={16} /></button></div>
    <div className="palette-search"><MagnifyingGlass size={14} /><input autoFocus aria-label="筛选节点" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索节点类型" /></div>
    <div className="node-picker-list">{visible.map((entry) => { const Icon = entry.icon; return <button type="button" className="node-picker-item" key={entry.type} onClick={() => onSelect(entry.type)}><span className={`palette-icon ${entry.tone}`}><Icon size={16} /></span><span><strong>{entry.label}</strong><small>{entry.type}</small></span><Plus size={14} /></button>; })}</div>
    {!visible.length ? <div className="palette-empty">没有匹配的节点</div> : null}
  </div>;
}

function CommandPalette({ open, commands, onClose }) {
  const [query, setQuery] = useState("");
  useEffect(() => { if (open) setQuery(""); }, [open]);
  if (!open) return null;
  const visible = commands.filter((command) => command.label.toLowerCase().includes(query.trim().toLowerCase()));
  return <div className="command-backdrop" onClick={onClose}><div className="command-palette" role="dialog" aria-modal="true" aria-label="命令菜单" onClick={(event) => event.stopPropagation()}><div className="command-search"><Command size={16} /><input autoFocus aria-label="搜索命令" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索命令" /><kbd>ESC</kbd></div><div className="command-list">{visible.map((command) => <button type="button" key={command.id} onClick={() => { command.run(); onClose(); }}><span>{command.icon || <Command size={15} />}{command.label}</span><kbd>{command.shortcut}</kbd></button>)}</div>{!visible.length ? <div className="palette-empty">没有匹配的命令</div> : null}</div></div>;
}

function ContextMenu({ menu, actions, onClose }) {
  if (!menu) return null;
  return <div className="context-menu" style={{ left: menu.x, top: menu.y }} role="menu" onClick={(event) => event.stopPropagation()}>{actions.map((action) => <button type="button" key={action.id} role="menuitem" disabled={action.disabled} onClick={() => { action.run(); onClose(); }}><span>{action.icon || <Command size={14} />}{action.label}</span><kbd>{action.shortcut}</kbd></button>)}</div>;
}

export function WorkflowCanvas({
  document,
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
  setImportText,
  setImportFormat,
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
  onMoveEnd,
  selectNode,
  selectEdge,
  onNodeContextMenu,
  onEdgeContextMenu,
  onPaneContextMenu,
  closeContextMenu,
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
}) {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  return <>
    <div className={`editor-grid ${paletteOpen ? "is-palette-open" : ""} ${inspectorOpen ? "is-inspector-open" : ""}`}>
      <NodePalette paletteFilter={paletteFilter} setPaletteFilter={setPaletteFilter} visiblePalette={visiblePalette} onAdd={(type) => { addNodeFromPalette(type); setPaletteOpen(false); setInspectorOpen(true); }} onClose={() => setPaletteOpen(false)} onDropStart={(event, type) => { event.dataTransfer.setData("application/tg-ifttt-node", type); event.dataTransfer.effectAllowed = "copy"; }} />
      <section className="canvas-panel">
        <div className="canvas-toolbar">
          <div className="canvas-toolbar-start"><button type="button" className="panel-toggle" onClick={() => setPaletteOpen((current) => !current)} aria-expanded={paletteOpen} aria-controls="node-palette"><GitBranch size={15} />节点</button><div className="canvas-tabs"><button type="button" className={mode === "canvas" ? "canvas-tab active" : "canvas-tab"} onClick={() => setMode("canvas")}><GitBranch size={16} />画布</button><button type="button" className={mode === "json" ? "canvas-tab active" : "canvas-tab"} onClick={() => { setMode("json"); setImportText(JSON.stringify(canonicalDocument, null, 2)); setImportFormat("json"); }}><Code size={16} />JSON 预览</button></div></div>
          <div className="canvas-tools"><div className="toolbar-group toolbar-history"><button type="button" className="tool-button" onClick={commands.find((command) => command.id === "undo")?.run} disabled={!canUndo} title="撤销"><ArrowUUpLeft size={15} /></button><button type="button" className="tool-button" onClick={commands.find((command) => command.id === "redo")?.run} disabled={!canRedo} title="重做"><ArrowUUpRight size={15} /></button></div><button type="button" className="tool-button toolbar-command" onClick={() => setCommandPaletteOpen(true)} title="命令菜单"><Command size={15} /></button><div className="zoom-controls"><button type="button" className="zoom-button" onClick={() => zoomOut({ duration: 180 })} title="缩小"><Minus size={15} /></button><span className="zoom-value">{Math.round(zoom * 100)}%</span><button type="button" className="zoom-button" onClick={() => zoomIn({ duration: 180 })} title="放大"><Plus size={15} /></button></div><div className="toolbar-group toolbar-view"><button type="button" className="zoom-button" onClick={resetZoom} title="重置缩放"><Crosshair size={15} /></button><button type="button" className="zoom-button" onClick={() => fitView({ padding: 0.22, duration: 350 })} title="适应画布"><ArrowsOut size={15} /></button><button type="button" className={`zoom-button ${showMinimap ? "active" : ""}`} onClick={() => setShowMinimap((current) => !current)} title="显示/隐藏缩略图"><MapTrifold size={15} /></button></div><button type="button" className={`panel-toggle inspector-toggle ${inspectorOpen ? "active" : ""}`} onClick={() => setInspectorOpen((current) => !current)} aria-expanded={inspectorOpen} aria-controls="workflow-inspector">检查器</button><span className="canvas-count">{nodes.length} 节点 / {edges.length} 连线</span></div>
        </div>
        {mode === "canvas" ? <div className="flow-wrap" ref={canvasRef} onDrop={onDrop} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}><ReactFlow nodes={canvasNodes} edges={canvasEdges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} onInit={setFlowInstance} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} onReconnect={onReconnect} isValidConnection={isValidConnection} onNodeDragStart={onNodeDragStart} onNodeDragStop={onNodeDragStop} onNodeClick={(event, node) => { selectNode(node.id, event); setInspectorOpen(true); }} onNodeDoubleClick={(event, node) => { selectNode(node.id, event); setInspectorOpen(true); }} onEdgeClick={(_, edge) => { selectEdge(edge.id); setInspectorOpen(true); }} onPaneClick={clearSelection} onNodeContextMenu={onNodeContextMenu} onEdgeContextMenu={onEdgeContextMenu} onPaneContextMenu={onPaneContextMenu} onMove={(_, viewport) => setZoom(viewport.zoom)} onMoveEnd={onMoveEnd} deleteKeyCode={null} selectionOnDrag selectionMode={SelectionMode.Partial} defaultViewport={document.ui?.viewport || { x: 0, y: 0, zoom: 1 }} minZoom={0.35} maxZoom={2.2} zoomOnScroll={false} zoomActivationKeyCode="Control" snapToGrid snapGrid={[16, 16]} connectionLineType="smoothstep" defaultEdgeOptions={{ type: "workflowEdge", labelShowBg: true, labelBgPadding: [6, 3], labelBgBorderRadius: 4, style: { stroke: "#6b8576", strokeWidth: 2 } }} nodesConnectable nodesDraggable edgesFocusable elevateEdgesOnSelect fitView><Background color="#cbd5cd" gap={18} size={1} /><Controls showInteractive={false} />{showMinimap ? <MiniMap nodeColor="#4c9b70" maskColor="rgba(241, 243, 240, 0.78)" /> : null}</ReactFlow>{pendingAdd ? <NodePicker pendingAdd={pendingAdd} onSelect={addNodeFromPalette} onClose={() => setPendingAdd(null)} /> : null}</div> : <textarea className="json-preview" value={JSON.stringify(canonicalDocument, null, 2)} readOnly spellCheck="false" />}
        <div className="canvas-help"><span><Mouse size={15} />拖动画布平移</span><span><Mouse size={15} />Ctrl + 滚轮缩放</span><span><Copy size={15} />Shift 多选 / ⌘K 命令</span><span><Trash size={15} />Delete 删除选中对象</span><span><GitBranch size={15} />从圆点拖出创建连线</span></div>
      </section>
      <WorkflowInspector node={selectedNode} edge={selectedEdge} nodes={nodes} workflowTarget={document.workflow.target} selectionCount={selectionCount} onChange={updateSelectedConfig} onRename={renameSelected} onDelete={deleteSelected} onEdgeChange={updateSelectedEdge} onClose={() => setInspectorOpen(false)} />
    </div>
    <CommandPalette open={commandPaletteOpen} commands={commands} onClose={() => setCommandPaletteOpen(false)} />
    <ContextMenu menu={contextMenu} actions={contextActions} onClose={closeContextMenu} />
  </>;
}
