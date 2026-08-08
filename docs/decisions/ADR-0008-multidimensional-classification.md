# ADR-0008: Classification is multidimensional and provenance-preserving

- Status: Accepted
- Date: 2026-08-08

## Context

A single genre string cannot represent useful distinctions across e-books and music. Classical music especially requires dimensions such as period, form and instrumentation in addition to a broad genre/domain. Different external providers may also use incompatible taxonomies.

## Decision

FolioTone models classification as typed facets/assertions rather than one canonical `genre` column.

Examples include:

E-books:
- domain;
- genre/subgenre;
- subject/topic/theme;
- audience;
- language;
- form.

Music:
- broad domain/genre;
- subgenre/style;
- classical period/era;
- musical form/work type;
- instrumentation/ensemble type;
- language/context where useful.

Each classification retains source/provenance, confidence where applicable and taxonomy/provider context.

`Classical` as a broad music domain and the `Classical period` as a historical era are distinct values in distinct dimensions.

## Consequences

- Conflicting provider classifications may coexist without data loss.
- Canonical/local classifications can be selected later without overwriting source assertions.
- Search/filtering can use independent facets.
- Calibre tags can later receive a flattened projection without forcing the FolioTone core to become flat.
- Classification rules and provider mappings must be versioned derived logic.
