// @ts-check
/**
 * The bottom panel — lint findings and the staged diff — plus the commit bar.
 *
 * The diff shown here is the engine's own unified diff, never reconstructed
 * locally, so what the user approves is exactly what `ref edit` will write.
 */
window.PV = window.PV || {};

(function (PV) {
  "use strict";

  let panelEl;
  let tabs;
  let body;
  let bar;

  PV.panelsInit = (elements) => {
    panelEl = elements.panel;
    tabs = elements.tabs;
    body = elements.body;
    bar = elements.bar;

    tabs.addEventListener("click", (event) => {
      const tab = event.target.closest("[data-panel]");
      if (!tab) {
        return;
      }
      PV.state.panel = tab.dataset.panel;
      PV.state.panelCollapsed = false;
      PV.persist();
      PV.renderPanels();
    });
  };

  function tabButton(id, label, count) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tab" + (PV.state.panel === id ? " active" : "");
    button.dataset.panel = id;
    button.textContent = count === null ? label : label + " (" + count + ")";
    return button;
  }

  function renderFindings(target) {
    const lint = PV.state.lint;
    if (!lint) {
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = "Validation findings are unavailable for this file.";
      target.appendChild(hint);
      return;
    }
    if (lint.counts.total === 0) {
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = "No findings. Every entry passed validation.";
      target.appendChild(hint);
      return;
    }

    for (const group of lint.byCategory) {
      const section = document.createElement("div");
      section.className = "finding-group";
      const heading = document.createElement("h4");
      heading.textContent = group.category + " (" + group.issues.length + ")";
      section.appendChild(heading);

      for (const issue of group.issues) {
        const line = document.createElement("div");
        line.className = "finding-row finding-" + issue.severity;

        const severity = document.createElement("span");
        severity.className = "finding-severity";
        severity.textContent = issue.severity;
        line.appendChild(severity);

        if (issue.key) {
          const key = document.createElement("button");
          key.type = "button";
          key.className = "link-button";
          key.textContent = issue.key;
          key.title = "Select this entry";
          key.addEventListener("click", () => {
            PV.select(issue.key);
          });
          line.appendChild(key);
        } else {
          const scope = document.createElement("span");
          scope.className = "finding-file";
          scope.textContent = "file";
          line.appendChild(scope);
        }

        const message = document.createElement("span");
        message.className = "finding-message";
        message.textContent = issue.message;
        line.appendChild(message);

        section.appendChild(line);
      }
      target.appendChild(section);
    }
  }

  function renderDiff(target) {
    const diff = PV.state.diff;
    if (!diff) {
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = "Edit a field, then choose Preview to see the exact diff.";
      target.appendChild(hint);
      return;
    }
    if (diff.length === 0) {
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = "Nothing is staged.";
      target.appendChild(hint);
      return;
    }

    for (const entry of diff) {
      const section = document.createElement("div");
      section.className = "diff-group";
      const heading = document.createElement("h4");
      heading.textContent = entry.key;
      section.appendChild(heading);

      for (const warning of entry.warnings || []) {
        const note = document.createElement("p");
        note.className = "diff-warning";
        note.textContent = warning;
        section.appendChild(note);
      }

      const pre = document.createElement("pre");
      pre.className = "diff";
      for (const line of (entry.diff || "").split("\n")) {
        const span = document.createElement("span");
        span.className = diffLineClass(line);
        span.textContent = line + "\n";
        pre.appendChild(span);
      }
      section.appendChild(pre);
      target.appendChild(section);
    }
  }

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

  function renderCompare(target) {
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

      row.appendChild(compareValueCell(field.local, field.other));
      row.appendChild(compareValueCell(field.other, field.local));

      const mergedCell = document.createElement("div");
      mergedCell.className = "compare-merged-cell";
      const value = document.createElement("textarea");
      value.className = "compare-merged-value";
      value.rows = 1;
      // A field the entry lacks entirely defaults to the other side, filling
      // the gap; a genuine conflict (both sides have a value) defaults to the
      // local one, so a remote value never silently overwrites curated data.
      value.value = field.local ?? field.other;
      value.spellcheck = false;
      merged.push({ field, value });

      const actions = document.createElement("span");
      actions.className = "compare-merged-actions";
      const useLocal = document.createElement("button");
      useLocal.type = "button";
      useLocal.className = "icon-button";
      useLocal.textContent = "⇦";
      useLocal.title = "Use the local value";
      useLocal.disabled = field.local === null;
      useLocal.addEventListener("click", () => {
        value.value = field.local ?? "";
      });
      const useOther = document.createElement("button");
      useOther.type = "button";
      useOther.className = "icon-button";
      useOther.textContent = "⇨";
      useOther.title = "Use the " + compareOtherLabel(compare).toLowerCase() + " value";
      useOther.addEventListener("click", () => {
        value.value = field.other;
      });
      actions.append(useLocal, useOther);

      mergedCell.append(actions, value);
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
  }

  function diffLineClass(line) {
    if (line.startsWith("+++") || line.startsWith("---")) {
      return "diff-file";
    }
    if (line.startsWith("@@")) {
      return "diff-hunk";
    }
    if (line.startsWith("+")) {
      return "diff-add";
    }
    if (line.startsWith("-")) {
      return "diff-del";
    }
    return "diff-context";
  }

  function collapseToggle() {
    const s = PV.state;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "icon-button collapse-toggle panel-toggle";
    button.title = s.panelCollapsed ? "Expand this panel" : "Collapse this panel";
    button.textContent = s.panelCollapsed ? "▴" : "▾";
    button.addEventListener("click", () => {
      PV.state.panelCollapsed = !PV.state.panelCollapsed;
      PV.persist();
      PV.renderPanels();
    });
    return button;
  }

  PV.renderPanels = () => {
    const s = PV.state;
    panelEl.classList.toggle("collapsed", s.panelCollapsed);
    PV.applyPaneSizes();
    const findingCount = s.lint ? s.lint.counts.total : null;
    tabs.replaceChildren(
      tabButton("findings", "Findings", findingCount),
      tabButton("diff", "Staged diff", s.counts.fields || null),
      tabButton("compare", "Compare", null),
      collapseToggle(),
    );

    const target = document.createElement("div");
    target.className = "panel-content";
    if (s.panel === "diff") {
      renderDiff(target);
    } else if (s.panel === "compare") {
      renderCompare(target);
    } else {
      renderFindings(target);
    }
    body.replaceChildren(target);

    renderCommitBar();
  };

  function renderCommitBar() {
    const s = PV.state;
    if (s.counts.fields === 0) {
      bar.hidden = true;
      bar.replaceChildren();
      return;
    }

    const summary = document.createElement("span");
    summary.className = "commit-summary";
    const fields = s.counts.fields;
    const entries = s.counts.entries;
    summary.textContent =
      fields + (fields === 1 ? " change in " : " changes in ") +
      entries + (entries === 1 ? " entry" : " entries") +
      " — not written yet";

    const preview = document.createElement("button");
    preview.type = "button";
    preview.className = "button";
    preview.textContent = "Preview";
    preview.addEventListener("click", () => {
      PV.state.panel = "diff";
      PV.state.panelCollapsed = false;
      PV.persist();
      PV.post({ type: "preview" });
    });

    const discard = document.createElement("button");
    discard.type = "button";
    discard.className = "button";
    discard.textContent = "Discard all";
    discard.addEventListener("click", () => PV.post({ type: "discardAll" }));

    const commit = document.createElement("button");
    commit.type = "button";
    commit.className = "button primary";
    commit.textContent = "Apply";
    commit.title = "Show the diff and ask for confirmation before writing";
    commit.addEventListener("click", () => {
      PV.state.panel = "diff";
      PV.state.panelCollapsed = false;
      PV.persist();
      PV.post({ type: "commit" });
    });

    bar.replaceChildren(summary, preview, discard, commit);
    bar.hidden = false;
  }
})(window.PV);
