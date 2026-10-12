/**
 * Renaming one citation key from the detail pane.
 *
 * Unlike a field edit this also rewrites any linked TeX `\cite{...}` keys, a
 * wider blast radius that warrants asking first — the same confirmation a
 * commit uses before writing.
 */

import * as vscode from "vscode";
import { resolveEngine } from "./engineDiscovery";
import { renameEntryKey } from "./library";
import { own } from "./records";
import type { StagingHost } from "./stagedCommit";

export async function renameKey(host: StagingHost, oldKey: string, newKey: string): Promise<void> {
  const { document } = host;
  const trimmed = newKey.trim();
  if (!trimmed || trimmed === oldKey) {
    return;
  }
  const refuse = (message: string): void => {
    host.post({ type: "renameKeyError", key: oldKey, message });
  };
  // The staging map is keyed by the entry's current citation key; renaming
  // out from under a pending field/type edit would orphan it.
  if (own(host.staging().entries, oldKey)) {
    refuse("Discard or apply this entry's pending changes before renaming its key.");
    return;
  }
  if (document.uri.scheme !== "file") {
    refuse("This document is not a local file, so it cannot be written.");
    return;
  }
  if (!(await host.reconcileBuffer())) {
    refuse("Rename cancelled: the file still has unsaved changes.");
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
    host.post({ type: "renameKeyCancelled", key: oldKey });
    return;
  }

  try {
    const { command } = await resolveEngine(document.uri);
    const outcome = await renameEntryKey(
      command,
      document.uri.fsPath,
      oldKey,
      trimmed,
      host.workingDirectory(),
    );
    if (!outcome.ok) {
      refuse(outcome.message);
      return;
    }
    host.post({ type: "keyRenamed", oldKey, newKey: outcome.new });
    await host.reload();
  } catch (error) {
    host.post(await host.describeFailure(error));
  }
}
