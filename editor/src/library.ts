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
  refEdit,
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

/** One entry's dry-run result. */
export interface PreviewEntry {
  key: string;
  diff: string;
  plan?: RefEditPlanEntry;
  warnings: string[];
}

export type PreviewResult =
  | { ok: true; entries: PreviewEntry[] }
  | { ok: false; key: string; message: string };

/**
 * Dry-run every staged change.
 *
 * These run concurrently: a dry run writes nothing, so there is no ordering
 * requirement, and the caller sorted the requests for a stable presentation.
 */
export async function previewEdits(
  command: PynakesCommand,
  filePath: string,
  requests: RefEditRequest[],
  cwd?: string,
): Promise<PreviewResult> {
  const envelopes = await Promise.all(
    requests.map((request) => refEdit(command, filePath, request, true, cwd)),
  );
  const entries: PreviewEntry[] = [];
  for (const [index, envelope] of envelopes.entries()) {
    const request = requests[index];
    if (envelope.status === "error") {
      return { ok: false, key: request.key, message: envelope.message };
    }
    entries.push({
      key: request.key,
      diff: envelope.diff ?? "",
      plan: envelope.plan?.entries?.find((candidate) => candidate.key === request.key),
      warnings: envelope.warnings ?? [],
    });
  }
  return { ok: true, entries };
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

export interface CommitResult {
  /** Entries written, in the order they were applied. */
  applied: string[];
  warnings: string[];
  /** Set when a write failed; entries before it were already applied. */
  failure?: { key: string; message: string };
}

/**
 * Apply staged changes.
 *
 * Strictly sequential, unlike the preview: each invocation rewrites the whole
 * file atomically, so concurrent writes would race and the last one would win
 * with the others lost. On the first failure it stops and reports what was
 * already applied, rather than continuing over a file in an unexpected state.
 */
export async function commitEdits(
  command: PynakesCommand,
  filePath: string,
  requests: RefEditRequest[],
  cwd?: string,
): Promise<CommitResult> {
  const applied: string[] = [];
  const warnings: string[] = [];
  for (const request of requests) {
    const envelope = await refEdit(command, filePath, request, false, cwd);
    if (envelope.status === "error") {
      return { applied, warnings, failure: { key: request.key, message: envelope.message } };
    }
    applied.push(request.key);
    warnings.push(...(envelope.warnings ?? []));
  }
  return { applied, warnings };
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
): Promise<MutationEnvelope> {
  switch (mutation.kind) {
    case "add":
      return refAdd(command, filePath, mutation.request, dryRun, cwd);
    case "import":
      return refImport(command, filePath, mutation.request, dryRun, cwd);
    case "remove":
      return refRemove(command, filePath, mutation.keys, mutation.keepFiles, dryRun, cwd);
    case "group":
      return groupsEntry(
        command,
        filePath,
        mutation.key,
        mutation.group,
        mutation.member,
        dryRun,
        cwd,
      );
    case "dedupeMerge":
      return dedupeMerge(command, filePath, mutation.keys, dryRun, cwd);
  }
}

export type MutationOutcome =
  | { ok: true; diff: string; warnings: string[]; modified: boolean; key?: string }
  /** The engine refused and named the choices — exit 2, never guessed past. */
  | { ok: false; conflict: true; message: string; options: { id: string; description: string }[] }
  | { ok: false; conflict?: false; message: string };

function reduce(envelope: MutationEnvelope): MutationOutcome {
  if (envelope.status === "error") {
    return { ok: false, message: envelope.message };
  }
  if (envelope.status === "conflict") {
    return {
      ok: false,
      conflict: true,
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

/** Apply a mutation that has already been previewed and approved. */
export async function applyMutation(
  command: PynakesCommand,
  filePath: string,
  mutation: Mutation,
  cwd?: string,
): Promise<MutationOutcome> {
  return reduce(await runMutation(command, filePath, mutation, false, cwd));
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
