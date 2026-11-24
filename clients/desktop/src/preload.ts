/** Narrow bridge only; Electron and IPC event objects never enter the web UI. */
import { contextBridge, ipcRenderer } from "electron";
const listeners = new Set<(message: unknown) => void>();
ipcRenderer.on("pynakes:event", (_event, message: unknown) => {
  for (const listener of listeners) listener(message);
});
const stateKey = `pynakes-view:${location.search}`;
contextBridge.exposeInMainWorld("PynakesHost", {
  postMessage: (message: unknown) => {
    void ipcRenderer.invoke("pynakes:request", message).catch(error => {
      for (const listener of listeners) listener({ type: "actionError", message: String(error) });
    });
  },
  getState: () => { try { return JSON.parse(localStorage.getItem(stateKey) ?? "null"); } catch { return null; } },
  setState: (state: unknown) => { localStorage.setItem(stateKey, JSON.stringify(state)); },
  onMessage: (handler: (message: unknown) => void) => {
    listeners.add(handler);
    return () => { listeners.delete(handler); };
  },
});
