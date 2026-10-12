/**
 * The bibliography view, registered as a custom editor for `.bib` files.
 *
 * It is a `CustomTextEditorProvider` so VS Code keeps ownership of the document:
 * the text buffer stays the source of truth, external edits arrive as change
 * events, and nothing here caches file content.
 *
 * Staged edits live here rather than in the webview, because a webview is
 * disposed whenever its tab is hidden and pending changes must survive that.
 *
 * This module is the glue: it reads, renders, and routes the webview's
 * messages. What a message *does* lives beside it — `stagedCommit.ts` and
 * `keyRename.ts` for writes from the detail pane, `mutations.ts` and
 * `groupHierarchy.ts` for entry- and group-level changes, `materialFetch.ts` for
 * downloading materials, `navigation.ts` for leaving the view, `diagnostics.ts`
 * and `statusBar.ts` for what is published outside it, and `documentAccess.ts`
 * for the questions every engine call asks about the document.
 */

import * as vscode from "vscode";
import { FindingsPublisher } from "./diagnostics";
import {
  describeFailure,
  neighbourPath,
  onlineLookupsAllowed,
  reconcileBuffer,
  sourceFor,
  viewSettings,
  workingDirectory,
  type TempMirror,
} from "./documentAccess";
import { resetEngineDiscovery, resolveEngine, type ResolvedEngine } from "./engineDiscovery";
import { promptGroupAction, promptNewGroup, type GroupActionRequest } from "./groupHierarchy";
import { renameKey } from "./keyRename";
import { promptFetch } from "./materialFetch";
import { compareEntry, readLibrary, runSearch, type LibraryRead, type Mutation } from "./library";
import {
  promptAdd,
  promptGroup,
  promptImport,
  reportDuplicates,
  runMutation,
} from "./mutations";
import { collectOpenablePaths, openCitation, openMaterial, revealEntry } from "./navigation";
import { type PynakesCommand, describeCommand } from "./pynakes";
import { commitStaged, previewStaged, type StagingHost } from "./stagedCommit";
import {
  discardEntry,
  emptyStaging,
  stageField,
  stageType,
  stagedCount,
  unstageField,
  type StagingState,
} from "./staging";
import { EngineStatusBar } from "./statusBar";
import { renderShell } from "./webview";

/** Coalesce bursts of keystrokes into a single engine read. */
const REFRESH_DEBOUNCE_MS = 250;

/** Everything an engine read needs besides the webview it reports to. */
interface MirrorContext {
  engine: ResolvedEngine;
  command: PynakesCommand;
  cwd: string | undefined;
  source: string;
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
  /** Which search this is, echoed back so a late answer to an older one is ignored. */
  seq?: number;
  /** Absolute path, for `openMaterial` and `openCitation`. */
  path?: string;
  /** One-based position within that file, for `openCitation`. */
  line?: number;
  column?: number;
  /** The entry- or group-level change requested, for `mutate`. */
  mutation?: Mutation;
  /** Group names the view already knows about, for `promptGroup` and the group actions. */
  groups?: string[];
  /** The group node a sidebar action was invoked on, for `groupActions`. */
  group?: GroupActionRequest;
}

export class BibliographyEditorProvider implements vscode.CustomTextEditorProvider {
  public static readonly viewType = "pynakes.bibliography";

  /** Refresh callbacks for every live view, driven by the refresh command. */
  private readonly liveViews = new Set<() => void>();

  /** Pending edits per document, surviving webview disposal. */
  private readonly staging = new Map<string, StagingState>();

  private readonly findings = new FindingsPublisher();

  /**
   * Paths the engine reported for the file currently shown in each panel.
   *
   * `openMaterial` and `openCitation` open a path the webview names, and the
   * webview is the least trustworthy part of this extension — so a path is
   * opened only when the last read actually reported it.
   */
  private readonly openablePaths = new WeakMap<vscode.WebviewPanel, Set<string>>();

  /** Every open panel per document, so a staging change reaches each view of it. */
  private readonly panelsByDocument = new Map<string, Set<vscode.WebviewPanel>>();

  /** Panels already closed: a read still in flight must not post to one. */
  private readonly disposedPanels = new WeakSet<vscode.WebviewPanel>();

  /**
   * The newest read started for each panel. Reads run concurrently — a burst of
   * typing, a save, a write's reload — and finish in any order, so only the
   * newest one may render; an older one finishing late would show stale text.
   */
  private readonly readGeneration = new WeakMap<vscode.WebviewPanel, number>();

  private constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly statusBar: EngineStatusBar,
  ) {}

  public static register(context: vscode.ExtensionContext): vscode.Disposable {
    const statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusItem.command = "pynakes.refreshBibliography";
    const statusBar = new EngineStatusBar(statusItem);
    const provider = new BibliographyEditorProvider(context, statusBar);
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
      // An explicit re-read also re-decides which engine runs, so installing
      // or upgrading pynakes takes effect without reloading the window.
      resetEngineDiscovery();
      for (const refresh of provider.liveViews) {
        refresh();
      }
    });
    return vscode.Disposable.from(registration, refreshCommand, statusBar, provider.findings);
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
    this.statusBar.track(panel);
    const documentId = document.uri.toString();
    const siblings = this.panelsByDocument.get(documentId) ?? new Set<vscode.WebviewPanel>();
    siblings.add(panel);
    this.panelsByDocument.set(documentId, siblings);
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
          this.findings.clear(document);
        }
      }),
      panel.webview.onDidReceiveMessage((message: ViewMessage) => {
        // Every handler reports its own failures; this catches what escapes
        // one, so nothing becomes an unhandled rejection.
        this.handleMessage(document, panel, message).catch((error: unknown) =>
          this.post(panel, { ...describeFailure(error), type: "actionError" }),
        );
      }),
      // The item describes one bibliography, so it follows the active tab.
      panel.onDidChangeViewState(() => this.statusBar.sync(panel)),
    ];

    panel.onDidDispose(() => {
      disposed = true;
      this.disposedPanels.add(panel);
      siblings.delete(panel);
      if (siblings.size === 0) {
        this.panelsByDocument.delete(documentId);
      }
      this.statusBar.forget(panel);
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
   * an `engineError` message — blanking the view and withdrawing its findings —
   * unless `reportFailure` reshapes it first, the hook every action-scoped read
   * (compare, search, preview, duplicates) uses to keep its failure its own.
   */
  private async withMirror(
    document: vscode.TextDocument,
    panel: vscode.WebviewPanel,
    body: (ctx: MirrorContext) => Promise<void>,
    reportFailure?: (failure: Record<string, unknown>) => Record<string, unknown>,
    superseded: () => boolean = () => false,
  ): Promise<void> {
    let mirror: TempMirror | undefined;
    try {
      const engine = await resolveEngine(document.uri);
      const cwd = workingDirectory(document);
      mirror = await sourceFor(document);
      await body({ engine, command: engine.command, cwd, source: mirror.source });
    } catch (error) {
      // A newer read owns the view now; this one's failure is about old text.
      if (superseded()) {
        return;
      }
      if (!reportFailure) {
        // A failed read of the library leaves the previous findings pointing
        // into content the engine could no longer read; Problems must go quiet
        // with the view. A failure scoped to one action (a compare, a search,
        // a preview) leaves both the view and Problems as they were.
        this.findings.clear(document);
        this.post(panel, describeFailure(error));
        return;
      }
      this.post(panel, reportFailure(describeFailure(error)));
    } finally {
      await mirror?.release().catch(() => undefined);
    }
  }

  /**
   * Send one message to a panel, unless it has closed.
   *
   * A read or a write can outlive its panel — the tab closed while the engine
   * ran — and posting to a disposed webview throws.
   */
  private post(panel: vscode.WebviewPanel, message: Record<string, unknown>): void {
    if (this.disposedPanels.has(panel)) {
      return;
    }
    try {
      void panel.webview.postMessage(message);
    } catch {
      // Disposed between the check and the post: nothing is listening.
    }
  }

  /** Read the document through the engine and hand the result to the view. */
  private async load(document: vscode.TextDocument, panel: vscode.WebviewPanel): Promise<void> {
    const generation = (this.readGeneration.get(panel) ?? 0) + 1;
    this.readGeneration.set(panel, generation);
    const superseded = (): boolean =>
      this.disposedPanels.has(panel) || this.readGeneration.get(panel) !== generation;
    await this.withMirror(document, panel, async ({ engine, command, cwd, source }) => {
      const result = await readLibrary(command, source, cwd, neighbourPath(document));
      if (superseded()) {
        return;
      }
      if (!result.ok) {
        this.findings.clear(document);
        this.post(panel, {
          type: "parseError",
          error: result.error.error,
          message: result.error.message,
          line: result.error.line,
        });
        return;
      }
      const settings = viewSettings(document);
      this.findings.publishLint(document, result.read.lint, settings.showFindings);
      this.findings.publishCitations(document, result.read.citations, settings.showFindings);
      this.openablePaths.set(
        panel,
        collectOpenablePaths(result.read.citations, result.read.materials),
      );
      this.statusBar.update(panel, {
        summary: result.read.summary,
        findings: result.read.lint?.counts,
        engine: { version: engine.version, source: engine.source, reason: engine.reason },
        dirty: document.isDirty,
      });
      this.post(panel, {
        type: "render",
        payload: toPayload(result.read),
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
    }, undefined, superseded);
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

  /**
   * Tell every view of this document what is pending now.
   *
   * The pending edits belong to the document, and a second view of the same
   * file (a split editor) commits them just as the first does, so each must
   * show them — not only the view that made the change.
   */
  private postStaging(document: vscode.TextDocument, panel: vscode.WebviewPanel): void {
    const message = {
      type: "staging",
      staging: this.stagingFor(document),
      counts: stagedCount(this.stagingFor(document)),
    };
    const panels = this.panelsByDocument.get(document.uri.toString()) ?? new Set([panel]);
    for (const view of panels) {
      this.post(view, message);
    }
  }

  // -- messages -------------------------------------------------------------

  private async handleMessage(
    document: vscode.TextDocument,
    panel: vscode.WebviewPanel,
    message: ViewMessage,
  ): Promise<void> {
    const host = (): StagingHost => this.host(document, panel);
    switch (message.type) {
      case "ready":
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
        await previewStaged(host());
        return;
      case "commit":
        await commitStaged(host());
        return;
      case "compareRemote":
        if (message.key) {
          await this.compareRemote(document, panel, message.key);
        }
        return;
      case "renameKey":
        if (message.key && message.newKey) {
          await renameKey(host(), message.key, message.newKey);
        }
        return;
      case "reveal":
        if (message.key) {
          await revealEntry(document, message.key);
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
        await openMaterial(this.openablePaths.get(panel), message.path);
        return;
      case "openCitation":
        await openCitation(
          this.openablePaths.get(panel),
          message.path,
          message.line,
          message.column,
        );
        return;
      case "mutate":
        if (message.mutation) {
          await runMutation(host(), message.mutation);
        }
        return;
      case "promptAdd":
        await promptAdd(host());
        return;
      case "promptImport":
        await promptImport(host());
        return;
      case "promptGroup":
        if (message.key) {
          await promptGroup(host(), message.key, message.groups ?? []);
        }
        return;
      case "groupActions":
        if (message.group?.name) {
          await promptGroupAction(host(), message.group, message.groups ?? []);
        }
        return;
      case "promptNewGroup":
        await promptNewGroup(host());
        return;
      case "fetchMaterials":
        // No key fetches for every entry; the plan and the approval say which.
        await promptFetch(host(), message.key || undefined);
        return;
      case "findDuplicates":
        await reportDuplicates(host());
        return;
      default:
        return;
    }
  }

  // -- reads on request -----------------------------------------------------

  private async search(
    document: vscode.TextDocument,
    panel: vscode.WebviewPanel,
    message: ViewMessage,
  ): Promise<void> {
    const query = message.query ?? "";
    const where = message.where ?? "";
    if (!query.trim() && !where.trim()) {
      this.post(panel, { type: "searchCleared", seq: message.seq });
      return;
    }
    const seq = message.seq;
    await this.withMirror(
      document,
      panel,
      async ({ command, cwd, source }) => {
        const outcome = await runSearch(command, source, { query, where, fuzzy: message.fuzzy }, cwd);
        this.post(
          panel,
          outcome.ok
            ? { type: "searchResult", seq, keys: outcome.keys, ranked: outcome.ranked, count: outcome.count }
            : { type: "searchError", seq, message: outcome.message },
        );
      },
      // A search that could not run says so in the search box's notice; the
      // table still shows the last good read rather than going blank.
      (failure) => ({
        type: "searchError",
        seq,
        message: typeof failure.message === "string" ? failure.message : "Search failed.",
      }),
    );
  }

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
    const online = onlineLookupsAllowed(document);
    await this.withMirror(
      document,
      panel,
      async ({ command, cwd, source }) => {
        const outcome = await compareEntry(command, source, key, online, cwd);
        this.post(
          panel,
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

  // -- the slice handed to the write modules ----------------------------------

  /**
   * The slice of this provider that the write modules are allowed to use.
   *
   * Built per message rather than held, because every capability it exposes is
   * already scoped to one document and one panel; handing over the provider
   * itself would let those modules reach state they have no business touching.
   */
  private host(document: vscode.TextDocument, panel: vscode.WebviewPanel): StagingHost {
    return {
      document,
      post: (message) => this.post(panel, message),
      stagedKeys: () => new Set(Object.keys(this.stagingFor(document).entries)),
      staging: () => this.stagingFor(document),
      resetStaging: () => this.staging.set(document.uri.toString(), emptyStaging()),
      postStaging: () => this.postStaging(document, panel),
      reconcileBuffer: () => reconcileBuffer(document),
      workingDirectory: () => workingDirectory(document),
      onlineLookupsAllowed: () => onlineLookupsAllowed(document),
      reload: () => this.load(document, panel),
      // A write that failed leaves the file as it was, so the view keeps
      // showing it: `actionError` reports the failure without blanking the
      // table the way a failed read (`engineError`) does.
      describeFailure: async (error) => ({ ...describeFailure(error), type: "actionError" }),
      withMirror: (body, reportFailure) =>
        this.withMirror(
          document,
          panel,
          ({ command, cwd, source }) => body({ command, cwd, source }),
          reportFailure,
        ),
    };
  }
}

/** Shape one read for the webview. */
function toPayload(read: LibraryRead): Record<string, unknown> {
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
