/**
 * Pure projections of the engine's group and lint reads onto what the sidebar
 * and findings panel display. No `vscode` import, no engine calls, no parsing.
 */

import type {
  AssetCheckSuccess,
  CitationOccurrence,
  GroupsListSuccess,
  GroupsTreeNode,
  LintIssue,
  LintSeverity,
  LintSuccess,
  MaterialPaths,
  MaterialPresence,
  TexScanSuccess,
} from "./model";

/** A group as the sidebar shows it: hierarchy position plus its membership. */
export interface GroupNode {
  name: string;
  /** Nesting depth, 0 for a root group. */
  depth: number;
  groupType: string;
  color: string;
  description: string;
  /** Citation keys that declare membership in this group. */
  keys: string[];
  /** True when entries reference this group but the metadata never declares it. */
  undeclared: boolean;
  children: GroupNode[];
}

/**
 * Build the display tree.
 *
 * Two independent sources are combined, because they genuinely can disagree:
 * `groups tree` reports the hierarchy the file's metadata *declares*, while
 * `groups list` reports the membership entries actually *claim*. A group that
 * only entries mention is surfaced rather than hidden — that mismatch is
 * something the reader wants to see, not something for the client to reconcile.
 */
export function buildGroupTree(
  nodes: GroupsTreeNode[],
  membership: Record<string, string[]>,
): GroupNode[] {
  const byName = new Map<string, GroupNode>();
  for (const node of nodes) {
    byName.set(node.name, {
      name: node.name,
      depth: 0,
      groupType: node.group_type,
      color: node.color,
      description: node.description,
      keys: membership[node.name] ?? [],
      undeclared: false,
      children: [],
    });
  }

  const declaredBy = new Map(nodes.map((node) => [node.name, node]));
  const roots: GroupNode[] = [];
  for (const node of nodes) {
    const built = byName.get(node.name);
    if (!built) {
      continue;
    }
    const parent = node.parent ? byName.get(node.parent) : undefined;
    // A node becomes a root when it names no parent, names one that does not
    // exist, names itself, or sits in a parent cycle. Attaching a cycle would
    // leave every group in it unreachable from any root, which would make the
    // whole sidebar disappear rather than merely render oddly.
    if (parent && parent !== built && !inParentCycle(declaredBy, node.name)) {
      parent.children.push(built);
    } else {
      roots.push(built);
    }
  }

  const declared = new Set(nodes.map((node) => node.name));
  for (const [name, keys] of Object.entries(membership)) {
    if (declared.has(name) || keys.length === 0) {
      continue;
    }
    roots.push({
      name,
      depth: 0,
      groupType: "",
      color: "",
      description: "Referenced by entries but not declared in the file metadata.",
      keys,
      undeclared: true,
      children: [],
    });
  }

  assignDepth(roots, 0, new Set());
  return roots;
}

/** True when following declared parents from `name` loops instead of ending. */
function inParentCycle(nodes: Map<string, GroupsTreeNode>, name: string): boolean {
  const seen = new Set<string>([name]);
  let current = nodes.get(name);
  while (current?.parent) {
    if (seen.has(current.parent)) {
      return true;
    }
    seen.add(current.parent);
    current = nodes.get(current.parent);
  }
  return false;
}

/** Stamp nesting depth, guarding against a cycle in the declared parents. */
function assignDepth(nodes: GroupNode[], depth: number, seen: Set<GroupNode>): void {
  for (const node of nodes) {
    if (seen.has(node)) {
      node.children = [];
      continue;
    }
    seen.add(node);
    node.depth = depth;
    assignDepth(node.children, depth + 1, seen);
  }
}

const SEVERITY_RANK: Record<LintSeverity, number> = { error: 3, warning: 2, info: 1 };

/** Lint findings arranged for per-row markers, a grouped panel, and Problems. */
export interface LintIndex {
  /** Findings that name an entry, keyed by citation key. */
  byKey: Record<string, LintIssue[]>;
  /** The worst severity per entry, for the row marker. */
  worstByKey: Record<string, LintSeverity>;
  /** Findings about the file rather than any one entry. */
  fileLevel: LintIssue[];
  /** Findings grouped by category, in descending count order. */
  byCategory: Array<{ category: string; issues: LintIssue[] }>;
  /** Every finding, in report order — the feed for native diagnostics. */
  issues: LintIssue[];
  counts: { errors: number; warnings: number; info: number; total: number };
}

/** Return the more severe of two severities. */
export function worseSeverity(left: LintSeverity, right: LintSeverity): LintSeverity {
  return SEVERITY_RANK[left] >= SEVERITY_RANK[right] ? left : right;
}

/** Index lint findings by entry and by category. */
export function indexLint(envelope: LintSuccess): LintIndex {
  const byKey: Record<string, LintIssue[]> = {};
  const worstByKey: Record<string, LintSeverity> = {};
  const fileLevel: LintIssue[] = [];
  const categories = new Map<string, LintIssue[]>();

  for (const issue of envelope.issues) {
    const bucket = categories.get(issue.category) ?? [];
    bucket.push(issue);
    categories.set(issue.category, bucket);

    const key = issue.key;
    if (!key) {
      fileLevel.push(issue);
      continue;
    }
    (byKey[key] ??= []).push(issue);
    worstByKey[key] = worstByKey[key] ? worseSeverity(worstByKey[key], issue.severity) : issue.severity;
  }

  const byCategory = [...categories.entries()]
    .map(([category, issues]) => ({ category, issues }))
    .sort((a, b) => b.issues.length - a.issues.length || a.category.localeCompare(b.category));

  return {
    byKey,
    worstByKey,
    fileLevel,
    byCategory,
    issues: envelope.issues,
    counts: {
      errors: envelope.summary.errors,
      warnings: envelope.summary.warnings,
      info: envelope.summary.info,
      total: envelope.summary.issues,
    },
  };
}

/** One finding shaped for the Problems panel, with a zero-based line. */
export interface LintDiagnosticItem {
  severity: LintSeverity;
  message: string;
  /** The finding type, shown as the diagnostic's code. */
  code: string;
  /** Zero-based line; findings without one land on the first line. */
  line: number;
}

/**
 * Project findings onto native-diagnostics input.
 *
 * The engine reports one-based lines (or none for file-level findings); VS
 * Code wants zero-based ranges, so that conversion — the classic off-by-one —
 * happens exactly here and nowhere else.
 */
export function lintDiagnostics(issues: LintIssue[]): LintDiagnosticItem[] {
  return issues.map((issue) => ({
    severity: issue.severity,
    message: issue.message,
    code: issue.type,
    line: Math.max(0, (issue.line ?? 1) - 1),
  }));
}

/** Group membership per entry, for the detail pane. */
export function groupsByEntry(envelope: GroupsListSuccess): Record<string, string[]> {
  const byEntry: Record<string, string[]> = {};
  for (const [group, keys] of Object.entries(envelope.groups)) {
    for (const key of keys) {
      (byEntry[key] ??= []).push(group);
    }
  }
  for (const groups of Object.values(byEntry)) {
    groups.sort((a, b) => a.localeCompare(b));
  }
  return byEntry;
}

// ---------------------------------------------------------------------------
// Citations: what the linked TeX sources cite, and where.
// ---------------------------------------------------------------------------

/** One entry's citation state, and one undefined citation's, for the view. */
export interface CitationIndex {
  /** Occurrences per citation key, for every key any source cites. */
  byKey: Record<string, CitationOccurrence[]>;
  /** Keys cited by a source that no entry in this library declares. */
  undefinedKeys: string[];
  /** The `.tex`/`.aux` files the engine actually read. */
  sources: string[];
  /** True when a `\nocite{*}` makes every entry cited. */
  includeAll: boolean;
  /** How many distinct keys the sources cite. */
  citedCount: number;
}

/**
 * Index the citation scan for per-row markers, the detail pane, and diagnostics.
 *
 * `usages` covers every cited key, including ones no entry declares — those are
 * the undefined citations. Whether a *row* counts as cited is decided against
 * this map rather than against the report's own `used`/`unused` lists, because
 * the rows come from the buffer while the scan reads the saved file: an entry
 * added but not yet saved would otherwise be reported as "not in the library".
 */
export function indexCitations(envelope: TexScanSuccess): CitationIndex {
  const report = envelope.report;
  const byKey = report.usages ?? {};
  return {
    byKey,
    undefinedKeys: [...(report.missing ?? [])].sort((a, b) => a.localeCompare(b)),
    sources: report.sources ?? [],
    includeAll: Boolean(report.include_all),
    citedCount: report.cited_count ?? Object.keys(byKey).length,
  };
}

/** True when the sources cite this key — or a `\nocite{*}` cites everything. */
export function isCited(index: CitationIndex | null, key: string): boolean {
  if (!index) {
    return false;
  }
  return index.includeAll || (index.byKey[key]?.length ?? 0) > 0;
}

/** Undefined citations shaped for native diagnostics, grouped by source file. */
export interface CitationDiagnosticFile {
  path: string;
  items: Array<{
    key: string;
    message: string;
    /** Zero-based, for `vscode.Range`. */
    line: number;
    /** Zero-based column of the macro's backslash. */
    column: number;
    /** Length of the whole matched macro, so the squiggle covers it. */
    length: number;
  }>;
}

/**
 * Project undefined citations onto per-file diagnostics input.
 *
 * The engine reports one-based line and column; VS Code wants zero-based, so
 * that conversion happens exactly here, as it does for lint findings.
 */
export function citationDiagnostics(index: CitationIndex): CitationDiagnosticFile[] {
  const byPath = new Map<string, CitationDiagnosticFile["items"]>();
  for (const key of index.undefinedKeys) {
    for (const occurrence of index.byKey[key] ?? []) {
      const items = byPath.get(occurrence.path) ?? [];
      items.push({
        key,
        message: `No entry in this bibliography declares the citation key "${key}".`,
        line: Math.max(0, occurrence.line - 1),
        column: Math.max(0, occurrence.column - 1),
        length: occurrence.text.length,
      });
      byPath.set(occurrence.path, items);
    }
  }
  return [...byPath.entries()]
    .map(([path, items]) => ({
      path,
      items: items.sort((a, b) => a.line - b.line || a.column - b.column),
    }))
    .sort((a, b) => a.path.localeCompare(b.path));
}

// ---------------------------------------------------------------------------
// Materials: the files an entry points to, and whether they are on disk.
// ---------------------------------------------------------------------------

/** One file an entry points to, ready to list and to open. */
export interface Material {
  /** `published_pdf`, `preprint_pdf`, ... for Pinax; the descriptor kind or
   * `"file"` for a BibLaTeX `file`-field link. */
  kind: string;
  /** Human-readable label for the row. */
  label: string;
  /** Absolute path, or `null` when the engine could not resolve one. */
  path: string | null;
  /** True when the file (or directory) is actually there. */
  present: boolean;
  /** Where the link came from: the deterministic Pinax store or a `file` field. */
  origin: "pinax" | "file";
  /** For a `file`-field link that did not validate: why. */
  status?: string;
}

/** Materials per citation key, plus what the store itself reported. */
export interface MaterialIndex {
  byKey: Record<string, Material[]>;
  /** The Pinax store root, when the library declares one. */
  pinaxRoot: string | null;
  /** Material-shaped files in the store whose key is not in the library. */
  orphanCount: number;
  /** Manifest rows disagreeing with the files on disk. */
  driftCount: number;
  /** `file`-field links that did not resolve to an existing file of the right type. */
  brokenCount: number;
}

/** The Pinax material kinds, in the order they are shown. */
const PINAX_KINDS: Array<{ kind: keyof MaterialPresence & string; label: string }> = [
  { kind: "published_pdf", label: "Published PDF" },
  { kind: "preprint_pdf", label: "Preprint PDF" },
  { kind: "preprint_source", label: "Preprint source" },
  { kind: "supplement_pdf", label: "Supplement PDF" },
  { kind: "erratum_pdf", label: "Erratum PDF" },
];

/**
 * Index an `asset check` read by citation key.
 *
 * Every path here comes from the engine. The client must never *build* one:
 * `<key><suffix>.pdf` is the Pinax store's addressing scheme, and rebuilding it
 * in TypeScript would put that scheme in two places. A material with no path in
 * the envelope is not shown.
 */
export function indexMaterials(envelope: AssetCheckSuccess): MaterialIndex {
  const byKey: Record<string, Material[]> = {};

  for (const presence of envelope.pinax?.entries ?? []) {
    const materials: Material[] = [];
    for (const { kind, label } of PINAX_KINDS) {
      const path = presence.paths?.[kind as keyof MaterialPaths];
      if (typeof path !== "string" || !path) {
        continue;
      }
      const present = Boolean(presence[kind]);
      if (!present) {
        // A store lists a path for every kind whether or not it holds one;
        // only what exists is a material.
        continue;
      }
      materials.push({ kind, label, path, present, origin: "pinax" });
    }
    if (materials.length > 0) {
      byKey[presence.key] = materials;
    }
  }

  let brokenCount = 0;
  for (const link of envelope.files ?? []) {
    if (link.status !== "ok") {
      brokenCount += 1;
    }
    const label = link.description?.trim() || link.kind?.trim() || "Linked file";
    (byKey[link.entry_key] ??= []).push({
      kind: link.kind?.toLowerCase() || "file",
      label,
      path: link.resolved_path,
      present: link.status === "ok",
      origin: "file",
      status: link.status,
    });
  }

  return {
    byKey,
    pinaxRoot: envelope.pinax?.root ?? null,
    orphanCount: envelope.pinax?.orphans?.length ?? 0,
    driftCount: envelope.pinax?.drift?.length ?? 0,
    brokenCount,
  };
}
