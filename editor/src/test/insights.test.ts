/** Tests for the group-tree and lint projections. */

import assert from "node:assert/strict";
import { test } from "node:test";
import { buildGroupTree, groupsByEntry, indexLint, worseSeverity } from "../insights.js";
import type { GroupNode } from "../insights.js";
import type { GroupsTreeNode, LintSuccess } from "../model.js";

function node(name: string, parent = "", extra: Partial<GroupsTreeNode> = {}): GroupsTreeNode {
  return {
    name,
    parent,
    context: 0,
    color: "",
    expanded: true,
    description: "",
    group_type: "StaticGroup",
    field: "",
    expression: "",
    case_sensitive: false,
    separator: "",
    search_flags: "",
    entries: [],
    ...extra,
  };
}

test("buildGroupTree nests declared groups and attaches membership", () => {
  const roots = buildGroupTree(
    [node("All"), node("Physics", "All"), node("Optics", "Physics")],
    { Physics: ["Newton1687"], Optics: ["Huygens1690"] },
  );

  assert.equal(roots.length, 1);
  assert.equal(roots[0].name, "All");
  assert.equal(roots[0].children[0].name, "Physics");
  assert.deepEqual(roots[0].children[0].keys, ["Newton1687"]);
  assert.equal(roots[0].children[0].children[0].name, "Optics");
  assert.deepEqual(roots[0].children[0].depth, 1);
  assert.deepEqual(roots[0].children[0].children[0].depth, 2);
});

test("groupKeys collects an entire subtree", () => {
  const roots = buildGroupTree(
    [node("All"), node("Physics", "All"), node("Optics", "Physics")],
    { Physics: ["Newton1687"], Optics: ["Huygens1690"] },
  );

  // The webview keeps its own copy of this walk (media/state.js); here it only
  // pins the shape the sidebar counts depend on.
  const keys = new Set<string>();
  const walk = (current: GroupNode): void => {
    for (const key of current.keys) {
      keys.add(key);
    }
    for (const child of current.children) {
      walk(child);
    }
  };
  walk(roots[0]);
  assert.deepEqual([...keys].sort(), ["Huygens1690", "Newton1687"]);
});

test("a group only entries mention is surfaced as undeclared", () => {
  // The hierarchy and the membership come from different places in the file and
  // can genuinely disagree; the mismatch is shown rather than hidden.
  const roots = buildGroupTree([node("All")], { Ghost: ["Newton1687"] });

  const ghost = roots.find((group) => group.name === "Ghost");
  assert.ok(ghost, "the undeclared group should appear as a root");
  assert.equal(ghost.undeclared, true);
  assert.deepEqual(ghost.keys, ["Newton1687"]);
});

test("an undeclared group with no members is not invented", () => {
  const roots = buildGroupTree([node("All")], { Empty: [] });

  assert.deepEqual(
    roots.map((group) => group.name),
    ["All"],
  );
});

test("a node naming a missing parent still appears, as a root", () => {
  const roots = buildGroupTree([node("Orphan", "Nowhere")], {});

  assert.deepEqual(
    roots.map((group) => group.name),
    ["Orphan"],
  );
});

test("a parent cycle does not hang the projection", () => {
  const roots = buildGroupTree([node("A", "B"), node("B", "A")], {});

  // Whatever the arrangement, walking the tree must terminate and lose
  // nothing — the sidebar flattens exactly this way.
  const names: string[] = [];
  const walk = (nodes: GroupNode[], seen: Set<GroupNode>): void => {
    for (const group of nodes) {
      if (seen.has(group)) {
        return;
      }
      seen.add(group);
      names.push(group.name);
      walk(group.children, seen);
      seen.delete(group);
    }
  };
  walk(roots, new Set());
  assert.ok(names.includes("A") || names.includes("B"));
  assert.ok(names.length <= 2);
});

function lint(issues: LintSuccess["issues"], counts: Partial<LintSuccess> = {}): LintSuccess {
  return {
    status: "success",
    action: "lint",
    file: "refs.bib",
    issue_count: issues.length,
    errors: 0,
    warnings: 0,
    info: issues.length,
    by_category: {},
    issues,
    ...counts,
  };
}

test("indexLint groups findings by entry and by category", () => {
  const index = indexLint(
    lint(
      [
        { type: "missing_doi", severity: "info", category: "consistency", fixer: null, message: "no DOI", key: "A" },
        { type: "bad_year", severity: "error", category: "validity", fixer: null, message: "bad year", key: "A" },
        { type: "dup", severity: "warning", category: "validity", fixer: null, message: "dup", key: "B" },
      ],
      { errors: 1, warnings: 1, info: 1 },
    ),
  );

  assert.equal(index.byKey.A.length, 2);
  // The row marker shows the worst severity on the entry.
  assert.equal(index.worstByKey.A, "error");
  assert.equal(index.worstByKey.B, "warning");
  assert.deepEqual(
    index.byCategory.map((group) => group.category),
    ["validity", "consistency"],
  );
  assert.deepEqual(index.counts, { errors: 1, warnings: 1, info: 1, total: 3 });
});

test("findings without an entry key are kept as file-level", () => {
  const index = indexLint(
    lint([
      { type: "encoding", severity: "warning", category: "file", fixer: null, message: "odd encoding", key: null },
    ]),
  );

  assert.equal(index.fileLevel.length, 1);
  assert.deepEqual(index.byKey, {});
});

test("worseSeverity ranks error above warning above info", () => {
  assert.equal(worseSeverity("info", "warning"), "warning");
  assert.equal(worseSeverity("error", "warning"), "error");
  assert.equal(worseSeverity("info", "info"), "info");
});

test("groupsByEntry inverts membership and sorts each entry's groups", () => {
  const byEntry = groupsByEntry({
    status: "success",
    action: "groups_list",
    file: "refs.bib",
    groups: { Optics: ["Newton1687"], Mechanics: ["Newton1687"], Waves: ["Huygens1690"] },
  });

  assert.deepEqual(byEntry.Newton1687, ["Mechanics", "Optics"]);
  assert.deepEqual(byEntry.Huygens1690, ["Waves"]);
});
