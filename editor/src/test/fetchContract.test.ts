/**
 * Fetching materials: the argument list, the real engine's plan, and what the
 * view says about it.
 *
 * Nothing here reaches the network. A dry run makes no request (the engine
 * guarantees it, and its own tests pin it), and the real-run paths exercised
 * here are the ones refused before any download: a file that moved since the
 * plan, and a run stopped before it started. The sentences the approval and
 * the result notice contain are checked against the real plan's envelope, so
 * a renamed key in it fails here rather than as an empty dialog.
 */

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import {
  FETCH_MATERIALS,
  fetchApproval,
  fetchLabel,
  fetchResult,
  nothingToFetch,
  planFetch,
  plannedFileCount,
  reduceFetch,
  runFetch,
  type AssetFetchEnvelope,
} from "../fetchPlan.js";
import { PynakesCancelledError, assetFetchArgs } from "../pynakes.js";
import { command, engineSkipReason } from "./engine.js";

const skip = engineSkipReason();

const LIBRARY = `@article{Einstein1905,
  title = {Zur Elektrodynamik bewegter K{\\"o}rper},
  doi = {10.1002/andp.19053221004},
  eprint = {1234.5678},
  archiveprefix = {arXiv},
}

@misc{Turing1936,
  title = {On Computable Numbers},
  eprint = {2345.6789},
  archiveprefix = {arXiv},
}

@book{Newton1687,
  title = {Principia},
}
`;

function tempBib(contents = LIBRARY): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pynakes-fetch-"));
  const file = path.join(dir, "refs.bib");
  fs.writeFileSync(file, contents, "utf-8");
  return file;
}

test("assetFetchArgs names the key, the material, and the guard", () => {
  assert.deepEqual(assetFetchArgs("/lib/refs.bib", { key: "Turing1936" }, true), [
    "asset",
    "fetch",
    "/lib/refs.bib",
    "--dry-run",
    "--diff",
    "--",
    "Turing1936",
  ]);
  assert.deepEqual(
    assetFetchArgs("/lib/refs.bib", { material: "best-pdf" }, false, "ab".repeat(32)),
    ["asset", "fetch", "/lib/refs.bib", "--material", "best-pdf", "--diff", "--expect-sha256", "ab".repeat(32)],
  );
});

test("the material choices are the engine's own --material values", { skip }, () => {
  const values = FETCH_MATERIALS.map((choice) => choice.value).filter(Boolean);
  // Read the choices from the machine-readable command schema, not --help: help
  // is rendered for a terminal, and its wrapping and colour vary by environment.
  const capabilities = JSON.parse(
    execFileSync(command.executable, [...command.leadingArgs, "capabilities", "--json"]).toString(),
  ) as {
    command_schemas: Record<string, { options: { flags: string[]; choices?: string[] }[] }>;
  };
  const material = capabilities.command_schemas["asset fetch"].options.find((option) =>
    option.flags.includes("--material"),
  );
  assert.ok(material?.choices, "asset fetch should declare --material choices");
  for (const value of values) {
    assert.ok(material.choices.includes(value as string), `--material ${value} should exist`);
  }
});

test("a dry run plans each file at the engine's path, and writes nothing", { skip }, async () => {
  const file = tempBib();
  const before = fs.readFileSync(file, "utf-8");
  const files = path.join(path.dirname(file), "refs.files");

  const plan = await planFetch(command, file, {});

  assert.ok(plan.ok, JSON.stringify(plan));
  assert.equal(plan.filesDir, files);
  assert.match(plan.sourceSha256 ?? "", /^[0-9a-f]{64}$/);
  // A library with no store yet records one: the .bib change is the diff.
  assert.equal(plan.modified, true);
  assert.match(plan.diff, /pinax-files-dir: refs\.files/);
  assert.deepEqual(
    plan.planned.map((entry) => [entry.key, entry.artifacts.map((item) => item.artifact)]),
    [
      ["Einstein1905", ["published_pdf", "preprint_pdf"]],
      ["Turing1936", ["preprint_pdf"]],
    ],
  );
  const einstein = plan.planned[0].artifacts;
  assert.equal(einstein[0].path, path.join(files, "Einstein1905.published.pdf"));
  assert.equal(einstein[1].fallback, true);
  assert.deepEqual(plan.skipped, [
    { key: "Newton1687", artifact: undefined, reason: "no arXiv id and no DOI" },
  ]);

  assert.equal(fs.readFileSync(file, "utf-8"), before, "a dry run must not write the .bib");
  assert.equal(fs.existsSync(files), false, "a dry run must not create the store");
});

test("the approval names the network, every file and where, and the skips", { skip }, async () => {
  const file = tempBib();
  const plan = await planFetch(command, file, {});
  assert.ok(plan.ok);

  const { title, detail } = fetchApproval({}, plan);

  assert.equal(title, "Fetch materials for 2 entries?");
  assert.match(detail, /network requests/);
  assert.match(detail, /Planning this made none/);
  // Two of the three planned files are alternatives: the fallback preprint.
  assert.match(detail, /Would write up to 2 files:/);
  assert.match(detail, /Einstein1905: Published PDF \(DOI 10\.1002\/andp\.19053221004\) → .*Einstein1905\.published\.pdf/);
  assert.match(detail, /Preprint PDF, only if no published PDF is found \(arXiv 1234\.5678\)/);
  assert.match(detail, /Turing1936: Preprint PDF \(arXiv 2345\.6789\) → .*Turing1936\.preprint\.pdf/);
  assert.match(detail, /Nothing to fetch:\n• Newton1687: no arXiv id and no DOI/);
  assert.match(detail, /provenance manifest under .*refs\.files/);
  assert.match(detail, /The \.bib changes too/);
  assert.equal(plannedFileCount(plan), 3);
});

test("one material for one entry plans only that", { skip }, async () => {
  const file = tempBib();
  const plan = await planFetch(command, file, { key: "Turing1936", material: "source" });
  assert.ok(plan.ok, JSON.stringify(plan));
  assert.deepEqual(
    plan.planned.map((entry) => entry.artifacts.map((item) => item.artifact)),
    [["preprint_source"]],
  );
  const { title, detail } = fetchApproval({ key: "Turing1936", material: "source" }, plan);
  assert.equal(title, "Fetch materials for Turing1936?");
  assert.match(detail, /Would write 1 file:\n• Turing1936: Preprint source/);
});

test("an entry with nothing to fetch says why, without asking", { skip }, async () => {
  const file = tempBib();
  const plan = await planFetch(command, file, { key: "Newton1687" });
  assert.ok(plan.ok);
  assert.equal(plan.planned.length, 0);
  assert.equal(
    nothingToFetch({ key: "Newton1687" }, plan),
    "Nothing to fetch for Newton1687: no arXiv id and no DOI.",
  );
});

test("an unknown key is the engine's error, not an empty plan", { skip }, async () => {
  const file = tempBib();
  const plan = await planFetch(command, file, { key: "Nobody1900" });
  assert.equal(plan.ok, false);
  assert.match(plan.ok ? "" : plan.message, /No entry with key 'Nobody1900'/);
});

test("a fetch over a file that moved after its plan is refused before any download", { skip }, async () => {
  const file = tempBib();
  const plan = await planFetch(command, file, { key: "Turing1936" });
  assert.ok(plan.ok && plan.sourceSha256);
  fs.appendFileSync(file, "\n@misc{Kepler1609, title = {Astronomia Nova}}\n");

  const applied = await runFetch(command, file, { key: "Turing1936" }, plan.sourceSha256);

  assert.equal(applied.ok, false);
  assert.equal(applied.ok ? undefined : applied.conflict, true);
  assert.equal(applied.ok ? undefined : applied.error, "ExternalModification");
  assert.equal(fs.existsSync(path.join(path.dirname(file), "refs.files")), false);
});

test("a fetch stopped before it starts is a cancellation, not a protocol error", { skip }, async () => {
  const file = tempBib();
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    runFetch(command, file, { key: "Turing1936" }, "ab".repeat(32), undefined, controller.signal),
    PynakesCancelledError,
  );
});

test("the result reports what landed, what was skipped and why, and failures", () => {
  const envelope: AssetFetchEnvelope = {
    status: "success",
    action: "asset_fetch",
    file: "refs.bib",
    dry_run: false,
    modified: false,
    modified_entries: 0,
    warnings: [],
    files_dir: "/lib/refs.files",
    fetched: [
      { key: "Turing1936", pdf_path: "/lib/refs.files/Turing1936.preprint.pdf", source_path: null },
    ],
    skipped: [
      { key: "Einstein1905", artifact: "published_pdf", reason: "no open-access PDF found" },
      { key: "Newton1687", reason: "no arXiv id and no DOI" },
    ],
    failed: [{ key: "Kepler1609", error: "arXiv returned HTTP 503" }],
  };
  const outcome = reduceFetch(envelope);
  assert.ok(outcome.ok);

  const result = fetchResult(outcome, new Set(["Turing1936", "Einstein1905", "Kepler1609"]));

  assert.equal(result.level, "warning");
  assert.equal(
    result.message,
    "Fetched 1 file for Turing1936. " +
      "Skipped Einstein1905 Published PDF (no open-access PDF found). " +
      "Failed Kepler1609 (arXiv returned HTTP 503).",
  );
  // An entry the plan left out is not reported again as skipped.
  assert.doesNotMatch(result.message, /Newton1687/);

  // An engine that plans without naming files is never read as "nothing to fetch".
  const older = reduceFetch({
    ...envelope,
    dry_run: true,
    fetched: [],
    failed: [],
    skipped: [{ key: "Turing1936", reason: "would fetch" }],
  });
  assert.ok(older.ok);
  assert.deepEqual(older.unplanned, ["Turing1936"]);
  assert.deepEqual(older.planned, []);

  const nothing = reduceFetch({ ...envelope, fetched: [], failed: [] });
  assert.ok(nothing.ok);
  assert.equal(fetchResult(nothing, new Set(["Einstein1905"])).level, "info");
  assert.equal(fetchLabel({}), "Fetch missing materials");
});
