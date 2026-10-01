/**
 * Resolving *which* pynakes engine to run.
 *
 * This is deliberately the only module concerned with locating the engine, so
 * discovery strategy (settings, interpreter probing, a bundled copy, version
 * comparison) can evolve without touching the command layer in `pynakes.ts`.
 * Callers depend on the signature below, not on how the answer is reached.
 *
 * The extension ships a vendored copy of the engine in `engine/`, so a user
 * needs a Python interpreter but not a pynakes install. An engine the user
 * installed themselves still wins when it is *newer* than the bundled one, so
 * upgrading pynakes takes effect without waiting for an extension release.
 *
 * Resolution order:
 *
 *   1. `pynakes.executable`, when set — an explicit choice is never overridden.
 *   2. `pynakes.engine`, when it forces `bundled` or `installed`.
 *   3. Otherwise probe both, taking the installed engine only if its version is
 *      strictly greater. A tie keeps the bundle, the copy this extension was
 *      built and tested against.
 *   4. If the bundle has no usable interpreter, the installed engine is used
 *      even when older: a working older engine beats no engine.
 *
 * This module never spawns a process itself — `pynakes.ts` is the only place
 * allowed to do that — so every probe goes through its `engineVersion`, whose
 * `undefined` return already means "this candidate does not work".
 */

import * as fsp from "node:fs/promises";
import * as path from "node:path";
import * as vscode from "vscode";
import { PynakesUnavailableError, describeCommand, engineVersion } from "./pynakes";
import { isNewerThan, parseVersion } from "./version";

/** A resolved invocation: an executable plus any arguments that precede the subcommand. */
export interface PynakesCommand {
  executable: string;
  leadingArgs: string[];
}

/** Identifies this extension, for locating the vendored engine on disk. */
const EXTENSION_ID = "pynakes.pynakes-vscode";

/** Directory inside the extension holding the vendored engine. */
const ENGINE_DIRECTORY = "engine";

/** Keeps the working directory off `sys.path`; see the launcher's docstring. */
const ISOLATION_FLAG = "-P";

/** Where the engine came from, for display and diagnostics. */
export type EngineSource = "setting" | "bundled" | "installed";

/** How the extension should invoke pynakes, plus why this engine was chosen. */
export interface ResolvedEngine {
  command: PynakesCommand;
  source: EngineSource;
  /** Version of the chosen engine, absent when it declined to report one. */
  version?: string;
  /** Version of the vendored engine, absent when no usable bundle was found. */
  bundledVersion?: string;
  /** Version of the engine on `PATH`, absent when there is none that runs. */
  installedVersion?: string;
  /** One sentence explaining the choice, suitable for a tooltip or log line. */
  reason: string;
}

/** The manifest `scripts/vendor-engine.mjs` writes beside the vendored tree. */
interface EngineManifest {
  version: string;
  requiresPython: string;
  /** Absolute path to the launcher, once the manifest has been resolved. */
  launcher: string;
}

interface EngineSettings {
  executable: string;
  executableArgs: string[];
  mode: "auto" | "bundled" | "installed";
}

/** A candidate that ran successfully, with the version it reported. */
interface EngineCandidate {
  command: PynakesCommand;
  source: EngineSource;
  version: string;
}

/**
 * Cached resolutions, keyed on the settings they depend on.
 *
 * Probing costs a process spawn per candidate and the view reads on every
 * keystroke burst, so this must not re-probe per read. A map rather than a
 * single slot: two open bibliographies resolving to different workspace
 * folders would otherwise evict each other's entry and re-probe — several
 * spawns — on every read. Keys are (settings, folder) pairs, bounded by how
 * many distinct configurations are actually in use. Keying on the settings
 * themselves invalidates an entry on a configuration change without this
 * module having to own a listener and its disposal.
 */
const cache = new Map<string, Promise<ResolvedEngine>>();

/** Read the settings that decide which engine runs. */
function readSettings(scope?: vscode.Uri): EngineSettings {
  const config = vscode.workspace.getConfiguration("pynakes", scope ?? null);
  return {
    executable: config.get<string>("executable")?.trim() ?? "",
    executableArgs: config.get<string[]>("executableArgs") ?? [],
    mode: config.get<"auto" | "bundled" | "installed">("engine") ?? "auto",
  };
}

/** Discard every memoized resolution, so the next read probes again. */
export function resetEngineDiscovery(): void {
  cache.clear();
}

/**
 * Resolve the engine and the reasoning behind the choice, memoized per settings.
 */
export function resolveEngine(scope?: vscode.Uri): Promise<ResolvedEngine> {
  const settings = readSettings(scope);
  const folder = scope ? vscode.workspace.getWorkspaceFolder(scope)?.uri.fsPath : undefined;
  const key = JSON.stringify({ settings, folder });
  let resolved = cache.get(key);
  if (!resolved) {
    resolved = selectEngine(settings, folder);
    cache.set(key, resolved);
  }
  return resolved;
}

async function selectEngine(
  settings: EngineSettings,
  folder: string | undefined,
): Promise<ResolvedEngine> {
  if (settings.executable) {
    const command = { executable: settings.executable, leadingArgs: settings.executableArgs };
    return {
      command,
      source: "setting",
      version: await engineVersion(command, folder),
      reason: `Using "${describeCommand(command)}" from the pynakes.executable setting.`,
    };
  }

  // Probe both candidates concurrently: neither depends on the other's result,
  // and this is the one place in a read where two spawns would serialize.
  const [bundled, installed] = await Promise.all([
    settings.mode === "installed" ? undefined : probeBundled(folder),
    settings.mode === "bundled" ? undefined : probeInstalled(folder),
  ]);

  if (settings.mode === "bundled") {
    if (!bundled) {
      throw new PynakesUnavailableError(
        "the bundled pynakes engine",
        "pynakes.engine is set to 'bundled', but no Python 3.12+ interpreter could run it.",
      );
    }
    return { ...bundled, reason: `Using the bundled engine ${bundled.version} (forced).` };
  }

  if (settings.mode === "installed") {
    if (!installed) {
      throw new PynakesUnavailableError(
        "pynakes",
        "pynakes.engine is set to 'installed', but no pynakes was found on PATH.",
      );
    }
    return { ...installed, reason: `Using the installed engine ${installed.version} (forced).` };
  }

  const bundledVersion = bundled?.version;
  const installedVersion = installed?.version;

  if (bundled && installed) {
    if (isNewerThan(installedVersion, bundledVersion)) {
      return {
        ...installed,
        bundledVersion,
        installedVersion,
        reason:
          `Using the installed engine ${installedVersion}, which is newer than the ` +
          `bundled ${bundledVersion}.`,
      };
    }
    return {
      ...bundled,
      bundledVersion,
      installedVersion,
      reason:
        `Using the bundled engine ${bundledVersion}; the installed ${installedVersion} ` +
        "is not newer.",
    };
  }

  if (bundled) {
    return {
      ...bundled,
      bundledVersion,
      reason: `Using the bundled engine ${bundledVersion}; no installed pynakes was found.`,
    };
  }

  if (installed) {
    return {
      ...installed,
      installedVersion,
      reason:
        `Using the installed engine ${installedVersion}; the bundled engine could not run ` +
        "because no Python 3.12+ interpreter was found.",
    };
  }

  throw new PynakesUnavailableError(
    "pynakes",
    "No pynakes engine is available: the bundled engine needs a Python 3.12+ interpreter, " +
      "and no installed pynakes was found on PATH.",
  );
}

/** Probe `pynakes` on `PATH`, the engine a user installed themselves. */
async function probeInstalled(cwd: string | undefined): Promise<EngineCandidate | undefined> {
  const command: PynakesCommand = { executable: "pynakes", leadingArgs: [] };
  const version = await engineVersion(command, cwd);
  if (!version || !parseVersion(version)) {
    return undefined;
  }
  return { command, source: "installed", version };
}

/**
 * Probe the vendored engine against each interpreter candidate in turn.
 *
 * The launcher refuses to run on a Python below the floor, so an interpreter
 * that is too old fails this probe exactly as a missing one does, and there is
 * no separate interpreter-version check to keep in sync with the engine's.
 */
async function probeBundled(cwd: string | undefined): Promise<EngineCandidate | undefined> {
  const manifest = await readManifest();
  if (!manifest) {
    return undefined;
  }
  for (const interpreter of await interpreterCandidates(cwd)) {
    const command: PynakesCommand = {
      executable: interpreter.executable,
      leadingArgs: [...interpreter.leadingArgs, ISOLATION_FLAG, manifest.launcher],
    };
    const version = await engineVersion(command, cwd);
    if (version && parseVersion(version)) {
      return { command, source: "bundled", version };
    }
  }
  return undefined;
}

/** Locate the vendored engine and read its manifest, resolving the launcher path. */
async function readManifest(): Promise<EngineManifest | undefined> {
  const root = engineRoot();
  if (!root) {
    return undefined;
  }
  try {
    const raw = await fsp.readFile(path.join(root, "engine.json"), "utf8");
    const parsed = JSON.parse(raw) as EngineManifest;
    if (!parsed.version || !parsed.launcher) {
      return undefined;
    }
    const launcher = path.join(root, parsed.launcher);
    await fsp.access(launcher);
    return { ...parsed, launcher };
  } catch {
    // No bundle in this build — e.g. a dev checkout that has not vendored yet.
    return undefined;
  }
}

/** Absolute path to the vendored engine directory, if the extension is resolvable. */
function engineRoot(): string | undefined {
  const extension = vscode.extensions.getExtension(EXTENSION_ID);
  if (!extension || extension.extensionUri.scheme !== "file") {
    return undefined;
  }
  return path.join(extension.extensionUri.fsPath, ENGINE_DIRECTORY);
}

interface InterpreterCandidate {
  executable: string;
  leadingArgs: string[];
}

/**
 * Interpreters to try for the bundled engine, best first.
 *
 * The Python extension's selection comes first because it is the interpreter
 * the user already chose for this workspace; a workspace virtual environment
 * comes next; bare `PATH` names last.
 */
async function interpreterCandidates(cwd: string | undefined): Promise<InterpreterCandidate[]> {
  const candidates: InterpreterCandidate[] = [];
  const seen = new Set<string>();
  const add = (executable: string | undefined, leadingArgs: string[] = []): void => {
    if (!executable) {
      return;
    }
    const identity = [executable, ...leadingArgs].join(" ");
    if (!seen.has(identity)) {
      seen.add(identity);
      candidates.push({ executable, leadingArgs });
    }
  };

  add(await pythonExtensionInterpreter(cwd));
  for (const found of await workspaceVirtualEnvs(cwd)) {
    add(found);
  }
  if (process.platform === "win32") {
    add("python.exe");
    add("py", ["-3"]);
  } else {
    add("python3");
    add("python");
  }
  return candidates;
}

/** Minimal shape of the parts of the Python extension's API used here. */
interface PythonExtensionApi {
  environments?: {
    getActiveEnvironmentPath?(scope?: vscode.Uri): { path?: string } | undefined;
    resolveEnvironment?(target: unknown): Promise<{ executable?: { uri?: vscode.Uri } } | undefined>;
  };
}

/**
 * The interpreter `ms-python.python` has selected, when that extension is present.
 *
 * Entirely optional: every failure path here falls through to the next
 * candidate, so the extension never hard-depends on the Python extension.
 */
async function pythonExtensionInterpreter(cwd: string | undefined): Promise<string | undefined> {
  try {
    const extension = vscode.extensions.getExtension<PythonExtensionApi>("ms-python.python");
    if (!extension) {
      return undefined;
    }
    const api = extension.isActive ? extension.exports : await extension.activate();
    const scope = cwd ? vscode.Uri.file(cwd) : undefined;
    const selected = api.environments?.getActiveEnvironmentPath?.(scope);
    if (!selected?.path) {
      return undefined;
    }
    // `path` may name an environment folder rather than the interpreter itself,
    // so prefer the resolved executable when the API can provide one.
    const resolved = await api.environments?.resolveEnvironment?.(selected);
    return resolved?.executable?.uri?.fsPath ?? selected.path;
  } catch {
    return undefined;
  }
}

/** Interpreters from a virtual environment sitting in the workspace folder. */
async function workspaceVirtualEnvs(cwd: string | undefined): Promise<string[]> {
  if (!cwd) {
    return [];
  }
  const relative =
    process.platform === "win32"
      ? [path.join("Scripts", "python.exe")]
      : [path.join("bin", "python3"), path.join("bin", "python")];
  const found: string[] = [];
  for (const directory of [".venv", "venv"]) {
    for (const leaf of relative) {
      const candidate = path.join(cwd, directory, leaf);
      try {
        await fsp.access(candidate);
        found.push(candidate);
      } catch {
        // Not present; try the next layout.
      }
    }
  }
  return found;
}
