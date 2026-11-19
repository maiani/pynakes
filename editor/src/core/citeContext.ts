/**
 * Where a citation key goes in TeX text, by the engine's own citation grammar.
 *
 * The view inserts citation keys into a manuscript and completes them as they
 * are typed, and both must agree with `tex scan` about what a citation *is*:
 * a key completed inside a macro the scan does not count would never show as
 * cited. So the macro-name and optional-argument patterns are not written
 * here — they come from `capabilities --section citation_grammar`, and this
 * module only composes them and works out positions. It reads TeX text and
 * nothing else; bibliography content never reaches it.
 */

/** `capabilities --section citation_grammar`, as far as this module needs it. */
export interface CitationGrammar {
  /** Regular-expression fragment for a citation macro's name, without the backslash. */
  macro_name: string;
  /** Fragment for the star and any `[...]` arguments between the name and the key list. */
  optional_arguments: string;
  key_separator: string;
  case_insensitive: boolean;
}

/** The citation key list the cursor stands in. */
export interface CitationContext {
  /** The citing macro's name without its backslash, as written. */
  macro: string;
  /** Every key already in the list, on either side of the cursor. */
  keys: string[];
  /** What is typed of the key at the cursor, up to the cursor. */
  prefix: string;
  /** Offset where the key at the cursor begins, after any leading whitespace. */
  tokenStart: number;
  /** Offset where the key at the cursor ends. */
  tokenEnd: number;
  /** False when no `}` closes the list yet. */
  closed: boolean;
}

/** How far back a macro may begin: a key list spanning more than this is not followed. */
const LOOKBACK = 2000;

/**
 * The citation key list containing `offset`, or `null` when it is in none.
 *
 * A key list is open at the cursor when a citation macro's `{` precedes it
 * with no brace in between. A macro on a line commented out with `%` does not
 * count, as the scan does not count it.
 */
export function findCitationContext(
  text: string,
  offset: number,
  grammar: CitationGrammar,
): CitationContext | null {
  const windowStart = Math.max(0, offset - LOOKBACK);
  const before = text.slice(windowStart, offset);
  const opening = new RegExp(
    `\\\\(${grammar.macro_name})${grammar.optional_arguments}\\{([^{}]*)$`,
    grammar.case_insensitive ? "i" : "",
  ).exec(before);
  if (!opening) {
    return null;
  }
  const macroStart = windowStart + opening.index;
  if (commentedOut(text, macroStart)) {
    return null;
  }
  const typedBefore = opening[2];
  // A paragraph break ends a macro argument in TeX: a list left unclosed above
  // one is not where the cursor is.
  if (/\n[ \t]*\r?\n/.test(typedBefore)) {
    return null;
  }
  const rest = /^[^{}]*/.exec(text.slice(offset, offset + LOOKBACK))?.[0] ?? "";
  const closed = text.charAt(offset + rest.length) === "}";
  // An unclosed list is still being typed; what follows it is not part of it.
  const typedAfter = closed ? rest : "";

  const separator = grammar.key_separator;
  const lastSeparator = typedBefore.lastIndexOf(separator);
  const tokenHead = lastSeparator === -1 ? typedBefore : typedBefore.slice(lastSeparator + separator.length);
  const afterSeparator = typedAfter.indexOf(separator);
  const tokenTail = afterSeparator === -1 ? typedAfter : typedAfter.slice(0, afterSeparator);
  const leading = tokenHead.length - tokenHead.trimStart().length;
  const trailing = tokenTail.length - tokenTail.trimEnd().length;
  return {
    macro: opening[1],
    keys: splitKeys(typedBefore + typedAfter, separator),
    prefix: tokenHead.trimStart(),
    tokenStart: offset - tokenHead.length + leading,
    tokenEnd: offset + tokenTail.length - trailing,
    closed,
  };
}

/** True when `name` is a macro the grammar counts as citing. */
export function isCitationMacro(name: string, grammar: CitationGrammar): boolean {
  return new RegExp(`^(?:${grammar.macro_name})$`, grammar.case_insensitive ? "i" : "").test(name);
}

/** One text insertion: `text` goes in at `offset`, replacing nothing. */
export interface CitationInsertion {
  offset: number;
  text: string;
  /** The keys this inserts, in order; requested keys already cited there are left out. */
  added: string[];
  /** True when the keys join an existing key list rather than a new macro. */
  merged: boolean;
}

/**
 * Plan inserting `keys` at `offset`.
 *
 * Inside an existing key list, the keys it lacks join it after the key at the
 * cursor, so a key half typed is never split; outside one, a new
 * `\macro{...}` goes in at the cursor. Returns `null` when every key is
 * already in the list at the cursor.
 */
export function planCitationInsertion(
  text: string,
  offset: number,
  keys: readonly string[],
  macro: string,
  grammar: CitationGrammar,
): CitationInsertion | null {
  const separator = grammar.key_separator;
  const context = findCitationContext(text, offset, grammar);
  if (!context) {
    const added = unique(keys);
    return { offset, text: `\\${macro}{${added.join(separator)}}`, added, merged: false };
  }
  const present = new Set(context.keys);
  const added = unique(keys).filter((key) => !present.has(key));
  if (added.length === 0) {
    return null;
  }
  // Insert where the key at the cursor ends; with no key there, at the cursor.
  const at = context.tokenEnd > context.tokenStart ? context.tokenEnd : offset;
  const preceding = text.slice(0, at).trimEnd();
  const following = text.slice(at).trimStart();
  const leadingSeparator = !(preceding.endsWith("{") || preceding.endsWith(separator));
  const trailingSeparator =
    context.closed && !(following.startsWith("}") || following.startsWith(separator));
  const joined = added.join(separator);
  return {
    offset: at,
    text: `${leadingSeparator ? separator : ""}${joined}${trailingSeparator ? separator : ""}`,
    added,
    merged: true,
  };
}

/** True when an unescaped `%` precedes `offset` on its line. */
function commentedOut(text: string, offset: number): boolean {
  const lineStart = text.lastIndexOf("\n", offset - 1) + 1;
  const line = text.slice(lineStart, offset);
  for (let i = 0; i < line.length; i++) {
    if (line[i] === "\\") {
      i++;
    } else if (line[i] === "%") {
      return true;
    }
  }
  return false;
}

function splitKeys(raw: string, separator: string): string[] {
  return raw.split(separator).map((key) => key.trim()).filter(Boolean);
}

function unique(keys: readonly string[]): string[] {
  return [...new Set(keys)];
}
