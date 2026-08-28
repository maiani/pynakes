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
import { resolveEngine, type ResolvedEngine } from "./engineDiscovery";
import {
  citationDiagnostics,
  lintDiagnostics,
  type CitationIndex,
  type LintIndex,
  type MaterialIndex,
} from "./insights";
import type { LintSeverity, Summary } from "./model";
import {
  commitEdits,
  compareEntry,
  previewEdits,
  readLibrary,
  renameEntryKey,
  runSearch,
  type LibraryRead,
} from "./library";
import {
  type PynakesCommand,
  PynakesProtocolError,
  PynakesUnavailableError,
  describeCommand,
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

/** Engine finding severities onto VS Code's diagnostic scale. */
const DIAGNOSTIC_SEVERITY: Record<LintSeverity, vscode.DiagnosticSeverity> = {
  error: vscode.DiagnosticSeverity.Error,
  warning: vscode.DiagnosticSeverity.Warning,
  info: vscode.DiagnosticSeverity.Information,
};

interface TempMirror {
  /** Path pynakes should read. */
  source: string;
  /** Removes the mirror, if one was created. */
  release(): Promise<void>;
}

/** Settings the view honors, re-read on every render so changes apply live. */
interface ViewSettings {
  /** Initial state of the search box's fuzzy toggle. */
  fuzzy: boolean;
  /** Whether per-row severity markers and the findings panel are shown. */
  showFindings: boolean;
}

/** Everything an engine read needs besides the webview it reports to. */
interface MirrorContext {
  engine: ResolvedEngine;
  command: PynakesCommand;
  cwd: string | undefined;
  source: string;
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
  /** The requested new citation key, for `renameKey`. */
  newKey?: string;
  query?: string;
  where?: string;
  fuzzy?: boolean;
  /** Absolute path, for `openMaterial` and `openCitation`. */
  path?: string;
  /** One-based position within that file, for `openCitation`. */
  line?: number;
  column?: number;
}

export class BibliographyEditorProvider implements vscode.CustomTextEditorProvider {
  public static readonly viewType = "pynakes.bibliography";

  /** Refresh callbacks for every live view, driven by the refresh command. */
  private readonly liveViews = new Set<() => void>();

  /** Every open panel, so a closing one can hand the status bar to a sibling. */
  private readonly openPanels = new Set<vscode.WebviewPanel>();

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

  /**
   * The engine's lint findings, published as native diagnostics so they also
   * appear in VS Code's Problems panel (and as squiggles in any text editor
   * showing the same file). One collection for the whole extension; per-file
   * entries are set on every read and cleared when a read fails or the file
   * closes, so Problems can never report what the view no longer does.
   */
  private readonly diagnostics: vscode.DiagnosticCollection;

  /**
   * Undefined citations, published against the `.tex` files that make them.
   *
   * A separate collection from the lint findings because it describes different
   * files: a citation with no entry behind it is a problem in the source that
   * cites it, so that is where the squiggle belongs. Keeping it separate also
   * means clearing one can never silently drop the other.
   */
  private readonly citationDiagnostics: vscode.DiagnosticCollection;

  /**
   * Paths the engine reported for the file currently shown in each panel.
   *
   * `openMaterial` and `openCitation` open a path the webview names, and the
   * webview is the least trustworthy part of this extension — so a path is
   * opened only when the last read actually reported it.
   */
  private readonly openablePaths = new WeakMap<vscode.WebviewPanel, Set<string>>();

  private constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly statusItem: vscode.StatusBarItem,
  ) {
    this.diagnostics = vscode.languages.createDiagnosticCollection("pynakes");
    this.citationDiagnostics = vscode.languages.createDiagnosticCollection("pynakes-citations");
  }

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
    return vscode.Disposable.from(
      registration,
      refreshCommand,
      statusItem,
      provider.diagnostics,
      provider.citationDiagnostics,
    );
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
    this.openPanels.add(panel);
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
      // Staged edits and published findings describe one document's content;
      // once it is gone they could never apply, so they go with it.
      vscode.workspace.onDidCloseTextDocument((closed) => {
        if (closed.uri.toString() === document.uri.toString()) {
          this.staging.delete(document.uri.toString());
          this.diagnostics.delete(document.uri);
          this.citationDiagnostics.clear();
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
      this.openPanels.delete(panel);
      this.statusByPanel.delete(panel);
      this.repointStatusBar();
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

  /**
   * Run one engine read against the document's current text.
   *
   * Resolves the engine, mirrors the buffer when it has unsaved changes, and
   * releases the mirror afterwards whatever the outcome. A thrown error becomes
   * an `engineError` message unless `reportFailure` reshapes it first — the
   * hook `compareRemote` uses to keep its failures scoped to one entry rather
   * than blanking the whole view.
   */
  private async withMirror(
    document: vscode.TextDocument,
    panel: vscode.WebviewPanel,
    body: (ctx: MirrorContext) => Promise<void>,
    reportFailure: (
      failure: Record<string, unknown>,
    ) => Record<string, unknown> = (failure) => failure,
  ): Promise<void> {
    let mirror: TempMirror | undefined;
    try {
      const engine = await resolveEngine(document.uri);
      const cwd = this.workingDirectory(document);
      mirror = await this.sourceFor(document);
      await body({ engine, command: engine.command, cwd, source: mirror.source });
    } catch (error) {
      // A failed read leaves the previous findings pointing into content the
      // engine could no longer read; Problems must go quiet with the view.
      this.diagnostics.delete(document.uri);
      this.citationDiagnostics.clear();
      void panel.webview.postMessage(reportFailure(await this.describeFailure(error, document)));
    } finally {
      await mirror?.release();
    }
  }

  /** Read the document through the engine and hand the result to the view. */
  private async load(document: vscode.TextDocument, panel: vscode.WebviewPanel): Promise<void> {
    await this.withMirror(document, panel, async ({ engine, command, cwd, source }) => {
      const result = await readLibrary(command, source, cwd, this.neighbourPath(document));
      if (!result.ok) {
        this.diagnostics.delete(document.uri);
        this.citationDiagnostics.clear();
        void panel.webview.postMessage({
          type: "parseError",
          error: result.error.error,
          message: result.error.message,
          line: result.error.line,
        });
        return;
      }
      const settings = this.viewSettings(document);
      this.publishDiagnostics(document, result.read.lint, settings.showFindings);
      this.publishCitationDiagnostics(result.read.citations, settings.showFindings);
      this.openablePaths.set(panel, collectOpenablePaths(result.read.citations, result.read.materials));
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
        settings,
      });
    });
  }

  /**
   * Publish (or withdraw) one file's findings as native diagnostics.
   *
   * The same `pynakes.showFindings` setting that gates the in-view markers
   * gates Problems, so the two can never disagree. Ranges are whole lines:
   * the engine locates a finding at its entry's declaration, which is all a
   * squiggle needs to be useful.
   */
  private publishDiagnostics(
    document: vscode.TextDocument,
    lint: LintIndex | null,
    showFindings: boolean,
  ): void {
    if (!showFindings || !lint) {
      this.diagnostics.delete(document.uri);
      return;
    }
    // Clamp rather than trust: the buffer may have moved on since the engine
    // read its mirror, and `lineAt` would throw on a stale out-of-range line.
    const lastLine = Math.max(0, document.lineCount - 1);
    const diagnostics = lintDiagnostics(lint.issues).map((item) => {
      const line = Math.min(item.line, lastLine);
      const diagnostic = new vscode.Diagnostic(
        document.lineAt(line).range,
        item.message,
        DIAGNOSTIC_SEVERITY[item.severity],
      );
      diagnostic.source = "pynakes";
      diagnostic.code = item.code;
      return diagnostic;
    });
    this.diagnostics.set(document.uri, diagnostics);
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
      citations: read.citations,
      materials: read.materials,
      warnings: read.warnings,
    };
  }

  /**
   * The document's real path on disk, for the reads about its neighbours.
   *
   * A dirty buffer is mirrored to a temporary file for every other read, but
   * `tex-sources`, `pinax-files-dir`, and relative `file` paths all resolve
   * from the `.bib`'s own directory — from a temp directory they resolve to
   * nothing. A document with no path on disk (never saved, or not a local
   * file) has no neighbours to read.
   */
  private neighbourPath(document: vscode.TextDocument): string | undefined {
    return document.uri.scheme === "file" ? document.uri.fsPath : undefined;
  }

  /**
   * Publish (or withdraw) undefined citations as diagnostics on the `.tex`
   * files that make them.
   *
   * Gated by the same `pynakes.showFindings` setting as the lint findings: both
   * are advisory validation, and a user who turned findings off did not ask for
   * one kind to keep reporting. The whole collection is replaced on every read,
   * so a citation that has since been resolved cannot linger.
   */
  private publishCitationDiagnostics(
    citations: CitationIndex | null,
    showFindings: boolean,
  ): void {
    this.citationDiagnostics.clear();
    if (!showFindings || !citations) {
      return;
    }
    for (const file of citationDiagnostics(citations)) {
      const diagnostics = file.items.map((item) => {
        const start = new vscode.Position(item.line, item.column);
        const diagnostic = new vscode.Diagnostic(
          new vscode.Range(start, start.translate(0, item.length)),
          item.message,
          vscode.DiagnosticSeverity.Warning,
        );
        diagnostic.source = "pynakes";
        diagnostic.code = "undefined-citation";
        return diagnostic;
      });
      this.citationDiagnostics.set(vscode.Uri.file(file.path), diagnostics);
    }
  }

  /**
   * Hand the status bar to whichever other bibliography view is active, or
   * hide it when there is none — a closing panel must not blank the item a
   * sibling view is still using.
   */
  private repointStatusBar(): void {
    for (const panel of this.openPanels) {
      if (panel.active && this.statusByPanel.get(panel)) {
        this.syncStatusBar(panel);
        return;
      }
    }
    this.statusItem.hide();
  }

  /** The webview-facing settings for one document. */
  private viewSettings(document: vscode.TextDocument): ViewSettings {
    const config = vscode.workspace.getConfiguration("pynakes", document.uri);
    return {
      fuzzy: config.get<boolean>("search.fuzzy", false),
      showFindings: config.get<boolean>("showFindings", true),
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
      case "compareRemote":
        if (message.key) {
          await this.compareRemote(document, panel, message.key);
        }
        return;
      case "renameKey":
        if (message.key && message.newKey) {
          await this.renameKey(document, panel, message.key, message.newKey);
        }
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
      case "openMaterial":
        await this.openMaterial(panel, message.path);
        return;
      case "openCitation":
        await this.openCitation(panel, message.path, message.line, message.column);
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
    await this.withMirror(document, panel, async ({ command, cwd, source }) => {
      const outcome = await runSearch(
        command,
        source,
        { query, where, fuzzy: message.fuzzy },
        cwd,
      );
      void panel.webview.postMessage(
        outcome.ok
          ? { type: "searchResult", keys: outcome.keys, ranked: outcome.ranked, count: outcome.count }
          : { type: "searchError", message: outcome.message },
      );
    });
  }

  // -- compare with remote ---------------------------------------------------

  /**
   * Compare one entry against its DOI/arXiv remote record (read-only).
   *
   * The network gate lives here, not in the webview: `online` is decided
   * from the `pynakes.allowOnlineLookups` setting for this document (on by
   * default; disabling it keeps compare fully offline), so whether a click
   * may reach the network is a setting decision, never something the view
   * can grant itself.
   */
  private async compareRemote(
    document: vscode.TextDocument,
    panel: vscode.WebviewPanel,
    key: string,
  ): Promise<void> {
    const online = vscode.workspace
      .getConfiguration("pynakes", document.uri)
      .get<boolean>("allowOnlineLookups", true);
    await this.withMirror(
      document,
      panel,
      async ({ command, cwd, source }) => {
        const outcome = await compareEntry(command, source, key, online, cwd);
        void panel.webview.postMessage(
          outcome.ok
            ? {
                type: "compareResult",
                key,
                source: outcome.source,
                identifier: outcome.identifier,
                fields: outcome.fields,
                warnings: outcome.warnings,
              }
            : { type: "compareError", key, message: outcome.message },
        );
      },
      // A compare failure is scoped to one entry, not the whole view, so it
      // is reported through `compareError` rather than the generic
      // `engineError` path other reads use (which blanks the table).
      (failure) => ({
        type: "compareError",
        key,
        message: typeof failure.message === "string" ? failure.message : "Compare failed.",
      }),
    );
  }

  // -- citation key rename ----------------------------------------------------

  /**
   * Rename one citation key, after reconciling the buffer and an explicit
   * approval. Unlike a field edit this also rewrites any linked TeX
   * `\cite{...}` keys, a wider blast radius that warrants asking first —
   * the same confirmation `commit` uses before writing.
   */
  private async renameKey(
    document: vscode.TextDocument,
    panel: vscode.WebviewPanel,
    oldKey: string,
    newKey: string,
  ): Promise<void> {
    const trimmed = newKey.trim();
    if (!trimmed || trimmed === oldKey) {
      return;
    }
    // The staging map is keyed by the entry's current citation key; renaming
    // out from under a pending field/type edit would orphan it.
    if (this.stagingFor(document).entries[oldKey]) {
      void panel.webview.postMessage({
        type: "renameKeyError",
        key: oldKey,
        message: "Discard or apply this entry's pending changes before renaming its key.",
      });
      return;
    }
    if (document.uri.scheme !== "file") {
      void panel.webview.postMessage({
        type: "renameKeyError",
        key: oldKey,
        message: "This document is not a local file, so it cannot be written.",
      });
      return;
    }
    if (!(await this.reconcileBuffer(document))) {
      void panel.webview.postMessage({
        type: "renameKeyError",
        key: oldKey,
        message: "Rename cancelled: the file still has unsaved changes.",
      });
      return;
    }

    const approval = await vscode.window.showWarningMessage(
      `Rename citation key "${oldKey}" to "${trimmed}"?`,
      {
        modal: true,
        detail: "Updates the entry and rewrites matching \\cite{...} keys in any linked TeX sources.",
      },
      "Rename",
    );
    if (approval !== "Rename") {
      void panel.webview.postMessage({ type: "renameKeyCancelled", key: oldKey });
      return;
    }

    try {
      const { command } = await resolveEngine(document.uri);
      const cwd = this.workingDirectory(document);
      const filePath = document.uri.fsPath;
      const outcome = await renameEntryKey(command, filePath, oldKey, trimmed, cwd);
      if (!outcome.ok) {
        void panel.webview.postMessage({ type: "renameKeyError", key: oldKey, message: outcome.message });
        return;
      }
      void panel.webview.postMessage({ type: "keyRenamed", oldKey, newKey: outcome.new });
      await this.load(document, panel);
    } catch (error) {
      void panel.webview.postMessage(await this.describeFailure(error, document));
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
    await this.withMirror(document, panel, async ({ command, cwd, source }) => {
      const result = await previewEdits(command, source, toRequests(state), cwd);
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
    });
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
      const { command } = await resolveEngine(document.uri);
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

  /**
   * Open one of an entry's materials.
   *
   * Handed to the operating system rather than opened in VS Code: a material is
   * a PDF or a source archive, and the editor has no viewer for either. A
   * directory is revealed in the file manager instead of "opened".
   */
  private async openMaterial(panel: vscode.WebviewPanel, target?: string): Promise<void> {
    const resolved = this.resolveOpenable(panel, target);
    if (!resolved) {
      return;
    }
    const uri = vscode.Uri.file(resolved);
    let isDirectory = false;
    try {
      isDirectory = (await vscode.workspace.fs.stat(uri)).type === vscode.FileType.Directory;
    } catch {
      void vscode.window.showWarningMessage(
        `${path.basename(resolved)} is no longer there. Re-read the file to refresh its materials.`,
      );
      return;
    }
    if (isDirectory) {
      await vscode.commands.executeCommand("revealFileInOS", uri);
      return;
    }
    await vscode.env.openExternal(uri);
  }

  /** Open a `.tex` source at one `\cite` occurrence. */
  private async openCitation(
    panel: vscode.WebviewPanel,
    target?: string,
    line?: number,
    column?: number,
  ): Promise<void> {
    const resolved = this.resolveOpenable(panel, target);
    if (!resolved) {
      return;
    }
    let document: vscode.TextDocument;
    try {
      document = await vscode.workspace.openTextDocument(vscode.Uri.file(resolved));
    } catch {
      void vscode.window.showWarningMessage(`Could not open ${path.basename(resolved)}.`);
      return;
    }
    // The engine reports one-based positions, and the source may have been
    // edited since it read them, so both are clamped rather than trusted.
    const row = Math.min(Math.max(0, (line ?? 1) - 1), Math.max(0, document.lineCount - 1));
    const text = document.lineAt(row);
    const col = Math.min(Math.max(0, (column ?? 1) - 1), text.text.length);
    const position = new vscode.Position(row, col);
    const selection = new vscode.Range(position, position);
    const editor = await vscode.window.showTextDocument(document, {
      viewColumn: vscode.ViewColumn.Beside,
      preview: false,
      selection,
    });
    editor.revealRange(selection, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
  }

  /**
   * Accept a path from the webview only when the last read reported it.
   *
   * The webview is this extension's least trustworthy input, and both open
   * actions hand a path to the operating system, so the path has to have come
   * from the engine rather than merely arrived in a message.
   */
  private resolveOpenable(panel: vscode.WebviewPanel, target?: string): string | undefined {
    if (target && this.openablePaths.get(panel)?.has(target)) {
      return target;
    }
    void vscode.window.showWarningMessage(
      "That file is not one this bibliography reported. Re-read the file and try again.",
    );
    return undefined;
  }

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

/**
 * Every path the view may ask to open: citation sources and existing materials.
 *
 * Built from the engine's own output, so the check in `resolveOpenable` accepts
 * exactly what this read reported and nothing else.
 */
function collectOpenablePaths(
  citations: CitationIndex | null,
  materials: MaterialIndex | null,
): Set<string> {
  const paths = new Set<string>();
  for (const occurrences of Object.values(citations?.byKey ?? {})) {
    for (const occurrence of occurrences) {
      paths.add(occurrence.path);
    }
  }
  for (const list of Object.values(materials?.byKey ?? {})) {
    for (const material of list) {
      if (material.path) {
        paths.add(material.path);
      }
    }
  }
  return paths;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
