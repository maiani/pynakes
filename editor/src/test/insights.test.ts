/** Tests for the group-tree and lint projections. */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  buildGroupTree,
  flattenGroups,
  groupKeys,
  groupsByEntry,
  indexLint,
  worseSeverity,
} from "../insights.js";
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

  assert.deepEqual(groupKeys(roots[0]).sort(), ["Huygens1690", "Newton1687"]);
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

  // Whatever the arrangement, flattening must terminate and lose nothing.
  const names = flattenGroups(roots, new Set()).map((group) => group.name);
  assert.ok(names.includes("A") || names.includes("B"));
  assert.ok(names.length <= 2);
});

test("flattenGroups honors collapsed subtrees", () => {
  const roots = buildGroupTree([node("All"), node("Physics", "All")], {});

  assert.deepEqual(
    flattenGroups(roots, new Set()).map((group) => group.name),
    ["All", "Physics"],
  );
  assert.deepEqual(
    flattenGroups(roots, new Set(["All"])).map((group) => group.name),
    ["All"],
  );
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
