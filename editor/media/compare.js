// @ts-check
/**
 * The Compare pane: one entry's fields beside another reference's, from the
 * engine's `ref compare`, with a word-level diff of each disagreeing value.
 *
 * Nothing here decides what differs — the engine names the fields — the
 * word diff only highlights where two values the engine reported part ways.
 */
window.PV = window.PV || {};

(function (PV) {
  "use strict";

  /** The engine's own message is CLI-flag phrasing; give it a GUI equivalent. */
  function compareWarningText(warning) {
    if (warning.type === "offline") {
      return 'Online lookups are disabled. Enable "pynakes.allowOnlineLookups" in settings to compare against DOI/arXiv metadata.';
    }
    return warning.message;
  }

  /**
   * A short description of what the entry was compared against.
   * @param {{source: string, identifier: string}} compare
   */
  function compareSourceText(compare) {
    if (compare.source === "local") {
      return "Compared against local entry " + compare.identifier;
    }
    if (compare.source === "doi") {
      return "Compared against DOI " + compare.identifier;
    }
    if (compare.source === "arxiv") {
      return "Compared against arXiv " + compare.identifier;
    }
    return "Compared against " + compare.source + ": " + compare.identifier;
  }

  /** A short column header for the non-local side of the comparison. */
  function compareOtherLabel(compare) {
    if (compare.source === "local") {
      return "Other entry";
    }
    if (compare.source === "doi") {
      return "DOI record";
    }
    if (compare.source === "arxiv") {
      return "arXiv record";
    }
    return "Other";
  }

  /** Split text into words and the whitespace/punctuation between them, exactly reconstructible by concatenation. */
  function tokenize(text) {
    return text.match(/\s+|\S+/g) || [];
  }

  /**
   * Word-level diff of two strings, via the standard LCS table.
   *
   * Returns `{ a, b }`, each a list of `{ text, type }` tokens (`type` is
   * "same", "del", or "add") — `a` describes `left` against `right`, `b` the
   * reverse. Quadratic in token count, which is fine for bibliography field
   * lengths (even a long abstract is at most a few hundred words).
   * @param {string} left
   * @param {string} right
   */
  function diffWords(left, right) {
    const a = tokenize(left);
    const b = tokenize(right);
    const n = a.length;
    const m = b.length;
    const table = new Array(n + 1);
    for (let i = 0; i <= n; i++) {
      table[i] = new Uint32Array(m + 1);
    }
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        table[i][j] =
          a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
      }
    }
    const aOut = [];
    const bOut = [];
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (a[i] === b[j]) {
        aOut.push({ text: a[i], type: "same" });
        bOut.push({ text: b[j], type: "same" });
        i++;
        j++;
      } else if (table[i + 1][j] >= table[i][j + 1]) {
        aOut.push({ text: a[i], type: "del" });
        i++;
      } else {
        bOut.push({ text: b[j], type: "add" });
        j++;
      }
    }
    while (i < n) {
      aOut.push({ text: a[i], type: "del" });
      i++;
    }
    while (j < m) {
      bOut.push({ text: b[j], type: "add" });
      j++;
    }
    return { a: aOut, b: bOut };
  }

  /** Render `tokens` (from `diffWords`) into `container`, highlighting changed spans. */
  function renderDiffTokens(container, tokens) {
    for (const token of tokens) {
      if (token.type === "same") {
        container.appendChild(document.createTextNode(token.text));
        continue;
      }
      const span = document.createElement("span");
      span.className = token.type === "add" ? "diff-word-add" : "diff-word-del";
      span.textContent = token.text;
      container.appendChild(span);
    }
  }

  /** One read-only comparison cell: "(missing)", or `text` diffed against `against`. */
  function compareValueCell(text, against) {
    const cell = document.createElement("div");
    if (text === null) {
      cell.className = "compare-value compare-missing";
      cell.textContent = "(missing)";
      return cell;
    }
    cell.className = "compare-value";
    const { a } = diffWords(text, against ?? "");
    renderDiffTokens(cell, a);
    return cell;
  }

  PV.renderCompare = (target) => {
    const compare = PV.state.compare;
    if (!compare) {
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = 'Select an entry and choose "Compare with remote" (next to its DOI or eprint field) to see this.';
      target.appendChild(hint);
      return;
    }

    const heading = document.createElement("h4");
    heading.textContent = compare.key;
    target.appendChild(heading);

    if (compare.error) {
      const note = document.createElement("p");
      note.className = "diff-warning";
      note.textContent = compare.error;
      target.appendChild(note);
      return;
    }

    if (compare.source) {
      const source = document.createElement("p");
      source.className = "hint";
      source.textContent = compareSourceText(compare);
      target.appendChild(source);
    }

    for (const warning of compare.warnings || []) {
      const note = document.createElement("p");
      note.className = "diff-warning";
      note.textContent = compareWarningText(warning);
      target.appendChild(note);
    }

    if (compare.fields.length === 0) {
      if (!compare.warnings || compare.warnings.length === 0) {
        const hint = document.createElement("p");
        hint.className = "hint";
        hint.textContent = "No differing fields.";
        target.appendChild(hint);
      }
      return;
    }

    const table = document.createElement("div");
    table.className = "compare-table";

    const header = document.createElement("div");
    header.className = "compare-row compare-header";
    const headerCells = ["Field", "Local", compareOtherLabel(compare), "Merged"];
    for (const label of headerCells) {
      const cell = document.createElement("span");
      cell.textContent = label;
      header.appendChild(cell);
    }
    table.appendChild(header);

    const merged = [];
    for (const field of compare.fields) {
      const row = document.createElement("div");
      row.className = "compare-row";

      const name = document.createElement("span");
      name.className = "compare-field-name";
      name.textContent = field.field;
      row.appendChild(name);

      const localCell = compareValueCell(field.local, field.other);
      const otherCell = compareValueCell(field.other, field.local);
      row.append(localCell, otherCell);

      const mergedCell = document.createElement("div");
      mergedCell.className = "compare-merged-cell";
      const value = document.createElement("textarea");
      value.className = "compare-merged-value";
      value.rows = 1;
      value.spellcheck = false;
      merged.push({ field, value });

      // Clicking a value cell selects it for the merged result — the
      // highlighted cell always shows which side the merged value currently
      // matches, staying in sync with manual edits to the merged text too.
      const syncSelection = () => {
        localCell.classList.toggle(
          "compare-selected",
          field.local !== null && value.value === field.local,
        );
        otherCell.classList.toggle("compare-selected", value.value === field.other);
      };
      const select = (text) => {
        value.value = text;
        syncSelection();
      };
      if (field.local !== null) {
        localCell.classList.add("compare-selectable");
        localCell.title = "Click to keep the local value";
        localCell.addEventListener("click", () => select(field.local));
      }
      otherCell.classList.add("compare-selectable");
      otherCell.title = "Click to keep the " + compareOtherLabel(compare).toLowerCase() + " value";
      otherCell.addEventListener("click", () => select(field.other));
      value.addEventListener("input", syncSelection);

      // A field the entry lacks entirely defaults to the other side, filling
      // the gap; a genuine conflict (both sides have a value) defaults to the
      // local one, so a remote value never silently overwrites curated data.
      select(field.local ?? field.other);

      mergedCell.appendChild(value);
      row.appendChild(mergedCell);
      table.appendChild(row);
    }
    target.appendChild(table);

    const apply = document.createElement("button");
    apply.type = "button";
    apply.className = "button primary";
    apply.textContent = "Apply merged";
    apply.title = "Stage each field's merged value for review in the staged diff";
    apply.addEventListener("click", () => {
      for (const { field, value } of merged) {
        PV.post({
          type: "stageField",
          key: compare.key,
          field: field.field,
          value: value.value,
          base: field.local,
        });
      }
    });
    target.appendChild(apply);
  };
})(window.PV);
