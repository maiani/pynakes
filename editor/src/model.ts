/**
 * Types for the `pynakes inspect --json` envelope, plus the pure projection
 * from that envelope to what the table view shows.
 *
 * This module is deliberately free of any `vscode` import so it can be unit
 * tested with `node --test`. It contains no BibTeX parsing: every value here
 * was already extracted by the engine. The only transformation applied is
 * display tidying (whitespace collapsing, name-separator rendering), which
 * never travels back to the file.
 */

/**
 * Human-readable projection of an entry's title/name fields, from `inspect
 * --display`: LaTeX markup and braces already cleaned, name lists already
 * split. Present only for fields the entry actually has.
 */
export interface InspectDisplay {
  title?: string;
  booktitle?: string;
  maintitle?: string;
  subtitle?: string;
  author?: string[];
  editor?: string[];
}

export interface InspectEntry {
  key: string;
  type: string;
  fields: Record<string, string>;
  resolved_fields?: Record<string, string>;
  display?: InspectDisplay;
}

export interface MetadataNamespace {
  values: Record<string, string>;
  blocks: unknown[];
}

export interface InspectSuccess {
  status: "success";
  action: string;
  file: string;
  encoding: string;
  line_ending: string;
  entry_count: number;
  entries: InspectEntry[];
  strings: Record<string, string>;
  preamble: string[];
  comments: string[];
  jabref_metadata: MetadataNamespace;
  pynakes_metadata: MetadataNamespace;
  duplicate_keys: Record<string, number>;
}

export interface InspectError {
  status: "error";
  error: string;
  message: string;
  line?: number;
}

export type InspectEnvelope = InspectSuccess | InspectError;

/** One row of the entry table. */
export interface EntryRow {
  /** Position in file order; also the stable row identity. */
  index: number;
  key: string;
  type: string;
  author: string;
  title: string;
  year: string;
  venue: string;
  /** True when this citation key occurs more than once in the file. */
  duplicate: boolean;
  /** Every stored field, for the detail pane. */
  fields: Record<string, string>;
}

/** Headline facts about the file, shown in the toolbar and footer. */
export interface Summary {
  file: string;
  entryCount: number;
  encoding: string;
  lineEnding: string;
  typeCounts: Array<[string, number]>;
  duplicateKeys: Array<[string, number]>;
  stringCount: number;
  preambleCount: number;
  commentCount: number;
  jabrefKeys: string[];
  pynakesKeys: string[];
}

/** Fields consulted for the venue column, in precedence order. */
const VENUE_FIELDS = [
  "journaltitle",
  "journal",
  "booktitle",
  "eventtitle",
  "series",
  "publisher",
  "institution",
  "school",
  "organization",
  "howpublished",
] as const;

/** Collapse runs of whitespace so a wrapped source value fits one table cell. */
export function collapseWhitespace(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

/**
 * Render a BibTeX name list for display: `A and B` becomes `A; B`.
 *
 * The `and` separator is only recognized as a separator between names, so a
 * braced `{Smith and Sons}` corporate name is left intact.
 */
export function formatNames(value: string): string {
  const collapsed = collapseWhitespace(value);
  const names: string[] = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < collapsed.length; i += 1) {
    const char = collapsed[i];
    if (char === "{") {
      depth += 1;
    } else if (char === "}") {
      depth = Math.max(0, depth - 1);
    } else if (depth === 0 && collapsed.startsWith(" and ", i)) {
      names.push(collapsed.slice(start, i));
      i += 4;
      start = i + 1;
    }
  }
  names.push(collapsed.slice(start));
  return names
    .map((name) => name.trim())
    .filter((name) => name.length > 0)
    .join("; ");
}

/** The year a row sorts and displays by: `year`, else the year part of `date`. */
export function entryYear(fields: Record<string, string>): string {
  const year = fields.year ?? "";
  if (year.trim()) {
    return collapseWhitespace(year);
  }
  const date = fields.date ?? "";
  const match = /\d{4}/.exec(date);
  return match ? match[0] : "";
}

/** The container a work appeared in, whatever the entry type calls it. */
export function entryVenue(fields: Record<string, string>): string {
  for (const name of VENUE_FIELDS) {
    const value = fields[name];
    if (value && value.trim()) {
      return collapseWhitespace(value);
    }
  }
  return "";
}

/**
 * Author/editor names for the table.
 *
 * Prefers the engine's `display` view — already split into individual names
 * and cleaned of LaTeX markup and braces, so a brace-protected corporate name
 * like `{Smith and Sons}` is never misread as two people. Falls back to
 * client-side splitting of the raw field for an engine that predates
 * `inspect --display`.
 */
export function entryAuthor(entry: InspectEntry): string {
  const names = entry.display?.author ?? entry.display?.editor;
  if (names) {
    return names.map(collapseWhitespace).join("; ");
  }
  return formatNames(entry.fields.author ?? entry.fields.editor ?? "");
}

/** Project the engine's entry list onto table rows, preserving file order. */
export function toRows(envelope: InspectSuccess): EntryRow[] {
  const duplicates = new Set(Object.keys(envelope.duplicate_keys ?? {}));
  return envelope.entries.map((entry, index) => ({
    index,
    key: entry.key,
    type: entry.type,
    author: entryAuthor(entry),
    title: collapseWhitespace(
      entry.display?.title ?? entry.fields.title ?? entry.fields.shorttitle ?? "",
    ),
    year: entryYear(entry.fields),
    venue: entryVenue(entry.fields),
    duplicate: duplicates.has(entry.key),
    fields: entry.fields,
  }));
}

/** Summarize the file for the toolbar, footer, and empty states. */
export function summarize(envelope: InspectSuccess): Summary {
  const counts = new Map<string, number>();
  for (const entry of envelope.entries) {
    counts.set(entry.type, (counts.get(entry.type) ?? 0) + 1);
  }
  const typeCounts = [...counts.entries()].sort(
    (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]),
  );
  return {
    file: envelope.file,
    entryCount: envelope.entry_count,
    encoding: envelope.encoding,
    lineEnding: envelope.line_ending,
    typeCounts,
    duplicateKeys: Object.entries(envelope.duplicate_keys ?? {}).sort((a, b) =>
      a[0].localeCompare(b[0]),
    ),
    stringCount: Object.keys(envelope.strings ?? {}).length,
    preambleCount: (envelope.preamble ?? []).length,
    commentCount: (envelope.comments ?? []).length,
    jabrefKeys: Object.keys(envelope.jabref_metadata?.values ?? {}).sort(),
    pynakesKeys: Object.keys(envelope.pynakes_metadata?.values ?? {}).sort(),
  };
}

// ---------------------------------------------------------------------------
// Envelopes for the other engine reads and for the one write path.
// ---------------------------------------------------------------------------

/** One node of the declared group hierarchy, as `groups tree` reports it. */
export interface GroupsTreeNode {
  name: string;
  parent: string;
  context: number;
  color: string;
  expanded: boolean;
  description: string;
  group_type: string;
  field: string;
  expression: string;
  case_sensitive: boolean;
  separator: string;
  search_flags: string;
  entries: string[];
}

export interface GroupsTreeSuccess {
  status: "success";
  action: "groups_tree";
  file: string;
  tree: GroupsTreeNode[];
}

export type GroupsTreeEnvelope = GroupsTreeSuccess | InspectError;

export interface GroupsListSuccess {
  status: "success";
  action: "groups_list";
  file: string;
  /** Group name to the citation keys that declare membership in it. */
  groups: Record<string, string[]>;
}

export type GroupsListEnvelope = GroupsListSuccess | InspectError;

export type LintSeverity = "error" | "warning" | "info";

export interface LintIssue {
  type: string;
  severity: LintSeverity;
  category: string;
  fixer: string | null;
  message: string;
  /** Absent or null for findings about the file rather than one entry. */
  key?: string | null;
  field?: string | null;
  /** One-based source line, when the engine could locate the finding. */
  line?: number | null;
}

export interface LintSuccess {
  status: "success";
  action: "lint";
  file: string;
  issue_count: number;
  errors: number;
  warnings: number;
  info: number;
  by_category: Record<string, number>;
  issues: LintIssue[];
}

export type LintEnvelope = LintSuccess | InspectError;

export interface SearchMatch {
  key: string;
  type: string;
  matched_fields: string[];
  fields: Record<string, string>;
  score: number;
}

export interface SearchSuccess {
  status: "success";
  action: "search";
  file: string;
  query: string;
  where: string | null;
  ranked: boolean;
  count: number;
  matches: SearchMatch[];
}

export type SearchEnvelope = SearchSuccess | InspectError;

/** What a modifying command's `plan` reports about one entry's change. */
export interface RefEditPlanEntry {
  change: string;
  key: string;
  fields?: Record<string, { old: string | null; new: string | null }>;
  /** Present when the entry type changed. */
  type?: { old: string; new: string };
}

/** One field where the other side of a `ref compare` disagrees with the local entry. */
export interface FieldComparison {
  field: string;
  /** `null` when the entry has no value for this field at all. */
  local: string | null;
  other: string;
}

export interface RefCompareWarning {
  type: string;
  key: string;
  message: string;
}

export interface RefCompareSuccess {
  status: "success";
  action: "ref_compare";
  file: string;
  online: boolean;
  key: string;
  /** `"doi"` or `"arxiv"` for a fetched remote record, `"local"` for another
   * entry in the library; `null` when nothing could be compared. */
  source: string | null;
  /** That source's DOI, arXiv id, or citation key, respectively. */
  identifier: string | null;
  fields: FieldComparison[];
  warnings: RefCompareWarning[];
}

export type RefCompareEnvelope = RefCompareSuccess | InspectError;

/** What `keys rename` reports. */
export interface KeysRenameSuccess {
  status: "success";
  action: "keys_rename";
  file: string;
  dry_run: boolean;
  modified: boolean;
  modified_entries: number;
  warnings: { type: string; message: string }[];
  old: string;
  new: string;
  /** `\cite{...}` occurrences rewritten across linked TeX sources. */
  source_occurrences: number;
  diff?: string;
}

/** The new key is already taken, or the old one is ambiguous (a duplicate). */
export interface KeysRenameConflict {
  status: "conflict";
  error: string;
  message: string;
  key?: string;
  options: { id: string; description: string }[];
}

export type KeysRenameEnvelope = KeysRenameSuccess | KeysRenameConflict | InspectError;

// ---------------------------------------------------------------------------
// The bibliography's neighbours: the TeX sources that cite it, and the
// materials it points to. Both describe files *around* the `.bib`, which is
// why they are read from the saved file at its real location — see
// `readNeighbours` in `library.ts`.
// ---------------------------------------------------------------------------

/** One `\cite`-family occurrence, as `tex scan --json` locates it. */
export interface CitationOccurrence {
  path: string;
  /** One-based line within that file. */
  line: number;
  /** One-based column of the macro's leading backslash. */
  column: number;
  /** The whole matched macro, e.g. `\citep[see][]{A,B}`. */
  text: string;
  /** The citing command's name without its backslash: `cite`, `citep`, ... */
  macro: string;
}

export interface TexScanReport {
  used: string[];
  unused: string[];
  /** Cited keys no entry declares. */
  missing: string[];
  cited_count: number;
  /** Source files actually read. */
  sources: string[];
  /** True when a `\nocite{*}` makes every entry count as used. */
  include_all: boolean;
  /** Every occurrence, keyed by the citation key it cites. */
  usages: Record<string, CitationOccurrence[]>;
}

export interface TexScanSuccess {
  status: "success";
  action: "used";
  file: string;
  report: TexScanReport;
}

export type TexScanEnvelope = TexScanSuccess | InspectError;

/** One attachment parsed from an entry's BibLaTeX `file` field. */
export interface LinkedFile {
  entry_key: string;
  field: string;
  index: number;
  description: string | null;
  /** The path as the field stores it. */
  path: string;
  /** The descriptor's type word, e.g. `PDF` or `directory`. */
  kind: string | null;
  /** Absolute path the engine resolved it to, or `null` when it found none. */
  resolved_path: string | null;
  status: "ok" | "missing" | "wrong_type" | "unresolved";
}

/** Deterministic Pinax material paths for one citation key. */
export interface MaterialPaths {
  key: string;
  published_pdf: string;
  preprint_pdf: string;
  preprint_source: string;
  supplement_pdf: string;
  erratum_pdf: string;
}

/** Which of one entry's deterministic material paths exist on disk. */
export interface MaterialPresence {
  key: string;
  paths: MaterialPaths;
  published_pdf: boolean;
  preprint_pdf: boolean;
  preprint_source: boolean;
  supplement_pdf: boolean;
  erratum_pdf: boolean;
  any_present: boolean;
}

export interface PinaxScan {
  root: string;
  entries: MaterialPresence[];
  /** Material-shaped files whose citation key is not in the library. */
  orphans: Array<{ key: string; kind: string; path: string }>;
  drift: Array<Record<string, string>>;
}

export interface AssetCheckSuccess {
  status: "success";
  action: "files_check";
  file: string;
  checked: number;
  ok: number;
  missing: number;
  wrong_type: number;
  unresolved: number;
  files: LinkedFile[];
  issues: LinkedFile[];
  /** Present only when the library declares `pinax-files-dir`. */
  pinax?: PinaxScan;
}

export type AssetCheckEnvelope = AssetCheckSuccess | InspectError;

// ---------------------------------------------------------------------------
// Entry-level and group-level mutations.
//
// Unlike a field edit, these change *which* entries exist or which groups they
// belong to, so they cannot be expressed as a staged `ref.edit`. Every one of
// them emits the engine's shared modifying-command envelope, which is what lets
// the view run them all through one preview-and-approve path.
// ---------------------------------------------------------------------------

/** The keys every modifying command emits, whatever it changed. */
export interface MutationSuccess {
  status: "success";
  action: string;
  file: string;
  dry_run: boolean;
  modified: boolean;
  modified_entries: number;
  warnings: string[];
  plan?: {
    summary: Record<string, number>;
    entries: RefEditPlanEntry[];
  };
  diff?: string;
  /**
   * The sha256 of the file as this invocation read it. A preview's value goes
   * back as `--expect-sha256` on the write it was approved for, so that write
   * is refused if the file changed while the approval was pending.
   */
  source_sha256?: string;
  /**
   * The entry the command acted on, for the ones that act on exactly one:
   * `ref add`, `ref import`, and the two `groups` entry commands. Absent from
   * `ref remove` and `dedupe merge`, which can touch several.
   */
  key?: string;
}

/**
 * A modifying command that refused because the answer is the caller's to give
 * — an import whose reference is already present, a key already taken. The
 * engine exits 2 and names the choices rather than picking one.
 */
export interface MutationConflict {
  status: "conflict";
  error: string;
  message: string;
  key?: string;
  options: { id: string; description: string }[];
  /** An `ExternalModification` refused by `--expect-sha256`: the digest passed... */
  expected_sha256?: string;
  /** ...and the digest the file has now. */
  source_sha256?: string;
}

export type MutationEnvelope = MutationSuccess | MutationConflict | InspectError;

/** `ref add`: the entry it appended. */
export interface RefAddSuccess extends MutationSuccess {
  key: string;
  entry_type: string;
  fields: Record<string, string>;
}

/** `ref import`: what was resolved, and from where. */
export interface RefImportSuccess extends MutationSuccess {
  key: string;
  identifier: string;
  identifier_kind?: string;
  provider?: string;
  entry_type?: string;
}

/** `ref remove`: which keys went, and whether their materials went too. */
export interface RefRemoveSuccess extends MutationSuccess {
  removed_keys: string[];
  removed_count: number;
  keep_files: boolean;
}

/** `groups add-entry` / `groups remove-entry`. */
export interface GroupsEntrySuccess extends MutationSuccess {
  key: string;
  group: string;
}

/** What the engine matched a cluster on. */
export interface DuplicateIdentity {
  kind: string;
  value: string | null;
}

/** One set of entries the engine judges to be the same work. */
export interface DuplicateCluster {
  identity: DuplicateIdentity;
  /** Why they matched: `doi`, `arxiv`, `title`, ... */
  reason: string;
  entries: Array<{ key: string; type: string; fields: Record<string, string> }>;
  keys: string[];
}

export interface DedupeCheckSuccess {
  status: "success";
  action: "dedupe_check";
  file: string;
  has_duplicates: boolean;
  cluster_count: number;
  duplicate_entries: number;
  clusters: DuplicateCluster[];
}

export type DedupeCheckEnvelope = DedupeCheckSuccess | InspectError;

/** One cluster `dedupe merge` collapsed, and what it took from the copies. */
export interface MergedCluster {
  identity: DuplicateIdentity;
  /** The entry that survived; the others were folded into it. */
  primary_key: string;
  removed_keys: string[];
  field_changes: Record<string, string>;
  type_changed: string | null;
}

export interface DedupeMergeSuccess extends MutationSuccess {
  action: "dedupe_merge";
  clusters: DuplicateCluster[];
  merged: MergedCluster[];
  merged_clusters: number;
  removed_entries: number;
  field_changes: number;
}

// A cluster whose copies disagree irreconcilably is an exit-2 `DedupeConflict`.
export type DedupeMergeEnvelope = DedupeMergeSuccess | MutationConflict | InspectError;

/** One `corpus batch` operation, spelled in the engine's batch vocabulary. */
export interface RefEditOperation {
  op: "ref.edit";
  key: string;
  fields?: Record<string, string>;
  clear_fields?: string[];
  entry_type?: string;
}

/**
 * `corpus batch`: several operations previewed as one diff and written in one
 * commit — every one of them, or none.
 */
export interface CorpusBatchSuccess extends MutationSuccess {
  action: "batch";
  operations: { op: string; result: Record<string, unknown> }[];
}

export type CorpusBatchEnvelope = CorpusBatchSuccess | MutationConflict | InspectError;
