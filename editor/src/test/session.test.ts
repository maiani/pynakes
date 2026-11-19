/** Session behavior without VS Code, files, child processes, or a browser. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { BibliographySession, type SessionHost, type EditTarget } from "../core/session";
import type { PreviewResult } from "../core/library";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function fixture() {
  const session = new BibliographySession();
  session.stageField("Newton1687", "title", "Principia", "Old title");
  const events: Record<string, unknown>[] = [];
  const order: string[] = [];
  const preview: Extract<PreviewResult, { ok: true }> = {
    ok: true, entries: [{ key: "Newton1687", plan: {
      key: "Newton1687", change: "modified", fields: { title: { old: "Old title", new: "Principia" } },
    } }], diff: "-Old title\n+Principia", warnings: [], sourceSha256: "snapshot-digest",
  };
  const target: EditTarget = {
    name: "refs.bib",
    preview: async () => { order.push("preview"); return preview; },
    commit: async (requests, digest) => {
      order.push("write");
      assert.equal(digest, "snapshot-digest");
      assert.equal(requests[0].set?.title, "Principia");
      return { ok: true, applied: ["Newton1687"], warnings: [] };
    },
  };
  const host: SessionHost = {
    preview: requests => target.preview(requests),
    prepareWrite: async () => { order.push("reconcile"); return target; },
    approve: async approval => {
      order.push("approve");
      assert.equal(events.at(-1)?.type, "diff");
      assert.equal(approval.diff, preview.diff);
      return true;
    },
    post: event => { events.push(event); },
    postStaging: () => { order.push("staging"); },
    reload: async () => { order.push("reload"); },
    describeFailure: async error => ({ type: "actionError", message: String(error) }),
  };
  return { session, host, target, preview, events, order };
}

test("a host-free session reconciles, shows the approved diff, and writes with its digest", async () => {
  const { session, host, events, order } = fixture();
  await session.commit(host);
  assert.deepEqual(order, ["reconcile", "preview", "approve", "write", "staging", "reload"]);
  assert.deepEqual(events.map(event => event.type), ["diff", "committed"]);
  assert.equal(session.stagedKeys().size, 0);
});

test("session snapshots cannot mutate pending edits", () => {
  const { session } = fixture();
  session.snapshot().entries.Newton1687.fields.title.value = "Changed outside";
  assert.equal(session.snapshot().entries.Newton1687.fields.title.value, "Principia");
});

test("refused reconciliation and missing fingerprints never reach approval or write", async () => {
  for (const reason of ["dirty", "digest"] as const) {
    const { session, host, preview, events, order } = fixture();
    if (reason === "dirty") host.prepareWrite = async () => ({ error: "Unsaved changes" });
    else delete preview.sourceSha256;
    await session.commit(host);
    assert.equal(events.at(-1)?.type, "commitError");
    assert.ok(!order.includes("approve") && !order.includes("write"));
    assert.equal(session.stagedKeys().size, 1);
  }
});

test("base conflicts reload current values without asking for approval", async () => {
  const { session, host, preview, events, order } = fixture();
  preview.entries[0].plan!.fields!.title.old = "Someone else's title";
  await session.commit(host);
  assert.equal(events.at(-1)?.type, "conflict");
  assert.deepEqual(order, ["reconcile", "preview", "reload"]);
  assert.equal(session.stagedKeys().size, 1);
});

test("declining approval preserves all staged changes", async () => {
  const { session, host, events, order } = fixture();
  host.approve = async () => false;
  await session.commit(host);
  assert.equal(events.at(-1)?.type, "commitCancelled");
  assert.ok(!order.includes("write"));
  assert.equal(session.stagedKeys().size, 1);
});

test("a new edit or discard during approval invalidates the pending write", async () => {
  for (const discard of [false, true]) {
    const { session, host, events, order } = fixture();
    host.approve = async () => {
      if (discard) session.discardAll();
      else session.stageField("Newton1687", "year", "1687", null);
      return true;
    };
    await session.commit(host);
    assert.ok(!order.includes("write"));
    assert.match(String(events.at(-1)?.message), /Pending edits changed/);
    assert.equal(session.stagedKeys().size, discard ? 0 : 1);
    if (!discard) assert.equal(session.snapshot().entries.Newton1687.fields.year.value, "1687");
  }
});

test("editing during reconciliation or preview also invalidates the pending approval", async () => {
  for (const phase of ["reconcile", "preview"]) {
    const { session, host, target, preview, order } = fixture();
    const change = () => session.stageType("Newton1687", "article", "book");
    if (phase === "reconcile") host.prepareWrite = async () => { change(); return target; };
    else target.preview = async () => { change(); return preview; };
    await session.commit(host);
    assert.ok(!order.includes("approve") && !order.includes("write"));
    assert.equal(session.snapshot().entries.Newton1687.entryType?.value, "article");
  }
});

test("concurrent Apply requests share a session lock and cannot duplicate a write", async () => {
  const { session, host, order, events } = fixture();
  const approval = deferred<boolean>();
  const asked = deferred<void>();
  host.approve = () => { asked.resolve(); return approval.promise; };
  const first = session.commit(host);
  await asked.promise;
  await session.commit(host);
  assert.match(String(events.at(-1)?.message), /already in progress/);
  approval.resolve(true);
  await first;
  assert.equal(order.filter(step => step === "write").length, 1);
});

test("a guarded write refuses concurrent staging explicitly and releases the lock after failure", async () => {
  const { session, host, target } = fixture();
  target.commit = async () => {
    assert.throws(() => session.discardAll(), /write is in progress/);
    assert.throws(() => session.stageField("Other", "year", "1900", null), /write is in progress/);
    throw new Error("engine unavailable");
  };
  await session.commit(host);
  assert.equal(session.stagedKeys().size, 1);
  session.discardAll();
  session.stageField("Other", "year", "1900", null);
  assert.deepEqual([...session.stagedKeys()], ["Other"]);
});

test("external modifications and engine refusals preserve staging and reload", async () => {
  for (const conflict of [true, false]) {
    const { session, host, target, events, order } = fixture();
    target.commit = async () => ({ ok: false, conflict, error: conflict ? "ExternalModification" : "ValidationError", message: "refused" });
    await session.commit(host);
    assert.equal(events.at(-1)?.type, conflict ? "conflict" : "commitError");
    assert.equal(session.stagedKeys().size, 1);
    assert.equal(order.at(-1), "reload");
  }
});

test("stale previews and their failures cannot replace the current diff", async () => {
  for (const fail of [false, true]) {
    const { session, host, preview, events } = fixture();
    const old = deferred<PreviewResult>();
    host.preview = () => old.promise;
    const pending = session.preview(host);
    session.stageField("Newton1687", "year", "1687", null);
    host.preview = async () => preview;
    await session.preview(host);
    if (fail) old.reject(new Error("old failure"));
    else old.resolve({ ...preview, diff: "stale diff" });
    await pending;
    assert.equal(events.length, 1);
    assert.equal(events[0].type, "diff");
  }
});
