/** A local document host using the same engine and edit session as VS Code. */
import * as path from "node:path";
import { BibliographySession, type SessionHost, type EditApproval } from "../../../packages/client-core/src/session";
import { readLibrary, runSearch, previewEdits, commitEdits, previewMutation, applyMutation,
  describeMutation, compareEntry, findDuplicates, type LibraryRead, type Mutation } from "../../../packages/client-core/src/library";
import { approvalDetail, approvalTitle } from "../../../packages/client-core/src/mutationReview";
import { NO_FINGERPRINT_MESSAGE } from "../../../packages/client-core/src/writeErrors";
import { stagedCount } from "../../../packages/client-core/src/staging";
import { exportSelection, type PynakesCommand, type SelectionFormat } from "../../../packages/client-core/src/engine/pynakes";
import type { ViewMessage } from "../../../packages/client-core/src/protocol";

export interface PromptField { name: string; label: string; value?: string; choices?: string[]; required?: boolean; }
export interface DesktopServices {
  post(message: Record<string, unknown>): void;
  approve(title: string, detail: string): Promise<boolean>;
  prompt(title: string, fields: PromptField[]): Promise<Record<string, string> | null>;
  copy(text: string): void;
  saveExport(content: string, format: string): Promise<void>;
  openPath(file: string): Promise<void>;
}

export class DesktopDocument {
  readonly session = new BibliographySession();
  read: LibraryRead | undefined;
  private generation = 0;
  private busy = false;
  constructor(readonly file: string, readonly command: PynakesCommand, readonly services: DesktopServices) {}
  get cwd(): string { return path.dirname(this.file); }
  get hasPending(): boolean { return this.busy || this.session.stagedKeys().size > 0; }
  private post(message: Record<string, unknown>): void { this.services.post(message); }
  postStaging(): void {
    const staging = this.session.snapshot();
    this.post({ type: "staging", staging, counts: stagedCount(staging) });
  }
  async reload(): Promise<void> {
    const generation = ++this.generation;
    const result = await readLibrary(this.command, this.file, this.cwd, this.file);
    if (generation !== this.generation) return;
    if (!result.ok) {
      this.read = undefined;
      this.post({ type: "parseError", ...result.error });
      return;
    }
    this.read = result.read;
    this.post({ type: "render", payload: result.read, dirty: false, staging: this.session.snapshot(),
      engine: { source: "desktop", command: this.command.executable, reason: "Local pynakes engine" },
      settings: { openMaterialsWith: "system", showFindings: true, fuzzy: false } });
  }
  private sessionHost(): SessionHost {
    return {
      preview: requests => previewEdits(this.command, this.file, requests, this.cwd),
      prepareWrite: async () => ({ name: path.basename(this.file),
        preview: requests => previewEdits(this.command, this.file, requests, this.cwd),
        commit: (requests, digest) => commitEdits(this.command, this.file, requests, digest, this.cwd) }),
      approve: (approval: EditApproval) => this.services.approve(
        `Apply ${approval.counts.fields} changes to ${approval.counts.entries} entries in ${approval.name}?`,
        ["The exact diff is shown in the Diff pane.", ...approval.warnings].join("\n")),
      post: message => this.post(message), postStaging: () => this.postStaging(),
      reload: () => this.reload(), describeFailure: async error => ({ type: "actionError", message: String(error) }),
    };
  }
  async handle(message: ViewMessage): Promise<void> {
    if (this.busy && ["stageField", "stageType", "unstageField", "discardEntry", "discardAll", "commit", "mutate", "renameKey"].includes(message.type ?? "")) {
      throw new Error("An apply operation is in progress. Finish or cancel it first.");
    }
    switch (message.type) {
      case "ready": case "refresh": return this.reload();
      case "stageField":
        if (message.key && message.field) this.session.stageField(message.key, message.field, message.value ?? null, message.base ?? null);
        break;
      case "stageType":
        if (message.key && message.value && typeof message.base === "string") this.session.stageType(message.key, message.value, message.base);
        break;
      case "unstageField": if (message.key && message.field) this.session.unstageField(message.key, message.field); break;
      case "discardEntry": if (message.key) this.session.discardEntry(message.key); break;
      case "discardAll": this.session.discardAll(); break;
      case "preview": return this.session.preview(this.sessionHost());
      case "commit":
        this.busy = true;
        try { await this.session.commit(this.sessionHost()); } finally { this.busy = false; }
        return;
      case "search": {
        if (!message.query?.trim() && !message.where?.trim()) { this.post({ type: "searchCleared", seq: message.seq }); return; }
        const result = await runSearch(this.command, this.file, { query: message.query ?? "", where: message.where, fuzzy: message.fuzzy }, this.cwd);
        this.post(result.ok ? { type: "searchResult", seq: message.seq, ...result } : { type: "searchError", seq: message.seq, message: result.message });
        return;
      }
      case "mutate": if (message.mutation) await this.mutate(message.mutation); return;
      case "renameKey": if (message.key && message.newKey) await this.mutate({ kind: "renameKey", oldKey: message.key, newKey: message.newKey }); return;
      case "promptAdd": {
        const form = await this.services.prompt("New reference", [
          { name: "key", label: "Citation key", required: true },
          { name: "type", label: "Entry type", choices: this.read?.entrySchemas?.map(schema => schema.entry_type), required: true },
        ]);
        if (form) await this.mutate({ kind: "add", request: { key: form.key, entryType: form.type, fields: {} } });
        return;
      }
      case "promptImport": {
        const form = await this.services.prompt("Import reference — online lookup", [{ name: "identifier", label: "DOI, arXiv ID, ISBN or supported URL", required: true }]);
        if (form) await this.mutate({ kind: "import", request: { identifier: form.identifier } });
        return;
      }
      case "promptGroup": {
        const form = await this.services.prompt("Group membership", [{ name: "group", label: "Group name", required: true }]);
        if (form) await this.mutate({ kind: "groups", keys: message.keys ?? (message.key ? [message.key] : []), group: form.group, member: message.member !== false, create: message.member !== false });
        return;
      }
      case "promptNewGroup": {
        const form = await this.services.prompt("New group", [{ name: "name", label: "Name", required: true }]);
        if (form) await this.mutate({ kind: "groupTree", edit: { op: "add", name: form.name } });
        return;
      }
      case "groupActions": {
        if (!message.group) return;
        const form = await this.services.prompt(`Group: ${message.group.name}`, [
          { name: "action", label: "Action", choices: ["rename", "describe", "move", "remove"], required: true },
          { name: "value", label: "New name, description or parent (blank for top level)" },
        ]);
        if (!form) return;
        const name = message.group.name;
        if (form.action === "rename") await this.mutate({ kind: "groupTree", edit: { op: "rename", name, newName: form.value } });
        if (form.action === "describe") await this.mutate({ kind: "groupTree", edit: { op: "describe", name, description: form.value } });
        if (form.action === "move") await this.mutate({ kind: "groupTree", edit: { op: "move", name, parent: form.value } });
        if (form.action === "remove") await this.mutate({ kind: "groupTree", edit: { op: "remove", name } });
        return;
      }
      case "findDuplicates": {
        const result = await findDuplicates(this.command, this.file, this.cwd);
        this.post(result.ok ? { type: "duplicates", clusters: result.clusters } : { type: "duplicatesError", message: result.message });
        return;
      }
      case "compareRemote": {
        if (!message.key) return;
        const online = await this.services.approve("Look up remote metadata?", "This sends the reference's identifier to its metadata provider.");
        if (!online) { this.post({ type: "compareError", key: message.key, message: "Lookup cancelled." }); return; }
        const result = await compareEntry(this.command, this.file, message.key, true, this.cwd);
        this.post(result.ok ? { type: "compareResult", key: message.key, ...result } : { type: "compareError", key: message.key, message: result.message });
        return;
      }
      case "copyKey": if (message.key) this.services.copy(message.key); return;
      case "cite": this.services.copy(`\\cite{${(message.keys ?? []).join(",")}}`); return;
      case "copyBib": case "exportSelection": return this.export(message.keys ?? [], message.type === "copyBib");
      case "openMaterial": case "openCitation": if (message.path) await this.openReportedPath(message.path); return;
      case "doubleClickEntry": {
        const material = this.read?.materials?.byKey[message.key ?? ""]?.find(item => item.present && item.path?.toLowerCase().endsWith(".pdf"));
        if (material?.path) await this.openReportedPath(material.path);
        return;
      }
      case "reveal": case "openAsText": return this.services.openPath(this.file);
      default: throw new Error(`This desktop version does not support ${message.type ?? "this action"}.`);
    }
    this.postStaging();
  }
  async mutate(mutation: Mutation): Promise<void> {
    if (this.busy) throw new Error("An apply operation is already in progress.");
    // Until all mutation types share a session transaction, require a clean staging set.
    if (this.session.stagedKeys().size) throw new Error("Apply or discard pending field edits before changing entries or groups.");
    const label = describeMutation(mutation);
    this.busy = true;
    try {
      const preview = await previewMutation(this.command, this.file, mutation, this.cwd);
      if (!preview.ok) { this.post({ type: "mutationError", label, message: preview.message }); return; }
      if (!preview.modified) { this.post({ type: "mutationNoop", label, message: "Nothing to change." }); return; }
      if (!preview.sourceSha256) throw new Error(NO_FINGERPRINT_MESSAGE);
      this.post({ type: "diff", entries: [{ key: label, diff: preview.diff, warnings: preview.warnings }] });
      if (!await this.services.approve(approvalTitle(label, mutation, preview), approvalDetail(mutation, preview))) {
        this.post({ type: "mutationCancelled", label }); return;
      }
      const result = await applyMutation(this.command, this.file, mutation, preview.sourceSha256, this.cwd);
      if (!result.ok) { this.post({ type: "mutationError", label, message: result.message }); await this.reload(); return; }
      this.post({ type: "mutationDone", label, warnings: result.warnings, metadataChanged: mutation.kind === "metadata",
        select: mutation.kind === "add" || mutation.kind === "import" ? result.key : undefined,
        renamedKey: mutation.kind === "renameKey" ? { from: mutation.oldKey, to: mutation.newKey } : undefined,
        renamedGroup: mutation.kind === "groupTree" && mutation.edit.op === "rename" ? { from: mutation.edit.name, to: mutation.edit.newName } : undefined });
      await this.reload();
    } finally { this.busy = false; }
  }
  private async export(keys: string[], copy: boolean): Promise<void> {
    if (!keys.length) return;
    if (keys.some(key => this.session.stagedKeys().has(key))) throw new Error("Apply or discard pending edits before exporting them.");
    const form = copy ? { format: "bib" } : await this.services.prompt("Export selection", [{ name: "format", label: "Format", choices: ["bib", "csl-json", "ris", "mods", "endnote", "csv"], required: true }]);
    if (!form) return;
    const result = await exportSelection(this.command, this.file, keys, form.format as SelectionFormat, this.cwd);
    if (result.status !== "success") throw new Error(result.message);
    if (result.warnings.length && !await this.services.approve("Continue export?", result.warnings.map(w => w.message ?? w.type).join("\n"))) return;
    if (copy) this.services.copy(result.content);
    else await this.services.saveExport(result.content, form.format);
  }
  private async openReportedPath(file: string): Promise<void> {
    const paths = new Set<string>();
    for (const items of Object.values(this.read?.materials?.byKey ?? {})) for (const item of items) if (item.present && item.path) paths.add(item.path);
    for (const items of Object.values(this.read?.citations?.byKey ?? {})) for (const item of items) paths.add(item.path);
    if (!paths.has(file)) throw new Error("This path is not an existing material or citation source in the current bibliography.");
    await this.services.openPath(file);
  }
}
