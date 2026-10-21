// @ts-check
/** Wiring: toolbar controls, keyboard handling, and messages from the extension. */
window.PV = window.PV || {};

(function (PV) {
  "use strict";

  /** Searching spawns an engine process, so keystrokes are coalesced. */
  const SEARCH_DEBOUNCE_MS = 300;

  const elements = {
    query: document.getElementById("query"),
    where: document.getElementById("where"),
    fuzzy: document.getElementById("fuzzy"),
    uncited: document.getElementById("uncited"),
    counts: document.getElementById("counts"),
    banner: document.getElementById("banner"),
    notice: document.getElementById("notice"),
    groups: document.getElementById("groups"),
    rows: document.getElementById("rows"),
    empty: document.getElementById("empty"),
    rightDock: document.getElementById("right-dock"),
    rightTabs: document.getElementById("right-tabs"),
    rightBody: document.getElementById("right-body"),
    bottomDock: document.getElementById("bottom-dock"),
    bottomTabs: document.getElementById("bottom-tabs"),
    bottomBody: document.getElementById("bottom-body"),
    commitBar: document.getElementById("commit-bar"),
    headers: document.querySelectorAll("th[data-col]"),
    importEntry: document.getElementById("import-entry"),
    addEntry: document.getElementById("add-entry"),
    sidebarSplitter: document.getElementById("sidebar-splitter"),
    detailSplitter: document.getElementById("detail-splitter"),
    panelSplitter: document.getElementById("panel-splitter"),
  };

  PV.tableInit({
    body: elements.rows,
    headers: elements.headers,
    empty: elements.empty,
    counts: elements.counts,
  });
  PV.groupsInit(elements.groups);
  PV.panelsInit({
    rightDock: elements.rightDock,
    rightTabs: elements.rightTabs,
    rightBody: elements.rightBody,
    bottomDock: elements.bottomDock,
    bottomTabs: elements.bottomTabs,
    bottomBody: elements.bottomBody,
    detailSplitter: elements.detailSplitter,
    panelSplitter: elements.panelSplitter,
    bar: elements.commitBar,
  });
  PV.layoutInit({
    sidebar: elements.groups,
    detail: elements.rightDock,
    panel: elements.bottomDock,
    sidebarSplitter: elements.sidebarSplitter,
    detailSplitter: elements.detailSplitter,
    panelSplitter: elements.panelSplitter,
  });

  elements.query.value = PV.state.search.query;
  elements.where.value = PV.state.search.where;
  elements.fuzzy.checked = PV.state.search.fuzzy;
  elements.uncited.checked = PV.state.uncitedOnly;

  // The mutating actions all hand off to the extension, which prompts for what
  // it needs and runs the change through preview-and-approve. The view never
  // builds an entry or a group name itself.
  elements.importEntry.addEventListener("click", () => PV.post({ type: "promptImport" }));
  elements.addEntry.addEventListener("click", () => PV.post({ type: "promptAdd" }));
  elements.uncited.addEventListener("change", () => {
    PV.state.uncitedOnly = elements.uncited.checked;
    PV.persist();
    PV.renderTable();
  });

  let searchTimer;
  /**
   * Numbers each search sent. Every search is its own engine process, and they
   * can answer out of order; only the answer to the latest one is shown.
   */
  let searchSeq = 0;
  function requestSearch() {
    const s = PV.state.search;
    s.query = elements.query.value;
    s.where = elements.where.value;
    s.fuzzy = elements.fuzzy.checked;
    PV.persist();
    clearTimeout(searchTimer);
    // Whatever is still running answers a question no longer asked.
    searchSeq += 1;
    if (!s.query.trim() && !s.where.trim()) {
      s.keys = null;
      s.error = null;
      s.busy = false;
      PV.renderTable();
      PV.renderDocks();
      return;
    }
    s.busy = true;
    PV.renderTable();
    searchTimer = setTimeout(() => {
      PV.post({ type: "search", seq: searchSeq, query: s.query, where: s.where, fuzzy: s.fuzzy });
    }, SEARCH_DEBOUNCE_MS);
  }

  elements.query.addEventListener("input", requestSearch);
  elements.where.addEventListener("input", requestSearch);
  elements.fuzzy.addEventListener("change", requestSearch);

  elements.query.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      PV.moveSelection(1, event);
    } else if (event.key === "Escape" && elements.query.value) {
      event.preventDefault();
      elements.query.value = "";
      requestSearch();
    }
  });

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const typing =
      target === elements.query ||
      target === elements.where ||
      (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA"));
    if ((event.ctrlKey || event.metaKey) && event.key === "f") {
      event.preventDefault();
      elements.query.focus();
      elements.query.select();
      return;
    }
    // A key a control already handled — a group row's Enter, say — is not
    // also the table's; and Enter on a button is that button's click, not a
    // request to open the selected entry's source.
    const control =
      target && typeof target.closest === "function"
        ? target.closest("button, select, a, [role='button']")
        : null;
    if (typing || event.defaultPrevented) {
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a" && !control) {
      event.preventDefault();
      PV.selectAll();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      PV.moveSelection(1, event);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      PV.moveSelection(-1, event);
    } else if (event.key === "Enter" && !control && PV.state.selectedKey) {
      event.preventDefault();
      PV.post({ type: "reveal", key: PV.state.selectedKey });
    }
  });

  function showBanner(kind, message, detail, action) {
    elements.banner.replaceChildren();
    elements.banner.className = "banner banner-" + kind;
    const strong = document.createElement("strong");
    strong.textContent = message;
    elements.banner.appendChild(strong);
    if (detail) {
      const paragraph = document.createElement("p");
      paragraph.textContent = detail;
      elements.banner.appendChild(paragraph);
    }
    if (action) {
      const button = PV.button("button", action.label, null, () =>
        PV.post({ type: action.message }),
      );
      elements.banner.appendChild(button);
    }
    elements.banner.hidden = false;
  }

  function clearBanner() {
    elements.banner.hidden = true;
    elements.banner.replaceChildren();
  }

  /** A transient line above the table for outcomes that are not errors. */
  function notify(kind, text) {
    elements.notice.className = "notice notice-" + kind;
    elements.notice.textContent = text;
    elements.notice.hidden = false;
  }

  function clearNotice() {
    elements.notice.hidden = true;
    elements.notice.textContent = "";
  }

  /** Messages that end a mutation, whatever its outcome. */
  const MUTATION_ENDS = new Set(["mutationDone", "mutationNoop", "mutationCancelled", "mutationError"]);

  function renderAll() {
    PV.renderGroups();
    PV.renderTable();
    PV.renderDocks();
  }

  window.addEventListener("message", (event) => {
    const message = event.data;
    const s = PV.state;
    const staleSearch =
      typeof message.seq === "number" && message.seq !== searchSeq;

    // A key rename is a mutation like any other, so whichever way one ends —
    // written, declined, cancelled, nothing to do — the key field is released
    // and re-rendered from the entry as it now is.
    if (MUTATION_ENDS.has(message.type) && s.renameBusy) {
      s.renameBusy = null;
      if (message.type !== "mutationDone") {
        PV.renderDocks();
      }
    }

    switch (message.type) {
      case "render": {
        s.rows = message.payload.rows;
        s.summary = message.payload.summary;
        s.groups = message.payload.groups || [];
        s.groupsByEntry = message.payload.groupsByEntry || {};
        s.entrySchemas = message.payload.entrySchemas || [];
        s.lint = message.payload.lint || null;
        s.citations = message.payload.citations || null;
        s.materials = message.payload.materials || null;
        s.metadata = message.payload.metadata || null;
        s.warnings = message.payload.warnings || [];
        s.engine = message.engine;
        s.dirty = message.dirty;
        s.staging = message.staging || { entries: {} };
        s.counts = countStaged(s.staging);
        if (message.settings) {
          s.showFindings = message.settings.showFindings !== false;
          s.openMaterialsWith =
            message.settings.openMaterialsWith === "system" ? "system" : "editor";
          if (s.search.fuzzy === null && typeof message.settings.fuzzy === "boolean") {
            // First render: seed the toggle from the setting. Afterwards the
            // user's own toggle (persisted) decides.
            s.search.fuzzy = message.settings.fuzzy;
            elements.fuzzy.checked = s.search.fuzzy;
          }
        }
        if (s.selectedKey && !s.rows.some((row) => row.key === s.selectedKey)) {
          s.selectedKey = null;
        }
        PV.computeVisible();
        if (!s.selectedKey && s.visible.length > 0) {
          s.selectedKey = s.visible[0].key;
          PV.persist();
        }
        clearBanner();
        if (s.warnings.length > 0) {
          notify("warning", s.warnings.join("  ·  "));
        } else if (elements.notice.classList.contains("notice-warning")) {
          clearNotice();
        }
        renderAll();
        break;
      }
      case "staging":
        s.staging = message.staging || { entries: {} };
        s.counts = message.counts || countStaged(s.staging);
        // Keep the caret where it is if the user is still typing in a field.
        PV.renderDocks({ preserveFocus: true });
        PV.renderTable();
        break;
      case "searchResult":
        if (staleSearch) {
          break;
        }
        s.search.keys = message.keys;
        s.search.ranked = message.ranked;
        s.search.error = null;
        s.search.busy = false;
        PV.renderTable();
        clearNotice();
        break;
      case "searchCleared":
        if (staleSearch) {
          break;
        }
        s.search.keys = null;
        s.search.error = null;
        s.search.busy = false;
        PV.renderTable();
        clearNotice();
        break;
      case "searchError":
        if (staleSearch) {
          break;
        }
        s.search.busy = false;
        s.search.error = message.message;
        notify("error", "Search rejected: " + message.message);
        PV.renderTable();
        break;
      case "diff":
        s.diff = message.entries;
        PV.showPane("diff");
        break;
      case "compareResult":
        if (s.compareBusy === message.key) {
          s.compareBusy = null;
        }
        s.compare = {
          key: message.key,
          source: message.source,
          identifier: message.identifier,
          fields: message.fields || [],
          warnings: message.warnings || [],
        };
        PV.showPane("compare");
        break;
      case "compareError":
        if (s.compareBusy === message.key) {
          s.compareBusy = null;
        }
        s.compare = { key: message.key, error: message.message };
        PV.showPane("compare");
        break;
      case "duplicates":
        s.duplicates = message.clusters || [];
        PV.showPane("duplicates");
        break;
      case "duplicatesError":
        s.duplicates = { error: message.message };
        PV.showPane("duplicates");
        break;
      case "mutationDone":
        if (message.metadataChanged) s.metadataDraft = null;
        notify("success", message.label + ": done.");
        // Any write can invalidate the cluster list — a merge resolves one, a
        // remove can empty one, an import can create one. Clearing it says
        // "ask again" rather than showing a cluster that no longer exists.
        s.duplicates = null;
        if (message.renamedGroup && s.selectedGroup === message.renamedGroup.from) {
          s.selectedGroup = message.renamedGroup.to;
          PV.persist();
        }
        if (message.renamedKey && s.selectedKey === message.renamedKey.from) {
          s.selectedKeys.delete(message.renamedKey.from);
          s.selectedKeys.add(message.renamedKey.to);
          s.selectedKey = message.renamedKey.to;
          PV.persist();
        }
        if (message.select) {
          // The reload that follows renders the table; remembering the key here
          // means the new entry is selected as soon as it exists.
          s.selectedKey = message.select;
          s.selectedKeys = new Set([message.select]);
          PV.persist();
        }
        break;
      case "fetchState":
        // The fetch is over, whatever its outcome: its buttons work again.
        if (!message.busy) {
          s.fetchBusy = null;
          PV.renderDocks();
        }
        break;
      case "fetchDone":
        notify(message.level || "info", message.message);
        break;
      case "mutationNoop":
        notify("info", message.message);
        break;
      case "mutationCancelled":
        if (!message.quiet) {
          notify("info", message.label + ": cancelled, nothing written.");
        }
        break;
      case "mutationError":
        notify("error", message.label + ": " + message.message);
        break;
      case "conflict": {
        const detail = message.conflicts
          .map(
            (conflict) =>
              conflict.key + "." + conflict.field +
              ": expected " + describe(conflict.expected) +
              ", file has " + describe(conflict.actual),
          )
          .join("\n");
        showBanner("error", message.message, detail, null);
        PV.showPane("diff");
        break;
      }
      case "committed":
        s.diff = null;
        notify(
          "success",
          "Applied " + message.applied.length +
            (message.applied.length === 1 ? " entry" : " entries") +
            (message.warnings.length ? " — " + message.warnings.join("; ") : ""),
        );
        PV.renderDocks();
        break;
      case "commitCancelled":
        notify("info", "Apply cancelled. Nothing was written.");
        break;
      case "commitError":
        showBanner("error", "Apply failed", message.message, null);
        break;
      case "parseError":
        s.rows = [];
        s.summary = null;
        s.metadata = null;
        s.materials = null;
        s.groups = [];
        s.lint = null;
        showBanner(
          "error",
          message.line ? message.error + " at line " + message.line : message.error,
          message.message,
          { label: "Open as text", message: "openAsText" },
        );
        renderAll();
        elements.empty.hidden = true;
        break;
      case "actionError":
        // An action failed, but the file is as the last read showed it: the
        // table stays, and whatever was waiting on the action is released.
        s.renameBusy = null;
        s.compareBusy = null;
        showBanner(
          "error",
          message.message,
          message.detail,
          message.kind === "unavailable" ? { label: "Open settings", message: "openSettings" } : null,
        );
        PV.renderDocks();
        break;
      case "engineError":
        s.rows = [];
        s.summary = null;
        s.metadata = null;
        s.materials = null;
        s.groups = [];
        s.lint = null;
        showBanner(
          "error",
          message.message,
          message.detail,
          message.kind === "unavailable" ? { label: "Open settings", message: "openSettings" } : null,
        );
        renderAll();
        elements.empty.hidden = true;
        break;
      default:
        break;
    }
  });

  function describe(value) {
    return value === null || value === undefined ? "no value" : JSON.stringify(value);
  }

  function countStaged(staging) {
    let fields = 0;
    const entries = Object.values(staging.entries || {});
    for (const entry of entries) {
      fields += Object.keys(entry.fields || {}).length + (entry.entryType ? 1 : 0);
    }
    return { fields, entries: entries.length };
  }

  PV.post({ type: "ready" });
})(window.PV);
