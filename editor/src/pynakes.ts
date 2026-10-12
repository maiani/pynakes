/**
 * The single boundary between the extension and the pynakes engine.
 *
 * Everything the view knows about a bibliography arrives through the engine's
 * stable JSON envelope, and every change leaves through it. The extension
 * deliberately has no BibTeX parser, metadata schema, or selector-grammar
 * implementation of its own, so this module — with `engineProcess.ts`, which
 * holds the one function that spawns a process — is the only way to reach the
 * engine, and no other module may interpret `.bib` text.
 *
 * Which engine gets run is decided in `engineDiscovery.ts`.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { PynakesCommand } from "./engineDiscovery";
import { run, runJson } from "./engineProcess";
import { extractVersion } from "./version";
import type { AssetFetchEnvelope } from "./fetchPlan";
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
export {
  PynakesCancelledError,
  PynakesProtocolError,
  PynakesUnavailableError,
  describeCommand,
} from "./engineProcess";

/**
 * End of options: every token after it is an operand.
 *
 * Citation keys, group names, identifiers and search queries are the user's
 * text, and one that begins with `-` (a group called `-draft`, say) would
 * otherwise be read as an option. So every builder below that passes such a
 * value puts its options first and its operands after this marker, and
 * `runJson` adds `--json` before it.
 */
export const END_OF_OPTIONS = "--";

/** `head` (subcommand and library), then the options, then the operands. */
function invocation(head: string[], options: string[], operands: string[]): string[] {
  return operands.length > 0 ? [...head, ...options, END_OF_OPTIONS, ...operands] : [...head, ...options];
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
  return runJson<SearchEnvelope>(command, searchArgs(filePath, options), cwd);
}

export function searchArgs(filePath: string, options: SearchOptions): string[] {
  const flags: string[] = [];
  if (options.where?.trim()) {
    flags.push("--where", options.where.trim());
  }
  if (options.fuzzy) {
    flags.push("--fuzzy");
  }
  if (options.caseSensitive) {
    flags.push("--case-sensitive");
  }
  return invocation(["search", filePath], flags, [options.query]);
}

/**
 * The flags every modifying invocation shares: `--dry-run` for a preview, the
 * diff always, and — on the write a preview was approved for — the digest that
 * preview reported, so the engine refuses rather than writes if the file moved
 * while the approval was pending. Appended to `flags`, which go before any
 * operand.
 */
function modifyingFlags(flags: string[], dryRun: boolean, expectSha256?: string): string[] {
  if (dryRun) {
    flags.push("--dry-run");
  }
  flags.push("--diff");
  if (expectSha256) {
    flags.push("--expect-sha256", expectSha256);
  }
  return flags;
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
  const flags: string[] = [];
  if (withKey) {
    flags.push("--with", withKey);
  } else if (online) {
    flags.push("--online");
  }
  return runJson<RefCompareEnvelope>(
    command,
    invocation(["ref", "compare", filePath], flags, [key]),
    cwd,
  );
}

/**
 * Rename one citation key, rewriting matching `\cite{...}` keys in any TeX
 * sources the library's `tex-sources` metadata names, and moving the key's
 * Pinax materials with it.
 *
 * A modifying command like the mutations below, and run the same way: a
 * `--dry-run --diff` preview whose diff covers the `.bib` and every rewritten
 * source, then the identical call guarded by `--expect-sha256`.
 */
export function keysRename(
  command: PynakesCommand,
  filePath: string,
  oldKey: string,
  newKey: string,
  dryRun: boolean,
  cwd?: string,
  expectSha256?: string,
): Promise<KeysRenameEnvelope> {
  return runJson<KeysRenameEnvelope>(
    command,
    keysRenameArgs(filePath, oldKey, newKey, dryRun, expectSha256),
    cwd,
  );
}

export function keysRenameArgs(
  filePath: string,
  oldKey: string,
  newKey: string,
  dryRun: boolean,
  expectSha256?: string,
): string[] {
  return invocation(
    ["keys", "rename", filePath],
    modifyingFlags([], dryRun, expectSha256),
    [oldKey, newKey],
  );
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
  const flags = ["--type", request.entryType];
  for (const [field, value] of Object.entries(request.fields)) {
    if (value.trim()) {
      flags.push("--field", `${field}=${value}`);
    }
  }
  return invocation(
    ["ref", "add", filePath],
    modifyingFlags(flags, dryRun, expectSha256),
    [request.key],
  );
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
  const flags: string[] = [];
  if (request.key?.trim()) {
    flags.push("--key", request.key.trim());
  }
  if (request.allowDuplicate) {
    flags.push("--allow-duplicate");
  }
  return invocation(
    ["ref", "import", filePath],
    modifyingFlags(flags, dryRun, expectSha256),
    [request.identifier],
  );
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
  const flags = keepFiles ? ["--keep-files"] : [];
  return invocation(
    ["ref", "remove", filePath],
    modifyingFlags(flags, dryRun, expectSha256),
    keys,
  );
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
  create = false,
): string[] {
  // The engine refuses a group it does not know unless asked to create it, so
  // a typo in a group the library already has is never silently a new one.
  const flags = member && create ? ["--create"] : [];
  return invocation(
    ["groups", member ? "add-entry" : "remove-entry", filePath],
    modifyingFlags(flags, dryRun, expectSha256),
    [key, group],
  );
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
  create = false,
): Promise<MutationEnvelope> {
  return runJson<MutationEnvelope>(
    command,
    groupsEntryArgs(filePath, key, group, member, dryRun, expectSha256, create),
    cwd,
  );
}

/**
 * One edit to the declared group hierarchy — a node of `groups tree`, not an
 * entry's membership of one.
 *
 * Every rule about the tree is the engine's: whether a name is taken, whether a
 * move would make a cycle, which descendants a removal takes with it, which
 * entries a rename moves to the new name. The view
 * names the node and the requested change and nothing more.
 */
export type GroupTreeEdit =
  | { op: "add"; name: string; parent?: string }
  | { op: "rename"; name: string; newName: string }
  /** `parent` is `""` for the top level. */
  | { op: "move"; name: string; parent: string }
  | { op: "remove"; name: string }
  | { op: "describe"; name: string; description: string };

export function groupTreeArgs(
  filePath: string,
  edit: GroupTreeEdit,
  dryRun: boolean,
  expectSha256?: string,
): string[] {
  let subcommand: string;
  let flags: string[];
  let operands: string[];
  switch (edit.op) {
    case "add":
      subcommand = "add-group";
      flags = edit.parent ? ["--parent", edit.parent] : [];
      operands = [edit.name];
      break;
    case "rename":
      // `--members` carries the group's entries along, so a renamed group keeps
      // its members instead of leaving them under a name nothing declares.
      subcommand = "rename-group";
      flags = ["--members"];
      operands = [edit.name, edit.newName];
      break;
    case "move":
      // An empty parent is the engine's spelling of "top level", so it is
      // passed rather than omitted.
      subcommand = "move-group";
      flags = ["--parent", edit.parent];
      operands = [edit.name];
      break;
    case "remove":
      subcommand = "remove-group";
      flags = [];
      operands = [edit.name];
      break;
    case "describe":
      subcommand = "update-group";
      flags = ["--description", edit.description];
      operands = [edit.name];
      break;
  }
  return invocation(
    ["groups", subcommand, filePath],
    modifyingFlags(flags, dryRun, expectSha256),
    operands,
  );
}

export function groupTree(
  command: PynakesCommand,
  filePath: string,
  edit: GroupTreeEdit,
  dryRun: boolean,
  cwd?: string,
  expectSha256?: string,
): Promise<MutationEnvelope> {
  return runJson<MutationEnvelope>(
    command,
    groupTreeArgs(filePath, edit, dryRun, expectSha256),
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
  const flags: string[] = [];
  for (const key of keys ?? []) {
    flags.push("--key", key);
  }
  return invocation(["dedupe", "merge", filePath], modifyingFlags(flags, dryRun, expectSha256), []);
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

/**
 * Download an entry's missing Pinax materials — or every entry's, with no key.
 *
 * `material` is one of the engine's own `--material` values; without it the
 * library's `pinax-fetch-policy` decides. A dry run makes no network request
 * and creates nothing: it reports, per entry, each artifact a real run would
 * request and the path it would land at, which is what the approval names.
 * The real run is the only call here that may run for minutes, so it takes no
 * timeout and can be stopped through `signal` instead — every file it writes
 * lands atomically, so stopping it leaves no half-written material.
 */
export interface AssetFetchRequest {
  key?: string;
  material?: string;
}

export function assetFetchArgs(
  filePath: string,
  request: AssetFetchRequest,
  dryRun: boolean,
  expectSha256?: string,
): string[] {
  const flags = request.material ? ["--material", request.material] : [];
  return invocation(
    ["asset", "fetch", filePath],
    modifyingFlags(flags, dryRun, expectSha256),
    request.key ? [request.key] : [],
  );
}

export function assetFetch(
  command: PynakesCommand,
  filePath: string,
  request: AssetFetchRequest,
  dryRun: boolean,
  cwd?: string,
  expectSha256?: string,
  signal?: AbortSignal,
): Promise<AssetFetchEnvelope> {
  return runJson<AssetFetchEnvelope>(
    command,
    assetFetchArgs(filePath, request, dryRun, expectSha256),
    cwd,
    dryRun ? undefined : { signal, timeoutMs: 0 },
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
