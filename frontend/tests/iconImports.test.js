import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const appSource = fs.readFileSync(path.join(testDirectory, "../src/App.jsx"), "utf8");
const canvasSource = fs.readFileSync(path.join(testDirectory, "../src/WorkflowCanvas.jsx"), "utf8");
const iconImport = `${appSource}\n${canvasSource}`.match(/import \{([\s\S]*?)\} from "@phosphor-icons\/react";/g)?.join("\n") || "";

test("canvas icons used by the editor are imported", () => {
  for (const icon of ["MagnifyingGlass", "MapTrifold", "Copy"]) {
    assert.match(iconImport, new RegExp(`\\b${icon}\\b`), `${icon} must be imported`);
  }
});
