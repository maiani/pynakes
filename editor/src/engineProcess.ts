/**
 * Spawning the engine: the one place a process is started.
 *
 * `pynakes.ts` builds every invocation and names what each one returns; this
 * module only runs one and turns its output into an envelope or a typed error.
 * Kept apart so the argument builders read without the process plumbing, and
 * so the rules about how long a call may run and how it may be stopped live in
 * one place.
 */

import { execFile } from "node:child_process";
import type { PynakesCommand } from "./engineDiscovery";

/** Output JSON for a large library is well past `execFile`'s 1 MB default. */
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

/** Run one pynakes subcommand, resolving even when it exits non-zero. */
export function run(
  command: PynakesCommand,
  args: string[],
  cwd?: string,
  options: RunOptions = {},
): Promise<RunResult> {
  const argv = [...command.leadingArgs, ...args];
  return new Promise((resolve, reject) => {
    execFile(
      command.executable,
      argv,
      {
        cwd,
        maxBuffer: MAX_BUFFER,
        timeout: options.timeoutMs ?? TIMEOUT_MS,
        windowsHide: true,
        signal: options.signal,
      },
      (error, stdout, stderr) => {
        if (options.signal?.aborted) {
          reject(new PynakesCancelledError(describeCommand(command)));
          return;
        }
        if (error && typeof (error as NodeJS.ErrnoException).errno === "number") {
          const spawnFailure = (error as NodeJS.ErrnoException).code;
          if (spawnFailure === "ENOENT" || spawnFailure === "EACCES") {
            reject(new PynakesUnavailableError(describeCommand(command), error));
            return;
          }
        }
        const code = error && typeof error.code === "number" ? error.code : 0;
        resolve({ stdout, stderr, code });
      },
    );
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
