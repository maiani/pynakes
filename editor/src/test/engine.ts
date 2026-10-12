/**
 * The real engine, for the tests that run it.
 *
 * Runs this repository's own `src/` through `python3 -m pynakes`, so the tests
 * check the extension against the engine it ships with rather than whatever
 * happens to be installed. A contributor working on the extension alone, with
 * no Python environment, gets a clear skip rather than a failing `npm test`.
 *
 * CI sets `PYNAKES_REQUIRE_ENGINE`, turning that skip into a failure: these
 * tests once skipped on every CI run for want of the engine's dependencies,
 * and a green job hid that none of them ran.
 */

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { applyMutation, describeMutation, previewMutation, type Mutation } from "../library.js";
import type { PynakesCommand } from "../pynakes.js";

// out/test/engine.js -> out/test -> out -> editor -> repo root
export const repoRoot = path.resolve(__dirname, "..", "..", "..");
const repoSrc = path.join(repoRoot, "src");

export const command: PynakesCommand = { executable: "python3", leadingArgs: ["-m", "pynakes"] };
process.env.PYTHONPATH = repoSrc;

/** Why the engine cannot run here, or `false` when it can. */
export function engineSkipReason(): string | false {
  try {
    execFileSync(command.executable, [...command.leadingArgs, "--version"], {
      stdio: "ignore",
    });
    return false;
  } catch (error) {
    const reason =
      `pynakes is not runnable as "${command.executable} -m pynakes" with ` +
      `PYTHONPATH=${repoSrc}: ${(error as Error).message}`;
    if (process.env.PYNAKES_REQUIRE_ENGINE) {
      throw new Error(`PYNAKES_REQUIRE_ENGINE is set, but ${reason}`);
    }
    return reason;
  }
}

/** Write `contents` as `name` in a fresh temporary directory, and return its path. */
export function tempBib(contents: string, name = "refs.bib"): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pynakes-test-"));
  const file = path.join(dir, name);
  fs.writeFileSync(file, contents, "utf-8");
  return file;
}

/**
 * Run one mutation as the view does: preview, check the preview wrote nothing
 * and reported a digest, then apply guarded by that digest.
 */
export async function previewThenApply(file: string, mutation: Mutation) {
  const before = fs.readFileSync(file, "utf-8");
  const preview = await previewMutation(command, file, mutation);
  if (!preview.ok) {
    assert.fail(`${describeMutation(mutation)} preview failed: ${JSON.stringify(preview)}`);
  }
  assert.equal(fs.readFileSync(file, "utf-8"), before, "a preview must write nothing");
  assert.equal(preview.modified, true);
  assert.match(preview.sourceSha256 ?? "", /^[0-9a-f]{64}$/);
  const applied = await applyMutation(command, file, mutation, preview.sourceSha256 ?? "");
  if (!applied.ok) {
    assert.fail(`${describeMutation(mutation)} failed: ${JSON.stringify(applied)}`);
  }
  return preview;
}
