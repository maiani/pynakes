/**
 * The bibliography view, registered as a custom editor for `.bib` files.
 *
 * It is a `CustomTextEditorProvider` so VS Code keeps ownership of the document:
 * the text buffer stays the source of truth, external edits arrive as change
 * events, and nothing here caches file content.
 *
 * Staged edits live here rather than in the webview, because a webview is
 * disposed whenever its tab is hidden and pending changes must survive that.
 */

import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";
import { resolveEngine } from "./engineDiscovery";
import type { Summary } from "./model";
import {
  commitEdits,
  previewEdits,
  readLibrary,
  runSearch,
  type LibraryRead,
} from "./library";
import {
  PynakesProtocolError,
  PynakesUnavailableError,
  describeCommand,
  resolveCommand,
} from "./pynakes";
import {
  discardEntry,
  emptyStaging,
  findConflicts,
  isEmpty,
  stageField,
  stageType,
  stagedCount,
  toRequests,
  unstageField,
  type StagingConflict,
  type StagingState,
} from "./staging";
import { renderShell } from "./webview";

/** Coalesce bursts of keystrokes into a single engine read. */
const REFRESH_DEBOUNCE_MS = 250;

interface TempMirror {
  /** Path pynakes should read. */
  source: string;
  /** Removes the mirror, if one was created. */
  release(): Promise<void>;
}

/** What the status bar item reports about one open bibliography. */
interface StatusDetails {
  summary: Summary;
  findings?: { errors: number; warnings: number; info: number; total: number };
  engine: { version?: string; source: string; reason: string };
  dirty: boolean;
}

/** Messages the webview sends. */
interface ViewMessage {
  type?: string;
  key?: string;
  field?: string;
  value?: string | null;
  /** The value a staged change was made against; null when the field was absent. */
  base?: string | null;
  entryType?: string;
  query?: string;
  where?: string;
  fuzzy?: boolean;
}

export class BibliographyEditorProvider implements vscode.CustomTextEditorProvider {
  public static readonly viewType = "pynakes.bibliography";

  /** Refresh callbacks for every live view, driven by the refresh command. */
  private readonly liveViews = new Set<() => void>();

  /** Pending edits per document, surviving webview disposal. */
  private readonly staging = new Map<string, StagingState>();

  /**
   * File and engine details for each open view.
   *
   * They are shown in VS Code's status bar rather than inside the view: it is
   * ambient information, rarely read, and a permanent row of the editor is too
   * much space for it. One item is shared by every view and re-pointed at
   * whichever one is active.
   */
  private readonly statusByPanel = new WeakMap<vscode.WebviewPanel, StatusDetails>();

  private constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly statusItem: vscode.StatusBarItem,
  ) {}

  public static register(context: vscode.ExtensionContext): vscode.Disposable {
    const statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusItem.command = "pynakes.refreshBibliography";
    const provider = new BibliographyEditorProvider(context, statusItem);
    const registration = vscode.window.registerCustomEditorProvider(
      BibliographyEditorProvider.viewType,
      provider,
      {
        webviewOptions: { retainContextWhenHidden: false },
        supportsMultipleEditorsPerDocument: true,
      },
    );
    const refreshCommand = vscode.commands.registerCommand("pynakes.refreshBibliography", () => {
      if (provider.liveViews.size === 0) {
        void vscode.window.showInformationMessage("No Pynakes bibliography view is open.");
        return;
      }
      for (const refresh of provider.liveViews) {
        refresh();
      }
    });
    return vscode.Disposable.from(registration, refreshCommand, statusItem);
  }

  public async resolveCustomTextEditor(
    document: vscode.TextDocument,
    panel: vscode.WebviewPanel,
    _token: vscode.CancellationToken,
  ): Promise<void> {
    panel.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, "media")],
    };
    panel.webview.html = renderShell(panel.webview, this.context.extensionUri);

    let pending: NodeJS.Timeout | undefined;
    let disposed = false;
    const load = (): void => {
      if (!disposed) {
        void this.load(document, panel);
      }
    };
    const scheduleLoad = (): void => {
      if (pending) {
        clearTimeout(pending);
      }
      pending = setTimeout(load, REFRESH_DEBOUNCE_MS);
    };

    this.liveViews.add(load);
    const subscriptions: vscode.Disposable[] = [
      vscode.workspace.onDidChangeTextDocument((event) => {
        const sameDocument = event.document.uri.toString() === document.uri.toString();
        if (sameDocument && event.contentChanges.length > 0) {
          scheduleLoad();
        }
      }),
      // A save flips the buffer from dirty to clean, which changes whether the
      // view reads the file itself or a mirror of the buffer.
      vscode.workspace.onDidSaveTextDocument((saved) => {
        if (saved.uri.toString() === document.uri.toString()) {
          scheduleLoad();
        }
      }),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration("pynakes", document.uri)) {
          scheduleLoad();
        }
      }),
      panel.webview.onDidReceiveMessage((message: ViewMessage) => {
        void this.handleMessage(document, panel, message);
      }),
      // The item describes one bibliography, so it follows the active tab.
      panel.onDidChangeViewState(() => this.syncStatusBar(panel)),
    ];

    panel.onDidDispose(() => {
      disposed = true;
      this.statusByPanel.delete(panel);
      this.statusItem.hide();
      if (pending) {
        clearTimeout(pending);
      }
      this.liveViews.delete(load);
      for (const subscription of subscriptions) {
        subscription.dispose();
      }
    });
  }

  // -- reading --------------------------------------------------------------

  /** Read the document through the engine and hand the result to the view. */
  private async load(document: vscode.TextDocument, panel: vscode.WebviewPanel): Promise<void> {
    let mirror: TempMirror | undefined;
    try {
      const command = await resolveCommand(document.uri);
      const cwd = this.workingDirectory(document);
      mirror = await this.sourceFor(document);
      const result = await readLibrary(command, mirror.source, cwd);
      if (!result.ok) {
        void panel.webview.postMessage({
          type: "parseError",
          error: result.error.error,
          message: result.error.message,
          line: result.error.line,
        });
        return;
      }
      const engine = await resolveEngine(document.uri);
      this.statusByPanel.set(panel, {
        summary: result.read.summary,
        findings: result.read.lint?.counts,
        engine: {
          version: engine.version,
          source: engine.source,
          reason: engine.reason,
        },
        dirty: document.isDirty,
      });
      this.syncStatusBar(panel);
      void panel.webview.postMessage({
        type: "render",
        payload: this.toPayload(result.read),
        engine: {
          command: describeCommand(engine.command),
          version: engine.version,
          source: engine.source,
          reason: engine.reason,
        },
        dirty: document.isDirty,
        staging: this.stagingFor(document),
      });
    } catch (error) {
      void panel.webview.postMessage(await this.describeFailure(error, document));
    } finally {
      await mirror?.release();
    }
  }

  /** Point the shared status bar item at this view, or hide it. */
  private syncStatusBar(panel: vscode.WebviewPanel): void {
    const details = this.statusByPanel.get(panel);
    if (!panel.active || !details) {
      this.statusItem.hide();
      return;
    }
    const engine = details.engine;
    this.statusItem.text = engine.version
      ? `$(book) pynakes ${engine.version}`
      : "$(book) pynakes";
    this.statusItem.tooltip = this.buildTooltip(details);
    this.statusItem.show();
  }

  /** The detail that used to occupy a row of the view, now one hover away. */
  private buildTooltip(details: StatusDetails): vscode.MarkdownString {
    const { summary, findings, engine } = details;
    const lines: string[] = [`**${path.basename(summary.file)}**`, ""];

    const entries = `${summary.entryCount} ${summary.entryCount === 1 ? "entry" : "entries"}`;
    const types = summary.typeCounts
      .slice(0, 4)
      .map(([type, count]) => `${count} ${type}`)
      .join(", ");
    lines.push(types ? `${entries} — ${types}` : entries);

    if (findings && findings.total > 0) {
      lines.push(
        `${findings.total} findings — ${findings.errors} error, ` +
          `${findings.warnings} warning, ${findings.info} info`,
      );
    }
    if (summary.duplicateKeys.length > 0) {
      const names = summary.duplicateKeys.map(([key, count]) => `${key} (${count})`).join(", ");
      lines.push(`Duplicate keys: ${names}`);
    }
    if (summary.stringCount > 0) {
      lines.push(`${summary.stringCount} \`@string\` definitions`);
    }

    const namespaces = [
      summary.jabrefKeys.length > 0 ? "jabref-meta" : null,
      summary.pynakesKeys.length > 0 ? "pynakes-meta" : null,
    ].filter(Boolean);
    if (namespaces.length > 0) {
      lines.push(`Metadata: ${namespaces.join(", ")}`);
    }

    lines.push(`Encoding: ${summary.encoding}, ${summary.lineEnding.toUpperCase()} line endings`);
    if (details.dirty) {
      lines.push("_Reading the unsaved buffer, not the file on disk._");
    }
    lines.push("", `Engine: **${engine.source}**. ${engine.reason}`);
    lines.push("", "Click to re-read the file.");

    const tooltip = new vscode.MarkdownString(lines.join("\n\n"));
    tooltip.isTrusted = true;
    return tooltip;
  }

  /** Shape one read for the webview. */
  private toPayload(read: LibraryRead): Record<string, unknown> {
    return {
      rows: read.rows,
      summary: read.summary,
      groups: read.groups,
      groupsByEntry: read.groupsByEntry,
      lint: read.lint,
      warnings: read.warnings,
    };
  }

  /** Turn a thrown boundary error into something the view can explain. */
  private async describeFailure(
    error: unknown,
    document: vscode.TextDocument,
  ): Promise<Record<string, unknown>> {
    if (error instanceof PynakesUnavailableError) {
      return {
        type: "engineError",
        kind: "unavailable",
        message: `Could not run the pynakes engine as "${error.command}".`,
        detail:
          "No usable engine was found. The extension ships one, which needs a " +
          "Python 3.11+ interpreter on the system; if there is none, install the " +
          "engine with `pip install pynakes`. The `pynakes.executable` setting " +
          "overrides discovery entirely, and `pynakes.engine` can force the " +
          "bundled or the installed engine.",
      };
    }
    if (error instanceof PynakesProtocolError) {
      return { type: "engineError", kind: "protocol", message: error.message, detail: error.detail };
    }
    void document;
    return {
      type: "engineError",
      kind: "unknown",
      message: "Reading the bibliography failed.",
      detail: error instanceof Error ? (error.stack ?? error.message) : String(error),
    };
  }

  /**
   * Decide what pynakes should read.
   *
   * A saved local file is read in place. An unsaved buffer — or any document
   * that is not a local file — is mirrored to a temporary file first, so the
   * view always reflects the text on screen rather than the text on disk.
   */
  private async sourceFor(document: vscode.TextDocument): Promise<TempMirror> {
    if (document.uri.scheme === "file" && !document.isDirty) {
      return { source: document.uri.fsPath, release: async () => {} };
    }
    const directory = await fs.mkdtemp(path.join(os.tmpdir(), "pynakes-vscode-"));
    const basename = path.basename(document.uri.path) || "bibliography.bib";
    const source = path.join(directory, basename.endsWith(".bib") ? basename : `${basename}.bib`);
    await fs.writeFile(source, document.getText(), "utf8");
    return {
      source,
      release: async () => {
        await fs.rm(directory, { recursive: true, force: true });
      },
    };
  }

  /** Run the engine from the workspace folder so relative paths resolve. */
  private workingDirectory(document: vscode.TextDocument): string | undefined {
    const folder = vscode.workspace.getWorkspaceFolder(document.uri);
    if (folder?.uri.scheme === "file") {
      return folder.uri.fsPath;
    }
    if (document.uri.scheme === "file") {
      return path.dirname(document.uri.fsPath);
    }
    return undefined;
  }

  // -- staging --------------------------------------------------------------

  private stagingFor(document: vscode.TextDocument): StagingState {
    const id = document.uri.toString();
    let state = this.staging.get(id);
    if (!state) {
      state = emptyStaging();
      this.staging.set(id, state);
    }
    return state;
  }

  private postStaging(document: vscode.TextDocument, panel: vscode.WebviewPanel): void {
    void panel.webview.postMessage({
      type: "staging",
      staging: this.stagingFor(document),
      counts: stagedCount(this.stagingFor(document)),
    });
  }

  // -- messages -------------------------------------------------------------

  private async handleMessage(
    document: vscode.TextDocument,
    panel: vscode.WebviewPanel,
    message: ViewMessage,
  ): Promise<void> {
    switch (message.type) {
      case "ready":
        await this.load(document, panel);
        return;
      case "refresh":
        await this.load(document, panel);
        return;
      case "search":
        await this.search(document, panel, message);
        return;
      case "stageField":
        if (message.key && message.field) {
          stageField(
            this.stagingFor(document),
            message.key,
            message.field,
            message.value ?? null,
            message.base ?? null,
          );
          this.postStaging(document, panel);
        }
        return;
      case "unstageField":
        if (message.key && message.field) {
          unstageField(this.stagingFor(document), message.key, message.field);
          this.postStaging(document, panel);
        }
        return;
      case "stageType":
        if (message.key && message.value && typeof message.base === "string") {
          stageType(this.stagingFor(document), message.key, message.value, message.base);
          this.postStaging(document, panel);
        }
        return;
      case "discardEntry":
        if (message.key) {
          discardEntry(this.stagingFor(document), message.key);
          this.postStaging(document, panel);
        }
        return;
      case "discardAll":
        this.staging.set(document.uri.toString(), emptyStaging());
        this.postStaging(document, panel);
        return;
      case "preview":
        await this.preview(document, panel);
        return;
      case "commit":
        await this.commit(document, panel);
        return;
      case "reveal":
        if (message.key) {
          await this.revealEntry(document, message.key);
        }
        return;
      case "copyKey":
        if (message.key) {
          await vscode.env.clipboard.writeText(message.key);
          vscode.window.setStatusBarMessage(`Copied ${message.key}`, 2000);
        }
        return;
      case "openAsText":
        await vscode.commands.executeCommand("vscode.openWith", document.uri, "default", {
          viewColumn: vscode.ViewColumn.Beside,
        });
        return;
      case "openSettings":
        await vscode.commands.executeCommand("workbench.action.openSettings", "pynakes");
        return;
      default:
        return;
    }
  }

  // -- search ---------------------------------------------------------------

  private async search(
    document: vscode.TextDocument,
    panel: vscode.WebviewPanel,
    message: ViewMessage,
  ): Promise<void> {
    const query = message.query ?? "";
    const where = message.where ?? "";
    if (!query.trim() && !where.trim()) {
      void panel.webview.postMessage({ type: "searchCleared" });
      return;
    }
    let mirror: TempMirror | undefined;
    try {
      const command = await resolveCommand(document.uri);
      const cwd = this.workingDirectory(document);
      mirror = await this.sourceFor(document);
      const outcome = await runSearch(
        command,
        mirror.source,
        { query, where, fuzzy: message.fuzzy },
        cwd,
      );
      void panel.webview.postMessage(
        outcome.ok
          ? { type: "searchResult", keys: outcome.keys, ranked: outcome.ranked, count: outcome.count }
          : { type: "searchError", message: outcome.message },
      );
    } catch (error) {
      void panel.webview.postMessage(await this.describeFailure(error, document));
    } finally {
      await mirror?.release();
    }
  }

  // -- preview and commit ---------------------------------------------------

  /**
   * Dry-run the staged changes and show the exact diff.
   *
   * Previews run against the buffer, mirror included, so an unsaved document can
   * still be inspected. Committing is stricter — see `commit`.
   */
  private async preview(
    document: vscode.TextDocument,
    panel: vscode.WebviewPanel,
  ): Promise<void> {
    const state = this.stagingFor(document);
    if (isEmpty(state)) {
      void panel.webview.postMessage({ type: "diff", entries: [] });
      return;
    }
    let mirror: TempMirror | undefined;
    try {
      const command = await resolveCommand(document.uri);
      const cwd = this.workingDirectory(document);
      mirror = await this.sourceFor(document);
      const result = await previewEdits(command, mirror.source, toRequests(state), cwd);
      if (!result.ok) {
        void panel.webview.postMessage({
          type: "commitError",
          message: `Previewing ${result.key} failed: ${result.message}`,
        });
        return;
      }
      void panel.webview.postMessage({
        type: "diff",
        entries: result.entries.map((entry) => ({
          key: entry.key,
          diff: entry.diff,
          warnings: entry.warnings,
        })),
      });
    } catch (error) {
      void panel.webview.postMessage(await this.describeFailure(error, document));
    } finally {
      await mirror?.release();
    }
  }

  /**
   * Apply the staged changes, after a diff and an explicit approval.
   *
   * The order matters. The buffer is reconciled with disk first, because the
   * engine writes to the file and a dirty buffer would either be overwritten or
   * would overwrite the commit. Then a dry run produces the diff *and* the
   * current values, which are checked against what each edit was staged
   * against — that is what stops a commit from silently reverting a change
   * someone else made in between. Only then is approval requested.
   */
  private async commit(document: vscode.TextDocument, panel: vscode.WebviewPanel): Promise<void> {
    const state = this.stagingFor(document);
    if (isEmpty(state)) {
      return;
    }
    if (document.uri.scheme !== "file") {
      void panel.webview.postMessage({
        type: "commitError",
        message: "This document is not a local file, so it cannot be written.",
      });
      return;
    }
    if (!(await this.reconcileBuffer(document))) {
      void panel.webview.postMessage({
        type: "commitError",
        message: "Apply cancelled: the file still has unsaved changes.",
      });
      return;
    }

    const requests = toRequests(state);
    try {
      const command = await resolveCommand(document.uri);
      const cwd = this.workingDirectory(document);
      const filePath = document.uri.fsPath;

      const preview = await previewEdits(command, filePath, requests, cwd);
      if (!preview.ok) {
        void panel.webview.postMessage({
          type: "commitError",
          message: `Cannot apply: ${preview.key} — ${preview.message}`,
        });
        return;
      }

      const conflicts: StagingConflict[] = [];
      for (const entry of preview.entries) {
        const staged = state.entries[entry.key];
        if (staged) {
          conflicts.push(...findConflicts(staged, entry.plan));
        }
      }
      if (conflicts.length > 0) {
        void panel.webview.postMessage({
          type: "conflict",
          conflicts,
          message:
            "The file changed since these edits were made. Nothing was written — " +
            "review the current values and edit again.",
        });
        await this.load(document, panel);
        return;
      }

      // Put the diff on screen before asking, so approval is informed.
      void panel.webview.postMessage({
        type: "diff",
        entries: preview.entries.map((entry) => ({
          key: entry.key,
          diff: entry.diff,
          warnings: entry.warnings,
        })),
      });

      const counts = stagedCount(state);
      const name = path.basename(filePath);
      const approval = await vscode.window.showWarningMessage(
        `Apply ${counts.fields} ${counts.fields === 1 ? "change" : "changes"} to ` +
          `${counts.entries} ${counts.entries === 1 ? "entry" : "entries"} in ${name}?`,
        { modal: true, detail: "The exact diff is shown in the bibliography view." },
        "Apply",
      );
      if (approval !== "Apply") {
        void panel.webview.postMessage({ type: "commitCancelled" });
        return;
      }

      const result = await commitEdits(command, filePath, requests, cwd);
      if (result.failure) {
        void panel.webview.postMessage({
          type: "commitError",
          message:
            `Wrote ${result.applied.length} of ${requests.length} entries, then ` +
            `${result.failure.key} failed: ${result.failure.message}`,
        });
        // Keep only what was not applied, so a retry does not redo written work.
        for (const key of result.applied) {
          discardEntry(state, key);
        }
      } else {
        this.staging.set(document.uri.toString(), emptyStaging());
        void panel.webview.postMessage({
          type: "committed",
          applied: result.applied,
          warnings: result.warnings,
        });
      }
      this.postStaging(document, panel);
      await this.load(document, panel);
    } catch (error) {
      void panel.webview.postMessage(await this.describeFailure(error, document));
    }
  }

  /**
   * Bring the buffer and the file on disk into agreement before writing.
   *
   * The editor's own `files.autoSave` decides how: when autosave is on the
   * buffer is saved without asking, because that is what the editor would do
   * moments later anyway. With autosave off, saving is the user's decision, so
   * it is asked for rather than assumed.
   */
  private async reconcileBuffer(document: vscode.TextDocument): Promise<boolean> {
    if (!document.isDirty) {
      return true;
    }
    const autoSave = vscode.workspace
      .getConfiguration("files", document.uri)
      .get<string>("autoSave", "off");
    if (autoSave !== "off") {
      return document.save();
    }
    const name = path.basename(document.uri.fsPath);
    const choice = await vscode.window.showWarningMessage(
      `${name} has unsaved changes.`,
      {
        modal: true,
        detail:
          "Applying writes to the file, so the buffer has to be saved first. " +
          "Save it now and continue?",
      },
      "Save and Apply",
    );
    if (choice !== "Save and Apply") {
      return false;
    }
    return document.save();
  }

  // -- navigation -----------------------------------------------------------

  /** Open the source text beside the view, at the entry's declaration. */
  private async revealEntry(document: vscode.TextDocument, key: string): Promise<void> {
    const pattern = new RegExp(`@[A-Za-z]+\\s*[{(]\\s*${escapeRegExp(key)}\\s*,`);
    const match = pattern.exec(document.getText());
    const position = match ? document.positionAt(match.index) : new vscode.Position(0, 0);
    const range = new vscode.Range(position, position);
    const editor = await vscode.window.showTextDocument(document, {
      viewColumn: vscode.ViewColumn.Beside,
      preview: false,
      selection: range,
    });
    editor.revealRange(range, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
    if (!match) {
      void vscode.window.showWarningMessage(`Could not locate "${key}" in the source text.`);
    }
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
