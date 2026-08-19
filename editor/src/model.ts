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

export interface InspectEntry {
  key: string;
  type: string;
  fields: Record<string, string>;
  resolved_fields?: Record<string, string>;
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

/** What the extension posts to the webview on a successful read. */
export interface RenderPayload {
  rows: EntryRow[];
  summary: Summary;
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

/** Project the engine's entry list onto table rows, preserving file order. */
export function toRows(envelope: InspectSuccess): EntryRow[] {
  const duplicates = new Set(Object.keys(envelope.duplicate_keys ?? {}));
  return envelope.entries.map((entry, index) => ({
    index,
    key: entry.key,
    type: entry.type,
    author: formatNames(entry.fields.author ?? entry.fields.editor ?? ""),
    title: collapseWhitespace(entry.fields.title ?? entry.fields.shorttitle ?? ""),
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

/** Build the message payload for a successful read. */
export function toRenderPayload(envelope: InspectSuccess): RenderPayload {
  return { rows: toRows(envelope), summary: summarize(envelope) };
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

/** What `ref edit` reports about one entry's change. */
export interface RefEditPlanEntry {
  change: string;
  key: string;
  fields?: Record<string, { old: string | null; new: string | null }>;
}

export interface RefEditSuccess {
  status: "success";
  action: "ref_edit";
  file: string;
  dry_run: boolean;
  modified: boolean;
  modified_entries: number;
  warnings: string[];
  plan: {
    summary: Record<string, number>;
    entries: RefEditPlanEntry[];
  };
  diff?: string;
}

export type RefEditEnvelope = RefEditSuccess | InspectError;
