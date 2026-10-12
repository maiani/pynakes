// @ts-check
/**
 * The groups sidebar: the declared hierarchy, plus membership counts.
 *
 * Its edit affordances — "+" in the heading, "⋯" on each group, or the
 * context menu — only name the node and hand off to the extension, which asks
 * what to change and runs it through preview and approval. No rule about the
 * hierarchy lives here.
 */
window.PV = window.PV || {};

(function (PV) {
  "use strict";

  let container;

  PV.groupsInit = (element) => {
    container = element;
    container.addEventListener("click", onClick);
    container.addEventListener("contextmenu", onContextMenu);
    container.addEventListener("keydown", onKeyDown);
  };

  /**
   * A row is focusable and acts like a toggle button: Enter or Space filters
   * by it, as a click does. Only when the row itself has focus — its twisty
   * and "⋯" are real buttons with their own activation. Shift+F10 or the
   * context-menu key opens the group's actions, as a right-click does.
   */
  function onKeyDown(event) {
    const row = event.target;
    if (!(row instanceof HTMLElement) || !row.classList.contains("group-row")) {
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggleFilter(row.dataset.group || "");
    } else if ((event.key === "F10" && event.shiftKey) || event.key === "ContextMenu") {
      if (row.dataset.group) {
        event.preventDefault();
        requestActions(row.dataset.group);
      }
    }
  }

  /** Filter by a group — or clear the filter when it is already the one. */
  function toggleFilter(name) {
    PV.state.selectedGroup = PV.state.selectedGroup === name ? null : name || null;
    PV.persist();
    PV.renderGroups();
    PV.renderTable();
    focusRow(name);
  }

  /** Re-rendering replaces every row, so put the keyboard back where it was. */
  function focusRow(name) {
    for (const row of container.querySelectorAll(".group-row")) {
      if (row instanceof HTMLElement && (row.dataset.group || "") === name) {
        row.focus();
        return;
      }
    }
  }

  /** Ask the extension what to do with one group node. */
  function requestActions(name) {
    const node = PV.findGroup(name);
    if (!node) {
      return;
    }
    PV.post({
      type: "groupActions",
      group: { name: node.name, undeclared: !!node.undeclared, description: node.description || "" },
      // Candidate parents for a move: what the hierarchy declares. Which of
      // them would make a cycle is the engine's question, not this view's.
      groups: declaredNames(),
    });
  }

  function declaredNames() {
    const names = [];
    const walk = (nodes) => {
      for (const node of nodes) {
        if (!node.undeclared) {
          names.push(node.name);
        }
        walk(node.children || []);
      }
    };
    walk(PV.state.groups || []);
    return names;
  }

  function onContextMenu(event) {
    const row = event.target.closest(".group-row[data-group]");
    if (!row || !row.dataset.group) {
      return;
    }
    event.preventDefault();
    requestActions(row.dataset.group);
  }

  function onClick(event) {
    if (event.target.closest("button.group-new")) {
      PV.post({ type: "promptNewGroup" });
      return;
    }
    const actions = event.target.closest("button.group-actions");
    if (actions) {
      requestActions(actions.dataset.actionGroup);
      return;
    }
    const sidebarToggle = event.target.closest("button.sidebar-toggle");
    if (sidebarToggle) {
      PV.state.sidebarCollapsed = !PV.state.sidebarCollapsed;
      PV.persist();
      PV.renderGroups();
      return;
    }
    const twisty = event.target.closest("button.twisty");
    if (twisty) {
      const name = twisty.dataset.group;
      if (PV.state.collapsedGroups.has(name)) {
        PV.state.collapsedGroups.delete(name);
      } else {
        PV.state.collapsedGroups.add(name);
      }
      PV.persist();
      PV.renderGroups();
      return;
    }
    const row = event.target.closest("[data-group]");
    if (!row) {
      return;
    }
    // Clicking the selected group clears the filter, so the sidebar is a toggle.
    toggleFilter(row.dataset.group || "");
  }

  /**
   * Make a row a keyboard-reachable toggle. Not a `<button>`, because it holds
   * buttons of its own (the twisty and "⋯"), which a button may not contain.
   */
  function filterRow(row, label, pressed) {
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    row.setAttribute("aria-label", label);
    row.setAttribute("aria-pressed", pressed ? "true" : "false");
  }

  /** Flatten the tree in display order, skipping collapsed subtrees. */
  function flatten(nodes, rows) {
    for (const node of nodes) {
      rows.push(node);
      if (!PV.state.collapsedGroups.has(node.name)) {
        flatten(node.children || [], rows);
      }
    }
    return rows;
  }

  PV.renderGroups = () => {
    const s = PV.state;
    // A group that was removed or renamed elsewhere cannot stay the filter.
    if (s.selectedGroup && !PV.findGroup(s.selectedGroup)) {
      s.selectedGroup = null;
      PV.persist();
    }
    container.classList.toggle("collapsed", s.sidebarCollapsed);
    PV.applyPaneSizes();
    const fragment = document.createDocumentFragment();

    const heading = document.createElement("div");
    heading.className = "sidebar-heading";
    const label = document.createElement("span");
    label.className = "sidebar-heading-label";
    label.textContent = "Groups";
    heading.appendChild(label);
    const toggle = PV.button(
      "icon-button collapse-toggle sidebar-toggle",
      s.sidebarCollapsed ? "▸" : "◂",
      s.sidebarCollapsed ? "Expand groups" : "Collapse groups",
    );
    if (!s.sidebarCollapsed) {
      const add = document.createElement("button");
      add.type = "button";
      add.className = "icon-button group-new";
      add.title = "New group";
      add.setAttribute("aria-label", "New group");
      add.textContent = "+";
      heading.appendChild(add);
    }
    heading.appendChild(toggle);
    fragment.appendChild(heading);

    if (s.sidebarCollapsed) {
      container.replaceChildren(fragment);
      return;
    }

    const all = document.createElement("div");
    all.className = "group-row" + (s.selectedGroup === null ? " selected" : "");
    all.dataset.group = "";
    filterRow(all, "All entries", s.selectedGroup === null);
    const allLabel = document.createElement("span");
    allLabel.className = "group-name";
    allLabel.textContent = "All entries";
    const allCount = document.createElement("span");
    allCount.className = "group-count";
    allCount.textContent = String(s.rows.length);
    all.append(allLabel, allCount);
    fragment.appendChild(all);

    const rows = flatten(s.groups || [], []);
    if (rows.length === 0) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = "This file declares no groups. Use + to add one.";
      fragment.appendChild(empty);
    }

    for (const node of rows) {
      const row = document.createElement("div");
      row.className = "group-row" + (s.selectedGroup === node.name ? " selected" : "");
      row.dataset.group = node.name;
      filterRow(row, 'Filter by group "' + node.name + '"', s.selectedGroup === node.name);
      row.style.paddingLeft = `${6 + node.depth * 14}px`;

      const hasChildren = (node.children || []).length > 0;
      const twisty = document.createElement("button");
      twisty.type = "button";
      twisty.className = "twisty" + (hasChildren ? "" : " empty");
      twisty.dataset.group = node.name;
      twisty.textContent = hasChildren
        ? PV.state.collapsedGroups.has(node.name)
          ? "▸"
          : "▾"
        : "";
      twisty.tabIndex = hasChildren ? 0 : -1;
      if (hasChildren) {
        twisty.title = "Collapse or expand";
      }
      row.appendChild(twisty);

      if (node.color) {
        const swatch = document.createElement("span");
        swatch.className = "group-color";
        // A JabRef group colour is data from the file, not a theme decision.
        swatch.style.backgroundColor = node.color;
        row.appendChild(swatch);
      }

      const label = document.createElement("span");
      label.className = "group-name";
      label.textContent = node.name;
      let tooltip = node.description || node.name;
      if (node.groupType) {
        tooltip += `\n${node.groupType}`;
      }
      if (node.undeclared) {
        label.classList.add("undeclared");
        tooltip = "Referenced by entries but not declared in the file metadata.";
      }
      label.title = tooltip;
      row.appendChild(label);

      const count = document.createElement("span");
      count.className = "group-count";
      count.textContent = String(PV.groupKeys(node).size);
      row.appendChild(count);

      const actions = document.createElement("button");
      actions.type = "button";
      actions.className = "icon-button group-actions";
      actions.dataset.actionGroup = node.name;
      actions.textContent = "⋯";
      actions.title = "Change this group";
      actions.setAttribute("aria-label", 'Change group "' + node.name + '"');
      row.appendChild(actions);

      fragment.appendChild(row);
    }

    container.replaceChildren(fragment);
  };
})(window.PV);
