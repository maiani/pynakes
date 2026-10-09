/**
 * Entry- and group-level changes made from the view.
 *
 * Separate from the custom editor because they are a different kind of change
 * from a field edit: they alter which entries exist rather than what one holds,
 * so none of them goes through the staging map. What they share is a single
 * path — preview with the engine's own `--dry-run --diff`, show that diff,
 * ask, then re-run the identical invocation without `--dry-run` — and keeping
 * that path in one place is what stops six near-copies drifting apart in what
 * they check before writing.
 *
 * The custom editor passes a `MutationHost` rather than itself, so nothing here
 * reaches into the provider's state and this module can be read on its own.
 */

import * as vscode from "vscode";
import { resolveEngine } from "./engineDiscovery";
import {
  FILE_MOVED_MESSAGE,
  NO_FINGERPRINT_MESSAGE,
  applyMutation,
  describeMutation,
  findDuplicates,
  previewMutation,
  type Mutation,
} from "./library";
import type { PynakesCommand } from "./pynakes";

/** What a mutation needs from the view it runs in. */
export interface MutationHost {
  readonly document: vscode.TextDocument;
  /** Send one message to the webview. */
  post(message: Record<string, unknown>): void;
  /** Citation keys with pending field edits, which a mutation must not orphan. */
  stagedKeys(): Set<string>;
  /** Make the file on disk match the buffer, or report that it could not. */
  reconcileBuffer(): Promise<boolean>;
  workingDirectory(): string | undefined;
  /** Whether this view may reach the network, from `pynakes.allowOnlineLookups`. */
  onlineLookupsAllowed(): boolean;
  /** Re-read the bibliography and re-render. */
  reload(): Promise<void>;
  describeFailure(error: unknown): Promise<Record<string, unknown>>;
  /** Run a read against the buffer, mirrored when it has unsaved changes. */
  withMirror(
    body: (ctx: { command: PynakesCommand; cwd?: string; source: string }) => Promise<void>,
    reportFailure?: (failure: Record<string, unknown>) => Record<string, unknown>,
  ): Promise<void>;
}

/**
 * Entry types offered when adding an entry by hand.
 *
 * A convenience list, not a schema: the engine accepts any type, and `lint`
 * judges whether the entry satisfies it. These are simply the ones worth one
 * keystroke, ordered by how often a working bibliography needs them.
 */
const ENTRY_TYPES = [
  "article",
  "book",
  "inproceedings",
  "incollection",
  "inbook",
  "phdthesis",
  "mastersthesis",
  "techreport",
  "misc",
  "online",
  "unpublished",
  "proceedings",
  "manual",
  "dataset",
  "software",
];

/** Citation keys a mutation would rewrite or remove, for the staging check. */
function mutationKeys(mutation: Mutation): string[] {
  switch (mutation.kind) {
    case "add":
      return [mutation.request.key];
    case "import":
      return mutation.request.key ? [mutation.request.key] : [];
    case "remove":
      return mutation.keys;
    case "group":
      return [mutation.key];
    case "dedupeMerge":
      // A whole-file merge (no keys) could touch anything, but it is previewed
      // and approved like the rest; what matters here is the named cluster,
      // whose entries are about to be rewritten or removed.
      return mutation.keys ?? [];
  }
}

/**
 * What the approval dialog says beyond the diff already on screen.
 *
 * Each line names a consequence the diff itself does not show — deleted files,
 * a network request — so approving is never a surprise.
 */
function approvalDetail(mutation: Mutation, warnings: string[]): string {
  const lines: string[] = [];
  switch (mutation.kind) {
    case "remove":
      lines.push(
        mutation.keepFiles
          ? "Removes the entries and keeps their linked materials on disk."
          : "Removes the entries and deletes their Pinax materials from disk.",
      );
      break;
    case "import":
      lines.push(`Resolved from ${mutation.request.identifier} over the network.`);
      break;
    case "dedupeMerge":
      lines.push(
        mutation.keys?.length
          ? "Folds this pair into its first entry and removes the copies."
          : "Folds every duplicate in the file into its first entry and removes the copies.",
      );
      break;
    default:
      break;
  }
  lines.push(...warnings);
  lines.push("The diff above is exactly what will be written.");
  return lines.join("\n\n");
}

/**
 * Ask for a key and a type, then add an empty entry of that type.
 *
 * Deliberately minimal: the entry arrives with nothing in it and the existing
 * field editor fills it, rather than this growing a second entry form that
 * would have to know each type's required fields — something the engine
 * already knows and `lint` already reports.
 *
 * Native VS Code prompts rather than in-view forms: they are modal in the way
 * this needs, already keyboard-accessible, and keep the webview free of
 * input state the extension would have to mirror.
 */
export async function promptAdd(host: MutationHost): Promise<void> {
  const key = await vscode.window.showInputBox({
    title: "New entry",
    prompt: "Citation key for the new entry",
    placeHolder: "Newton1687",
    validateInput: (value) =>
      // Only the shape the format itself forbids: a key with whitespace, a
      // comma or a brace cannot be written back. Whether it is *taken* is the
      // engine's judgement, and it refuses with a conflict.
      /[\s,{}()="#%'\\~]/.test(value)
        ? "A citation key cannot contain whitespace, braces, quotes, or a comma."
        : undefined,
  });
  if (!key?.trim()) {
    return;
  }
  const entryType = await vscode.window.showQuickPick(ENTRY_TYPES, {
    title: `New entry — ${key.trim()}`,
    placeHolder: "Entry type",
  });
  if (!entryType) {
    return;
  }
  await runMutation(host, {
    kind: "add",
    request: { key: key.trim(), entryType, fields: {} },
  });
}

/**
 * Ask for an identifier and import it.
 *
 * This is the one view action that reaches the network, so it honors
 * `pynakes.allowOnlineLookups` like `compare` does: with lookups off it says
 * so rather than quietly failing at the provider.
 */
export async function promptImport(host: MutationHost): Promise<void> {
  if (!host.onlineLookupsAllowed()) {
    host.post({
      type: "mutationError",
      label: "Import",
      message:
        "Online lookups are disabled, so a reference cannot be fetched. " +
        "Enable pynakes.allowOnlineLookups to import by identifier.",
    });
    return;
  }
  const identifier = await vscode.window.showInputBox({
    title: "Import a reference",
    prompt: "DOI, arXiv id, ISBN, or a supported publisher URL",
    placeHolder: "10.1103/PhysRevLett.124.2446",
  });
  if (!identifier?.trim()) {
    return;
  }
  await runMutation(host, {
    kind: "import",
    request: { identifier: identifier.trim() },
  });
}

/**
 * Add the selected entry to a group.
 *
 * Offers the groups the file already declares, plus a free-text option, so
 * the common case is a pick rather than retyping a name exactly. Removing a
 * membership is the chip's own affordance in the detail pane, which needs no
 * prompt.
 */
export async function promptGroup(
  host: MutationHost,
  key: string,
  candidates: string[],
): Promise<void> {
  const NEW_GROUP = "$(add) New group…";
  const picked = candidates.length
    ? await vscode.window.showQuickPick([...candidates, NEW_GROUP], {
        title: `Add ${key} to a group`,
        placeHolder: "Group name",
      })
    : NEW_GROUP;
  if (!picked) {
    return;
  }
  let group = picked;
  if (picked === NEW_GROUP) {
    const typed = await vscode.window.showInputBox({
      title: `Add ${key} to a group`,
      prompt: "Group name",
      validateInput: (value) =>
        // `;` separates memberships in the stored field, so a name containing
        // one could not be read back as a single group.
        value.includes(";") ? "A group name cannot contain a semicolon." : undefined,
    });
    if (!typed?.trim()) {
      return;
    }
    group = typed.trim();
  }
  // Only a name typed under "New group…" may create a group.
  await runMutation(host, {
    kind: "group",
    key,
    group,
    member: true,
    create: picked === NEW_GROUP,
  });
}

/**
 * Run one entry- or group-level change through preview, approval, and write.
 *
 * These cannot use the staging map: it is keyed by citation key and holds
 * field edits, whereas these change which entries exist. What they keep
 * instead is the property that matters — the diff shown is the diff that
 * lands. The engine's own `--dry-run --diff` output goes to the Diff pane,
 * the approval dialog is raised over it, and approval re-runs the identical
 * invocation without `--dry-run`, conditional on the file still having the
 * digest the preview reported — so nothing written while the dialog was open
 * is overwritten.
 *
 * The file is reconciled first for the same reason a commit reconciles it: a
 * write against a stale buffer would discard whatever the text editor holds.
 */
export async function runMutation(
  host: MutationHost,
  // Reassigned when an import conflict is answered, so the write that follows
  // carries the answer rather than repeating the refused request.
  mutation: Mutation,
): Promise<void> {
  const label = describeMutation(mutation);
  const fail = (message: string): void => {
    host.post({ type: "mutationError", label, message });
  };

  if (host.document.uri.scheme !== "file") {
    fail("This document is not a local file, so it cannot be written.");
    return;
  }
  // A pending field edit on an entry this would remove or rewrite would be
  // left pointing at something that no longer exists.
  const staged = host.stagedKeys();
  const touched = mutationKeys(mutation).filter((key) => staged.has(key));
  if (touched.length > 0) {
    fail(`Discard or apply the pending changes to ${touched.join(", ")} before this.`);
    return;
  }
  if (!(await host.reconcileBuffer())) {
    fail("Cancelled: the file still has unsaved changes.");
    return;
  }

  try {
    const { command } = await resolveEngine(host.document.uri);
    const cwd = host.workingDirectory();
    const filePath = host.document.uri.fsPath;

    let preview = await previewMutation(command, filePath, mutation, cwd);
    // A conflict is the engine declining to guess, not a failure. The one
    // such question this view can put to the user is "the library already has
    // this reference — add it anyway?", so that one is asked here and the
    // answer replayed through `--allow-duplicate`. Every other conflict is
    // reported as it came, because resolving it is not this dialog's business.
    if (!preview.ok && preview.conflict === true && mutation.kind === "import") {
      const anyway = await vscode.window.showWarningMessage(
        preview.message,
        { modal: true, detail: preview.options.map((option) => option.description).join("\n") },
        "Import anyway",
      );
      if (anyway !== "Import anyway") {
        host.post({ type: "mutationCancelled", label });
        return;
      }
      mutation = { kind: "import", request: { ...mutation.request, allowDuplicate: true } };
      preview = await previewMutation(command, filePath, mutation, cwd);
    }
    if (!preview.ok) {
      fail(preview.message);
      return;
    }
    if (!preview.modified) {
      host.post({
        type: "mutationNoop",
        label,
        message: `${label}: nothing to change.`,
      });
      return;
    }

    // The write is conditional on the file the preview read. An engine that
    // cannot report that file's digest cannot honor the condition either, so
    // nothing is attempted rather than writing unguarded.
    const sourceSha256 = preview.sourceSha256;
    if (!sourceSha256) {
      fail(NO_FINGERPRINT_MESSAGE);
      return;
    }

    host.post({
      type: "diff",
      entries: [{ key: label, diff: preview.diff, warnings: preview.warnings }],
    });

    const approval = await vscode.window.showWarningMessage(
      `${label}?`,
      { modal: true, detail: approvalDetail(mutation, preview.warnings) },
      "Apply",
    );
    if (approval !== "Apply") {
      host.post({ type: "mutationCancelled", label });
      return;
    }

    const applied = await applyMutation(command, filePath, mutation, sourceSha256, cwd);
    if (!applied.ok) {
      // Not applied, whichever way it was refused. A file that moved while the
      // dialog was open is re-read, so what the view shows is what is there.
      if (applied.conflict === true && applied.error === "ExternalModification") {
        fail(FILE_MOVED_MESSAGE);
        await host.reload();
        return;
      }
      fail(applied.conflict === true ? `Nothing was written: ${applied.message}` : applied.message);
      return;
    }
    host.post({
      type: "mutationDone",
      label,
      warnings: applied.warnings,
      // An entry that was just created is almost certainly the one to edit
      // next — a `ref add` deliberately arrives empty. The engine names it,
      // including the key it generated for an import.
      select: mutation.kind === "add" || mutation.kind === "import" ? applied.key : undefined,
    });
    await host.reload();
  } catch (error) {
    host.post(await host.describeFailure(error));
  }
}

/**
 * Report which entries the engine judges to be the same work.
 *
 * Read-only, so it runs against the buffer like every other read — an unsaved
 * paste of a reference the library already has is exactly when this is worth
 * asking.
 */
export async function reportDuplicates(host: MutationHost): Promise<void> {
  await host.withMirror(
    async ({ command, cwd, source }) => {
      const outcome = await findDuplicates(command, source, cwd);
      host.post(
        outcome.ok
          ? { type: "duplicates", clusters: outcome.clusters }
          : { type: "duplicatesError", message: outcome.message },
      );
    },
    (failure) => ({ type: "duplicatesError", message: String(failure.message ?? failure) }),
  );
}
