// @ts-check
/**
 * The relocatable panes: Edit, Findings, the staged diff, Compare, and
 * Duplicates. The Compare and Duplicates bodies live in `compare.js` and
 * `duplicates.js`; this module owns the docks they are shown in.
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
  const PANE_ORDER = ["edit", "findings", "diff", "compare", "duplicates", "materials", "metadata"];
  const PANE_LABEL = {
    edit: "Edit",
    findings: "Findings",
    diff: "Staged diff",
    compare: "Compare",
    duplicates: "Duplicates",
    materials: "Materials",
    metadata: "Metadata",
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
      if (locationOf(pane) === "bottom") PV.state.panelCollapsed = false;
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
    if (pane === "metadata") return PV.renderMetadata(target);
    if (pane === "materials") return PV.renderMaterials(target);
    if (pane === "findings") {
      return renderFindings(target);
    }
    if (pane === "diff") {
      return renderDiff(target);
    }
    if (pane === "compare") {
      return PV.renderCompare(target);
    }
    if (pane === "duplicates") {
      return PV.renderDuplicates(target);
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
          const key = PV.button("link-button", issue.key, "Select this entry", () => {
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
    const button = PV.button(
      "icon-button collapse-toggle panel-toggle",
      s.panelCollapsed ? "▴" : "▾",
      s.panelCollapsed ? "Expand this panel" : "Collapse this panel",
      () => {
        PV.state.panelCollapsed = !PV.state.panelCollapsed;
        PV.persist();
        PV.renderDocks();
      },
    );
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

    const preview = PV.button("button", "Preview", null, () => {
      PV.state.dock[locationOf("diff")] = "diff";
      PV.state.panelCollapsed = false;
      PV.persist();
      PV.post({ type: "preview" });
    });

    const discard = PV.button("button", "Discard all", null, () => PV.post({ type: "discardAll" }));

    const commit = PV.button(
      "button primary",
      "Apply",
      "Show the diff and ask for confirmation before writing",
      () => {
        PV.state.dock[locationOf("diff")] = "diff";
        PV.state.panelCollapsed = false;
        PV.persist();
        PV.post({ type: "commit" });
      },
    );

    els.commitBar.replaceChildren(summary, preview, discard, commit);
    els.commitBar.hidden = false;
  }
})(window.PV);
