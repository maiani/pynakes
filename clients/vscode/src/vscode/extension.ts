/**
 * Extension entry point.
 *
 * The view is opt-in: `.bib` files still open in the text editor by default,
 * and this contributes an alternative editor plus a command to reach it.
 */

import * as vscode from "vscode";
import { BibliographyEditorProvider } from "./bibliographyEditor";

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(BibliographyEditorProvider.register(context));

  context.subscriptions.push(
    vscode.commands.registerCommand("pynakes.openBibliography", async (resource?: vscode.Uri) => {
      const target = resource ?? (await pickBibliography());
      if (!target) {
        return;
      }
      await vscode.commands.executeCommand(
        "vscode.openWith",
        target,
        BibliographyEditorProvider.viewType,
      );
    }),
  );
}

export function deactivate(): void {
  // Everything is disposed through context.subscriptions.
}

/** Resolve which file to open: the active one, or one the user picks. */
async function pickBibliography(): Promise<vscode.Uri | undefined> {
  const active = vscode.window.activeTextEditor?.document.uri;
  if (active && active.path.toLowerCase().endsWith(".bib")) {
    return active;
  }

  const found = await vscode.workspace.findFiles("**/*.bib", "**/{node_modules,.git}/**", 500);
  if (found.length === 0) {
    void vscode.window.showInformationMessage("No .bib file found in this workspace.");
    return undefined;
  }
  if (found.length === 1) {
    return found[0];
  }

  const items = found
    .map((uri) => ({
      label: vscode.workspace.asRelativePath(uri),
      description: undefined as string | undefined,
      uri,
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
  const choice = await vscode.window.showQuickPick(items, {
    title: "Open bibliography",
    placeHolder: "Select a .bib file",
    matchOnDescription: true,
  });
  return choice?.uri;
}
