/**
 * Leaving the view for something it points at: an entry's declaration in the
 * source text, a `\cite` in a `.tex` file, or a material on disk.
 *
 * Both open actions hand a path to the operating system or the editor, and the
 * path arrives in a webview message — the least trustworthy input this
 * extension has. So a path is opened only when it is in the set the last read
 * reported (see `collectOpenablePaths`).
 */

import * as path from "node:path";
import * as vscode from "vscode";
import type { CitationIndex, MaterialIndex } from "./insights";
import { customEditorsOf, hasCustomViewer, planMaterialOpen } from "./materialOpener";

/**
 * Every path the view may ask to open: citation sources and existing materials.
 *
 * Built from the engine's own output, so the check in `resolveOpenable` accepts
 * exactly what this read reported and nothing else.
 */
export function collectOpenablePaths(
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
      // Only what the engine found on disk, as the kind it should be: the view
      // offers nothing else, so a request for anything else is not one it made.
      if (material.path && material.present) {
        paths.add(material.path);
      }
    }
  }
  return paths;
}

/** Accept a path from the webview only when the last read reported it. */
function resolveOpenable(openable: Set<string> | undefined, target?: string): string | undefined {
  if (target && openable?.has(target)) {
    return target;
  }
  void vscode.window.showWarningMessage(
    "That file is not one this bibliography reported. Re-read the file and try again.",
  );
  return undefined;
}

/**
 * Open one of an entry's materials, inside VS Code or with the system.
 *
 * `requested` is the click's own choice (the row's secondary action, or an
 * Alt-click); without one, `pynakes.openMaterialsWith` decides. In VS Code the
 * file opens beside the view in whatever editor is associated with it, and
 * nothing is executed. A file VS Code has no viewer for (a PDF with no viewer
 * extension) still opens there, to VS Code's binary placeholder, and a
 * notification once per format per session offers the system's viewer instead.
 */
export async function openMaterial(
  openable: Set<string> | undefined,
  target?: string,
  requested?: unknown,
  scope?: vscode.Uri,
): Promise<void> {
  const resolved = resolveOpenable(openable, target);
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
  const extension = path.extname(resolved).toLowerCase();
  const plan = planMaterialOpen({
    setting: vscode.workspace.getConfiguration("pynakes", scope ?? null).get("openMaterialsWith"),
    requested,
    isDirectory,
    inWorkspace: isDirectory && vscode.workspace.getWorkspaceFolder(uri) !== undefined,
    hasViewer: !isDirectory && installedViewerFor(resolved, scope),
    extension,
  });
  switch (plan.action) {
    case "revealInExplorer":
      await vscode.commands.executeCommand("revealInExplorer", uri);
      return;
    case "revealInOS":
      await vscode.commands.executeCommand("revealFileInOS", uri);
      return;
    case "system":
      await vscode.env.openExternal(uri);
      return;
    case "editor":
      await vscode.commands.executeCommand("vscode.open", uri, {
        viewColumn: vscode.ViewColumn.Beside,
        preview: false,
      });
      if (plan.suggestViewer && !hinted.has(extension)) {
        hinted.add(extension);
        void suggestViewer(uri, extension);
      }
      return;
  }
}

/** Formats already hinted about this session, so the notification shows once each. */
const hinted = new Set<string>();

/** Whether an installed custom editor would show this file when VS Code opens it. */
function installedViewerFor(filePath: string, scope?: vscode.Uri): boolean {
  const editors = customEditorsOf(vscode.extensions.all.map((extension) => extension.packageJSON));
  const associations = vscode.workspace
    .getConfiguration("workbench", scope ?? null)
    .get<unknown>("editorAssociations");
  return hasCustomViewer(filePath, editors, associations);
}

/** Offer the system's viewer, without blocking: the file is already open. */
async function suggestViewer(uri: vscode.Uri, extension: string): Promise<void> {
  const external = "Open Externally";
  const always = "Always Open Externally";
  const find = "Find a PDF Viewer";
  const choices = extension === ".pdf" ? [external, always, find] : [external, always];
  const choice = await vscode.window.showInformationMessage(
    `VS Code has no viewer for ${extension} files, so ${path.basename(uri.fsPath)} opened as ` +
      "binary. Open it with the system's viewer instead, or install a viewer extension.",
    ...choices,
  );
  if (choice === external || choice === always) {
    await vscode.env.openExternal(uri);
  }
  if (choice === always) {
    await vscode.workspace
      .getConfiguration("pynakes")
      .update("openMaterialsWith", "system", vscode.ConfigurationTarget.Global);
  }
  if (choice === find) {
    await vscode.commands.executeCommand("workbench.extensions.search", "pdf viewer");
  }
}

/** Open a `.tex` source at one `\cite` occurrence. */
export async function openCitation(
  openable: Set<string> | undefined,
  target?: string,
  line?: number,
  column?: number,
): Promise<void> {
  const resolved = resolveOpenable(openable, target);
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

/** Open the source text beside the view, at the entry's declaration. */
export async function revealEntry(document: vscode.TextDocument, key: string): Promise<void> {
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

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Resolve the current double-click preference against engine-reported materials. */
export async function doubleClickEntry(
  document: vscode.TextDocument,
  key: string,
  materials: MaterialIndex | null | undefined,
  openable: Set<string> | undefined,
): Promise<void> {
  if (vscode.workspace.getConfiguration("pynakes", document.uri).get("doubleClickAction") === "source") {
    await revealEntry(document, key);
    return;
  }
  const entries = materials?.byKey;
  const list = entries && Object.hasOwn(entries, key) ? entries[key] : [];
  const seen = new Set<string>();
  const pdfs = (list ?? []).filter((material) => {
    const target = material.path;
    if (!material.present || !target || path.extname(target).toLowerCase() !== ".pdf" || seen.has(target)) {
      return false;
    }
    seen.add(target);
    return true;
  });
  if (!pdfs.length) {
    void vscode.window.showInformationMessage(`No local PDF is available for "${key}".`);
    return;
  }
  const chosen = pdfs.length === 1 ? pdfs[0] : (await vscode.window.showQuickPick(
    pdfs.map((material) => ({ label: material.label, description: material.path!, material })),
    { placeHolder: `Open a PDF for ${key}` },
  ))?.material;
  if (chosen) {
    await openMaterial(openable, chosen.path!, undefined, document.uri);
  }
}
