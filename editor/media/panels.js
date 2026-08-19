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
    const findingCount = s.lint ? s.lint.counts.total : null;
    tabs.replaceChildren(
      tabButton("findings", "Findings", findingCount),
      tabButton("diff", "Staged diff", s.counts.fields || null),
      collapseToggle(),
    );

    const target = document.createElement("div");
    target.className = "panel-content";
    if (s.panel === "diff") {
      renderDiff(target);
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
