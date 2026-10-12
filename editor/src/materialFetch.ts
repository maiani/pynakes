/**
 * Fetching an entry's missing materials — or the whole library's — from the view.
 *
 * The same family as the entry-level changes in `mutations.ts`: plan with the
 * engine's own `--dry-run --diff`, show what the plan says, ask, then run the
 * identical invocation without `--dry-run`, conditional on the file still
 * being the one planned against. What differs is what the approval has to
 * name. A fetch's real work is files beside the `.bib` and requests to the
 * network, neither of which a diff of the `.bib` shows — so the dialog lists
 * each file the engine said it would write, where, and by which identifier,
 * and each entry it left out with the engine's reason (see `fetchPlan.ts`).
 *
 * Like `asset check`, a fetch runs against the `.bib` as saved at its real
 * location: `pinax-files-dir` resolves from the `.bib`'s own directory, which
 * the temporary mirror used for unsaved buffers does not have. The buffer is
 * reconciled first, under the same autosave-or-ask policy a commit follows.
 */

import * as vscode from "vscode";
import { resolveEngine } from "./engineDiscovery";
import {
  FETCH_LOOKUPS_DISABLED,
  FETCH_MATERIALS,
  NO_PLAN_MESSAGE,
  fetchApproval,
  fetchLabel,
  fetchResult,
  nothingToFetch,
  planFetch,
  runFetch,
} from "./fetchPlan";
import { NO_FINGERPRINT_MESSAGE } from "./library";
import { reportRefusal, type MutationHost } from "./mutations";
import { PynakesCancelledError, type AssetFetchRequest } from "./pynakes";

/** Ask which material to fetch; `undefined` when the pick was dismissed. */
async function pickMaterial(key: string | undefined): Promise<{ material?: string } | undefined> {
  const picked = await vscode.window.showQuickPick(
    FETCH_MATERIALS.map((choice) => ({ label: choice.label, detail: choice.detail, choice })),
    {
      title: key ? `Fetch materials for ${key}` : "Fetch missing materials for every entry",
      placeHolder: "Which materials? Only missing ones are fetched.",
    },
  );
  return picked ? { material: picked.choice.value } : undefined;
}

/**
 * Plan, approve, and fetch.
 *
 * With `key`, one entry's materials; without it, every entry's. Whatever the
 * outcome, the view is told the fetch is over, so its button is usable again.
 */
export async function promptFetch(host: MutationHost, key: string | undefined): Promise<void> {
  const done = (): void => host.post({ type: "fetchState", key: key ?? null, busy: false });
  try {
    await fetchMaterials(host, key);
  } catch (error) {
    host.post(await host.describeFailure(error));
  } finally {
    done();
  }
}

async function fetchMaterials(host: MutationHost, key: string | undefined): Promise<void> {
  let label = fetchLabel({ key });
  const fail = (message: string): void => host.post({ type: "mutationError", label, message });

  // The network gate is the extension's, read from the setting: the view
  // cannot grant itself a lookup. Said up front rather than discovered at the
  // provider.
  if (!host.onlineLookupsAllowed()) {
    fail(FETCH_LOOKUPS_DISABLED);
    return;
  }
  if (host.document.uri.scheme !== "file") {
    fail("This document is not a local file, so it has no materials directory.");
    return;
  }
  const choice = await pickMaterial(key);
  if (!choice) {
    return;
  }
  const request: AssetFetchRequest = { key, material: choice.material };
  label = fetchLabel(request);
  if (!(await host.reconcileBuffer())) {
    fail("Cancelled: the file still has unsaved changes.");
    return;
  }

  const { command } = await resolveEngine(host.document.uri);
  const cwd = host.workingDirectory();
  const filePath = host.document.uri.fsPath;

  const plan = await planFetch(command, filePath, request, cwd);
  if (!plan.ok) {
    fail(plan.message);
    return;
  }
  // Approving a fetch whose files nobody can name would approve blind.
  if (plan.unplanned.length > 0) {
    fail(NO_PLAN_MESSAGE);
    return;
  }
  if (plan.planned.length === 0) {
    host.post({ type: "mutationNoop", label, message: nothingToFetch(request, plan) });
    return;
  }
  // The `.bib` may change (a first fetch records the store), so the run is
  // conditional on the file the plan read, like every other write here.
  const sourceSha256 = plan.sourceSha256;
  if (!sourceSha256) {
    fail(NO_FINGERPRINT_MESSAGE);
    return;
  }
  if (plan.diff) {
    host.post({ type: "diff", entries: [{ key: label, diff: plan.diff, warnings: plan.warnings }] });
  }

  const { title, detail } = fetchApproval(request, plan);
  const approval = await vscode.window.showWarningMessage(title, { modal: true, detail }, "Fetch");
  if (approval !== "Fetch") {
    host.post({ type: "mutationCancelled", label });
    return;
  }

  let applied;
  try {
    applied = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: label,
        cancellable: true,
      },
      async (progress, token) => {
        // The engine reports no per-file progress in JSON mode, so this says
        // only that it is working, and how to stop it.
        progress.report({ message: "downloading… (Cancel stops it; finished files are kept)" });
        const controller = new AbortController();
        const subscription = token.onCancellationRequested(() => controller.abort());
        try {
          return await runFetch(command, filePath, request, sourceSha256, cwd, controller.signal);
        } finally {
          subscription.dispose();
        }
      },
    );
  } catch (error) {
    if (error instanceof PynakesCancelledError) {
      // Every material lands atomically, so a stopped fetch keeps what it
      // finished and leaves nothing half-written. Re-read to show which.
      host.post({
        type: "fetchDone",
        level: "info",
        message: `${label}: stopped. Anything already downloaded was kept.`,
      });
      await host.reload();
      return;
    }
    throw error;
  }

  if (!applied.ok) {
    await reportRefusal(host, fail, applied);
    return;
  }
  const result = fetchResult(applied, new Set(plan.planned.map((entry) => entry.key)));
  host.post({ type: "fetchDone", level: result.level, message: `${label}: ${result.message}` });
  await host.reload();
}
