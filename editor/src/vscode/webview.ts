/** VS Code resource and security adapter for the shared UI. */
import { randomBytes } from "node:crypto";
import * as vscode from "vscode";
import { renderShell as sharedShell } from "../core/shell";

export function renderShell(webview: vscode.Webview, extensionUri: vscode.Uri): string {
  const asset = (...parts: string[]): string => String(webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, ...parts)));
  return sharedShell({ asset, cspSource: webview.cspSource, nonce: randomBytes(24).toString("base64url"),
    bridgeScripts: [asset("media", "vscode.js")], themeStyles: [asset("media", "vscode.css")] });
}
