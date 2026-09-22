/**
 * Contract tests against the real pynakes CLI — not a mock.
 *
 * Everything else under `test/` exercises pure functions and never spawns the
 * engine, so nothing here caught two real drifts between the CLI's JSON
 * envelope and this file's hand-written TypeScript mirror of it: a renamed
 * envelope key (`FieldComparison.remote` -> `.other`) and a wrong argument
 * order for `keys rename` (`FILE OLD NEW`, guessed as `OLD NEW FILE`). Both
 * shipped past `tsc`, since the type declarations describe the shape a
 * developer believes the CLI has, not the shape it actually has. These tests
 * run the real engine against a real temp file and check the parts of the
 * contract that have already drifted once.
 *
 * Requires a `python3` that can `import pynakes` from this repo's `src/`
 * (see `pixi.toml`); skips itself with a clear reason otherwise, rather than
 * failing `npm test` for a contributor working on the extension alone.
 */

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import {
  type PynakesCommand,
  dedupeCheck,
  dedupeMerge,
  groupsEntry,
  groupsList,
  groupsTree,
  inspectBib,
  keysRename,
  lintBib,
  refAdd,
  refCompare,
  refEdit,
  refRemove,
  searchBib,
} from "../pynakes.js";

// out/test/cliContract.test.js -> out/test -> out -> editor -> repo root -> src
const repoSrc = path.resolve(__dirname, "..", "..", "..", "src");

const command: PynakesCommand = { executable: "python3", leadingArgs: ["-m", "pynakes"] };
process.env.PYTHONPATH = repoSrc;

function engineSkipReason(): string | false {
  try {
    execFileSync(command.executable, [...command.leadingArgs, "--version"], {
      stdio: "ignore",
    });
    return false;
  } catch (error) {
    return `pynakes is not runnable as "${command.executable} -m pynakes" with ` +
      `PYTHONPATH=${repoSrc}: ${(error as Error).message}`;
  }
}

const skip = engineSkipReason();

function tempBib(contents: string): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pynakes-contract-"));
  const file = path.join(dir, "refs.bib");
  fs.writeFileSync(file, contents, "utf-8");
  return file;
}

test("inspect/groups/lint/search return their documented envelope shape", { skip }, async () => {
  const file = tempBib(
    "@article{Smith2020,\n  title = {A Paper},\n  author = {Jane Smith},\n  year = {2020}\n}\n",
  );

  const inspected = await inspectBib(command, file);
  if (inspected.status !== "success") {
    assert.fail(`inspect failed: ${JSON.stringify(inspected)}`);
  }
  assert.equal(inspected.entries.length, 1);
  assert.equal(inspected.entries[0].key, "Smith2020");

  const tree = await groupsTree(command, file);
  assert.equal(tree.status, "success");

  const list = await groupsList(command, file);
  assert.equal(list.status, "success");

  const lint = await lintBib(command, file);
  assert.equal(lint.status, "success");

  const search = await searchBib(command, file, { query: "Smith" });
  if (search.status !== "success") {
    assert.fail(`search failed: ${JSON.stringify(search)}`);
  }
  assert.ok(search.matches.some((match) => match.key === "Smith2020"));
});

test("ref edit stages a field through the documented argv shape", { skip }, async () => {
  const file = tempBib("@article{Smith2020,\n  title = {A Paper}\n}\n");

  const envelope = await refEdit(
    command,
    file,
    { key: "Smith2020", set: { number: "10" }, clear: [] },
    false,
  );
  if (envelope.status !== "success") {
    assert.fail(`ref edit failed: ${JSON.stringify(envelope)}`);
  }
  assert.match(fs.readFileSync(file, "utf-8"), /number\s*=\s*\{?10\}?/);
});

test(
  "ref compare --with diffs two local entries and reports .other, not .remote",
  { skip },
  async () => {
    const file = tempBib(
      "@article{A,\n  author = {Someone Else},\n  title = {Same Title}\n}\n" +
        "@article{B,\n  author = {John Smith},\n  title = {Same Title}\n}\n",
    );

    const envelope = await refCompare(command, file, "A", false, undefined, "B");
    if (envelope.status !== "success") {
      assert.fail(`ref compare --with failed: ${JSON.stringify(envelope)}`);
    }
    assert.equal(envelope.source, "local");
    assert.equal(envelope.identifier, "B");

    const author = envelope.fields.find((field) => field.field === "author");
    assert.ok(author, "expected the differing author field to be reported");
    assert.equal(author && "other" in author, true);
    assert.equal(author && "remote" in author, false);
    assert.equal(author?.local, "Someone Else");
    assert.equal((author as { other: string }).other, "John Smith");
  },
);

test("keys rename takes FILE OLD NEW, not OLD NEW FILE", { skip }, async () => {
  const file = tempBib("@article{OldKey2020,\n  title = {A Paper}\n}\n");

  const envelope = await keysRename(command, file, "OldKey2020", "NewKey2020");
  if (envelope.status !== "success") {
    assert.fail(`keys rename failed: ${JSON.stringify(envelope)}`);
  }
  assert.equal(envelope.old, "OldKey2020");
  assert.equal(envelope.new, "NewKey2020");

  const rewritten = fs.readFileSync(file, "utf-8");
  assert.match(rewritten, /@article\{NewKey2020,/);
  assert.doesNotMatch(rewritten, /@article\{OldKey2020,/);
});

// --- entry and group mutations ---------------------------------------------
//
// Argument *order* is what drifted before (`keys rename`), and these commands
// each put the file in a different position: `ref add KEY FILE`,
// `ref remove FILE KEY...`, `groups add-entry FILE KEY GROUP`. Nothing in the
// TypeScript types can catch a wrong one, so each is run for real.

test("ref add takes KEY then FILE, and writes the requested type", { skip }, async () => {
  const file = tempBib("@article{Existing2020,\n  title = {A Paper}\n}\n");

  const envelope = await refAdd(
    command,
    file,
    { key: "New2024", entryType: "inproceedings", fields: { title: "Fresh Work" } },
    false,
  );
  if (envelope.status !== "success") {
    assert.fail(`ref add failed: ${JSON.stringify(envelope)}`);
  }
  const written = fs.readFileSync(file, "utf-8");
  assert.match(written, /@inproceedings\{New2024,/);
  assert.match(written, /title\s*=\s*\{Fresh Work\}/);
  assert.match(written, /@article\{Existing2020,/);
});

test("ref add reports an existing key as a conflict rather than writing", { skip }, async () => {
  const original = "@article{Taken2020,\n  title = {A Paper}\n}\n";
  const file = tempBib(original);

  const envelope = await refAdd(
    command,
    file,
    { key: "Taken2020", entryType: "article", fields: {} },
    false,
  );

  assert.equal(envelope.status, "conflict");
  assert.equal(fs.readFileSync(file, "utf-8"), original);
});

test("ref remove takes FILE then the keys, and honors --dry-run", { skip }, async () => {
  const original =
    "@article{Keep2020,\n  title = {Kept}\n}\n\n@article{Drop2021,\n  title = {Dropped}\n}\n";
  const file = tempBib(original);

  const preview = await refRemove(command, file, ["Drop2021"], false, true);
  if (preview.status !== "success") {
    assert.fail(`ref remove --dry-run failed: ${JSON.stringify(preview)}`);
  }
  assert.equal(preview.dry_run, true);
  assert.ok(preview.diff && preview.diff.includes("-@article{Drop2021,"));
  assert.equal(fs.readFileSync(file, "utf-8"), original, "a dry run must write nothing");

  const applied = await refRemove(command, file, ["Drop2021"], false, false);
  assert.equal(applied.status, "success");
  const written = fs.readFileSync(file, "utf-8");
  assert.doesNotMatch(written, /@article\{Drop2021,/);
  assert.match(written, /@article\{Keep2020,/);
});

test("groups add-entry and remove-entry take FILE KEY GROUP", { skip }, async () => {
  const file = tempBib("@article{Smith2020,\n  title = {A Paper}\n}\n");

  const added = await groupsEntry(command, file, "Smith2020", "Reviewed", true, false);
  if (added.status !== "success") {
    assert.fail(`groups add-entry failed: ${JSON.stringify(added)}`);
  }
  assert.match(fs.readFileSync(file, "utf-8"), /groups\s*=\s*\{Reviewed\}/);

  const removed = await groupsEntry(command, file, "Smith2020", "Reviewed", false, false);
  assert.equal(removed.status, "success");
  assert.doesNotMatch(fs.readFileSync(file, "utf-8"), /groups\s*=\s*\{Reviewed\}/);
});

/** Two duplicate pairs, so a per-cluster merge can be told from a whole-file one. */
const TWO_DUPLICATE_PAIRS =
  "@article{Alpha1,\n  author = {Ada Lovelace},\n  title = {On Engines},\n" +
  "  journal = {Notes},\n  year = {1843},\n  doi = {10.5555/engines}\n}\n\n" +
  "@article{Alpha2,\n  author = {Ada Lovelace},\n  title = {On Engines},\n" +
  "  journal = {Notes},\n  year = {1843},\n  doi = {10.5555/engines},\n" +
  "  note = {Offprint}\n}\n\n" +
  "@article{Beta1,\n  author = {Carl Gauss},\n  title = {On Residues},\n" +
  "  journal = {Werke},\n  year = {1801},\n  doi = {10.5555/residues}\n}\n\n" +
  "@article{Beta2,\n  author = {Carl Gauss},\n  title = {On Residues},\n" +
  "  journal = {Werke},\n  year = {1801},\n  doi = {10.5555/residues},\n" +
  "  note = {Reprint}\n}\n";

test("dedupe check reports clusters with the keys the view renders", { skip }, async () => {
  const file = tempBib(TWO_DUPLICATE_PAIRS);

  const envelope = await dedupeCheck(command, file);
  if (envelope.status !== "success") {
    assert.fail(`dedupe check failed: ${JSON.stringify(envelope)}`);
  }
  assert.equal(envelope.cluster_count, 2);
  const alpha = envelope.clusters.find((cluster) => cluster.keys.includes("Alpha1"));
  assert.ok(alpha, "expected the Alpha pair to be one cluster");
  assert.deepEqual(alpha?.keys, ["Alpha1", "Alpha2"]);
  assert.equal(alpha?.identity.value, "10.5555/engines");
  assert.equal(alpha?.entries[0].fields.title, "On Engines");
});

test("dedupe merge --key merges one cluster and leaves the other", { skip }, async () => {
  const file = tempBib(TWO_DUPLICATE_PAIRS);

  const envelope = await dedupeMerge(command, file, ["Alpha2"], false);
  if (envelope.status !== "success") {
    assert.fail(`dedupe merge --key failed: ${JSON.stringify(envelope)}`);
  }
  assert.equal(envelope.merged_clusters, 1);
  assert.equal(envelope.merged[0].primary_key, "Alpha1");

  const written = fs.readFileSync(file, "utf-8");
  assert.doesNotMatch(written, /@article\{Alpha2,/);
  assert.match(written, /@article\{Beta1,/, "an unapproved cluster must survive");
  assert.match(written, /@article\{Beta2,/, "an unapproved cluster must survive");
});

test("dedupe merge without keys still merges every cluster", { skip }, async () => {
  const file = tempBib(TWO_DUPLICATE_PAIRS);

  const envelope = await dedupeMerge(command, file, undefined, false);
  if (envelope.status !== "success") {
    assert.fail(`dedupe merge failed: ${JSON.stringify(envelope)}`);
  }
  assert.equal(envelope.merged_clusters, 2);
});
