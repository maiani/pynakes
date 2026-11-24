import type { Mutation, MutationOutcome } from "./library";
import type { GroupTreeEdit } from "./engine/pynakes";

/** Citation keys a mutation would rewrite or remove, for the staging check. */
export function mutationKeys(mutation: Mutation): string[] {
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
export function approvalDetail(mutation: Mutation, preview: PreviewedMutation): string {
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
export function approvalTitle(label: string, mutation: Mutation, preview: PreviewedMutation): string {
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
