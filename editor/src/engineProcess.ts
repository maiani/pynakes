/**
 * Spawning the engine: the one place a process is started.
 *
 * `pynakes.ts` builds every invocation and names what each one returns; this
 * module only runs one and turns its output into an envelope or a typed error.
 * Kept apart so the argument builders read without the process plumbing, and
 * so the rules about how long a call may run and how it may be stopped live in
 * one place.
 */

import { spawn, type ChildProcess } from "node:child_process";
import type { PynakesCommand } from "./engineDiscovery";

/** Output JSON for a large library runs to megabytes; past this, something is wrong. */
const MAX_BUFFER = 64 * 1024 * 1024;

/** Upper bound on a single engine call, so a wedged process cannot hang the view. */
const TIMEOUT_MS = 60_000;

/** The engine could not be started at all — usually a wrong command setting. */
export class PynakesUnavailableError extends Error {
  constructor(
    public readonly command: string,
    public readonly reason: unknown,
  ) {
    super(`Could not run "${command}".`);
    this.name = "PynakesUnavailableError";
  }
}

/** The engine ran but produced something other than a JSON envelope. */
export class PynakesProtocolError extends Error {
  constructor(
    message: string,
    public readonly detail: string,
  ) {
    super(message);
    this.name = "PynakesProtocolError";
  }
}

/**
 * The call was stopped on request before it finished.
 *
 * Distinct from a protocol error: a killed process produces no envelope, and
 * that is the expected outcome of a cancellation rather than a broken contract.
 */
export class PynakesCancelledError extends Error {
  constructor(command: string) {
    super(`"${command}" was cancelled.`);
    this.name = "PynakesCancelledError";
  }
}

/** Human-readable form of an invocation, for error messages. */
export function describeCommand(command: PynakesCommand): string {
  return [command.executable, ...command.leadingArgs].join(" ");
}

export interface RunResult {
  stdout: string;
  stderr: string;
  code: number;
}

/** How one call may be bounded or stopped. */
export interface RunOptions {
  /**
   * Stops the process when aborted. Only for calls whose interruption the
   * engine tolerates — one whose every write is atomic.
   */
  signal?: AbortSignal;
  /** Milliseconds before the process is killed; `0` for no limit. */
  timeoutMs?: number;
}

/** How long a stopped process tree has to exit on SIGTERM before it is killed outright. */
const KILL_GRACE_MS = 2_000;

/**
 * Stop a process and everything it started.
 *
 * Killing only the spawned process is not enough: the engine is often run
 * through a launcher — a shell shim, `conda run`, a venv's console script —
 * whose Python child would keep running, and keep writing, after its parent
 * was stopped. On Linux and macOS the engine is spawned as the leader of its
 * own process group (`detached`), so signalling the negative pid reaches the
 * whole group. Windows has no process groups to signal; `taskkill /T` walks
 * the tree from the pid instead.
 */
export function killProcessTree(child: ChildProcess): void {
  const pid = child.pid;
  if (pid === undefined) {
    return;
  }
  if (process.platform === "win32") {
    // `/T` takes the children with it, `/F` because a console process ignores
    // a polite request. Its own failure (the tree already gone) is not ours.
    const killer = spawn("taskkill", ["/pid", String(pid), "/T", "/F"], {
      windowsHide: true,
      stdio: "ignore",
    });
    killer.on("error", () => child.kill());
    return;
  }
  const signalGroup = (signal: NodeJS.Signals): void => {
    try {
      process.kill(-pid, signal);
    } catch {
      // ESRCH: the group has already gone.
    }
  };
  signalGroup("SIGTERM");
  // A process that traps SIGTERM still goes; one that has already exited makes
  // this a no-op. Unref'd so a pending grace timer never holds the host open.
  setTimeout(() => signalGroup("SIGKILL"), KILL_GRACE_MS).unref();
}

/** Run one pynakes subcommand, resolving even when it exits non-zero. */
export function run(
  command: PynakesCommand,
  args: string[],
  cwd?: string,
  options: RunOptions = {},
): Promise<RunResult> {
  const argv = [...command.leadingArgs, ...args];
  const label = describeCommand(command);
  return new Promise((resolve, reject) => {
    const { signal } = options;
    if (signal?.aborted) {
      reject(new PynakesCancelledError(label));
      return;
    }
    let child: ChildProcess;
    try {
      child = spawn(command.executable, argv, {
        cwd,
        windowsHide: true,
        // Its own process group on POSIX, so a stop reaches its children too.
        // Not on Windows, where it would open a console window instead.
        detached: process.platform !== "win32",
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch (error) {
      reject(new PynakesUnavailableError(label, error));
      return;
    }

    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];
    let size = 0;
    let stopped: "cancelled" | "timeout" | "overflow" | undefined;
    let settled = false;

    const stop = (reason: NonNullable<typeof stopped>): void => {
      if (stopped === undefined) {
        stopped = reason;
        killProcessTree(child);
      }
    };
    const collect = (into: Buffer[]) => (chunk: Buffer) => {
      size += chunk.length;
      if (size > MAX_BUFFER) {
        stop("overflow");
        return;
      }
      into.push(chunk);
    };
    child.stdout?.on("data", collect(stdout));
    child.stderr?.on("data", collect(stderr));

    const timeoutMs = options.timeoutMs ?? TIMEOUT_MS;
    const timer = timeoutMs > 0 ? setTimeout(() => stop("timeout"), timeoutMs) : undefined;
    const onAbort = (): void => stop("cancelled");
    signal?.addEventListener("abort", onAbort, { once: true });

    const finish = (): void => {
      settled = true;
      if (timer) {
        clearTimeout(timer);
      }
      signal?.removeEventListener("abort", onAbort);
    };

    child.on("error", (error: NodeJS.ErrnoException) => {
      if (settled) {
        return;
      }
      // Only a failure to start leaves no `close` to wait for.
      if (error.code === "ENOENT" || error.code === "EACCES") {
        finish();
        reject(new PynakesUnavailableError(label, error));
      }
    });
    // `close`, not `exit`: the pipes are drained, and the process reaped.
    child.on("close", (code) => {
      if (settled) {
        return;
      }
      finish();
      const out = Buffer.concat(stdout).toString("utf8");
      const err = Buffer.concat(stderr).toString("utf8");
      switch (stopped) {
        case "cancelled":
          reject(new PynakesCancelledError(label));
          return;
        case "overflow":
          reject(
            new PynakesProtocolError(
              `${label} ${args[0] ?? ""} produced more than ${MAX_BUFFER} bytes of output.`.trim(),
              err.trim(),
            ),
          );
          return;
        case "timeout":
          resolve({
            stdout: out,
            stderr: [err, `Stopped after ${timeoutMs} ms without finishing.`]
              .filter(Boolean)
              .join("\n"),
            code: code ?? -1,
          });
          return;
        default:
          resolve({ stdout: out, stderr: err, code: code ?? -1 });
      }
    });
  });
}

/**
 * Run a subcommand with `--json` and return its envelope.
 *
 * An error envelope is a legitimate result, not an exception: the engine reports
 * a malformed file or a rejected query on exit 1 with `{"status": "error", ...}`,
 * and the view displays it. Only a broken *contract* throws.
 */
export async function runJson<T>(
  command: PynakesCommand,
  args: string[],
  cwd?: string,
  options?: RunOptions,
): Promise<T> {
  // Before any end-of-options marker, so it stays an option rather than
  // becoming one more operand.
  const marker = args.indexOf("--");
  const withJson =
    marker === -1 ? [...args, "--json"] : [...args.slice(0, marker), "--json", ...args.slice(marker)];
  const result = await run(command, withJson, cwd, options);
  const text = result.stdout.trim();
  const label = `${describeCommand(command)} ${args[0] ?? ""}`.trim();
  if (!text) {
    throw new PynakesProtocolError(
      `${label} produced no output (exit ${result.code}).`,
      result.stderr.trim(),
    );
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new PynakesProtocolError(
      `${label} did not return JSON (exit ${result.code}).`,
      [result.stderr.trim(), text.slice(0, 2000)].filter(Boolean).join("\n\n"),
    );
  }
  const status = (parsed as { status?: string })?.status;
  if (status !== "success" && status !== "error" && status !== "conflict") {
    throw new PynakesProtocolError(`${label} returned an unrecognized envelope.`, text.slice(0, 2000));
  }
  return parsed as T;
}
