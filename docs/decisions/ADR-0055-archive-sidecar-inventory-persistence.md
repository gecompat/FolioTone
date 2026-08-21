# ADR-0055: Archive-Sidecar-Inventar und Statusgrenze

- Status: Accepted
- Datum: 2026-08-21

## Kontext

Der historische Backlogpunkt W3-019 verlangt ein begrenztes, inkrementelles
Inventar für Archive, Volumes und Sidecars sowie eine pfadfreie
Statusprojektion. Seit seiner Formulierung wurden die Zuständigkeiten weiter
getrennt:

- ADR-0052 und Migration `0019_archive_evidence` persistieren Archive-,
  Source-/Volume-, Execution-, Member- und Wrapper-Lineage insert-only;
- ADR-0053 und Migration `0020_archive_collection_runs` persistieren die
  restartbare Collection-Orchestrierung und deren pfadfreien Status;
- `archive-sidecar-classifier/v1` klassifiziert höchstens 32 bereits
  indexierte direkte Nachbardateien rein und ohne Inhaltszugriff;
- ADR-0039 und ADR-0043 verbieten, freie 7-Zip-Prosa oder grobe Exitcodes als
  Authority für `CORRUPT`, `UNSUPPORTED_METHOD` oder Passwortursachen zu
  verwenden.

Damit sind Archive-/Volume-Inventar, Missing-Volume-Findings, Encryption-
Status und Collection-Bericht bereits umgesetzt. Es fehlt ausschließlich die
persistente, scan- und archivegebundene Sidecar-Inventar-Evidence. Die alten
Ursachenliterale bleiben als Legacy-/DTO-Domain erhalten, dürfen im realen
Provider aber nur aus einer später separat festgelegten strukturierten
Evidence stammen.

## Entscheidung

W3-019 wird in einen abgeschlossenen Bestand und genau ein mechanisches
Folgepaket geteilt. `S-EBAR-07A` ergänzt einen additiven, insert-only
Sidecar-Inventarsnapshot mit geordneten Kindzeilen und bounded Store-Query. Es verändert weder
Archive-Toolausführung noch Collection-Planung oder öffentliche CLI-Profile.

### Persistiertes Profil

Das Profil heißt exakt:

```text
archive-sidecar-inventory/v1
```

Ein Elternsnapshot bezeichnet das vollständige Ergebnis für genau einen
persistierten `ArchiveObservation` und enthält:

```text
id
profile
content_hash
archive_observation_id
archive_file_observation_id
scan_root_id
source_scan_run_id
sidecar_count
created_at
```

Jede geordnete Kindzeile enthält ausschließlich:

```text
inventory_id
sidecar_ordinal
sidecar_file_observation_id
sidecar_kind
```

Nicht gespeichert werden Basename, relativer oder absoluter Pfad,
Dateiinhalt, Textvorschau, Secret Candidate, Hash des Sidecar-Inhalts oder
Toolausgabe. Die bestehende private `file_observations.relative_path`-Spalte
wird ausschließlich innerhalb der Store-Revalidierung gelesen und nie in das
neue DTO, einen Fehler oder Bericht projiziert.

### Exakte Bindung

Ein Sidecar-Snapshot ist nur gültig, wenn alle folgenden Aussagen gemeinsam
gelten:

1. Der `ArchiveObservation`-Graph existiert, ist materiell valide und gehört
   exakt zu `scan_root_id` und `source_scan_run_id`.
2. `archive_file_observation_id` ist eine Sourcezeile dieses Graphen und
   bezeichnet die kanonische primäre Source mit `source_ordinal=0`.
3. Archive- und Sidecar-`FileObservation` existieren im selben abgeschlossenen
   `ScanRun`, gehören zum selben `ScanRoot` und sind verschieden.
4. Beide gespeicherten relativen Pfade sind kanonisch, und ihre unmittelbaren
   Eltern sind exakt gleich. Rekursion oder ein nur gleichnamiges Verzeichnis
   genügt nicht.
5. Der Sidecar-Basename wird erneut mit
   `archive-sidecar-classifier/v1` klassifiziert; das Ergebnis muss exakt dem
   gespeicherten `sidecar_kind` entsprechen.
6. Der Snapshot enthält vollständig 0 bis 32 eindeutige
   Sidecar-FileObservations. Die Kindzeilen sind lückenlos ab Ordinal 0 und
   kanonisch nach `sidecar_kind`, `sidecar_file_observation_id` sortiert.

Der Writer nimmt keine vom Caller behauptete Sidecar-Liste, keinen Basename
und keinen Pfad entgegen. `create_or_get_sidecar_inventory()` erhält genau die
opaque `archive_observation_id`, eine passende `OwnedScanRootWriteLease` und
einen timezone-aware Commitzeitpunkt. Er leitet die kanonische
vollständige Kandidatenmenge selbst aus den aktuellen `FileObservation`-Zeilen
desselben abgeschlossenen Scans und unmittelbaren Verzeichnisses ab, liest
höchstens 33 klassifizierbare direkte Nachbarn und klassifiziert sie erneut.
Damit sind auch ein leerer Snapshot und die Abwesenheit eines 33. zulässigen
Sidecars materiell belegt; eine vom Caller gekürzte Teilmenge ist unmöglich.

Der Store prüft und fencet die bestehende Root-Lease innerhalb derselben
Transaktion vor der Ableitung, unmittelbar vor einem Insert und erneut vor
jeder erfolgreichen Rückgabe. Er akzeptiert ausschließlich die bereits für
Archive-Evidence erlaubten Owner-Klassen. Eine fremde, abgelaufene oder
überholte Lease scheitert pfadfrei; es gibt keinen unfenced Write-Pfad.

Ein Sidecar kann mehreren im selben Verzeichnis liegenden Archiven zugeordnet
sein. Diese Beziehungen sind getrennte Evidence und werden nicht geraten oder
zusammengeführt.

### Identität und Wiederholung

`content_hash` verwendet `canonical-json/v1` mit eigener Domain-Separation,
dem vollständigen Elternmaterial und allen geordneten Kindzeilen außer `id`
und `created_at`. Pfade und Sidecar-Inhalte sind ausgeschlossen.

Lease-Token, Owner-Run und Fence-Epoch gehören nicht in den materiellen Hash.
Sie autorisieren den konkreten Insert, dürfen aber eine spätere exakte
Wiederholung unter einer neuen gültigen Lease nicht in anderes Inventarmaterial
verwandeln.

Die ID ist UUIDv5 im festen Namespace
`40d517c3-c650-5760-8b8b-6e8e6665989b` über die kleingeschriebene
64-Hex-Repräsentation des materiellen `content_hash`.
Exakte Wiederholung liefert den vorhandenen Snapshot. Gleiche ID mit anderem
Material, fremde Root-/Scan-Lineage, geänderte Klassifikation, mehr als 32
Kindzeilen oder nichtkanonische Reihenfolge scheitern fail-closed. Es gibt keinen
Update-/Delete-/generischen `save()`-Pfad.

### Schema und Query

Die additive Migration heißt `0021_archive_sidecar_inventory`, folgt exakt
auf `0020_archive_collection_runs` und legt diese beiden Tabellen an:

```text
archive_sidecar_inventories
archive_sidecar_inventory_items
```

Erforderlich sind:

- Foreign Keys auf ArchiveObservation, beide FileObservations, ScanRoot und
  ScanRun;
- Unique Constraints für `archive_observation_id`, `content_hash`, die
  lückenlose `(inventory_id, sidecar_ordinal)`-Ordnung sowie
  `(inventory_id, sidecar_file_observation_id)`;
- Checks für Profil, Content Hash, `sidecar_count` von 0 bis 32, Ordinal und
  die feste Sidecar-Kind-Allowlist;
- ein Kindindex auf `(inventory_id, sidecar_kind,
  sidecar_file_observation_id)`;
- den für die bounded Ableitung nötigen Index
  `ix_file_observations_run_path` auf der bestehenden Tabelle
  `(scan_run_id, relative_path)`.

Der Store liest für genau eine explizite `archive_observation_id` höchstens
einen Elternsnapshot sowie 33 Kindzeilen (`limit + 1`). Mehr als 32 Kindzeilen,
fremde oder korrupte Lineage und
unbekannte Literale scheitern mit einem festen pfadfreien Fehler. Es gibt
keine unbounded `list_all()`-, Offset- oder Root-weite Sidecar-Abfrage.
Der Integrationstest weist mit `EXPLAIN QUERY PLAN` nach, dass die
Direktnachbar-Ableitung den neuen Run-/Path-Index verwendet. SQL grenzt zuerst
den kanonischen Verzeichnispräfix und den direkten Kindpfad ein; nur die feste
Sidecar-Suffix-/Basename-Allowlist darf die 33er-Auswahl erreichen.

### Status- und Berichtgrenze

Der bestehende `archive-collection-report/v1` bleibt unverändert. Er berichtet
bereits Collection-, Listing-, Integrity-, Encryption- und Plan-Finding-
Counts. W3-019 autorisiert keine Änderung dieses öffentlichen Profils.

`MISSING_VOLUME` bleibt ein strukturierter Signature-/Volume-Planbefund.
`CORRUPT`, `UNSUPPORTED_METHOD`, `PASSWORD_REQUIRED` und vergleichbare
Ursachen dürfen vom realen 7-Zip-Provider weiterhin nicht aus stdout, stderr
oder Exitcode geraten werden. Ohne eigene strukturierte Evidence lautet der
reale Terminalstatus `TOOL_FAILED`; das Sidecar-Inventar ändert daran nichts.

## Arbeitspaket

`S-EBAR-07A` darf ausschließlich ändern:

- neue Migration `0021_archive_sidecar_inventory`;
- `src/foliotone/persistence/archive_schema.py`;
- `src/foliotone/persistence/archive.py`;
- unmittelbar betroffene Schema-Head-/Tabellen-/Index-Erwartungstests;
- eine neue fokussierte Integrationstestdatei für Sidecar-Persistenz.

Abnahme:

- leere Migration und Upgrade `0020 -> 0021` sind grün;
- ein vollständiger Snapshot mit null Sidecars roundtrippt und belegt das
  leere Klassifikationsergebnis ohne erfundene Kindzeile;
- exakt gebundene NFO/TXT/DIZ/INFO/URL/HTML/SFV/README/PASSWORD-Fälle
  roundtrippen insert-only;
- exakte Wiederholung ist idempotent;
- fremde, abgelaufene und stale gefencete Root-Leases schreiben nichts;
- fremder Root/Run, nicht abgeschlossener Scan, Nicht-Nachbar, Rekursion,
  Archive-Self-Link, falsche Klasse, 33. Sidecar und materielle Kollision
  scheitern fail-closed;
- Query nutzt den festgelegten Index und bleibt auf 32 begrenzt;
- DTOs, Exceptions und Testausgaben enthalten keine Pfade, Basenames,
  Inhalte, Hashwerte der Sidecar-Datei oder Secrets;
- Ruff, Mypy, `git diff --check` und nur die fokussierten Tests sind lokal
  grün; der vollständige Gate läuft einmal im Pull Request.

## Nicht autorisiert

Diese Entscheidung autorisiert keine Dateiöffnung, Sidecar-Inhaltsanalyse,
Secret-Erzeugung, Passwortprüfung, Archive-Extraction, Member-Byte-Identity,
Source-/Sidecar-Mutation, neue öffentliche CLI-Felder, Calibre-Schreibzugriffe
oder W10-Operation.

## Folgen

Nach `S-EBAR-07A` ist W3-019 abgeschlossen. FG-A3-MEMBER-BYTE,
FG-A-SECRET, S-EBAR-04A, EBAR-06 und W10 bleiben unverändert blockiert.
