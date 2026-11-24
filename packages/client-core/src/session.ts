/** A document's staged-edit session, independent of UI, filesystem and transport. */
import type { PreviewResult, CommitResult } from "./library";
import type { RefEditRequest } from "./engine/pynakes";
import { FILE_MOVED_MESSAGE, NO_FINGERPRINT_MESSAGE } from "./writeErrors";
import { own } from "./records";
import {
  emptyStaging, stageField, stageType, unstageField, discardEntry,
  stagedCount, isEmpty, toRequests, diffHeading, findConflicts,
  type StagingState, type StagingConflict,
} from "./staging";

/** A reconciled document and engine, bound together for the entire transaction. */
export interface EditTarget {
  name: string;
  preview(requests: RefEditRequest[]): Promise<PreviewResult>;
  commit(requests: RefEditRequest[], sourceSha256: string): Promise<CommitResult>;
}

export interface EditApproval {
  name: string;
  counts: ReturnType<typeof stagedCount>;
  diff: string;
  warnings: string[];
}

/** Host capabilities supplied per operation; a session can outlive any one view. */
export interface SessionHost {
  /** Read the current buffer, including unsaved edits; release temporary sources on failure. */
  preview(requests: RefEditRequest[]): Promise<PreviewResult>;
  /** Reconcile buffer/disk and resolve an engine before returning the write target. */
  prepareWrite(): Promise<EditTarget | { error: string }>;
  approve(approval: EditApproval): Promise<boolean>;
  post(message: Record<string, unknown>): void;
  postStaging(): void;
  reload(): Promise<void>;
  describeFailure(error: unknown): Promise<Record<string, unknown>>;
}

const STAGING_CHANGED = "Pending edits changed during review. Nothing was written; preview and apply again.";

/** A staging operation refused while the engine is writing the approved batch. */
export class SessionBusyError extends Error {}

export class BibliographySession {
  private state = emptyStaging();
  private revision = 0;
  private previewGeneration = 0;
  private committing = false;
  private writing = false;

  /** Detached presentation snapshot: callers cannot mutate session state. */
  snapshot(): StagingState { return structuredClone(this.state); }

  stagedKeys(): Set<string> { return new Set(Object.keys(this.state.entries)); }

  private change(edit: (state: StagingState) => void): void {
    // Once the guarded write starts, changing the base would need a new read.
    // Reject explicitly instead of silently losing or rebasing a concurrent edit.
    if (this.writing) throw new SessionBusyError("A write is in progress. Wait for it to finish before changing pending edits.");
    edit(this.state);
    this.revision++;
    this.previewGeneration++;
  }

  stageField(key: string, field: string, value: string | null, base: string | null): void {
    this.change(state => { stageField(state, key, field, value, base); });
  }
  stageType(key: string, value: string, base: string): void {
    this.change(state => { stageType(state, key, value, base); });
  }
  unstageField(key: string, field: string): void {
    this.change(state => { unstageField(state, key, field); });
  }
  discardEntry(key: string): void {
    this.change(state => { discardEntry(state, key); });
  }
  discardAll(): void {
    this.change(() => { this.state = emptyStaging(); });
  }

  private showDiff(host: SessionHost, requests: RefEditRequest[], result: Extract<PreviewResult, { ok: true }>): void {
    host.post({ type: "diff", entries: [{
      key: diffHeading(requests.map(request => request.key)),
      diff: result.diff, warnings: result.warnings,
    }] });
  }

  async preview(host: SessionHost): Promise<void> {
    // A separate preview must not replace the diff currently awaiting approval.
    if (this.committing) return;
    const generation = ++this.previewGeneration;
    const requests = toRequests(this.state);
    if (requests.length === 0) {
      host.post({ type: "diff", entries: [] });
      return;
    }
    try {
      const result = await host.preview(requests);
      if (generation !== this.previewGeneration) return;
      if (!result.ok) {
        host.post({ type: "commitError", message: `Preview failed: ${result.message}` });
        return;
      }
      this.showDiff(host, requests, result);
    } catch (error) {
      if (generation !== this.previewGeneration) return;
      const failure = await host.describeFailure(error);
      if (generation !== this.previewGeneration) return;
      host.post({ type: "commitError", message: `Preview failed: ${String(failure.message ?? "the engine could not run")}` });
    }
  }

  /** Reconcile → preview → base conflict check → approval → one guarded batch. */
  async commit(host: SessionHost): Promise<void> {
    if (this.committing) {
      host.post({ type: "commitError", message: "An apply operation is already in progress for this bibliography." });
      return;
    }
    if (isEmpty(this.state)) return;
    this.committing = true;
    this.previewGeneration++;
    const revision = this.revision;
    const state = this.snapshot();
    const requests = toRequests(state);
    const changed = (): boolean => {
      if (revision === this.revision) return false;
      host.post({ type: "commitError", message: STAGING_CHANGED });
      return true;
    };
    try {
      const target = await host.prepareWrite();
      if (changed()) return;
      if ("error" in target) {
        host.post({ type: "commitError", message: target.error });
        return;
      }
      const preview = await target.preview(requests);
      if (changed()) return;
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
        if (staged) conflicts.push(...findConflicts(staged, entry.plan));
      }
      if (conflicts.length > 0) {
        host.post({ type: "conflict", conflicts, message:
          "The file changed since these edits were made. Nothing was written — review the current values and edit again." });
        await host.reload();
        return;
      }
      this.showDiff(host, requests, preview);
      const approved = await host.approve({ name: target.name, counts: stagedCount(state), diff: preview.diff, warnings: preview.warnings });
      if (changed()) return;
      if (!approved) {
        host.post({ type: "commitCancelled" });
        return;
      }
      this.writing = true;
      const result = await target.commit(requests, sourceSha256);
      if (!result.ok) {
        if (result.conflict && result.error === "ExternalModification") {
          host.post({ type: "conflict", conflicts: [], message: FILE_MOVED_MESSAGE });
        } else {
          host.post({ type: "commitError", message: `Nothing was written: ${result.message}` });
        }
      } else {
        this.state = emptyStaging();
        this.revision++;
        host.post({ type: "committed", applied: result.applied, warnings: result.warnings });
      }
      this.writing = false;
      host.postStaging();
      await host.reload();
    } catch (error) {
      host.post(await host.describeFailure(error));
    } finally {
      this.writing = false;
      this.committing = false;
    }
  }
}
