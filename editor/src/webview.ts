/** The static webview shell: markup, CSP, and resource URIs. */

import { randomBytes } from "node:crypto";
import * as vscode from "vscode";

/** Fresh unguessable nonce per load, so the CSP can allow exactly our scripts. */
function nonce(): string {
  return randomBytes(24).toString("base64url");
}

const COLUMNS: Array<{ id: string; label: string; className: string }> = [
  { id: "type", label: "Type", className: "col-type" },
  { id: "key", label: "Citation key", className: "col-key" },
  { id: "author", label: "Author", className: "col-author" },
  { id: "title", label: "Title", className: "col-title" },
  { id: "year", label: "Year", className: "col-year" },
  { id: "venue", label: "Published in", className: "col-venue" },
];

/**
 * Client scripts, in load order.
 *
 * They share a `window.PV` namespace rather than using ES modules: a nonce does
 * not extend to statically imported modules under this CSP, and `strict-dynamic`
 * would loosen it more than this view needs.
 */
const SCRIPTS = [
  "state.js",
  "table.js",
  "groups.js",
  "detail.js",
  "panels.js",
  "layout.js",
  "main.js",
];

/** Build the full HTML document for one bibliography view. */
export function renderShell(webview: vscode.Webview, extensionUri: vscode.Uri): string {
  const asset = (...parts: string[]): vscode.Uri =>
    webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, ...parts));
  const styleUri = asset("media", "view.css");
  const token = nonce();
  // `unsafe-inline` covers style *properties* set through the CSSOM: the group
  // sidebar indents by depth and paints each group's declared colour. Values are
  // assigned via `element.style.x`, which rejects anything malformed, so file
  // content cannot smuggle CSS through it; no stylesheet text is ever built from
  // bibliography data. Scripts remain nonce-only.
  const csp = [
    "default-src 'none'",
    `style-src ${webview.cspSource} 'unsafe-inline'`,
    `font-src ${webview.cspSource}`,
    `img-src ${webview.cspSource} data:`,
    `script-src 'nonce-${token}'`,
  ].join("; ");

  const headers = COLUMNS.map(
    (column) =>
      `<th class="${column.className}" data-col="${column.id}" tabindex="0" role="columnheader"` +
      ` aria-sort="none"><span>${column.label}</span></th>`,
  ).join("");

  const scripts = SCRIPTS.map(
    (name) => `<script nonce="${token}" src="${asset("media", name)}"></script>`,
  ).join("\n");

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link href="${styleUri}" rel="stylesheet">
<title>Bibliography</title>
</head>
<body>
<header class="toolbar">
  <input id="query" class="filter" type="search" spellcheck="false"
         placeholder="Search entries — words, phrases, field:term" aria-label="Search query">
  <input id="where" class="filter where" type="text" spellcheck="false"
         placeholder="--where 'year >= 2020 and doi missing'" aria-label="Where predicate">
  <label class="toggle" title="Also match misspellings and inflections by similarity">
    <input id="fuzzy" type="checkbox"> fuzzy
  </label>
  <label class="toggle" title="Show only entries no linked TeX source cites">
    <input id="uncited" type="checkbox"> uncited
  </label>
  <span id="counts" class="counts" aria-live="polite"></span>
  <span class="toolbar-actions">
    <button id="import-entry" class="button" type="button"
            title="Add a reference from a DOI, arXiv id, or supported URL">Import…</button>
    <button id="add-entry" class="button" type="button"
            title="Add an empty entry to fill in here">New entry</button>
    <button id="find-duplicates" class="button" type="button"
            title="Find entries the engine judges to be the same work">Duplicates</button>
  </span>
</header>
<div id="banner" class="banner" hidden></div>
<div id="notice" class="notice" hidden></div>
<main class="layout">
  <nav id="groups" class="sidebar" aria-label="Groups"></nav>
  <div id="sidebar-splitter" class="pane-splitter" title="Drag to resize; double-click to reset"></div>
  <section class="center">
    <div class="table-pane">
      <table class="entries" aria-label="Bibliography entries">
        <thead><tr><th class="col-status" aria-label="Status"></th>${headers}</tr></thead>
        <tbody id="rows"></tbody>
      </table>
      <p id="empty" class="empty" hidden></p>
    </div>
    <div id="panel-splitter" class="pane-splitter pane-splitter-horizontal" title="Drag to resize; double-click to reset"></div>
    <section id="bottom-dock" class="pane-dock bottom-dock" aria-label="Bottom panes">
      <div id="bottom-tabs" class="pane-tabs" role="tablist"></div>
      <div id="bottom-body" class="pane-body"></div>
    </section>
  </section>
  <div id="detail-splitter" class="pane-splitter" title="Drag to resize; double-click to reset"></div>
  <aside id="right-dock" class="pane-dock right-dock" aria-label="Entry editing and other panes">
    <div id="right-tabs" class="pane-tabs" role="tablist"></div>
    <div id="right-body" class="pane-body"></div>
  </aside>
</main>
<div id="commit-bar" class="commit-bar" hidden></div>
${scripts}
</body>
</html>`;
}
