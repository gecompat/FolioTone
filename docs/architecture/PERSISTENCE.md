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

`scan_runs` speichert zusätzlich nullable `lease_token` und
`lease_expires_at`. Neue aktive Scans halten beide Felder gemeinsam; terminale
Läufe halten keines. Nullable Felder erlauben das konservative Upgrade älterer
Läufe.

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

The Alembic environment also enables foreign keys, explicitly selects modern
transaction control for Python's SQLite driver and ends SQLAlchemy's small
implicit PRAGMA transaction before starting Alembic's migration transaction.
This keeps SQLite DDL and the Alembic version-table update in the same
transactional boundary.

## Migration policy

- migration files are immutable after merge;
- `0001_initial` is an explicit schema snapshot and does not call current metadata to create the schema;
- migrations are applied programmatically with `foliotone.persistence.migrate()`;
- re-running `upgrade head` is expected to be idempotent;
- future SQLite changes use Alembic batch operations when required;
- CI creates a database from nothing and verifies the Alembic revision;
- CI also runs a migration inside the built FolioTone Docker image to catch missing packaged migration resources.
- `migrate()` recognizes only the exact empty, schema-identical 0016 table set
  that an older interrupted SQLite upgrade could leave before its revision
  stamp. It removes that empty partial DDL and reruns the immutable migration;
  incompatible or populated tables fail closed.

## Repository behavior

`SQLiteRepository[T]` uses an explicit registered codec for each supported immutable W1 model.

Current contract:

```text
save(value)
get(EntityId)
list_all()
```

`save()` is an ID-based insert-or-update operation. It does not infer identity from metadata or external IDs.

Dieser generische Update-by-ID-Vertrag ist für die immutable book-only
Classification-Lineage und Projection aus ADR-0037 ausdrücklich nicht
zulässig. EB-04 verwendet dafür einen dedizierten insert-only Store; die seit
`0001` bestehende Tabelle `classification_assertions` wird nicht neu angelegt
oder umgedeutet.

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

### Recoverbare Scan-Lease

`SQLiteIndexStore` startet neue Scans mit einer 30-Minuten-Lease. Heartbeats
und terminale Übergänge verwenden bedingte Updates gegen Token und
`RUNNING`-Status. Die explizite Recovery liest den neuesten `RUNNING`-Lauf
eines `ScanRoot` und setzt ihn nur bei abgelaufener oder fehlender Lease atomar
auf `INTERRUPTED`. Ein gleichzeitig erneuerter aktiver Lauf wird nicht
übernommen.

Alembic `0009_scan_run_leases` ergänzt die beiden Lease-Spalten und
`ix_scan_runs_root_status_lease`. Ein vor dem Upgrade verwaister ungeleaster
Lauf bleibt lesbar und kann nach externer Prozessprüfung ausdrücklich
wiederhergestellt werden. Die Recovery verändert keine Source Media und führt
den Resume-Vertrag aus ADR-0015 unverändert über einen neuen `ScanRun` fort.

### Gemeinsame `ScanRoot`-Write-Lease

Alembic `0012_scan_root_write_leases` ergänzt einen dauerhaften Mutex- und
Sequencer-Slot je `ScanRoot`. Der Slot bleibt nach Release als Tombstone
erhalten; jeder neue Besitzer erhöht die `fence_epoch`. Owner-Art, Owner-ID,
Token und Epoch bilden zusammen den Besitzbeleg. Das Token wird nicht in
`repr`, Status oder Fehlermeldungen ausgegeben.

Scan, selektives Kandidaten-Hashing, Collection-Analyse und einzelne
E-Book-Analyse erwerben den Root-Slot atomar mit ihrem Lauf. Jede
rootbezogene Schreibtransaktion beginnt mit einem bedingten No-op-`UPDATE` auf
dem Slot und prüft anschließend die zusätzliche Run-Lease. Fachdaten folgen
erst danach. Finish setzt den Lauf terminal und gibt den Slot zuletzt frei.
Dadurch kann ein stale Prozess nach einer Übernahme keinen späten
Fingerprint-, Observation-, Status- oder Evidence-Write mehr committen.

`0012` ergänzt außerdem `uq_scan_runs_active_root`. Upgrade und Downgrade
verweigern sich bei aktiven Writern, weil laufende Prozesse einer älteren
Schemafassung keinen gültigen Root-Fence besitzen können. Scanner und
Collection-Service erneuern Root- und Run-Lease während langer I/O- oder
Toolarbeit mit separaten Keepern; die Fachtransaktionen bleiben kurz. Der
vollständige Vertrag ist in ADR-0027 festgelegt.

### Persistierte Resolution und Review-Historie

Alembic `0013_resolution_review_core` ergänzt die Tabellen
`resolution_candidates`, `resolution_candidate_evidence`, `review_items` und
`review_decisions`. Kandidaten und ihre konkreten polymorphen Evidence-Links
werden atomar über einen dedizierten Store eingefügt; der generische
Update-by-ID-Repositorypfad ist für diese Snapshots nicht zulässig.

Review-Entscheidungen werden ausschließlich angehängt. `sequence_no` ordnet
auch Entscheidungen mit identischem Zeitpunkt eindeutig. Evidence-
Fingerprint, vollständiger Candidate-Set-Fingerprint und
`decision_compatibility_version` bilden den optimistischen Stale-Vertrag.
Migration `0013` ist additiv und verweigert einen Daten verlierenden Downgrade,
solange Resolution- oder Review-Daten existieren. Details stehen in ADR-0028.

### Persistierte Relation Candidates

Alembic `0014_relation_candidates` ergänzt die insert-only Tabellen
`relation_candidates` und `relation_candidate_evidence`. Jeder Snapshot ist
an einen expliziten abgeschlossenen `ScanRun`, kanonische Endpoints, ein
versioniertes Matcherprofil sowie materielle Evidence- und Candidate-Set-
Fingerprints gebunden. Der dedizierte Store reproduziert das reine
Matcher-Ergebnis vor dem Insert und validiert polymorphe Evidence-Referenzen
atomar gegen ihre konkrete Tabelle.

Matching-Review verwendet `ReviewType.MATCH_RELATION` und
`ReviewCandidateKind.RELATION` im bestehenden append-only Review-Core.
Kompatible ACCEPT-/REJECT-Entscheidungen dürfen bei unveränderter fachlicher
Semantik trotz neuer technischer Matcher-Version wiederverwendet werden;
DEFER bleibt reviewbar. Migration `0014` verweigert einen Daten verlierenden
Downgrade bei vorhandenen Relation-Candidate-Daten. Details stehen in
ADR-0031.

### Selektiver Kandidaten-Hash-Lookup

`DuplicateHashCandidateService` schränkt die Quick-Evidence zuerst auf die
aktuellen, weiterhin passenden Beobachtungen des neuesten abgeschlossenen
Scans ein. Die konsistenten mehrfach belegten Quick-Gruppen werden genau einmal
pro Invocation in einer verbindungslokalen Temp-Tabelle materialisiert.
Statistik und Keyset-Batches lesen anschließend nur diesen Snapshot. Zwischen
einem vollständig gelesenen Temp-Batch und dem atomaren Fingerprint-Write wird
die Read-Transaktion ausdrücklich beendet, damit SQLite keine Writer-Sperre
behält.

Alembic `0010_candidate_hash_lookup_index` ergänzt
`ix_fingerprints_target_profile_id_value` auf `target_kind`, Hashprofil,
`target_id` und `value`. Der Index unterstützt sowohl den aktuellen
Observation-Lookup als auch die Konsistenzprüfung mehrerer Fingerprint-Werte.
Die Temp-Tabelle bleibt flüchtiger Invocation-Zustand und verändert weder den
Evidence-Vertrag noch die persistierte Resume-Semantik aus ADR-0023.

Alembic `0011_candidate_hash_run_leases` ergänzt
`ebook_candidate_hash_runs`. Ein partieller Unique-Index erlaubt je
`scan_root_id` höchstens einen `RUNNING`-Lauf; terminale Historie bleibt
erhalten. Die Tabelle enthält keine Pfade, Dateinamen oder Hashwerte. Während
`SELECTING` bleiben Kandidatenzahlen `NULL`; danach publizieren `HASHING` und
`FINALIZING` Heartbeat, Lease-Ablauf sowie verarbeitete, erfolgreiche,
fehlgeschlagene und verbleibende Kandidaten.

Fingerprint-Insert und Fortschrittsfortschreibung eines Batches liegen in
derselben Transaktion und werden durch Run-ID, Lease-Token, `RUNNING`-Status
und noch nicht abgelaufene Lease gefencet. Ein stale Vorgänger kann nach einer
Übernahme weder seinen Heartbeat noch Fingerprints schreiben. Die allgemeine
`fingerprints`-Tabelle erhält bewusst keine neue Eindeutigkeitsregel, weil
mehrere provenance-behaftete Fingerprints desselben Targets legitim bleiben.

### Read-only Runtime- und Abschlussprüfung

Status- und Abschlussabfragen verwenden eine eigene SQLite-Engine mit URI-
Parameter `mode=ro` und `PRAGMA query_only=ON`. Dieser Pfad erzeugt weder das
Datenbankverzeichnis noch die Datenbankdatei, führt keine Migration aus und
setzt keine schreibenden Runtime-PRAGMAs. `immutable=1` wird nicht verwendet,
damit ein laufendes WAL nicht als unveränderlicher, möglicherweise veralteter
Snapshot behandelt wird.

`ebook-hash-status` projiziert den neuesten `EbookCandidateHashRun` als
pfadfreien Text- oder JSON-Status. `ebook-postscan-verify` vergleicht die
persistierte Revision mit dem paketierten Alembic-Head und prüft die
kritischen Tabellen und Indizes. Anschließend validiert der Befehl die
Source-Scan-, Kandidaten-Hash-, Inventar- und Collection-Lineage. Erwartete
Inventardateien werden ausschließlich im Speicher erneut gerendert und im
explizit adressierten privaten Artefaktverzeichnis bytegenau geprüft. Der
Verifier öffnet keine Source Media und schreibt weder Datenbank noch
Artefakte.

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

### Entschiedene Archive-Evidence-Grenze

ADR-0052 legt die additive Migration `0019_archive_evidence` mit den fünf
Tabellen `archive_observations`, `archive_observation_sources`,
`archive_observation_executions`, `archive_member_observations` und
`archive_wrapper_lineage` fest. Der dedizierte
`SQLiteArchiveEvidenceStore` ist insert-only und verwendet niemals den
generischen Update-by-ID-Pfad. Ein Member wird nicht im generischen
`FileRecord`-/`FileObservation`-Schema gespeichert. Konkrete Source-, Listing-,
Integrity- und spätere Extraction-`ToolExecution`-Referenzen bleiben erhalten.
Der Elternsnapshot bewahrt außerdem die vollständige Signature-v2-Projektion
einschließlich Suffix-/Container-/Inspection-Achsen sowie Parserstatus und den
nullable gelockten Formatfall. Gleiche Sourcebytes nach Umbenennung sind daher
nicht automatisch dieselbe Compatibility-Evidence.

Persistierbar sind ausschließlich opake `SecretHandle`- und
`secret_version`-Referenzen sowie feste Versuchstatus- und Quellklassen.
Secretmaterial, dessen Länge, Prefix, Hash oder eine rückrechenbare Ableitung
gehören weder in Tabellen noch `ToolResult`, `ToolArtifact`, Cache oder
Runtime-Berichte. Relative Memberlocator bleiben private Persistenzdaten und
werden nicht in öffentliche Status-/Report-DTOs projiziert.

Listing- und Member-Reuse binden mindestens vollständigen Archive-SHA-256,
Volumegruppenfingerprint, ToolProvider-/Tool-/Adapter-/Parserversion,
Listing-, Extraction- und Safety-Profil sowie Secret-Version oder `NONE`.
Ein neueres terminales Fehlerresultat darf keine ältere erfolgreiche
Ableitung als aktuell erscheinen lassen. Wrapper-Reuse bindet zusätzlich die
festen Image-/Command-/Frameprofile; innerer TAR-Hash und innere Größe bleiben
content-gebundene Ergebnisevidence.
Der Store fence-validiert jede atomare Transaktion gegen die vorhandene
ScanRoot-Write-Lease und rekonstruiert Contenthash, Memberidentitäten und
Sum-Types beim Read erneut. Bounds, Indizes, Idempotenz, Rollback und
Downgrade-Guard sind im ADR exakt festgelegt.

### Restartbare Archive-Collection

ADR-0053 trennt `archive-collection-orchestration/v1` vom allgemeinen
E-Book-Collection-Profil. Migration `0020_archive_collection_runs` ergänzt
eigene Run-, Item- und geordnete Source-Zeilen für einen immutable
Multi-Volume-Plan. Persistiert werden nur opaque Observation-IDs,
Hash-/Größenmaterial, Ordinale, feste Stagingrollen, Lifecycle und
Summenzähler; keine Pfade oder Memberlocator.

`ARCHIVE_COLLECTION_RUN` nimmt am gemeinsamen ScanRoot-Write-Fence teil.
Jeder Claim, Heartbeat, Evidence-/Itemabschluss und Runübergang validiert
Token, Ablauf und Fence-Epoch atomar. Ein stale Resume übernimmt denselben
Plan und setzt nur verwaiste `RUNNING`-Items zurück. Der Statusbericht öffnet
SQLite read-only, aggregiert bounded in SQL und gibt weder Source-IDs noch
Hashes, Pfade, Locator oder Secrets aus.

### Immutable CollectionState-Snapshots

Migration `0023_collection_state` ergänzt die Tabellen
`collection_state_snapshots`, `collection_state_components`,
`collection_state_counts` und `collection_state_items`. Update- und Delete-
Trigger machen Parent- und Childzeilen insert-only. Ein belegter Snapshot
verhindert den Downgrade, damit keine Projektion still verloren geht.

`SQLiteCollectionStateStore` bindet genau einen abgeschlossenen book-only
`ScanRun` und liest seine aktuelle sowie ältere relevante Evidence in stabilen
Keyset-Batches. Der erste Pass berechnet Komponenten, vollständige Zähler und
den kanonischen Item-Stream-Digest. Nach dem Parent-Insert rekonstruiert der
zweite Pass dieselben Items; eine Abweichung bricht die gesamte Transaktion ab.
Identische kanonische Daten verwenden denselben content-addressed Snapshot,
geänderte Evidence erzeugt einen neuen Parent.

Der gespeicherte Itemzustand enthält opaque File-/Observation-IDs, technische
Summen sowie komponentenbezogene Zustände und Digests, aber keine Pfade oder
Metadatenwerte. Der öffentliche Report prüft Parent und Item-Stream erneut
über eine echte SQLite-Read-only-Verbindung und gibt interne Evidence- und
Item-Digests nicht aus.

### Snapshotgebundener CollectionQuery-Index

Migration `0024_collection_state_diff_query` ergänzt
`collection_query_indexes`, `collection_query_documents` und
`collection_query_values` sowie eine lokale FTS5-Projektion. Parent,
Dokumente und Werte sind insert-only. Der Parent bindet genau einen
`CollectionStateSnapshot`; vollständige Counts, Coverage, Truncation und
Digests erlauben einen deterministischen Rebuild und die Verifikation einer
idempotenten Wiederholung. Deklarierte Dokument- und Wertanzahlen begrenzen
zulässige Ordinale; zusammen mit Eindeutigkeit verhindern sie nach dem
vollständigen Build weitere Appends.

Dokumentzeilen speichern nur opaque File-/Observation-IDs, Format und feste
Komponentenzustände. Wertzeilen enthalten diese technischen Filter,
Finding-Codes und ausgewählte private `METADATA_CANDIDATE`-Werte. Es gibt kein
eigenes Pfad-/Locatorfeld und weder Content, OCR noch Query-History; da ein
beobachteter Candidate selbst private Freitextwerte tragen kann, bleibt der
gesamte Index private Runtime-Persistenz. FTS5 übernimmt ausschließlich
normalisierte `METADATA_CANDIDATE`-Werte und wird nur über gebundene Parameter
eines validierten Query-AST gelesen. Die Suche öffnet SQLite mit `mode=ro` und
`query_only=ON`; absolute Pfadwerte werden auch bei expliziter privater
Textausgabe unterdrückt.

### Immutable Library-Health-Projektion

Migration `0025_library_health` ergänzt `library_health_snapshots`,
`library_health_dimensions`, `library_health_findings` und
`library_health_samples`. Alle vier Tabellen sind insert-only; deklarierte
Parent-Counts und bounded Insert-Trigger versiegeln die gültigen Child-
Ordinale. Ein Downgrade wird verweigert, sobald eine der Tabellen Daten
enthält.

Der Health-Parent bindet exakt den `CollectionState`-Content-Digest und den
Content-Digest des snapshotgebundenen Query-Indexes. Dimension-, Finding- und
Sample-Digests werden bei jedem Read vollständig rekonstruiert und geprüft.
Die Projektion speichert vollständige Counts, aber je Finding höchstens 64
opaque File-/Observation-ID-Paare; Pfade, Metadatenwerte, Fingerprints,
Query-Werte und Evidence-Digests werden nicht als Sample übernommen. Ein vor
Migration `0025` vorhandener Snapshot erhält Health nur durch einen erneuten
`collection-state-build`, der zuerst die zugrunde liegende Evidence
revalidiert.

### Insert-only Metadatenkorrekturpläne

Migration `0026_metadata_correction_plans` erweitert den generischen Review-
Core additiv um die fest gepaarten Literale `METADATA_CORRECTION` und
`METADATA_CORRECTION_CANDIDATE`. Weil SQLite bestehende Check-Constraints
nicht direkt erweitert, rekonstruiert die Migration die Review-Tabellen in
Abhängigkeitsreihenfolge. Vorhandene `ReviewItem`-, `ReviewDecision`- und
`ConsolidationPlan`-Reviewzeilen werden bytewertgleich übernommen. Ein leerer
Downgrade stellt den vorherigen Constraint wieder her; vorhandene Metadata-
Correction-Daten oder -Reviewfälle sperren den Downgrade.

Vierzehn normalisierte Tabellen speichern Candidate, Feldkorrekturen,
beobachtete und ausgewählte private Werte, Feld- und Candidate-Evidence,
Dependencies sowie Plan, Review-Snapshot, Preconditions, Verifikation und
Blocker. Parent-Counts und bounded Insert-Trigger begrenzen jeden Child-Graph.
Update und Delete werden auf allen Tabellen durch Trigger abgewiesen. Der
Content Hash bleibt der semantische Idempotenzschlüssel; ein abweichender
Payload unter derselben Identität wird nicht überschrieben.

`SQLiteMetadataCorrectionStore` validiert vor dem Candidate-Insert den
abgeschlossenen book-only `ScanRun`, die exakte File-/Observation-Lineage,
Full-SHA-256-Evidence, polymorphe ValueAssertion-/ToolResult-/Fingerprint-
Referenzen, Zielträger und alle drei Dependency-Achsen. Vor dem Plan-Insert
prüft er zusätzlich die neueste kompatible Review Decision und rekonstruiert
den erwarteten Plan mit dem kanonischen Reducer. Reads rehydrieren Values,
Evidence, Dependencies, Reviews, Preconditions, Verifikation und Blocker mit
harten Obergrenzen und berechnen Candidate- und Planidentität erneut.

Die Planung benötigt keine `ScanRootWriteLease`: Sie öffnet keine Source Media
und schreibt nur neue immutable Datenbankzeilen. Private Metadatenwerte liegen
ausschließlich in `metadata_correction_values`; Fehlertexte und die Standard-
Reportfläche übernehmen sie nicht. `ebook-metadata-correction-report` öffnet
die bestehende Datenbank mit `mode=ro` und `query_only=ON`, rehydriert genau
einen Plan bounded über den Store und projiziert nur erlaubte opaque IDs,
Profile, Statuswerte, Content Hash, Zielträger, Format, Feldpfade,
Operationen, Counts, Reviewstatus und Blockerliterale.

### Gefencete Metadaten-Write-Authorization und Journal

Migration `0027_metadata_write_operations` erweitert den bestehenden
`ScanRootWriteLease`-Owner-Vertrag um `METADATA_WRITE_PREPARATION` und
`METADATA_WRITE_RUN`. Die neuen Tabellen `metadata_write_authorizations`,
`metadata_write_runs` und `metadata_write_events` speichern genau den durch
ADR-0063 begrenzten EPUB-Titelwriter. Authorization und Run sind durch
No-Update-/No-Delete-Trigger immutable; Events sind gapless, append-only und
auf höchstens 16 Sequenzeinträge je Run begrenzt.
Die eindeutige `authorization_id` im Run macht jede Authorization genau einmal
verbrauchbar. Ein Downgrade wird verweigert, sobald eine der drei Tabellen
Daten enthält.

Die content-addressed Authorization übernimmt den vollständigen Prepare-
Snapshot: W9-Plan-ID und -Content-Hash, File-/Observation-/Root-Identität,
erwartete Input-/Output-Hashes und -Größen, `dcterms:modified`, Capability-ID,
Writer-/Patcher-/Staging-/Validatorprofile, konkrete Toolversionen, den
Validator-Set-Fingerprint, Preparation-Fence und ein höchstens 15 Minuten
offenes Zeitfenster. Vor dem Insert revalidiert
`SQLiteMetadataWriteStore` den unveränderten aktuellen Plan, seine Source-/
Evidence-/Dependency-Lineage und die neueste kompatible akzeptierte Review
Decision in derselben gefenceten Transaktion.

Ein Run entsteht nur unter einer neuen `METADATA_WRITE_RUN`-Lease und
verbraucht die Authorization zusammen mit seinem `CREATED`-Event atomar.
Jedes Folgeevent muss die tatsächlich aktuelle Fence-Epoch, die nächste
gapless Sequenz, einen erlaubten Statusübergang und einen monotonen Zeitpunkt
tragen. Der Status-Read selektiert ausschließlich opaque IDs, Profile,
Zeitpunkte und Zustände. Pfade, Titelwerte, Source-/Output-Hashes,
Capability-Inhalte, Fence-Epochs, Findings und Confirmation-Digests werden
nicht gelesen oder projiziert. Capability-Pfade stammen ausschließlich aus
einer privaten, bounded und owner-only geschützten Runtime-Konfiguration und
werden nicht in SQLite übernommen. Migration und Store führen keine Source-
Media-Operation aus.

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

Cross-table polymorphic target validation, allgemeine unbeschränkte Query-Repositories,
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
