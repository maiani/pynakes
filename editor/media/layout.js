// @ts-check
/**
 * Resizable pane borders: the groups sidebar, the detail pane, and the
 * bottom findings/diff panel. Mirrors the table's column-resize drag (see
 * `table.js`), with each dragged size remembered per workspace via
 * `PV.persist()`.
 */
window.PV = window.PV || {};

(function (PV) {
  "use strict";

  const MIN_PANE = 120;
  const MIN_PANEL_HEIGHT = 80;

  let sidebar, detail, panelEl;

  PV.layoutInit = (elements) => {
    sidebar = elements.sidebar;
    detail = elements.detail;
    panelEl = elements.panel;

    PV.applyPaneSizes();

    installSplitter(elements.sidebarSplitter, {
      axis: "x",
      sign: 1,
      measure: () => sidebar.getBoundingClientRect().width,
      get: () => PV.state.sidebarWidth,
      set: (value) => (PV.state.sidebarWidth = value),
    });
    installSplitter(elements.detailSplitter, {
      axis: "x",
      sign: -1,
      measure: () => detail.getBoundingClientRect().width,
      get: () => PV.state.detailWidth,
      set: (value) => (PV.state.detailWidth = value),
    });
    installSplitter(elements.panelSplitter, {
      axis: "y",
      sign: -1,
      min: MIN_PANEL_HEIGHT,
      measure: () => panelEl.getBoundingClientRect().height,
      get: () => PV.state.panelHeight,
      set: (value) => (PV.state.panelHeight = value),
    });
  };

  /**
   * Apply remembered pane sizes as an explicit `flex-basis`, overriding the
   * stylesheet's default. `null` clears the override, letting the stylesheet
   * decide again. A collapsed pane keeps its stylesheet (collapsed) size
   * regardless of any remembered width, so collapsing still works.
   */
  PV.applyPaneSizes = () => {
    const s = PV.state;
    sidebar.style.flexBasis =
      !s.sidebarCollapsed && typeof s.sidebarWidth === "number" ? s.sidebarWidth + "px" : "";
    detail.style.flexBasis = typeof s.detailWidth === "number" ? s.detailWidth + "px" : "";
    panelEl.style.flexBasis =
      !s.panelCollapsed && typeof s.panelHeight === "number" ? s.panelHeight + "px" : "";
  };

  function installSplitter(handle, config) {
    handle.addEventListener("mousedown", (event) => startDrag(event, config));
    handle.addEventListener("dblclick", (event) => {
      event.preventDefault();
      config.set(null);
      PV.persist();
      PV.applyPaneSizes();
    });
  }

  function startDrag(event, config) {
    // Without this the drag would also start a text selection.
    event.preventDefault();
    const min = config.min || MIN_PANE;
    const cursorClass = config.axis === "x" ? "resizing" : "resizing-row";
    const start = config.axis === "x" ? event.clientX : event.clientY;
    const startSize = config.measure();

    const onMove = (move) => {
      const current = config.axis === "x" ? move.clientX : move.clientY;
      const delta = (current - start) * config.sign;
      config.set(Math.max(min, Math.round(startSize + delta)));
      PV.applyPaneSizes();
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.classList.remove(cursorClass);
      PV.persist();
    };
    document.body.classList.add(cursorClass);
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }
})(window.PV);
