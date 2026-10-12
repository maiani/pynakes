/**
 * Stopping an engine call stops everything it started.
 *
 * The engine is often reached through a launcher whose Python child does the
 * work, so these run a real two-level process: a fake "launcher" that starts a
 * long-running child, records the child's pid, and waits on it. Cancelling or
 * timing out the call must leave neither running. Normal runs must behave as
 * they always did: output and exit code come back unchanged.
 */

import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import {
  PynakesCancelledError,
  PynakesUnavailableError,
  run,
} from "../engineProcess.js";
import type { PynakesCommand } from "../pynakes.js";

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pynakes-process-"));

/** A launcher that starts a child sleeping for a minute, writes its pid, and waits on it. */
const launcher = path.join(dir, "launcher.js");
fs.writeFileSync(
  launcher,
  `const { spawn } = require("node:child_process");
const fs = require("node:fs");
const child = spawn(process.execPath, ["-e", "setTimeout(() => {}, 60000)"], { stdio: "ignore" });
fs.writeFileSync(process.argv[2], String(child.pid));
child.on("exit", () => process.exit(0));
`,
);

/** A well-behaved engine stand-in: prints its arguments and exits with the code asked for. */
const echo = path.join(dir, "echo.js");
fs.writeFileSync(
  echo,
  `process.stdout.write(JSON.stringify(process.argv.slice(2)));
process.stderr.write("note");
process.exit(Number(process.argv[2]));
`,
);

const node = (script: string): PynakesCommand => ({
  executable: process.execPath,
  leadingArgs: [script],
});

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

/** The pid the launcher wrote, once it has. */
async function childPid(file: string): Promise<number> {
  for (let i = 0; i < 200; i++) {
    const text = fs.existsSync(file) ? fs.readFileSync(file, "utf-8") : "";
    if (text) {
      return Number(text);
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error("the launcher never started its child");
}

async function gone(pid: number): Promise<boolean> {
  for (let i = 0; i < 200; i++) {
    if (!alive(pid)) {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  return false;
}

async function cancelKillsTheTree(): Promise<void> {
  const pidFile = path.join(dir, `cancel-${Date.now()}.pid`);
  const controller = new AbortController();
  const call = run(node(launcher), [pidFile], undefined, { signal: controller.signal, timeoutMs: 0 });
  const pid = await childPid(pidFile);
  assert.ok(alive(pid), "the launcher's child should be running before the cancel");

  controller.abort();

  // Rejecting means `close` fired: the launcher itself was reaped, not left a zombie.
  await assert.rejects(call, PynakesCancelledError);
  assert.ok(await gone(pid), `the launcher's child (pid ${pid}) outlived the cancel`);
}

async function timeoutKillsTheTree(): Promise<void> {
  const pidFile = path.join(dir, `timeout-${Date.now()}.pid`);
  const call = run(node(launcher), [pidFile], undefined, { timeoutMs: 1_000 });
  const pid = await childPid(pidFile);

  const result = await call;

  assert.notEqual(result.code, 0);
  assert.match(result.stderr, /Stopped after 1000 ms/);
  assert.ok(await gone(pid), `the launcher's child (pid ${pid}) outlived the timeout`);
}

/**
 * Which branch of `killProcessTree` this platform runs. Each platform can only
 * exercise its own — POSIX has no `taskkill`, Windows no process groups — so
 * the test names the branch it proves rather than skipping the other one, and
 * the Windows branch is proven where the suite runs on Windows.
 */
const branch =
  process.platform === "win32" ? "Windows: taskkill /T /F" : "POSIX: the negative pid's process group";

test(`cancelling a call kills the launcher's whole tree (${branch})`, () => cancelKillsTheTree());
test(`a timed-out call kills the launcher's whole tree (${branch})`, () => timeoutKillsTheTree());

test("a normal run returns its output and exit code unchanged", async () => {
  const ok = await run(node(echo), ["0", "--json"]);
  assert.deepEqual(ok, { stdout: JSON.stringify(["0", "--json"]), stderr: "note", code: 0 });

  const failed = await run(node(echo), ["2"]);
  assert.equal(failed.code, 2);
  assert.equal(failed.stdout, JSON.stringify(["2"]));
});

test("a call already cancelled never starts", async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    run(node(echo), ["0"], undefined, { signal: controller.signal }),
    PynakesCancelledError,
  );
});

test("an executable that does not exist is unavailable, not a protocol error", async () => {
  await assert.rejects(
    run({ executable: path.join(dir, "no-such-engine"), leadingArgs: [] }, ["--version"]),
    PynakesUnavailableError,
  );
});
