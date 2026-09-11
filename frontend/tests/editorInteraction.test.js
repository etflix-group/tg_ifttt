import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import test from "node:test";

import { documentToFlow, flowToDocument, renameFlowNode } from "../src/flowModel.js";
import { libraryEntry } from "../src/nodeLibrary.js";

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const appSource = fs.readFileSync(path.join(testDirectory, "../src/App.jsx"), "utf8");
const canvasSource = fs.readFileSync(path.join(testDirectory, "../src/WorkflowCanvas.jsx"), "utf8");

const document = {
  version: 1,
  workflow: { id: "daily", name: "Daily", enabled: true, account: "" },
  triggers: [{ type: "manual" }],
  nodes: [
    { id: "send", type: "telegram.send_message", config: { target: "@bot", text: "/start" } },
    { id: "end", type: "end", config: {} },
  ],
  edges: [{ from: "send", to: "end" }],
};

test("new workflow nodes use the Chinese library label instead of their generated id", () => {
  assert.equal(libraryEntry("telegram.send_message").label, "发送消息");
  assert.match(appSource, /label: libraryEntry\(type\)\.label/);
  assert.deepEqual(documentToFlow(document).nodes.map((node) => node.data.label), ["发送消息", "结束"]);
});

test("node display names can be cleared while keeping the internal id and persist after typing", () => {
  const flow = documentToFlow(document);
  const cleared = renameFlowNode(flow.nodes, "send", "");
  assert.equal(cleared[0].id, "send");
  assert.equal(cleared[0].data.label, "");

  const renamed = renameFlowNode(cleared, "send", "启动面板");
  const saved = flowToDocument(renamed, flow.edges, document.workflow, document.triggers, document.ui);
  assert.equal(saved.nodes[0].name, "启动面板");
});

test("canvas zoom is activated only by Control plus the mouse wheel", () => {
  assert.match(canvasSource, /zoomOnScroll=\{false\}/);
  assert.match(canvasSource, /zoomActivationKeyCode="Control"/);
});
