/**
 * The view's write path, run end to end against the real engine.
 *
 * `runMutation` is what a key rename, a merge, and every other entry-level
 * change goes through: refuse what would orphan a pending edit, preview, show
 * the diff, ask, then write guarded by the preview's digest. Only the dialog
 * is a stand-in here — the engine, the file, and the decisions are real.
 */

import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { command, engineSkipReason } from "./engine.js";

const skip = engineSkipReason();

/** Every modal the code under test raised, and the answer each one gets. */
const dialogs: { title: string; detail: string }[] = [];
let answer: string | undefined = "Apply";

Object.assign(require("vscode") as Record<string, unknown>, {
  workspace: {
    getConfiguration: () => ({
      get: (name: string) =>
        name === "executable"
          ? command.executable
          : name === "executableArgs"
            ? command.leadingArgs
            : undefined,
    }),
    getWorkspaceFolder: () => undefined,
  },
  window: {
    showWarningMessage: async (title: string, options: { detail?: string }) => {
      dialogs.push({ title, detail: options?.detail ?? "" });
      return answer;
    },
  },
});

// Loaded after the stand-ins, so the modules see them.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { runMutation } = require("../mutations.js") as typeof import("../mutations.js");
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { renameKey } = require("../keyRename.js") as typeof import("../keyRename.js");
type MutationHost = import("../mutations.js").MutationHost;

function tempBib(contents: string): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pynakes-flow-"));
  const file = path.join(dir, "refs.bib");
  fs.writeFileSync(file, contents, "utf-8");
  return file;
}

/** A host over one file, recording what it posts; `staged` are keys with pending edits. */
function hostFor(file: string, staged: string[] = []) {
  const posted: Record<string, unknown>[] = [];
  let reloads = 0;
  const host: MutationHost = {
    document: { uri: { scheme: "file", fsPath: file } } as unknown as MutationHost["document"],
    post: (message) => posted.push(message),
    stagedKeys: () => new Set(staged),
    reconcileBuffer: async () => true,
    workingDirectory: () => path.dirname(file),
    onlineLookupsAllowed: () => false,
    reload: async () => {
      reloads += 1;
    },
    describeFailure: async (error) => ({ type: "actionError", message: String(error) }),
    withMirror: async () => undefined,
  };
  return { host, posted, reloads: () => reloads };
}

function types(posted: Record<string, unknown>[]): unknown[] {
  return posted.map((message) => message.type);
}

const PRINCIPIA =
  "@book{Newton1687,\n  title = {Principia}\n}\n" +
  "@inbook{Newton1687a,\n  crossref = {Newton1687},\n  title = {Book III}\n}\n" +
  "@book{Newton1704,\n  title = {Opticks}\n}\n" +
  "@comment{pynakes-meta: tex-sources:paper.tex;\npinax-files-dir:\n}\n";

function principia(): { file: string; tex: string; files: string } {
  const file = tempBib(PRINCIPIA);
  const dir = path.dirname(file);
  const tex = path.join(dir, "paper.tex");
  fs.writeFileSync(tex, "As in \\cite{Newton1687}.\n", "utf-8");
  const files = path.join(dir, "refs.files");
  fs.mkdirSync(files);
  fs.writeFileSync(path.join(files, "Newton1687.preprint.pdf"), "pdf");
  return { file, tex, files };
}

test("a key rename shows its diff, names what the diff hides, then writes", { skip }, async () => {
  const { file, tex, files } = principia();
  const { host, posted } = hostFor(file);
  dialogs.length = 0;
  answer = "Apply";

  await renameKey(host, "Newton1687", "  Principia1687 ");

  assert.deepEqual(types(posted), ["diff", "mutationDone"]);
  const diff = posted[0].entries as { diff: string }[];
  assert.match(diff[0].diff, /\\cite\{Principia1687\}/);
  assert.equal(dialogs.length, 1);
  assert.match(dialogs[0].detail, /paper\.tex \(1\)/);
  assert.match(dialogs[0].detail, /Newton1687\.preprint\.pdf → Principia1687\.preprint\.pdf/);
  assert.deepEqual(posted[1].renamedKey, { from: "Newton1687", to: "Principia1687" });
  assert.match(fs.readFileSync(file, "utf-8"), /@book\{Principia1687,/);
  assert.match(fs.readFileSync(tex, "utf-8"), /\\cite\{Principia1687\}/);
  assert.ok(fs.existsSync(path.join(files, "Principia1687.preprint.pdf")));
});

test("a declined key rename writes nothing", { skip }, async () => {
  const { file } = principia();
  const before = fs.readFileSync(file, "utf-8");
  const { host, posted } = hostFor(file);
  answer = undefined;

  await renameKey(host, "Newton1687", "Principia1687");

  assert.deepEqual(types(posted), ["diff", "mutationCancelled"]);
  assert.equal(fs.readFileSync(file, "utf-8"), before);
  answer = "Apply";
});

test("a key rename onto a taken key is declined by the engine", { skip }, async () => {
  const { file } = principia();
  const before = fs.readFileSync(file, "utf-8");
  const { host, posted } = hostFor(file);
  dialogs.length = 0;

  await renameKey(host, "Newton1687", "Newton1704");

  assert.deepEqual(types(posted), ["mutationError"]);
  assert.match(String(posted[0].message), /^Nothing was written: /);
  assert.equal(dialogs.length, 0, "a conflict is reported, not put up for approval");
  assert.equal(fs.readFileSync(file, "utf-8"), before);
});

test("a key rename refuses to orphan a pending edit, on it or on what follows it", { skip }, async () => {
  for (const staged of ["Newton1687", "Newton1687a"]) {
    const { file } = principia();
    const before = fs.readFileSync(file, "utf-8");
    const { host, posted } = hostFor(file, [staged]);
    dialogs.length = 0;

    await renameKey(host, "Newton1687", "Principia1687");

    assert.deepEqual(types(posted), ["mutationError"], staged);
    assert.match(String(posted[0].message), new RegExp(`pending changes to ${staged}\\b`));
    assert.equal(dialogs.length, 0);
    assert.equal(fs.readFileSync(file, "utf-8"), before);
  }
});

const PAIRS =
  "@article{Alpha1,\n  title = {On Engines},\n  doi = {10.5555/engines}\n}\n" +
  "@article{Alpha2,\n  title = {On Engines},\n  doi = {10.5555/engines},\n  year = {1843}\n}\n" +
  "@article{Beta1,\n  title = {On Residues},\n  doi = {10.5555/residues}\n}\n" +
  "@article{Beta2,\n  title = {On Residues},\n  doi = {10.5555/residues}\n}\n";

test("a whole-file merge refuses when it would remove an entry with pending edits", { skip }, async () => {
  for (const staged of ["Beta2", "Alpha1"]) {
    const file = tempBib(PAIRS);
    const { host, posted } = hostFor(file, [staged]);
    dialogs.length = 0;

    await runMutation(host, { kind: "dedupeMerge" });

    assert.deepEqual(types(posted), ["mutationError"], staged);
    assert.match(String(posted[0].message), new RegExp(`pending changes to ${staged}\\b`));
    assert.equal(dialogs.length, 0);
    assert.equal(fs.readFileSync(file, "utf-8"), PAIRS);
  }
});

test("a one-pair merge ignores pending edits outside the pair it touches", { skip }, async () => {
  const file = tempBib(PAIRS);
  const { host, posted } = hostFor(file, ["Beta2"]);

  await runMutation(host, { kind: "dedupeMerge", keys: ["Alpha2"] });

  assert.deepEqual(types(posted), ["diff", "mutationDone"]);
  const written = fs.readFileSync(file, "utf-8");
  assert.doesNotMatch(written, /@article\{Alpha2,/);
  assert.match(written, /@article\{Beta2,/);
});

test("a one-pair merge refuses when its surviving entry has pending edits", { skip }, async () => {
  const file = tempBib(PAIRS);
  const { host, posted } = hostFor(file, ["Alpha1"]);

  // Named by a key that is not the staged one, so only the preview can tell.
  await runMutation(host, { kind: "dedupeMerge", keys: ["Alpha2"] });

  assert.deepEqual(types(posted), ["mutationError"]);
  assert.equal(fs.readFileSync(file, "utf-8"), PAIRS);
});
