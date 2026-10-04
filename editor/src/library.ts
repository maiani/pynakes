/**
 * Composing the engine's several reads into one view of a bibliography, and
 * running staged changes through it.
 *
 * Knows nothing about VS Code: it takes a resolved command and a file path.
 */

import {
  buildGroupTree,
  groupsByEntry,
  indexCitations,
  indexLint,
  indexMaterials,
  type CitationIndex,
  type GroupNode,
  type LintIndex,
  type MaterialIndex,
} from "./insights";
import type {
  DuplicateCluster,
  EntryRow,
  FieldComparison,
  InspectError,
  MutationEnvelope,
  RefCompareWarning,
  RefEditPlanEntry,
  Summary,
} from "./model";
import { summarize, toRows } from "./model";
import {
  type PynakesCommand,
  type RefAddRequest,
  type RefEditRequest,
  type RefImportRequest,
  type SearchOptions,
  assetCheck,
  corpusBatch,
  dedupeCheck,
  dedupeMerge,
  groupsEntry,
  groupsList,
  groupsTree,
  inspectBib,
  keysRename,
  lintBib,
  refAdd,
  refCompare,
  refImport,
  refRemove,
  searchBib,
  texScan,
} from "./pynakes";

/** Everything the view needs about a bibliography. */
export interface LibraryRead {
  rows: EntryRow[];
  summary: Summary;
  groups: GroupNode[];
  /** Group names per citation key, for the detail pane. */
  groupsByEntry: Record<string, string[]>;
  lint: LintIndex | null;
  /** What the linked TeX sources cite, when any are declared and readable. */
  citations: CitationIndex | null;
  /** Which of each entry's materials are on disk, when any are linked. */
  materials: MaterialIndex | null;
  /** Non-fatal problems with the supplementary reads. */
  warnings: string[];
}

export type LibraryReadResult =
  | { ok: true; read: LibraryRead }
  | { ok: false; error: InspectError };

/**
 * Read a bibliography.
 *
 * `inspect` is authoritative: if it fails, there is no view to show. Every
 * other read is supplementary, so a failure there degrades to a warning and an
 * otherwise working table rather than an error page. They all run concurrently
 * — independent reads of a file nothing is writing.
 *
 * `neighbourPath` is where the citation and material reads look, and it is
 * deliberately not `filePath`. Those two reads are about the files *around* the
 * bibliography — the `.tex` sources that cite it, the PDFs it points to — and
 * every path leading to them (`tex-sources`, `pinax-files-dir`, a relative
 * `file` field) is resolved by the engine relative to the `.bib`'s own
 * directory. A buffer with unsaved changes is read through a mirror in a
 * temporary directory, where all of those would resolve to nothing and the view
 * would claim a library has no sources and no materials. So the caller passes
 * the document's real path on disk, and omits it when the document has none
 * (never saved, or not a local file) — the cost being that unsaved edits to a
 * `file` field or to `tex-sources` are not reflected until the file is saved.
 */
export async function readLibrary(
  command: PynakesCommand,
  filePath: string,
  cwd?: string,
  neighbourPath?: string,
): Promise<LibraryReadResult> {
  const [inspected, tree, list, lint, scan, assets] = await Promise.all([
    inspectBib(command, filePath, cwd),
    groupsTree(command, filePath, cwd),
    groupsList(command, filePath, cwd),
    lintBib(command, filePath, cwd),
    neighbourPath ? texScan(command, neighbourPath, cwd) : undefined,
    neighbourPath ? assetCheck(command, neighbourPath, cwd) : undefined,
  ]);

  if (inspected.status === "error") {
    return { ok: false, error: inspected };
  }

  const warnings: string[] = [];
  const membership = list.status === "success" ? list.groups : {};
  if (list.status === "error") {
    warnings.push(`Group membership unavailable: ${list.message}`);
  }
  if (tree.status === "error") {
    warnings.push(`Group hierarchy unavailable: ${tree.message}`);
  }
  if (lint.status === "error") {
    warnings.push(`Validation unavailable: ${lint.message}`);
  }
  // A library that declares no TeX sources is the ordinary case, not a problem
  // to report: the engine says `NoSources` and the view simply shows no
  // citation state. Anything else went wrong and is worth saying out loud.
  if (scan?.status === "error" && scan.error !== "NoSources") {
    warnings.push(`Citations unavailable: ${scan.message}`);
  }
  if (assets?.status === "error") {
    warnings.push(`Material state unavailable: ${assets.message}`);
  }

  return {
    ok: true,
    read: {
      rows: toRows(inspected),
      summary: summarize(inspected),
      groups: buildGroupTree(tree.status === "success" ? tree.tree : [], membership),
      groupsByEntry: list.status === "success" ? groupsByEntry(list) : {},
      lint: lint.status === "success" ? indexLint(lint) : null,
      citations: scan?.status === "success" ? indexCitations(scan) : null,
      materials: assets?.status === "success" ? indexMaterials(assets) : null,
      warnings,
    },
  };
}

/** Outcome of running the engine's own search. */
export type SearchOutcome =
  | { ok: true; keys: string[]; ranked: boolean; count: number }
  | { ok: false; message: string };

/** Run the engine's search and reduce it to the keys the table should show. */
export async function runSearch(
  command: PynakesCommand,
  filePath: string,
  options: SearchOptions,
  cwd?: string,
): Promise<SearchOutcome> {
  const envelope = await searchBib(command, filePath, options, cwd);
  if (envelope.status === "error") {
    return { ok: false, message: envelope.message };
  }
  return {
    ok: true,
    keys: envelope.matches.map((match) => match.key),
    ranked: envelope.ranked,
    count: envelope.count,
  };
}

/** Said when a write was refused because the file moved under its approved preview. */
export const FILE_MOVED_MESSAGE =
  "The file changed while this change was awaiting approval, so nothing was written. " +
  "Review the current state and apply again.";

/** Said when the engine's preview carried no digest to make the write conditional on. */
export const NO_FINGERPRINT_MESSAGE =
  "Nothing was written: the engine did not report the file's fingerprint, so the write " +
  "could not be guarded against a concurrent change. Update pynakes, or let the " +
  "extension use its bundled engine.";

/** What the engine reports it would change in one staged entry. */
export interface PreviewEntry {
  key: string;
  plan?: RefEditPlanEntry;
}

/**
 * A modifying call that did not apply.
 *
 * `conflict` is the engine's exit 2 — it declined rather than failed — and
 * `error` names which conflict, so a caller can tell a file that moved
 * (`ExternalModification`) from a question it was asked. Either way nothing
 * was written, which is the one thing every caller must act on.
 */
export interface NotApplied {
  ok: false;
  conflict: boolean;
  error?: string;
  message: string;
}

export type PreviewResult =
  | {
      ok: true;
      entries: PreviewEntry[];
      /** The single diff of the one write the commit would make. */
      diff: string;
      warnings: string[];
      /** The file's digest as the preview read it; the commit passes it back. */
      sourceSha256?: string;
    }
  | NotApplied;

function notApplied(envelope: { status: "error" | "conflict"; error: string; message: string }): NotApplied {
  return {
    ok: false,
    conflict: envelope.status === "conflict",
    error: envelope.error,
    message: envelope.message,
  };
}

/**
 * Dry-run every staged change as the one `corpus batch` the commit will run.
 *
 * The caller sorted the requests, so a preview and the commit that follows it
 * apply the same operations in the same order, and the diff approved is the
 * diff that lands.
 */
export async function previewEdits(
  command: PynakesCommand,
  filePath: string,
  requests: RefEditRequest[],
  cwd?: string,
): Promise<PreviewResult> {
  const envelope = await corpusBatch(command, filePath, requests, true, undefined, cwd);
  if (envelope.status !== "success") {
    return notApplied(envelope);
  }
  return {
    ok: true,
    entries: requests.map((request) => ({
      key: request.key,
      plan: envelope.plan?.entries?.find((candidate) => candidate.key === request.key),
    })),
    diff: envelope.diff ?? "",
    warnings: envelope.warnings ?? [],
    sourceSha256: envelope.source_sha256,
  };
}

/** Outcome of comparing one entry against another reference. */
export type CompareOutcome =
  | {
      ok: true;
      source: string | null;
      identifier: string | null;
      fields: FieldComparison[];
      warnings: RefCompareWarning[];
    }
  | { ok: false; message: string };

/**
 * Compare one entry's fields against another reference (read-only).
 *
 * Pass `withKey` to compare against another local entry instead of fetching
 * a remote record.
 */
export async function compareEntry(
  command: PynakesCommand,
  filePath: string,
  key: string,
  online: boolean,
  cwd?: string,
  withKey?: string,
): Promise<CompareOutcome> {
  const envelope = await refCompare(command, filePath, key, online, cwd, withKey);
  if (envelope.status === "error") {
    return { ok: false, message: envelope.message };
  }
  return {
    ok: true,
    source: envelope.source,
    identifier: envelope.identifier,
    fields: envelope.fields,
    warnings: envelope.warnings,
  };
}

export type CommitResult =
  | {
      ok: true;
      /** Entries written — every staged one, since the batch is all or nothing. */
      applied: string[];
      warnings: string[];
    }
  | NotApplied;

/**
 * Apply staged changes as one `corpus batch`: one write, all of them or none.
 *
 * `expectSha256` is the digest the approved preview reported. The engine
 * refuses with an `ExternalModification` conflict, writing nothing, when the
 * file no longer has it — an edit made while the approval dialog was open is
 * never overwritten.
 */
export async function commitEdits(
  command: PynakesCommand,
  filePath: string,
  requests: RefEditRequest[],
  expectSha256: string,
  cwd?: string,
): Promise<CommitResult> {
  const envelope = await corpusBatch(command, filePath, requests, false, expectSha256, cwd);
  if (envelope.status !== "success") {
    return notApplied(envelope);
  }
  return {
    ok: true,
    applied: requests.map((request) => request.key),
    warnings: envelope.warnings ?? [],
  };
}

/** Outcome of renaming one citation key. */
export type RenameKeyOutcome =
  | { ok: true; old: string; new: string; sourceOccurrences: number }
  | { ok: false; message: string };

/**
 * Rename one citation key, rewriting matching `\cite{...}` keys in any linked
 * TeX sources. The engine itself refuses a target key that already exists or
 * a source key that is ambiguous (a duplicate) — both surface here as `ok: false`.
 */
export async function renameEntryKey(
  command: PynakesCommand,
  filePath: string,
  oldKey: string,
  newKey: string,
  cwd?: string,
): Promise<RenameKeyOutcome> {
  const envelope = await keysRename(command, filePath, oldKey, newKey, cwd);
  if (envelope.status !== "success") {
    return { ok: false, message: envelope.message };
  }
  return {
    ok: true,
    old: envelope.old,
    new: envelope.new,
    sourceOccurrences: envelope.source_occurrences,
  };
}


// ---------------------------------------------------------------------------
// Entry- and group-level mutations
// ---------------------------------------------------------------------------

/**
 * One entry- or group-level change, named independently of the command that
 * performs it.
 *
 * The view does not branch on the operation once it has built one of these: it
 * previews, shows the diff, asks, and applies. Keeping the shape uniform is
 * what makes a single approval path correct for all of them, rather than six
 * near-copies that could drift apart in what they check before writing.
 */
export type Mutation =
  | { kind: "add"; request: RefAddRequest }
  | { kind: "import"; request: RefImportRequest }
  | { kind: "remove"; keys: string[]; keepFiles: boolean }
  | { kind: "group"; key: string; group: string; member: boolean }
  /** `keys` names the cluster(s) to merge; omitted means every cluster. */
  | { kind: "dedupeMerge"; keys?: string[] };

/** A short label for the diff panel and the confirmation prompt. */
export function describeMutation(mutation: Mutation): string {
  switch (mutation.kind) {
    case "add":
      return `Add ${mutation.request.key}`;
    case "import":
      return `Import ${mutation.request.identifier}`;
    case "remove":
      return mutation.keys.length === 1
        ? `Remove ${mutation.keys[0]}`
        : `Remove ${mutation.keys.length} entries`;
    case "group":
      return mutation.member
        ? `Add ${mutation.key} to "${mutation.group}"`
        : `Remove ${mutation.key} from "${mutation.group}"`;
    case "dedupeMerge":
      return mutation.keys?.length
        ? `Merge ${mutation.keys.join(", ")}`
        : "Merge every duplicate";
  }
}

function runMutation(
  command: PynakesCommand,
  filePath: string,
  mutation: Mutation,
  dryRun: boolean,
  cwd?: string,
  expectSha256?: string,
): Promise<MutationEnvelope> {
  switch (mutation.kind) {
    case "add":
      return refAdd(command, filePath, mutation.request, dryRun, cwd, expectSha256);
    case "import":
      return refImport(command, filePath, mutation.request, dryRun, cwd, expectSha256);
    case "remove":
      return refRemove(
        command,
        filePath,
        mutation.keys,
        mutation.keepFiles,
        dryRun,
        cwd,
        expectSha256,
      );
    case "group":
      return groupsEntry(
        command,
        filePath,
        mutation.key,
        mutation.group,
        mutation.member,
        dryRun,
        cwd,
        expectSha256,
      );
    case "dedupeMerge":
      return dedupeMerge(command, filePath, mutation.keys, dryRun, cwd, expectSha256);
  }
}

export type MutationOutcome =
  | {
      ok: true;
      diff: string;
      warnings: string[];
      modified: boolean;
      key?: string;
      /** The file's digest as this call read it; a preview's goes back on the write. */
      sourceSha256?: string;
    }
  /**
   * The engine refused and named the choices — exit 2, never guessed past.
   * `error` says which refusal: `ExternalModification` is a file that moved
   * under an approved preview.
   */
  | {
      ok: false;
      conflict: true;
      error: string;
      message: string;
      options: { id: string; description: string }[];
    }
  | { ok: false; conflict?: false; message: string };

function reduce(envelope: MutationEnvelope): MutationOutcome {
  if (envelope.status === "error") {
    return { ok: false, message: envelope.message };
  }
  if (envelope.status === "conflict") {
    return {
      ok: false,
      conflict: true,
      error: envelope.error,
      message: envelope.message,
      options: envelope.options ?? [],
    };
  }
  return {
    ok: true,
    diff: envelope.diff ?? "",
    warnings: envelope.warnings ?? [],
    modified: envelope.modified,
    key: envelope.key,
    sourceSha256: envelope.source_sha256,
  };
}

/** Preview a mutation: what it would change, written nowhere. */
export async function previewMutation(
  command: PynakesCommand,
  filePath: string,
  mutation: Mutation,
  cwd?: string,
): Promise<MutationOutcome> {
  return reduce(await runMutation(command, filePath, mutation, true, cwd));
}

/**
 * Apply a mutation that has already been previewed and approved.
 *
 * `expectSha256` is the digest that preview reported: the engine writes only
 * if the file still has it, and otherwise answers with an
 * `ExternalModification` conflict and writes nothing.
 */
export async function applyMutation(
  command: PynakesCommand,
  filePath: string,
  mutation: Mutation,
  expectSha256: string,
  cwd?: string,
): Promise<MutationOutcome> {
  return reduce(await runMutation(command, filePath, mutation, false, cwd, expectSha256));
}

export type DuplicatesOutcome =
  | { ok: true; clusters: DuplicateCluster[]; duplicateEntries: number }
  | { ok: false; message: string };

/** Which entries the engine judges to be the same work (read-only). */
export async function findDuplicates(
  command: PynakesCommand,
  filePath: string,
  cwd?: string,
): Promise<DuplicatesOutcome> {
  const envelope = await dedupeCheck(command, filePath, cwd);
  if (envelope.status === "error") {
    return { ok: false, message: envelope.message };
  }
  return { ok: true, clusters: envelope.clusters, duplicateEntries: envelope.duplicate_entries };
}
