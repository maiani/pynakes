/**
 * Composing the engine's several reads into one view of a bibliography, and
 * running staged changes through it.
 *
 * Knows nothing about VS Code: it takes a resolved command and a file path.
 */

import { buildGroupTree, groupsByEntry, indexLint, type GroupNode, type LintIndex } from "./insights";
import type { EntryRow, FieldComparison, InspectError, RefEditPlanEntry, Summary } from "./model";
import { summarize, toRows } from "./model";
import {
  type PynakesCommand,
  type RefEditRequest,
  type SearchOptions,
  groupsList,
  groupsTree,
  inspectBib,
  lintBib,
  refCompare,
  refEdit,
  searchBib,
} from "./pynakes";

/** Everything the view needs about a bibliography. */
export interface LibraryRead {
  rows: EntryRow[];
  summary: Summary;
  groups: GroupNode[];
  /** Group names per citation key, for the detail pane. */
  groupsByEntry: Record<string, string[]>;
  lint: LintIndex | null;
  /** Non-fatal problems with the supplementary reads. */
  warnings: string[];
}

export type LibraryReadResult =
  | { ok: true; read: LibraryRead }
  | { ok: false; error: InspectError };

/**
 * Read a bibliography.
 *
 * `inspect` is authoritative: if it fails, there is no view to show. The group
 * and lint reads are supplementary, so a failure there degrades to a warning
 * and an otherwise working table rather than an error page. All four run
 * concurrently — they are independent reads of the same immutable file.
 */
export async function readLibrary(
  command: PynakesCommand,
  filePath: string,
  cwd?: string,
): Promise<LibraryReadResult> {
  const [inspected, tree, list, lint] = await Promise.all([
    inspectBib(command, filePath, cwd),
    groupsTree(command, filePath, cwd),
    groupsList(command, filePath, cwd),
    lintBib(command, filePath, cwd),
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

  return {
    ok: true,
    read: {
      rows: toRows(inspected),
      summary: summarize(inspected),
      groups: buildGroupTree(tree.status === "success" ? tree.tree : [], membership),
      groupsByEntry: list.status === "success" ? groupsByEntry(list) : {},
      lint: lint.status === "success" ? indexLint(lint) : null,
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

/** Outcome of comparing one entry against its DOI/arXiv remote record. */
export type CompareOutcome =
  | {
      ok: true;
      source: string | null;
      identifier: string | null;
      fields: FieldComparison[];
      warnings: string[];
    }
  | { ok: false; message: string };

/** Compare one entry's fields against remote metadata (read-only). */
export async function compareEntry(
  command: PynakesCommand,
  filePath: string,
  key: string,
  online: boolean,
  cwd?: string,
): Promise<CompareOutcome> {
  const envelope = await refCompare(command, filePath, key, online, cwd);
  if (envelope.status === "error") {
    return { ok: false, message: envelope.message };
  }
  return {
    ok: true,
    source: envelope.source,
    identifier: envelope.identifier,
    fields: envelope.fields,
    warnings: envelope.warnings.map((warning) => warning.message),
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
