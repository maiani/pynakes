# Bundled journal abbreviation data

The CSV files in this directory are vendored, unmodified, from
[abbrv.jabref.org](https://github.com/JabRef/abbrv.jabref.org) — the same
journal abbreviation lists JabRef itself ships and uses for its "Manage
journal abbreviations" feature.

- Source: <https://github.com/JabRef/abbrv.jabref.org>
- License: CC0 1.0 Universal (public domain dedication) — see upstream
  `LICENSE.md`. No attribution is legally required; this notice is kept for
  traceability.
- Vendored from commit `8a3c78adb840669b3eeb97280684f94ad5af0fa4` (2026-08-05T04:57:16Z), branch `main`.
- Files (see upstream `journals/README.md` for what each list covers):
  - `journal_abbreviations_acs.csv`
  - `journal_abbreviations_aea.csv`
  - `journal_abbreviations_ams.csv`
  - `journal_abbreviations_annee-philologique.csv`
  - `journal_abbreviations_astronomy.csv`
  - `journal_abbreviations_dainst.csv`
  - `journal_abbreviations_entrez.csv`
  - `journal_abbreviations_general.csv`
  - `journal_abbreviations_geology_physics.csv`
  - `journal_abbreviations_geology_physics_variations.csv`
  - `journal_abbreviations_ieee.csv`
  - `journal_abbreviations_ieee_strings.csv`
  - `journal_abbreviations_lifescience.csv`
  - `journal_abbreviations_mathematics.csv`
  - `journal_abbreviations_mechanical.csv`
  - `journal_abbreviations_medicus.csv`
  - `journal_abbreviations_meteorology.csv`
  - `journal_abbreviations_sociology.csv`
  - `journal_abbreviations_ubc.csv`

These are used as-is (including any upstream data quirks, e.g. occasional
unescaped commas in an abbreviation field) — pynakes does not edit them by
hand. Refresh with:

```bash
python scripts/update_journal_abbreviations.py
```
