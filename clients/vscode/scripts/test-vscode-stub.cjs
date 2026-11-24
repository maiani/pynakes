"use strict";

/**
 * Preload script for `npm test` (`node --require`).
 *
 * `engineDiscovery.ts` does `import * as vscode from "vscode"` — real outside
 * the extension host only. Everything under `test/` exercises pure logic that
 * never calls into it, but the module still has to *load* for `require()` to
 * succeed, since CommonJS resolves and evaluates the whole file up front. All
 * actual `vscode.*` reads happen inside functions the tests never call
 * (`resolveCommand`, `resolveEngine`, ...), so an empty stub is enough.
 */

const Module = require("node:module");

const STUB_ID = "\0pynakes-vscode-stub";
const stub = new Module(STUB_ID, null);
stub.exports = {};
stub.loaded = true;
Module._cache[STUB_ID] = stub;

const originalResolveFilename = Module._resolveFilename;
Module._resolveFilename = function (request, ...rest) {
  if (request === "vscode") {
    return STUB_ID;
  }
  return originalResolveFilename.call(this, request, ...rest);
};
