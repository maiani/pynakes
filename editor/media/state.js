// @ts-check
/**
 * Shared state for the bibliography view.
 *
 * The webview holds presentation state only — what is selected, sorted,
 * collapsed, typed into the search box. The authoritative data comes from the
 * extension on every render, and staged edits live in the extension so they
 * survive this webview being disposed when its tab is hidden.
 */
window.PV = window.PV || {};

(function (PV) {
  "use strict";

  const vscode = acquireVsCodeApi();
  PV.post = (message) => vscode.postMessage(message);

  const persisted = vscode.getState() || {};

  PV.state = {
    rows: [],
    summary: null,
    groups: [],
    groupsByEntry: {},
    lint: null,
    engine: null,
    warnings: [],
    dirty: false,
    staging: { entries: {} },
    counts: { fields: 0, entries: 0 },
    search: {
      query: typeof persisted.query === "string" ? persisted.query : "",
      where: typeof persisted.where === "string" ? persisted.where : "",
      fuzzy: Boolean(persisted.fuzzy),
      keys: null,
      ranked: false,
      error: null,
      busy: false,
    },
    selectedGroup: persisted.selectedGroup || null,
    collapsedGroups: new Set(Array.isArray(persisted.collapsed) ? persisted.collapsed : []),
    selectedKey: persisted.selectedKey || null,
    sortColumn: persisted.sortColumn || "index",
    sortDescending: Boolean(persisted.sortDescending),
    panel: persisted.panel || "findings",
    // Column widths in pixels, by column position. Empty means the stylesheet
    // decides; the first drag snapshots the current layout so nothing jumps.
    columnWidths: Array.isArray(persisted.columnWidths) ? persisted.columnWidths : [],
    diff: null,
    notice: null,
    visible: [],
  };

  PV.persist = () => {
    const s = PV.state;
    vscode.setState({
      query: s.search.query,
      where: s.search.where,
      fuzzy: s.search.fuzzy,
      selectedGroup: s.selectedGroup,
      collapsed: [...s.collapsedGroups],
      selectedKey: s.selectedKey,
      sortColumn: s.sortColumn,
      sortDescending: s.sortDescending,
      panel: s.panel,
      columnWidths: s.columnWidths,
    });
  };

  /** Find a group node by name anywhere in the tree. */
  PV.findGroup = (name) => {
    let found = null;
    const walk = (nodes) => {
      for (const node of nodes) {
        if (node.name === name) {
          found = node;
          return;
        }
        walk(node.children || []);
      }
    };
    walk(PV.state.groups || []);
    return found;
  };

  /** Every key in a group and its descendants. */
  PV.groupKeys = (node) => {
    const keys = new Set();
    const walk = (current) => {
      for (const key of current.keys || []) {
        keys.add(key);
      }
      for (const child of current.children || []) {
        walk(child);
      }
    };
    walk(node);
    return keys;
  };

  /** The pending change for one field, or undefined. */
  PV.stagedField = (key, field) => PV.state.staging.entries?.[key]?.fields?.[field];

  /** True when the entry has any pending change. */
  PV.entryStaged = (key) => Boolean(PV.state.staging.entries?.[key]);

  /** Displayed value of a field: the staged one when present, else the file's. */
  PV.effectiveValue = (row, field) => {
    const staged = PV.stagedField(row.key, field);
    if (staged) {
      return staged.value;
    }
    return row.fields[field] ?? null;
  };

  /** Field names to show for an entry: stored fields plus any staged additions. */
  PV.fieldNames = (row) => {
    const names = new Set(Object.keys(row.fields));
    const staged = PV.state.staging.entries?.[row.key];
    for (const field of Object.keys(staged?.fields || {})) {
      names.add(field);
    }
    return [...names];
  };

  const SORTABLE = {
    type: (row) => row.type,
    key: (row) => row.key.toLowerCase(),
    author: (row) => row.author.toLowerCase(),
    title: (row) => row.title.toLowerCase(),
    year: (row) => row.year,
    venue: (row) => row.venue.toLowerCase(),
  };

  /**
   * Decide which rows are shown, and in what order.
   *
   * Search and group selection intersect: both narrow the set. When a ranked
   * search is active and no column sort was chosen, the engine's relevance order
   * is preserved rather than replaced by file order.
   */
  PV.computeVisible = () => {
    const s = PV.state;
    let rows = s.rows.slice();

    if (s.search.keys) {
      const allowed = new Set(s.search.keys);
      rows = rows.filter((row) => allowed.has(row.key));
    }
    if (s.selectedGroup) {
      const node = PV.findGroup(s.selectedGroup);
      if (node) {
        const keys = PV.groupKeys(node);
        rows = rows.filter((row) => keys.has(row.key));
      }
    }

    const rankOrder = s.search.keys && s.search.ranked && s.sortColumn === "index";
    if (rankOrder) {
      const position = new Map(s.search.keys.map((key, index) => [key, index]));
      rows.sort((a, b) => (position.get(a.key) ?? 0) - (position.get(b.key) ?? 0));
    } else if (s.sortColumn !== "index") {
      const read = SORTABLE[s.sortColumn];
      rows.sort((a, b) => {
        const left = read(a);
        const right = read(b);
        if (left === right) {
          return a.index - b.index;
        }
        // Blanks sort last regardless of direction, so gaps never lead.
        if (!left) {
          return 1;
        }
        if (!right) {
          return -1;
        }
        return left < right ? -1 : 1;
      });
      if (s.sortDescending) {
        rows.reverse();
      }
    } else {
      rows.sort((a, b) => a.index - b.index);
    }

    s.visible = rows;
    return rows;
  };
})(window.PV);
