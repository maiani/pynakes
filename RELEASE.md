# Engine v0.8.0 release preparation

The engine candidate is **0.8.0 Beta**, prepared on 2026-10-21. The editor is
independently versioned and follows engine acceptance. The Python API remains
experimental until 1.0. Preparation does not publish a package or create a tag.
The dated changelog is a draft release section; update its date if publication
happens later. Versioning comes from setuptools-scm and the eventual `v0.8.0` tag.

## Candidate evidence

Feature scope is recorded in [CHANGELOG.md](CHANGELOG.md); linked bibliographies
are deferred to v0.9 in [DEVPLAN.md](DEVPLAN.md).

| Scope | Recorded result | Evidence |
| --- | --- | --- |
| Current source after code consolidation | 3,339 tests (93.49% coverage); Ruff, types and strict docs pass; 4,758 encoding comparisons and both dialects' schema comparisons match previous behavior | `.cache/release-0.8.0/consolidation/CHECKPOINT.md` |
| Before code consolidation, including selection export and field encoding | 3,339 source tests (93.49% coverage), 3,339 installed-wheel tests; Ruff, types, strict docs, build, Twine and artifact-version checks pass | `.cache/release-0.8.0/selection-encoding/CHECKPOINT.md` |
| Earlier editor-contract checkpoint | Five reference tasks and two disposable real-library smoke checks pass | `.cache/release-0.8.0/editor-contracts/CHECKPOINT.md` |
| Blind agent evaluation | All five tasks passed mechanical and semantic review on the recorded wheel | [Evaluation review](evals/agent/REVIEW-0.8.md) and its linked raw run bundle |

Earlier wheel, reference, smoke and blind-agent results describe their recorded
artifacts. The consolidation has source validation; its installed-wheel checks
remain part of the clean-commit rebuild. The evaluation review retains
historical failures; orchestrator review does not replace owner acceptance.

## Local candidate validation

Evidence lives in ignored `.cache/release-0.8.0/`: source and wheel test logs,
artifact hashes, strict documentation build, performance measurements, reference
evaluation baseline and private-library smoke results. `CHECKPOINT.md` records
the exact outcome and limitations. Rehearsal artifacts built from an uncommitted
working tree must not be published.

1. Run `pytest --cov --cov-fail-under=90`, `ruff check src tests`,
   `ruff format --check src tests`, `ty check`, and `mkdocs build --strict`.
2. Measure the five reference evaluation solutions with
   `python scripts/agent_eval.py measure --out .cache/release-0.8.0/agent-baseline.json`.
   Read [the evaluation review](evals/agent/REVIEW-0.8.md). Reference solutions
   verify the engine; they do not count as blind agent runs or owner acceptance.
3. Record scale baselines using `scripts/bench_scale.py --only bounded --only
   analyze --only coauthors`, with `--shape unrelated` and `--shape dense`.
   Save JSON with `--out`; record entry counts, Python/platform and memory
   measurement scope. Do not turn single-machine timings into CI thresholds.
4. Build and inspect candidate distributions:

   ```sh
   SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PYNAKES=0.8.0 python -m build --outdir .cache/release-0.8.0/dist
   python -m twine check --strict .cache/release-0.8.0/dist/*
   python .github/scripts/check_release.py --tag v0.8.0 --dist .cache/release-0.8.0/dist
   ```

   The override is process-local. Check both wheel and sdist versions, package
   data and the Beta classifier. The private analysis implementation must be
   present; the removed public `pynakes.coauthors` module must be absent.
5. Install the wheel in a fresh virtual environment. Copy tests, docs, README,
   pyproject, `.pre-commit-hooks.yaml`, scripts and evals into a test directory
   without `src/`. Run `pytest -o pythonpath=` there, without source `PYTHONPATH`.
   Confirm `pynakes.__file__` points into that environment's `site-packages` and
   its version is 0.8.0. Keeping scripts/evals exercises the new reference task.
6. Exercise disposable copies of real bibliographies: round-trip, inspect/lint,
   preview/apply formatting, reparse, normalization idempotence, bounded reads,
   analysis and co-authorship reports. Hash the originals before and after.
   Restrict normalization to in-entry steps; do not follow copied metadata into
   original TeX/Pinax projects. Keep all private content and logs ignored.

## Final release gates

- Obtain owner acceptance of the candidate and the evidence scope above.
- Review and commit the release preparation, then push/open the candidate PR
  when authorized. Require the full CI matrix on that exact revision, including
  Python 3.12–3.15, Linux/macOS/Windows, dependency floors and packaging.
- Merge to `main` when authorized; rebuild and validate from the clean release
  commit. The release guard checks ancestry and a nonempty 0.8.0 changelog.
- Only after publication authorization, create and push `v0.8.0`. That push
  triggers the release workflow: build, installed-wheel tests on all platforms,
  PyPI publication and GitHub release creation. Verify the published metadata,
  hashes and a fresh PyPI installation before declaring release complete.

## Editor handoff

Once the engine candidate is accepted, work on the editor against 0.8.0 using
[the editor roadmap](DEVPLAN.md#editor-track) for pending command wiring.
Keep bibliography logic in the engine. Compile and test with the extension's own
Node toolchain, exercise the JSON envelope and new read/analysis capabilities,
and validate the vendored engine and launcher. The editor's version, changelog,
manual acceptance, VSIX packaging and publisher/channel setup are separate.
Do not infer editor publication from engine readiness or publication.
