/** Keep reusable code usable without loading a VS Code extension host. */
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { test } from "node:test";
import { JSDOM } from "jsdom";

const root = path.resolve(__dirname, "../../../../..");

test("shared models, engine transport and UI have no VS Code or Electron dependencies", () => {
  for (const directory of ["../../packages/client-core/src", "../../packages/client-core/src/engine", "../../packages/client-ui/src", "../../packages/client-ui/assets"]) {
    for (const name of fs.readdirSync(path.join(root, directory))) {
      if (!fs.statSync(path.join(root, directory, name)).isFile()) continue;
      const source = fs.readFileSync(path.join(root, directory, name), "utf8");
      assert.doesNotMatch(source, /(?:from\s+|require\()["'](?:vscode|electron|[^"']*\/vscode\/)/, name);
      assert.doesNotMatch(source, /acquireVsCodeApi|--vscode-/, name);
    }
  }
});

test("VS Code bridge forwards messages and state and supports unsubscribing", () => {
  const dom = new JSDOM("", { runScripts: "outside-only" });
  let state: unknown;
  const sent: unknown[] = [];
  Object.assign(dom.window, { acquireVsCodeApi: () => ({
    postMessage: (message: unknown) => sent.push(message),
    getState: () => state,
    setState: (value: unknown) => { state = value; },
  }) });
  dom.window.eval(fs.readFileSync(path.join(root, "media/vscode.js"), "utf8"));
  const bridge = (dom.window as unknown as { PynakesHost: {
    postMessage(message: unknown): void;
    getState(): unknown;
    setState(value: unknown): void;
    onMessage(handler: (message: unknown) => void): () => void;
  } }).PynakesHost;
  bridge.postMessage({ type: "ready" });
  assert.deepEqual(sent, [{ type: "ready" }]);
  bridge.setState({ query: "Newton" });
  assert.deepEqual(bridge.getState(), { query: "Newton" });
  const received: unknown[] = [];
  const unsubscribe = bridge.onMessage(message => received.push(message));
  dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data: { type: "library" } }));
  unsubscribe();
  dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data: null }));
  assert.deepEqual(received, [{ type: "library" }]);
  dom.window.close();
});
