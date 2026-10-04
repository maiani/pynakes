/**
 * The staged-edit model: what the user has changed but not yet committed.
 *
 * Pure and `vscode`-free so it can be unit tested. Staging lives in the
 * extension rather than the webview because a webview is disposed when its tab
 * is hidden, and pending changes to a file must not evaporate with it.
 *
 * Every staged field remembers the value it was edited *against*. That base is
 * what makes a safe commit possible: the `corpus batch --dry-run` preview
 * reports the value the file currently holds, and comparing the two detects
 * that the file moved under the editor before the edit was approved. (A move
 * *after* that preview is the engine's to catch, through `--expect-sha256`.)
 */

import type { RefEditPlanEntry } from "./model";
import type { RefEditRequest } from "./pynakes";

/** One field's pending change. */
export interface StagedField {
  /** The new value, or null to remove the field. */
  value: string | null;
  /** The value when editing started; null when the field did not exist. */
  base: string | null;
}

/** One entry's pending changes. */
export interface StagedEntry {
  key: string;
  fields: Record<string, StagedField>;
  /** A pending entry-type change. */
  entryType?: { value: string; base: string };
}

/** All pending changes for one bibliography. */
export interface StagingState {
  entries: Record<string, StagedEntry>;
}

export function emptyStaging(): StagingState {
  return { entries: {} };
}

/** True when nothing is pending. */
export function isEmpty(state: StagingState): boolean {
  return Object.keys(state.entries).length === 0;
}

/** Drop an entry that no longer holds any pending change. */
function prune(state: StagingState, key: string): void {
  const entry = state.entries[key];
  if (!entry) {
    return;
  }
  if (Object.keys(entry.fields).length === 0 && !entry.entryType) {
    delete state.entries[key];
  }
}

function entryFor(state: StagingState, key: string): StagedEntry {
  return (state.entries[key] ??= { key, fields: {} });
}

/**
 * Stage a field value.
 *
 * Setting a field back to the value it started from unstages it, so the pending
 * set always describes real differences and an accidental round trip leaves
 * nothing behind.
 */
export function stageField(
  state: StagingState,
  key: string,
  field: string,
  value: string | null,
  base: string | null,
): StagingState {
  const entry = entryFor(state, key);
  if (value === base) {
    delete entry.fields[field];
  } else {
    // Preserve the original base across repeated edits of the same field.
    const existing = entry.fields[field];
    entry.fields[field] = { value, base: existing ? existing.base : base };
  }
  prune(state, key);
  return state;
}

/** Discard one field's pending change. */
export function unstageField(state: StagingState, key: string, field: string): StagingState {
  const entry = state.entries[key];
  if (entry) {
    delete entry.fields[field];
    prune(state, key);
  }
  return state;
}

/** Stage an entry-type change, unstaging it when set back to the original. */
export function stageType(
  state: StagingState,
  key: string,
  value: string,
  base: string,
): StagingState {
  const entry = entryFor(state, key);
  if (value === base) {
    delete entry.entryType;
  } else {
    const existing = entry.entryType;
    entry.entryType = { value, base: existing ? existing.base : base };
  }
  prune(state, key);
  return state;
}

/** Discard everything pending for one entry. */
export function discardEntry(state: StagingState, key: string): StagingState {
  delete state.entries[key];
  return state;
}

/** How much is pending, for the commit bar. */
export function stagedCount(state: StagingState): { fields: number; entries: number } {
  let fields = 0;
  for (const entry of Object.values(state.entries)) {
    fields += Object.keys(entry.fields).length + (entry.entryType ? 1 : 0);
  }
  return { fields, entries: Object.keys(state.entries).length };
}

/**
 * Translate pending changes into one `ref.edit` request per entry, all of
 * which are committed together as one `corpus batch`.
 *
 * Sorted by citation key so a preview and the commit that follows it apply in
 * the same order, and so the diff a user approved is the diff that lands.
 */
export function toRequests(state: StagingState): RefEditRequest[] {
  return Object.values(state.entries)
    .sort((a, b) => a.key.localeCompare(b.key))
    .map((entry) => {
      const set: Record<string, string> = {};
      const clear: string[] = [];
      for (const field of Object.keys(entry.fields).sort()) {
        const staged = entry.fields[field];
        if (staged.value === null) {
          clear.push(field);
        } else {
          set[field] = staged.value;
        }
      }
      const request: RefEditRequest = { key: entry.key, set, clear };
      if (entry.entryType) {
        request.entryType = entry.entryType.value;
      }
      return request;
    });
}

/**
 * The heading over a staged commit's diff.
 *
 * The commit is one write, so its diff is one diff; the heading names the
 * entries it covers rather than pretending each has a diff of its own.
 */
export function diffHeading(keys: string[]): string {
  if (keys.length === 1) {
    return keys[0];
  }
  return `${keys.length} entries: ${keys.join(", ")}`;
}

/** A staged change whose base no longer matches what the file holds. */
export interface StagingConflict {
  key: string;
  field: string;
  /** The value the edit was made against. */
  expected: string | null;
  /** The value the engine reports the file currently holds. */
  actual: string | null;
}

/**
 * Compare a dry-run plan against what was staged.
 *
 * The engine reports the current value of every field it would change. When
 * that disagrees with the base a change was staged against, the file moved
 * underneath the editor and committing would silently overwrite the newer
 * value, so the caller must refuse rather than write. A pending entry-type
 * change is checked the same way against the plan's reported type.
 *
 * A change the plan omits is not a conflict: the engine leaves out fields that
 * already hold the requested value (and unchanged types), which means the
 * intended change is simply already in place.
 */
export function findConflicts(
  entry: StagedEntry,
  plan: RefEditPlanEntry | undefined,
): StagingConflict[] {
  const conflicts: StagingConflict[] = [];
  const planned = plan?.fields ?? {};
  for (const [field, staged] of Object.entries(entry.fields)) {
    const change = planned[field];
    if (!change) {
      continue;
    }
    if (change.old !== staged.base) {
      conflicts.push({ key: entry.key, field, expected: staged.base, actual: change.old });
    }
  }
  // The engine compares types case-insensitively, so the base must too.
  const plannedType = plan?.type;
  if (entry.entryType && plannedType) {
    if (plannedType.old.trim().toLowerCase() !== entry.entryType.base.trim().toLowerCase()) {
      conflicts.push({
        key: entry.key,
        field: "@type",
        expected: entry.entryType.base,
        actual: plannedType.old,
      });
    }
  }
  return conflicts;
}
