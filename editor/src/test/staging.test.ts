/** Tests for the staged-edit model, including the pre-commit safety check. */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  discardEntry,
  emptyStaging,
  findConflicts,
  isEmpty,
  stageField,
  stageType,
  stagedCount,
  toRequests,
  unstageField,
} from "../staging.js";

test("staging a change records the value it was made against", () => {
  const state = stageField(emptyStaging(), "Newton1687", "year", "1686", "1687");

  assert.deepEqual(state.entries.Newton1687.fields.year, { value: "1686", base: "1687" });
  assert.deepEqual(stagedCount(state), { fields: 1, entries: 1 });
});

test("setting a field back to its original value unstages it", () => {
  let state = stageField(emptyStaging(), "Newton1687", "year", "1686", "1687");
  state = stageField(state, "Newton1687", "year", "1687", "1687");

  assert.ok(isEmpty(state), "the entry should be dropped once nothing differs");
});

test("repeated edits keep the original base rather than the last value", () => {
  let state = stageField(emptyStaging(), "Euler1748", "title", "Introductio", "Introductio in analysin");
  state = stageField(state, "Euler1748", "title", "Introductio in", "Introductio");

  // The base must remain the file's value, or the conflict check compares
  // against something the file never held.
  assert.equal(state.entries.Euler1748.fields.title.base, "Introductio in analysin");
  assert.equal(state.entries.Euler1748.fields.title.value, "Introductio in");
});

test("a new field stages against an absent base", () => {
  const state = stageField(emptyStaging(), "Euler1748", "note", "Reviewed", null);

  assert.deepEqual(state.entries.Euler1748.fields.note, { value: "Reviewed", base: null });
});

test("removing a field stages a null value", () => {
  const state = stageField(emptyStaging(), "Euler1748", "month", null, "mar");

  assert.deepEqual(state.entries.Euler1748.fields.month, { value: null, base: "mar" });
});

test("unstaging the last change drops the entry", () => {
  let state = stageField(emptyStaging(), "Euler1748", "note", "Reviewed", null);
  state = unstageField(state, "Euler1748", "note");

  assert.ok(isEmpty(state));
});

test("a type change stages and unstages like a field", () => {
  let state = stageType(emptyStaging(), "Franklin1953", "misc", "online");
  assert.equal(state.entries.Franklin1953.entryType?.value, "misc");
  assert.deepEqual(stagedCount(state), { fields: 1, entries: 1 });

  state = stageType(state, "Franklin1953", "online", "online");
  assert.ok(isEmpty(state), "setting the type back should clear it");
});

test("discarding an entry removes all of its pending changes", () => {
  let state = stageField(emptyStaging(), "Curie1898", "year", "1899", "1898");
  state = stageField(state, "Curie1898", "note", "Checked", null);
  state = discardEntry(state, "Curie1898");

  assert.ok(isEmpty(state));
});

test("requests split set from clear and sort deterministically", () => {
  let state = stageField(emptyStaging(), "Zeno", "year", "1", "2");
  state = stageField(state, "Anaximander", "note", "kept", null);
  state = stageField(state, "Anaximander", "month", null, "mar");
  state = stageType(state, "Anaximander", "book", "article");

  const requests = toRequests(state);

  assert.deepEqual(
    requests.map((request) => request.key),
    ["Anaximander", "Zeno"],
  );
  assert.deepEqual(requests[0].set, { note: "kept" });
  assert.deepEqual(requests[0].clear, ["month"]);
  assert.equal(requests[0].entryType, "book");
  assert.equal(requests[1].entryType, undefined);
});

test("findConflicts reports a field the file changed underneath the edit", () => {
  const state = stageField(emptyStaging(), "Newton1687", "year", "1686", "1687");

  const conflicts = findConflicts(state.entries.Newton1687, {
    change: "modified",
    key: "Newton1687",
    fields: { year: { old: "1690", new: "1686" } },
  });

  assert.deepEqual(conflicts, [
    { key: "Newton1687", field: "year", expected: "1687", actual: "1690" },
  ]);
});

test("findConflicts accepts a field whose current value matches the base", () => {
  const state = stageField(emptyStaging(), "Newton1687", "year", "1686", "1687");

  const conflicts = findConflicts(state.entries.Newton1687, {
    change: "modified",
    key: "Newton1687",
    fields: { year: { old: "1687", new: "1686" } },
  });

  assert.deepEqual(conflicts, []);
});

test("a field the plan omits is not a conflict", () => {
  const state = stageField(emptyStaging(), "Newton1687", "year", "1686", "1687");

  // The engine leaves out fields that already hold the requested value, which
  // means the intended change is simply already in place.
  assert.deepEqual(findConflicts(state.entries.Newton1687, undefined), []);
  assert.deepEqual(
    findConflicts(state.entries.Newton1687, { change: "modified", key: "Newton1687", fields: {} }),
    [],
  );
});

test("adding a field conflicts when the file already gave it a value", () => {
  const state = stageField(emptyStaging(), "Euler1748", "note", "Reviewed", null);

  const conflicts = findConflicts(state.entries.Euler1748, {
    change: "modified",
    key: "Euler1748",
    fields: { note: { old: "Added by someone else", new: "Reviewed" } },
  });

  assert.deepEqual(conflicts, [
    { key: "Euler1748", field: "note", expected: null, actual: "Added by someone else" },
  ]);
});

test("a staged type change conflicts when the file's type moved underneath", () => {
  const state = stageType(emptyStaging(), "Franklin1953", "article", "misc");

  const conflicts = findConflicts(state.entries.Franklin1953, {
    change: "modified",
    key: "Franklin1953",
    fields: {},
    type: { old: "online", new: "article" },
  });

  assert.deepEqual(conflicts, [
    { key: "Franklin1953", field: "@type", expected: "misc", actual: "online" },
  ]);
});

test("a staged type change accepts a case-insensitive match with the plan", () => {
  // The engine compares types case-insensitively, so `Misc` in the file must
  // not read as a conflict against a base of `misc`.
  const state = stageType(emptyStaging(), "Franklin1953", "article", "misc");

  assert.deepEqual(
    findConflicts(state.entries.Franklin1953, {
      change: "modified",
      key: "Franklin1953",
      fields: {},
      type: { old: "Misc", new: "article" },
    }),
    [],
  );
});

test("a type change the plan omits is not a conflict", () => {
  const state = stageType(emptyStaging(), "Franklin1953", "book", "article");

  assert.deepEqual(
    findConflicts(state.entries.Franklin1953, { change: "modified", key: "Franklin1953", fields: {} }),
    [],
  );
});
