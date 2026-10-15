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
 * (see `pixi.toml`); see `engine.ts` for when it skips instead.
 */

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { test } from "node:test";
import {
  type RefEditRequest,
  assetCheck,
  dedupeCheck,
  dedupeMerge,
  groupsEntry,
  groupsList,
  groupsTree,
  inspectBib,
  inspectLibrary,
  keysRename,
  lintBib,
  refAdd,
  refCompare,
  refRemove,
  searchBib,
  texScan,
} from "../pynakes.js";
import {
  type Mutation,
  applyMutation,
  commitEdits,
  previewEdits,
  previewMutation,
} from "../library.js";
import { command, engineSkipReason, previewThenApply, tempBib } from "./engine.js";

const skip = engineSkipReason();

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

  const scan = await texScan(command, file);
  const assets = await assetCheck(command, file);
  const combined = await inspectLibrary(command, file);
  assert.equal(combined.status, "success");
  if (combined.status === "success") {
    // One process returns exactly what the separate commands would.
    assert.deepEqual(combined.insights, {
      groups_tree: tree,
      groups_list: list,
      lint,
      tex_scan: scan,
      asset_check: assets,
    });
    const { insights, ...base } = combined;
    assert.deepEqual(base, inspected);
  }

  const search = await searchBib(command, file, { query: "Smith" });
  if (search.status !== "success") {
    assert.fail(`search failed: ${JSON.stringify(search)}`);
  }
  assert.ok(search.matches.some((match) => match.key === "Smith2020"));
});

// --- staged commits: one batch, guarded by the preview's digest ------------

const TWO_ENTRIES =
  "@book{Newton1687,\n  title = {Principia},\n  year = {1687}\n}\n\n" +
  "@book{Euler1748,\n  title = {Introductio},\n  year = {1748}\n}\n";

const STAGED: RefEditRequest[] = [
  { key: "Euler1748", set: { note: "  two volumes  " }, clear: [], entryType: "article" },
  { key: "Newton1687", set: { year: "1713" }, clear: ["title"] },
];

test("several staged entries preview as one diff and commit as one write", { skip }, async () => {
  const file = tempBib(TWO_ENTRIES);

  const preview = await previewEdits(command, file, STAGED);
  if (!preview.ok) {
    assert.fail(`preview failed: ${JSON.stringify(preview)}`);
  }
  assert.equal(fs.readFileSync(file, "utf-8"), TWO_ENTRIES, "a preview must write nothing");
  assert.match(preview.diff, /-@book\{Euler1748,/);
  assert.match(preview.diff, /\+  year = \{1713\}/);
  assert.deepEqual(preview.entries[1].plan?.fields?.year, { old: "1687", new: "1713" });
  assert.match(preview.sourceSha256 ?? "", /^[0-9a-f]{64}$/);

  const result = await commitEdits(command, file, STAGED, preview.sourceSha256 ?? "");
  if (!result.ok) {
    assert.fail(`commit failed: ${JSON.stringify(result)}`);
  }
  assert.deepEqual(result.applied, ["Euler1748", "Newton1687"]);
  const written = fs.readFileSync(file, "utf-8");
  assert.match(written, /@article\{Euler1748,/);
  // Values are trimmed exactly as `ref edit --field` trims them.
  assert.match(written, /note = \{two volumes\}/);
  assert.match(written, /year = \{1713\}/);
  assert.doesNotMatch(written, /Principia/);
});

test("a commit over a file that moved after its preview writes nothing", { skip }, async () => {
  const file = tempBib(TWO_ENTRIES);
  const preview = await previewEdits(command, file, STAGED);
  if (!preview.ok) {
    assert.fail(`preview failed: ${JSON.stringify(preview)}`);
  }
  // An edit made while the approval dialog is open.
  const moved = TWO_ENTRIES + "\n@misc{Leibniz1684,\n  year = {1684}\n}\n";
  fs.writeFileSync(file, moved, "utf-8");

  const result = await commitEdits(command, file, STAGED, preview.sourceSha256 ?? "");

  assert.equal(result.ok, false);
  assert.equal(!result.ok && result.conflict, true);
  assert.equal(!result.ok && result.error, "ExternalModification");
  assert.equal(fs.readFileSync(file, "utf-8"), moved);
});

test("a batch that cannot apply one entry applies none and says so", { skip }, async () => {
  const file = tempBib(TWO_ENTRIES);
  const requests = [
    { key: "Euler1748", set: { note: "kept" }, clear: [] },
    { key: "Missing1900", set: { note: "x" }, clear: [] },
  ];

  const preview = await previewEdits(command, file, requests);
  assert.equal(preview.ok, false);

  // Even with a valid precondition, the write is one transaction.
  const sha = await previewEdits(command, file, requests.slice(0, 1));
  const result = await commitEdits(command, file, requests, sha.ok ? sha.sourceSha256 ?? "" : "");
  assert.equal(result.ok, false);
  assert.equal(fs.readFileSync(file, "utf-8"), TWO_ENTRIES, "all or nothing");
});

test("a duplicated key is refused, never reported as applied", { skip }, async () => {
  // `ref edit` answered this with an exit-2 conflict the view read as success,
  // so the staged edit was cleared without being written.
  const duplicated = TWO_ENTRIES + "\n@book{Euler1748,\n  title = {Copy}\n}\n";
  const file = tempBib(duplicated);

  const preview = await previewEdits(command, file, [
    { key: "Euler1748", set: { note: "x" }, clear: [] },
  ]);

  assert.equal(preview.ok, false);
  assert.equal(fs.readFileSync(file, "utf-8"), duplicated);
});

test("an entry-level change is applied only to the file its preview read", { skip }, async () => {
  const file = tempBib(TWO_ENTRIES);
  const mutation = { kind: "remove" as const, keys: ["Euler1748"], keepFiles: true };

  const preview = await previewMutation(command, file, mutation);
  if (!preview.ok) {
    assert.fail(`preview failed: ${JSON.stringify(preview)}`);
  }
  const moved = TWO_ENTRIES + "\n@misc{Leibniz1684,\n  year = {1684}\n}\n";
  fs.writeFileSync(file, moved, "utf-8");

  const stale = await applyMutation(command, file, mutation, preview.sourceSha256 ?? "");
  assert.equal(stale.ok, false);
  assert.equal(!stale.ok && stale.conflict === true && stale.error, "ExternalModification");
  assert.equal(fs.readFileSync(file, "utf-8"), moved);

  const fresh = await previewMutation(command, file, mutation);
  if (!fresh.ok) {
    assert.fail(`preview failed: ${JSON.stringify(fresh)}`);
  }
  const applied = await applyMutation(command, file, mutation, fresh.sourceSha256 ?? "");
  assert.equal(applied.ok, true);
  assert.doesNotMatch(fs.readFileSync(file, "utf-8"), /@book\{Euler1748,/);
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

  const envelope = await keysRename(command, file, "OldKey2020", "NewKey2020", false);
  if (envelope.status !== "success") {
    assert.fail(`keys rename failed: ${JSON.stringify(envelope)}`);
  }
  assert.equal(envelope.old, "OldKey2020");
  assert.equal(envelope.new, "NewKey2020");

  const rewritten = fs.readFileSync(file, "utf-8");
  assert.match(rewritten, /@article\{NewKey2020,/);
  assert.doesNotMatch(rewritten, /@article\{OldKey2020,/);
});

test("a key rename previews its TeX and material changes, then lands guarded", { skip }, async () => {
  const file = tempBib(
    "@book{Newton1687,\n  title = {Principia}\n}\n" +
      "@inbook{Newton1687a,\n  crossref = {Newton1687},\n  title = {Book III}\n}\n" +
      "@comment{pynakes-meta: tex-sources:paper.tex;\npinax-files-dir:\n}\n",
  );
  const dir = path.dirname(file);
  const tex = path.join(dir, "paper.tex");
  fs.writeFileSync(tex, "See \\cite{Newton1687} and \\cite{Newton1687}.\n", "utf-8");
  const files = path.join(dir, "refs.files");
  fs.mkdirSync(files);
  fs.writeFileSync(path.join(files, "Newton1687.preprint.pdf"), "pdf");

  const mutation: Mutation = { kind: "renameKey", oldKey: "Newton1687", newKey: "Principia1687" };
  const preview = await previewThenApply(file, mutation);
  assert.match(preview.diff, /\+@book\{Principia1687,/);
  assert.match(preview.diff, /\\cite\{Principia1687\}/, "the diff covers the TeX source");
  // The entry that follows by crossref is named, so a pending edit on it is caught.
  assert.deepEqual([...preview.rewrittenKeys].sort(), ["Newton1687", "Newton1687a"]);
  assert.equal(preview.rewrittenSources?.length, 1);
  assert.equal(preview.rewrittenSources?.[0].occurrences, 2);
  assert.equal(path.basename(preview.rewrittenSources?.[0].path ?? ""), "paper.tex");
  assert.deepEqual(
    preview.materialMoves?.map((move) => [path.basename(move.source_path), path.basename(move.target_path)]),
    [["Newton1687.preprint.pdf", "Principia1687.preprint.pdf"]],
  );

  assert.match(fs.readFileSync(tex, "utf-8"), /\\cite\{Principia1687\}/);
  assert.ok(fs.existsSync(path.join(files, "Principia1687.preprint.pdf")));
  assert.ok(!fs.existsSync(path.join(files, "Newton1687.preprint.pdf")));
});

test("a key rename onto a taken key is the engine's conflict, nothing written", { skip }, async () => {
  const file = tempBib(
    "@book{Newton1687,\n  title = {Principia}\n}\n@book{Newton1704,\n  title = {Opticks}\n}\n",
  );
  const before = fs.readFileSync(file, "utf-8");

  const preview = await previewMutation(command, file, {
    kind: "renameKey",
    oldKey: "Newton1687",
    newKey: "Newton1704",
  });
  assert.equal(preview.ok, false);
  assert.equal(!preview.ok && preview.conflict, true);
  assert.equal(!preview.ok && preview.conflict === true && preview.error, "CitationKeyConflict");
  assert.equal(fs.readFileSync(file, "utf-8"), before);
});

test("a key rename approved against a file that moved is refused", { skip }, async () => {
  const file = tempBib("@book{Newton1687,\n  title = {Principia}\n}\n");
  const mutation: Mutation = { kind: "renameKey", oldKey: "Newton1687", newKey: "Principia1687" };
  const preview = await previewMutation(command, file, mutation);
  assert.ok(preview.ok && preview.sourceSha256, JSON.stringify(preview));
  fs.appendFileSync(file, "@book{Newton1704,\n  title = {Opticks}\n}\n", "utf-8");

  const applied = await applyMutation(command, file, mutation, preview.sourceSha256 ?? "");
  assert.equal(!applied.ok && applied.conflict === true && applied.error, "ExternalModification");
  assert.match(fs.readFileSync(file, "utf-8"), /@book\{Newton1687,/);
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

  // An unknown group is refused unless the caller asks to create it.
  const refused = await groupsEntry(command, file, "Smith2020", "Reviewed", true, false);
  assert.equal(refused.status, "error");
  const added = await groupsEntry(
    command, file, "Smith2020", "Reviewed", true, false, undefined, undefined, true,
  );
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

test("a merge preview names every entry it rewrites or removes", { skip }, async () => {
  const file = tempBib(TWO_DUPLICATE_PAIRS);

  const whole = await previewMutation(command, file, { kind: "dedupeMerge" });
  assert.ok(whole.ok, JSON.stringify(whole));
  // The removed copies always; a survivor only when the merge changes it.
  for (const key of ["Alpha2", "Beta2"]) {
    assert.ok(whole.ok && whole.rewrittenKeys.includes(key), `${key} must be named`);
  }

  const one = await previewMutation(command, file, { kind: "dedupeMerge", keys: ["Alpha2"] });
  assert.ok(one.ok, JSON.stringify(one));
  assert.ok(one.ok && one.rewrittenKeys.includes("Alpha2"));
  assert.ok(one.ok && !one.rewrittenKeys.some((key) => key.startsWith("Beta")));
});

test("dedupe merge without keys still merges every cluster", { skip }, async () => {
  const file = tempBib(TWO_DUPLICATE_PAIRS);

  const envelope = await dedupeMerge(command, file, undefined, false);
  if (envelope.status !== "success") {
    assert.fail(`dedupe merge failed: ${JSON.stringify(envelope)}`);
  }
  assert.equal(envelope.merged_clusters, 2);
});

// --- the group hierarchy -----------------------------------------------------
//
// Each sidebar action is one `groupTree` mutation, previewed and then applied
// with the preview's digest. These run the exact path the view takes, so a
// wrong argument order, a missing `--expect-sha256`, or an envelope key the
// approval dialog reads would each fail here rather than in the field.

const HIERARCHY = "@book{Newton1687,\n  title = {Principia}\n}\n";

async function treeNames(file: string): Promise<Array<[string, string]>> {
  const tree = await groupsTree(command, file);
  if (tree.status !== "success") {
    assert.fail(`groups tree failed: ${JSON.stringify(tree)}`);
  }
  return tree.tree.map((node) => [node.name, node.parent]);
}

test("the sidebar's hierarchy edits run add, rename, move and describe", { skip }, async () => {
  const file = tempBib(HIERARCHY);
  const edit = (edit: Extract<Mutation, { kind: "groupTree" }>["edit"]): Mutation => ({
    kind: "groupTree",
    edit,
  });

  const added = await previewThenApply(file, edit({ op: "add", name: "Physics" }));
  assert.match(added.diff, /\+.*Physics/);
  await previewThenApply(file, edit({ op: "add", name: "Optics", parent: "Physics" }));
  await previewThenApply(file, edit({ op: "add", name: "Mechanics" }));
  assert.deepEqual(await treeNames(file), [
    ["Physics", ""],
    ["Optics", "Physics"],
    ["Mechanics", ""],
  ]);

  await previewThenApply(file, edit({ op: "rename", name: "Optics", newName: "Light" }));
  await previewThenApply(file, edit({ op: "move", name: "Light", parent: "Mechanics" }));
  assert.deepEqual(await treeNames(file), [
    ["Physics", ""],
    ["Light", "Mechanics"],
    ["Mechanics", ""],
  ]);
  // An empty parent is the top level, and is passed rather than omitted.
  await previewThenApply(file, edit({ op: "move", name: "Light", parent: "" }));
  assert.deepEqual((await treeNames(file))[1], ["Light", ""]);

  await previewThenApply(file, edit({ op: "describe", name: "Light", description: "Waves" }));
  const described = await groupsTree(command, file);
  assert.equal(
    described.status === "success" && described.tree.find((n) => n.name === "Light")?.description,
    "Waves",
  );
  await previewThenApply(file, edit({ op: "describe", name: "Light", description: "" }));
  const cleared = await groupsTree(command, file);
  assert.equal(
    cleared.status === "success" && cleared.tree.find((n) => n.name === "Light")?.description,
    "",
  );
});

test("removing a group names every descendant it takes, before writing", { skip }, async () => {
  const file = tempBib(HIERARCHY);
  for (const [name, parent] of [
    ["Physics", ""],
    ["Optics", "Physics"],
    ["Lenses", "Optics"],
    ["Mechanics", ""],
  ]) {
    await previewThenApply(file, { kind: "groupTree", edit: { op: "add", name, parent } });
  }

  const preview = await previewThenApply(file, {
    kind: "groupTree",
    edit: { op: "remove", name: "Physics" },
  });

  assert.deepEqual(preview.removedGroups, ["Physics", "Optics", "Lenses"]);
  assert.deepEqual(await treeNames(file), [["Mechanics", ""]]);
});

test("renaming a group moves its members and names them, before writing", { skip }, async () => {
  const file = tempBib(
    "@book{Newton1704,\n  title = {Opticks}\n}\n\n" +
      "@book{Huygens1690,\n  title = {Traité de la lumière}\n}\n\n" +
      "@book{Galileo1638,\n  title = {Two New Sciences}\n}\n",
  );
  await previewThenApply(file, { kind: "groupTree", edit: { op: "add", name: "Optics" } });
  await previewThenApply(file, { kind: "groupTree", edit: { op: "add", name: "Optics Lab" } });
  for (const [key, group] of [
    ["Newton1704", "Optics"],
    ["Huygens1690", "Optics"],
    ["Galileo1638", "Optics Lab"],
  ]) {
    await previewThenApply(file, { kind: "group", key, group, member: true });
  }
  const galileo = /@book\{Galileo1638,[^@]*/.exec(fs.readFileSync(file, "utf-8"))?.[0];

  const preview = await previewThenApply(file, {
    kind: "groupTree",
    edit: { op: "rename", name: "Optics", newName: "Light" },
  });

  assert.deepEqual(preview.renamedMembers, ["Newton1704", "Huygens1690"]);
  assert.match(preview.diff, /^\+ {2}groups = \{Light\}$/m);
  const listed = await groupsList(command, file);
  if (listed.status !== "success") {
    assert.fail(`groups list failed: ${JSON.stringify(listed)}`);
  }
  assert.deepEqual([...listed.groups.Light].sort(), ["Huygens1690", "Newton1704"]);
  assert.equal(listed.groups.Optics, undefined, "no entry is left under the old name");
  // An exact-name match: a group whose name only starts with it is untouched.
  assert.ok(galileo && fs.readFileSync(file, "utf-8").includes(galileo));
});

test("a hierarchy edit the engine declines is never reported as applied", { skip }, async () => {
  const file = tempBib(HIERARCHY);
  await previewThenApply(file, { kind: "groupTree", edit: { op: "add", name: "Physics" } });
  await previewThenApply(file, {
    kind: "groupTree",
    edit: { op: "add", name: "Optics", parent: "Physics" },
  });
  const settled = fs.readFileSync(file, "utf-8");

  // A name already taken is the engine's exit-2 conflict, not an error and not a success.
  const taken = await previewMutation(command, file, {
    kind: "groupTree",
    edit: { op: "add", name: "Optics" },
  });
  assert.equal(!taken.ok && taken.conflict === true && taken.error, "GroupConflict");
  const clash = await previewMutation(command, file, {
    kind: "groupTree",
    edit: { op: "rename", name: "Physics", newName: "Optics" },
  });
  assert.equal(!clash.ok && clash.conflict === true && clash.error, "GroupConflict");

  // A move under its own descendant is refused by the engine; the view never checks.
  const cycle = await previewMutation(command, file, {
    kind: "groupTree",
    edit: { op: "move", name: "Physics", parent: "Optics" },
  });
  assert.equal(cycle.ok, false);
  assert.notEqual(!cycle.ok && cycle.conflict, true);

  const missing = await previewMutation(command, file, {
    kind: "groupTree",
    edit: { op: "remove", name: "Chemistry" },
  });
  assert.equal(missing.ok, false);
  assert.equal(fs.readFileSync(file, "utf-8"), settled);
});

test("a hierarchy edit is applied only to the file its preview read", { skip }, async () => {
  const file = tempBib(HIERARCHY);
  await previewThenApply(file, { kind: "groupTree", edit: { op: "add", name: "Physics" } });
  const mutation: Mutation = {
    kind: "groupTree",
    edit: { op: "rename", name: "Physics", newName: "Natural Philosophy" },
  };
  const preview = await previewMutation(command, file, mutation);
  if (!preview.ok) {
    assert.fail(`preview failed: ${JSON.stringify(preview)}`);
  }
  const moved = fs.readFileSync(file, "utf-8") + "\n@misc{Leibniz1684,\n  year = {1684}\n}\n";
  fs.writeFileSync(file, moved, "utf-8");

  const stale = await applyMutation(command, file, mutation, preview.sourceSha256 ?? "");

  assert.equal(!stale.ok && stale.conflict === true && stale.error, "ExternalModification");
  assert.equal(fs.readFileSync(file, "utf-8"), moved);
});

test("bulk group membership previews and commits atomically", { skip }, async () => {
  const file = tempBib("@book{Newton1687, title={Principia}}\n@book{Euler1748, title={Analysis}}\n");
  const mutation: Mutation = { kind: "groups", keys: ["Newton1687", "Euler1748"], group: "Classics", member: true, create: true };
  const added = await previewThenApply(file, mutation);
  assert.deepEqual(added.rewrittenKeys.sort(), ["Euler1748", "Newton1687"]);
  const before = fs.readFileSync(file, "utf-8");
  const refused = await applyMutation(command, file, { ...mutation, keys: ["Newton1687", "Missing"], member: false }, createHash("sha256").update(before).digest("hex"));
  assert.equal(refused.ok, false);
  assert.equal(fs.readFileSync(file, "utf-8"), before, "a failed batch writes nothing");
  await previewThenApply(file, { ...mutation, member: false });
  assert.ok(!fs.readFileSync(file, "utf-8").includes("Classics"));
  await previewThenApply(file, { kind: "remove", keys: mutation.keys, keepFiles: true });
  assert.ok(!fs.readFileSync(file, "utf-8").includes("@book"));
});


test("metadata edits round-trip through the engine with preview and validation", { skip }, async () => {
  const file = tempBib("@book{Newton1687, title={Principia}}\n");
  const edit = { namespace: "pynakes" as const, key: "notes", value: "Library notes" };
  await previewThenApply(file, { kind: "metadata", edit });
  let read = await inspectBib(command, file);
  assert.equal(read.status, "success");
  if (read.status === "success") assert.equal(read.pynakes_metadata.values.notes, "Library notes");
  await previewThenApply(file, { kind: "metadata", edit: { ...edit, value: "Revised notes" } });
  const before = fs.readFileSync(file, "utf-8");
  const refused = await previewMutation(command, file, { kind: "metadata", edit: { namespace: "jabref", key: "unknown-test-key", value: "value" } });
  assert.equal(refused.ok, false);
  assert.equal(fs.readFileSync(file, "utf-8"), before);
  await previewThenApply(file, { kind: "metadata", edit: { ...edit, value: null } });
  read = await inspectBib(command, file);
  if (read.status === "success") assert.equal(read.pynakes_metadata.values.notes, undefined);
});
