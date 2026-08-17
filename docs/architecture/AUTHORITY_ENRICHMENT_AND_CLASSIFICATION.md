# Authority, Entity Resolution, Enrichment and Classification

## Purpose

FolioTone must not treat author, artist, composer, title, genre or edition strings as identities. Real collections contain aliases, reversed names, initials, pseudonyms, transliterations, misspellings, incomplete tags and inconsistent filename conventions.

This layer turns observations into traceable identity candidates before duplicate matching. It also provides a controlled path for external knowledge, classification and later quality assessment.

## Architectural position

```text
Filesystem / embedded metadata / Calibre
                |
                v
         raw observations
                |
                v
      normalization + parsing
                |
                v
   Authority / Entity Resolution
                |
        +-------+-------+
        |               |
        v               v
 local authority   external enrichment
        |               |
        +-------+-------+
                v
       canonical candidates
                |
                v
         classification
                |
                v
        Matching Engine
```

Entity resolution answers questions such as "which person or work does this value refer to?" Matching answers questions such as "are these two files the same edition or recording?" These are related but separate problems.

## Core authority concepts

### Agent

`Agent` is the common identity concept for contributors and credited parties.

Planned `AgentType` values include:

- `PERSON`
- `GROUP`
- `ORGANIZATION`
- `ENSEMBLE`
- `ORCHESTRA`
- `CHOIR`
- `UNKNOWN`

Do not encode author/artist/composer as independent identity types. Roles are relationships between an Agent and another entity.

### AgentName

An Agent may have multiple names. Planned name types include:

- `CANONICAL`
- `SORT_NAME`
- `ALIAS`
- `PSEUDONYM`
- `CREDITED_AS`
- `TRANSLITERATION`
- `FORMER_NAME`

A name record should be able to retain:

- original value;
- normalized comparison form;
- language where known;
- script where known;
- source/provenance;
- validity or confidence where applicable.

Normalization must never destroy the observed spelling.

### ExternalIdentifier

External identifiers are evidence and durable cross-references. Examples include GND identifiers, Wikidata entity IDs, Open Library keys, MusicBrainz IDs, ISRC, ISWC, ISBN, barcode and catalog numbers where appropriate to the entity type.

An external identifier must retain its namespace/provider and must not be treated as globally unique without that namespace.

### Contribution / Credit

Roles belong on relationships, not on a flattened name field.

Book examples:

- `AUTHOR`
- `EDITOR`
- `TRANSLATOR`
- `ILLUSTRATOR`
- `NARRATOR`

Music examples:

- `COMPOSER`
- `LYRICIST`
- `LIBRETTIST`
- `ARRANGER`
- `CONDUCTOR`
- `VOCALIST`
- `PERFORMER`
- instrument-specific performer roles where useful.

The same Agent can hold several roles on the same or different entities.

## Provenance and value states

FolioTone must preserve where a value came from and how it was derived. A canonical value must not silently replace evidence.

Planned value states:

- `OBSERVED` — read directly from filesystem, embedded metadata, document content or an adapter;
- `DERIVED` — normalized, parsed or inferred locally from observed data;
- `EXTERNAL` — returned by an external authority/catalog/provider;
- `CANONICAL` — FolioTone's current selected representation;
- `USER_CONFIRMED` — explicitly confirmed through review and therefore strong local evidence.

A value/assertion should retain at least:

- entity/field target;
- value;
- state;
- source kind and source reference;
- extraction/parser/provider version;
- timestamp where relevant;
- confidence if the value is probabilistic;
- supporting evidence or explanation.

`USER_CONFIRMED` does not erase contradictory evidence; it changes decision priority while provenance remains inspectable.

## Name normalization

Name normalization is a candidate-generation aid, not identity proof.

The implementation must account for at least:

- `Given Family` vs. `Family, Given`;
- initials and abbreviated given names;
- multiple given names;
- prefixes/particles such as `von`, `van`, `de`, `del`, `di`;
- suffixes such as `Jr.`;
- punctuation and whitespace variants;
- Unicode normalization and diacritics;
- transliteration and multiple scripts;
- locale-dependent name order;
- pseudonyms/stage names;
- historical name variants;
- groups/organizations that must not be parsed as human names;
- homonyms: equal normalized names do not imply equal Agents.

A future normalization implementation should emit both normalized forms and an explanation/version so results can be invalidated selectively after rule changes.

## Filename and path context

Filename/path parsing is its own component. It emits candidates; it does not directly mutate canonical metadata.

Example input shape:

```text
Author Name / Series Name / 01 - Title (Year) [Language].epub
```

Potential derived candidates:

- parent directory -> possible author;
- parent directory -> possible series;
- numeric prefix -> possible series/track position;
- text segment -> possible title;
- bracket/token -> possible language, edition, year or format hint.

Planned concepts:

- `FilenameParser`
- `PathContextAnalyzer`
- `FieldCandidate`

A `FieldCandidate` should retain source location, parser version and confidence. Parsing rules should be configurable/versioned because collections use different conventions.

## Tool-derived e-book metadata candidates

The implemented `ebook-metadata-candidate/v1` contract projects bounded OPF 2
and OPF 3 evidence into provider-neutral `ToolResult` records. Stable field
paths keep related identifier namespace/value, contributor
name/role/sort-name, and series name/position components together. Each result
retains the exact tool execution, file observation, source location, profile
and extraction confidence. Unknown role schemes remain source-role evidence;
the projection does not infer an `Agent`, `Work`, `Edition`, `Series` or
canonical field value. Those identity decisions remain responsibilities of the
later authority and entity-resolution layers.

## E-book authority model extensions

### Work

The intellectual work independent of edition or file format.

### Edition

A specific publication/edition/translation/format-bearing bibliographic manifestation as modeled by FolioTone. Exact mapping to external catalog vocabularies may vary by provider and must remain adapter-specific.

### Series / SeriesMembership

Series must be modeled explicitly rather than stored only as text tags. Membership should support non-integer positions and uncertain/derived ordering.

Examples that must remain representable include `0`, `1`, `1.5`, volume labels, prequels, omnibuses and unknown positions.

Translations can be editions of the same Work while retaining translator/language evidence. Distinct translations must not be collapsed merely because they represent the same underlying Work.

## Music authority model extensions

The music model needs an explicit composition/work layer and a release-group layer.

```text
Agent --role--> MusicWork
                    |
              performed as
                    v
                Recording
                    |
             appears on
                    v
            ReleaseRecording
                    |
                    v
                 Release
                    |
                    v
              ReleaseGroup
```

### MusicWork

Represents the composition/work independent of a particular performance or recording.

Planned work relationships include:

- `PART_OF`
- `ARRANGEMENT_OF`
- `TRANSLATION_OF`
- `DERIVED_FROM`
- `REVISION_OF`

The model must support multi-part/hierarchical works without assuming that every track boundary defines a separate work.

### CatalogDesignation

Classical catalog identifiers should be representable structurally as namespace/system + value, for example BWV, K/KV, Hob., D, RV, HWV, WoO or other catalog systems. Do not hard-code a closed list into the domain model.

### Recording

A particular recorded performance/production independent of the release on which it appears.

### ReleaseGroup

Represents the logical album/single/release concept grouping related concrete releases.

### Release

Represents a concrete issuing/edition, which may differ by date, territory, label, format, mastering, packaging, bonus material or other release-specific properties.

### ReleaseRecording

Associates a Recording with a Release and carries disc/track position and release-specific credit/title observations.

## Music variants that must remain distinguishable

The model and future matching rules must be able to express distinctions such as:

- same MusicWork, different Recording;
- live vs. studio Recording;
- same Recording on multiple Releases;
- remix;
- remaster/mastering variant;
- radio edit/extended version;
- acoustic/instrumental/karaoke variants;
- mono/stereo/surround release variants;
- transcodes and quality variants at File level.

No single fingerprint is expected to resolve all of these distinctions.

## Multidimensional classification

Classification is not a single `genre` string. Store classifications as typed facets with provenance and confidence.

Possible e-book facets:

- domain: fiction/non-fiction/reference/etc.;
- genre/subgenre;
- subject/topic/theme;
- audience;
- language;
- form where useful.

Possible music facets:

- broad domain/genre;
- subgenre/style;
- classical period/era;
- musical form/work type;
- instrumentation/ensemble type;
- language;
- context such as soundtrack/spoken word where useful.

For classical music, `Classical` as a broad domain must be distinct from the `Classical period` as an era.

A provider classification is evidence, not automatically the canonical classification. Conflicting taxonomies may coexist.

## External enrichment provider boundary

External knowledge is accessed through adapters/providers, never directly from matching/domain code.

`PR #38` hat die strukturierten Book/Authority-Provider-Verträge
(offline-synthetische Query-/DTO-/Result-Contracts) auf `main` eingeführt;
`PR #39` ergänzt die multidimensionalen E-Book-Klassifikations-DTOs. Die
Providerverträge verwenden inzwischen getrennte Zugriffs- und Cache-
Dimensionen gemäß ADR-0026.

Conceptual interface responsibilities:

- resolve/search by structured identifiers or candidate fields;
- return provider-native records as adapter DTOs;
- map useful values into provenance-preserving assertions/candidates;
- expose provider/version/source metadata;
- respect provider rate/access/licensing constraints;
- support caching and retry/backoff where allowed;
- avoid leaking private local context.

Candidate provider categories:

- authority providers;
- bibliographic providers;
- music metadata providers;
- acoustic fingerprint providers;
- generic web research providers as a controlled fallback.

See `docs/reference/EXTERNAL_DATA_SOURCES.md` for the initial source registry.

## Enrichment modes and privacy

Network use must be explicit and separable from local analysis.

Kanonische `ProviderAccessMode`-Werte:

- `OFFLINE` — no network access;
- `LOCAL_DATASETS` — use locally imported authority/catalog datasets only;
- `ONLINE_STRUCTURED` — use configured structured APIs/services;
- `ONLINE_WEB_RESEARCH` — generic web research fallback, separately enabled.

ADR-0026 definiert davon getrennt die `ProviderCachePolicy`-Werte
`USE_IF_FRESH`, `REFRESH_IF_STALE`, `FORCE_REFRESH` und `NO_CACHE`.
`OFFLINE` mit `USE_IF_FRESH` ist cache-only; bei einem fehlenden oder veralteten
Treffer erfolgt kein Source Fetch. `OFFLINE` mit `NO_CACHE` verwendet weder
Cache noch externe Quelle. Die Kombinationen `OFFLINE` mit
`REFRESH_IF_STALE` oder `FORCE_REFRESH` sind ungültig. Eine Cache-Policy kann
keinen Zugriff freigeben, den der Zugriffsmodus oder Providerdescriptor
verbietet.

Privacy rules:

- never send absolute local paths to an external provider;
- never send collection-wide inventories unless the provider contract and user configuration explicitly allow it;
- prefer structured candidate fields/identifiers over raw filenames;
- send the minimum fields required for a lookup;
- cache successful results to avoid repeated disclosure and unnecessary traffic;
- record which provider was queried and when;
- API keys/secrets belong in local configuration and never Git;
- generic web/AI inference can create candidates but cannot become sole authoritative evidence for destructive decisions.

## Authority cache

The cache is part of runtime state under `/data`, not Git.

Planned cached information includes:

- provider;
- normalized query key;
- external entity ID;
- selected provider data or normalized projection;
- fetched timestamp;
- provider/data version where available;
- expiry/refresh policy;
- terms/license/provenance metadata needed for correct downstream use.

Bulk/local datasets should have their own import/version state rather than pretending to be API cache entries.

## Review-driven local knowledge

Review decisions should improve later resolution without requiring machine learning first.

Examples:

- confirmed alias -> Agent mapping;
- confirmed filename parsing rule for a collection convention;
- confirmed same/different entity decision;
- preferred canonical display/sort name;
- rejected false-positive authority candidate.

Such knowledge must remain versioned/auditable and must not silently rewrite historical observations.

### Persistierter Resolution-/Review-Core

EB-02 persistiert lokale book-only `ResolutionCandidate`-Snapshots und ihre
konkreten `ResolutionEvidenceLink`-Datensätze. Ein erstmaliger Fall bleibt
immer `REVIEW_REQUIRED`; ausschließlich eine semantisch exakt kompatible
frühere ACCEPT-Entscheidung darf AUTO_SAFE wiederverwendet werden. REJECT
unterdrückt den unveränderten Fall, DEFER hält ihn reviewbar.

`ReviewDecision` ist append-only und wird durch eine monotone Sequenz sowie
Evidence-, Candidate-Set- und Decision-Compatibility-Snapshots optimistisch
gefencet. Technische Resolver-/Producer-Versionen bleiben Auditdaten und
entwerten eine fachlich kompatible Entscheidung nicht. Source Evidence und
kanonische Entity-Felder bleiben unverändert. ADR-0028 enthält den
vollständigen Vertrag.

## Future evidence sources

These are planned extensions, not W1 requirements:

### Cover/image perceptual fingerprints

Useful for book editions and music releases. Similar cover art is supporting evidence, not proof of identity.

### Quality assessment

Keep quality ranking separate from duplicate identity.

E-book examples:

- structural validity;
- missing resources/TOC/cover;
- text availability;
- corruption indicators;
- metadata completeness.

Music examples:

- lossless/lossy;
- codec/technical quality;
- corruption indicators;
- tag/cover completeness.

A future consolidation planner may use quality assessment after identity has been established.

## Versioning requirement

Normalization rules, filename parsers, entity-resolution rules, external provider mappings, classification rules and canonical-selection rules are derived logic. Their versions must be representable so stale results can be detected and recomputed selectively.
