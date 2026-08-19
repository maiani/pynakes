/**
 * Tests for version ordering. These run under `node --test` against the
 * compiled output and never load the `vscode` module.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { compareVersions, extractVersion, isNewerThan, parseVersion } from "../version.js";

test("orders plain releases by numeric segment, not lexically", () => {
  assert.equal(compareVersions("0.6.0", "0.5.1"), 1);
  assert.equal(compareVersions("0.9.0", "0.10.0"), -1);
  assert.equal(compareVersions("1.0.0", "0.99.99"), 1);
  assert.equal(compareVersions("0.6.0", "0.6.0"), 0);
});

test("treats omitted trailing zeros as equal", () => {
  assert.equal(compareVersions("0.6", "0.6.0"), 0);
  assert.equal(compareVersions("1", "1.0.0.0"), 0);
});

test("orders pre-, post-, and dev-releases per PEP 440", () => {
  assert.equal(compareVersions("0.6.0.dev1", "0.6.0"), -1);
  assert.equal(compareVersions("0.6.0a1", "0.6.0"), -1);
  assert.equal(compareVersions("0.6.0a1", "0.6.0b1"), -1);
  assert.equal(compareVersions("0.6.0b1", "0.6.0rc1"), -1);
  assert.equal(compareVersions("0.6.0.post1", "0.6.0"), 1);
  assert.equal(compareVersions("0.6.0a1.dev1", "0.6.0a1"), -1);
  assert.equal(compareVersions("0.6.0.dev1", "0.5.9"), 1);
});

test("ignores local labels when ordering", () => {
  assert.equal(compareVersions("0.6.0+local", "0.6.0"), 0);
  assert.equal(compareVersions("0.6.0+abc", "0.6.1"), -1);
});

test("parses the version strings the engine actually prints", () => {
  assert.deepEqual(parseVersion("0.6.0")?.release, [0, 6, 0]);
  assert.deepEqual(parseVersion("0.0.0+unknown")?.release, [0, 0, 0]);
  assert.deepEqual(parseVersion(" 0.6.0 ")?.release, [0, 6, 0]);
  assert.equal(parseVersion("not-a-version"), undefined);
  assert.equal(parseVersion(undefined), undefined);
});

test("extracts a version from surrounding command output", () => {
  assert.equal(extractVersion("0.6.0\n"), "0.6.0");
  assert.equal(extractVersion("pynakes, version 0.6.0"), "0.6.0");
  assert.equal(extractVersion("0.7.0.dev3+g1234"), "0.7.0.dev3+g1234");
  assert.equal(extractVersion("no version here"), undefined);
});

test("prefers the installed engine only when it is strictly newer", () => {
  assert.equal(isNewerThan("0.7.0", "0.6.0"), true);
  assert.equal(isNewerThan("0.6.0", "0.6.0"), false, "a tie must keep the bundled engine");
  assert.equal(isNewerThan("0.5.1", "0.6.0"), false);
  assert.equal(isNewerThan("0.7.0.dev1", "0.6.0"), true);
});

test("an engine that cannot identify itself never wins", () => {
  assert.equal(isNewerThan("0.0.0+unknown", "0.6.0"), false);
  assert.equal(isNewerThan(undefined, "0.6.0"), false);
  assert.equal(isNewerThan("garbage", "0.6.0"), false);
});

test("an unknown bundled version yields to any parseable installed one", () => {
  assert.equal(isNewerThan("0.5.0", undefined), true);
  assert.equal(isNewerThan("0.5.0", "garbage"), true);
});
