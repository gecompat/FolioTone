# ADR-0007: Music uses Work, Recording, Release Group and Release as separate concepts

- Status: Accepted
- Date: 2026-08-08

## Context

A `Recording -> Release` model is insufficient for classical music and many non-classical cases. A composition can have many performances/recordings; the same recording can appear on many concrete releases; related concrete releases can represent one logical album/release concept.

Classical music additionally requires work hierarchies, composer/arranger roles, catalog designations and explicit distinctions between a composition and a performed recording.

## Decision

FolioTone models at least these distinct music concepts:

- `MusicWork` — composition/work independent of a particular performance;
- `MusicWorkRelation` — hierarchy/derivation relationships such as part-of, arrangement, translation, revision and derivative;
- `Recording` — a particular recorded performance/production;
- `ReleaseGroup` — logical album/single/release concept;
- `Release` — concrete issuing/edition;
- `ReleaseRecording` — placement of a Recording on a Release.

Agents connect through typed roles such as composer, lyricist, arranger, conductor and performer rather than through a single artist string.

Classical catalog designations are represented as namespace/system + value and are not restricted to a hard-coded closed list.

## Consequences

- W1 must include these entities/relationships before persistence is frozen.
- Matching can distinguish same composition, same recording and same release as different relation levels.
- Classical work movements/parts can be represented without assuming one track equals one work.
- Remasters, remixes, alternate releases and performance variants can be modeled without collapsing fundamentally different concepts.
- MusicBrainz can be used as an external provider, but its schema remains behind an adapter and does not become FolioTone's core schema.
