import assert from "node:assert/strict";
import test from "node:test";

import { createHistory, recordHistory, redoHistory, undoHistory } from "../src/workflowHistory.js";

test("history records semantic edits and clears redo after a new edit", () => {
  let history = createHistory({ value: 0 });
  history = recordHistory(history, { value: 1 });
  history = recordHistory(history, { value: 2 });

  assert.deepEqual(undoHistory(history), {
    past: [{ value: 0 }],
    present: { value: 1 },
    future: [{ value: 2 }],
  });

  history = undoHistory(history);
  history = recordHistory(history, { value: 3 });
  assert.deepEqual(redoHistory(history), history);
});

test("history does not retain more than fifty snapshots", () => {
  let history = createHistory({ value: 0 });
  for (let value = 1; value <= 55; value += 1) history = recordHistory(history, { value });

  assert.equal(history.past.length, 50);
  assert.equal(history.past[0].value, 5);
  assert.equal(history.present.value, 55);
});
