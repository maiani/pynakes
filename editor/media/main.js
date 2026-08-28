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

  elements.uncited.addEventListener("change", () => {
    PV.state.uncitedOnly = elements.uncited.checked;
    PV.persist();
    PV.renderTable();
  });

  let searchTimer;
  function requestSearch() {
    const s = PV.state.search;
    s.query = elements.query.value;
    s.where = elements.where.value;
    s.fuzzy = elements.fuzzy.checked;
    PV.persist();
    clearTimeout(searchTimer);
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
      PV.post({ type: "search", query: s.query, where: s.where, fuzzy: s.fuzzy });
    }, SEARCH_DEBOUNCE_MS);
  }

  elements.query.addEventListener("input", requestSearch);
  elements.where.addEventListener("input", requestSearch);
  elements.fuzzy.addEventListener("change", requestSearch);

  elements.query.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      PV.moveSelection(1);
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
    if (typing) {
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      PV.moveSelection(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      PV.moveSelection(-1);
    } else if (event.key === "Enter" && PV.state.selectedKey) {
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
      const button = document.createElement("button");
      button.className = "button";
      button.type = "button";
      button.textContent = action.label;
      button.addEventListener("click", () => PV.post({ type: action.message }));
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

  function renderAll() {
    PV.renderGroups();
    PV.renderTable();
    PV.renderDocks();
  }

  window.addEventListener("message", (event) => {
    const message = event.data;
    const s = PV.state;

    switch (message.type) {
      case "render": {
        s.rows = message.payload.rows;
        s.summary = message.payload.summary;
        s.groups = message.payload.groups || [];
        s.groupsByEntry = message.payload.groupsByEntry || {};
        s.lint = message.payload.lint || null;
        s.citations = message.payload.citations || null;
        s.materials = message.payload.materials || null;
        s.warnings = message.payload.warnings || [];
        s.engine = message.engine;
        s.dirty = message.dirty;
        s.staging = message.staging || { entries: {} };
        s.counts = countStaged(s.staging);
        if (message.settings) {
          s.showFindings = message.settings.showFindings !== false;
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
        s.search.keys = message.keys;
        s.search.ranked = message.ranked;
        s.search.error = null;
        s.search.busy = false;
        PV.renderTable();
        clearNotice();
        break;
      case "searchCleared":
        s.search.keys = null;
        s.search.error = null;
        s.search.busy = false;
        PV.renderTable();
        clearNotice();
        break;
      case "searchError":
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
        s.compareBusy = null;
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
        s.compareBusy = null;
        s.compare = { key: message.key, error: message.message };
        PV.showPane("compare");
        break;
      case "keyRenamed":
        s.renameBusy = null;
        if (s.selectedKey === message.oldKey) {
          s.selectedKey = message.newKey;
          PV.persist();
        }
        notify("success", "Renamed " + message.oldKey + " to " + message.newKey + ".");
        break;
      case "renameKeyCancelled":
        s.renameBusy = null;
        PV.renderDocks();
        break;
      case "renameKeyError":
        s.renameBusy = null;
        notify("error", "Rename failed: " + message.message);
        PV.renderDocks();
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
      case "engineError":
        s.rows = [];
        s.summary = null;
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
