/**
 * Smoke tests for the webview: the real shell and the real `media/` scripts,
 * driven by an emulated host over the real engine.
 *
 * The client scripts are plain JavaScript that neither `tsc` nor the other
 * tests ever load, so a view that threw on its very first render — every pane
 * tab was marked active after appending its fragment, when the fragment was
 * already empty — passed the whole suite and shipped. These tests load the
 * view in jsdom, answer its messages the way `bibliographyEditor.ts` does (the
 * same `library` and `staging` functions, the same engine), click through what
 * a user would, and fail on any error the view raises.
 *
 * jsdom has no layout, so this proves the view runs, not that it looks right.
 */

import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { test } from "node:test";
import { JSDOM, VirtualConsole } from "jsdom";
import {
  findDuplicates,
  previewEdits,
  previewMutation,
  readLibrary,
  type Mutation,
} from "../library.js";
import {
  diffHeading,
  discardEntry,
  emptyStaging,
  stagedCount,
  stageField,
  stageType,
  toRequests,
  unstageField,
} from "../staging.js";
import { command, engineSkipReason, previewThenApply, repoRoot, tempBib } from "./engine.js";

const skip = engineSkipReason();

const editorRoot = path.join(repoRoot, "editor");
const fixtures = path.join(repoRoot, "tests", "fixtures");

// `webview.ts` builds resource URIs through `vscode.Uri.joinPath`; the test
// stub for `vscode` is empty, so give it just that before the shell is built.
(require("vscode") as Record<string, unknown>).Uri = {
  joinPath: (base: { fsPath: string }, ...parts: string[]) => ({
    fsPath: path.join(base.fsPath, ...parts),
  }),
};
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { renderShell } = require("../webview.js") as typeof import("../webview.js");

type Message = Record<string, unknown> & { type: string };

/** One open view: its window, what it raised, and what it asked the host. */
interface View {
  window: JSDOM["window"];
  document: Document;
  errors: string[];
  outbox: Message[];
  post(message: Message): void;
}

function openView(): View {
  const errors: string[] = [];
  const outbox: Message[] = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (error) => errors.push(error.stack ?? error.message));
  virtualConsole.on("error", (...args: unknown[]) => errors.push(args.map(String).join(" ")));

  const html = renderShell(
    {
      cspSource: "test:",
      asWebviewUri: (uri: { fsPath: string }) => `test:${path.relative(editorRoot, uri.fsPath)}`,
    } as never,
    { fsPath: editorRoot } as never,
  );
  // Scripts are not fetched: each is evaluated in the shell's order, as the
  // webview would load them.
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, virtualConsole });
  const { window } = dom;
  let state: unknown;
  Object.assign(window, {
    acquireVsCodeApi: () => ({
      postMessage: (message: Message) => outbox.push(message),
      getState: () => state,
      setState: (next: unknown) => {
        state = next;
      },
    }),
  });
  for (const match of html.matchAll(/<script nonce="[^"]+" src="test:([^"]+)"><\/script>/g)) {
    window.eval(fs.readFileSync(path.join(editorRoot, match[1]), "utf-8"));
  }
  return {
    window,
    document: window.document,
    errors,
    outbox,
    post: (message) => window.dispatchEvent(new window.MessageEvent("message", { data: message })),
  };
}

/**
 * The host side of the view, for the messages a smoke test needs answered.
 *
 * Mirrors `BibliographyEditorProvider.handleMessage`: the same staging
 * bookkeeping and the same engine reads. Anything else the view asks for —
 * revealing a line, prompting for a key — needs VS Code itself and is ignored.
 */
class Host {
  private staging = emptyStaging();

  /** The view settings each render carries; a test may change them. */
  settings: Record<string, unknown> = { fuzzy: false, showFindings: true };

  constructor(
    private readonly view: View,
    private readonly file: string,
  ) {}

  /** Answer everything the view has asked, including what the answers prompt. */
  async drain(): Promise<void> {
    for (let message = this.view.outbox.shift(); message; message = this.view.outbox.shift()) {
      await this.handle(message);
    }
  }

  private async handle(message: Message): Promise<void> {
    const m = message as Message & Record<string, string>;
    switch (m.type) {
      case "ready":
      case "refresh": {
        const result = await readLibrary(command, this.file, undefined, this.file);
        assert.ok(result.ok, `the fixture should read: ${JSON.stringify(result)}`);
        const read = result.read;
        this.view.post({
          type: "render",
          payload: {
            rows: read.rows,
            summary: read.summary,
            groups: read.groups,
            groupsByEntry: read.groupsByEntry,
            lint: read.lint,
            citations: read.citations,
            materials: read.materials,
            warnings: read.warnings,
          },
          engine: { command: "python3 -m pynakes", version: "test", source: "setting", reason: "" },
          dirty: false,
          staging: this.staging,
          settings: this.settings,
        });
        return;
      }
      case "stageField":
        stageField(this.staging, m.key, m.field, m.value ?? null, m.base ?? null);
        return this.postStaging();
      case "unstageField":
        unstageField(this.staging, m.key, m.field);
        return this.postStaging();
      case "stageType":
        stageType(this.staging, m.key, m.value, m.base);
        return this.postStaging();
      case "discardEntry":
        discardEntry(this.staging, m.key);
        return this.postStaging();
      case "discardAll":
        this.staging = emptyStaging();
        return this.postStaging();
      case "preview": {
        const requests = toRequests(this.staging);
        const result = await previewEdits(command, this.file, requests);
        assert.ok(result.ok, `the staged edit should preview: ${JSON.stringify(result)}`);
        this.view.post({
          type: "diff",
          entries: [
            {
              key: diffHeading(requests.map((request) => request.key)),
              diff: result.diff,
              warnings: result.warnings,
            },
          ],
        });
        return;
      }
      case "findDuplicates": {
        const outcome = await findDuplicates(command, this.file);
        this.view.post(
          outcome.ok
            ? { type: "duplicates", clusters: outcome.clusters }
            : { type: "duplicatesError", message: outcome.message },
        );
        return;
      }
      default:
        return;
    }
  }

  private postStaging(): void {
    this.view.post({
      type: "staging",
      staging: this.staging,
      counts: stagedCount(this.staging),
    });
  }
}

/** Fail on anything the view raised, and on a dock showing other than one active tab. */
function assertHealthy(view: View, step: string): void {
  assert.deepEqual(view.errors, [], `the view raised errors ${step}`);
  for (const dock of ["right", "bottom"]) {
    const tabs = view.document.querySelectorAll(`#${dock}-tabs .tab`);
    if (tabs.length > 0) {
      const active = view.document.querySelectorAll(`#${dock}-tabs .tab.active`);
      assert.equal(active.length, 1, `the ${dock} dock should have one active tab ${step}`);
    }
  }
}

function click(view: View, selector: string): number {
  // Re-query after each click: a click can re-render the very list it came from.
  const count = view.document.querySelectorAll(selector).length;
  for (let index = 0; index < count; index += 1) {
    const element = view.document.querySelectorAll<HTMLElement>(selector)[index];
    element?.click();
  }
  return count;
}

async function opened(fixture: string, file?: string): Promise<{ view: View; host: Host }> {
  const view = openView();
  const host = new Host(view, file ?? path.join(fixtures, fixture));
  await host.drain();
  assertHealthy(view, "on first render");
  return { view, host };
}

for (const fixture of [
  "biblatex_sample.bib",
  "duplicate_entries.bib",
  "jabref_groups.bib",
  "linked_files.bib",
]) {
  test(`${fixture}: the view renders and survives clicking through it`, { skip }, async () => {
    const { view, host } = await opened(fixture);

    assert.ok(view.document.querySelectorAll("#rows tr").length > 0, "rows should render");
    assert.equal(view.document.getElementById("right-dock")?.hidden, false, "panes should show");

    click(view, "#rows tr");
    assertHealthy(view, "selecting rows");
    click(view, ".tab");
    click(view, ".tab");
    assertHealthy(view, "switching panes");
    assert.ok(click(view, ".pane-move") > 0, "panes should be movable");
    click(view, ".pane-move");
    assertHealthy(view, "moving panes between docks");
    click(view, ".group-row");
    click(view, "th[data-col]");
    click(view, "#uncited");
    click(view, "#uncited");
    assertHealthy(view, "filtering and sorting");

    view.document.getElementById("find-duplicates")?.click();
    await host.drain();
    assertHealthy(view, "after finding duplicates");
  });
}

test("a field edit stages, previews as a diff, and discards", { skip }, async () => {
  const { view, host } = await opened("simple.bib");
  click(view, '.tab[data-pane="edit"]');

  const input = view.document.querySelector<HTMLInputElement>(
    '.field-value[id$="year"], .field-value',
  );
  assert.ok(input, "the edit pane should offer a field input");
  input.value = "1905";
  input.dispatchEvent(new view.window.Event("blur"));
  await host.drain();
  assertHealthy(view, "after staging an edit");
  assert.ok(view.document.querySelector(".field-row.staged"), "the edit should show as staged");
  assert.equal(view.document.getElementById("commit-bar")?.hidden, false);

  const buttons = [...view.document.querySelectorAll<HTMLButtonElement>("#commit-bar button")];
  buttons.find((button) => button.textContent === "Preview")?.click();
  await host.drain();
  assertHealthy(view, "after previewing");
  assert.match(view.document.body.textContent ?? "", /1905/, "the diff should show the edit");

  [...view.document.querySelectorAll<HTMLButtonElement>("#commit-bar button")]
    .find((button) => button.textContent === "Discard all")
    ?.click();
  await host.drain();
  assertHealthy(view, "after discarding");
  assert.equal(view.document.querySelector(".field-row.staged"), null);
});

test("an engine failure and a parse failure show a banner, not an error", { skip }, async () => {
  const { view } = await opened("simple.bib");
  view.post({ type: "engineError", kind: "unavailable", message: "No engine", detail: "detail" });
  assertHealthy(view, "on an engine error");
  assert.equal(view.document.getElementById("banner")?.hidden, false);

  view.post({ type: "parseError", error: "ParseError", message: "Unbalanced braces", line: 3 });
  assertHealthy(view, "on a parse error");
  assert.match(view.document.getElementById("banner")?.textContent ?? "", /line 3/);
});

/** What the view asked the host since the last drain, without answering it. */
function asked(view: View, type: string): Message[] {
  return view.outbox.filter((message) => message.type === type);
}

function groupRow(view: View, name: string): HTMLElement | null {
  return [...view.document.querySelectorAll<HTMLElement>(".group-row")].find(
    (row) => row.dataset.group === name,
  ) ?? null;
}

test("the groups sidebar hands hierarchy edits to the extension", { skip }, async () => {
  const { view } = await opened("jabref_groups.bib");

  view.document.querySelector<HTMLButtonElement>("button.group-new")?.click();
  assert.equal(asked(view, "promptNewGroup").length, 1, '"+" should ask for a new group');

  const actions = view.document.querySelector<HTMLButtonElement>(
    'button.group-actions[data-action-group="All Papers"]',
  );
  assert.ok(actions, "every group should carry an actions button");
  assert.equal(actions.tabIndex, 0, "the actions button must be reachable by keyboard");
  actions.click();
  const [request] = asked(view, "groupActions");
  assert.deepEqual((request.group as Record<string, unknown>).name, "All Papers");
  assert.equal((request.group as Record<string, unknown>).undeclared, false);
  const candidates = request.groups as string[];
  assert.ok(candidates.includes("Machine Learning:AI Papers"));
  // Entries name "AI Papers" but the hierarchy does not declare it, so it is no move target.
  assert.ok(!candidates.includes("AI Papers"));
  assert.ok(!groupRow(view, "All Papers")?.classList.contains("selected"), "not a filter click");

  groupRow(view, "AI Papers")?.dispatchEvent(
    new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }),
  );
  const undeclared = asked(view, "groupActions")[1];
  assert.equal((undeclared.group as Record<string, unknown>).name, "AI Papers");
  assert.equal((undeclared.group as Record<string, unknown>).undeclared, true);
  assertHealthy(view, "after asking for group actions");
});

test("a renamed group stays the filter, and a removed one stops being it", { skip }, async () => {
  const file = tempBib(
    fs.readFileSync(path.join(fixtures, "jabref_groups.bib"), "utf-8"),
    "groups.bib",
  );
  const { view, host } = await opened("jabref_groups.bib", file);

  groupRow(view, "Blockchain:Cryptocurrency")?.click();
  assert.ok(groupRow(view, "Blockchain:Cryptocurrency")?.classList.contains("selected"));

  // The write itself is the extension's, exactly as `runMutation` performs it.
  const write = (mutation: Mutation) => previewThenApply(file, mutation);

  // File one entry under the group, so the rename has a member to carry along.
  await write({ kind: "group", key: "Brown2021", group: "Blockchain:Cryptocurrency", member: true });
  const rename: Mutation = {
    kind: "groupTree",
    edit: { op: "rename", name: "Blockchain:Cryptocurrency", newName: "Ledgers" },
  };
  const preview = await previewMutation(command, file, rename);
  assert.ok(preview.ok && preview.renamedMembers, JSON.stringify(preview));
  assert.deepEqual(preview.renamedMembers, ["Brown2021"]);
  await write(rename);
  view.post({
    type: "mutationDone",
    label: "Rename",
    warnings: [],
    renamedGroup: { from: "Blockchain:Cryptocurrency", to: "Ledgers" },
  });
  view.outbox.push({ type: "refresh" });
  await host.drain();
  assertHealthy(view, "after a rename");
  assert.ok(groupRow(view, "Ledgers")?.classList.contains("selected"), "the filter follows");
  const shown = [...view.document.querySelectorAll<HTMLElement>("#rows tr")].map(
    (row) => row.dataset.key,
  );
  assert.deepEqual(shown, ["Brown2021"], "and so does the member");

  // A removal keeps memberships, so the member leaves first: otherwise the
  // group would stay on as one the hierarchy does not declare.
  await write({ kind: "group", key: "Brown2021", group: "Ledgers", member: false });
  await write({ kind: "groupTree", edit: { op: "remove", name: "Ledgers" } });
  view.post({ type: "mutationDone", label: "Remove", warnings: [] });
  view.outbox.push({ type: "refresh" });
  await host.drain();
  assertHealthy(view, "after a removal");
  assert.equal(groupRow(view, "Ledgers"), null);
  assert.ok(groupRow(view, "")?.classList.contains("selected"), "back to all entries");
});

test("fetching materials is handed to the extension, one fetch at a time", { skip }, async () => {
  const { view } = await opened("simple.bib");
  click(view, '.tab[data-pane="edit"]');
  const selected = view.document.querySelector<HTMLElement>("#rows tr.selected, #rows tr");
  selected?.click();

  const entryFetch = view.document.querySelector<HTMLButtonElement>("button.material-fetch");
  assert.ok(entryFetch, "the detail pane should offer fetching the entry's materials");
  assert.equal(entryFetch.textContent, "Fetch missing…");
  entryFetch.click();
  const [request] = asked(view, "fetchMaterials");
  assert.ok(typeof request.key === "string" && request.key, "a per-entry fetch names its key");
  assertHealthy(view, "after asking to fetch");

  // While it runs, neither the entry's button nor the toolbar's starts another.
  const busy = view.document.querySelector<HTMLButtonElement>("button.material-fetch");
  assert.equal(busy?.textContent, "Fetching…");
  assert.equal(busy?.disabled, true);
  const toolbar = view.document.getElementById("fetch-materials") as HTMLButtonElement;
  assert.equal(toolbar.disabled, true);

  view.post({ type: "fetchState", key: request.key, busy: false });
  view.post({ type: "fetchDone", level: "success", message: "Fetched 1 file." });
  assertHealthy(view, "after the fetch ended");
  assert.equal(view.document.querySelector<HTMLButtonElement>("button.material-fetch")?.disabled, false);
  assert.equal(toolbar.disabled, false);
  assert.match(view.document.getElementById("notice")?.textContent ?? "", /Fetched 1 file/);

  toolbar.click();
  const all = asked(view, "fetchMaterials")[1];
  assert.equal(all.key, undefined, "the toolbar fetches for every entry");
  assert.equal(view.document.querySelector<HTMLButtonElement>("button.material-fetch")?.disabled, true);
  view.post({ type: "fetchState", key: null, busy: false });
  view.post({ type: "mutationError", label: "Fetch missing materials", message: "Online lookups are disabled." });
  assertHealthy(view, "after a refused fetch");
  assert.equal(toolbar.disabled, false);
});

test("a material opens where the setting says, or the other way on request", { skip }, async () => {
  const file = tempBib(
    "@book{Newton1687,\n  author = {Isaac Newton},\n  title = {Principia},\n" +
      "  year = {1687},\n  file = {:Newton1687.pdf:PDF}\n}\n",
    "materials.bib",
  );
  const pdf = path.join(path.dirname(file), "Newton1687.pdf");
  fs.writeFileSync(pdf, "%PDF-1.4\n");
  const { view, host } = await opened("", file);
  click(view, '.tab[data-pane="edit"]');
  view.document.querySelector<HTMLElement>("#rows tr")?.click();

  const material = () => view.document.querySelector<HTMLButtonElement>(".material .link-button");
  const alternate = () => view.document.querySelector<HTMLButtonElement>(".material .material-alt");
  assert.ok(material(), "the linked PDF should be listed");
  assert.equal(alternate()?.textContent, "Open externally", "the default is VS Code");
  assert.equal(alternate()?.tagName, "BUTTON", "a button, so Tab reaches it and Enter activates it");
  assert.equal(alternate()?.disabled, false);
  assert.match(material()?.title ?? "", /^Open in VS Code: .*Alt\+click: Open externally/);

  material()?.click();
  alternate()?.click();
  material()?.dispatchEvent(new view.window.MouseEvent("click", { bubbles: true, altKey: true }));
  assert.deepEqual(
    asked(view, "openMaterial").map((message) => [message.path, message.opener]),
    [
      [pdf, "editor"],
      [pdf, "system"],
      [pdf, "system"],
    ],
  );
  assertHealthy(view, "after opening a material");

  // Keyboard: Tab reaches the alternative, and Enter on it is its own click,
  // not the table's "open the selected entry's source".
  alternate()?.focus();
  assert.equal(view.document.activeElement, alternate());
  alternate()?.dispatchEvent(new view.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  assert.deepEqual(asked(view, "reveal"), [], "Enter on a material button is not a reveal");

  // With the setting flipped, the plain click and the alternative swap.
  view.outbox.length = 0;
  host.settings = { ...host.settings, openMaterialsWith: "system" };
  view.outbox.push({ type: "refresh" });
  await host.drain();
  assert.equal(alternate()?.textContent, "Open in Code");
  material()?.click();
  alternate()?.click();
  assert.deepEqual(
    asked(view, "openMaterial").map((message) => message.opener),
    ["system", "editor"],
  );
  assertHealthy(view, "after the setting changed");
});

test("citation keys named like Object.prototype members render as entries", { skip }, async () => {
  const file = tempBib(
    "@misc{constructor,\n  title = {On Machines},\n  groups = {Mechanics}\n}\n\n" +
      "@article{toString,\n  title = {On Strings}\n}\n\n" +
      "@misc{Euler1748,\n  title = {Introductio}\n}\n",
    "proto.bib",
  );
  const { view } = await opened("proto.bib", file);

  const keys = [...view.document.querySelectorAll<HTMLElement>("#rows tr")].map(
    (row) => row.dataset.key,
  );
  assert.deepEqual(keys, ["constructor", "toString", "Euler1748"]);
  click(view, '.tab[data-pane="edit"]');
  click(view, "#rows tr");
  assertHealthy(view, "selecting each entry");
  // An entry with no pending change is not shown as having one.
  assert.equal(view.document.querySelectorAll("#rows .staged-dot").length, 0);
});

test("a late answer to an older search does not replace the newer one", { skip }, async () => {
  const { view } = await opened("simple.bib");
  const query = view.document.getElementById("query") as HTMLInputElement;

  query.value = "first";
  query.dispatchEvent(new view.window.Event("input"));
  query.value = "second";
  query.dispatchEvent(new view.window.Event("input"));
  await new Promise((resolve) => setTimeout(resolve, 400));
  const [sent] = asked(view, "search");
  assert.equal(sent.query, "second", "only the settled query is sent");
  const all = [...view.document.querySelectorAll<HTMLElement>("#rows tr")].map((row) => row.dataset.key);

  view.post({ type: "searchResult", seq: (sent.seq as number) - 1, keys: [], ranked: false, count: 0 });
  assert.equal(view.document.querySelectorAll("#rows tr").length, all.length, "a stale answer is dropped");

  view.post({ type: "searchResult", seq: sent.seq, keys: [all[0]], ranked: false, count: 1 });
  assert.equal(view.document.querySelectorAll("#rows tr").length, 1, "the current answer is shown");
  assertHealthy(view, "after out-of-order search answers");
});

test("a failed action reports itself without blanking the table", { skip }, async () => {
  const { view } = await opened("simple.bib");
  const rows = view.document.querySelectorAll("#rows tr").length;
  click(view, '.tab[data-pane="edit"]');
  const key = view.document.querySelector<HTMLInputElement>("input.detail-key");
  assert.ok(key, "the edit pane shows the citation key");
  key.value = "Renamed1905";
  key.dispatchEvent(new view.window.Event("blur"));
  assert.equal(view.document.querySelector<HTMLInputElement>("input.detail-key")?.disabled, true);

  view.post({ type: "actionError", kind: "protocol", message: "keys rename broke", detail: "" });

  assertHealthy(view, "after a failed action");
  assert.equal(view.document.querySelectorAll("#rows tr").length, rows, "the table stays");
  assert.match(view.document.getElementById("banner")?.textContent ?? "", /keys rename broke/);
  assert.equal(
    view.document.querySelector<HTMLInputElement>("input.detail-key")?.disabled,
    false,
    "the key field is usable again",
  );
});

test("a JabRef group colour paints its swatch", { skip }, async () => {
  const file = tempBib(
    "@comment{jabref-meta: databaseType:bibtex;}\n\n" +
      "@comment{jabref-meta: grouping:\n0 AllEntriesGroup:;\n" +
      "1 StaticGroup:Optics\;0\;1\;0x8a8a8aff\;\;\;;\n}\n\n" +
      "@book{Newton1704,\n  title = {Opticks},\n  groups = {Optics}\n}\n",
    "colours.bib",
  );
  const { view } = await opened("colours.bib", file);

  const swatch = groupRow(view, "Optics")?.querySelector<HTMLElement>(".group-color");
  assert.ok(swatch, "a coloured group shows a swatch");
  assert.notEqual(swatch.style.backgroundColor, "", "and the swatch is painted");
});

// --- keyboard access ---------------------------------------------------------

function press(view: View, target: Element, key: string, init: KeyboardEventInit = {}): void {
  target.dispatchEvent(
    new view.window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }),
  );
}

test("group rows are focusable toggles that Enter and Space operate", { skip }, async () => {
  const { view } = await opened("jabref_groups.bib");

  const row = groupRow(view, "All Papers");
  assert.ok(row, "the group should render");
  assert.equal(row.tabIndex, 0, "a group row must be reachable by Tab");
  assert.equal(row.getAttribute("role"), "button");
  assert.equal(row.getAttribute("aria-pressed"), "false");
  assert.equal(groupRow(view, "")?.tabIndex, 0, '"All entries" is reachable too');

  row.focus();
  press(view, row, "Enter");
  const selected = groupRow(view, "All Papers");
  assert.ok(selected?.classList.contains("selected"), "Enter filters by the group");
  assert.equal(selected?.getAttribute("aria-pressed"), "true");
  assert.equal(view.document.activeElement, selected, "focus survives the re-render");
  assert.equal(asked(view, "reveal").length, 0, "Enter on a group is not the table's Enter");

  press(view, selected, " ");
  assert.equal(
    groupRow(view, "All Papers")?.classList.contains("selected"),
    false,
    "Space on the filtering group clears the filter",
  );

  const again = groupRow(view, "All Papers");
  assert.ok(again);
  press(view, again, "F10", { shiftKey: true });
  const [request] = asked(view, "groupActions");
  assert.equal((request?.group as Record<string, unknown>)?.name, "All Papers");

  // Keys pressed on the row's own buttons are theirs, not the row's.
  const twisty = groupRow(view, "All Papers")?.querySelector<HTMLElement>("button.twisty");
  if (twisty) {
    press(view, twisty, "Enter");
    assert.equal(groupRow(view, "All Papers")?.classList.contains("selected"), false);
  }
  assertHealthy(view, "after operating groups by keyboard");
});

test("duplicate-cluster keys are buttons that select their entry", { skip }, async () => {
  const file = tempBib(
    "@article{Lovelace1843,\n  author = {Ada Lovelace},\n  title = {Notes on the Engine},\n" +
      "  year = {1843},\n  doi = {10.5555/engine}\n}\n" +
      "@article{Lovelace1843b,\n  author = {Ada Lovelace},\n  title = {Notes on the Engine},\n" +
      "  year = {1843},\n  doi = {10.5555/engine}\n}\n",
  );
  const { view, host } = await opened("refs.bib", file);
  view.document.getElementById("find-duplicates")?.click();
  await host.drain();

  const keys = [...view.document.querySelectorAll<HTMLElement>(".dup-key")];
  assert.deepEqual(
    keys.map((key) => key.textContent),
    ["Lovelace1843", "Lovelace1843b"],
  );
  for (const key of keys) {
    assert.equal(key.tagName, "BUTTON", "a cluster key must be a real, focusable button");
    assert.equal((key as HTMLButtonElement).type, "button");
    assert.ok(key.classList.contains("link-button"), "styled, and focus-ringed, like other links");
  }
  keys[1].focus();
  assert.equal(view.document.activeElement, keys[1]);
  press(view, keys[1], "Enter");
  assert.equal(asked(view, "reveal").length, 0, "Enter on a button is its click, not a reveal");
  keys[1].click();
  assert.equal(
    view.document.querySelector<HTMLElement>("#rows tr.selected")?.dataset.key,
    "Lovelace1843b",
    "activating the key selects its entry",
  );
  assertHealthy(view, "after selecting from a cluster");
});

test("a key rename holds the key field until its mutation ends, however it ends", { skip }, async () => {
  const { view } = await opened("simple.bib");
  click(view, '.tab[data-pane="edit"]');
  const field = () => view.document.querySelector<HTMLInputElement>("input.detail-key");
  const original = field()?.value ?? "";
  assert.ok(original, "the edit pane shows the citation key");

  for (const ending of [
    { type: "mutationError", label: `Rename ${original}`, message: "Nothing was written: taken" },
    { type: "mutationCancelled", label: `Rename ${original}` },
    { type: "mutationNoop", label: `Rename ${original}`, message: "nothing to change" },
  ]) {
    const input = field();
    assert.ok(input);
    input.value = "Renamed1905";
    input.dispatchEvent(new view.window.Event("blur"));
    const [request] = view.outbox.splice(0).filter((message) => message.type === "renameKey");
    assert.deepEqual([request?.key, request?.newKey], [original, "Renamed1905"]);
    assert.equal(field()?.disabled, true, "the field waits while the rename is reviewed");

    view.post(ending);
    assert.equal(field()?.disabled, false, `released by ${ending.type}`);
    assert.equal(field()?.value, original, `and showing the key as it is, after ${ending.type}`);
  }
  assertHealthy(view, "after renames that wrote nothing");
});
