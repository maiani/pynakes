// @ts-check
/**
 * The relocatable panes: Edit, Findings, the staged diff, and Compare.
 *
 * Each pane lives in one of two docks — the right dock (where the entry editor
 * usually sits) or the bottom dock (where findings and the diff usually sit) —
 * and can be moved between them. A dock holding more than one pane gets a tab
 * row to choose among them; a move button beside each tab relocates that pane
 * to the other dock.
 *
 * The diff shown here is the engine's own unified diff, never reconstructed
 * locally, so what the user approves is exactly what `ref edit` will write.
 */
window.PV = window.PV || {};

(function (PV) {
  "use strict";

  /** Pane definitions: canonical order and their labels. */
  const PANE_ORDER = ["edit", "findings", "diff", "compare", "duplicates"];
  const PANE_LABEL = {
    edit: "Edit",
    findings: "Findings",
    diff: "Staged diff",
    compare: "Compare",
    duplicates: "Duplicates",
  };

  const els = {};

  PV.panelsInit = (elements) => {
    els.dock = {
      right: {
        root: elements.rightDock,
        tabs: elements.rightTabs,
        body: elements.rightBody,
        splitter: elements.detailSplitter,
      },
      bottom: {
        root: elements.bottomDock,
        tabs: elements.bottomTabs,
        body: elements.bottomBody,
        splitter: elements.panelSplitter,
      },
    };
    els.commitBar = elements.bar;
  };

  /** Panes living in a dock, in canonical order (findings drops out when disabled). */
  function panesIn(loc) {
    return PANE_ORDER.filter(
      (pane) =>
        PV.state.paneDock[pane] === loc &&
        !(pane === "findings" && PV.state.showFindings === false),
    );
  }

  /** The dock a pane currently lives in. */
  function locationOf(pane) {
    return PV.state.paneDock[pane] === "right" ? "right" : "bottom";
  }

  function tabCount(pane) {
    const s = PV.state;
    if (pane === "findings") {
      return s.showFindings !== false && s.lint ? s.lint.counts.total : null;
    }
    if (pane === "diff") {
      return s.counts.fields || null;
    }
    if (pane === "duplicates") {
      return Array.isArray(s.duplicates) ? s.duplicates.length || null : null;
    }
    return null;
  }

  /** A tab button selecting `pane`, plus a button that moves it to the other dock. */
  function paneTab(pane) {
    const fragment = document.createDocumentFragment();
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tab";
    button.dataset.pane = pane;
    const count = tabCount(pane);
    button.textContent = count === null ? PANE_LABEL[pane] : PANE_LABEL[pane] + " (" + count + ")";
    button.addEventListener("click", () => {
      PV.state.dock[locationOf(pane)] = pane;
      PV.persist();
      PV.renderDocks();
    });
    fragment.appendChild(button);

    const move = document.createElement("button");
    move.type = "button";
    move.className = "icon-button pane-move";
    const other = locationOf(pane) === "right" ? "bottom" : "right";
    move.textContent = locationOf(pane) === "right" ? "▾" : "▸";
    move.title = "Move this pane to the " + (other === "right" ? "right" : "bottom");
    move.addEventListener("click", () => relocatePane(pane, other));
    fragment.appendChild(move);
    return fragment;
  }

  /** Relocate a pane to the other dock and show it there. */
  function relocatePane(pane, to) {
    const s = PV.state;
    s.paneDock[pane] = to;
    s.dock[to] = pane;
    PV.persist();
    PV.renderDocks();
  }

  function renderDock(loc, options) {
    const s = PV.state;
    const dock = els.dock[loc];
    const panes = panesIn(loc);
    const hasPanes = panes.length > 0;
    dock.root.hidden = !hasPanes;
    dock.splitter.hidden = !hasPanes;
    if (!hasPanes) {
      dock.tabs.replaceChildren();
      dock.body.replaceChildren();
      return;
    }

    const active = panes.includes(s.dock[loc]) ? s.dock[loc] : panes[0];
    s.dock[loc] = active;

    dock.root.classList.toggle("collapsed", loc === "bottom" && s.panelCollapsed);

    const tabs = document.createElement("div");
    tabs.className = "pane-tabs-inner";
    for (const pane of panes) {
      const holder = document.createElement("span");
      holder.className = "pane-tab-holder" + (pane === active ? " active" : "");
      // Query before appending: appending a fragment empties it.
      const tab = paneTab(pane);
      tab.querySelector(".tab").classList.toggle("active", pane === active);
      holder.appendChild(tab);
      tabs.appendChild(holder);
    }

    if (loc === "bottom") {
      tabs.appendChild(collapseToggle());
    }
    dock.tabs.replaceChildren(tabs);

    const target = document.createElement("div");
    target.className = "pane-content";
    renderPane(active, target, options);
    dock.body.replaceChildren(target);
  }

  /** Render one pane's content into `target`. */
  function renderPane(pane, target, options) {
    if (pane === "findings") {
      return renderFindings(target);
    }
    if (pane === "diff") {
      return renderDiff(target);
    }
    if (pane === "compare") {
      return renderCompare(target);
    }
    if (pane === "duplicates") {
      return renderDuplicates(target);
    }
    if (pane === "edit") {
      return PV.renderEditBody(target, options);
    }
    return undefined;
  }

  PV.renderDocks = (options) => {
    PV.applyPaneSizes();
    renderDock("right", options);
    renderDock("bottom", options);
    renderCommitBar();
  };

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

  /**
   * Duplicate clusters, each with the merge that would resolve it.
   *
   * Merging is offered per cluster rather than for the file, because deciding
   * that two records are the same work is a judgement made one pair at a time.
   * The engine's `dedupe merge --key` is what makes that possible; without it
   * the only choice would be every merge or none.
   */
  function renderDuplicates(target) {
    const duplicates = PV.state.duplicates;
    if (duplicates === null) {
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = "Choose Duplicates in the toolbar to look for repeated works.";
      target.appendChild(hint);
      return;
    }
    if (duplicates === "loading") {
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = "Looking for duplicates…";
      target.appendChild(hint);
      return;
    }
    if (!Array.isArray(duplicates)) {
      const problem = document.createElement("p");
      problem.className = "hint";
      problem.textContent = duplicates.error;
      target.appendChild(problem);
      return;
    }
    if (duplicates.length === 0) {
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = "No duplicate works found.";
      target.appendChild(hint);
      return;
    }

    for (const cluster of duplicates) {
      const section = document.createElement("div");
      section.className = "dup-cluster";

      const head = document.createElement("div");
      head.className = "dup-head";
      const reason = document.createElement("span");
      reason.className = "dup-reason";
      reason.textContent = cluster.reason;
      head.appendChild(reason);
      const identity = document.createElement("span");
      identity.className = "dup-identity";
      identity.textContent = cluster.identity?.value || "matched by title";
      head.appendChild(identity);
      section.appendChild(head);

      for (const [index, entry] of (cluster.entries || []).entries()) {
        const line = document.createElement("div");
        line.className = "dup-entry";
        const key = document.createElement("span");
        key.className = "dup-key";
        key.textContent = entry.key;
        key.title = "Select this entry";
        key.addEventListener("click", () => PV.select(entry.key));
        line.appendChild(key);
        const title = document.createElement("span");
        title.className = "dup-title";
        title.textContent = entry.fields?.title || "";
        line.appendChild(title);
        if (index === 0) {
          const survivor = document.createElement("span");
          survivor.className = "dup-survivor";
          survivor.textContent = "keeps";
          line.appendChild(survivor);
        }
        section.appendChild(line);
      }

      const merge = document.createElement("button");
      merge.className = "button";
      merge.type = "button";
      merge.textContent = "Merge this pair";
      merge.title = "Fold the copies into the first entry, after reviewing the diff";
      merge.addEventListener("click", () => {
        PV.post({
          type: "mutate",
          // The cluster is named by a key inside it, so the engine re-finds it
          // rather than the view describing a merge it cannot perform.
          mutation: { kind: "dedupeMerge", keys: cluster.keys },
        });
      });
      section.appendChild(merge);
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
      PV.renderDocks();
    });
    return button;
  }
  function renderCommitBar() {
    const s = PV.state;
    if (s.counts.fields === 0) {
      els.commitBar.hidden = true;
      els.commitBar.replaceChildren();
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
      PV.state.dock[locationOf("diff")] = "diff";
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
      PV.state.dock[locationOf("diff")] = "diff";
      PV.state.panelCollapsed = false;
      PV.persist();
      PV.post({ type: "commit" });
    });

    els.commitBar.replaceChildren(summary, preview, discard, commit);
    els.commitBar.hidden = false;
  }
})(window.PV);
