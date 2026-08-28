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
    /** Citation occurrences per key, from the linked TeX sources. */
    citations: null,
    /** Materials per key, with whether each is on disk. */
    materials: null,
    engine: null,
    warnings: [],
    dirty: false,
    staging: { entries: {} },
    counts: { fields: 0, entries: 0 },
    search: {
      query: typeof persisted.query === "string" ? persisted.query : "",
      where: typeof persisted.where === "string" ? persisted.where : "",
      // null until the first render delivers the pynakes.search.fuzzy setting;
      // a persisted boolean (the user toggled it) always wins over the setting.
      fuzzy: typeof persisted.fuzzy === "boolean" ? persisted.fuzzy : null,
      keys: null,
      ranked: false,
      error: null,
      busy: false,
    },
    showFindings: true,
    /** When set, the table shows only entries no linked TeX source cites. */
    uncitedOnly: Boolean(persisted.uncitedOnly),
    selectedGroup: persisted.selectedGroup || null,
    collapsedGroups: new Set(Array.isArray(persisted.collapsed) ? persisted.collapsed : []),
    sidebarCollapsed: Boolean(persisted.sidebarCollapsed),
    selectedKey: persisted.selectedKey || null,
    sortColumn: persisted.sortColumn || "index",
    sortDescending: Boolean(persisted.sortDescending),
    // Which pane is active in each dock ("right" / "bottom").
    dock: {
      right: typeof persisted.dock?.right === "string" ? persisted.dock.right : "edit",
      bottom: typeof persisted.dock?.bottom === "string" ? persisted.dock.bottom : "findings",
    },
    // Where each relocatable pane currently lives: "right" or "bottom".
    paneDock: {
      edit: persisted.paneDock?.edit || "right",
      findings: persisted.paneDock?.findings || "bottom",
      diff: persisted.paneDock?.diff || "bottom",
      compare: persisted.paneDock?.compare || "bottom",
    },
    panelCollapsed: Boolean(persisted.panelCollapsed),
    // Column widths in pixels, by column position. Empty means the stylesheet
    // decides; the first drag snapshots the current layout so nothing jumps.
    columnWidths: Array.isArray(persisted.columnWidths) ? persisted.columnWidths : [],
    // Pane sizes in pixels. `null` means the stylesheet decides.
    sidebarWidth: typeof persisted.sidebarWidth === "number" ? persisted.sidebarWidth : null,
    detailWidth: typeof persisted.detailWidth === "number" ? persisted.detailWidth : null,
    panelHeight: typeof persisted.panelHeight === "number" ? persisted.panelHeight : null,
    diff: null,
    notice: null,
    visible: [],
    /** Last "Compare with remote" result or error, for the entry it was run on. */
    compare: null,
    /** Citation key currently awaiting a compare response, or null. */
    compareBusy: null,
    /** Citation key currently awaiting a rename response, or null. */
    renameBusy: null,
  };

  PV.persist = () => {
    const s = PV.state;
    vscode.setState({
      query: s.search.query,
      where: s.search.where,
      fuzzy: s.search.fuzzy,
      selectedGroup: s.selectedGroup,
      collapsed: [...s.collapsedGroups],
      sidebarCollapsed: s.sidebarCollapsed,
      selectedKey: s.selectedKey,
      sortColumn: s.sortColumn,
      sortDescending: s.sortDescending,
      panelCollapsed: s.panelCollapsed,
      uncitedOnly: s.uncitedOnly,
      dock: s.dock,
      paneDock: s.paneDock,
      columnWidths: s.columnWidths,
      sidebarWidth: s.sidebarWidth,
      detailWidth: s.detailWidth,
      panelHeight: s.panelHeight,
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

  /**
   * True when a linked TeX source cites this key.
   *
   * A `\nocite{*}` cites everything, so it makes every entry cited. With no
   * citation read at all (no linked sources, or an unsaved new file) nothing is
   * known, which is not the same as uncited — callers check `state.citations`
   * before showing either.
   */
  PV.isCited = (key) => {
    const index = PV.state.citations;
    if (!index) {
      return false;
    }
    return index.includeAll || (index.byKey?.[key] || []).length > 0;
  };

  /** Where this key is cited, in scan order. */
  PV.citationsOf = (key) => PV.state.citations?.byKey?.[key] || [];

  /** The materials this entry points to, present ones first. */
  PV.materialsOf = (key) => PV.state.materials?.byKey?.[key] || [];

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

  /**
   * Bring a pane to the front in whichever dock it currently lives, expanding
   * that dock. The pane itself does not move — `PV.relocatePane` does that.
   */
  PV.showPane = (pane) => {
    const loc = PV.state.paneDock[pane] || "bottom";
    PV.state.dock[loc] = pane;
    PV.state.panelCollapsed = false;
    PV.persist();
    PV.renderDocks();
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
    if (s.uncitedOnly && s.citations) {
      rows = rows.filter((row) => !PV.isCited(row.key));
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
      // Direction lives in the comparator rather than a post-sort reverse, so
      // the blank-last rule below holds for both directions.
      const descending = s.sortDescending;
      rows.sort((a, b) => {
        const left = read(a);
        const right = read(b);
        if (!left || !right) {
          // Blanks sort last regardless of direction, so gaps never lead.
          if (left === right) {
            return a.index - b.index;
          }
          return left ? -1 : 1;
        }
        if (left === right) {
          return a.index - b.index;
        }
        const ordered = left < right ? -1 : 1;
        return descending ? -ordered : ordered;
      });
    } else {
      rows.sort((a, b) => a.index - b.index);
    }

    s.visible = rows;
    return rows;
  };
})(window.PV);
