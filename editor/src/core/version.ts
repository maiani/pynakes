/**
 * Version parsing and comparison for engine selection.
 *
 * The extension has to answer one question — "is the installed engine newer
 * than the bundled one?" — from nothing but the string `pynakes --version`
 * prints. That string comes from `importlib.metadata`, so it is a PEP 440
 * version, and the subset that appears in practice (releases, pre-releases,
 * post-releases, dev releases, local labels) is what this module orders.
 *
 * Like `model.ts`, this file deliberately imports no `vscode`, so it can be
 * unit tested with `node --test`.
 */

/** A PEP 440 version decomposed into its comparable parts. */
export interface ParsedVersion {
  /** Numeric release segments, e.g. `[0, 6, 0]` for `0.6.0`. */
  release: number[];
  /** The original string, kept for display and diagnostics. */
  raw: string;
}

/**
 * Matches the leading version-looking token in arbitrary command output.
 *
 * Deliberately tolerant of a two-segment release (`0.7`): a version does not
 * have to have three parts, and treating one as unparseable would silently
 * discard a perfectly good engine.
 */
const VERSION_TOKEN =
  /\d+(?:\.\d+)*(?:[-_.]?(?:a|b|c|rc|alpha|beta|pre|preview|post|rev|r|dev)\d*)*(?:\+[A-Za-z0-9.]+)?/;

const PEP440 =
  /^v?(\d+(?:\.\d+)*)(?:[-_.]?(a|b|c|rc|alpha|beta|pre|preview)[-_.]?(\d*))?(?:[-_.]?(post|rev|r)[-_.]?(\d*))?(?:[-_.]?(dev)[-_.]?(\d*))?(?:\+([A-Za-z0-9.]+))?$/;

/** Pre-release letters in ascending order; anything else sorts as `rc`. */
const PRE_RANK: Record<string, number> = {
  a: 0,
  alpha: 0,
  b: 1,
  beta: 1,
  c: 2,
  rc: 2,
  pre: 2,
  preview: 2,
};

/** Extract the version token from raw command output, e.g. `--version` stdout. */
export function extractVersion(output: string): string | undefined {
  return VERSION_TOKEN.exec(output)?.[0];
}

/**
 * Parse a PEP 440 version string, or return `undefined` when it is not one.
 *
 * A local label (`+unknown`, `+local`) parses but is ignored for ordering, so
 * an engine that cannot identify itself (`0.0.0+unknown`) simply sorts low.
 */
export function parseVersion(value: string | undefined): ParsedVersion | undefined {
  if (!value) {
    return undefined;
  }
  const match = PEP440.exec(value.trim().toLowerCase());
  if (!match) {
    return undefined;
  }
  const release = match[1].split(".").map((part) => Number.parseInt(part, 10));
  if (release.some((part) => !Number.isFinite(part))) {
    return undefined;
  }
  return { release, raw: value.trim() };
}

/** A version split into the two groups that must be compared independently. */
interface VersionKey {
  /** Numeric release segments, compared element-wise with zero padding. */
  release: number[];
  /** Pre/post/dev ranks, compared only once the release segments agree. */
  suffix: number[];
}

/**
 * Decompose a version into comparable groups.
 *
 * Release and suffix must stay separate rather than becoming one flat array:
 * `0.6` and `0.6.0` have release segments of different lengths, so a flat key
 * would shift the suffix ranks out of alignment and report the two as unequal.
 *
 * Suffix ranks follow PEP 440, giving `1.0.dev1 < 1.0a1 < 1.0 < 1.0.post1`.
 * Absent segments take the rank that sorts a plain release after its own
 * pre-releases and before its own post-releases.
 */
function versionKey(value: string): VersionKey | undefined {
  const match = PEP440.exec(value.trim().toLowerCase());
  if (!match) {
    return undefined;
  }
  const [, releaseText, preLetter, preNumber, postLabel, postNumber, devLabel, devNumber] = match;
  const release = releaseText.split(".").map((part) => Number.parseInt(part, 10));

  // An absent pre-release outranks any present one; present ones order by letter.
  const pre = preLetter
    ? [0, PRE_RANK[preLetter] ?? 2, preNumber ? Number.parseInt(preNumber, 10) : 0]
    : [1, 0, 0];
  // A post-release outranks the plain release it follows.
  const post = postLabel ? [1, postNumber ? Number.parseInt(postNumber, 10) : 0] : [0, 0];
  // A dev release ranks below whatever it is a dev release of.
  const dev = devLabel ? [0, devNumber ? Number.parseInt(devNumber, 10) : 0] : [1, 0];

  return { release, suffix: [...pre, ...post, ...dev] };
}

/** Compare two numeric arrays element-wise, treating a missing tail as zeros. */
function comparePadded(left: number[], right: number[]): number {
  const width = Math.max(left.length, right.length);
  for (let index = 0; index < width; index += 1) {
    const difference = (left[index] ?? 0) - (right[index] ?? 0);
    if (difference !== 0) {
      return difference < 0 ? -1 : 1;
    }
  }
  return 0;
}

/** Compare two version strings: negative, zero, or positive, like a sort callback. */
export function compareVersions(left: string, right: string): number {
  const a = versionKey(left);
  const b = versionKey(right);
  if (!a || !b) {
    // Callers check parseability first; an unparseable pair has no ordering.
    return 0;
  }
  // Trailing zeros are insignificant, so `0.6` and `0.6.0` compare equal.
  const byRelease = comparePadded(a.release, b.release);
  return byRelease !== 0 ? byRelease : comparePadded(a.suffix, b.suffix);
}

/**
 * Whether *candidate* is strictly newer than *baseline*.
 *
 * Strictly, so that a tie keeps the bundled engine: when both report the same
 * version, the copy the extension ships and was tested against should win.
 */
export function isNewerThan(candidate: string | undefined, baseline: string | undefined): boolean {
  if (!candidate || !parseVersion(candidate)) {
    return false;
  }
  if (!baseline || !parseVersion(baseline)) {
    return true;
  }
  return compareVersions(candidate, baseline) > 0;
}
