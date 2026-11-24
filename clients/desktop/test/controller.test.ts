import test from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { DesktopDocument, type DesktopServices } from "../src/controller";

const source = "@book{Newton1687,\n  title = {Principia},\n  year = {1687}\n}\n";
const command = { executable: process.env.PYNAKES_TEST_PYTHON ?? "python3", leadingArgs: ["-m", "pynakes"] };
process.env.PYTHONPATH = path.resolve(__dirname, "../../../../src");
async function fixture(action: (document: DesktopDocument, services: DesktopServices, messages: Record<string, unknown>[]) => Promise<void>) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "pynakes-desktop-test-"));
  const file = path.join(directory, "references.bib");
  await fs.writeFile(file, source);
  const messages: Record<string, unknown>[] = [];
  const services: DesktopServices = { post: message => messages.push(message), approve: async () => true,
    prompt: async () => null, copy: () => {}, saveExport: async () => {}, openPath: async () => { throw new Error("Unexpected file open"); } };
  try { await action(new DesktopDocument(file, command, services), services, messages); }
  finally { await fs.rm(directory, { recursive: true, force: true }); }
}
const stage = { type: "stageField", key: "Newton1687", field: "title", value: "Revised Principia", base: "Principia" };
test("loads, searches, previews and applies through the shared engine", async () => fixture(async (document, services, messages) => {
  await document.reload();
  assert.equal(document.read?.rows[0].key, "Newton1687");
  await document.handle({ type: "search", query: "Principia", seq: 1 });
  assert.deepEqual(messages.find(message => message.type === "searchResult")?.keys, ["Newton1687"]);
  await document.handle(stage);
  await document.handle({ type: "preview" });
  assert.equal(await fs.readFile(document.file, "utf8"), source);
  assert.ok(messages.some(message => message.type === "diff"));
  await document.handle({ type: "commit" });
  assert.match(await fs.readFile(document.file, "utf8"), /Revised Principia/);
  assert.equal(document.hasPending, false);
  let copied = ""; services.copy = text => { copied = text; };
  await document.handle({ type: "copyBib", keys: ["Newton1687"] });
  assert.match(copied, /Revised Principia/);
}));
test("cancelled apply retains staging and leaves bytes untouched", async () => fixture(async (document, services) => {
  services.approve = async () => false;
  await document.handle(stage);
  await document.handle({ type: "commit" });
  assert.equal(await fs.readFile(document.file, "utf8"), source);
  assert.equal(document.hasPending, true);
  await assert.rejects(document.mutate({ kind: "renameKey", oldKey: "Newton1687", newKey: "Newton" }), /pending field edits/);
}));
test("external edit during approval is preserved", async () => fixture(async (document, services, messages) => {
  const external = source.replace("1687}", "1688}");
  services.approve = async () => { await fs.writeFile(document.file, external); return true; };
  await document.handle(stage);
  await document.handle({ type: "commit" });
  assert.equal(await fs.readFile(document.file, "utf8"), external);
  assert.equal(document.hasPending, true);
  assert.ok(messages.some(message => ["commitError", "conflict"].includes(String(message.type))));
}));
test("entry mutations require approval and reject unknown material paths", async () => fixture(async (document, services) => {
  services.approve = async () => false;
  await document.mutate({ kind: "renameKey", oldKey: "Newton1687", newKey: "Newton" });
  assert.equal(await fs.readFile(document.file, "utf8"), source);
  services.approve = async () => true;
  await document.mutate({ kind: "renameKey", oldKey: "Newton1687", newKey: "Newton" });
  assert.match(await fs.readFile(document.file, "utf8"), /@book\{Newton,/);
  await assert.rejects(document.handle({ type: "openMaterial", path: "/tmp/unrelated" }), /not an existing material/);
}));
