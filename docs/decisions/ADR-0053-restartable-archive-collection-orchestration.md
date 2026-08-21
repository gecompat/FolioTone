# ADR-0053: Restartbare Archive-Collection-Orchestrierung

- Status: Accepted
- Datum: 2026-08-21

## Kontext

ADR-0052 und S-EBAR-07 persistieren genau einen immutable direkten oder
Wrapper-Archive-Graphen unter einem vorhandenen ScanRoot-Fence. Für eine reale
Collection fehlen weiterhin ein stabiler Plan, begrenzte Konkurrenz,
Heartbeat, stale Resume und ein path-freier Fortschrittsbericht.

Der allgemeine `ebook-collection-analysis/v1`-Lauf kann nicht wiederverwendet
werden. Er plant einzelne EPUB/MOBI/AZW/AZW3/PDF-Beobachtungen. Ein
Archive-Item kann dagegen mehrere Volume-Beobachtungen besitzen, erzeugt eine
eigene `ArchiveEvidenceSnapshot` und verwendet andere Status-, Reuse- und
Privacyregeln. Eine stille Erweiterung seiner Tabellen oder Statusliterale
würde beide Profile unprüfbar vermischen.

## Entscheidung

FolioTone führt das Profil `archive-collection-orchestration/v1` ein. EBAR-08
implementiert einen eigenständigen, restartbaren und ausschließlich
read-only gegenüber Source Media arbeitenden Archive-Lauf.

### Stabiler Plan

Ein neuer Lauf bindet genau einen expliziten `ScanRoot` und dessen neuesten
`COMPLETED`-`ScanRun`. Die Planung liest ausschließlich `PRESENT`-
`FileObservation`-/`FileRecord`-Zeilen dieses Scans, deren relativer Pfad,
Größe und Änderungszeit zwischen Record und Observation übereinstimmen.

EBAR-08 ergänzt in `archive.signatures` eine reine bounded
`partition_archive_volume_names()`-Grenze. Der Orchestrator gruppiert zuerst
nach privatem Parentverzeichnis und übergibt nur Basenames. Die Funktion
partitioniert jede Eingabemenge deterministisch in direkte Einzelarchive,
vollständige New-RAR-, Old-RAR-, 7z- und als unsupported markierte
Split-ZIP-Volumegruppen sowie feste Findings für Lücken, Mehrdeutigkeit,
Kollisionen und verwaiste Volumes. Jedes
Eingabeelement wird exakt einmal konsumiert; unbekannte oder doppelt
beanspruchte Namen scheitern fail-closed. Sie führt kein Filesystem-I/O aus
und gibt keine Namen öffentlich aus.

Die Planung revalidiert jede Source und liest ausschließlich den bereits
gebundenen bounded Signature-Prefix der kanonischen Source. Die vorhandene
Signature-v2-Grenze erzeugt daraus die vollständige Publication-/Storage-/
Outer-/Recognition-Projektion. Der Plan persistiert ausschließlich:

- die opaque Item-ID und einen kontiguierlichen Planordinal;
- die primäre `FileObservation`-ID;
- alle gruppierten Source-`FileObservation`-IDs mit kontiguierlichem
  Sourceordinal;
- erwartete Größe und vollständigen `FILE_SHA256` jeder Source;
- eine feste, opaque Stagingrolle (`archive`, `archive.001` usw.);
- das Planungsprofil und den Source-`ScanRun`.
- die vollständige path-freie Signature-v2-Projektion der kanonischen Source.

Kandidaten sind ausschließlich die geschlossenen Suffixklassen `EPUB`,
`CBZ`, `CBR`, `ZIP`, `RAR`, `SEVEN_Z`, `TAR`, `TAR_GZIP`, `TAR_BZIP2`,
`TAR_XZ`, `TAR_ZSTD` und `UNSUPPORTED`. `OTHER` wird nicht geplant. Die
Publication-Klassen bleiben vollständig erhalten und dürfen auch nach
erfolgreichem Listing niemals als entbehrliche Verpackung interpretiert
werden. `UNSUPPORTED` und Split-ZIP dürfen einen auditierbaren
`NOT_ATTEMPTED`-/Fehlergraphen erzeugen, aber keinen Tool- oder
Extraction-Fallback.

Jede Source benötigt bereits vollständigen `FILE_SHA256` mit `sha256/1`.
Fehlende Hash-Evidence ist kein heimlicher Toollauf und keine partielle
Gruppe: Der Kandidat wird nicht geplant und der Lauf zählt ihn als
`HASH_EVIDENCE_MISSING`. Mehrdeutige, kollidierende, lückenhafte oder den
Bounds widersprechende Volumegruppen werden als feste Plan-Findings gezählt,
nicht geraten. Eine `FileObservation` darf in höchstens einem Item vorkommen.

Der Plan wird in stabiler privater Pfad-/Observation-ID-Reihenfolge mit
`fetchmany(500)` und begrenzten, jeweils gefenceten Schreibtransaktionen
erzeugt. Ein Run bleibt dabei `PLANNING`; Claim oder Providerlauf sind in
diesem Zustand verboten. Nach jedem Batch wird die Lease erneuert.
`--plan-limit` kann die geordneten vollständigen Gruppen deterministisch
begrenzen.

Jede Planzeile besitzt eine kanonische Content-Projektion. Nach Abbruch wird
die deterministische Enumeration ab Ordinal null wiederholt: Bereits
persistierte Ordinale müssen bytegleich dieselbe Projektion besitzen, fehlende
Suffixordinale werden ergänzt. Drift oder zusätzliche alte Ordinale brechen
fail-closed ab. Erst nach vollständiger Enumeration werden Plananzahl,
Finding-Counts und `plan_content_hash` in einer Transaktion versiegelt und der
Run auf `RUNNING` gesetzt. Ab dann bleibt der Plan immutable. Ein Resume ändert
weder Source-Scan, Gruppe, Workerzahl, Planlimit noch Profile.

### Persistenz und Migration

Alembic `0020_archive_collection_runs` ergänzt drei Tabellen:

- `archive_collection_runs` hält Root, Source-Scan, Profile, Workerzahl,
  Lifecycle, Planlimit, nullable-versiegelten `plan_content_hash`, Zähler,
  Lease und Fence-Epoch;
- `archive_collection_items` hält Planordinal, primäre Observation,
  Versuchszahl, technischen Status, optional genau eine terminale
  `archive_observation_id`, Reuse-Disposition, die vollständige Signature-v2-
  Projektion und einen festen Fehlercode;
- `archive_collection_item_sources` hält die geordneten Source-Observation-
  IDs, Hash-/Größenmaterial und opaque Stagingrollen; `run_id` wird für die
  gruppenweite Eindeutigkeit mitgeführt.

Die DDL erzwingt mindestens:

- eindeutige `(run_id, plan_ordinal)` und
  `(run_id, primary_file_observation_id)`;
- eindeutige `(run_id, file_observation_id)` über alle Item-Sources sowie
  `(item_id, source_ordinal)` und `(item_id, staging_name)`;
- Worker `1..2`, Planlimit entweder `NULL` oder positiv, Versuchszahl
  `0..65535`, SHA-256 als 64 lowercase Hex und nichtnegative Größen;
- `plan_content_hash IS NULL` nur für `PLANNING` oder einen vor Versiegelung
  terminal gescheiterten Run; jeder ausführbare oder abgeschlossene Run
  besitzt Hash und Plananzahl;
- `PENDING`/`RUNNING` ohne Archive-ID und Fehlercode, `SUCCEEDED` mit
  Archive-ID ohne Fehlercode, `FAILED` mit Archive-ID und Fehlercode sowie
  `ERROR` ohne Archive-ID und mit Fehlercode;
- Disposition `EXECUTED|REUSED` nur für `SUCCEEDED` oder `FAILED`;
  `FAILED` ist exakt `EXECUTED`, alle anderen Zustände besitzen keine
  Disposition;
- Foreign Keys zu Root, Scan, FileObservation und ArchiveObservation sowie
  geschlossene Profil-, Status-, Signature- und Finding-Literale.

Claim und Report verwenden die belegten Indizes
`(run_id, status, plan_ordinal)`, `(run_id, archive_observation_id)` und
`(file_observation_id, run_id, item_id)`; Offset-Pagination wird nicht
eingeführt. Ein partieller Unique-Index erlaubt je ScanRoot höchstens einen
Run in `PLANNING|RUNNING|INTERRUPTED`; ein neuer Start neben einem resumierbaren
Run wird abgelehnt.

Migration `0020` erweitert außerdem den geschlossenen CHECK der bestehenden
`scan_root_write_leases.owner_kind`-Spalte um `ARCHIVE_COLLECTION_RUN`. Der
SQLite-Batch-Rebuild erhält jede vorhandene Lease wertgleich; fremde oder
unbekannte Ownerwerte brechen die Migration ab.

Die Tabellen speichern keine relativen oder absoluten Pfade, keine Member-
Locator, keine Raw-Ausgabe, keine Secretkandidaten und keine extrahierten
Bytes. Jede Itemzeile und ihre Source-Zeilen werden atomar geschrieben; die
separate finale Runtransaktion versiegelt Anzahl, Findings und Planhash. Der
Downgrade ist bei einer belegten neuen Tabelle gesperrt.

Run-Zustände sind `PLANNING`, `RUNNING`, `INTERRUPTED`, `FAILED`, `COMPLETED`
und `COMPLETED_WITH_FAILURES`. `FAILED` ist ausschließlich ein nicht
resumierbarer Plan-/Persistenzkonflikt unter noch gültigem Fence.
Item-Zustände sind `PENDING`, `RUNNING`,
`SUCCEEDED`, `FAILED` und `ERROR`. Ein persistierter Graph mit
`listing_status=LISTED` ist `SUCCEEDED`, auch wenn er konservativ
Verschlüsselung oder fehlende Integrität festhält. `FAILED` steht für einen
erwarteten terminalen Provider-/Parser-/Toolstatus, dessen auditierbarer
Fehlergraph ebenfalls vollständig persistiert wurde; `ERROR` für einen
Orchestrierungs- oder Vertragsfehler ohne Graph. Genau `SUCCEEDED` und
`FAILED` binden eine `archive_observation_id`; diese muss zum selben Root,
Source-Scan und exakt derselben geordneten Sourcegruppe gehören.

### Lease, Fencing und Resume

`ScanRootWriteOwnerKind` erhält exakt `ARCHIVE_COLLECTION_RUN`. Ein Lauf
besitzt zugleich seine Run-Lease und die root-weite Write-Lease mit demselben
opaque Token und Owner-Run. Die Standarddauer beträgt 30 Minuten; der
Heartbeat läuft spätestens alle 60 Sekunden und zusätzlich vor Claim, nach
jedem Itemabschluss und vor dem terminalen Run-Übergang.

Jeder Plan-, Claim-, Itemabschluss-, Heartbeat- und Runabschluss-Write prüft
Token, Owner, Ablauf und Fence-Epoch in derselben Transaktion. Ein verlorenes,
abgelaufenes oder übernommenes Fence darf weder Archive-Evidence noch Item-
oder Runstatus schreiben. Die bestehende S-EBAR-07-Storegrenze erhält die
konkrete `OwnedScanRootWriteLease`; es entsteht kein zweiter oder schwächerer
Writerpfad.

Eine aktive Lease blockiert Start und Resume. Ein ungeleaster, nichtterminaler
Run blockiert einen neuen Start und verlangt explizites Resume. Nach Ablauf
darf nur ein
explizites Resume denselben Run übernehmen. Es erhöht den Fence-Epoch atomar
und ersetzt Token/Ablauf. Ein verwaister `PLANNING`-Run setzt die exakt
deterministische Planenumeration wie oben beschrieben fort. Ein versiegelter
Run setzt ausschließlich verwaiste `RUNNING`-Items auf `PENDING`; terminale
Items bleiben unverändert. Ein alter Worker scheitert danach bei jedem Write.
Ein kontrollierter Abbruch setzt einen versiegelten Run auf `INTERRUPTED` und
gibt die Lease frei; ein noch nicht versiegelter Run bleibt `PLANNING`, aber
ungeleast. Ein harter Abbruch bleibt nach Lease-Ablauf resumierbar.

Ein planversiegelter Run mit offenen Items wird am Ende einer durch
`--max-items` begrenzten Invocation `INTERRUPTED`. Sind keine offenen Items
mehr vorhanden, wird er `COMPLETED` oder bei mindestens einem `FAILED`/`ERROR`
`COMPLETED_WITH_FAILURES`. Jeder terminale Run besitzt keine Leasefelder.

### Begrenzte Ausführung

Die gespeicherte Workerzahl liegt zwischen 1 und 2 und kann beim Resume nicht
geändert werden. Eine Invocation beansprucht höchstens das Zweifache der
Workerzahl und höchstens den expliziten positiven `--max-items`-Bound.

Für jeden erfolgreichen Claim-Versuch eines Items geschieht in dieser
Reihenfolge:

1. Revalidierung der persistierten Sourcegruppe gegen Root, Scan, Presence,
   Größe und vollständigen Hash sowie exakte Wiederbeobachtung der gebundenen
   Signature-v2-Projektion aus einem neuen bounded Prefix;
2. Aufbau der bereits freigegebenen Volume-/Provider-Eingaben aus der
   identischen Signature-v2-Projektion;
3. exakter Listing-Reuse-Versuch nach ADR-0052 oder höchstens ein
   Providerlauf dieses Versuches;
4. Persistenz desselben privaten Provider-Handoffs ohne zweiten Toollauf;
5. atomarer, erneut gefenceter Itemabschluss.

Der feste produktive Provider-/Runner-Authoritypfad bleibt unverändert;
EBAR-08 führt keinen injizierbaren öffentlichen Runtime-Bypass ein.
Unterschiedliche Items dürfen nur innerhalb der vorhandenen globalen
Containergrenze parallel laufen. Itemabschlüsse werden serialisiert. Ein
per-Item-Fehler beendet andere Items nicht.

### Reuse und Fehlerpriorität

Nur `find_listing_reuse()` mit exakt kompatibler Source-/Signature-/Provider-/
Runner-/Parser-/Formatlock-/Safety-/Secret-Achse darf einen neuen Toollauf
ersetzen. Der neue Itemabschluss referenziert den vorhandenen immutable
Archive-Graphen und markiert `REUSED`; er kopiert keine Kindzeilen.

Priorität:

1. verlorenes Fence oder fehlgeschlagener Heartbeat beendet die Invocation;
2. kontrollierte Cancellation bleibt resumierbar und erzeugt keinen
   erfundenen terminalen Itemgraphen;
3. erwartete Provider-/Parser-/Toolfehler werden als auditierbarer Graph
   persistiert und als `FAILED` mit festem, path-freiem Code abgeschlossen;
4. unerwartete Adapter-/Vertragsfehler werden `ERROR`;
5. nur vollständig persistierte oder exakt wiederverwendete Graphen werden
   `SUCCEEDED`.

### Path-freier Bericht

`foliotone archive-collection-status --run-id <ID>` öffnet SQLite strikt
read-only, liest genau einen konsistenten DB-Snapshot in einer Transaktion und
ruft weder Provider noch Source Media auf. Die öffentliche Ausgabe enthält
ausschließlich in festgelegter Feld-/Literalreihenfolge:

- Run-ID, Profile, Runstatus und Source-Scan-ID;
- geplante, pending, running, succeeded, failed und error Counts;
- executed/reused Counts;
- aggregierte feste Listing-, Integrity-, Encryption-, Recognition- und
  Storage-Literale;
- Plan-Finding- und Fehlercode-Counts;
- `truncated=false`, da keine Itemliste ausgegeben wird.

Der Bericht gibt keine File-/Item-/Archive-Observation-IDs außer der explizit
angefragten Run-ID aus, keine Pfade, Locator, Hashes, Volume-Namen,
Toolausgabe, Fehlerdetails oder Secrets. Alle Counts werden in bounded SQL-
Aggregationen gelesen. Ein inkonsistenter oder unbekannter persistierter Graph
scheitert mit einem festen generischen Fehler und Exitcode 2.

## EBAR-08-Paketgrenzen

Die Umsetzung bleibt in vier einzeln review- und mergebaren Schritten. Ein
Paket darf ausschließlich die aufgelisteten Dateien ändern oder neu anlegen.

### S-EBAR-08A — Models, Schema und gefenceter Store

```text
src/foliotone/core/archive_collection_models.py
src/foliotone/core/__init__.py
src/foliotone/persistence/archive_collection_schema.py
src/foliotone/persistence/archive_collection.py
src/foliotone/persistence/archive.py
src/foliotone/persistence/schema.py
src/foliotone/persistence/alembic/versions/0020_archive_collection_runs.py
src/foliotone/persistence/scan_root_lease.py
src/foliotone/persistence/__init__.py
tests/integration/test_archive_collection_persistence.py
tests/integration/test_scan_root_write_leases.py
tests/integration/test_database_fixtures.py
tests/integration/test_persistence.py
```

### S-EBAR-08B — Reine Gruppenpartition und restartbare Planung

```text
src/foliotone/archive/signatures.py
src/foliotone/persistence/archive_collection.py
src/foliotone/workflows/archive_collection_plan.py
tests/unit/test_archive_collection_plan.py
tests/unit/test_archive_signatures.py
tests/integration/test_archive_collection_persistence.py
```

### S-EBAR-08C — Bounded Ausführung, Resume und Heartbeat

```text
src/foliotone/persistence/archive_collection.py
src/foliotone/persistence/archive.py
src/foliotone/workflows/archive_collection.py
tests/unit/test_archive_collection.py
tests/integration/test_archive_collection_persistence.py
```

### S-EBAR-08D — Read-only Status und CLI-Abschluss

```text
src/foliotone/persistence/archive_collection.py
src/foliotone/workflows/archive_collection_report.py
src/foliotone/cli/main.py
tests/integration/test_archive_collection_report.py
```

Die beiden zentralen Persistenztests dürfen ausschließlich Head-, Tabellen-
und Indexerwartungen von `0019` auf `0020` aktualisieren. Kein späteres Paket
darf diese beiden Dateien erneut ändern. Keine vorhandene
Archive-Runtime-, Parser-, Provider-, Extraction- oder Schema-0019-Semantik
darf gelockert werden.

Pflichttests umfassen:

- Upgrade `0019 -> 0020`, leere Neuinstallation, idempotente Migration und
  bewachten Downgrade;
- stabilen Single-/Multi-Volume-Plan, fehlende Hashes, Gruppenlücken,
  Kollisionen, Bounds, bounded Batchplanung, Abbruch/Resume vor der
  Planversiegelung, Planhash-Drift und keine Pfadpersistenz;
- aktive Konkurrenz, Heartbeat, verlorenes Fence, stale Takeover und
  Nachweis, dass der alte Worker nichts mehr schreibt;
- Resume ohne Replanning, Retry nur verwaister Items und unveränderte
  terminale Items;
- executed und reused direkte/Wrapper-Fälle mit exakt einer
  Archive-Persistenz und ohne zweiten Toollauf;
- Providerfehler, Cancellation, unerwarteten Fehler und Heartbeatverlust mit
  exakter Statuspriorität;
- bounded Batch/Worker, vollständige Counts sowie read-only, path-/locator-/
  hash-/secret-freie deterministische Reports;
- echte SQLite-Indexpläne und lokale synthetische Daten; breite Tests nur
  einmal im stabilen PR-CI.

## Nicht autorisiert

Diese Entscheidung autorisiert keine Extraction, Passwortprüfung,
Secretübergabe, Source-/Sidecar-/Archive-/Membermutation, Quarantäne,
Metadatenwrites, Archive-aware Matching oder W10-Ausführung. Das negative
Workspace-Backend-Gate und FG-A-SECRET bleiben unverändert. EBAR-09 folgt erst
nach erfolgreicher Abnahme aller vier EBAR-08-Pakete.

## Konsequenzen

- Archive-Collection- und allgemeine E-Book-Collection-Läufe bleiben getrennt
  versioniert und migrierbar.
- Multi-Volume-Gruppen besitzen einen immutable, pfadfreien Plan und können
  nach Prozessverlust ohne Replanning fortgesetzt werden.
- Root-weites Fencing verhindert, dass stale Worker Evidence oder Status
  nachträglich überschreiben.
- Ein privater Collection-Status ist reproduzierbar, bounded und öffnet keine
  Source Media.
