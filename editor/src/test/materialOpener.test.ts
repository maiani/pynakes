/**
 * Where a material opens: the pure decision (setting x click x file kind x
 * viewer availability), and the host acting on it with stand-ins for the
 * `vscode` APIs it calls.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  asMaterialOpener,
  customEditorsOf,
  globMatches,
  hasCustomViewer,
  planMaterialOpen,
  type MaterialOpenFacts,
} from "../materialOpener.js";

const file: MaterialOpenFacts = {
  setting: undefined,
  isDirectory: false,
  inWorkspace: false,
  hasViewer: true,
  extension: ".pdf",
};

test("a plain click follows the setting, which defaults to VS Code", () => {
  assert.equal(planMaterialOpen(file).action, "editor");
  assert.equal(planMaterialOpen({ ...file, setting: "editor" }).action, "editor");
  assert.equal(planMaterialOpen({ ...file, setting: "system" }).action, "system");
  // An unrecognized value is the default, not an error.
  assert.equal(planMaterialOpen({ ...file, setting: "browser" }).action, "editor");
});

test("the click's own choice wins over the setting, both ways", () => {
  assert.equal(planMaterialOpen({ ...file, setting: "editor", requested: "system" }).action, "system");
  assert.equal(planMaterialOpen({ ...file, setting: "system", requested: "editor" }).action, "editor");
  // A malformed request from the webview falls back to the setting.
  assert.equal(planMaterialOpen({ ...file, setting: "system", requested: "run" }).action, "system");
  assert.equal(asMaterialOpener("run"), undefined);
});

test("a directory is revealed, in the Explorer only when it can show it", () => {
  const directory = { ...file, isDirectory: true, extension: "" };
  assert.equal(planMaterialOpen({ ...directory, inWorkspace: true }).action, "revealInExplorer");
  assert.equal(planMaterialOpen({ ...directory, inWorkspace: false }).action, "revealInOS");
  assert.equal(
    planMaterialOpen({ ...directory, inWorkspace: true, setting: "system" }).action,
    "revealInOS",
  );
  assert.equal(planMaterialOpen({ ...directory, hasViewer: false }).suggestViewer, false);
});

test("a format VS Code cannot show still opens there, with a hint", () => {
  const noViewer = { ...file, hasViewer: false };
  const plan = planMaterialOpen(noViewer);
  assert.deepEqual(plan, { action: "editor", suggestViewer: true, opener: "editor" });
  assert.equal(planMaterialOpen({ ...noViewer, extension: ".tar" }).suggestViewer, true);
  // Text the editor can show, a viewer that exists, or the system: no hint.
  assert.equal(planMaterialOpen({ ...noViewer, extension: ".tex" }).suggestViewer, false);
  assert.equal(planMaterialOpen(file).suggestViewer, false);
  assert.equal(planMaterialOpen({ ...noViewer, requested: "system" }).suggestViewer, false);
});

test("globs match as VS Code's editor resolver does", () => {
  assert.ok(globMatches("*.pdf", "/lib/refs.files/Newton1687.pdf"));
  assert.ok(globMatches("*.PDF", "/lib/Newton1687.pdf"), "case-insensitive");
  assert.ok(globMatches("*.{jpg,png}", "C:\\lib\\Euler1748.png"));
  assert.ok(globMatches("**/*.pdf", "/lib/a/b/Euler1748.pdf"));
  assert.ok(globMatches("Euler17[0-9][0-9].pdf", "/lib/Euler1748.pdf"));
  assert.ok(!globMatches("*.pdf", "/lib/Euler1748.pdf.txt"));
  assert.ok(!globMatches("/other/*.pdf", "/lib/Euler1748.pdf"));
});

test("only a viewer VS Code would actually pick counts", () => {
  const editors = customEditorsOf([
    { contributes: { customEditors: [{ viewType: "pdf.view", selector: [{ filenamePattern: "*.pdf" }] }] } },
    {
      contributes: {
        customEditors: [
          { viewType: "djvu.view", selector: [{ filenamePattern: "*.djvu" }], priority: "option" },
          { viewType: 42, selector: [] },
        ],
      },
    },
    undefined,
    { contributes: { customEditors: "nonsense" } },
  ]);
  assert.deepEqual(
    editors.map((editor) => editor.viewType),
    ["pdf.view", "djvu.view"],
    "malformed contributions are skipped",
  );
  assert.ok(hasCustomViewer("/lib/Newton1687.pdf", editors, undefined));
  // An "option" editor is used only when associated with the file.
  assert.ok(!hasCustomViewer("/lib/Euler1748.djvu", editors, {}));
  assert.ok(hasCustomViewer("/lib/Euler1748.djvu", editors, { "*.djvu": "djvu.view" }));
  assert.ok(hasCustomViewer("/lib/Euler1748.djvu", editors, [{ filenamePattern: "*.djvu", viewType: "djvu.view" }]));
  // Associated with the text editor, or with a viewer no longer installed: none.
  assert.ok(!hasCustomViewer("/lib/Newton1687.pdf", editors, { "*.pdf": "default" }));
  assert.ok(!hasCustomViewer("/lib/Newton1687.pdf", editors, { "*.pdf": "gone.view" }));
  assert.ok(!hasCustomViewer("/lib/Newton1687.pdf", [], undefined));
});

// --- the host acting on the plan ---------------------------------------------

/** What the stubbed `vscode` was asked to do. */
const calls: Array<[string, ...unknown[]]> = [];
const settings: Record<string, unknown> = {};
let installed: unknown[] = [];
let directories = new Set<string>();
let answer: string | undefined;

const uriOf = (fsPath: string) => ({ fsPath, toString: () => `file://${fsPath}` });

Object.assign(require("vscode") as Record<string, unknown>, {
  Uri: { file: uriOf },
  Position: class {},
  Range: class {},
  TextEditorRevealType: { InCenterIfOutsideViewport: 0 },
  FileType: { File: 1, Directory: 2 },
  ViewColumn: { Beside: -2 },
  ConfigurationTarget: { Global: 1 },
  workspace: {
    fs: { stat: async (uri: { fsPath: string }) => ({ type: directories.has(uri.fsPath) ? 2 : 1 }) },
    getConfiguration: (section: string) => ({
      get: (name: string) => settings[`${section}.${name}`],
      update: async (name: string, value: unknown, target: unknown) =>
        calls.push(["update", `${section}.${name}`, value, target]),
    }),
    getWorkspaceFolder: (uri: { fsPath: string }) =>
      uri.fsPath.startsWith("/work/") ? { uri: uriOf("/work") } : undefined,
  },
  extensions: {
    get all() {
      return installed.map((packageJSON) => ({ packageJSON }));
    },
  },
  commands: {
    executeCommand: async (command: string, ...args: unknown[]) => calls.push([command, ...args]),
  },
  env: { openExternal: async (uri: { fsPath: string }) => calls.push(["openExternal", uri.fsPath]) },
  window: {
    showWarningMessage: async (message: string) => calls.push(["warning", message]),
    showInformationMessage: async (message: string, ...items: string[]) => {
      calls.push(["info", message, ...items]);
      return answer;
    },
  },
});

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { openMaterial, doubleClickEntry } = require("../navigation.js") as typeof import("../navigation.js");

function reset(): void {
  calls.length = 0;
  for (const name of Object.keys(settings)) {
    delete settings[name];
  }
  installed = [];
  directories = new Set();
  answer = undefined;
}

/** Let the notification's follow-up, which is not awaited, run. */
const settle = () => new Promise((resolve) => setImmediate(resolve));

test("a PDF opens in VS Code by default, and the system on request", async () => {
  reset();
  installed = [{ contributes: { customEditors: [{ viewType: "pdf.view", selector: [{ filenamePattern: "*.pdf" }] }] } }];
  const openable = new Set(["/lib/Newton1687.pdf"]);

  await openMaterial(openable, "/lib/Newton1687.pdf");
  assert.equal(calls[0][0], "vscode.open");
  assert.equal((calls[0][1] as { fsPath: string }).fsPath, "/lib/Newton1687.pdf");
  assert.equal(calls.length, 1, "a viewer is installed, so no hint");

  calls.length = 0;
  await openMaterial(openable, "/lib/Newton1687.pdf", "system");
  assert.deepEqual(calls, [["openExternal", "/lib/Newton1687.pdf"]]);

  calls.length = 0;
  settings["pynakes.openMaterialsWith"] = "system";
  await openMaterial(openable, "/lib/Newton1687.pdf");
  assert.deepEqual(calls, [["openExternal", "/lib/Newton1687.pdf"]]);
  await openMaterial(openable, "/lib/Newton1687.pdf", "editor");
  assert.equal(calls[1][0], "vscode.open");
});

test("with no PDF viewer the file still opens, and the hint shows once", async () => {
  reset();
  answer = "Always Open Externally";
  const openable = new Set(["/lib/Euler1748.pdf", "/lib/Gauss1801.pdf"]);

  await openMaterial(openable, "/lib/Euler1748.pdf");
  await settle();
  assert.equal(calls[0][0], "vscode.open", "never blocked on the hint");
  const info = calls.find((call) => call[0] === "info");
  assert.ok(info && info.includes("Find a PDF Viewer"));
  assert.ok(calls.some((call) => call[0] === "openExternal" && call[1] === "/lib/Euler1748.pdf"));
  assert.deepEqual(
    calls.find((call) => call[0] === "update"),
    ["update", "pynakes.openMaterialsWith", "system", 1],
  );

  calls.length = 0;
  await openMaterial(openable, "/lib/Gauss1801.pdf");
  await settle();
  assert.equal(calls.filter((call) => call[0] === "info").length, 0, "once per format per session");
});

test("a directory is revealed, and an unreported path is refused", async () => {
  reset();
  directories = new Set(["/work/refs.files/Euler1748", "/lib/Euler1748"]);
  const openable = new Set(directories);

  await openMaterial(openable, "/work/refs.files/Euler1748");
  await openMaterial(openable, "/lib/Euler1748");
  await openMaterial(openable, "/work/refs.files/Euler1748", "system");
  assert.deepEqual(
    calls.map((call) => call[0]),
    ["revealInExplorer", "revealFileInOS", "revealFileInOS"],
  );

  calls.length = 0;
  await openMaterial(openable, "/etc/passwd", "editor");
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "warning");
});

const entryDocument = { uri: uriOf("/lib/refs.bib") } as unknown as import("vscode").TextDocument;
const pdfIndex = (paths: string[]): import("../insights").MaterialIndex => ({
  byKey: { Newton1687: paths.map((path) => ({
    path, kind: "pdf", label: path, present: true, origin: "file",
  })) },
  pinaxRoot: null, orphanCount: 0, driftCount: 0, brokenCount: 0,
});

test("double-click opens a local PDF by default using the viewer preference", async () => {
  reset();
  settings["pynakes.openMaterialsWith"] = "system";
  const target = "/lib/Newton1687.PDF";
  await doubleClickEntry(entryDocument, "Newton1687", pdfIndex(["/lib/source.zip", target, target]), new Set([target]));
  assert.deepEqual(calls, [["openExternal", target]]);
});

test("double-click reports missing PDFs, including unknown prototype-like keys", async () => {
  reset();
  const index = pdfIndex(["/lib/missing.pdf"]);
  index.byKey.Newton1687[0].present = false;
  for (const key of ["Newton1687", "constructor"]) {
    await doubleClickEntry(entryDocument, key, index, new Set());
  }
  assert.equal(calls.length, 2);
  assert.ok(calls.every((call) => call[0] === "info" && String(call[1]).includes("No local PDF")));
});

test("double-click offers multiple PDFs and respects cancellation", async () => {
  reset();
  settings["pynakes.openMaterialsWith"] = "system";
  const paths = ["/lib/published.pdf", "/lib/preprint.pdf"];
  const window = require("vscode").window;
  window.showQuickPick = async (items: unknown[]) => items[1];
  await doubleClickEntry(entryDocument, "Newton1687", pdfIndex(paths), new Set(paths));
  assert.deepEqual(calls, [["openExternal", paths[1]]]);
  calls.length = 0;
  window.showQuickPick = async () => undefined;
  await doubleClickEntry(entryDocument, "Newton1687", pdfIndex(paths), new Set(paths));
  assert.deepEqual(calls, []);
});

test("source preference keeps the source jump", async () => {
  reset();
  settings["pynakes.doubleClickAction"] = "source";
  const vscode = require("vscode");
  vscode.Position = class {};
  vscode.Range = class {};
  vscode.TextEditorRevealType = { InCenterIfOutsideViewport: 0 };
  vscode.window.showTextDocument = async () => {
    calls.push(["source"]);
    return { revealRange() {} };
  };
  const document = { ...entryDocument, getText: () => "@book{Newton1687,}", positionAt: () => ({}) };
  await doubleClickEntry(document as unknown as import("vscode").TextDocument, "Newton1687", null, new Set());
  assert.deepEqual(calls, [["source"]]);
});
