import { Handle, NodeToolbar, Position } from "@xyflow/react";
import { Copy, DotsThree, PlayCircle, Plus, Trash } from "@phosphor-icons/react";

import { libraryEntry } from "./nodeLibrary.js";

function stopAndRun(event, callback) {
  event.preventDefault();
  event.stopPropagation();
  callback?.();
}

function nodeSummary(data, entry) {
  if (data.nodeType === "telegram.send_message") return data.config?.text || data.config?.target || entry.hint;
  if (data.nodeType === "telegram.click_button") return data.config?.match?.value || "等待面板按钮";
  if (data.nodeType === "telegram.wait_message") return data.config?.text_match?.value || "等待下一条消息";
  if (data.nodeType === "condition") return data.config?.expression || "安全表达式";
  if (data.nodeType === "delay") return `${data.config?.seconds ?? 0} 秒`;
  return entry.hint;
}

export function WorkflowNode({ data, selected }) {
  const entry = libraryEntry(data.nodeType);
  const Icon = entry.icon;
  const label = data.label || entry.label;
  const status = data.executionState || "idle";
  const statusLabel = { idle: "未执行", running: "执行中", waiting: "等待事件", success: "已完成", failed: "失败" }[status] || "未执行";
  const errors = data.validationErrors || [];
  const runtimeError = data.executionError || "";
  const run = (event) => stopAndRun(event, data.onExecute);
  const duplicate = (event) => stopAndRun(event, data.onDuplicate);
  const addAfter = (event) => stopAndRun(event, data.onAddAfter);
  const remove = (event) => stopAndRun(event, data.onDelete);
  const more = (event) => { event.preventDefault(); event.stopPropagation(); data.onMore?.(event); };
  return (
    <>
      <NodeToolbar isVisible={selected} position={Position.Top} className="node-toolbar nodrag" offset={4}>
        <button type="button" className="node-toolbar-button" onClick={run} aria-label={`执行 ${label}`} title="执行节点"><PlayCircle size={14} /></button>
        <button type="button" className="node-toolbar-button" onClick={duplicate} aria-label={`复制 ${label}`} title="复制节点"><Copy size={14} /></button>
        <button type="button" className="node-toolbar-button" onClick={addAfter} aria-label="在此节点后添加节点" title="添加节点"><Plus size={14} /></button>
        <button type="button" className="node-toolbar-button" onClick={more} aria-label="更多节点操作" title="更多操作"><DotsThree size={16} weight="bold" /></button>
        <button type="button" className="node-toolbar-button danger" onClick={remove} aria-label={`删除 ${label}`} title="删除节点"><Trash size={14} /></button>
      </NodeToolbar>
      <div className={`workflow-node ${selected ? "is-selected" : ""} status-${status} ${errors.length ? "has-errors" : ""}`} title="单击选择，拖动移动，双击编辑">
        <Handle type="target" position={Position.Left} className="node-handle" />
        <div className={`node-accent ${entry.tone}`} />
        <div className="node-kicker"><Icon size={15} weight="bold" /><span>{entry.label}</span><span className="node-kind">{data.nodeType}</span></div>
        <div className="node-title-row"><div className="node-title">{label}</div><span className={`node-status-badge status-${status}`}><span className="node-status-dot" />{statusLabel}</span></div>
        <div className="node-summary">{nodeSummary(data, entry)}</div>
        {runtimeError ? <div className="node-error-summary">{runtimeError}</div> : errors.length ? <div className="node-error-summary">{errors[0]}</div> : null}
        <button type="button" className="node-add-action nodrag" onMouseDown={(event) => event.stopPropagation()} onClick={addAfter} aria-label="从此节点添加节点" title="从此节点添加节点"><Plus size={12} weight="bold" /></button>
        <Handle type="source" position={Position.Right} className="node-handle node-source" />
      </div>
    </>
  );
}
