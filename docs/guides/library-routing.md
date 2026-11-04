# Routing references into a Library

A personal Library can keep manageable member bibliographies without imposing
one subject taxonomy. For example, `books.bib` holds books across all subjects,
while `engines.bib` holds other references about engines. A reference has one
home; groups, keywords and search provide overlapping topical views.

## Manifest policy

Create the member files first and declare relative paths:

```toml
pynakes-library = 1
name = "Research"
members = ["books.bib", "engines.bib", "inbox.bib"]

[routing]
fallback = "inbox.bib"

[[routing.rules]]
name = "Books across subjects"
where = "type in [book, mvbook, booklet]"
destination = "books.bib"
priority = 100

[[routing.rules]]
name = "Engine research"
where = 'keywords contains "engines"'
destination = "engines.bib"
priority = 10
```

Each rule requires `name`, `where`, `destination` and an integer `priority`.
Names must be unique. Unknown keys, invalid selectors and destinations outside
membership (including excluded members) are errors. Rules use the existing
`--where` grammar; predicates needing manuscript citation state or a member's
saved queries are unavailable here. Member-specific formatting settings remain
in each `.bib`; cross-member placement policy belongs in this manifest, not in
`pynakes-meta` or `metadata set`. `--destination` / `destination=` overrides that policy
for one addition. There is no separate routing language or metadata namespace.

Selection is deterministic:

1. Check every member for existing work or citation-key candidates. Existing
   references need review, even if a different destination was requested.
   Incomplete member reads block additions because uniqueness cannot be checked.
2. An explicit destination selects a declared member.
3. Otherwise, the highest numerical priority among matching rules wins. Several
   winning rules selecting the same member agree; different winning destinations
   are ambiguous. Rule order does not break a tie.
4. No matching rule uses `fallback`; without one, placement remains unresolved.

The inbox is for unmatched references. Ambiguous matches remain unwritten until
reviewed; there is no implicit unattended tie-break. Rules do not infer subjects
from PDF contents or call a provider. Book chapters can be included explicitly
by adding `inbook` and `incollection` to a rule if that is the desired policy.

## Preview and add

```bash
pynakes library add research.library.toml Example1900 \
  --type book --field 'title=Imaginary Engines' \
  --field 'author=Example, Alice' --field year=1900 \
  --field keywords=engines --dry-run --diff --json
```

The report names the destination and reason, every matching rule with its
priority, and the bibliography diff. Here the book rule wins over the subject
rule. Use `--destination inbox.bib` to explicitly choose another member; relative paths
resolve from the manifest directory, independently of the working directory.

Apply by omitting `--dry-run`. For a reviewed preview, pass both its
`library_sha256` as `--expect-library-sha256` and its destination
`source_sha256` as `--expect-sha256`. Changing routing rules, member bytes or
pattern membership invalidates the Library fingerprint. The normal modifying
JSON envelope reports the destination in `file`, plus `manifest`, `routing`
and `library_sha256`. Routing/existing-work conflicts exit 2 with options;
invalid inputs or incomplete reads exit 1. Missing required fields are warnings,
consistent with `ref add`.

This initial command adds supplied metadata. DOI acquisition and PDF inspection
remain in their existing commands; acquiring and routing a PDF in one Library
transaction is not implemented yet. `library add` does not copy, move, fetch or
rewrite materials. Supplied `file` links are interpreted relative to the chosen
bibliography, just as with `ref add`.

## Python staging

```python
from pynakes import BibEntry, Library

library = Library.open("research.library.toml")
entry = BibEntry(
    key="Example1900",
    type="book",
    fields={"title": "Imaginary Engines", "author": "Example, Alice", "year": "1900"},
)
decision = library.route(entry)  # offline preview against the held Library view
print(decision.to_dict())
addition = library.stage_entry(entry)  # raises LibraryRoutingError if review is needed
print(addition.bibliography.diff())
addition.bibliography.commit()  # writes one member; rechecks the entire read set
```

`stage_entry` stages a copy of the supplied type/key/fields, using the destination
bibliography's normal insertion behavior. It does not transfer raw source text,
entry comments or private material ownership from another bibliography.
`reset()` discards the staged addition. Reopen the Library after a commit before
staging another addition: a held Library is a snapshot, not a live shared writer.
Commit checks detect changes to the manifest and member data, including another
member acquiring a duplicate after the preview. They are optimistic checks,
not a filesystem lock across the collection; `force=True` does not bypass them.

Existing-work checks reuse the engine's conservative exact/probable/conflict
identity evidence. A repeated citation key never proves work identity. An exact
match is reported as `existing` and prevents a second copy; probable matches,
multiple matches and conflicting shared identifiers require review. Preprint
and published classes are not silently collapsed. General cross-file identity
reports and reconciliation remain planned.

## Pinax materials

Each member can own its Pinax under the Library directory, for example
`materials/books` and `materials/inbox`. Distinct roots avoid citation-key
collisions between member stores. This keeps materials inside the personal
Library without changing the current bibliography-owned Pinax model.

Routing new metadata is implemented. Moving an existing reference between
members together with its PDFs, annotations and provenance is not. A shared
Library material store needs an identity contract independent of member citation
keys; do not point multiple Pinax owners at one mutable root as a workaround.
