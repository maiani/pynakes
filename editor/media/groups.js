// @ts-check
/** The groups sidebar: the declared hierarchy, plus membership counts. */
window.PV = window.PV || {};

(function (PV) {
  "use strict";

  let container;

  PV.groupsInit = (element) => {
    container = element;
    container.addEventListener("click", onClick);
  };

  function onClick(event) {
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
    const name = row.dataset.group;
    // Clicking the selected group clears the filter, so the sidebar is a toggle.
    PV.state.selectedGroup = PV.state.selectedGroup === name ? null : name || null;
    PV.persist();
    PV.renderGroups();
    PV.renderTable();
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
    container.classList.toggle("collapsed", s.sidebarCollapsed);
    const fragment = document.createDocumentFragment();

    const heading = document.createElement("div");
    heading.className = "sidebar-heading";
    const label = document.createElement("span");
    label.className = "sidebar-heading-label";
    label.textContent = "Groups";
    heading.appendChild(label);
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "icon-button collapse-toggle sidebar-toggle";
    toggle.title = s.sidebarCollapsed ? "Expand groups" : "Collapse groups";
    toggle.textContent = s.sidebarCollapsed ? "▸" : "◂";
    heading.appendChild(toggle);
    fragment.appendChild(heading);

    if (s.sidebarCollapsed) {
      container.replaceChildren(fragment);
      return;
    }

    const all = document.createElement("div");
    all.className = "group-row" + (s.selectedGroup === null ? " selected" : "");
    all.dataset.group = "";
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
      empty.textContent = "This file declares no groups.";
      fragment.appendChild(empty);
    }

    for (const node of rows) {
      const row = document.createElement("div");
      row.className = "group-row" + (s.selectedGroup === node.name ? " selected" : "");
      row.dataset.group = node.name;
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

      fragment.appendChild(row);
    }

    container.replaceChildren(fragment);
  };
})(window.PV);
