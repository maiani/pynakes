/** Real engine transactions through the VS Code session adapter. */
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { test } from "node:test";
import { BibliographySession } from "../../../../packages/client-core/src/session";
import { command, engineSkipReason, tempBib } from "./engine";
import type { StagingHost } from "../vscode/stagedCommit";

const skip = engineSkipReason();
let approve: () => Promise<string | undefined> = async () => "Apply";
const dialogs: string[] = [];
Object.assign(require("vscode"), {
  workspace: {
    getConfiguration: () => ({ get: (name: string) =>
      name === "executable" ? command.executable : name === "executableArgs" ? command.leadingArgs : undefined }),
    getWorkspaceFolder: () => undefined,
  },
  window: { showWarningMessage: async (title: string) => { dialogs.push(title); return approve(); } },
});
const { sessionHost } = require("../vscode/stagedCommit") as typeof import("../vscode/stagedCommit");

const ORIGINAL = "@book{Newton1687,\n  title = {Old title}\n}\n";
function fixture() {
  const file = tempBib(ORIGINAL);
  const session = new BibliographySession();
  session.stageField("Newton1687", "title", "Principia", "Old title");
  const events: Record<string, unknown>[] = [];
  let reloads = 0;
  const host: StagingHost = {
    document: { uri: { scheme: "file", fsPath: file } } as unknown as StagingHost["document"],
    post: event => { events.push(event); },
    postStaging: () => {},
    stagedKeys: () => session.stagedKeys(),
    reconcileBuffer: async () => true,
    workingDirectory: () => path.dirname(file),
    onlineLookupsAllowed: () => false,
    reload: async () => { reloads++; },
    describeFailure: async error => ({ type: "actionError", message: String(error) }),
    withMirror: body => body({ command, source: file, cwd: path.dirname(file) }),
  };
  dialogs.length = 0;
  approve = async () => "Apply";
  return { file, session, host, events, reloads: () => reloads };
}

test("the VS Code adapter approves a session diff and applies the real guarded batch", { skip }, async () => {
  const { file, session, host, events, reloads } = fixture();
  await session.commit(sessionHost(host));
  assert.deepEqual(events.map(event => event.type), ["diff", "committed"]);
  assert.match(dialogs[0], /Apply 1 change to 1 entry in/);
  assert.equal(fs.readFileSync(file, "utf8"), ORIGINAL.replace("Old title", "Principia"));
  assert.equal(session.stagedKeys().size, 0);
  assert.equal(reloads(), 1);
});

test("a disk edit during approval is preserved and pending session edits survive", { skip }, async () => {
  const { file, session, host, events } = fixture();
  const external = ORIGINAL.replace("Old title", "External edit");
  approve = async () => { fs.writeFileSync(file, external); return "Apply"; };
  await session.commit(sessionHost(host));
  assert.equal(fs.readFileSync(file, "utf8"), external);
  assert.equal(events.at(-1)?.type, "conflict");
  assert.equal(session.stagedKeys().size, 1);
});

test("the adapter previews the supplied dirty-buffer mirror without writing the document", { skip }, async () => {
  const { file, session, host, events } = fixture();
  const mirror = tempBib(ORIGINAL.replace("Old title", "Buffer title"));
  host.withMirror = body => body({ command, source: mirror });
  await session.preview(sessionHost(host));
  const diff = (events[0].entries as { diff: string }[])[0].diff;
  assert.match(diff, /Buffer title/);
  assert.match(diff, /Principia/);
  assert.equal(fs.readFileSync(file, "utf8"), ORIGINAL);
  assert.equal(dialogs.length, 0);
});

test("unreconciled and nonlocal documents never reach a session approval", { skip }, async () => {
  for (const local of [true, false]) {
    const { file, session, host, events } = fixture();
    if (local) host.reconcileBuffer = async () => false;
    else Object.assign(host.document.uri, { scheme: "untitled" });
    await session.commit(sessionHost(host));
    assert.equal(events.at(-1)?.type, "commitError");
    assert.equal(dialogs.length, 0);
    assert.equal(fs.readFileSync(file, "utf8"), ORIGINAL);
    assert.equal(session.stagedKeys().size, 1);
  }
});

test("mirror failure is reported once by the session without blanking the view", { skip }, async () => {
  const { session, host, events } = fixture();
  host.withMirror = async (_body, reportFailure) => {
    reportFailure!({ message: "Unable to read buffer" });
  };
  await session.preview(sessionHost(host));
  assert.equal(events.length, 1);
  assert.equal(events[0].type, "commitError");
  assert.match(String(events[0].message), /Unable to read buffer/);
});
