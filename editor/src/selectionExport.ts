/** Selection exports use the engine's codecs and dependency rules. */
import * as vscode from "vscode";
import type { MutationHost } from "./mutations";
import { exportSelection, type SelectionFormat } from "./pynakes";

export async function promptExport(host: MutationHost, keys: string[], copy: boolean): Promise<void> {
  if (!keys.length) return;
  if (keys.some(key => host.stagedKeys().has(key))) {
    void vscode.window.showInformationMessage("Apply or discard pending changes to the selection before exporting.");
    return;
  }
  const chosen = copy ? "bib" : await vscode.window.showQuickPick(
    ["bib", "csl-json", "ris", "mods", "endnote", "csv"], { title: "Export selection", placeHolder: "Format" });
  if (!chosen) return;
  const format = chosen as SelectionFormat;
  await host.withMirror(async ({command, source, cwd}) => {
    const result = await exportSelection(command, source, keys, format, cwd);
    if (result.status !== "success") throw new Error(result.message);
    if (result.warnings.length) {
      const proceed = await vscode.window.showWarningMessage(
        result.warnings.map(warning => warning.message ?? warning.type ?? "Export warning").join("\n"),
        { modal: true }, "Continue export");
      if (!proceed) return;
    }
    if (copy) {
      await vscode.env.clipboard.writeText(result.content);
      vscode.window.setStatusBarMessage("Copied selection as BibTeX (including dependencies and library metadata)", 4000);
    } else {
      const language = format === "bib" ? "bibtex" : format === "csl-json" ? "json" : format === "mods" ? "xml" : "plaintext";
      const document = await vscode.workspace.openTextDocument({ content: result.content, language });
      await vscode.window.showTextDocument(document, { preview: false });
      vscode.window.setStatusBarMessage("Selection exported to a new document; save it to keep the export", 5000);
    }
  });
}
