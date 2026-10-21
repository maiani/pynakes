/** Tests for locating citation key lists and planning insertions into them. */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  findCitationContext,
  isCitationMacro,
  planCitationInsertion,
  type CitationGrammar,
} from "../citeContext.js";

/**
 * The grammar as `capabilities --section citation_grammar` publishes it;
 * `cliContract.test.ts` checks the real engine still says the same.
 */
const GRAMMAR: CitationGrammar = {
  macro_name: "[a-zA-Z]*cite[a-zA-Z]*",
  optional_arguments: "\\*?\\s*(?:\\[[^\\]]*\\]\\s*)*",
  key_separator: ",",
  case_insensitive: true,
};

/** Split `text` at its `|`, the cursor. */
function at(marked: string): [string, number] {
  const offset = marked.indexOf("|");
  return [marked.slice(0, offset) + marked.slice(offset + 1), offset];
}

function context(marked: string) {
  const [text, offset] = at(marked);
  return findCitationContext(text, offset, GRAMMAR);
}

/** The text after applying the planned insertion, with `|` where the cursor lands. */
function cite(marked: string, keys: string[], macro = "cite"): string | null {
  const [text, offset] = at(marked);
  const plan = planCitationInsertion(text, offset, keys, macro, GRAMMAR);
  if (!plan) {
    return null;
  }
  return `${text.slice(0, plan.offset)}${plan.text}|${text.slice(plan.offset)}`;
}

test("finds the key list the cursor stands in, with the key being typed", () => {
  const found = context(String.raw`See \citep[see][p.~3]{Newton1687, Eul|}.`);
  assert.ok(found);
  assert.equal(found.macro, "citep");
  assert.deepEqual(found.keys, ["Newton1687", "Eul"]);
  assert.equal(found.prefix, "Eul");
  assert.equal(found.closed, true);
});

test("counts the macros the scan counts, in any case and starred", () => {
  assert.ok(context(String.raw`\Textcite{|}`));
  assert.ok(context(String.raw`\parencite*{|}`));
  assert.ok(context(String.raw`\nocite{|}`));
  assert.equal(context(String.raw`\ref{|}`), null);
  assert.equal(context(String.raw`\label{fig:|}`), null);
});

test("is not inside a citation once its list is closed, or in a commented line", () => {
  assert.equal(context(String.raw`\cite{Newton1687} and |`), null);
  assert.equal(context(String.raw`% \cite{|}`), null);
  assert.ok(context(String.raw`50\% of \cite{|}`), "an escaped percent sign is not a comment");
});

test("an unclosed list does not reach across a paragraph break", () => {
  assert.ok(context("\\cite{Newton1687,\n  |"));
  assert.equal(context("\\cite{Newton1687\n\nLater text |"), null);
});

test("a new citation goes in at the cursor, outside any list", () => {
  assert.equal(cite("As shown |.", ["Newton1687", "Euler1748"]), String.raw`As shown \cite{Newton1687,Euler1748}|.`);
  assert.equal(cite("As shown |.", ["Newton1687"], "parencite"), String.raw`As shown \parencite{Newton1687}|.`);
});

test("keys join the list the cursor is in, after the key there", () => {
  assert.equal(cite(String.raw`\cite{Newton1687|}`, ["Euler1748"]), String.raw`\cite{Newton1687,Euler1748|}`);
  assert.equal(cite(String.raw`\cite{|}`, ["Euler1748"]), String.raw`\cite{Euler1748|}`);
  assert.equal(cite(String.raw`\cite{New|ton1687}`, ["Euler1748"]), String.raw`\cite{Newton1687,Euler1748|}`);
  assert.equal(cite(String.raw`\cite{|Newton1687}`, ["Euler1748"]), String.raw`\cite{Newton1687,Euler1748|}`);
  assert.equal(cite(String.raw`\cite{Newton1687, |}`, ["Euler1748"]), String.raw`\cite{Newton1687, Euler1748|}`);
  assert.equal(
    cite(String.raw`\cite{Newton1687|, Gauss1801}`, ["Euler1748"]),
    String.raw`\cite{Newton1687,Euler1748|, Gauss1801}`,
  );
});

test("keys already in the list are not added twice", () => {
  assert.equal(
    cite(String.raw`\cite{Newton1687|}`, ["Newton1687", "Euler1748", "Euler1748"]),
    String.raw`\cite{Newton1687,Euler1748|}`,
  );
  assert.equal(cite(String.raw`\cite{Newton1687, Euler1748|}`, ["Newton1687", "Euler1748"]), null);
});

test("the configured macro is checked against the grammar", () => {
  assert.ok(isCitationMacro("autocite", GRAMMAR));
  assert.ok(isCitationMacro("Citet", GRAMMAR));
  assert.equal(isCitationMacro("ref", GRAMMAR), false);
  assert.equal(isCitationMacro("cite{x}", GRAMMAR), false);
});
