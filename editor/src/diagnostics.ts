/**
 * The engine's findings, published as native diagnostics.
 *
 * Lint findings appear in VS Code's Problems panel (and as squiggles in any
 * text editor showing the same file); undefined citations appear on the `.tex`
 * files that make them. Both collections are replaced on every read and
 * cleared when a read fails or the file closes, so Problems can never report
 * what the view no longer does.
 */

import * as vscode from "vscode";
import {
  citationDiagnostics,
  lintDiagnostics,
  type CitationIndex,
  type LintIndex,
} from "./insights";
import type { LintSeverity } from "./model";

/** Engine finding severities onto VS Code's diagnostic scale. */
const DIAGNOSTIC_SEVERITY: Record<LintSeverity, vscode.DiagnosticSeverity> = {
  error: vscode.DiagnosticSeverity.Error,
  warning: vscode.DiagnosticSeverity.Warning,
  info: vscode.DiagnosticSeverity.Information,
};

export class FindingsPublisher implements vscode.Disposable {
  /** One collection for the whole extension; entries are per `.bib` file. */
  private readonly lint = vscode.languages.createDiagnosticCollection("pynakes");

  /**
   * Undefined citations, published against the `.tex` files that make them.
   *
   * A separate collection from the lint findings because it describes different
   * files: a citation with no entry behind it is a problem in the source that
   * cites it, so that is where the squiggle belongs. Keeping it separate also
   * means clearing one can never silently drop the other.
   */
  private readonly citations = vscode.languages.createDiagnosticCollection("pynakes-citations");

  /**
   * What each open bibliography published, by `.tex` path.
   *
   * Two bibliographies can be open at once, and both can be cited by the same
   * source. Each one's diagnostics are kept apart so that re-reading (or
   * closing) one replaces only its own, and a source cited by both shows the
   * findings of both.
   */
  private readonly citationsByDocument = new Map<string, Map<string, vscode.Diagnostic[]>>();

  /** Withdraw everything published for this document. */
  clear(document: vscode.TextDocument): void {
    this.lint.delete(document.uri);
    this.replaceCitations(document, new Map());
  }

  /** Replace one bibliography's citation diagnostics, re-merging every source they touch. */
  private replaceCitations(
    document: vscode.TextDocument,
    next: Map<string, vscode.Diagnostic[]>,
  ): void {
    const id = document.uri.toString();
    const touched = new Set([...(this.citationsByDocument.get(id)?.keys() ?? []), ...next.keys()]);
    if (next.size > 0) {
      this.citationsByDocument.set(id, next);
    } else {
      this.citationsByDocument.delete(id);
    }
    for (const texPath of touched) {
      const merged = [...this.citationsByDocument.values()].flatMap(
        (byPath) => byPath.get(texPath) ?? [],
      );
      const uri = vscode.Uri.file(texPath);
      if (merged.length > 0) {
        this.citations.set(uri, merged);
      } else {
        this.citations.delete(uri);
      }
    }
  }

  /**
   * Publish (or withdraw) one file's findings as native diagnostics.
   *
   * The same `pynakes.showFindings` setting that gates the in-view markers
   * gates Problems, so the two can never disagree. Ranges are whole lines:
   * the engine locates a finding at its entry's declaration, which is all a
   * squiggle needs to be useful.
   */
  publishLint(document: vscode.TextDocument, lint: LintIndex | null, showFindings: boolean): void {
    if (!showFindings || !lint) {
      this.lint.delete(document.uri);
      return;
    }
    // Clamp rather than trust: the buffer may have moved on since the engine
    // read its mirror, and `lineAt` would throw on a stale out-of-range line.
    const lastLine = Math.max(0, document.lineCount - 1);
    const diagnostics = lintDiagnostics(lint.issues).map((item) => {
      const line = Math.min(item.line, lastLine);
      const diagnostic = new vscode.Diagnostic(
        document.lineAt(line).range,
        item.message,
        DIAGNOSTIC_SEVERITY[item.severity],
      );
      diagnostic.source = "pynakes";
      diagnostic.code = item.code;
      return diagnostic;
    });
    this.lint.set(document.uri, diagnostics);
  }

  /**
   * Publish (or withdraw) undefined citations as diagnostics on the `.tex`
   * files that make them.
   *
   * Gated by the same `pynakes.showFindings` setting as the lint findings: both
   * are advisory validation, and a user who turned findings off did not ask for
   * one kind to keep reporting. Everything this bibliography published is
   * replaced on every read, so a citation that has since been resolved cannot
   * linger — and nothing another open bibliography published is touched.
   */
  publishCitations(
    document: vscode.TextDocument,
    citations: CitationIndex | null,
    showFindings: boolean,
  ): void {
    const next = new Map<string, vscode.Diagnostic[]>();
    if (!showFindings || !citations) {
      this.replaceCitations(document, next);
      return;
    }
    for (const file of citationDiagnostics(citations)) {
      const diagnostics = file.items.map((item) => {
        const start = new vscode.Position(item.line, item.column);
        const diagnostic = new vscode.Diagnostic(
          new vscode.Range(start, start.translate(0, item.length)),
          item.message,
          vscode.DiagnosticSeverity.Warning,
        );
        diagnostic.source = "pynakes";
        diagnostic.code = "undefined-citation";
        return diagnostic;
      });
      next.set(file.path, diagnostics);
    }
    this.replaceCitations(document, next);
  }

  dispose(): void {
    this.citationsByDocument.clear();
    this.lint.dispose();
    this.citations.dispose();
  }
}
