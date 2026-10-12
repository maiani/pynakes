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
 * Open one of an entry's materials.
 *
 * Handed to the operating system rather than opened in VS Code: a material is
 * a PDF or a source archive, and the editor has no viewer for either. A
 * directory is revealed in the file manager instead of "opened".
 */
export async function openMaterial(
  openable: Set<string> | undefined,
  target?: string,
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
  if (isDirectory) {
    await vscode.commands.executeCommand("revealFileInOS", uri);
    return;
  }
  await vscode.env.openExternal(uri);
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
