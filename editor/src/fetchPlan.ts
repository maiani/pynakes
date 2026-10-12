/**
 * Fetching materials: the `asset fetch` envelope, and what the view says about it.
 *
 * Kept free of `vscode` so every sentence the approval dialog and the result
 * notice contain can be tested against the real engine's output. The flow that
 * asks, runs and reports lives in `materialFetch.ts`.
 *
 * Nothing here decides what an entry can have fetched, or where a file goes.
 * The engine's dry run names each artifact a real run would request, the
 * identifier it would be requested by, and the path it would be written to;
 * an entry with nothing to fetch comes back with the engine's reason. This
 * module only arranges those into sentences.
 */

import { materialLabel } from "./insights";
import { notApplied, type NotApplied } from "./library";
import {
  warningText,
  type InspectError,
  type MutationConflict,
  type MutationSuccess,
} from "./model";
import { assetFetch, type AssetFetchRequest, type PynakesCommand } from "./pynakes";

// ---------------------------------------------------------------------------
// The envelope.
// ---------------------------------------------------------------------------

/** One artifact a dry run says a real run would request. */
export interface PlannedArtifact {
  /** `published_pdf`, `preprint_pdf`, `preprint_source`, `supplement_pdf`. */
  artifact: string;
  /** Where the store would write it — the engine's path, never rebuilt here. */
  path: string;
  doi?: string;
  arxiv_id?: string | null;
  /** The preprint `best-pdf` requests only when no published PDF is found. */
  fallback?: boolean;
}

/**
 * One request the engine made for a material, as it recorded it: the URL asked
 * for and where redirects ended (both without credentials or token-like query
 * parameters), the HTTP status, and the content type.
 */
export interface FetchAttempt {
  url: string | null;
  final_url?: string | null;
  status?: number | null;
  content_type?: string | null;
  /** `pdf`, `not_pdf`, `http_error`, or `network_error`. */
  outcome?: string;
}

/** An entry, or one artifact of it, that was not fetched — and why. */
export interface FetchSkip {
  key: string;
  reason?: string | null;
  artifact?: string;
  /** Present on a dry run's "would fetch" items: what a real run would request. */
  planned?: PlannedArtifact[];
  /** The requests made before giving up, when any were. */
  attempts?: FetchAttempt[];
}

/** Files a real run wrote for one entry. */
export interface FetchedMaterial {
  key: string;
  artifact?: string;
  pdf_path?: string | null;
  source_path?: string | null;
}

export interface FetchFailure {
  key: string;
  error: string;
  artifact?: string;
  attempts?: FetchAttempt[];
}

export interface AssetFetchSuccess extends MutationSuccess {
  /** The Pinax store the files land in — recorded first when the library has none. */
  files_dir?: string | null;
  fetched: FetchedMaterial[];
  skipped: FetchSkip[];
  failed: FetchFailure[];
  /**
   * The run's counts. `requested` is entries; the rest count items, and
   * `already_present + unavailable + planned` is the length of `skipped`.
   */
  summary?: {
    requested: number;
    fetched: number;
    already_present: number;
    unavailable: number;
    failed: number;
    planned: number;
  };
}

export type AssetFetchEnvelope = AssetFetchSuccess | MutationConflict | InspectError;

// ---------------------------------------------------------------------------
// What the view asks for.
// ---------------------------------------------------------------------------

/**
 * The materials that can be asked for: the engine's own `--material` values,
 * plus leaving the choice to the library's `pinax-fetch-policy`.
 */
export const FETCH_MATERIALS: ReadonlyArray<{
  value: string | undefined;
  label: string;
  detail: string;
}> = [
  {
    value: undefined,
    label: "As the library's fetch policy says",
    detail: "Whatever pinax-fetch-policy selects for this library",
  },
  {
    value: "best-pdf",
    label: "Best PDF",
    detail: "The published PDF when open access, otherwise the preprint",
  },
  { value: "published", label: "Published PDF", detail: "The open-access version of record" },
  { value: "preprint", label: "Preprint PDF", detail: "The arXiv PDF" },
  { value: "source", label: "Preprint source", detail: "The arXiv source archive" },
  {
    value: "supplement",
    label: "Supplement PDF",
    detail: "One unambiguous supplementary PDF",
  },
];

/** The reason a dry run gives an entry it would fetch for. */
const WOULD_FETCH = "would fetch";

/** Said when the engine's plan does not name the files a fetch would write. */
export const NO_PLAN_MESSAGE =
  "Nothing was fetched: this engine does not report which files a fetch would write, so " +
  "there is nothing to approve. Update pynakes, or let the extension use its bundled engine.";

/** Said instead of running anything when `pynakes.allowOnlineLookups` is off. */
export const FETCH_LOOKUPS_DISABLED =
  'Online lookups are disabled. Enable "pynakes.allowOnlineLookups" in settings to fetch ' +
  "materials from arXiv and publishers.";

/** The action's name, for the dialog, the progress notice and the result. */
export function fetchLabel(request: AssetFetchRequest): string {
  return request.key ? `Fetch materials for ${request.key}` : "Fetch missing materials";
}

// ---------------------------------------------------------------------------
// The outcome.
// ---------------------------------------------------------------------------

/** One entry's planned downloads. */
export interface FetchPlanEntry {
  key: string;
  artifacts: PlannedArtifact[];
}

/** A key with the engine's reason, for skips and failures alike. */
export interface FetchNote {
  key: string;
  artifact?: string;
  reason: string;
  /** What the requests behind it got: each host and its HTTP status, or what failed. */
  tried?: string;
}

/**
 * Each request's host and what came back — `journals.aps.org (HTTP 403)` —
 * from the engine's own record, repeated requests to one host said once.
 */
export function triedText(attempts: FetchAttempt[] | undefined): string | undefined {
  const parts = (attempts ?? []).map((attempt) => {
    const url = attempt.final_url ?? attempt.url ?? "";
    let host = url;
    try {
      host = new URL(url).host;
    } catch {
      // Not a URL the engine recorded in full: show what it gave.
    }
    const answer = attempt.status
      ? `HTTP ${attempt.status}${attempt.content_type ? `, ${attempt.content_type}` : ""}`
      : (attempt.outcome ?? "no response").replace(/_/g, " ");
    return `${host} (${answer})`;
  });
  const unique = [...new Set(parts)];
  return unique.length > 0 ? unique.join(", ") : undefined;
}

export type FetchOutcome =
  | {
      ok: true;
      diff: string;
      warnings: string[];
      /** Whether the `.bib` changes — a store recorded — not whether files were fetched. */
      modified: boolean;
      sourceSha256?: string;
      filesDir: string | null;
      planned: FetchPlanEntry[];
      /**
       * Entries a dry run would fetch for but named no files for — an engine
       * older than the `planned` list. Never treated as "nothing to fetch".
       */
      unplanned: string[];
      skipped: FetchNote[];
      fetched: Array<{ key: string; paths: string[] }>;
      failed: FetchNote[];
    }
  | NotApplied;

export function reduceFetch(envelope: AssetFetchEnvelope): FetchOutcome {
  if (envelope.status !== "success") {
    return notApplied(envelope);
  }
  const planned: FetchPlanEntry[] = [];
  const unplanned: string[] = [];
  const skipped: FetchNote[] = [];
  for (const item of envelope.skipped ?? []) {
    if (item.planned?.length) {
      planned.push({ key: item.key, artifacts: item.planned });
    } else if (envelope.dry_run && item.reason === WOULD_FETCH) {
      unplanned.push(item.key);
    } else {
      skipped.push({
        key: item.key,
        artifact: item.artifact,
        reason: item.reason || "unavailable",
        tried: triedText(item.attempts),
      });
    }
  }
  // A failed download is also reported as a `download_failed` warning; the
  // failure line already says it, so only the warnings that add something
  // (one a fallback made up for) are shown.
  const failedKeys = new Set((envelope.failed ?? []).map((item) => item.key));
  const warnings = (envelope.warnings ?? []).filter(
    (warning) => warning.type !== "download_failed" || !failedKeys.has(String(warning.key)),
  );
  return {
    ok: true,
    diff: envelope.diff ?? "",
    warnings: warnings.map(warningText),
    modified: envelope.modified,
    sourceSha256: envelope.source_sha256,
    filesDir: envelope.files_dir ?? null,
    planned,
    unplanned,
    skipped,
    fetched: (envelope.fetched ?? []).map((item) => ({
      key: item.key,
      paths: [item.pdf_path, item.source_path].filter((path): path is string => Boolean(path)),
    })),
    failed: (envelope.failed ?? []).map((item) => ({
      key: item.key,
      artifact: item.artifact,
      reason: item.error,
      tried: triedText(item.attempts),
    })),
  };
}

/** The dry run: what would be fetched, requesting nothing and writing nothing. */
export async function planFetch(
  command: PynakesCommand,
  filePath: string,
  request: AssetFetchRequest,
  cwd?: string,
): Promise<FetchOutcome> {
  return reduceFetch(await assetFetch(command, filePath, request, true, cwd));
}

/** The approved run, refused by the engine if the file is no longer the one planned. */
export async function runFetch(
  command: PynakesCommand,
  filePath: string,
  request: AssetFetchRequest,
  expectSha256: string,
  cwd?: string,
  signal?: AbortSignal,
): Promise<FetchOutcome> {
  return reduceFetch(
    await assetFetch(command, filePath, request, false, cwd, expectSha256, signal),
  );
}

// ---------------------------------------------------------------------------
// What the view says.
// ---------------------------------------------------------------------------

/** How many lines of a long plan the dialog lists before summarizing the rest. */
const MAX_LISTED = 10;

type Planned = Extract<FetchOutcome, { ok: true }>;

function listed(lines: string[], noun: (count: number) => string): string[] {
  if (lines.length <= MAX_LISTED) {
    return lines;
  }
  const rest = lines.length - MAX_LISTED;
  return [...lines.slice(0, MAX_LISTED), `…and ${rest} more ${noun(rest)}.`];
}

function plural(count: number, one: string, many: string): string {
  return count === 1 ? one : many;
}

function artifactLine(key: string, item: PlannedArtifact): string {
  const by = item.doi ? `DOI ${item.doi}` : item.arxiv_id ? `arXiv ${item.arxiv_id}` : "";
  const when = item.fallback ? ", only if no published PDF is found" : "";
  return `• ${key}: ${materialLabel(item.artifact)}${when}${by ? ` (${by})` : ""} → ${item.path}`;
}

function noteLine(note: FetchNote): string {
  const what = note.artifact ? ` ${materialLabel(note.artifact)}` : "";
  return `• ${note.key}${what}: ${note.reason}`;
}

function triedSuffix(note: FetchNote): string {
  return note.tried ? ` [tried ${note.tried}]` : "";
}

/** Count the files a plan would request, fallbacks included. */
export function plannedFileCount(outcome: Planned): number {
  return outcome.planned.reduce((total, entry) => total + entry.artifacts.length, 0);
}

/**
 * The approval dialog: what the `.bib` diff cannot show.
 *
 * That approving reaches the network (and the preview did not), which files
 * would be written and where — as the engine reported them — what was left
 * out and the engine's reason, and whether the `.bib` itself changes.
 */
export function fetchApproval(
  request: AssetFetchRequest,
  outcome: Planned,
): { title: string; detail: string } {
  // A best-pdf fallback is requested only in place of the published PDF it
  // follows, so at most one of the two is written.
  const files = plannedFileCount(outcome);
  const atMost =
    files -
    outcome.planned.reduce(
      (total, entry) => total + entry.artifacts.filter((item) => item.fallback).length,
      0,
    );
  const entries = outcome.planned.length;
  const title = request.key
    ? `${fetchLabel(request)}?`
    : `Fetch materials for ${entries} ${plural(entries, "entry", "entries")}?`;

  const sections: string[] = [
    "Approving makes network requests: each file below is requested by the DOI or " +
      "arXiv id shown. Planning this made none.",
    [
      `Would write ${atMost === files ? "" : "up to "}${atMost} ${plural(atMost, "file", "files")}:`,
      ...listed(
        outcome.planned.flatMap((entry) =>
          entry.artifacts.map((item) => artifactLine(entry.key, item)),
        ),
        (count) => plural(count, "file", "files"),
      ),
    ].join("\n"),
  ];
  if (outcome.skipped.length > 0) {
    sections.push(
      [
        "Nothing to fetch:",
        ...listed(outcome.skipped.map(noteLine), (count) => plural(count, "entry", "entries")),
      ].join("\n"),
    );
  }
  sections.push(
    "A file the provider cannot supply is skipped, not an error, and reported afterwards. " +
      "Each download is recorded in the store's provenance manifest" +
      (outcome.filesDir ? ` under ${outcome.filesDir}.` : "."),
  );
  sections.push(
    outcome.modified
      ? "The .bib changes too, exactly as the diff shows — but only if a file is " +
        "actually fetched: a run that downloads nothing leaves it as it is."
      : "The .bib itself is not changed.",
  );
  sections.push(...outcome.warnings);
  return { title, detail: sections.join("\n\n") };
}

/** Said instead of asking when the dry run planned nothing at all. */
export function nothingToFetch(request: AssetFetchRequest, outcome: Planned): string {
  if (request.key) {
    const reasons = outcome.skipped
      .filter((note) => note.key === request.key)
      .map((note) => note.reason);
    return `Nothing to fetch for ${request.key}` + (reasons.length ? `: ${reasons.join("; ")}.` : ".");
  }
  return "Nothing to fetch: every entry already has what the fetch selects, or has no DOI or arXiv id to fetch it by.";
}

/**
 * The notice after a real run: what landed, what the providers could not
 * supply, and what failed — each with the engine's own reason.
 *
 * Only skips for entries the plan included are reported; on a whole-library
 * fetch the rest are the entries that had nothing to fetch in the first place.
 */
export function fetchResult(
  outcome: Planned,
  plannedKeys: ReadonlySet<string>,
): { level: "success" | "warning" | "info" | "error"; message: string } {
  const files = outcome.fetched.reduce((total, item) => total + item.paths.length, 0);
  const keys = [...new Set(outcome.fetched.map((item) => item.key))];
  const parts: string[] = [];
  if (files > 0) {
    parts.push(
      `Fetched ${files} ${plural(files, "file", "files")}` +
        (keys.length === 1 ? ` for ${keys[0]}.` : ` for ${keys.length} entries.`),
    );
  } else {
    parts.push("Nothing was downloaded.");
  }
  const skips = outcome.skipped.filter((note) => plannedKeys.has(note.key));
  if (skips.length > 0) {
    parts.push(
      "Skipped " +
        skips
          .map(
            (note) =>
              `${note.key}${note.artifact ? ` ${materialLabel(note.artifact)}` : ""} (${note.reason})` +
              triedSuffix(note),
          )
          .join("; ") +
        ".",
    );
  }
  if (outcome.failed.length > 0) {
    parts.push(
      "Failed " +
        outcome.failed.map((note) => `${note.key} (${note.reason})${triedSuffix(note)}`).join("; ") +
        ".",
    );
  }
  parts.push(...outcome.warnings);
  const level =
    outcome.failed.length > 0
      ? files > 0
        ? "warning"
        : "error"
      : files > 0
        ? skips.length > 0
          ? "warning"
          : "success"
        : "info";
  return { level, message: parts.join(" ") };
}
