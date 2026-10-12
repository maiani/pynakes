/**
 * The extension-host services that publish outside the view: engine discovery,
 * the Problems panel, and the status bar tooltip.
 *
 * Each needs a few `vscode` APIs, provided here as minimal stand-ins before the
 * modules load (every test file runs in its own process, so they stay local).
 */

import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";

/** Settings each test chooses, read by the stubbed `getConfiguration`. */
const settings: Record<string, unknown> = {};

class Position {
  constructor(
    public line: number,
    public character: number,
  ) {}
  translate(_lines: number, characters: number): Position {
    return new Position(this.line, this.character + characters);
  }
}

/** A diagnostic collection that records what is currently published, by path. */
class Collection {
  readonly published = new Map<string, unknown[]>();
  set(uri: { fsPath: string }, items: unknown[]): void {
    this.published.set(uri.fsPath, items);
  }
  delete(uri: { fsPath: string }): void {
    this.published.delete(uri.fsPath);
  }
  clear(): void {
    this.published.clear();
  }
  dispose(): void {}
}
const collections: Collection[] = [];

Object.assign(require("vscode") as Record<string, unknown>, {
  workspace: {
    getConfiguration: () => ({ get: (name: string) => settings[name] }),
    getWorkspaceFolder: () => undefined,
  },
  extensions: { getExtension: () => undefined },
  languages: {
    createDiagnosticCollection: () => {
      const collection = new Collection();
      collections.push(collection);
      return collection;
    },
  },
  Uri: { file: (fsPath: string) => ({ fsPath, toString: () => `file://${fsPath}` }) },
  Position,
  Range: class {
    constructor(
      public start: Position,
      public end: Position,
    ) {}
  },
  Diagnostic: class {
    source?: string;
    code?: string;
    constructor(
      public range: unknown,
      public message: string,
      public severity: number,
    ) {}
  },
  DiagnosticSeverity: { Error: 0, Warning: 1, Information: 2 },
});

/* eslint-disable @typescript-eslint/no-require-imports */
const { resolveEngine, resetEngineDiscovery } =
  require("../engineDiscovery.js") as typeof import("../engineDiscovery.js");
const { FindingsPublisher } = require("../diagnostics.js") as typeof import("../diagnostics.js");
const { escapeMarkdown } = require("../statusBar.js") as typeof import("../statusBar.js");
const { indexCitations } = require("../insights.js") as typeof import("../insights.js");
/* eslint-enable @typescript-eslint/no-require-imports */

test(
  "an engine that could not be found is looked for again on the next read",
  { skip: process.platform === "win32" && "uses a POSIX shell script as the engine" },
  async () => {
    const bin = fs.mkdtempSync(path.join(os.tmpdir(), "pynakes-path-"));
    const originalPath = process.env.PATH;
    process.env.PATH = bin;
    settings.engine = "installed";
    resetEngineDiscovery();
    try {
      await assert.rejects(resolveEngine(), /pynakes/);

      // Installing pynakes after the first failure...
      const script = path.join(bin, "pynakes");
      fs.writeFileSync(script, "#!/bin/sh\necho 'pynakes 9.9.9'\n");
      fs.chmodSync(script, 0o755);
      // ...is noticed by the next read, without a settings change.
      const resolved = await resolveEngine();
      assert.equal(resolved.version, "9.9.9");
    } finally {
      process.env.PATH = originalPath;
      delete settings.engine;
      resetEngineDiscovery();
    }
  },
);

function citing(key: string, texPath: string) {
  return indexCitations({
    status: "success",
    action: "tex_scan",
    file: "refs.bib",
    report: {
      used: [],
      unused: [],
      missing: [key],
      cited_count: 1,
      sources: [texPath],
      include_all: false,
      usages: { [key]: [{ path: texPath, line: 1, column: 1, macro: "cite", text: `\\cite{${key}}` }] },
    },
  });
}

test("two open bibliographies keep their own undefined-citation diagnostics", () => {
  const publisher = new FindingsPublisher();
  const citations = collections[collections.length - 1];
  const first = { uri: { toString: () => "file:///a/one.bib" } } as never;
  const second = { uri: { toString: () => "file:///a/two.bib" } } as never;

  publisher.publishCitations(first, citing("Missing1", "/a/paper.tex"), true);
  publisher.publishCitations(second, citing("Missing2", "/a/paper.tex"), true);
  assert.equal(citations.published.get("/a/paper.tex")?.length, 2, "a shared source shows both");

  // Re-reading one replaces only its own.
  publisher.publishCitations(second, null, true);
  assert.equal(citations.published.get("/a/paper.tex")?.length, 1);

  publisher.publishCitations(first, citing("Missing1", "/a/other.tex"), true);
  assert.equal(citations.published.has("/a/paper.tex"), false, "a resolved citation goes");
  assert.equal(citations.published.get("/a/other.tex")?.length, 1);
});

test("the status bar tooltip shows the file's text, never Markdown made from it", () => {
  assert.equal(escapeMarkdown("[x](command:evil)"), "\\[x\\]\\(command:evil\\)");
  assert.equal(escapeMarkdown("Newton1687"), "Newton1687");
});
