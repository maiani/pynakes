# Engine v0.9.0 release preparation

The engine release is **0.9.0 Beta**, authorized for publication on
2026-11-04 after final review. The version comes from the `v0.9.0` tag.
The editor is versioned separately and remains unpublished; the Python API
remains experimental until 1.0.

## Final review, 2026-11-04

The reviewed engine revision is `813a9c3`; the release-preparation commit only
updates the changelog date and release documentation. All five handoff tasks
are complete, each in its own commit. Review additionally fixed duplicate-key
precedence during sorted insertion and cancellation of a newly staged addition,
and extracted CLI helpers to keep every Python source module below 800 lines.

- Source suite: **3,541 tests passed, 93.65% coverage**, on Python 3.15.
- Ruff lint and format, ty, generated command-reference check and strict
  Zensical documentation build passed.
- Editor: **172 tests passed**, with engine checks required; no editor release.
- Clean-revision wheel and sdist built as 0.9.0; strict Twine and release
  version checks passed. Rehearsal artifacts are not publication artifacts.
- Installed-wheel suite: **3,541 tests passed** in a fresh Python 3.12
  environment, with imports confirmed from `site-packages` and no checkout
  `src/` available.
- All five reference agent-evaluation solutions passed on that installed wheel.
  This is deterministic engine validation, not a new blind-agent assessment.

Local logs and artifacts are ignored under `.cache/release-0.9.0/`, including
`final-source-tests.log`, `editor-tests.log`, `final-build.log`,
`final-wheel-tests.log`, `final-reference-baseline.json` and `FINAL-SHA256SUMS`.
The tagged workflow builds the distributions it publishes, retests the wheel
on Linux, Windows and macOS, then publishes to PyPI and GitHub. Publication
still requires successful CI on the exact release revision and verification
of the published artifacts and a fresh PyPI installation.

The historical blind evaluation below remains **3/5**; its two agent behavior
failures have not been rerun in this review. The engine reports conflicts and
preserves files, but agent adherence to the updated conflict guidance is not
newly established. Private-library acceptance remains owner-run; this review
uses the committed synthetic and historical fixtures.

## Historical candidate evidence (2026-10-28)

The scope is in [CHANGELOG.md](CHANGELOG.md): the settled command surface
(`corpus` retired, `groups` renamed, `ref lookup`, encoding and title
protection in `normalize`), bibliography links (`biblink`), the field-report
follow-ups and fixes, and documentation on Zensical. Forms deprecated in 0.9.0
keep working, hidden, until 0.10.0.

| Scope | Recorded result | Evidence |
| --- | --- | --- |
| Candidate source (`b87bdae`) | 3,425 tests, 93.62% coverage; Ruff, ty and the strict Zensical build pass | `.cache/release-0.9.0/source-tests.log` |
| Source after the fixes | 3,436 tests pass | local run, 2026-10-28 |
| Distributions | Wheel and sdist built as 0.9.0; `twine check --strict` and `check_release.py --tag v0.9.0` pass | `.cache/release-0.9.0/SHA256SUMS`, `build.log` |
| Reference evaluation | All five reference solutions pass on the installed wheel (Python 3.12.14) | `evals/agent/runs/2026-10-28-claude-v090/baseline.json` |
| Blind agent evaluation | Three of five tasks pass; `duplicate-conflict` and `concurrent-edit` fail edit authorization after a correctly reported refusal. The conflict guidance has since changed; a rerun of those two tasks on the release revision is pending | [Run README](evals/agent/runs/2026-10-28-claude-v090/README.md) |
| CI on the pushed branch | Every job passed except the lowest-dependency job, which failed two help-listing tests; fixed in `b364a40` and verified locally with typer 0.26.0, click 8.1.0 and rich 13.8.0 | PR #6 |
| Installed-wheel suite | Not run locally; the release workflow runs it on every platform | — |
| Real-bibliography smoke checks | Pending: the owner's step, on private libraries | — |

Evidence lives in the ignored `.cache/release-0.9.0/`: logs, artifact hashes,
the reference baseline and the blind-run working files. The committed run
bundle keeps the transcripts with full responses and verbatim answers. The
orchestrator's review does not replace owner acceptance.

## Local candidate validation

Rehearsal artifacts built from an uncommitted working tree must not be
published.

1. Run `pytest --cov --cov-fail-under=90`, `ruff check src tests`,
   `ruff format --check src tests`, `ty check`, and `zensical build --strict`.
2. Build and inspect the distributions:

   ```sh
   SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PYNAKES=0.9.0 python -m build --outdir .cache/release-0.9.0/dist
   python -m twine check --strict .cache/release-0.9.0/dist/*
   python .github/scripts/check_release.py --tag v0.9.0 --dist .cache/release-0.9.0/dist
   ```

   The override is process-local. Check the wheel and sdist versions, package
   data and the Beta classifier.
3. Install the wheel in a fresh virtual environment and run the agent
   evaluation against it, as [evals/agent/README.md](evals/agent/README.md)
   describes: `measure` for the reference baseline, `prepare`, one isolated
   agent per task given only its brief, the reviewer's `review.json`, then
   `collect`. Commit the bundle under `evals/agent/runs/`. Reference solutions
   verify the engine; they are not blind runs or owner acceptance.
4. Copy tests, docs, README, pyproject, `.pre-commit-hooks.yaml`, scripts and
   evals into a directory without `src/` and run `pytest -o pythonpath=` there
   with the wheel's environment. Confirm `pynakes.__file__` points into its
   `site-packages` and the version is 0.9.0. The release workflow repeats this
   on every platform.
5. Exercise disposable copies of real bibliographies: round-trip, inspect and
   lint, format preview and apply, reparse, normalization idempotence, bounded
   reads, analysis, and `biblink check` between a manuscript bibliography and
   its master. Hash the originals before and after, and keep private content
   and logs ignored. This step is the owner's: it uses private libraries.

## Final release gates

- Owner acceptance of the candidate and the evidence above.
- The full CI matrix green on the exact release revision: Python 3.12–3.15 on
  Linux, macOS and Windows, the dependency floors, documentation, the editor
  and packaging.
- Merge to `main` when authorized; rebuild and validate from the clean release
  commit. The release guard checks ancestry and a non-empty 0.9.0 changelog
  section.
- Only after publication is authorized, create and push `v0.9.0`. That push
  runs the release workflow: build, installed-wheel tests on every platform,
  PyPI publication and the GitHub release. Verify the published metadata,
  hashes and a fresh installation from PyPI before calling the release done.

## Editor handoff

The editor already runs the renamed commands (`batch`, the `groups`
subcommands, the `groups_list` insight). Its version, changelog, manual
acceptance, VSIX packaging and publisher setup are separate from the engine
release; do not infer editor publication from engine publication.
