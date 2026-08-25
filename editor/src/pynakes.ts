/**
 * The single boundary between the extension and the pynakes engine.
 *
 * Everything the view knows about a bibliography arrives through the engine's
 * stable JSON envelope, and every change leaves through it. The extension
 * deliberately has no BibTeX parser, metadata schema, or selector-grammar
 * implementation of its own, so this is the only module that may spawn a
 * process, and no other module may interpret `.bib` text.
 *
 * Which engine gets run is decided in `engineDiscovery.ts`.
 */

import { execFile } from "node:child_process";
import type { PynakesCommand } from "./engineDiscovery";
import { extractVersion } from "./version";
import type {
  GroupsListEnvelope,
  GroupsTreeEnvelope,
  InspectEnvelope,
  KeysRenameEnvelope,
  LintEnvelope,
  RefCompareEnvelope,
  RefEditEnvelope,
  SearchEnvelope,
} from "./model";

export type { PynakesCommand } from "./engineDiscovery";

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

/** Human-readable form of an invocation, for error messages. */
export function describeCommand(command: PynakesCommand): string {
  return [command.executable, ...command.leadingArgs].join(" ");
}

interface RunResult {
  stdout: string;
  stderr: string;
  code: number;
}

/** Run one pynakes subcommand, resolving even when it exits non-zero. */
function run(command: PynakesCommand, args: string[], cwd?: string): Promise<RunResult> {
  const argv = [...command.leadingArgs, ...args];
  return new Promise((resolve, reject) => {
    execFile(
      command.executable,
      argv,
      { cwd, maxBuffer: MAX_BUFFER, timeout: TIMEOUT_MS, windowsHide: true },
      (error, stdout, stderr) => {
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
async function runJson<T>(command: PynakesCommand, args: string[], cwd?: string): Promise<T> {
  const result = await run(command, [...args, "--json"], cwd);
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

/**
 * Every entry with its fields, plus encoding, metadata, and duplicate keys.
 *
 * `--display` asks the engine for a `display` view per entry — title fields
 * with LaTeX markup and braces cleaned to plain text, and `author`/`editor`
 * split into individual, cleaned names — so the view never has to parse
 * BibTeX/LaTeX itself. It is read-only presentation data, never staged or
 * written back.
 */
export function inspectBib(
  command: PynakesCommand,
  filePath: string,
  cwd?: string,
): Promise<InspectEnvelope> {
  return runJson<InspectEnvelope>(command, ["inspect", filePath, "--display"], cwd);
}

/** The declared group hierarchy from the file's metadata. */
export function groupsTree(
  command: PynakesCommand,
  filePath: string,
  cwd?: string,
): Promise<GroupsTreeEnvelope> {
  return runJson<GroupsTreeEnvelope>(command, ["groups", "tree", filePath], cwd);
}

/** Group membership as the entries themselves declare it. */
export function groupsList(
  command: PynakesCommand,
  filePath: string,
  cwd?: string,
): Promise<GroupsListEnvelope> {
  return runJson<GroupsListEnvelope>(command, ["groups", "list", filePath], cwd);
}

/** Advisory validation findings. */
export function lintBib(
  command: PynakesCommand,
  filePath: string,
  cwd?: string,
): Promise<LintEnvelope> {
  return runJson<LintEnvelope>(command, ["lint", filePath], cwd);
}

/** Options mirroring the flags `search` actually accepts. */
export interface SearchOptions {
  query: string;
  /** Narrows *which* entries the query searches, exactly as `--where` does. */
  where?: string;
  fuzzy?: boolean;
  caseSensitive?: boolean;
}

/**
 * Run the engine's own search.
 *
 * `--where` narrows a query rather than standing alone, because that is the only
 * read-only path the engine exposes for the selector grammar. The extension does
 * not evaluate predicates itself.
 */
export function searchBib(
  command: PynakesCommand,
  filePath: string,
  options: SearchOptions,
  cwd?: string,
): Promise<SearchEnvelope> {
  const args = ["search", options.query, filePath];
  if (options.where?.trim()) {
    args.push("--where", options.where.trim());
  }
  if (options.fuzzy) {
    args.push("--fuzzy");
  }
  if (options.caseSensitive) {
    args.push("--case-sensitive");
  }
  return runJson<SearchEnvelope>(command, args, cwd);
}

/** A field-level change to one entry, as `ref edit` expresses it. */
export interface RefEditRequest {
  key: string;
  /** Fields to set or replace. */
  set: Record<string, string>;
  /** Fields to remove. */
  clear: string[];
  /** New entry type, when the type is being changed. */
  entryType?: string;
}

/** Build the argument list for one `ref edit` invocation. */
export function refEditArgs(filePath: string, request: RefEditRequest, dryRun: boolean): string[] {
  const args = ["ref", "edit", request.key, filePath];
  for (const [field, value] of Object.entries(request.set)) {
    args.push("--field", `${field}=${value}`);
  }
  for (const field of request.clear) {
    args.push("--clear-field", field);
  }
  if (request.entryType) {
    args.push("--type", request.entryType);
  }
  if (dryRun) {
    args.push("--dry-run");
  }
  args.push("--diff");
  return args;
}

/**
 * Apply (or preview) one entry's staged changes.
 *
 * With `dryRun` the engine reports the plan and diff without writing, which is
 * both the preview and the pre-commit safety check: the plan's `old` values
 * reveal whether the file still holds what the view was editing against.
 */
export function refEdit(
  command: PynakesCommand,
  filePath: string,
  request: RefEditRequest,
  dryRun: boolean,
  cwd?: string,
): Promise<RefEditEnvelope> {
  return runJson<RefEditEnvelope>(command, refEditArgs(filePath, request, dryRun), cwd);
}

/**
 * Compare one entry's fields against another reference (read-only).
 *
 * With `withKey`, compares against another entry already in the library —
 * no network access. Otherwise compares against a fetched DOI/arXiv remote
 * record; `online` gates that network call and is decided by the extension
 * host from the `pynakes.allowOnlineLookups` setting (on by default), never
 * by the webview. Without it the engine still runs (offline) and reports why
 * nothing could be compared.
 */
export function refCompare(
  command: PynakesCommand,
  filePath: string,
  key: string,
  online: boolean,
  cwd?: string,
  withKey?: string,
): Promise<RefCompareEnvelope> {
  const args = ["ref", "compare", key, filePath];
  if (withKey) {
    args.push("--with", withKey);
  } else if (online) {
    args.push("--online");
  }
  return runJson<RefCompareEnvelope>(command, args, cwd);
}

/**
 * Rename one citation key, rewriting matching `\cite{...}` keys in any TeX
 * sources the library's `tex-sources` metadata names.
 */
export function keysRename(
  command: PynakesCommand,
  filePath: string,
  oldKey: string,
  newKey: string,
  cwd?: string,
): Promise<KeysRenameEnvelope> {
  return runJson<KeysRenameEnvelope>(command, ["keys", "rename", filePath, oldKey, newKey], cwd);
}

/** Engine version string, or `undefined` when it cannot be determined. */
export async function engineVersion(
  command: PynakesCommand,
  cwd?: string,
): Promise<string | undefined> {
  try {
    const result = await run(command, ["--version"], cwd);
    return extractVersion(result.stdout);
  } catch {
    return undefined;
  }
}
