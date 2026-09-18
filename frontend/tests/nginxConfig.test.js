import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("production Nginx config does not require the optional Node-RED service", async () => {
  const config = await readFile(new URL("../nginx.conf", import.meta.url), "utf8");

  assert.match(config, /proxy_pass http:\/\/tg-ifttt-api:8000;/);
  assert.doesNotMatch(config, /tg-ifttt-nodered/);
});

test("development Nginx config keeps the Node-RED proxy", async () => {
  const config = await readFile(new URL("../nginx.dev.conf", import.meta.url), "utf8");

  assert.match(config, /proxy_pass http:\/\/tg-ifttt-nodered:1880\/nodered\//);
});
