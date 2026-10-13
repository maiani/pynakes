# Engine 0.7.0 Beta release; editor 0.1.0 Alpha follows

Release **pynakes 0.7.0 Beta first**, as requested on 2026-10-13. The editor
0.1.0 Alpha follows independently after its own acceptance and publisher setup.
The engine's Python API remains experimental until 1.0. Versioning is driven
by setuptools-scm and release tags; local RC artifacts are validation builds,
not separate PyPI milestones. Current release evidence belongs in the ignored
`.cache/release-0.7.0/`; earlier rehearsals remain in `.cache/stage7/`.

## Engine readiness

1. Verify the full CI matrix for the engine commit, including documentation,
   lowest dependencies and packaging.
2. Build and inspect local validation artifacts without creating a tag:

   ```bash
   SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PYNAKES=0.7.0rc1 python -m build --outdir .cache/stage7/dist
   python -m twine check --strict .cache/stage7/dist/*
   python .github/scripts/check_release.py --tag v0.7.0rc1 --dist .cache/stage7/dist
   ```

   Use `0.7.0` and `v0.7.0` for final-version rehearsal artifacts in a separate
   output directory. Distribution checks only inspect artifact versions;
   they do not establish tag ancestry or publish anything. The override is
   process-local; do not put it in package configuration.
3. Install the wheel in a fresh virtual environment. Run the full suite from
   a copy of `tests/`, docs, README, pyproject and `.pre-commit-hooks.yaml`, with
   no `src/` and with `pytest -o pythonpath=`. Confirm imports come from that
   environment's `site-packages`, report the intended version and carry the
   Beta classifier. Run Ruff, ty and strict MkDocs in the source checkout.
4. Exercise the wheel on disposable copies of real libraries: inspect/lint,
   preview and apply layout changes, reparse, check normalization idempotence,
   and confirm originals' hashes are unchanged. Keep private copies/logs local;
   never commit entries, materials, titles or keys from them. Limit
   normalization to in-entry steps so copied Pinax/TeX metadata cannot redirect
   writes into the original research project.
5. Record manual agent acceptance separately: tasks, wheel, outcomes and any
   contract/data-loss failures. `test_contract.py` and `test_workflows.py` are
   automated engine tests, not an agent evaluation. The former hand-run
   harness was deliberately removed in `0ef2951`.
6. During candidate observation, fix regressions only; new features wait for
   0.8; 0.7.x patches fix bugs only. Editor readiness does not gate the engine.

## Editor readiness (after the engine)

Complete editor acceptance against the ready engine, keeping all bibliography
logic in the engine. Run `npm run compile && npm test` with the engine tests
required. Finish the editor alpha gates before publishing the extension.

`npm run package:prerelease` produces the 0.1.0 VSIX with its prerelease marker.
Set the engine override to the version being tested and choose a Python 3.12
build interpreter with `PYNAKES_VENDOR_PYTHON`. Verify the marker, bundled
engine metadata/version and launcher smoke checks. Exclude local validation
artifacts from the VSIX. Verify the publisher/account setup for the selected
distribution channel.

## Engine publication

Review and commit the engine release changes, push the commit and require its
full CI matrix to pass. Date the engine changelog. Rebuild from the clean
release commit and validate the artifacts; uncommitted rehearsal artifacts are
not the artifacts to publish.

The `v0.7.0` tag push triggers the engine release workflow: validate
ancestry/changelog, build, test the wheel on Linux/macOS/Windows, publish PyPI,
then create the GitHub release. Verify both the package metadata and a fresh
installation from PyPI before reporting completion. Leave the editor changelog
undated and do not publish a VSIX as part of this engine release.

## Evidence and remaining gates

Record artifact hashes, command exit codes, installed-wheel import location,
manual agent acceptance and remote run URLs in `.cache/release-0.7.0/`.
A local build or green source test suite alone does not complete the release.
The editor's manual acceptance, publisher/channel setup and publication remain
open until separately completed.
