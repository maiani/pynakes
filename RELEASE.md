# Coordinated 0.7.0 Beta and editor 0.1.0 Alpha release

Finish engine readiness first, then move to editor work. Publish **pynakes
0.7.0 Beta** and **editor 0.1.0 Alpha** together after both are ready. The
engine's Python API remains experimental until 1.0. This checklist records
preparation, not publication; versioning remains driven by setuptools-scm and
release tags. Local RC artifacts are validation builds, not a separate PyPI
publication milestone.

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
   0.7.1 or 0.8. Once the engine is ready, move to the editor track.

## Editor readiness (after the engine)

Complete editor acceptance against the ready engine, keeping all bibliography
logic in the engine. Run `npm run compile && npm test` with the engine tests
required. Finish the editor alpha gates before either release is published.

`npm run package:prerelease` produces the 0.1.0 VSIX with its prerelease marker.
Set the engine override to the version being tested and choose a Python 3.12
build interpreter with `PYNAKES_VENDOR_PYTHON`. Verify the marker, bundled
engine metadata/version and launcher smoke checks. Exclude local validation
artifacts from the VSIX. Verify the publisher/account setup for the selected
distribution channel.

## Coordinated publication

After both tracks are ready, review and commit their release changes, push the
commit and require its CI matrix to pass. Date the final changelogs. Rebuild
from the clean release commit and validate both artifacts. Local uncommitted
preparation artifacts are not the artifacts to publish.

The `v0.7.0` tag push triggers the existing engine release workflow: validate
ancestry/changelog, build, test the wheel on Linux/macOS/Windows, publish PyPI,
then create the GitHub release. Do not push that tag until the editor is ready
for the same release window. Publish editor 0.1.0 as an Alpha prerelease through
the selected publisher account and verify both releases are available before
announcing them. The two version numbers and compatibility policies remain
independent even though publication is coordinated.

## Local evidence and remaining gates

Artifacts, logs and hashes live in `.cache/stage7/`, ignored by Git. Engine
readiness is assessed before further editor feature work. Manual acceptance,
remaining editor work and coordinated publication stay open until actually
completed; a local RC build alone does not close Stage 7.
