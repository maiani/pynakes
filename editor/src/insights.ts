/**
 * Pure projections of the engine's group and lint reads onto what the sidebar
 * and findings panel display. No `vscode` import, no engine calls, no parsing.
 */

import type { GroupsListSuccess, GroupsTreeNode, LintIssue, LintSeverity, LintSuccess } from "./model";

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
      errors: envelope.errors,
      warnings: envelope.warnings,
      info: envelope.info,
      total: envelope.issue_count,
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
