/**
 * Where a material opens: inside VS Code, or with the operating system's own
 * handler. Pure decisions only — `navigation.ts` gathers the facts (the
 * setting, the click, what is on disk, which viewers are installed) and acts.
 *
 * Opening in VS Code never executes anything: the file is shown by whatever
 * editor is associated with it (a PDF viewer extension, the built-in image
 * preview, the text editor). Opening with the system hands the path to the
 * OS, as the extension always did.
 */

/** The two places a material can open; `pynakes.openMaterialsWith`'s values. */
export type MaterialOpener = "editor" | "system";

/** The setting's default: inside VS Code. */
export const DEFAULT_MATERIAL_OPENER: MaterialOpener = "editor";

/** Accept a value from settings or the webview only when it names an opener. */
export function asMaterialOpener(value: unknown): MaterialOpener | undefined {
  return value === "editor" || value === "system" ? value : undefined;
}

/**
 * Formats a material is commonly stored in that the text editor cannot show.
 * With no custom editor claiming one, VS Code opens such a file to its
 * "binary or unsupported encoding" placeholder — still harmless, but worth a
 * hint. Anything else (`.tex`, `.bib`, `.txt`, ...) the text editor shows.
 */
const VIEWER_NEEDED = new Set([
  ".pdf",
  ".djvu",
  ".epub",
  ".zip",
  ".gz",
  ".tgz",
  ".tar",
  ".bz2",
  ".xz",
  ".7z",
  ".rar",
  ".doc",
  ".docx",
  ".odt",
  ".ppt",
  ".pptx",
  ".xls",
  ".xlsx",
]);

/** A custom editor some installed extension contributes. */
export interface CustomEditorContribution {
  viewType: string;
  /** Its `selector[].filenamePattern` globs. */
  patterns: string[];
  /** `"default"` (the manifest's default) or `"option"`. */
  priority?: string;
}

/** What the host knows when a material is about to open. */
export interface MaterialOpenFacts {
  /** `pynakes.openMaterialsWith`, unvalidated. */
  setting: unknown;
  /** The opener the click asked for, unvalidated; absent means the setting. */
  requested?: unknown;
  /** True when the path is a directory. */
  isDirectory: boolean;
  /** True when a directory lies inside an open workspace folder. */
  inWorkspace: boolean;
  /** True when VS Code has an editor that can show this file. */
  hasViewer: boolean;
  /** The file's lower-cased extension, with its dot. */
  extension: string;
}

/** What to do, and whether to hint that VS Code cannot show the file well. */
export interface MaterialOpenPlan {
  action: "editor" | "system" | "revealInExplorer" | "revealInOS";
  /** Set when the file opens in VS Code to a placeholder rather than a view. */
  suggestViewer: boolean;
  /** The opener that was chosen, for the notification's alternative. */
  opener: MaterialOpener;
}

/**
 * Decide how to open one material.
 *
 * The click's own choice wins over the setting; an unrecognized value in
 * either falls back to the default. A directory is never "opened": in VS Code
 * it is revealed in the Explorer when the Explorer can show it (it is inside
 * the workspace), and otherwise in the OS file manager, as it always was.
 */
export function planMaterialOpen(facts: MaterialOpenFacts): MaterialOpenPlan {
  const opener =
    asMaterialOpener(facts.requested) ?? asMaterialOpener(facts.setting) ?? DEFAULT_MATERIAL_OPENER;
  if (facts.isDirectory) {
    const action = opener === "editor" && facts.inWorkspace ? "revealInExplorer" : "revealInOS";
    return { action, suggestViewer: false, opener };
  }
  if (opener === "system") {
    return { action: "system", suggestViewer: false, opener };
  }
  const suggestViewer = !facts.hasViewer && VIEWER_NEEDED.has(facts.extension.toLowerCase());
  return { action: "editor", suggestViewer, opener };
}

/**
 * Whether VS Code would show `filePath` in a custom editor when it is opened.
 *
 * A `"default"`-priority custom editor whose pattern matches takes the file
 * on its own; an `"option"`-priority one only when `workbench.editorAssociations`
 * points the file at it. An association to `"default"` (the text editor)
 * means no viewer, whatever is installed.
 */
export function hasCustomViewer(
  filePath: string,
  editors: CustomEditorContribution[],
  associations: unknown,
): boolean {
  const associated = associatedViewType(filePath, associations);
  if (associated !== undefined) {
    return associated !== "default" && editors.some((editor) => editor.viewType === associated);
  }
  return editors.some(
    (editor) =>
      (editor.priority ?? "default") !== "option" &&
      editor.patterns.some((pattern) => globMatches(pattern, filePath)),
  );
}

/** The view type `workbench.editorAssociations` assigns to a path, if any. */
function associatedViewType(filePath: string, associations: unknown): string | undefined {
  const pairs: Array<[string, unknown]> = [];
  if (Array.isArray(associations)) {
    // The older array form: [{ filenamePattern, viewType }].
    for (const item of associations) {
      if (item && typeof item === "object") {
        const { filenamePattern, viewType } = item as Record<string, unknown>;
        if (typeof filenamePattern === "string") {
          pairs.push([filenamePattern, viewType]);
        }
      }
    }
  } else if (associations && typeof associations === "object") {
    pairs.push(...Object.entries(associations as Record<string, unknown>));
  }
  for (const [pattern, viewType] of pairs) {
    if (typeof viewType === "string" && globMatches(pattern, filePath)) {
      return viewType;
    }
  }
  return undefined;
}

/** Read the custom editors out of extension manifests, skipping malformed ones. */
export function customEditorsOf(manifests: unknown[]): CustomEditorContribution[] {
  const editors: CustomEditorContribution[] = [];
  for (const manifest of manifests) {
    const contributed = (manifest as { contributes?: { customEditors?: unknown } } | undefined)
      ?.contributes?.customEditors;
    if (!Array.isArray(contributed)) {
      continue;
    }
    for (const item of contributed) {
      const { viewType, selector, priority } = (item ?? {}) as Record<string, unknown>;
      if (typeof viewType !== "string" || !Array.isArray(selector)) {
        continue;
      }
      const patterns = selector
        .map((entry) => (entry as { filenamePattern?: unknown } | null)?.filenamePattern)
        .filter((pattern): pattern is string => typeof pattern === "string");
      editors.push({ viewType, patterns, priority: typeof priority === "string" ? priority : undefined });
    }
  }
  return editors;
}

/**
 * Match a VS Code filename glob, case-insensitively as VS Code's editor
 * resolver does: a pattern with a path separator matches the whole path,
 * any other the file's name. Supports `**`, `*`, `?`, `{a,b}` and `[...]`.
 */
export function globMatches(pattern: string, filePath: string): boolean {
  const normalized = filePath.replace(/\\/g, "/");
  const subject = pattern.includes("/") ? normalized : normalized.slice(normalized.lastIndexOf("/") + 1);
  try {
    return globToRegExp(pattern).test(subject);
  } catch {
    return false;
  }
}

function globToRegExp(pattern: string): RegExp {
  let source = "";
  let braces = 0;
  for (let index = 0; index < pattern.length; index += 1) {
    const char = pattern[index];
    if (char === "*") {
      if (pattern[index + 1] === "*") {
        index += 1;
        if (pattern[index + 1] === "/") {
          index += 1;
          source += "(?:.*/)?";
        } else {
          source += ".*";
        }
      } else {
        source += "[^/]*";
      }
    } else if (char === "?") {
      source += "[^/]";
    } else if (char === "{") {
      braces += 1;
      source += "(?:";
    } else if (char === "}" && braces > 0) {
      braces -= 1;
      source += ")";
    } else if (char === "," && braces > 0) {
      source += "|";
    } else if (char === "[") {
      const close = pattern.indexOf("]", index + 1);
      if (close < 0) {
        source += "\\[";
      } else {
        const body = pattern.slice(index + 1, close).replace(/^!/, "^").replace(/\\/g, "\\\\");
        source += `[${body}]`;
        index = close;
      }
    } else {
      source += char.replace(/[.+^$()|\\\]]/g, "\\$&");
    }
  }
  return new RegExp(`^${source}$`, "i");
}
