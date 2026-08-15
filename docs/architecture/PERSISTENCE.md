# Persistence Architecture

## Purpose

FolioTone persists index state, provenance, resolved identities, specialist-tool evidence, matching evidence and later review/planning state without coupling the domain model to a concrete database library.

W1 uses SQLite with SQLAlchemy Core and Alembic. Domain classes remain immutable provider/tool-independent dataclasses.

## Boundaries

```text
Domain/Application
      |
      v
Repository[T] contracts
      |
      v
explicit Codec[T]
      |
      v
SQLAlchemy Core tables
      |
      v
SQLite

Schema evolution: Alembic migrations
```

The domain layer does not import SQLAlchemy or Alembic.

## Internal identity

FolioTone-owned IDs are UUID-backed `EntityId` values. SQLite stores them as canonical UUID strings.

External provider/catalog IDs are separate `ExternalIdentifier` records. They never become primary keys.

## Datetime representation

Domain datetimes must be timezone-aware. Persistence normalizes them to UTC ISO-8601 text.

This avoids relying on SQLite timezone semantics and keeps round-trip behavior explicit.

## Current tables

### Physical/index

- `scan_roots`
- `scan_runs`
- `file_records`
- `file_observations`

`file_records` has a uniqueness constraint on `(scan_root_id, relative_path)`.

### Provenance / authority

- `value_assertions`
- `agents`
- `agent_names`
- `external_identifiers`
- `contributions`

Provenance-bearing tables flatten the stable source fields (`source_kind`, `source_name`, `source_version`, `observed_at`) while reconstructing the domain `Provenance` value object through codecs.

### E-books

- `works`
- `editions`
- `series`
- `series_memberships`

### Music

- `music_works`
- `music_work_relations`
- `catalog_designations`
- `recordings`
- `release_groups`
- `releases`
- `release_recordings`

### Tool orchestration

- `tool_executions`
- `tool_results`

Material specialist-tool evidence keeps a link to the exact execution identity and therefore to provider/tool/adapter/input/config versions.

### E-Book-Collection-Analyse

- `ebook_collection_runs`
- `ebook_collection_items`
- `ebook_collection_item_executions`
- `ebook_collection_findings`
- `ebook_collection_finding_executions`

Ein `EbookCollectionRun` verweist auf genau einen `ScanRoot` und einen
abgeschlossenen Source-`ScanRun`. Die zugehörigen Items verweisen auf exakte
`FileObservation`-IDs. Eindeutige Constraints auf `(run_id, observation_id)`
und `(run_id, ordinal)` verhindern doppelte Planpositionen. Die Tabellen
enthalten Lifecycle, Lease, Versuchszahl und begrenzte Ergebniszähler, aber
keine Pfade oder Metadatenwerte.

Die drei Projektions-/Zuordnungstabellen binden den terminalen Item-Zustand an
geordnete Workflow-Schritte, Quality-Befundcodes und deren exakte
`ToolExecution`-Quellen. Sie speichern weiterhin keine Source-Pfade,
Metadatenwerte oder extrahierten Inhalte.

### Classification / matching evidence

- `classification_assertions`
- `fingerprints`
- `relations`
- `evidence`

## Deliberate generic references

Some relationships use `(target_kind, target_id)` rather than a SQL foreign key to one table because the target can be one of several domain entity types. Domain validation and future service-level integrity checks own these polymorphic references.

Concrete single-table relationships use SQLite foreign keys where applicable.

## Foreign-key behavior

Application-created SQLite connections enable `PRAGMA foreign_keys=ON` and a
30-second `PRAGMA busy_timeout` through an SQLAlchemy connection event. Das
Timeout begrenzt vorübergehende Writer-Konkurrenz zwischen den höchstens acht
Collection-Workern; es ersetzt keine Lease oder Transaction-Grenze.

The Alembic environment also enables foreign keys, but explicitly ends SQLAlchemy's small implicit PRAGMA transaction before starting Alembic's migration transaction. This is important: otherwise the version-table update can be rolled back independently of SQLite DDL.

## Migration policy

- migration files are immutable after merge;
- `0001_initial` is an explicit schema snapshot and does not call current metadata to create the schema;
- migrations are applied programmatically with `foliotone.persistence.migrate()`;
- re-running `upgrade head` is expected to be idempotent;
- future SQLite changes use Alembic batch operations when required;
- CI creates a database from nothing and verifies the Alembic revision;
- CI also runs a migration inside the built FolioTone Docker image to catch missing packaged migration resources.

## Repository behavior

`SQLiteRepository[T]` uses an explicit registered codec for each supported immutable W1 model.

Current contract:

```text
save(value)
get(EntityId)
list_all()
```

`save()` is an ID-based insert-or-update operation. It does not infer identity from metadata or external IDs.

### Begrenzter Evidence-Lesepfad

Paarvergleich und exakte Evidence-Wiederverwendung verwenden nicht
`list_all()`. Die SQLite-spezifische Projektion
`load_observation_evidence()` lädt ausschließlich
`ToolExecution`, `ToolResult` und `Fingerprint` für explizite
`FileObservation`-IDs. Drei feste `LIMIT maximum + 1`-Grenzen verhindern eine
unbeschränkte Historienladung. Eine Überschreitung wird als technischer Fehler
gemeldet; es gibt keinen Fallback auf vollständige Tabellenabfragen.

Der Reuse-Pfad fordert genau eine Observation an und lädt danach höchstens 64
`ToolArtifact`-Records für die ausgewählte exakte Ausführung über
`ix_tool_artifacts_execution`. Eine dichte oder inkonsistente Historie führt
konservativ zur erneuten read-only Ausführung, nicht zu einem Full-Table-Read.

Alembic `0006_ebook_evidence_lookup_indexes` ergänzt zusammengesetzte Indizes
für `ToolExecution.input_identity` sowie polymorphe Target-/Execution-Abfragen
auf `tool_results` und `fingerprints`. Der synthetische Skalierungstest prüft
die verwendeten SQLite-Query-Pläne mit 10.000 nicht angeforderten Datensätzen
je Evidence-Tabelle.

### Fortsetzbarer Collection-Plan

`SQLiteEbookCollectionStore` erstellt den Plan aus dem neuesten
`COMPLETED`-`ScanRun`. Ein gestreamter, stabil sortierter SELECT wird mit
`fetchmany(500)` in `ebook_collection_items` übernommen. Der Plan bleibt nach
der Anlage unverändert und wird beim Resume nicht erneut aus dem aktuellen
Index abgeleitet. Für einen begrenzten heterogenen Pilot kann
`--plan-per-format N` statt eines globalen `--plan-limit` jeweils höchstens N
stabil sortierte Beobachtungen pro unterstütztem Format planen. Die beiden
Begrenzungen sind gegenseitig exklusiv; der Default bleibt der einzelne
gestreamte Read über den vollständigen Plan.

Alembic `0007_ebook_collection_batches` ergänzt die beiden Batch-Tabellen
sowie `ix_ebook_collection_runs_root_status` und
`ix_ebook_collection_items_run_status_ordinal`. Claim, Completion,
Heartbeat, kontrolliertes `INTERRUPTED` und stale Claim Recovery laufen in
kurzen expliziten Transaktionen. Toolausführungen bleiben davon getrennte,
provenance-erhaltende Records.

### Deterministischer Collection-Bericht

`SQLiteEbookCollectionReportStore` liest einen nicht mehr `RUNNING`
befindlichen Collection-Lauf in einer Transaktion. Vollständige Summenzähler
werden getrennt von begrenzten Review-Items und Kandidatengruppen berechnet.
Die Review-Abfrage behält Befundreihenfolge und exakte `ToolExecution`-
Referenzen. Die Duplicate-/Varianten-Abfragen streamen sortierte
Fingerprint-Gruppen mit `fetchmany(500)` und halten nur die begrenzten größten
Gruppen im Speicher.

Alembic `0008_ebook_collection_reports` ergänzt die drei
Collection-Projektionstabellen, ihre Foreign Keys und Indizes sowie
`ix_fingerprints_kind_algorithm_version_value_target` für den belegten
Gruppierungspfad. Ein Bericht wird abgelehnt, wenn `finding_count` und
persistierte Befundprojektion oder die Schrittzähler und
Ausführungsprojektion auseinanderfallen. Rohe Fingerprint-Werte verlassen die
Query-Schicht nicht.

### Deterministischer scanweiter Inventarbericht

`SQLiteEbookInventoryReportStore` bindet sich an den neuesten
`COMPLETED`-`ScanRun` und berücksichtigt ausschließlich aktuelle
`PRESENT`-Beobachtungen unterstützter E-Book-Formate, die noch exakt zu ihrem
`FileRecord` passen. Die Projektion liest keine Source-Media-Dateien und
benötigt keinen `EbookCollectionRun`.

Format-/Byte-Summen und Hash-Abdeckung werden vollständig aggregiert.
Mehrfach belegte konsistente `QUICK_FILE`-Gruppen weisen den noch offenen
Vollhashbedarf aus. Exakte `FILE_SHA256`-Gruppen werden sortiert gestreamt;
nur die durch Gruppen- und Mitgliederlimits priorisierten Details bleiben im
Speicher. Vollständige Summen, Kürzungsmarker und das technische potenzielle
Speicherersparnis bleiben erhalten. Rohe Fingerprint-Werte verlassen die
Query-Schicht nicht. ADR-0024 definiert Snapshot-, Datenschutz- und
Nicht-Mutationsvertrag; eine zusätzliche Persistenzmigration ist nicht nötig.

## Current constraints and deferred integrity

Implemented SQL constraints include:

- primary keys for all durable records;
- foreign keys for concrete single-table dependencies;
- unique file path within one scan root;
- unique namespaced external identifier per target;
- unique catalog designation per music work/system/value.
- eindeutige Observation und Ordinalposition innerhalb eines
  `EbookCollectionRun`.
- eindeutige Ausführungs- und Befundordinale je `EbookCollectionItem` sowie
  eindeutige `ToolExecution`-Referenzen innerhalb ihrer jeweiligen Projektion.

Cross-table polymorphic target validation, allgemeine Query-Repositories,
Bulk-Write-Pfade und Transaction Orchestration bleiben zurückgestellt, bis
ihre konkreten Zugriffsverträge vorliegen. Der gemessene E-Book-
Paarvergleichspfad besitzt gezielte Indizes; weitere Performance-Indizes
werden weiterhin nur über additive Migrationen für belegte Access Patterns
ergänzt.

## Tests

W1 persistence integration tests cover:

- empty database -> Alembic head;
- repeat `upgrade head`;
- current table set + Alembic revision;
- full synthetic W1 domain graph round-trip;
- immutable-record update by internal ID;
- foreign-key enforcement;
- unique scan-root-relative file path;
- deterministic listing.
- begrenzte, indexgestützte Observation-Evidence-Abfragen unabhängig von
  nicht angeforderten collection-weiten Records.
- fortsetzbare Collection-Zustände, Lease-Konflikte, stale Claim Recovery und
  einen einzelnen gestreamten Plan-Read mit begrenzten Insert-Batches.
- transaktionale Item-Ausführungs-/Befundprovenance sowie begrenzte,
  deterministische Collection-Berichtabfragen.

No real collection data is used in tests.
