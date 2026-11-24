// @ts-check
/** The entry table: columns, sorting, selection, and per-row status markers. */
window.PV = window.PV || {};

(function (PV) {
  "use strict";

  const SEVERITY_MARK = { error: "✖", warning: "▲", info: "ⓘ" };

  /** Narrowest a column may be dragged, so it stays clickable. */
  const MIN_COLUMN_WIDTH = 44;

  let body;
  let headers;
  let empty;
  let counts;

  PV.tableInit = (elements) => {
    body = elements.body;
    headers = elements.headers;
    empty = elements.empty;
    counts = elements.counts;

    body.addEventListener("click", (event) => {
      const row = event.target.closest("tr");
      if (row?.dataset.key) {
        PV.select(row.dataset.key, event);
      }
    });
    body.addEventListener("dblclick", (event) => {
      const row = event.target.closest("tr");
      if (row?.dataset.key) {
        PV.post({ type: "doubleClickEntry", key: row.dataset.key });
      }
    });

    body.addEventListener("dragstart", (event) => {
      const row = event.target.closest("tr[data-key]");
      if (!row || !event.dataTransfer) return;
      if (!PV.state.selectedKeys.has(row.dataset.key)) PV.select(row.dataset.key);
      PV.draggedKeys = [...PV.state.selectedKeys];
      event.dataTransfer.setData("application/x-pynakes-entries", JSON.stringify(PV.draggedKeys));
      event.dataTransfer.effectAllowed = "copy";
    });
    body.addEventListener("dragend", () => {
      PV.draggedKeys = null;
      document.querySelectorAll(".drop-target").forEach((row) => row.classList.remove("drop-target"));
    });

    installResizers();
    applyColumnWidths();

    for (const header of headers) {
      const activate = () => {
        const column = header.dataset.col;
        if (PV.state.sortColumn === column) {
          PV.state.sortDescending = !PV.state.sortDescending;
        } else {
          PV.state.sortColumn = column;
          PV.state.sortDescending = false;
        }
        PV.persist();
        PV.renderTable();
      };
      header.addEventListener("click", activate);
      header.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
        }
      });
    }
  };

  function allHeaders() {
    return body.closest("table").querySelectorAll("thead th");
  }

  /**
   * Apply remembered widths.
   *
   * Under `table-layout: fixed` the header cells decide the layout, so widths go
   * on the `th` elements. The table is then sized to their sum and allowed to
   * exceed the pane, which is what makes the pane scroll instead of squeezing
   * every column back to fit.
   */
  function applyColumnWidths() {
    const table = body.closest("table");
    const widths = PV.state.columnWidths;
    const cells = allHeaders();
    if (!widths.length) {
      table.style.width = "";
      table.style.minWidth = "";
      for (const cell of cells) {
        cell.style.width = "";
      }
      return;
    }
    let total = 0;
    cells.forEach((cell, index) => {
      const width = widths[index];
      if (typeof width === "number") {
        cell.style.width = width + "px";
        total += width;
      }
    });
    table.style.minWidth = "0";
    table.style.width = total + "px";
  }

  /** Freeze the current layout into explicit widths before the first drag. */
  function snapshotWidths() {
    if (PV.state.columnWidths.length > 0) {
      return;
    }
    PV.state.columnWidths = [...allHeaders()].map((cell) =>
      Math.round(cell.getBoundingClientRect().width),
    );
  }

  function startResize(event, index) {
    // Without this the drag would also register as a click and re-sort.
    event.preventDefault();
    event.stopPropagation();
    snapshotWidths();
    const startX = event.clientX;
    const startWidth = PV.state.columnWidths[index];

    const onMove = (move) => {
      PV.state.columnWidths[index] = Math.max(
        MIN_COLUMN_WIDTH,
        Math.round(startWidth + (move.clientX - startX)),
      );
      applyColumnWidths();
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.classList.remove("resizing");
      PV.persist();
    };
    document.body.classList.add("resizing");
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  function installResizers() {
    allHeaders().forEach((cell, index) => {
      const handle = document.createElement("span");
      handle.className = "col-resize";
      handle.title = "Drag to resize this column; double-click to reset all";
      handle.addEventListener("mousedown", (event) => startResize(event, index));
      handle.addEventListener("click", (event) => event.stopPropagation());
      handle.addEventListener("dblclick", (event) => {
        event.preventDefault();
        event.stopPropagation();
        PV.state.columnWidths = [];
        PV.persist();
        applyColumnWidths();
      });
      cell.appendChild(handle);
    });
  }

  /** Move the selection by `offset` rows and scroll it into view. */
  PV.moveSelection = (offset, modifiers = {}) => {
    const rows = PV.state.visible;
    if (rows.length === 0) {
      return;
    }
    const current = rows.findIndex((row) => row.key === PV.state.selectedKey);
    const next = Math.min(rows.length - 1, Math.max(0, current === -1 ? 0 : current + offset));
    PV.select(rows[next].key, modifiers);
    const element = body.querySelector(`tr[data-key="${CSS.escape(rows[next].key)}"]`);
    if (element) {
      element.scrollIntoView({ block: "nearest" });
    }
  };

  PV.select = (key, modifiers = {}) => {
    const s = PV.state;
    if (modifiers.shiftKey && s.selectionAnchor) {
      const keys = s.visible.map((row) => row.key);
      const anchor = keys.indexOf(s.selectionAnchor);
      const end = keys.indexOf(key);
      if (!modifiers.ctrlKey && !modifiers.metaKey) s.selectedKeys.clear();
      if (anchor >= 0 && end >= 0) {
        keys.slice(Math.min(anchor, end), Math.max(anchor, end) + 1).forEach((key) => s.selectedKeys.add(key));
      } else {
        s.selectedKeys.add(key);
      }
    } else if (modifiers.ctrlKey || modifiers.metaKey) {
      if (s.selectedKeys.has(key)) s.selectedKeys.delete(key);
      else s.selectedKeys.add(key);
      s.selectionAnchor = key;
    } else {
      s.selectedKeys = new Set([key]);
      s.selectionAnchor = key;
    }
    s.selectedKey = s.selectedKeys.has(key) ? key : [...s.selectedKeys].at(-1) || null;
    PV.persist();
    refreshSelection();
    PV.renderDetail();
  };

  PV.selectAll = () => {
    const s = PV.state;
    s.selectedKeys = new Set(s.visible.map((row) => row.key));
    s.selectedKey = s.visible[0]?.key || null;
    s.selectionAnchor = s.selectedKey;
    PV.persist();
    refreshSelection();
    PV.renderDetail();
  };

  function refreshSelection() {
    for (const row of body.querySelectorAll("tr[data-key]")) {
      const selected = PV.state.selectedKeys.has(row.dataset.key);
      row.classList.toggle("selected", selected);
      row.setAttribute("aria-selected", String(selected));
    }
    counts.textContent = counts.textContent.replace(/ · \d+ selected$/, "");
    if (PV.state.selectedKeys.size > 1) counts.textContent += ` · ${PV.state.selectedKeys.size} selected`;
  }

  function cell(text, className) {
    const td = document.createElement("td");
    td.className = className;
    td.textContent = text;
    td.title = text;
    return td;
  }

  PV.renderTable = () => {
    const s = PV.state;
    const rows = PV.computeVisible();
    const previousSelection = [...s.selectedKeys].join("\0");
    const previousKey = s.selectedKey;
    const visibleKeys = new Set(rows.map((row) => row.key));
    s.selectedKeys = new Set([...s.selectedKeys].filter((key) => visibleKeys.has(key)));
    if (!s.selectedKeys.size && s.selectedKey && visibleKeys.has(s.selectedKey)) s.selectedKeys.add(s.selectedKey);
    if (!s.selectedKeys.has(s.selectedKey)) s.selectedKey = [...s.selectedKeys][0] || null;
    const fragment = document.createDocumentFragment();

    for (const row of rows) {
      const tr = document.createElement("tr");
      tr.dataset.key = row.key;
      tr.tabIndex = -1;
      tr.draggable = true;
      tr.setAttribute("aria-selected", String(s.selectedKeys.has(row.key)));
      if (s.selectedKeys.has(row.key)) {
        tr.classList.add("selected");
      }

      const status = document.createElement("td");
      status.className = "col-status";
      if (PV.entryStaged(row.key)) {
        const dot = document.createElement("span");
        dot.className = "staged-dot";
        dot.textContent = "●";
        dot.title = "Has changes not yet applied";
        status.appendChild(dot);
      }
      const severity = PV.own(s.lint?.worstByKey, row.key);
      if (severity && s.showFindings !== false) {
        const mark = document.createElement("span");
        mark.className = `severity severity-${severity}`;
        mark.textContent = PV.own(SEVERITY_MARK, severity) || "•";
        const issues = PV.own(s.lint.byKey, row.key) || [];
        mark.title = issues.map((issue) => `${issue.severity}: ${issue.message}`).join("\n");
        status.appendChild(mark);
      }
      if (s.citations && !PV.isCited(row.key)) {
        const uncited = document.createElement("span");
        uncited.className = "uncited-mark";
        uncited.textContent = "○";
        uncited.title = "No linked TeX source cites this entry";
        status.appendChild(uncited);
      }
      const materials = PV.materialsOf(row.key);
      if (materials.length > 0) {
        const mark = document.createElement("span");
        const broken = materials.some((material) => !material.present);
        mark.className = "material-mark" + (broken ? " material-broken" : "");
        mark.textContent = "🗎";
        mark.title = materials
          .map((material) => material.label + (material.present ? "" : " — missing"))
          .join("\n");
        status.appendChild(mark);
      }
      tr.appendChild(status);

      const type = document.createElement("td");
      type.className = "col-type";
      const badge = document.createElement("span");
      badge.className = "type-badge";
      badge.textContent = row.type;
      type.appendChild(badge);
      type.title = row.type;
      tr.appendChild(type);

      const key = cell(row.key, "col-key");
      if (row.duplicate) {
        const dup = document.createElement("span");
        dup.className = "dup-badge";
        dup.textContent = "dup";
        dup.title = "This citation key occurs more than once in the file";
        key.appendChild(dup);
      }
      tr.appendChild(key);

      tr.appendChild(cell(row.author, "col-author"));
      tr.appendChild(cell(row.title, "col-title"));
      tr.appendChild(cell(row.year, "col-year"));
      tr.appendChild(cell(row.venue, "col-venue"));
      fragment.appendChild(tr);
    }
    body.replaceChildren(fragment);

    if (previousSelection !== [...s.selectedKeys].join("\0") || previousKey !== s.selectedKey) {
      PV.persist();
      PV.renderDetail();
    }

    const total = s.rows.length;
    const shown = rows.length;
    if (total === 0) {
      empty.textContent = "This file contains no entries.";
      empty.hidden = false;
    } else if (shown === 0) {
      empty.textContent = s.search.keys
        ? "No entry matches this search."
        : "No entry in this group.";
      empty.hidden = false;
    } else {
      empty.hidden = true;
    }

    const parts = [];
    parts.push(shown === total ? `${total} ${total === 1 ? "entry" : "entries"}` : `${shown} of ${total}`);
    if (s.search.keys && s.search.ranked) {
      parts.push("ranked");
    }
    if (s.search.busy) {
      parts.push("searching…");
    }
    if (s.selectedKeys.size > 1) parts.push(`${s.selectedKeys.size} selected`);
    counts.textContent = parts.join(" · ");

    for (const header of headers) {
      const active = header.dataset.col === s.sortColumn;
      header.setAttribute(
        "aria-sort",
        active ? (s.sortDescending ? "descending" : "ascending") : "none",
      );
      header.classList.toggle("sorted", active);
      header.classList.toggle("descending", active && s.sortDescending);
    }
  };
})(window.PV);
