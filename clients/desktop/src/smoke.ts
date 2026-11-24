/** Executable Electron smoke check: real renderer, preload, controller and engine. */
import type { BrowserWindow } from "electron";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import assert from "node:assert/strict";
import type { DesktopDocument } from "./controller";

async function until(window: BrowserWindow, expression: string): Promise<void> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (await window.webContents.executeJavaScript(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Renderer timed out: ${expression}`);
}
export async function smokeTest(
  open: (file: string) => Promise<BrowserWindow>,
  document: (window: BrowserWindow) => DesktopDocument,
  close: (window: BrowserWindow) => void,
  hasPrompt: (window: BrowserWindow) => boolean,
): Promise<void> {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "pynakes-desktop-"));
  const file = path.join(directory, "references.bib");
  await fs.writeFile(file, "@book{Newton1687,\n  title = {Principia},\n  year = {1687}\n}\n@book{Euler1748,\n  title = {Introductio},\n  year = {1748}\n}\n");
  let window: BrowserWindow | undefined;
  try {
    window = await open(file);
    const errors: string[] = [];
    window.webContents.on("console-message", event => { if (event.level === "error") errors.push(event.message); });
    await until(window, 'document.querySelectorAll("#rows tr").length === 2');
    assert.equal(await window.webContents.executeJavaScript('typeof require'), "undefined");
    assert.equal(await window.webContents.executeJavaScript('typeof window.PynakesHost.postMessage'), "function");
    await window.webContents.executeJavaScript('window.PynakesHost.postMessage({type:"stageField",key:"Newton1687",field:"title",value:"Principia revised",base:"Principia"})');
    await until(window, 'window.PV.state.counts.fields === 1');
    await window.webContents.executeJavaScript('window.PynakesHost.postMessage({type:"preview"})');
    await until(window, 'document.body.textContent.includes("Principia revised")');
    await window.webContents.executeJavaScript('window.PynakesHost.postMessage({type:"commit"})');
    await until(window, 'window.PV.state.counts.fields === 0 && window.PV.state.rows.some(row => row.key === "Newton1687" && row.title.includes("revised"))');
    assert.match(await fs.readFile(file, "utf8"), /Principia revised/);
    await window.webContents.executeJavaScript('window.PynakesHost.postMessage({type:"promptAdd"})');
    await until(window, 'document.querySelector("dialog[open]") !== null');
    await window.webContents.executeJavaScript('document.querySelector("dialog").close("cancel")');
    for (let attempt = 0; hasPrompt(window) && attempt < 100; attempt++) await new Promise(resolve => setTimeout(resolve, 20));
    assert.equal(hasPrompt(window), false);
    assert.equal(document(window).session.stagedKeys().size, 0);
    await window.webContents.executeJavaScript('window.PynakesHost.postMessage({type:"promptAdd"})');
    await until(window, 'document.querySelector("dialog[open]") !== null');
    await window.webContents.executeJavaScript('document.querySelector("dialog input[name=key]").value = "Maxwell1865"; document.querySelector("dialog select[name=type]").value = "article"; document.querySelector("dialog button[type=submit]").click()');
    await until(window, 'window.PV.state.rows.some(row => row.key === "Maxwell1865")');
    assert.match(await fs.readFile(file, "utf8"), /Maxwell1865/);
    await fs.writeFile(file, (await fs.readFile(file, "utf8")).replace("Introductio", "External title"));
    await until(window, 'window.PV.state.rows.some(row => row.key === "Euler1748" && row.title.includes("External title"))');
    await window.webContents.executeJavaScript("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
    const image = await window.webContents.capturePage();
    await fs.writeFile(process.env.PYNAKES_SMOKE_SCREENSHOT ?? path.join(os.tmpdir(), "pynakes-desktop.png"), image.toPNG());
    assert.deepEqual(errors, []);
    console.log("Desktop smoke passed: isolated bridge, render, stage, preview, commit, dialog, external refresh.");
  } finally {
    if (window) close(window);
    await fs.rm(directory, { recursive: true, force: true });
  }
}
