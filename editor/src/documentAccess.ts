/**
 * What every engine call needs to know about the document it runs against:
 * which path to read, where to run from, whether it may write, and how a
 * failure is explained.
 *
 * Plain functions of one `TextDocument`, with no state of their own, so the
 * custom editor and the modules it delegates to share one answer to each
 * question rather than each keeping a copy.
 */

import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";
import { asMaterialOpener, DEFAULT_MATERIAL_OPENER, type MaterialOpener } from "./materialOpener";
import { PynakesProtocolError, PynakesUnavailableError } from "./pynakes";

export interface TempMirror {
  /** Path pynakes should read. */
  source: string;
  /** Removes the mirror, if one was created. */
  release(): Promise<void>;
}

/** Settings the view honors, re-read on every render so changes apply live. */
export interface ViewSettings {
  /** Initial state of the search box's fuzzy toggle. */
  fuzzy: boolean;
  /** Whether per-row severity markers and the findings panel are shown. */
  showFindings: boolean;
  /** Where a material opens on a plain click: `"editor"` or `"system"`. */
  openMaterialsWith: MaterialOpener;
}

/**
 * Decide what pynakes should read.
 *
 * A saved local file is read in place. An unsaved buffer — or any document
 * that is not a local file — is mirrored to a temporary file first, so the
 * view always reflects the text on screen rather than the text on disk.
 */
export async function sourceFor(document: vscode.TextDocument): Promise<TempMirror> {
  if (document.uri.scheme === "file" && !document.isDirty) {
    return { source: document.uri.fsPath, release: async () => {} };
  }
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "pynakes-vscode-"));
  const release = async (): Promise<void> => {
    await fs.rm(directory, { recursive: true, force: true });
  };
  const basename = path.basename(document.uri.path) || "bibliography.bib";
  // `.bib` in any case: the engine recognizes the library by that suffix.
  const source = path.join(
    directory,
    basename.toLowerCase().endsWith(".bib") ? basename : `${basename}.bib`,
  );
  try {
    await fs.writeFile(source, document.getText(), "utf8");
  } catch (error) {
    // No mirror is handed back to release, so the directory goes here.
    await release().catch(() => undefined);
    throw error;
  }
  return { source, release };
}

/** Run the engine from the workspace folder so relative paths resolve. */
export function workingDirectory(document: vscode.TextDocument): string | undefined {
  const folder = vscode.workspace.getWorkspaceFolder(document.uri);
  if (folder?.uri.scheme === "file") {
    return folder.uri.fsPath;
  }
  if (document.uri.scheme === "file") {
    return path.dirname(document.uri.fsPath);
  }
  return undefined;
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
export function neighbourPath(document: vscode.TextDocument): string | undefined {
  return document.uri.scheme === "file" ? document.uri.fsPath : undefined;
}

/** The webview-facing settings for one document. */
export function viewSettings(document: vscode.TextDocument): ViewSettings {
  const config = vscode.workspace.getConfiguration("pynakes", document.uri);
  return {
    fuzzy: config.get<boolean>("search.fuzzy", false),
    showFindings: config.get<boolean>("showFindings", true),
    openMaterialsWith:
      asMaterialOpener(config.get<unknown>("openMaterialsWith")) ?? DEFAULT_MATERIAL_OPENER,
  };
}

/**
 * Whether this view may reach the network for this document.
 *
 * Every network-backed action reads this one place, so "no lookups" means the
 * same thing for comparing and for importing rather than depending on which
 * button was pressed.
 */
export function onlineLookupsAllowed(document: vscode.TextDocument): boolean {
  return vscode.workspace
    .getConfiguration("pynakes", document.uri)
    .get<boolean>("allowOnlineLookups", true);
}

/** Turn a thrown boundary error into something the view can explain. */
export function describeFailure(error: unknown): Record<string, unknown> {
  if (error instanceof PynakesUnavailableError) {
    return {
      type: "engineError",
      kind: "unavailable",
      message: `Could not run the pynakes engine as "${error.command}".`,
      detail:
        "No usable engine was found. The extension ships one, which needs a " +
        "Python 3.12+ interpreter on the system; if there is none, install the " +
        "engine with `pip install pynakes`. The `pynakes.executable` setting " +
        "overrides discovery entirely, and `pynakes.engine` can force the " +
        "bundled or the installed engine.",
    };
  }
  if (error instanceof PynakesProtocolError) {
    return { type: "engineError", kind: "protocol", message: error.message, detail: error.detail };
  }
  return {
    type: "engineError",
    kind: "unknown",
    message: "Reading the bibliography failed.",
    detail: error instanceof Error ? (error.stack ?? error.message) : String(error),
  };
}

/**
 * Bring the buffer and the file on disk into agreement before writing.
 *
 * The editor's own `files.autoSave` decides how: when autosave is on the
 * buffer is saved without asking, because that is what the editor would do
 * moments later anyway. With autosave off, saving is the user's decision, so
 * it is asked for rather than assumed.
 */
export async function reconcileBuffer(document: vscode.TextDocument): Promise<boolean> {
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
