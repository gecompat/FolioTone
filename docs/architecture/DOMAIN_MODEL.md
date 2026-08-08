# Planned Domain Model

This document defines the conceptual model for W1. Exact Python/SQL representations are intentionally deferred to W1 implementation and should be captured in an ADR if they introduce material trade-offs.

The model deliberately separates physical files, observed metadata, authority identities, canonical entities, relations and review decisions.

## Physical/index layer

### File

Represents a concrete filesystem object, not a book, work, recording or release.

Expected fields include:

- stable internal ID;
- scan root / storage identity;
- relative path and filename;
- size and filesystem timestamps used as observations;
- presence state;
- first/last seen timestamps;
- generic hashes/fingerprints with algorithm/version;
- media type and analysis state.

Absolute private host paths should not be required in domain-level exports or logs when a scan-root-relative path is sufficient.

### ScanRoot / ScanRun / FileObservation

Needed to distinguish file state from storage availability and to make incremental scans auditable.

A temporarily unavailable root must not turn all previously indexed files into deleted files.

## Provenance/value layer

Canonical values must not overwrite evidence.

### SourceAssertion / ValueAssertion

A generic assertion concept should be able to retain:

- target entity/field;
- value;
- state;
- source/provenance;
- extractor/parser/provider/rule version;
- confidence where applicable;
- observation/fetch timestamp where relevant;
- explanation/supporting evidence.

Planned value states:

- `OBSERVED`
- `DERIVED`
- `EXTERNAL`
- `CANONICAL`
- `USER_CONFIRMED`

The exact class/table decomposition is a W1 implementation decision, but these distinctions are mandatory.

## Authority/contributor layer

### Agent

Represents a person, group or organization that can participate in a work, edition, recording or release.

Initial `AgentType` vocabulary:

- `PERSON`
- `GROUP`
- `ORGANIZATION`
- `ENSEMBLE`
- `ORCHESTRA`
- `CHOIR`
- `UNKNOWN`

### AgentName

Represents one name form for an Agent while preserving the observed/provider spelling.

Initial name types:

- `CANONICAL`
- `SORT_NAME`
- `ALIAS`
- `PSEUDONYM`
- `CREDITED_AS`
- `TRANSLITERATION`
- `FORMER_NAME`

Language/script/provenance should be representable where known.

### ExternalIdentifier

Namespaced identifier associated with the entity type for which it is valid. Examples include GND, Wikidata/Open Library/MusicBrainz IDs, ISBN, ISRC, ISWC, barcode and catalog identifiers.

Identifier namespace/provider is mandatory; raw identifier strings are not assumed globally unique.

### Contribution / Credit

Associates an Agent with another entity through a role instead of flattening roles into string columns.

Example roles:

Books:
- author;
- editor;
- translator;
- illustrator;
- narrator.

Music:
- composer;
- lyricist;
- librettist;
- arranger;
- conductor;
- performer/vocalist/instrument-specific roles.

Role vocabularies may expand without changing the Agent identity model.

## E-book layer

### Work

The intellectual work independent of edition/format. Evidence may include normalized title, contributors, language/original-title relationships and external identifiers.

### Edition

A publication/edition/translation represented by FolioTone. Expected evidence may include publisher, publication date, language, ISBN, edition statement, translator/other credits, series data and normalized content fingerprint.

One Work can have multiple Editions. Different translations remain distinguishable even when they represent the same Work.

### Series / SeriesMembership

Represents bibliographic series explicitly rather than only as a free-form tag.

Series positions must allow non-integer and uncertain representations because real collections contain positions such as `0`, `1.5`, prequel/omnibus labels and provider disagreements.

### File relationship

One Edition may be represented by one or more files/formats. Identical bytes are a file-level relation; same edition is a bibliographic/content relation.

## Music layer

### MusicWork

Represents the composition/work independent of any particular recorded performance.

Examples range from a modern song composition to a classical symphony, opera, movement or other work unit appropriate to the source model.

### MusicWorkRelation

Supports structured relationships between MusicWorks, initially including:

- `PART_OF`
- `ARRANGEMENT_OF`
- `TRANSLATION_OF`
- `DERIVED_FROM`
- `REVISION_OF`

A track boundary must not automatically imply a separate MusicWork.

### CatalogDesignation

Represents work-catalog identifiers as system/namespace + value. Examples may include BWV, K/KV, Hob., D, RV, HWV and WoO, but the domain model must not hard-code a closed list.

### Recording

A particular recorded performance/production independent of the album/release on which it appears.

### ReleaseGroup

A logical album/single/release concept grouping related concrete Releases.

### Release

A concrete published issuing/edition with release-level metadata such as title, release artist/credits, date, territory, label, catalog number, barcode, format/packaging and disc count where available.

### ReleaseRecording

Associates a Recording with a Release and carries release-specific placement such as disc number, track number, title variation, duration observation and credits.

This many-to-many association avoids the incorrect assumption that a Recording belongs to exactly one Release.

## Classification layer

### ClassificationAssertion

Classification is modeled as typed facets with provenance, taxonomy/provider context and confidence where applicable.

Possible dimensions include:

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
- language/context.

Different provider classifications may coexist. `Classical` as a broad music domain is distinct from the `Classical period` as an era.

## Entity-resolution layer

### FieldCandidate

Represents a parsed/derived candidate value from filename, path context, metadata or another local inference source. It does not directly overwrite canonical metadata.

### EntityResolutionCandidate

Represents a proposed mapping between an observed/derived value and an Agent/Work/Edition/MusicWork/Recording/ReleaseGroup/Release or external authority entity.

Expected properties include candidate entity, score/confidence, source/provider, explanation and resolution-rule/provider version.

### AuthorityCache / ExternalProviderState

Persistent runtime concepts used to avoid repeated online queries and to version local imported datasets/provider results. Concrete cache schema belongs to persistence/adapters, not to domain business rules.

## Matching layer

### Relation

A classified relationship between two entities/files. Relation type and confidence/review status are separate concepts.

Initial relation taxonomy:

File/content:
- `EXACT_DUPLICATE`
- `CONTENT_DUPLICATE`
- `FORMAT_VARIANT`
- `QUALITY_VARIANT`
- `TRANSCODE`

E-book:
- `SAME_WORK`
- `SAME_EDITION`
- `DIFFERENT_EDITION`

Music:
- `SAME_MUSIC_WORK`
- `SAME_RECORDING`
- `SAME_RELEASE_GROUP`
- `SAME_RELEASE`
- `DIFFERENT_RECORDING`
- `DIFFERENT_RELEASE`

The exact final enum is refined during matching implementation, but different identity levels must not be collapsed.

### MatchStatus

Initial decision/status vocabulary:

- `CONFIRMED`
- `PROBABLE`
- `POSSIBLE`
- `REJECTED`
- `REVIEW_REQUIRED`

Uncertainty must not be encoded as if it were a domain relation.

### Evidence

Each match must record reasons rather than only a scalar score. Expected properties:

- evidence type;
- observed values or normalized comparison result where safe;
- direction/weight or qualitative strength;
- algorithm/rule/provider version;
- explanation suitable for review.

Resolved authority identities are evidence inputs to matching; they do not replace file/content evidence.

### Fingerprint

A fingerprint is versioned by kind/algorithm. Planned levels include full file SHA-256, fast/partial file fingerprint, normalized e-book text/content fingerprint, audio-stream fingerprint, later acoustic fingerprint and later cover/image perceptual fingerprint.

## Review layer

A ReviewDecision records the chosen relation/rejection/resolution decision, system-level actor type, timestamp, evidence snapshot/reference and relevant matcher/resolver/rule version. Do not require private human identity merely to persist a review decision.

Review may also create durable local authority knowledge such as a confirmed alias-to-Agent mapping or rejected external candidate.

## Consolidation layer

W9 introduces `ConsolidationPlan` only. Plans describe candidate actions and preconditions, but are non-executable until W10 is explicitly enabled by a future accepted ADR.

## Related decisions

- `ADR-0006-authority-entity-resolution-provenance.md`
- `ADR-0007-music-work-and-release-group.md`
- `ADR-0008-multidimensional-classification.md`
- `ADR-0009-external-enrichment-and-privacy.md`
- `AUTHORITY_ENRICHMENT_AND_CLASSIFICATION.md`
