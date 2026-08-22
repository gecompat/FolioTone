# Planned Domain Model

This document defines the conceptual model for W1. Exact Python/SQL representations are intentionally deferred to W1 implementation and should be captured in an ADR if they introduce material trade-offs.

The model deliberately separates physical files, observed metadata, tool executions, authority identities, canonical entities, relations and review decisions.

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
- extractor/parser/provider/tool/rule version;
- confidence where applicable;
- observation/fetch/execution timestamp where relevant;
- explanation/supporting evidence.

Planned value states:

- `OBSERVED`
- `DERIVED`
- `EXTERNAL`
- `CANONICAL`
- `USER_CONFIRMED`

The exact class/table decomposition is a W1 implementation decision, but these distinctions are mandatory.

## Tool execution / specialist evidence layer

External specialist tools are execution sources, not domain authorities.

### ToolProviderDescriptor

Conceptual metadata describing an installed/available specialist integration. It should be able to represent:

- logical provider/tool name;
- integration kind such as CLI, service, container job or local library;
- discovered tool version;
- FolioTone adapter version;
- capabilities exposed to FolioTone;
- availability/health state;
- whether a capability is analysis-only or potentially mutating.

Concrete command lines, container image schemas and provider-specific configuration remain adapter concerns.

### ToolExecution

Represents one bounded execution/query of an external tool that produced observations, candidates or artifacts.

Expected provenance includes:

- stable internal execution ID;
- tool/provider identity and tool version;
- adapter/parser version;
- operation/profile name;
- relevant configuration/profile version or digest where practical;
- started/completed timestamps;
- status/exit code/error classification;
- FolioTone input references using internal IDs/relative paths instead of unnecessary private host paths;
- produced observation/assertion/artifact references;
- timeout/cancellation/retry metadata where relevant.

An adapter-specific accepted exit code can represent a completed inspection
with a negative domain verdict. In that case the execution is successful, the
non-zero code remains preserved, and the verdict is represented separately as
`ToolResult` Evidence. Exit codes outside the immutable adapter allowlist are
technical failures. See ADR-0017.

The exact persistence decomposition is a W1 decision. The requirement is that a downstream Evidence item can explain which tool execution produced it and whether it becomes stale after tool/adapter/config changes.

### ToolArtifact / ToolResultReference

Represents a report, structured output, temporary normalized result or other artifact that is useful beyond the process boundary.

Large/transient raw output should not automatically be stored forever. Persistence should retain only what is needed for reproducibility, evidence and debugging, subject to privacy/storage policy.

### Safety state

A ToolProvider may expose mutating operations, but FolioTone must distinguish capability from authorization. Through W9 only analysis-safe operations may execute against source media.

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

### EbookCollectionRun / EbookCollectionItem

`EbookCollectionRun` beschreibt einen fortsetzbaren Analyse-Lauf über einen
unveränderlichen Plan aus genau einem abgeschlossenen `ScanRun`. Der Lauf hält
das Collection- und Analyseprofil, die Evidence-Policy, eine begrenzte
Workerzahl sowie die Lease für eine aktive Invocation.

`EbookCollectionItem` bindet genau eine geplante `FileObservation` an einen
stabilen Ordinalwert und hält Versuchszahl, technischen Zustand,
Quality-Gesamtzustand und begrenzte Ergebniszähler. Relative oder absolute
Pfade, Metadatenwerte und extrahierte Inhalte gehören nicht in diese
Batch-Modelle. Die Observation-ID verbindet den Status mit der lokalen
Runtime-Persistenz.

Ein Batch-Ergebnis beschreibt Ausführung und Analyseabdeckung. Es ist keine
`Relation`, kein Duplicate-Verdict und keine `Work`-/`Edition`-
Identitätsentscheidung.

### EbookCandidateHashRun

`EbookCandidateHashRun` beschreibt eine einzelne, rootweit geleaste
Invocation zur selektiven Vollhash-Bestätigung. Er bindet sich an genau einen
abgeschlossenen Source-`ScanRun` und speichert `SELECTING`, `HASHING` oder
`FINALIZING`, den Heartbeat-/Lease-Zustand sowie begrenzte Zähler. Private
Pfade, relative Dateinamen und Fingerprint-Werte gehören nicht in dieses
Modell. Terminale Läufe behalten ihre Historie; nur ein `RUNNING`-Lauf pro
`ScanRoot` ist zulässig.

### EbookCollectionReportSnapshot / EbookCollectionCandidateGroup

`EbookCollectionReportSnapshot` ist eine read-only Anwendungsprojektion eines
persistierten, nicht mehr aktiven `EbookCollectionRun`. Sie kombiniert
vollständige Summenzähler mit begrenzten priorisierten Review-Items und
technischen Kandidatengruppen. Befunde behalten ihre exakten verfügbaren
`ToolExecution`-Quellen; die Projektion wird nicht als kanonisches Domain-
Objekt oder Matching-Ergebnis persistiert.

Eine `EbookCollectionCandidateGroup` fasst Beobachtungen zusammen, die
entweder denselben vollständigen Datei-Hash oder denselben normalisierten
Textfingerprint bei unterschiedlichen vollständigen Datei-Hashes besitzen.
Die Gruppe hat eine abgeleitete stabile ID und dokumentierte Basis, ist aber
keine `Relation`, Confidence oder Aussage über `Edition`-/`Work`-Identität.

### CollectionStateSnapshot / CollectionStateItem

`CollectionStateSnapshot` ist eine immutable, rebuildbare book-only
Anwendungsprojektion über genau einen abgeschlossenen `ScanRun`. Der Snapshot
bindet feste Profilversionen und vollständige Zähler an den technischen
Bestand. Seine Komponenten unterscheiden Coverage, Freshness, Konflikte und
Kürzungen ausdrücklich; fehlende oder veraltete Evidence wird nicht als
erfolgreiche Analyse ausgegeben.

`CollectionStateItem` verbindet genau eine aktuelle `FileObservation` mit den
relevanten persistierten Evidence-Bezügen. Content- und Item-Digests sichern
deterministische Wiederverwendung und spätere Diffbarkeit. Sie erzeugen keine
neue Datei-, `Edition`- oder `Work`-Identität, kein kanonisches Metadatum und
keine Mutation Authority. Öffentliche Reports geben weder private Pfade und
Metadatenwerte noch interne Evidence-Digests aus.

### CollectionStateDiff / CollectionQuery

`CollectionStateDiff` ist eine rebuildbare Anwendungsprojektion über genau
zwei kompatible `CollectionStateSnapshot`-Objekte. Ein Eintrag trägt eine oder
mehrere feste Änderungskategorien, bestätigt aber weder Ursache noch Identity.
Counts beziehen sich auf den vollständigen Vergleich; Detailseiten verwenden
eine opaque `File`-ID als Keyset-Cursor.

`CollectionQuery` ist ein validierter, begrenzter AST und kein SQL- oder
Calibre-Abfragefragment. Der zugehörige insert-only Index bindet ausgewählte
`METADATA_CANDIDATE`-Werte, technische Statuswerte und Finding-Codes an genau
einen Snapshot. Die Projektion erzeugt keine kanonischen Metadaten und
speichert keine Query-History. `CollectionQuery` und sein Index bleiben
book-only; eine spätere medienübergreifende Abstraktion wird nicht vorweggenommen.

### LibraryHealthSnapshot

`LibraryHealthSnapshot` ist eine immutable, content-addressed book-only
Projektion über genau einen `CollectionStateSnapshot` und dessen gebundenen
Query-Index. Sie bewertet sieben unabhängige Bereiche: Scan/Fixity,
Analyseabdeckung, Metadaten/Authority/Classification, offene Reviews,
Duplicate-/Varianten-Evidence, Dependencies und blockierte Operationen.

Jede Dimension besitzt eigene Coverage, eigenen Status, vollständige
Finding-Counts und begrenzte opaque File-/Observation-Samples. Der Status
reduziert nur die Severity innerhalb derselben Dimension; es existiert kein
dimensionsübergreifender Score. Ein Finding ist Evidence für einen Zustand,
keine Identity-, Keep-, Quarantäne- oder andere Mutationsentscheidung.

`LibraryHealthComparison` stellt Counts, Coverage und Status zweier
verschiedener Health-Snapshots desselben `ScanRoot` gegenüber. Er behauptet
keine Kausalität und verändert keine persistierte Evidence.

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

Different provider/tool classifications may coexist. `Classical` as a broad music domain is distinct from the `Classical period` as an era.

Für die book-only Projection trennt ADR-0037 immutable Source Assertions von
versionierten lokalen Projection Snapshots. Der bestehende generische
Assertion-Datensatz bleibt Source Evidence; Projection-Werte überschreiben ihn
nicht und sind niemals allein Identity-Beweis.

## Entity-resolution layer

### FieldCandidate

Represents a parsed/derived candidate value from filename, path context, metadata, external tool output or another inference source. It does not directly overwrite canonical metadata.

The implemented e-book metadata specialization uses versioned grouped field
paths and persists each candidate as a `ToolResult` linked to the exact
`ToolExecution` and `FileObservation`. Identifier, contributor and series
groups retain their component relationship without creating an authority or
bibliographic entity. Direct extraction confidence describes the projection,
not the truth or canonical status of the metadata value.

### EntityResolutionCandidate

Represents a proposed mapping between an observed/derived value and an Agent/Work/Edition/MusicWork/Recording/ReleaseGroup/Release or external authority entity.

Expected properties include candidate entity, score/confidence, source/provider/tool, explanation and resolution-rule/provider/tool-adapter version.

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

### Controlled comparison fixtures

The versioned synthetic e-book comparison corpus provides labeled ground truth
for later matching implementation. Each item separates raw file bytes,
normalized extracted text, observed metadata and bibliographic `Work`/`Edition`
identity. Pair scenarios cover exact copies, metadata-only changes, format
variants of the same `Edition`, and a translation as a different `Edition` of
the same `Work`. A separate disagreement scenario retains two versioned tool
values without choosing a canonical value. These fixtures are calibration
inputs, not persisted match decisions or matcher behavior.

Die additive v2-Ground-Truth ergänzt AZW, AZW3 und PDF, vollständig fehlende
Analyse-Evidence, gezielt inkompatible beziehungsweise unvollständige
Evidence sowie Cover-dHash-Distanzen von 0, 1, 8, 32 und 64 Bit. Die
Distanzwerte kalibrieren ausschließlich den technischen Vergleich; sie
definieren keine Matching-Schwelle. Ein separater synthetischer
Skalierungsfall prüft, dass nicht angeforderte collection-weite Evidence den
Paarvergleich weder inhaltlich noch bei der Zahl der SQL-Abfragen vergrößert.

### Structural validation evidence

The implemented EPUBCheck slice attaches a bounded conformance verdict,
severity counts and diagnostic-code counts to the exact `FileObservation` and
`ToolExecution`. `CONFORMANT` and `NONCONFORMANT` describe the external
validator result; they do not establish bibliographic identity, canonical
metadata or a complete quality ranking. Raw message text and local paths are
not projected into `ToolResult` values.

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
- source assertion / ToolExecution / provider reference;
- algorithm/rule/provider/tool/adapter version;
- explanation suitable for review.

Resolved authority identities and specialist tool results are evidence inputs to matching; they do not replace independent file/content evidence.

### Fingerprint

A fingerprint is versioned by kind/algorithm. Implemented levels include full
file SHA-256, fast/partial file fingerprint, normalized e-book text/content
fingerprint and the optional `EBOOK_COVER_DHASH` against an exact
`FileObservation` plus `ToolExecution`. Planned levels include audio-stream and
acoustic fingerprints (for example via Chromaprint) and later music-release
artwork Evidence. A perceptual cover hash is supporting visual similarity
Evidence; it does not establish file, `Edition`, `Work`, `Release` or other
canonical identity by itself.

## Review layer

A ReviewDecision records the chosen relation/rejection/resolution decision, system-level actor type, timestamp, evidence snapshot/reference and relevant matcher/resolver/rule/tool versions. Do not require private human identity merely to persist a review decision.

Review may also create durable local authority knowledge such as a confirmed alias-to-Agent mapping or rejected external/tool candidate.

## Consolidation layer

W9 introduces `ConsolidationPlan` only. Plans describe candidate actions and preconditions, but are non-executable until W10 is explicitly enabled by a future accepted ADR.

## Related decisions

- `ADR-0006-authority-entity-resolution-provenance.md`
- `ADR-0007-music-work-and-release-group.md`
- `ADR-0008-multidimensional-classification.md`
- `ADR-0037-book-classification-assertions-and-projections.md`
- `ADR-0009-external-enrichment-and-privacy.md`
- `ADR-0010-tool-provider-orchestration.md`
- `AUTHORITY_ENRICHMENT_AND_CLASSIFICATION.md`
- `../reference/EXTERNAL_TOOLS.md`
