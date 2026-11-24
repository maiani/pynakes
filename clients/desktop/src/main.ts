/** Thin Electron host: local resources, windows, dialogs and document lifecycle. */
import { app, BrowserWindow, Menu, dialog, protocol, ipcMain, clipboard, shell } from "electron";
import * as fs from "node:fs/promises";
import { watchFile, unwatchFile } from "node:fs";
import * as path from "node:path";
import { randomBytes, createHash } from "node:crypto";
import { renderShell } from "../../../packages/client-ui/src/shell";
import type { ViewMessage } from "../../../packages/client-core/src/protocol";
import { DesktopDocument, type PromptField } from "./controller";
import { resolveDesktopEngine } from "./engine";

const origin = "pynakes://app";
protocol.registerSchemesAsPrivileged([{ scheme: "pynakes", privileges: { standard: true, secure: true, supportFetchAPI: true } }]);
const windows = new Map<number, { window: BrowserWindow; document: DesktopDocument; cancelPrompt(): void }>();
const openFiles = new Map<string, BrowserWindow>();
const pendingPrompts = new Map<number, { id: string; resolve(value: Record<string, string> | null): void }>();
const smoke = process.argv.includes("--smoke-test");
const closing = new Set<number>();

async function chooseFile(): Promise<void> {
  const result = await dialog.showOpenDialog({ title: "Open bibliography", properties: ["openFile"], filters: [{ name: "Bibliographies", extensions: ["bib"] }] });
  if (!result.canceled && result.filePaths[0]) await openDocument(result.filePaths[0]);
}
async function newFile(): Promise<void> {
  const result = await dialog.showSaveDialog({ title: "New bibliography", defaultPath: "references.bib", filters: [{ name: "BibTeX", extensions: ["bib"] }] });
  if (!result.canceled && result.filePath) {
    // Do not overwrite an existing bibliography, even after the platform's save dialog.
    await fs.writeFile(result.filePath, "", { flag: "wx" });
    await openDocument(result.filePath);
  }
}
function run(action: () => Promise<unknown>): void {
  void action().catch(error => dialog.showErrorBox("Pynakes", String(error)));
}
function installMenu(): void {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    ...(process.platform === "darwin" ? [{ role: "appMenu" as const }] : []),
    { label: "File", submenu: [
      { label: "New bibliography…", accelerator: "CmdOrCtrl+N", click: () => run(newFile) },
      { label: "Open bibliography…", accelerator: "CmdOrCtrl+O", click: () => run(chooseFile) },
      { type: "separator" }, { role: "close" }, { role: "quit" },
    ] },
    { role: "editMenu" },
    { label: "View", submenu: [
      { label: "Refresh bibliography", accelerator: "CmdOrCtrl+R", click: () => {
        const window = BrowserWindow.getFocusedWindow();
        if (window) run(async () => windows.get(window.id)?.document.reload());
      } }, { role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" }, { role: "togglefullscreen" },
      { role: "toggleDevTools" },
    ] },
  ]));
}

async function openDocument(input: string): Promise<BrowserWindow> {
  const file = await fs.realpath(input);
  if (path.extname(file).toLowerCase() !== ".bib") throw new Error("Choose a .bib bibliography.");
  const existing = openFiles.get(file);
  if (existing) { existing.focus(); return existing; }
  const command = await resolveDesktopEngine(__dirname);
  const window = new BrowserWindow({ width: 1360, height: 900, minWidth: 760, minHeight: 520,
    title: `${path.basename(file)} — Pynakes`, show: !smoke,
    webPreferences: { preload: path.join(__dirname, "preload.cjs"), sandbox: true, contextIsolation: true, nodeIntegration: false },
  });
  openFiles.set(file, window);
  const post = (message: Record<string, unknown>) => {
    if (!window.isDestroyed()) window.webContents.send("pynakes:event", message);
  };
  const approve = async (title: string, detail: string): Promise<boolean> => {
    if (smoke) return true;
    const result = await dialog.showMessageBox(window, { type: "question", message: title, detail,
      buttons: ["Cancel", "Apply"], defaultId: 0, cancelId: 0, noLink: true });
    return result.response === 1;
  };
  const prompt = (title: string, fields: PromptField[]): Promise<Record<string, string> | null> => {
    if (pendingPrompts.has(window.id)) throw new Error("Finish the open dialog first.");
    return new Promise(resolve => {
      const id = randomBytes(16).toString("hex");
      pendingPrompts.set(window.id, { id, resolve });
      post({ type: "desktopPrompt", id, title, fields });
    });
  };
  const document = new DesktopDocument(file, command, { post, approve, prompt,
    copy: text => clipboard.writeText(text),
    saveExport: async (content, format) => {
      const chosen = await dialog.showSaveDialog(window, { title: "Export selection", defaultPath: `selection.${format === "csl-json" ? "json" : format}` });
      if (!chosen.canceled && chosen.filePath) {
        if (await fs.realpath(chosen.filePath).catch(() => path.resolve(chosen.filePath!)) === file) throw new Error("Export to a different file to preserve the open bibliography.");
        await fs.writeFile(chosen.filePath, content);
      }
    },
    openPath: async source => {
      if (!await approve("Open this file with its system application?", source)) return;
      const error = await shell.openPath(source);
      if (error) throw new Error(error);
    },
  });
  const cancelPrompt = () => { pendingPrompts.get(window.id)?.resolve(null); pendingPrompts.delete(window.id); };
  windows.set(window.id, { window, document, cancelPrompt });
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", event => event.preventDefault());
  window.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  window.webContents.session.setPermissionCheckHandler(() => false);
  window.on("close", event => {
    if (closing.has(window.id) || !document.hasPending) return;
    event.preventDefault();
    void dialog.showMessageBox(window, { type: "warning", message: "This bibliography has pending edits or an operation in progress.",
      detail: "Return to the editor to apply or discard your edits before closing.", buttons: ["Return to editor"] });
  });
  window.on("closed", () => {
    unwatchFile(file, changed); cancelPrompt(); openFiles.delete(file); windows.delete(window.id); closing.delete(window.id);
  });
  let timer: NodeJS.Timeout | undefined;
  const changed = () => {
    clearTimeout(timer);
    timer = setTimeout(() => { if (!window.isDestroyed()) void document.reload().catch(error => post({ type: "actionError", message: String(error) })); }, 150);
  };
  watchFile(file, { interval: 700, persistent: false }, changed);
  const viewId = createHash("sha256").update(file).digest("hex");
  await window.loadURL(`${origin}/index.html?document=${viewId}`);
  return window;
}

ipcMain.handle("pynakes:request", async (event, value: unknown) => {
  const window = BrowserWindow.fromWebContents(event.sender);
  const url = event.senderFrame?.url;
  if (!window || !url || (new URL(url).protocol !== "pynakes:" || new URL(url).host !== "app") || new URL(url).pathname !== "/index.html" || event.senderFrame !== event.sender.mainFrame) throw new Error("Untrusted request source.");
  const record = windows.get(window.id);
  if (!record || !value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid request.");
  const message = value as Record<string, unknown>;
  if (typeof message.type !== "string") throw new Error("Missing request type.");
  for (const key of ["key", "field", "query", "where", "path", "newKey"]) {
    if (message[key] !== undefined && typeof message[key] !== "string") throw new Error(`Invalid ${key}.`);
  }
  for (const key of ["value", "base"]) {
    if (message[key] !== undefined && message[key] !== null && typeof message[key] !== "string") throw new Error(`Invalid ${key}.`);
  }
  if (message.group !== undefined && (!message.group || typeof message.group !== "object" || typeof (message.group as Record<string, unknown>).name !== "string")) throw new Error("Invalid group.");
  if (message.keys !== undefined && (!Array.isArray(message.keys) || !message.keys.every(key => typeof key === "string"))) throw new Error("Invalid selection.");
  if (message.type === "desktopPromptResult") {
    const pending = pendingPrompts.get(window.id);
    if (!pending || pending.id !== message.id) throw new Error("Unknown dialog.");
    const values = message.values;
    if (values !== null && (typeof values !== "object" || !values || Array.isArray(values) || !Object.values(values).every(value => typeof value === "string"))) throw new Error("Invalid dialog values.");
    pendingPrompts.delete(window.id); pending.resolve(values as Record<string, string> | null); return;
  }
  if (message.type === "desktopOpen") return chooseFile();
  await record.document.handle(message as ViewMessage);
});

async function setup(): Promise<void> {
  protocol.handle("pynakes", async request => {
    const url = new URL(request.url);
    if (url.host !== "app") return new Response("Not found", { status: 404 });
    if (url.pathname === "/index.html") {
      return new Response(renderShell({ asset: (...parts) => `${origin}/${parts.join("/")}`, cspSource: origin,
        nonce: randomBytes(24).toString("base64url"), bridgeScripts: [`${origin}/desktop.js`], themeStyles: [`${origin}/desktop.css`] }), { headers: { "Content-Type": "text/html" } });
    }
    const relative = url.pathname.slice(1);
    if (!/^(ui\/[a-zA-Z]+\.(js|css)|desktop\.(js|css))$/.test(relative)) return new Response("Not found", { status: 404 });
    try {
      return new Response(await fs.readFile(path.join(__dirname, relative)), { headers: { "Content-Type": relative.endsWith(".css") ? "text/css" : "text/javascript" } });
    } catch { return new Response("Not found", { status: 404 }); }
  });
  installMenu();
  if (smoke) {
    const { smokeTest } = await import("./smoke.js");
    await smokeTest(openDocument, window => windows.get(window.id)!.document, window => { closing.add(window.id); window.close(); }, window => pendingPrompts.has(window.id));
    app.quit(); return;
  }
  const files = process.argv.slice(app.isPackaged ? 1 : 2).filter(argument => argument.toLowerCase().endsWith(".bib"));
  if (files.length) for (const file of files) await openDocument(file);
  else { await chooseFile(); if (!windows.size) app.quit(); }
}
app.whenReady().then(setup).catch(error => {
  if (smoke) { console.error(error); app.exit(1); }
  else dialog.showErrorBox("Pynakes could not start", String(error));
});
app.on("open-file", (event, file) => { event.preventDefault(); void app.whenReady().then(() => openDocument(file)).catch(error => dialog.showErrorBox("Pynakes", String(error))); });
app.on("activate", () => { if (!BrowserWindow.getAllWindows().length) run(chooseFile); });
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
