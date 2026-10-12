/**
 * Names the user typed reach the real engine as names, whatever they look like.
 *
 * A group called `-x` or a citation key `-k` begins like an option, so every
 * argument builder passes such values after `--`. These run the real engine,
 * because only the engine's own parser can say whether that worked.
 */

import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import {
  type Mutation,
  applyMutation,
  describeMutation,
  previewMutation,
  renameEntryKey,
  runSearch,
} from "../library.js";
import { groupsList, groupsTree, inspectBib } from "../pynakes.js";
import { command, engineSkipReason } from "./engine.js";

const skip = engineSkipReason();

function tempBib(contents: string): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pynakes-operands-"));
  const file = path.join(dir, "refs.bib");
  fs.writeFileSync(file, contents, "utf-8");
  return file;
}

async function previewThenApply(file: string, mutation: Mutation) {
  const preview = await previewMutation(command, file, mutation);
  if (!preview.ok) {
    assert.fail(`${describeMutation(mutation)} preview failed: ${JSON.stringify(preview)}`);
  }
  const applied = await applyMutation(command, file, mutation, preview.sourceSha256 ?? "");
  if (!applied.ok) {
    assert.fail(`${describeMutation(mutation)} failed: ${JSON.stringify(applied)}`);
  }
  return preview;
}

async function treeNames(file: string): Promise<string[]> {
  const tree = await groupsTree(command, file);
  if (tree.status !== "success") {
    assert.fail(`groups tree failed: ${JSON.stringify(tree)}`);
  }
  return tree.tree.map((node) => node.name);
}

test("a group named like an option is still a group", { skip }, async () => {
  const file = tempBib("@book{Newton1687,\n  title = {Principia}\n}\n");

  await previewThenApply(file, { kind: "groupTree", edit: { op: "add", name: "-x" } });
  await previewThenApply(file, { kind: "group", key: "Newton1687", group: "-x", member: true });
  await previewThenApply(file, {
    kind: "groupTree",
    edit: { op: "describe", name: "-x", description: "-a description" },
  });
  const renamed = await previewThenApply(file, {
    kind: "groupTree",
    edit: { op: "rename", name: "-x", newName: "-y" },
  });

  assert.deepEqual(renamed.renamedMembers, ["Newton1687"]);
  assert.deepEqual(await treeNames(file), ["-y"]);
  const listed = await groupsList(command, file);
  assert.equal(listed.status === "success" && listed.groups["-y"]?.[0], "Newton1687");

  await previewThenApply(file, { kind: "group", key: "Newton1687", group: "-y", member: false });
  await previewThenApply(file, { kind: "groupTree", edit: { op: "remove", name: "-y" } });
  assert.deepEqual(await treeNames(file), []);
});

test("a citation key named like an option is still a key", { skip }, async () => {
  const file = tempBib("@book{Newton1687,\n  title = {Principia}\n}\n");

  await previewThenApply(file, {
    kind: "add",
    request: { key: "-k", entryType: "misc", fields: { title: "-dashed title" } },
  });
  const renamed = await renameEntryKey(command, file, "-k", "-j");
  assert.ok(renamed.ok, JSON.stringify(renamed));

  const found = await runSearch(command, file, { query: "-dashed" });
  assert.ok(found.ok, JSON.stringify(found));

  await previewThenApply(file, { kind: "remove", keys: ["-j"], keepFiles: true });
  const inspected = await inspectBib(command, file);
  assert.deepEqual(
    inspected.status === "success" && inspected.entries.map((entry) => entry.key),
    ["Newton1687"],
  );
});

test("renaming a group to a different case of its name renames it", { skip }, async () => {
  const file = tempBib("@book{Newton1704,\n  title = {Opticks}\n}\n");
  await previewThenApply(file, { kind: "groupTree", edit: { op: "add", name: "Optics" } });
  await previewThenApply(file, { kind: "group", key: "Newton1704", group: "Optics", member: true });

  const renamed = await previewThenApply(file, {
    kind: "groupTree",
    edit: { op: "rename", name: "Optics", newName: "OPTICS" },
  });

  assert.deepEqual(renamed.renamedMembers, ["Newton1704"]);
  assert.deepEqual(await treeNames(file), ["OPTICS"]);
});
