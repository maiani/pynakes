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
        PV.select(row.dataset.key);
      }
    });
    body.addEventListener("dblclick", (event) => {
      const row = event.target.closest("tr");
      if (row?.dataset.key) {
        PV.post({ type: "reveal", key: row.dataset.key });
      }
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
  PV.moveSelection = (offset) => {
    const rows = PV.state.visible;
    if (rows.length === 0) {
      return;
    }
    const current = rows.findIndex((row) => row.key === PV.state.selectedKey);
    const next = Math.min(rows.length - 1, Math.max(0, current === -1 ? 0 : current + offset));
    PV.select(rows[next].key);
    const element = body.querySelector(`tr[data-key="${CSS.escape(rows[next].key)}"]`);
    if (element) {
      element.scrollIntoView({ block: "nearest" });
    }
  };

  PV.select = (key) => {
    PV.state.selectedKey = key;
    PV.persist();
    for (const row of body.querySelectorAll("tr")) {
      row.classList.toggle("selected", row.dataset.key === key);
    }
    PV.renderDetail();
  };

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
    const fragment = document.createDocumentFragment();

    for (const row of rows) {
      const tr = document.createElement("tr");
      tr.dataset.key = row.key;
      tr.tabIndex = -1;
      if (row.key === s.selectedKey) {
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
      const severity = s.lint?.worstByKey?.[row.key];
      if (severity && s.showFindings !== false) {
        const mark = document.createElement("span");
        mark.className = `severity severity-${severity}`;
        mark.textContent = SEVERITY_MARK[severity] || "•";
        const issues = s.lint.byKey[row.key] || [];
        mark.title = issues.map((issue) => `${issue.severity}: ${issue.message}`).join("\n");
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
