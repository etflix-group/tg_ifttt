# n8n 风格工作流画布重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有工作流 Schema、API 和 Python 执行器的前提下，把 React 编辑器补齐为可发现、可恢复、可验证的 n8n 风格画布。

**Architecture:** 保留 `App.jsx` 作为认证、服务端数据和当前工作流的 owner；把图转换/校验放在 `flowModel.js`，把撤销栈放在纯模块 `workflowHistory.js`，把节点、边、检查器和画布交互拆成聚焦的 React 组件。所有编辑先作用于 XYFlow 内存图，再由现有 `flowToDocument` 生成 canonical JSON。

**Tech Stack:** React 18、`@xyflow/react` 12、Phosphor Icons、原生 CSS、Node `node:test`、现有 FastAPI API。

## Global Constraints

- 不新增 npm 依赖。
- 保留 `documentToFlow`、`flowToDocument` 的 JSON 兼容行为和 `ui.nodes` / `ui.viewport` 持久化。
- 不把凭据、token 或 session 写入 localStorage、工作流 JSON 或浏览器剪贴板。
- undo/redo 只作用于未保存的画布草稿，最多保留 50 个快照。
- React Flow 的拖动帧不单独进入历史；节点拖动在 `onNodeDragStop` 记录一次。
- 前端校验只改善反馈，服务端校验仍是最终边界。
- 每个任务完成后运行对应的最小测试；最终运行 frontend test/build 和 Python 回归测试。

---

### Task 1: 提取节点定义并建立纯历史栈

**Files:**
- Create: `frontend/src/nodeLibrary.js`
- Create: `frontend/src/workflowHistory.js`
- Test: `frontend/tests/workflowHistory.test.js`
- Modify: `frontend/src/App.jsx:1-95`

**Interfaces:**
- `nodeLibrary.js` exports `NODE_LIBRARY`, `EMPTY_WORKFLOW`, `libraryEntry(type)`, `defaultConfig(type)`.
- `workflowHistory.js` exports `createHistory(value)`, `recordHistory(history, next, previous)`, `undoHistory(history)`, `redoHistory(history)`.

- [ ] **Step 1: Write the failing history test**

```js
import assert from "node:assert/strict";
import test from "node:test";
import { createHistory, recordHistory, redoHistory, undoHistory } from "../src/workflowHistory.js";

test("history records semantic edits and clears redo after a new edit", () => {
  let history = createHistory({ value: 0 });
  history = recordHistory(history, { value: 1 });
  history = recordHistory(history, { value: 2 });
  assert.deepEqual(undoHistory(history), { past: [{ value: 0 }], present: { value: 1 }, future: [{ value: 2 }] });
  history = undoHistory(history);
  history = recordHistory(history, { value: 3 });
  assert.deepEqual(redoHistory(history), history);
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `cd frontend && node --test tests/workflowHistory.test.js`

Expected: FAIL because `workflowHistory.js` does not exist.

- [ ] **Step 3: Implement the bounded pure history functions**

```js
const LIMIT = 50;
const clone = (value) => JSON.parse(JSON.stringify(value));
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);

export function createHistory(value) {
  return { past: [], present: clone(value), future: [] };
}

export function recordHistory(history, next, previous = history.present) {
  if (same(previous, next)) return { ...history, present: clone(next) };
  return { past: [...history.past, clone(previous)].slice(-LIMIT), present: clone(next), future: [] };
}

export function undoHistory(history) {
  if (!history.past.length) return history;
  const previous = history.past.at(-1);
  return { past: history.past.slice(0, -1), present: clone(previous), future: [clone(history.present), ...history.future].slice(0, LIMIT) };
}

export function redoHistory(history) {
  if (!history.future.length) return history;
  const next = history.future[0];
  return { past: [...history.past, clone(history.present)].slice(-LIMIT), present: clone(next), future: history.future.slice(1) };
}
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `cd frontend && node --test tests/workflowHistory.test.js`

Expected: PASS.

- [ ] **Step 5: Move node definitions out of `App.jsx`**

Copy the existing `NODE_LIBRARY`, `EMPTY_WORKFLOW`, `libraryEntry`, and `defaultConfig` implementations unchanged into `nodeLibrary.js`; replace their inline definitions with:

```js
import { EMPTY_WORKFLOW, NODE_LIBRARY, defaultConfig, libraryEntry } from "./nodeLibrary.js";
import { createHistory, recordHistory, redoHistory, undoHistory } from "./workflowHistory.js";
```

Keep a single `clone` implementation in `nodeLibrary.js` or `flowModel.js`; do not introduce a second node registry.

- [ ] **Step 6: Run existing frontend tests and build**

Run: `cd frontend && npm test && npm run build`

Expected: existing tests pass and Vite produces `dist/` without import errors.

### Task 2: Add pure graph commands and validation

**Files:**
- Modify: `frontend/src/flowModel.js`
- Modify: `frontend/tests/flowModel.test.js`

**Interfaces:**
- `validateConnection(connection, edges)` returns `{ valid: true }` or `{ valid: false, reason: string }`.
- `removeSelectedElements(nodes, edges, selection)` removes all selected node IDs and their incident edges, or one selected edge.
- `insertNodeOnEdge(nodes, edges, edgeId, node)` replaces one edge with `source -> node -> target`.
- `validateNodeConfig(node)` returns an array of user-facing error strings.

- [ ] **Step 1: Add failing tests for graph commands**

```js
test("validateConnection rejects self links and duplicate links", () => {
  const flow = documentToFlow(document);
  assert.deepEqual(validateConnection({ source: "send", target: "send" }, flow.edges), { valid: false, reason: "不能连接节点自身" });
  assert.deepEqual(validateConnection({ source: "send", target: "check" }, flow.edges), { valid: false, reason: "这两个节点之间已经存在连线" });
});

test("insertNodeOnEdge preserves the branch condition on the incoming edge", () => {
  const flow = documentToFlow(document);
  const next = insertNodeOnEdge(flow.nodes, flow.edges, flow.edges[1].id, { id: "delay-1", type: "workflow", position: { x: 600, y: 90 }, data: { nodeType: "delay", config: { seconds: 2 }, label: "delay-1" } });
  assert.deepEqual(next.edges.map((edge) => [edge.source, edge.target, edge.data?.condition || ""]), [
    ["send", "check", ""],
    ["check", "delay-1", "variables.ok == true"],
    ["delay-1", "end", ""],
  ]);
});

test("validateNodeConfig reports required Telegram values", () => {
  assert.deepEqual(validateNodeConfig({ data: { nodeType: "telegram.send_message", config: { target: "", text: "" } } }), ["目标会话不能为空", "消息内容不能为空"]);
});
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `cd frontend && node --test tests/flowModel.test.js`

Expected: FAIL with missing named exports.

- [ ] **Step 3: Implement the pure helpers**

Use `edge.source`, `edge.target`, and `edge.data.condition` as the XYFlow representation. Keep edge IDs local to the canvas; `flowToDocument` remains the only canonical serializer. Reject self-links and an existing source-target pair before calling `addEdge`.

- [ ] **Step 4: Run all frontend tests**

Run: `cd frontend && npm test`

Expected: PASS with the original layout, viewport, condition, and removal tests unchanged.

### Task 3: Split node, edge, and inspector rendering

**Files:**
- Create: `frontend/src/WorkflowNode.jsx`
- Create: `frontend/src/WorkflowEdge.jsx`
- Create: `frontend/src/WorkflowInspector.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- `WorkflowNode` receives XYFlow node props and reads callbacks from `data.onAddAfter`, `data.onDuplicate`, `data.onDelete`, and `data.onExecute`.
- `WorkflowEdge` receives XYFlow edge props and reads `data.onAddNode` and `data.onDelete`.
- `WorkflowInspector` receives `{ node, edge, nodes, onChange, onRename, onDelete, onEdgeChange }`.

- [ ] **Step 1: Move existing forms without changing field names**

Move `Field`, `TextInput`, `NodeInspector`, and `EdgeInspector` into `WorkflowInspector.jsx`. Add `validateNodeConfig(node)` output below the type chip and mark invalid fields with `aria-invalid="true"`; leave raw JSON editing inside native `<details>`.

- [ ] **Step 2: Add n8n-style node toolbar and output add button**

`WorkflowNode.jsx` must render `NodeToolbar` only when selected, retain both handles, and include accessible buttons for execute, duplicate, add node, and delete. Every action calls `event.stopPropagation()` and its supplied callback.

- [ ] **Step 3: Add selected edge toolbar**

`WorkflowEdge.jsx` uses `getSmoothStepPath` and `BaseEdge`. When selected, render a small `+` button and a delete button through `EdgeLabelRenderer`; when unselected, keep `pointer-events: none` for the label wrapper so normal canvas selection remains reliable.

- [ ] **Step 4: Replace inline component definitions and run build**

Register `workflow: WorkflowNode` and `workflowEdge: WorkflowEdge` in the React Flow props. Run:

```text
cd frontend && npm test && npm run build
```

Expected: PASS and no change to the current canonical JSON output.

### Task 4: Wire selection, insertion, reconnect, and history

**Files:**
- Create: `frontend/src/WorkflowCanvas.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/flowModel.js`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- `WorkflowCanvas` accepts the current flow, selection, node palette, zoom controls, and event callbacks; it does not fetch data or mutate the canonical document directly.
- App owns `history`, `selectedNodeIds`, `selectedEdgeId`, `clipboard`, `pendingAdd`, and `contextMenu`.

- [ ] **Step 1: Add multi-selection and semantic edit helpers in App**

Use `selectedNodeIds` for Shift/Command toggles. Render `selected: selectedNodeIds.includes(node.id)`. `selectNode(id, additive)` clears the edge selection; plain selection replaces the array.

- [ ] **Step 2: Implement connector and edge insertion**

`pendingAdd` has the shape `{ sourceId: string | null, edgeId: string | null }`. Choosing a node type with `sourceId` creates the node to the right of the source and one new edge. Choosing a type with `edgeId` calls `insertNodeOnEdge`, positions the new node at the midpoint, selects it, and closes the picker.

- [ ] **Step 3: Implement connection validation and reconnect**

Pass `isValidConnection={(connection) => validateConnection(connection, edges).valid}` and an `onConnect` handler that displays `reason` in the existing notice. Pass `onReconnect` and use `reconnectEdge(oldEdge, connection, current.edges)` only after the same validation.

- [ ] **Step 4: Record history at semantic boundaries**

Use `setHistory((current) => recordHistory(current, next))` for add/delete/connect/config/rename; update only `present` during `onNodesChange` drag frames and call `recordHistory` with the drag-start snapshot at `onNodeDragStop`. `undoHistory` and `redoHistory` clear selection and do not call the API.

- [ ] **Step 5: Add copy, duplicate, paste, and delete commands**

Keep copied nodes in a ref/state object in memory. Copy selected nodes plus edges whose endpoints are both selected; paste with a 48px offset and unique IDs; duplicate is copy followed by paste. Batch deletion removes incident edges through `removeSelectedElements`.

- [ ] **Step 6: Run tests and build**

Run: `cd frontend && npm test && npm run build`

Expected: PASS.

### Task 5: Add command palette, context menu, and execution state

**Files:**
- Modify: `frontend/src/WorkflowCanvas.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/WorkflowNode.jsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Commands are `{ id, label, shortcut, run }`; the palette filters them by label and closes after `run()`.
- Context menu carries `{ x, y, target: "pane" | "node" | "edge" }` and exposes only commands valid for that target.

- [ ] **Step 1: Add keyboard command map**

Ignore events from `input`, `textarea`, `select`, and contenteditable elements. Support Escape, Delete/Backspace, Mod+Z, Mod+Shift+Z, Mod+Y, Mod+C, Mod+V, Mod+D, Mod+A, and Mod+K.

- [ ] **Step 2: Add visible command palette and context menu**

Use native buttons and one search input. Include Add node, Save, Run, Undo, Redo, Select all, Fit canvas, and Clear selection. Right-click suppresses the browser menu and opens the same actions near the pointer.

- [ ] **Step 3: Show run status without inventing per-node results**

Set `executionState` to `running` before `run()` and to `success`/`failed` from the existing request result/error. Pass that state into every node's `data`; render a small status dot and a header status pill. Keep the existing run list refresh.

- [ ] **Step 4: Verify keyboard behavior manually and rebuild**

Run: `cd frontend && npm test && npm run build`

Expected: PASS. Manual browser check: select two nodes with Shift, duplicate, undo, redo, copy/paste, right-click, open command palette, run, and verify focus remains in form fields while typing shortcuts.

### Task 6: Visual polish and acceptance verification

**Files:**
- Modify: `frontend/src/styles.css`
- Modify: `frontend/tests/flowModel.test.js` only if a regression is found
- Create: `.omx/state/n8n-canvas/ralph-progress.json`

- [ ] **Step 1: Polish the existing palette without changing the color system**

Add compact node toolbars, selected edge labels, clear focus rings, invalid field styles, command/picker surfaces, and responsive overflow. Keep the existing mint/graphite palette and do not add a component library.

- [ ] **Step 2: Run visual verdict after the first UI pass**

Capture the logged-in editor at desktop and mobile widths, compare node/edge selection, inspector, command palette, and empty states against the approved n8n interaction notes, and persist a JSON verdict under `.omx/state/n8n-canvas/ralph-progress.json`.

- [ ] **Step 3: Fix only issues found by the verdict**

Repeat the screenshot/verdict cycle until interaction affordances are legible, overlays do not cover critical controls, and keyboard focus is visible.

- [ ] **Step 4: Run final verification**

Run:

```text
cd frontend && npm test && npm run build
cd .. && pytest -q
```

Then manually verify: open an existing workflow, add from palette, add from a node `+`, insert into an edge, reconnect, edit Telegram fields, save, reload, run, inspect run records, import/export JSON, and confirm Node-RED compatibility still opens.

- [ ] **Step 5: Report changed files and remaining risks**

Report that the backend contract was preserved, identify any browser-only verification blocked by the project admin login, and do not claim per-node execution telemetry because the current API does not expose it.
