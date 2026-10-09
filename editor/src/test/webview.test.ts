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
import { findDuplicates, previewEdits, readLibrary } from "../library.js";
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
import { command, engineSkipReason, repoRoot } from "./engine.js";

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
          settings: { fuzzy: false, showFindings: true },
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

async function opened(fixture: string): Promise<{ view: View; host: Host }> {
  const view = openView();
  const host = new Host(view, path.join(fixtures, fixture));
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
