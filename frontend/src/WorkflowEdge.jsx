import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath } from "@xyflow/react";
import { Plus, Trash } from "@phosphor-icons/react";

function stopAndRun(event, callback) {
  event.preventDefault();
  event.stopPropagation();
  callback?.();
}

export function WorkflowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
  data,
}) {
  const [edgePath, labelX, labelY] = getSmoothStepPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition, borderRadius: 8 });
  const condition = data?.condition || "";
  const status = data?.executionState || "idle";
  return (
    <>
      <BaseEdge id={id} path={edgePath} interactionWidth={24} style={{ stroke: selected ? "#246b48" : status === "running" ? "#d18c37" : status === "waiting" ? "#5b8fb5" : status === "failed" ? "#bd6c63" : status === "success" ? "#55a878" : "#789784", strokeWidth: selected ? 2.8 : 1.7 }} />
      <EdgeLabelRenderer>
        <div className={`edge-label-wrap ${selected || condition ? "is-visible" : ""}`} style={{ transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`, pointerEvents: selected ? "all" : "none" }}>
          {condition ? <span className="edge-condition">{condition}</span> : null}
          {selected ? <span className="edge-actions nodrag nopan">
            <button type="button" className="edge-action-button" onClick={(event) => stopAndRun(event, data?.onAddNode)} aria-label="在连线中添加节点" title="添加节点"><Plus size={13} weight="bold" /></button>
            <button type="button" className="edge-action-button danger" onClick={(event) => stopAndRun(event, data?.onDelete)} aria-label="删除连线" title="删除连线"><Trash size={12} /></button>
          </span> : null}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}
