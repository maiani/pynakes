/**
 * Renaming one citation key from the detail pane.
 *
 * A rename reaches further than the field it is typed into: the engine also
 * rewrites matching `\cite{...}` keys in the linked TeX sources, re-points any
 * `crossref` that names the entry, and moves the key's Pinax material files.
 * So it is not staged like a field edit. It is a `renameKey` mutation, and
 * takes exactly the path every other entry-level change takes — the engine's
 * `keys rename --dry-run --diff` in the Staged diff pane, an approval dialog
 * naming the sources and material files the preview reported, then the
 * identical invocation guarded by `--expect-sha256`. A key already taken is the
 * engine's conflict, reported with nothing written.
 */

import { runMutation, type MutationHost } from "./mutations";

export async function renameKey(host: MutationHost, oldKey: string, newKey: string): Promise<void> {
  const trimmed = newKey.trim();
  if (!trimmed || trimmed === oldKey) {
    host.post({ type: "mutationCancelled", label: `Rename ${oldKey}`, quiet: true });
    return;
  }
  await runMutation(host, { kind: "renameKey", oldKey, newKey: trimmed });
}
