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

import { execFileSync } from "node:child_process";
import * as path from "node:path";
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
