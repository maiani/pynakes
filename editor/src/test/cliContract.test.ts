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
  groupsList,
  groupsTree,
  inspectBib,
  keysRename,
  lintBib,
  refCompare,
  refEdit,
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
