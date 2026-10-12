/**
 * The status bar item that names the engine and summarizes the file.
 *
 * File and engine details are shown in VS Code's status bar rather than inside
 * the view: it is ambient information, rarely read, and a permanent row of the
 * editor is too much space for it. One item is shared by every view and
 * re-pointed at whichever one is active.
 */

import * as path from "node:path";
import * as vscode from "vscode";
import type { Summary } from "./model";

/** What the status bar item reports about one open bibliography. */
export interface StatusDetails {
  summary: Summary;
  findings?: { errors: number; warnings: number; info: number; total: number };
  engine: { version?: string; source: string; reason: string };
  dirty: boolean;
}

export class EngineStatusBar implements vscode.Disposable {
  /** Every open panel, so a closing one can hand the item to a sibling. */
  private readonly openPanels = new Set<vscode.WebviewPanel>();
  private readonly byPanel = new WeakMap<vscode.WebviewPanel, StatusDetails>();

  constructor(private readonly item: vscode.StatusBarItem) {}

  /** Start tracking a panel; it has no details until its first read. */
  track(panel: vscode.WebviewPanel): void {
    this.openPanels.add(panel);
  }

  /** Stop tracking a closed panel, handing the item to a sibling if one is active. */
  forget(panel: vscode.WebviewPanel): void {
    this.openPanels.delete(panel);
    this.byPanel.delete(panel);
    this.repoint();
  }

  /** Record what one panel's latest read reported, and show it if it is active. */
  update(panel: vscode.WebviewPanel, details: StatusDetails): void {
    this.byPanel.set(panel, details);
    this.sync(panel);
  }

  /** Point the shared item at this view, or hide it. */
  sync(panel: vscode.WebviewPanel): void {
    const details = this.byPanel.get(panel);
    if (!panel.active || !details) {
      this.item.hide();
      return;
    }
    const engine = details.engine;
    this.item.text = engine.version ? `$(book) pynakes ${engine.version}` : "$(book) pynakes";
    this.item.tooltip = buildTooltip(details);
    this.item.show();
  }

  dispose(): void {
    this.item.dispose();
  }

  /**
   * Hand the item to whichever other bibliography view is active, or hide it
   * when there is none — a closing panel must not blank the item a sibling
   * view is still using.
   */
  private repoint(): void {
    for (const panel of this.openPanels) {
      if (panel.active && this.byPanel.get(panel)) {
        this.sync(panel);
        return;
      }
    }
    this.item.hide();
  }
}

/**
 * Escape Markdown in text that comes from the file or its path.
 *
 * Citation keys, entry types and file names are the file's own text; left
 * unescaped, a duplicate key spelled as a Markdown link would render as one.
 */
export function escapeMarkdown(text: string): string {
  return text.replace(/[\\`*_{}[\]()#+\-.!|<>~&]/g, "\\$&");
}

/** The detail that used to occupy a row of the view, now one hover away. */
export function buildTooltip(details: StatusDetails): vscode.MarkdownString {
  const { summary, findings, engine } = details;
  const lines: string[] = [`**${escapeMarkdown(path.basename(summary.file))}**`, ""];

  const entries = `${summary.entryCount} ${summary.entryCount === 1 ? "entry" : "entries"}`;
  const types = summary.typeCounts
    .slice(0, 4)
    .map(([type, count]) => `${count} ${escapeMarkdown(type)}`)
    .join(", ");
  lines.push(types ? `${entries} — ${types}` : entries);

  if (findings && findings.total > 0) {
    lines.push(
      `${findings.total} findings — ${findings.errors} error, ` +
        `${findings.warnings} warning, ${findings.info} info`,
    );
  }
  if (summary.duplicateKeys.length > 0) {
    const names = summary.duplicateKeys
      .map(([key, count]) => `${escapeMarkdown(key)} (${count})`)
      .join(", ");
    lines.push(`Duplicate keys: ${names}`);
  }
  if (summary.stringCount > 0) {
    lines.push(`${summary.stringCount} \`@string\` definitions`);
  }

  const namespaces = [
    summary.jabrefKeys.length > 0 ? "jabref-meta" : null,
    summary.pynakesKeys.length > 0 ? "pynakes-meta" : null,
  ].filter(Boolean);
  if (namespaces.length > 0) {
    lines.push(`Metadata: ${namespaces.join(", ")}`);
  }

  lines.push(`Encoding: ${summary.encoding}, ${summary.lineEnding.toUpperCase()} line endings`);
  if (details.dirty) {
    lines.push("_Reading the unsaved buffer, not the file on disk._");
  }
  lines.push("", `Engine: **${engine.source}**. ${escapeMarkdown(engine.reason)}`);
  lines.push("", "Click to re-read the file.");

  // Not trusted: nothing here is a command link, and the text includes the
  // file's own keys and types, which must never be able to become one.
  const tooltip = new vscode.MarkdownString(lines.join("\n\n"));
  tooltip.isTrusted = false;
  return tooltip;
}
