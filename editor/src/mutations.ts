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
  type MutationOutcome,
} from "./library";
import { refSchema, type GroupTreeEdit, type PynakesCommand } from "./pynakes";

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

/** Why the engine did not apply a call: its message, and whether it was a conflict. */
interface Refusal {
  conflict?: boolean;
  error?: string;
  message: string;
}

/**
 * Report a call the engine refused. A conflict is the engine declining — a
 * taken key, a merge it will not guess — so it is said to have written nothing
 * rather than to have failed. A write refused because the file moved while the
 * approval was open is re-read, so what the view shows is what is there.
 */
export async function reportRefusal(
  host: MutationHost,
  fail: (message: string) => void,
  refusal: Refusal,
): Promise<void> {
  if (refusal.conflict === true && refusal.error === "ExternalModification") {
    fail(FILE_MOVED_MESSAGE);
    await host.reload();
    return;
  }
  fail(refusal.conflict === true ? `Nothing was written: ${refusal.message}` : refusal.message);
}

/** Citation keys a mutation would rewrite or remove, for the staging check. */
function mutationKeys(mutation: Mutation): string[] {
  switch (mutation.kind) {
    case "add":
      return mutation.request.key ? [mutation.request.key] : [];
    case "import":
      return mutation.request.key ? [mutation.request.key] : [];
    case "remove":
    case "groups":
    case "generateKeys":
      return mutation.keys;
    case "group":
      return [mutation.key];
    case "dedupeMerge":
      // The named cluster is refused up front. Which other entries a merge
      // rewrites or removes — every cluster's, for a whole-file merge — only
      // the engine knows, and its preview's plan names them; they are checked
      // against the staging map there.
      return mutation.keys ?? [];
    case "renameKey":
      // The staging map is keyed by citation key, so a pending edit on the
      // renamed entry would be orphaned. Entries whose `crossref` follows the
      // rename are named by the preview's plan.
      return [mutation.oldKey];
    case "metadata":
    case "linkTexSource":
      return [];
    case "groupTree":
      // The hierarchy lives in the file's metadata, not in any entry. The
      // entries a rename moves are known only from its preview, and are
      // checked against the staging map there.
      return [];
  }
}

/**
 * What the approval dialog says beyond the diff already on screen.
 *
 * Each line names a consequence the diff itself does not show — deleted files,
 * a network request — so approving is never a surprise.
 */
function approvalDetail(mutation: Mutation, preview: PreviewedMutation): string {
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
      lines.push(...materialMoveDetail(preview, "into the surviving entry's"));
      break;
    case "generateKeys":
      lines.push(...renameKeyDetail("Selected entries", preview));
      break;
    case "renameKey":
      lines.push(...renameKeyDetail(mutation.oldKey, preview));
      break;
    case "groupTree":
      lines.push(...groupTreeDetail(mutation.edit, preview));
      break;
    case "linkTexSource":
      lines.push("Citations in this source then count toward which entries are cited.");
      break;
    default:
      break;
  }
  lines.push(...preview.warnings);
  lines.push("The diff above is exactly what will be written.");
  return lines.join("\n\n");
}

/** What the approval dialog reads from a successful preview. */
type PreviewedMutation = Extract<MutationOutcome, { ok: true }>;

/**
 * What a hierarchy edit does that its diff hides or scatters.
 *
 * The hierarchy and membership are separate records. A rename carries its
 * members along (`--members`), and the dialog names the entries the engine
 * reported moving; a removal changes the hierarchy only, and says so. The
 * descendants of a removed group are likewise the ones the engine reported it
 * would take — neither list is worked out here.
 */
function groupTreeDetail(edit: GroupTreeEdit, preview: PreviewedMutation): string[] {
  switch (edit.op) {
    case "remove": {
      const others = (preview.removedGroups ?? []).filter((name) => name !== edit.name);
      return [
        others.length > 0
          ? `Also removes ${others.length === 1 ? "its subgroup" : `its ${others.length} subgroups`}: ` +
            others.map((name) => `"${name}"`).join(", ") + "."
          : `"${edit.name}" has no subgroups.`,
        "Entries keep their memberships: any entry filed under a removed group shows it " +
          "as a group the hierarchy does not declare.",
      ];
    }
    case "rename": {
      const moved = preview.renamedMembers ?? [];
      return [
        moved.length > 0
          ? `Moves ${moved.length === 1 ? "its entry" : `its ${moved.length} entries`} ` +
            `to "${edit.newName}": ${listKeys(moved)}.`
          : `No entry is filed under "${edit.name}", so only the hierarchy changes.`,
      ];
    }
    case "move":
      return ["Its subgroups move with it."];
    default:
      return [];
  }
}

/**
 * What a key rename writes beyond the `.bib`, as the engine's preview named it.
 *
 * The diff on screen covers the rewritten TeX sources too, but a source can be
 * far down it; and the Pinax files that change name appear in no diff at all.
 */
function renameKeyDetail(oldKey: string, preview: PreviewedMutation): string[] {
  const sources = preview.rewrittenSources ?? [];
  const lines: string[] = [];
  if (sources.length > 0) {
    const total = sources.reduce((sum, source) => sum + source.occurrences, 0);
    lines.push(
      `Also rewrites ${total === 1 ? "one citation" : `${total} citations`} of ${oldKey} in ` +
        `${sources.length === 1 ? "a linked TeX source" : `${sources.length} linked TeX sources`}: ` +
        sources.map((source) => `${baseName(source.path)} (${source.occurrences})`).join(", ") +
        ".",
    );
  } else {
    lines.push(`No linked TeX source cites ${oldKey}, so only the bibliography changes.`);
  }
  lines.push(...materialMoveDetail(preview, "to the new key's"));
  return lines;
}

/** The Pinax files a preview says would change name — never shown in a diff. */
function materialMoveDetail(preview: PreviewedMutation, destination: string): string[] {
  const moves = preview.materialMoves ?? [];
  if (moves.length === 0) {
    return [];
  }
  return [
    `Moves ${moves.length === 1 ? "one material file" : `${moves.length} material files`} ` +
      `${destination} name on disk: ` +
      moves
        .map((move) => `${baseName(move.source_path)} → ${baseName(move.target_path)}`)
        .join(", ") +
      ".",
  ];
}

/** The last path segment, for a dialog line; the path itself came from the engine. */
function baseName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

/** Citation keys for a dialog: all of a short list, the first few of a long one. */
function listKeys(keys: string[], shown = 12): string {
  if (keys.length <= shown) {
    return keys.join(", ");
  }
  return `${keys.slice(0, shown).join(", ")} and ${keys.length - shown} more`;
}

/** The approval question, which for a removal counts what goes with the group. */
function approvalTitle(label: string, mutation: Mutation, preview: PreviewedMutation): string {
  if (mutation.kind === "groupTree" && mutation.edit.op === "remove") {
    const removed = mutation.edit.name;
    const subgroups = (preview.removedGroups ?? []).filter((name) => name !== removed);
    if (subgroups.length > 0) {
      return `${label} and ${subgroups.length === 1 ? "its subgroup" : `its ${subgroups.length} subgroups`}?`;
    }
  }
  if (mutation.kind === "groupTree" && mutation.edit.op === "rename") {
    const moved = preview.renamedMembers ?? [];
    if (moved.length > 0) {
      return `${label}, moving ${moved.length === 1 ? "its entry" : `its ${moved.length} entries`}?`;
    }
  }
  return `${label}?`;
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
  let request: import("./pynakes").RefAddRequest | undefined;
  await host.withMirror(async ({ command, source, cwd }) => {
    const response = await refSchema(command, source, cwd);
    if (response.status !== "success") throw new Error(response.message);
    const choice = await vscode.window.showQuickPick(
      [...response.entry_schemas.map(schema => schema.entry_type), "Custom type…"],
      { title: "New entry", placeHolder: "Entry type" },
    );
    if (!choice) return;
    const entryType = choice === "Custom type…"
      ? await vscode.window.showInputBox({ title: "Custom entry type" }) : choice;
    if (!entryType?.trim()) return;
    const schema = response.entry_schemas.find(schema => schema.entry_type === entryType);
    const fields: Record<string, string> = {};
    for (const alternatives of [...(schema?.required ?? []), ...(schema?.profile_required ?? []).map(f => [f])]) {
      if (alternatives.some(field => fields[field])) continue;
      const field = alternatives.length === 1 ? alternatives[0] : await vscode.window.showQuickPick(alternatives,
        { title: "Required alternative", placeHolder: "Choose a field to supply" });
      if (!field) return;
      const value = await vscode.window.showInputBox({ title: `New ${entryType} — ${field}`,
        prompt: "Leave blank if unknown; the engine will report missing requirements" });
      if (value === undefined) return;
      if (value.trim()) fields[field] = value;
    }
    // Optional fields matter for key patterns even when the type has no requirements.
    const optional = await vscode.window.showQuickPick(schema?.optional ?? [],
      { title: "Additional fields", canPickMany: true, placeHolder: "Select fields to fill, or accept none" });
    if (optional === undefined) return;
    for (const field of optional) {
      const value = await vscode.window.showInputBox({ title: `New ${entryType} — ${field}` });
      if (value === undefined) return;
      if (value.trim()) fields[field] = value;
    }
    const key = await vscode.window.showInputBox({ title: "Citation key",
      prompt: "Leave blank to generate from these fields using the library's key pattern" });
    if (key === undefined) return;
    request = { entryType: entryType.trim(), fields, ...(key.trim() ? { key: key.trim() } : {}) };
  });
  if (request) await runMutation(host, { kind: "add", request });
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
  keys: string[],
  candidates: string[],
  member = true,
): Promise<void> {
  if (!keys.length) return;
  const key = keys.length === 1 ? keys[0] : `${keys.length} entries`;
  const title = `${member ? "Add" : "Remove"} ${key} ${member ? "to" : "from"} a group`;
  const NEW_GROUP = "$(add) New group…";
  const picked = candidates.length
    ? await vscode.window.showQuickPick(member ? [...candidates, NEW_GROUP] : candidates, {
        title,
        placeHolder: "Group name",
      })
    : member ? NEW_GROUP : undefined;
  if (!picked) {
    return;
  }
  let group = picked;
  if (picked === NEW_GROUP) {
    const typed = await vscode.window.showInputBox({
      title,
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
    ...(keys.length === 1 ? { kind: "group", key: keys[0] } : { kind: "groups", keys }),
    group,
    member,
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
      await reportRefusal(host, fail, preview);
      return;
    }
    // Everything the engine says this would rewrite or remove, which for a
    // whole-file merge or a group rename is known only now.
    const rewritten = [...new Set([...(preview.renamedMembers ?? []), ...preview.rewrittenKeys])]
      .filter((key) => staged.has(key));
    if (rewritten.length > 0) {
      fail(`Discard or apply the pending changes to ${rewritten.join(", ")} before this.`);
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
      approvalTitle(label, mutation, preview),
      { modal: true, detail: approvalDetail(mutation, preview) },
      "Apply",
    );
    if (approval !== "Apply") {
      host.post({ type: "mutationCancelled", label });
      return;
    }

    const applied = await applyMutation(command, filePath, mutation, sourceSha256, cwd);
    if (!applied.ok) {
      await reportRefusal(host, fail, applied);
      return;
    }
    host.post({
      type: "mutationDone",
      metadataChanged: mutation.kind === "metadata",
      label,
      warnings: applied.warnings,
      // An entry that was just created is almost certainly the one to edit
      // next — a `ref add` deliberately arrives empty. The engine names it,
      // including the key it generated for an import.
      select: mutation.kind === "add" || mutation.kind === "import" ? applied.key : undefined,
      // A renamed group that was the sidebar's filter stays the filter.
      renamedGroup:
        mutation.kind === "groupTree" && mutation.edit.op === "rename"
          ? { from: mutation.edit.name, to: mutation.edit.newName }
          : undefined,
      // A renamed entry that was selected stays selected under its new key.
      renamedKey:
        mutation.kind === "renameKey"
          ? { from: mutation.oldKey, to: mutation.newKey }
          : undefined,
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
