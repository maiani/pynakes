/**
 * Previewing and committing the staged field edits.
 *
 * Staged edits accumulate in the extension (see `staging.ts`); this module
 * turns them into the one `corpus batch` that previews them and the identical
 * one that writes them. Kept apart from the custom editor so the order of the
 * checks a commit makes — reconcile, dry run, conflict check, approval,
 * guarded write — reads in one place.
 */

import * as path from "node:path";
import * as vscode from "vscode";
import { resolveEngine } from "./engineDiscovery";
import { FILE_MOVED_MESSAGE, NO_FINGERPRINT_MESSAGE, commitEdits, previewEdits } from "./library";
import type { MutationHost } from "./mutations";
import { own } from "./records";
import {
  diffHeading,
  findConflicts,
  isEmpty,
  stagedCount,
  toRequests,
  type StagingConflict,
  type StagingState,
} from "./staging";

/** What a commit needs from the view, beyond what a mutation does. */
export interface StagingHost extends MutationHost {
  /** This document's pending edits. */
  staging(): StagingState;
  /** Drop every pending edit, after they were written. */
  resetStaging(): void;
  /** Tell the webview what is pending now. */
  postStaging(): void;
}

/**
 * Dry-run the staged changes and show the exact diff.
 *
 * Previews run against the buffer, mirror included, so an unsaved document can
 * still be inspected. Committing is stricter — see `commitStaged`.
 */
export async function previewStaged(host: StagingHost): Promise<void> {
  const state = host.staging();
  if (isEmpty(state)) {
    host.post({ type: "diff", entries: [] });
    return;
  }
  await host.withMirror(async ({ command, cwd, source }) => {
    const requests = toRequests(state);
    const result = await previewEdits(command, source, requests, cwd);
    if (!result.ok) {
      host.post({ type: "commitError", message: `Preview failed: ${result.message}` });
      return;
    }
    host.post({
      type: "diff",
      entries: [
        {
          key: diffHeading(requests.map((request) => request.key)),
          diff: result.diff,
          warnings: result.warnings,
        },
      ],
    });
  }, (failure) => ({
    // The library is as it was; a preview that could not run is reported
    // where the commit bar's errors go, rather than blanking the table.
    type: "commitError",
    message: `Preview failed: ${typeof failure.message === "string" ? failure.message : "the engine could not run"}`,
  }));
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
 *
 * The write is one `corpus batch`, so it lands whole or not at all, and it
 * carries the digest the dry run reported, so a change made while the
 * approval dialog was open is refused rather than overwritten. Anything short
 * of success leaves every staged edit in place: nothing was written.
 */
export async function commitStaged(host: StagingHost): Promise<void> {
  const { document } = host;
  const state = host.staging();
  if (isEmpty(state)) {
    return;
  }
  if (document.uri.scheme !== "file") {
    host.post({
      type: "commitError",
      message: "This document is not a local file, so it cannot be written.",
    });
    return;
  }
  if (!(await host.reconcileBuffer())) {
    host.post({
      type: "commitError",
      message: "Apply cancelled: the file still has unsaved changes.",
    });
    return;
  }

  const requests = toRequests(state);
  try {
    const { command } = await resolveEngine(document.uri);
    const cwd = host.workingDirectory();
    const filePath = document.uri.fsPath;

    const preview = await previewEdits(command, filePath, requests, cwd);
    if (!preview.ok) {
      host.post({ type: "commitError", message: `Cannot apply: ${preview.message}` });
      return;
    }
    const sourceSha256 = preview.sourceSha256;
    if (!sourceSha256) {
      host.post({ type: "commitError", message: NO_FINGERPRINT_MESSAGE });
      return;
    }

    const conflicts: StagingConflict[] = [];
    for (const entry of preview.entries) {
      const staged = own(state.entries, entry.key);
      if (staged) {
        conflicts.push(...findConflicts(staged, entry.plan));
      }
    }
    if (conflicts.length > 0) {
      host.post({
        type: "conflict",
        conflicts,
        message:
          "The file changed since these edits were made. Nothing was written — " +
          "review the current values and edit again.",
      });
      await host.reload();
      return;
    }

    // Put the diff on screen before asking, so approval is informed.
    host.post({
      type: "diff",
      entries: [
        {
          key: diffHeading(requests.map((request) => request.key)),
          diff: preview.diff,
          warnings: preview.warnings,
        },
      ],
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
      host.post({ type: "commitCancelled" });
      return;
    }

    const result = await commitEdits(command, filePath, requests, sourceSha256, cwd);
    if (!result.ok) {
      // Nothing was written, so every staged edit stays staged. A file that
      // moved is reported as the conflict it is; the reload below shows what
      // it holds now, and the next apply re-checks each edit against it.
      if (result.conflict && result.error === "ExternalModification") {
        host.post({ type: "conflict", conflicts: [], message: FILE_MOVED_MESSAGE });
      } else {
        host.post({ type: "commitError", message: `Nothing was written: ${result.message}` });
      }
    } else {
      host.resetStaging();
      host.post({ type: "committed", applied: result.applied, warnings: result.warnings });
    }
    host.postStaging();
    await host.reload();
  } catch (error) {
    host.post(await host.describeFailure(error));
  }
}
