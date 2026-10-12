/**
 * Editing the declared group hierarchy from the groups sidebar.
 *
 * A different operation from an entry's membership of a group (the detail
 * pane's chips): these add, rename, move, describe and remove the *nodes* of
 * `groups tree`, through `groups add-group`, `rename-group`, `move-group`,
 * `update-group` and `remove-group`. Each one is a `groupTree` mutation, so it
 * goes through exactly the path every other entry- or group-level change takes
 * — the engine's `--dry-run --diff`, the Staged diff pane, an approval dialog,
 * and the identical invocation guarded by `--expect-sha256`.
 *
 * Nothing here knows the tree's rules. Whether a name is taken, whether a move
 * would make a cycle, which descendants a removal takes, which entries a rename
 * moves to the new name: the engine answers each of those, and this module only
 * asks which change was meant.
 */

import * as vscode from "vscode";
import { runMutation, type MutationHost } from "./mutations";
import type { GroupTreeEdit } from "./pynakes";

/** The node a sidebar action was invoked on, as the view's last read described it. */
export interface GroupActionRequest {
  name: string;
  /** Referenced by entries but absent from the declared hierarchy. */
  undeclared?: boolean;
  description?: string;
}

interface ActionItem extends vscode.QuickPickItem {
  action: "addChild" | "rename" | "move" | "describe" | "remove" | "declare";
}

/** Run one hierarchy edit through preview, approval, and the guarded write. */
function apply(host: MutationHost, edit: GroupTreeEdit): Promise<void> {
  return runMutation(host, { kind: "groupTree", edit });
}

/** Ask for a name, offering `value` to start from. Undefined when cancelled or blank. */
async function askName(title: string, value = ""): Promise<string | undefined> {
  const typed = await vscode.window.showInputBox({
    title,
    prompt: "Group name",
    value,
    valueSelection: [0, value.length],
  });
  return typed?.trim() || undefined;
}

/**
 * Add a group: at the top level, or under `parent`.
 *
 * The name is not checked here. A name the hierarchy already has is the
 * engine's `GroupConflict`, reported as written-nothing like any other.
 */
export async function promptNewGroup(host: MutationHost, parent?: string): Promise<void> {
  const name = await askName(parent ? `New subgroup of "${parent}"` : "New group");
  if (name) {
    await apply(host, { op: "add", name, parent });
  }
}

/**
 * Offer what can be done to one group node, then do it.
 *
 * `groups` is every group the view's last read declared, for the move target.
 * The node itself is left out because a group cannot be its own parent; its
 * descendants are not, because working out which they are is the engine's job,
 * and it refuses a move that would make a cycle.
 *
 * A group that entries mention but the hierarchy does not declare has no node
 * for these commands to act on, so the one thing offered is to declare it.
 */
export async function promptGroupAction(
  host: MutationHost,
  request: GroupActionRequest,
  groups: string[],
): Promise<void> {
  const name = request.name;
  const items: ActionItem[] = request.undeclared
    ? [
        {
          action: "declare",
          label: "$(add) Declare in the hierarchy",
          detail: "Entries are filed under this group, but the file's hierarchy does not list it.",
        },
      ]
    : [
        { action: "addChild", label: "$(add) Add subgroup…" },
        { action: "rename", label: "$(edit) Rename…" },
        { action: "move", label: "$(arrow-both) Move…", description: "Under another group" },
        { action: "describe", label: "$(note) Edit description…" },
        { action: "remove", label: "$(trash) Remove", description: "With its subgroups" },
      ];
  const picked = await vscode.window.showQuickPick(items, {
    title: `Group "${name}"`,
    placeHolder: "Change the group hierarchy",
  });
  switch (picked?.action) {
    case "declare":
      await apply(host, { op: "add", name });
      return;
    case "addChild":
      await promptNewGroup(host, name);
      return;
    case "rename": {
      const newName = await askName(`Rename group "${name}"`, name);
      if (newName && newName !== name) {
        await apply(host, { op: "rename", name, newName });
      }
      return;
    }
    case "move":
      await promptMove(host, name, groups);
      return;
    case "describe":
      await promptDescription(host, name, request.description ?? "");
      return;
    case "remove":
      await apply(host, { op: "remove", name });
      return;
    default:
      return;
  }
}

async function promptMove(host: MutationHost, name: string, groups: string[]): Promise<void> {
  const TOP_LEVEL = "$(arrow-up) Top level";
  const picked = await vscode.window.showQuickPick(
    [TOP_LEVEL, ...groups.filter((group) => group !== name)],
    { title: `Move group "${name}"`, placeHolder: "New parent group" },
  );
  if (picked) {
    await apply(host, { op: "move", name, parent: picked === TOP_LEVEL ? "" : picked });
  }
}

async function promptDescription(
  host: MutationHost,
  name: string,
  current: string,
): Promise<void> {
  const typed = await vscode.window.showInputBox({
    title: `Description of group "${name}"`,
    prompt: "Leave empty to clear it",
    value: current,
  });
  // Escape is a cancel; an emptied box is a request to clear.
  if (typed !== undefined && typed.trim() !== current.trim()) {
    await apply(host, { op: "describe", name, description: typed.trim() });
  }
}
