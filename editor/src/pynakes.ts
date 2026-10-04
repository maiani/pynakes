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
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { PynakesCommand } from "./engineDiscovery";
import { extractVersion } from "./version";
import type {
  AssetCheckEnvelope,
  CorpusBatchEnvelope,
  DedupeCheckEnvelope,
  DedupeMergeEnvelope,
  GroupsListEnvelope,
  GroupsTreeEnvelope,
  MutationEnvelope,
  InspectEnvelope,
  KeysRenameEnvelope,
  LintEnvelope,
  RefCompareEnvelope,
  RefEditOperation,
  SearchEnvelope,
  TexScanEnvelope,
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

/**
 * Which entries the linked TeX sources cite, and where each citation is.
 *
 * Scans the sources the library's `tex-sources` metadata names. A library that
 * declares none is an error envelope (`NoSources`), not an empty report — the
 * caller decides whether that is worth reporting.
 */
export function texScan(
  command: PynakesCommand,
  filePath: string,
  cwd?: string,
): Promise<TexScanEnvelope> {
  return runJson<TexScanEnvelope>(command, ["tex", "scan", filePath], cwd);
}

/**
 * Linked-file and Pinax material state: which of an entry's files exist.
 *
 * Read-only without `--strict`, so issues come back in the envelope rather than
 * as a non-zero exit. Every path in the result is resolved by the engine; the
 * client never constructs one.
 */
export function assetCheck(
  command: PynakesCommand,
  filePath: string,
  cwd?: string,
): Promise<AssetCheckEnvelope> {
  return runJson<AssetCheckEnvelope>(command, ["asset", "check", filePath], cwd);
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

/**
 * The tail every modifying invocation shares: `--dry-run` for a preview, the
 * diff always, and — on the write a preview was approved for — the digest that
 * preview reported, so the engine refuses rather than writes if the file moved
 * while the approval was pending.
 */
function modifyingFlags(args: string[], dryRun: boolean, expectSha256?: string): string[] {
  if (dryRun) {
    args.push("--dry-run");
  }
  args.push("--diff");
  if (expectSha256) {
    args.push("--expect-sha256", expectSha256);
  }
  return args;
}

/** A field-level change to one entry, as a `ref.edit` batch operation expresses it. */
export interface RefEditRequest {
  key: string;
  /** Fields to set or replace. */
  set: Record<string, string>;
  /** Fields to remove. */
  clear: string[];
  /** New entry type, when the type is being changed. */
  entryType?: string;
}

/** Spell one entry's change in the engine's batch vocabulary. */
export function refEditOperation(request: RefEditRequest): RefEditOperation {
  const operation: RefEditOperation = { op: "ref.edit", key: request.key };
  if (Object.keys(request.set).length > 0) {
    operation.fields = request.set;
  }
  if (request.clear.length > 0) {
    operation.clear_fields = request.clear;
  }
  if (request.entryType) {
    operation.entry_type = request.entryType;
  }
  return operation;
}

/** Build the argument list for one `corpus batch` invocation over an operations file. */
export function corpusBatchArgs(
  filePath: string,
  opsFile: string,
  dryRun: boolean,
  expectSha256?: string,
): string[] {
  return modifyingFlags(["corpus", "batch", filePath, "--ops-file", opsFile], dryRun, expectSha256);
}

/**
 * Apply (or preview) every staged entry's changes as one `corpus batch`.
 *
 * One invocation, so one write: the engine applies all of them or none, and
 * the preview is the single diff of exactly that write. With `dryRun` it also
 * reports each field's current value in the plan, which is the pre-commit
 * safety check, and the file's digest, which the write passes back.
 *
 * The operations travel in a temporary file rather than on the command line: a
 * commit of several long fields (abstracts, say) would otherwise approach the
 * platform's argument-length limit.
 */
export async function corpusBatch(
  command: PynakesCommand,
  filePath: string,
  requests: RefEditRequest[],
  dryRun: boolean,
  expectSha256?: string,
  cwd?: string,
): Promise<CorpusBatchEnvelope> {
  const dir = await fs.promises.mkdtemp(path.join(os.tmpdir(), "pynakes-batch-"));
  try {
    const opsFile = path.join(dir, "ops.json");
    await fs.promises.writeFile(opsFile, JSON.stringify(requests.map(refEditOperation)), "utf-8");
    return await runJson<CorpusBatchEnvelope>(
      command,
      corpusBatchArgs(filePath, opsFile, dryRun, expectSha256),
      cwd,
    );
  } finally {
    await fs.promises.rm(dir, { recursive: true, force: true });
  }
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

/**
 * Entry- and group-level mutations.
 *
 * These change which entries exist, or which groups they belong to, so none of
 * them fits the field-level staging map. What they share instead is the
 * engine's modifying-command contract: `--dry-run --diff` previews without
 * writing and the same invocation without it applies. The view runs every one
 * through the same preview-then-approve path, so the diff shown is the diff
 * that lands — the property the staged field editor already keeps. The write
 * carries the preview's `source_sha256` as `expectSha256`, so it lands only on
 * the file the preview read.
 *
 * Each builder is exported separately from its runner so the argument list can
 * be asserted in a unit test without spawning anything.
 */

/** A new entry written by hand: a key, a type, and whatever fields are known. */
export interface RefAddRequest {
  key: string;
  entryType: string;
  fields: Record<string, string>;
}

export function refAddArgs(
  filePath: string,
  request: RefAddRequest,
  dryRun: boolean,
  expectSha256?: string,
): string[] {
  const args = ["ref", "add", request.key, filePath, "--type", request.entryType];
  for (const [field, value] of Object.entries(request.fields)) {
    if (value.trim()) {
      args.push("--field", `${field}=${value}`);
    }
  }
  return modifyingFlags(args, dryRun, expectSha256);
}

export function refAdd(
  command: PynakesCommand,
  filePath: string,
  request: RefAddRequest,
  dryRun: boolean,
  cwd?: string,
  expectSha256?: string,
): Promise<MutationEnvelope> {
  return runJson<MutationEnvelope>(
    command,
    refAddArgs(filePath, request, dryRun, expectSha256),
    cwd,
  );
}

/**
 * An entry resolved from an identifier.
 *
 * This is the one view action that reaches the network, and it does so only
 * because the user typed an identifier and asked for it — the same explicit
 * rule the CLI keeps. `allowDuplicate` is how the caller answers the engine's
 * exit-2 conflict when the reference is already present; it is never passed
 * speculatively.
 */
export interface RefImportRequest {
  identifier: string;
  key?: string;
  allowDuplicate?: boolean;
}

export function refImportArgs(
  filePath: string,
  request: RefImportRequest,
  dryRun: boolean,
  expectSha256?: string,
): string[] {
  const args = ["ref", "import", request.identifier, filePath];
  if (request.key?.trim()) {
    args.push("--key", request.key.trim());
  }
  if (request.allowDuplicate) {
    args.push("--allow-duplicate");
  }
  return modifyingFlags(args, dryRun, expectSha256);
}

export function refImport(
  command: PynakesCommand,
  filePath: string,
  request: RefImportRequest,
  dryRun: boolean,
  cwd?: string,
  expectSha256?: string,
): Promise<MutationEnvelope> {
  return runJson<MutationEnvelope>(
    command,
    refImportArgs(filePath, request, dryRun, expectSha256),
    cwd,
  );
}

/**
 * Remove entries by citation key.
 *
 * `keepFiles` maps to `--keep-files`. The engine's default is to delete an
 * entry's Pinax materials along with it, which is a deletion the view must
 * name out loud before it happens rather than discover afterwards.
 */
export function refRemoveArgs(
  filePath: string,
  keys: string[],
  keepFiles: boolean,
  dryRun: boolean,
  expectSha256?: string,
): string[] {
  const args = ["ref", "remove", filePath, ...keys];
  if (keepFiles) {
    args.push("--keep-files");
  }
  return modifyingFlags(args, dryRun, expectSha256);
}

export function refRemove(
  command: PynakesCommand,
  filePath: string,
  keys: string[],
  keepFiles: boolean,
  dryRun: boolean,
  cwd?: string,
  expectSha256?: string,
): Promise<MutationEnvelope> {
  return runJson<MutationEnvelope>(
    command,
    refRemoveArgs(filePath, keys, keepFiles, dryRun, expectSha256),
    cwd,
  );
}

/** Add or remove one entry's membership of one group. */
export function groupsEntryArgs(
  filePath: string,
  key: string,
  group: string,
  member: boolean,
  dryRun: boolean,
  expectSha256?: string,
): string[] {
  const args = [
    "groups",
    member ? "add-entry" : "remove-entry",
    filePath,
    key,
    group,
  ];
  return modifyingFlags(args, dryRun, expectSha256);
}

export function groupsEntry(
  command: PynakesCommand,
  filePath: string,
  key: string,
  group: string,
  member: boolean,
  dryRun: boolean,
  cwd?: string,
  expectSha256?: string,
): Promise<MutationEnvelope> {
  return runJson<MutationEnvelope>(
    command,
    groupsEntryArgs(filePath, key, group, member, dryRun, expectSha256),
    cwd,
  );
}

/** Which entries the engine judges to be the same work (read-only). */
export function dedupeCheck(
  command: PynakesCommand,
  filePath: string,
  cwd?: string,
): Promise<DedupeCheckEnvelope> {
  return runJson<DedupeCheckEnvelope>(command, ["dedupe", "check", filePath], cwd);
}

/**
 * Collapse duplicate clusters into their first entry.
 *
 * With `keys`, only the clusters containing one of them are merged — the
 * per-pair decision a review actually makes. Naming the cluster by a key inside
 * it, rather than by an index or a reconstructed description, is what keeps the
 * merge the engine's: the view never says which entries to fold together.
 *
 * The engine's merge is conservative, filling only fields the survivor lacks,
 * and it refuses outright when two copies disagree irreconcilably.
 */
export function dedupeMergeArgs(
  filePath: string,
  keys: string[] | undefined,
  dryRun: boolean,
  expectSha256?: string,
): string[] {
  const args = ["dedupe", "merge", filePath];
  for (const key of keys ?? []) {
    args.push("--key", key);
  }
  return modifyingFlags(args, dryRun, expectSha256);
}

export function dedupeMerge(
  command: PynakesCommand,
  filePath: string,
  keys: string[] | undefined,
  dryRun: boolean,
  cwd?: string,
  expectSha256?: string,
): Promise<DedupeMergeEnvelope> {
  return runJson<DedupeMergeEnvelope>(
    command,
    dedupeMergeArgs(filePath, keys, dryRun, expectSha256),
    cwd,
  );
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
