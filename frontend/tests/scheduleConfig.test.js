import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import test from "node:test";

import { getScheduleTrigger, setScheduleTrigger } from "../src/flowModel.js";

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const appSource = fs.readFileSync(path.join(testDirectory, "../src/App.jsx"), "utf8");
const inspectorSource = fs.readFileSync(path.join(testDirectory, "../src/WorkflowInspector.jsx"), "utf8");

test("workflow editor exposes calendar schedule controls and bounded random seconds", () => {
  assert.match(appSource, /ScheduleConfig/);
  assert.match(inspectorSource, /interval_days/);
  assert.match(inspectorSource, /random_seconds/);
  assert.match(inspectorSource, /59 - .*second/);
  assert.match(inspectorSource, /每.*天.*时.*分.*秒/);
});

test("schedule trigger toggles without dropping other triggers", () => {
  const triggers = [{ type: "manual" }];
  const configured = setScheduleTrigger(triggers, { interval_days: 3, hour: 8, minute: 5, second: 57, random_seconds: true });
  assert.deepEqual(getScheduleTrigger(configured), { type: "schedule", interval_days: 3, hour: 8, minute: 5, second: 57, random_seconds: true });
  assert.deepEqual(setScheduleTrigger(configured, null), triggers);
});
