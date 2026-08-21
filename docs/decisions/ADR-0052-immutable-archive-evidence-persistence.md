# ADR-0052: Immutable Archive-Evidence-Persistenz

- Status: Accepted
- Datum: 2026-08-21

## Kontext

Die direkte Archive-Strecke und die getrennte Wrapper-Strecke erzeugen
begrenzte, secretfreie Listing-/Integrity-Ergebnisse mit exakter
`ToolExecution`-, Signature-, Parser-, Formatlock- und Material-Lineage.
Extraction bleibt wegen der leeren Workspace-Backend-Allowlist
`TOOL_UNAVAILABLE`. Dieser Blocker verhindert nicht, abgeschlossene read-only
Evidence sicher und restartbar zu speichern.

ADR-0038 und ADR-0039 definieren immutable `ArchiveObservation`- und
`ArchiveMemberObservation`-Snapshots sowie konservative Reuse-Profile, lassen
Migration, Tabellen, Indizes und Writer-Fencing aber offen. Die aktuelle
Alembic-Revision ist `0018_book_classification_projection`. Dieses Gate
schließt die Lücke ohne Runtime-, Extraction-, Secret- oder
Source-Mutationsauthority zu erweitern.

Diese Entscheidung ersetzt ausschließlich die historischen Aussagen in
ADR-0038 und ADR-0039, dass noch keine konkrete Archive-Migration oder
Tabellennamen festgelegt seien. Deren Runtime-, Privacy-, Reuse- und
Nicht-Mutationsgrenzen bleiben verbindlich.
Sie erfüllt außerdem das von ADR-0051 verlangte Persistenzgate für Wrapper-
Command-/Image-/Frame-Lineage und den inneren Streamdigest; die read-only
Wrapper-Runtime selbst wird nicht geändert.

## Entscheidung

Archive-Evidence wird als atomarer insert-only Snapshotgraph gespeichert. Der
Graph besitzt einen Elternsnapshot und ausschließlich begrenzte Source-,
Execution-, Member- und optionale Wrapper-Lineage. Es gibt keinen generischen
`save()`-/Update-by-ID-Pfad.

Die additive Migration heißt exakt `0019_archive_evidence`, folgt auf
`0018_book_classification_projection` und legt fünf Tabellen an:

```text
archive_observations
archive_observation_sources
archive_observation_executions
archive_member_observations
archive_wrapper_lineage
```

### `archive_observations`

Ein Elternsnapshot enthält exakt:

```text
id
profile
content_hash
scan_root_id
source_scan_run_id
observed_at
archive_full_sha256
archive_content_fingerprint
volume_group_fingerprint
signature_profile
compatibility_profile
container_class
suffix_kind
publication_kind
storage_family
outer_compression_kind
recognition_status
inspected_bytes
structural_confirmation_required
provider_profile
runner_profile
parser_profile
parser_status
format_case_kind
format_lock_profile
format_lock_sha256
listing_profile
integrity_profile
extraction_profile
safety_profile
secret_version
listing_status
encryption_status
integrity_status
extraction_status
password_attempt_status
extraction_policy_status
member_count
writer_owner_kind
writer_owner_run_id
writer_fence_epoch
```

`profile` ist exakt `archive-observation/v1`. `content_hash` ist ein
domain-separierter SHA-256 über das kanonische vollständige Snapshotmaterial
einschließlich aller geordneten Kindzeilen und Writer-Provenance;
Datenbank-Rowids und der geheime Lease-Token gehören nicht hinein. Die
kanonische Serialisierung folgt `canonical-json/v1`: UTF-8, NFC, sortierte
Objektschlüssel, kompakte Separatoren, feste Feldnamen, keine Floats und keine
nicht endlichen Zahlen.

`archive_full_sha256` bezeichnet den primären Source-Stream.
`archive_content_fingerprint` bindet die vollständige geordnete Sourcegruppe;
`volume_group_fingerprint` bindet deren Volumevertrag. Alle drei Werte sind
lowercase SHA-256. `member_count` liegt zwischen `0` und `10.000` und stimmt
exakt mit den Kindzeilen überein.

`id` ist eine kanonische `EntityId`, die der Caller vor dem Toollauf erzeugt
und bereits an die privaten Memberprojektionen bindet. Sie ist Teil des
gehashten Snapshotmaterials. `content_hash` ist keine alternative ID und darf
nicht öffentlich berichtet werden.

Die Signature-Lineage ist vollständig: `container_class`, `suffix_kind`,
Publication, Storage, äußere Kompression, Recognition, `inspected_bytes` und
`structural_confirmation_required` müssen exakt dieselbe gültige
`ArchiveSignatureObservationV2` ergeben. Damit kann eine Umbenennung oder eine
andere Publication-/Suffixprojektion nicht unter unveränderten Sourcebytes
still wiederverwendet werden. `inspected_bytes` liegt zwischen `0` und `512`.

`parser_status` stammt aus `ArchiveSevenZipSltParseStatus`. Genau bei
`PARSED` ist `format_case_kind` gesetzt und gehört zur final gelockten
`(parser storage family, format case)`-Zelle; bei allen anderen Parserstatus
ist es `NULL`. Bei Wrappern ist die Parser-Storage-Familie die in
`archive_wrapper_lineage` gebundene innere Familie `TAR`, nicht die
Source-Storage-Familie `UNKNOWN`. Ohne diese Achsen ist ein Snapshot weder
persistierbar noch wiederverwendbar.

Für v1 gelten ausschließlich folgende feste Produktionsidentitäten:

```text
signature_profile     = archive-signature-observer/v2
compatibility_profile = archive-publication-storage-compatibility/v1
provider_profile      = archive-7zip-provider/v1
                       | archive-7zip-wrapper-provider/v1
runner_profile        = archive-linux-container-runner/v1
                       | archive-wrapper-container-runner/v1
parser_profile        = archive-7zip-slt-parser/v3
format_lock_profile   = archive-7zip-format-lock/v1
format_lock_sha256    = 4270fbf6ba7782c3b2fb1025137581ce07a1bc271664e19692dce388a617e061
listing_profile       = archive-listing/v1
integrity_profile     = archive-integrity/v1
extraction_profile    = archive-extraction/v1
safety_profile        = archive-safety-policy/v1
secret_version        = NONE
```

Direkte und Wrapper-Provider-/Runnerprofile dürfen nur in ihrer jeweiligen
Paarung vorkommen. Ein neuer Profilwert benötigt eine additive Compatibility-
Entscheidung und darf nicht still als v1 gelesen werden.

Die Statuswerte stammen aus den bestehenden Enum-Allowlists. Ein `LISTED`-
Snapshot bindet eine Listing-Execution. Ein getesteter Integrity-Status bindet
zusätzlich eine davon verschiedene Integrity-Execution. Extraction-Status und
-Execution bleiben bis zur Freigabe von S-EBAR-04A/EBAR-06 `NOT_ATTEMPTED`
beziehungsweise abwesend. Cancellation bleibt snapshotlos: Ihre
`ToolExecution` wird gespeichert, aber es entsteht keine
`archive_observations`-Zeile.

Null Execution-Zeilen sind nur bei `listing_status = NOT_ATTEMPTED`,
`integrity_status = NOT_TESTED`, `extraction_status = NOT_ATTEMPTED` und
`member_count = 0` zulässig. Eine Execution-Zeile ist ausschließlich die
Listing-Rolle. Zwei Zeilen sind Listing plus Integrity. Drei Zeilen werden
erst nach der separaten Extraction-Freigabe zulässig. Rollen und Elternstatus
müssen stets dieselbe Sum-Type-Projektion bilden.

### Source-Lineage

`archive_observation_sources` besitzt den Primärschlüssel
`(archive_observation_id, source_ordinal)` und enthält:

```text
archive_observation_id
source_ordinal
file_observation_id
source_full_sha256
source_size_bytes
staging_name
```

Es existieren `1..256` Zeilen mit lückenlosen Ordinalen. Jede
`file_observation_id` ist innerhalb des Snapshots eindeutig, gehört zum
gespeicherten `source_scan_run_id`, dessen `ScanRun` zu demselben
`scan_root_id` gehört und `COMPLETED` ist, und bindet einen vorhandenen `FILE_SHA256`-
Fingerprint mit `sha256/1` und exakt demselben Wert. Alle Source-
`FileRecord`s müssen beim Schreiben `PRESENT` sein und dieselbe Größe tragen.
`staging_name` folgt ausschließlich der bestehenden opaken
`archive[.volume]`-Grammatik, enthält keinen Source-Pfad und ist innerhalb der
Gruppe case-insensitive eindeutig; exakt ein Eintrag heißt `archive`.

`archive_content_fingerprint` ist SHA-256 über die Domain
`archive-content-fingerprint/v1\0` und kanonisches JSON der geordneten
`file_observation_id`-/`source_full_sha256`-Paare.
`volume_group_fingerprint` verwendet unverändert die bestehende Domain
`archive-volume-group/v1\0` und kanonisches JSON der geordneten
`full_sha256`-/`size_bytes`-/`staging_name`-Tripel. Der Store berechnet beide
Werte neu; Callerwerte sind keine Authority.

### Execution-Lineage

`archive_observation_executions` besitzt den Primärschlüssel
`(archive_observation_id, execution_role)` und enthält:

```text
archive_observation_id
execution_role
tool_execution_id
```

`execution_role` ist ausschließlich `LISTING`, `INTEGRITY` oder `EXTRACTION`.
Eine `ToolExecution` darf innerhalb eines Snapshots nur einmal vorkommen. Der
Store prüft Provider, Toolversion, Adapterversion, Capability,
`input_identity`, `config_identity`, terminalen Status und die exakte
Statusprojektion des Elternsnapshots. Listing und Integrity sind verschiedene
Datensätze. Wrapper verwenden dieselben Rollen; ihr Composite-Vertrag steht
in `archive_wrapper_lineage`.

### Member-Lineage und Privacy

`archive_member_observations` besitzt den Primärschlüssel
`(archive_observation_id, member_ordinal)` und enthält:

```text
archive_observation_id
member_ordinal
profile
member_identity
member_path_safe
member_kind
declared_compressed_bytes
declared_uncompressed_bytes
observed_uncompressed_bytes
member_sha256
crc_status
encryption_status
listing_profile
extraction_profile
safety_profile
secret_version
```

`profile` ist exakt `archive-member-observation/v1`. Ordinale sind lückenlos
`0..member_count-1`. `member_identity` ist innerhalb eines Snapshots eindeutig
und wird aus vollständigem Archivhash, Volumegruppenfingerprint, privatem
NFC-Locator, Ordinal und Listingprofil neu berechnet. Größen sind nullable oder
Ganzzahlen zwischen `0` und `2.147.483.648`. Locator sind relative, durch die
bestehende Safety-Policy akzeptierte NFC-Werte mit höchstens 1.024 Codepoints,
4.096 UTF-8-Bytes und 128 Segmenten.

`member_path_safe` ist private Datenbank-Evidence. Kein öffentlicher Report,
Fehler, Log, `repr`, `str`, JSON-/CSV-Export oder Query-DTO darf ihn, seinen
Hash oder einen Rawstream ausgeben. Es gibt keinen Locatorindex. Extraction-ID,
beobachtete Größe und Member-SHA-256 bleiben gemeinsam abwesend, bis eine
vollständig erfolgreiche Extraction später separat freigegeben wird.
Nichtreguläre Member dürfen niemals Extraction-Evidence tragen. Teilmengen
sind nicht persistierbar.

### Wrapper-Lineage

`archive_wrapper_lineage` ist eine optionale One-to-one-Tabelle mit
`archive_observation_id` als Primär- und Fremdschlüssel. Eine Zeile existiert
genau dann, wenn `outer_compression_kind` `GZIP`, `BZIP2`, `XZ` oder `ZSTD`
ist. Sie enthält:

```text
archive_observation_id
profile
inner_storage_family
inner_stream_size_bytes
inner_stream_sha256
frame_profile
wrapper_runner_profile
image_reference
wrapper_command_identity
listing_command_identity
integrity_command_identity
```

`profile` ist `archive-7zip-wrapper-provider/v1`,
`inner_storage_family` ist ausschließlich `TAR`, die innere Größe liegt
zwischen `1.024` und `8.589.934.592`, und alle Hash-/Commandidentitäten sind
lowercase SHA-256. Parent und Wrapperzeile müssen dieselben festen Runner-,
Parser-, Formatlock-, Compatibility- und Imageidentitäten wie der versiegelte
W03-Outcome tragen. Direkte Archive besitzen keine Wrapperzeile.

Die v1-Imageidentität ist exakt
`ghcr.io/gecompat/foliotone-archive-7zip@sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287`.
Jede andere Referenz ist inkompatibel.

S-EBAR-07 darf den bestehenden privaten Provider-Handoff ausschließlich so
erweitern, dass bei jedem direkten oder Wrapper-`LISTED`-Outcome derselbe
bereits erzeugte locatortragende Listing-/Parserwert auch für die Persistenz
versiegelt verfügbar bleibt. Das gilt auch für gelistete Datenverschlüsselung,
ohne dadurch Integrity oder Extraction zu starten. Die Änderung erweitert
weder den öffentlichen Provider-Outcome noch den Extraction-Handoff und
startet keinen zweiten Toollauf.

## Reuse

`archive-listing-reuse/v1` bleibt der konservative Basisschlüssel aus:

```text
archive_full_sha256
volume_group_fingerprint
tool_provider_id
tool_version
adapter_version
parser_version
listing_profile
extraction_profile
safety_profile
secret_version
```

Die Persistenzquery verlangt zusätzlich exakte Signature-, Compatibility-,
Provider-, Runner-, Parserstatus-/Formatfall- und Formatlockidentitäten. Bei
Wrappern müssen außerdem
Frame-, Image- und alle drei Commandidentitäten kompatibel sein. Der
persistierte innere Hash und die innere Größe sind content-gebundene
Ergebnisevidence und werden beim Read revalidiert; sie müssen für den
Reuse-Lookup nicht vor dem Lauf erneut bekannt sein. Der v1-Schlüssel wird
nicht umdefiniert; die Zusatzlineage ist eine Compatibility-Bedingung.

Listing-Reuse liefert den neuesten exakt kompatiblen `LISTED`-Snapshot nach
`observed_at DESC, id DESC`. Member-Reuse mit `archive-member-reuse/v1` ist
ausschließlich für direkte Snapshots mit vollständiger späterer `EXTRACTED`-
Evidence zulässig. Wrapper können vor einem eigenen Extraction-Gate niemals
Member-Reuse liefern.

Fehler-, Timeout-, Limit-, Policy- und Tool-unavailable-Snapshots bleiben
auditierbar, nehmen aber nicht an einer Erfolgsquery teil. Ein neuerer Fehler
überschreibt oder maskiert daher keinen älteren exakt kompatiblen Erfolg.
Jede Material-, Profil-, Tool-, Adapter-, Parser-, Formatlock-, Secret- oder
Wrapperabweichung ist stale und führt zu einem neuen Lauf.

## Writer-Fencing und Transaktion

Jeder Schreibaufruf verlangt eine echte `OwnedScanRootWriteLease`. In dieser
Welle sind nur die vorhandenen Owner-Klassen `EBOOK_ANALYSIS` und
`EBOOK_COLLECTION_RUN` zulässig. Der dedizierte Store:

1. beginnt genau eine SQLite-Schreibtransaktion;
2. fence-validiert Root, Owner-Klasse, Owner-Run, geheimen Lease-Token,
   `fence_epoch` und Ablaufzeit gegen `scan_root_write_leases`;
3. validiert die vollständige Source-, Execution-, Profil- und Sum-Type-
   Lineage;
4. fügt Parent und alle Kinder atomar ein oder erkennt eine kanonisch
   bytegleiche Wiederholung;
5. fence-validiert unmittelbar vor Commit erneut.

Der Snapshot speichert Owner-Klasse, Owner-Run und Epoch, niemals den
Lease-Token. Ein verlorenes, abgelaufenes oder übernommenes Fence führt zu
einem festen pfadfreien Storefehler und vollständigem Rollback. Pro Aufruf ist
genau ein Snapshot mit höchstens 256 Sources, drei Executions, 10.000 Members
und einer Wrapperzeile zulässig; kein unbounded Batchpfad wird eingeführt.

Gleiche `id` plus gleicher `content_hash` und bytegleich rekonstruierter Graph
ist eine idempotente Wiederholung. Gleiche `id` oder gleicher `content_hash`
mit abweichendem Graph ist eine Kollision und scheitert. Eine Transaktion darf
keine vorhandenen Zeilen aktualisieren oder löschen.

## Tabellenconstraints und Indizes

Migration `0019_archive_evidence` erzwingt mindestens:

- Fremdschlüssel auf ScanRoot, ScanRun, FileObservation, ToolExecution und
  alle Parent-/Kindtabellen;
- feste Profil-, Enum-, SHA-256-, Ordinal-, Größen-, Status- und nullable
  Sum-Type-Checks;
- `UNIQUE(content_hash)` auf `archive_observations`;
- `UNIQUE(archive_observation_id, file_observation_id)` für Sources;
- `UNIQUE(archive_observation_id, tool_execution_id)` für Executions;
- `UNIQUE(archive_observation_id, member_identity)` für Members;
- `ix_archive_observations_scan_run_observed` auf
  `(scan_root_id, source_scan_run_id, observed_at, id)`;
- `ix_archive_observations_listing_reuse` auf der vollständigen materiellen
  Baseline plus `listing_status`, `observed_at` und `id`;
- `ix_archive_observations_member_reuse` auf derselben Baseline plus
  `extraction_status`, `observed_at` und `id`;
- `ix_archive_observation_sources_file` auf
  `(file_observation_id, archive_observation_id)`;
- `ix_archive_observation_executions_tool` auf
  `(tool_execution_id, archive_observation_id)`.

Beim Downgrade darf `0019` die fünf Tabellen nur entfernen, wenn alle leer
sind; andernfalls stoppt die Migration fail-closed.

## Dedizierter Store und gebundene Reads

`SQLiteArchiveEvidenceStore` besitzt ausschließlich:

```text
create_or_get(snapshot, write_lease, committed_at)
get_by_id(id)
find_listing_reuse(key, compatibility)
find_member_reuse(key, compatibility)
list_for_source_observation(file_observation_id, limit)
```

`limit` liegt zwischen `1` und `100`. Alle Reads verwenden SQL-Limits und
laden Kinder nur für den ausgewählten Parent beziehungsweise die begrenzte
Parentmenge. Overflow scheitert pfadfrei; es gibt kein `list_all`, Offset-
Paging oder generisches Repository. Rehydrierung berechnet `content_hash`,
Memberidentitäten, Statusmatrix und Wrapperbindung erneut und weist korrupte
oder ältere Schemas fail-closed ab.

## Folgepaket S-EBAR-07

S-EBAR-07 darf exakt folgende Dateien ändern oder hinzufügen:

```text
src/foliotone/archive/provider.py
src/foliotone/persistence/archive_schema.py
src/foliotone/persistence/archive.py
src/foliotone/persistence/alembic/versions/0019_archive_evidence.py
src/foliotone/persistence/__init__.py
tests/unit/test_ebar05_archive_provider.py
tests/integration/test_archive_persistence.py
tests/integration/test_database_fixtures.py
tests/integration/test_persistence.py
```

Die beiden zentralen Integrationstests dürfen ausschließlich die erwartete
Alembic-Head-/Tabellen-/Indexmenge von `0018` auf `0019` aktualisieren.

Pflichttests sind:

- Upgrade `0018 -> 0019`, leere Neuinstallation, wiederholtes Upgrade und
  bewachter leerer/nichtleerer Downgrade;
- direkte DDL-Negativtests für Profile, Enumwerte, SHA-256, Bounds,
  Ordinale, Fremdschlüssel und nullable Sum-Types;
- atomarer direkter und Wrapper-Roundtrip mit exakt denselben
  ToolExecution-/Source-/Profil-/Formatlockidentitäten;
- exakte Wiederholung, ID-/Hashkollision und injizierter Rollback nach jeder
  Kindtabellenphase;
- fremder Root/Run/Filehash, fehlender oder falscher ToolExecution-Status,
  nichtkontiguierliche Members, Signature-/Suffix-/Parserfall-Drift und
  manipulierte Wrapperlineage;
- verlorenes, abgelaufenes und übernommenes Writer-Fence;
- erfolgreicher Reuse trotz neuerem Fehler sowie Stale-Fälle für jede
  materielle Schlüssel-/Compatibilityachse;
- gebundene Reads, reale Indexpläne und path-/Locator-/Secret-freie Fehler;
- Nachweis, dass W03 denselben privaten Listingwert ohne zweiten Toollauf an
  den Store übergibt und weiterhin keinen öffentlichen Locator exportiert.

Gezielte lokale Tests und statische Prüfungen laufen pro Änderung. Eine breite
Suite wird erst einmal im stabilen PR-CI ausgeführt.

## Nicht autorisiert

Diese Entscheidung autorisiert nicht:

- Extraction, Workspace-Backend, Passwortversuch oder Secretkanal;
- Source-, Sidecar-, Archiv- oder Membermutation;
- Raw-stdout/-stderr, ToolArtifact, öffentliche Locator oder Secretmaterial;
- Archive-aware Matching, Keep Preference, Quarantäne oder Metadatenwrites;
- Collection-Orchestrierung, Heartbeat oder neue Lease-Owner-Klassen;
- PostgreSQL, Onlineprovider oder W10.

FG-A-SECRET und die Workspace-Backend-Revalidation bleiben unabhängig
blockiert. Nach S-EBAR-07 folgt EBAR-08 als eigenes Orchestrierungs- und
Fencingpaket.
