/**
 * Tests for the pure projection layer. These run under `node --test` against
 * the compiled output and never load the `vscode` module.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type InspectSuccess,
  collapseWhitespace,
  entryAuthor,
  entryVenue,
  entryYear,
  formatNames,
  summarize,
  toRows,
} from "../model.js";

function envelope(overrides: Partial<InspectSuccess> = {}): InspectSuccess {
  return {
    status: "success",
    action: "inspect",
    file: "library.bib",
    encoding: "utf-8",
    line_ending: "lf",
    entry_count: 0,
    entries: [],
    strings: {},
    preamble: [],
    comments: [],
    jabref_metadata: { values: {}, blocks: [] },
    pynakes_metadata: { values: {}, blocks: [] },
    duplicate_keys: {},
    ...overrides,
  };
}

test("collapseWhitespace folds wrapped source values onto one line", () => {
  assert.equal(collapseWhitespace("  On the\n  Motion   of Bodies  "), "On the Motion of Bodies");
});

test("formatNames renders the and-separator as a semicolon list", () => {
  assert.equal(
    formatNames("Newton, Isaac and Halley, Edmond"),
    "Newton, Isaac; Halley, Edmond",
  );
});

test("formatNames leaves a braced corporate name intact", () => {
  assert.equal(formatNames("{Peirce and Sons Institute}"), "{Peirce and Sons Institute}");
  assert.equal(
    formatNames("{Peirce and Sons Institute} and Lovelace, Ada"),
    "{Peirce and Sons Institute}; Lovelace, Ada",
  );
});

test("formatNames tolerates an empty or padded name list", () => {
  assert.equal(formatNames(""), "");
  assert.equal(formatNames("  Euler, Leonhard  "), "Euler, Leonhard");
});

test("entryYear prefers year and otherwise reads the date field", () => {
  assert.equal(entryYear({ year: "1687" }), "1687");
  assert.equal(entryYear({ date: "1859-11-24" }), "1859");
  assert.equal(entryYear({ date: "in press" }), "");
  assert.equal(entryYear({}), "");
});

test("entryVenue follows field precedence across entry types", () => {
  assert.equal(entryVenue({ journaltitle: "Annalen", journal: "Legacy" }), "Annalen");
  assert.equal(entryVenue({ journal: "Legacy" }), "Legacy");
  assert.equal(entryVenue({ booktitle: "Proceedings of Nowhere" }), "Proceedings of Nowhere");
  assert.equal(entryVenue({ publisher: "Royal Society" }), "Royal Society");
  assert.equal(entryVenue({ note: "unpublished" }), "");
});

test("toRows preserves file order and projects the display columns", () => {
  const rows = toRows(
    envelope({
      entry_count: 2,
      entries: [
        {
          key: "Newton1687",
          type: "book",
          fields: {
            author: "Newton, Isaac",
            title: "Philosophiae Naturalis\nPrincipia Mathematica",
            publisher: "Royal Society",
            year: "1687",
          },
        },
        {
          key: "Lovelace1843",
          type: "article",
          fields: {
            editor: "Menabrea, Luigi",
            title: "Notes upon the Analytical Engine",
            journaltitle: "Scientific Memoirs",
            date: "1843-10-01",
          },
        },
      ],
    }),
  );

  assert.deepEqual(
    rows.map((row) => [row.index, row.key, row.type, row.year, row.venue]),
    [
      [0, "Newton1687", "book", "1687", "Royal Society"],
      [1, "Lovelace1843", "article", "1843", "Scientific Memoirs"],
    ],
  );
  assert.equal(rows[0].title, "Philosophiae Naturalis Principia Mathematica");
  // An entry without an author falls back to the editor for the name column.
  assert.equal(rows[1].author, "Menabrea, Luigi");
});

test("entryAuthor prefers the engine's cleaned, pre-split display names", () => {
  assert.equal(
    entryAuthor({
      key: "Peirce1867",
      type: "article",
      fields: { author: "{Peirce and Sons Institute}" },
      display: { author: ["Peirce and Sons Institute"] },
    }),
    "Peirce and Sons Institute",
  );
});

test("entryAuthor falls back to editor names, then to splitting the raw field", () => {
  assert.equal(
    entryAuthor({
      key: "Lovelace1843",
      type: "article",
      fields: { editor: "Menabrea, Luigi" },
      display: { editor: ["Menabrea, Luigi"] },
    }),
    "Menabrea, Luigi",
  );
  // No `display` at all — an engine that predates `inspect --display`.
  assert.equal(
    entryAuthor({
      key: "Newton1687",
      type: "book",
      fields: { author: "Newton, Isaac and Halley, Edmond" },
    }),
    "Newton, Isaac; Halley, Edmond",
  );
});

test("toRows prefers the engine's cleaned title and author over raw fields", () => {
  const rows = toRows(
    envelope({
      entry_count: 1,
      entries: [
        {
          key: "Peirce1867",
          type: "article",
          fields: {
            title: "On an {Improvement} in Boole's Calculus",
            author: "Peirce, C. S. and {Crick and Sons}",
          },
          display: {
            title: "On an Improvement in Boole's Calculus",
            author: ["Peirce, C. S.", "Crick and Sons"],
          },
        },
      ],
    }),
  );

  assert.equal(rows[0].title, "On an Improvement in Boole's Calculus");
  assert.equal(rows[0].author, "Peirce, C. S.; Crick and Sons");
});

test("toRows flags every occurrence of a duplicated citation key", () => {
  const rows = toRows(
    envelope({
      entry_count: 3,
      entries: [
        { key: "Euler1748", type: "book", fields: {} },
        { key: "Euler1748", type: "book", fields: {} },
        { key: "Gauss1801", type: "book", fields: {} },
      ],
      duplicate_keys: { Euler1748: 2 },
    }),
  );
  assert.deepEqual(
    rows.map((row) => row.duplicate),
    [true, true, false],
  );
});

test("summarize counts types by frequency then name", () => {
  const summary = summarize(
    envelope({
      entry_count: 4,
      entries: [
        { key: "a", type: "article", fields: {} },
        { key: "b", type: "book", fields: {} },
        { key: "c", type: "article", fields: {} },
        { key: "d", type: "thesis", fields: {} },
      ],
      strings: { pub: "Royal Society" },
      comments: ["% a note\n"],
      jabref_metadata: { values: { groupsversion: "3;" }, blocks: [] },
    }),
  );
  assert.deepEqual(summary.typeCounts, [
    ["article", 2],
    ["book", 1],
    ["thesis", 1],
  ]);
  assert.equal(summary.entryCount, 4);
  assert.equal(summary.stringCount, 1);
  assert.equal(summary.commentCount, 1);
  assert.deepEqual(summary.jabrefKeys, ["groupsversion"]);
  assert.deepEqual(summary.pynakesKeys, []);
});

test("summarize sorts duplicate keys by name", () => {
  const summary = summarize(
    envelope({ duplicate_keys: { Zeno: 2, Anaximander: 3 } }),
  );
  assert.deepEqual(summary.duplicateKeys, [
    ["Anaximander", 3],
    ["Zeno", 2],
  ]);
});
