/**
 * Citing entries in a manuscript: inserting keys from the view, and
 * completing them inside a `\cite{...}` in a TeX source.
 *
 * Both draw on what the open views last read — their entries, and the TeX
 * sources the engine scanned for each — so neither runs the engine per
 * keystroke. What counts as a citation comes from the engine's
 * `citation_grammar`, fetched once per engine; see `citeContext.ts`. Inserting
 * edits the TeX buffer, never the file on disk, so it is the editor's own
 * undoable change and nothing about it needs an approval.
 */

import * as path from "node:path";
import * as vscode from "vscode";
import {
  findCitationContext,
  isCitationMacro,
  planCitationInsertion,
  type CitationGrammar,
} from "./citeContext";
import { resolveEngine } from "./engineDiscovery";
import type { CitationIndex } from "./insights";
import type { EntryRow } from "./model";
import { citationGrammar, describeCommand } from "./pynakes";

/** Documents treated as TeX sources: by language mode, or by extension when none is set. */
const TEX_LANGUAGES = new Set(["latex", "tex", "plaintex", "context", "latex-expl3", "doctex"]);
const TEX_SELECTOR: vscode.DocumentSelector = [
  ...[...TEX_LANGUAGES].map((language) => ({ language })),
  { pattern: "**/*.{tex,ltx}" },
];

export function isTexDocument(document: vscode.TextDocument): boolean {
  return TEX_LANGUAGES.has(document.languageId) || /\.(tex|ltx)$/i.test(document.fileName);
}

/** What one open view last read, as far as citing needs it. */
interface CitableLibrary {
  uri: vscode.Uri;
  rows: EntryRow[];
  /** The TeX sources the engine read for it, normalized for comparison. */
  sources: Set<string>;
}

/** Where a TeX editor's cursor was when it last had focus. */
interface CitationTarget {
  uri: vscode.Uri;
  selection: vscode.Selection;
}

/** The outcome of an insertion, for the caller to follow up on. */
export interface CitedResult {
  target: vscode.Uri;
  added: string[];
  /** False when the library does not list this source, so the citation will not count. */
  linked: boolean;
}

export class CitationService implements vscode.Disposable {
  private readonly libraries = new Map<string, CitableLibrary>();
  private readonly grammars = new Map<string, Promise<CitationGrammar | null>>();
  private lastTarget: CitationTarget | undefined;
  private readonly subscriptions: vscode.Disposable[];

  constructor() {
    const remember = (editor: vscode.TextEditor | undefined): void => {
      if (editor && isTexDocument(editor.document)) {
        this.lastTarget = { uri: editor.document.uri, selection: editor.selection };
      }
    };
    remember(vscode.window.activeTextEditor);
    this.subscriptions = [
      vscode.window.onDidChangeActiveTextEditor(remember),
      vscode.window.onDidChangeTextEditorSelection((event) => remember(event.textEditor)),
      vscode.languages.registerCompletionItemProvider(
        TEX_SELECTOR,
        { provideCompletionItems: (document, position) => this.complete(document, position) },
        "{",
        ",",
      ),
      vscode.commands.registerCommand("pynakes.insertCitation", () => this.pickAndInsert()),
    ];
  }

  dispose(): void {
    for (const subscription of this.subscriptions) {
      subscription.dispose();
    }
  }

  // -- what the views know --------------------------------------------------

  /** Record what a view of `document` just read. */
  update(document: vscode.TextDocument, rows: EntryRow[], citations: CitationIndex | null): void {
    this.libraries.set(document.uri.toString(), {
      uri: document.uri,
      rows,
      sources: new Set((citations?.sources ?? []).map(normalizePath)),
    });
    // Fetched ahead of the first completion, which should not wait on a process.
    void this.grammarFor(document.uri);
  }

  /** Forget a library whose last view closed. */
  forget(document: vscode.TextDocument): void {
    this.libraries.delete(document.uri.toString());
  }

  /** True when the library behind `bib` reads `tex` for its citations. */
  isLinked(bib: vscode.Uri, tex: vscode.Uri): boolean {
    return this.libraries.get(bib.toString())?.sources.has(normalizePath(tex.fsPath)) ?? false;
  }

  /**
   * The libraries to cite from in `tex`: those that read it, or — when none
   * does — every open one, so an unlinked draft can still cite.
   */
  private librariesFor(tex: vscode.Uri): CitableLibrary[] {
    const all = [...this.libraries.values()];
    const linked = all.filter((library) => library.sources.has(normalizePath(tex.fsPath)));
    return linked.length > 0 ? linked : all;
  }

  /** The engine's citation grammar, or `null` when the engine has none to give. */
  private async grammarFor(scope: vscode.Uri): Promise<CitationGrammar | null> {
    const engine = await resolveEngine(scope);
    const id = `${describeCommand(engine.command)}@${engine.version ?? ""}`;
    let grammar = this.grammars.get(id);
    if (!grammar) {
      grammar = citationGrammar(engine.command, scope.scheme === "file" ? path.dirname(scope.fsPath) : undefined)
        .then((envelope) => (envelope.status === "success" ? envelope.citation_grammar : null))
        .catch(() => null);
      this.grammars.set(id, grammar);
      // A failure is remembered only for this call; the next one asks again.
      void grammar.then((found) => {
        if (!found) {
          this.grammars.delete(id);
        }
      });
    }
    return grammar;
  }

  // -- inserting ------------------------------------------------------------

  /**
   * Cite `keys` from the library `bib` at the cursor of the TeX editor last
   * used: joined to the `\cite{...}` the cursor stands in, or as a new one.
   */
  async insert(keys: string[], bib: vscode.Uri): Promise<CitedResult | undefined> {
    if (keys.length === 0) {
      return undefined;
    }
    const grammar = await this.grammarFor(bib);
    if (!grammar) {
      void vscode.window.showErrorMessage(
        "This engine does not expose citation_grammar. Use the bundled engine or an engine with citation support.",
      );
      return undefined;
    }
    const macro = citationCommand(bib);
    if (!isCitationMacro(macro, grammar)) {
      void vscode.window.showErrorMessage(
        `"\\${macro}" is not a citation command pynakes counts, so citations made with it ` +
          "would not show as cited. Change pynakes.citationCommand to one that is, such as cite.",
      );
      return undefined;
    }
    const editor = await this.targetEditor();
    if (!editor) {
      void vscode.window.showInformationMessage(
        "Open the .tex file the citation goes in and place the cursor there, then cite again.",
      );
      return undefined;
    }
    const document = editor.document;
    const text = document.getText();
    const offset = document.offsetAt(editor.selection.active);
    const plan = planCitationInsertion(text, offset, keys, macro, grammar);
    const name = path.basename(document.fileName);
    if (!plan) {
      vscode.window.setStatusBarMessage(`Already cited there in ${name}`, 3000);
      return { target: document.uri, added: [], linked: this.isLinked(bib, document.uri) };
    }
    const at = document.positionAt(plan.offset);
    const applied = await editor.edit((builder) => builder.insert(at, plan.text));
    if (!applied) {
      void vscode.window.showErrorMessage(`Could not insert the citation into ${name}.`);
      return undefined;
    }
    // Leave the cursor after what was inserted, ready for the next one.
    const end = document.positionAt(plan.offset + plan.text.length);
    editor.selection = new vscode.Selection(end, end);
    editor.revealRange(new vscode.Range(at, end));
    vscode.window.setStatusBarMessage(`Cited ${plan.added.join(", ")} in ${name}`, 3000);
    return { target: document.uri, added: plan.added, linked: this.isLinked(bib, document.uri) };
  }

  /**
   * The TeX editor to insert into: the one last used, shown again if it was
   * hidden; else the only TeX editor on screen.
   */
  private async targetEditor(): Promise<vscode.TextEditor | undefined> {
    const target = this.lastTarget;
    if (target) {
      const visible = vscode.window.visibleTextEditors.find(
        (editor) => editor.document.uri.toString() === target.uri.toString(),
      );
      if (visible) {
        return visible;
      }
      try {
        const editor = await vscode.window.showTextDocument(target.uri, {
          viewColumn: vscode.ViewColumn.Beside,
          preserveFocus: true,
          preview: false,
          selection: target.selection,
        });
        return editor;
      } catch {
        // Deleted or unreadable since: fall through to what is on screen.
      }
    }
    const shown = vscode.window.visibleTextEditors.filter((editor) => isTexDocument(editor.document));
    return shown.length === 1 ? shown[0] : undefined;
  }

  /** From a TeX editor: pick entries of the libraries open in the view, and cite them. */
  private async pickAndInsert(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor || !isTexDocument(editor.document)) {
      void vscode.window.showInformationMessage("Place the cursor in a .tex file to insert a citation.");
      return;
    }
    const libraries = this.librariesFor(editor.document.uri);
    if (libraries.length === 0) {
      void vscode.window.showInformationMessage(
        "Open a bibliography with Open with Pynakes to cite from it.",
      );
      return;
    }
    const several = libraries.length > 1;
    const items = libraries.flatMap((library) =>
      library.rows.map((row) => ({
        label: row.key,
        description: [row.author, row.year].filter(Boolean).join(", "),
        detail: several ? `${row.title} — ${vscode.workspace.asRelativePath(library.uri)}` : row.title,
        key: row.key,
        library: library.uri,
      })),
    );
    const picked = await vscode.window.showQuickPick(items, {
      title: "Insert citation",
      placeHolder: "Search by key, author, year, or title",
      canPickMany: true,
      matchOnDescription: true,
      matchOnDetail: true,
    });
    if (!picked?.length) {
      return;
    }
    this.lastTarget = { uri: editor.document.uri, selection: editor.selection };
    await this.insert([...new Set(picked.map((item) => item.key))], picked[0].library);
  }

  // -- completing -----------------------------------------------------------

  private async complete(
    document: vscode.TextDocument,
    position: vscode.Position,
  ): Promise<vscode.CompletionItem[] | undefined> {
    if (!vscode.workspace.getConfiguration("pynakes", document.uri).get<boolean>("citationCompletion", true)) {
      return undefined;
    }
    const libraries = this.librariesFor(document.uri);
    if (libraries.length === 0) {
      return undefined;
    }
    const grammar = await this.grammarFor(libraries[0].uri);
    if (!grammar) {
      return undefined;
    }
    const context = findCitationContext(document.getText(), document.offsetAt(position), grammar);
    if (!context) {
      return undefined;
    }
    const range = new vscode.Range(document.positionAt(context.tokenStart), position);
    // Keys already in the list are not offered again, except the one being typed.
    const present = new Set(context.keys);
    present.delete(context.prefix);
    const several = libraries.length > 1;
    const seen = new Set<string>();
    const items: vscode.CompletionItem[] = [];
    for (const library of libraries) {
      for (const row of library.rows) {
        if (present.has(row.key) || seen.has(row.key)) {
          continue;
        }
        seen.add(row.key);
        const item = new vscode.CompletionItem(
          { label: row.key, description: [row.author, row.year].filter(Boolean).join(", ") },
          vscode.CompletionItemKind.Reference,
        );
        item.range = range;
        item.filterText = [row.key, row.author, row.year, row.title].join(" ");
        item.detail = row.title;
        if (several) {
          item.documentation = vscode.workspace.asRelativePath(library.uri);
        }
        items.push(item);
      }
    }
    return items;
  }
}

/** The macro a new citation is written with, from `pynakes.citationCommand`. */
function citationCommand(scope: vscode.Uri): string {
  const configured = vscode.workspace.getConfiguration("pynakes", scope).get<string>("citationCommand", "cite");
  return configured.trim().replace(/^\\/, "") || "cite";
}

/** A path as the engine's scan reports it, comparable across case-insensitive file systems. */
function normalizePath(file: string): string {
  const resolved = path.resolve(file);
  return process.platform === "win32" || process.platform === "darwin" ? resolved.toLowerCase() : resolved;
}

/** The source's path relative to the `.bib`'s directory, as `tex-sources` stores it. */
export function relativeSource(bib: vscode.Uri, tex: vscode.Uri): string {
  return path.relative(path.dirname(bib.fsPath), tex.fsPath).split(path.sep).join("/");
}
