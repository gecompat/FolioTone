# Projektstatus

Stand: 2026-08-09

## Aktuelle Welle

**W2 — Incremental Index + Filename/Path Context + Tool Runtime**

W0 und W1 sind abgeschlossen. Der grundlegende W2-Index-/ToolRuntime-Slice wurde in GitHub Actions und zusätzlich lokal unter Windows/Docker Desktop geprüft. `W2-004` ergänzt eine konservative, standardmäßig deaktivierte `DELETED`-Bestätigung. `W2-006` ergänzt persistente Move-/Rename-Kandidaten, ohne `FileRecord`-Identitäten zusammenzuführen. `W2-007` ergänzt eine explizite Resume-Lineage für unterbrochene Scans. Als nächster W2-Punkt folgt `W2-008`, der versionierte `FilenameParser` und `PathContextAnalyzer`.

## Implementierter W2-Slice

### Incremental Index

Implementiert sind:

- persistente logische `ScanRoot`-Identitäten mit eindeutigem Namen;
- `ScanRun`-Lifecycle mit `RUNNING`, `COMPLETED`, `FAILED` und `INTERRUPTED`;
- streaming-basierte Filesystem Discovery über `os.scandir` ohne collection-weite Pfadliste im Speicher;
- `FileRecord`, `FileObservation` und auditierbare `FileScanEvent`-Einträge;
- Zustände `NEW`, `UNCHANGED`, `MODIFIED`, `MISSING`, `REAPPEARED` und opt-in `DELETED`;
- Schutz vor falschem `MISSING`, wenn ein `ScanRoot` nicht verfügbar ist;
- `MISSING` bleibt ausdrücklich von `DELETED` getrennt;
- begrenzte Batch-Verarbeitung mit maximal 500 Dateien je Batch;
- read-only Scan-CLI `foliotone scan` für kontrollierte Smoke-Tests;
- persistente `FileRelocationCandidate`-Records für konservative Move-/Rename-Kandidaten;
- explizite Resume-Lineage über `ScanRun.resumed_from_run_id` und CLI `--resume-run`.

`MOVED` und `RENAMED` bleiben als `FileChangeState`-Vokabular reserviert. W2-006 emittiert diese Werte nicht als bestätigte Scan-Zustände, sondern speichert getrennte Relocation-Kandidaten.

### `DELETED`-Bestätigung

`W2-004` implementiert `DeletionConfirmationPolicy` als konservative, ausdrücklich zu aktivierende Policy. Eine Datei wird nur dann als `DELETED` klassifiziert, wenn gleichzeitig:

1. eine konfigurierte Mindestanzahl aufeinanderfolgender erfolgreicher Scans die Datei als `MISSING` bestätigt hat; die Policy akzeptiert mindestens 2 Scans;
2. eine konfigurierte Mindestdauer seit Beginn dieser aktuellen Abwesenheitsserie verstrichen ist.

Die Policy besitzt bei expliziter Konstruktion die Defaultwerte drei erfolgreiche `MISSING`-Scans und 24 Stunden. Die CLI aktiviert die Bestätigung jedoch nicht automatisch. Dafür stehen die Optionen `--confirm-deleted-after-missing-scans` und optional `--confirm-deleted-after-hours` zur Verfügung.

`FileRecord.missing_since_at` und `FileRecord.consecutive_missing_scans` halten den aktuellen Abwesenheitszustand persistent. Failed oder interrupted Scans erhöhen die Serie nicht. Nach bestätigtem `DELETED` wird bei fortbestehender Abwesenheit nicht in jedem Scan erneut ein `DELETED`-Event erzeugt. Taucht derselbe relative Pfad später wieder auf, entsteht `REAPPEARED`, der Zustand wird auf `PRESENT` zurückgesetzt und die Abwesenheitsserie gelöscht.

`DELETED` ist ausschließlich eine Indexklassifikation. Die Funktion löscht, verschiebt, benennt oder verändert keine Source-Media-Datei. ADR-0013 dokumentiert diese Entscheidung verbindlich.

### Move-/Rename-Kandidaten

`W2-006` implementiert `FileRelocationCandidate` als zusätzliche, nicht kanonische Evidence. Ein Kandidat entsteht nur zwischen zwei weiterhin getrennten `FileRecord`-Datensätzen desselben `ScanRoot`, wenn im selben erfolgreichen Scan:

- die Source erstmals `MISSING` wird (`consecutive_missing_scans == 1`);
- das Target `NEW` ist;
- die letzte prior Source-Observation und die aktuelle Target-Observation denselben unterstützten versionierten File-Fingerprint besitzen;
- der jeweilige Fingerprint-Block genau eine Source und genau ein Target enthält.

Unterstützt werden zunächst `QUICK_FILE` und `FILE_SHA256`. Wenn beide dasselbe eindeutige Paar stützen, wird `FILE_SHA256` als stärkere technische Evidence im Kandidaten referenziert. Der Kandidat verweist auf die konkreten Source-/Target-`Fingerprint`-IDs sowie Algorithmus und Version.

One-to-many-, many-to-one- und many-to-many-Blöcke werden nicht automatisch aufgelöst. Ebenso werden ältere `MISSING`-Records nicht rückwirkend mit später auftauchenden Dateien verknüpft. Das verhindert willkürliche Zuordnungen bei echten identischen Kopien.

`RelocationCandidateKind` beschreibt nur die Pfadform:

- `RENAMED`: gleicher Parent-Pfad, anderer Dateiname;
- `MOVED`: anderer Parent-Pfad, gleicher Dateiname;
- `MOVED_AND_RENAMED`: Parent-Pfad und Dateiname verändert.

Source bleibt `MISSING`, Target bleibt `NEW`; es findet weder ein Identity Merge noch eine Source-Media-Operation statt. ADR-0014 dokumentiert diese Entscheidung verbindlich.

### Interrupt/Resume

`W2-007` modelliert ein Resume als neuen `ScanRun` mit `resumed_from_run_id`. Ein Run kann nur dann als Resume-Quelle verwendet werden, wenn er persistent existiert, Status `INTERRUPTED` besitzt und zum selben `ScanRoot` gehört. `COMPLETED`, `FAILED`, `RUNNING` oder fremde Roots werden abgelehnt.

Resume öffnet den unterbrochenen Run nicht erneut. Der neue Run führt die streaming-basierte Discovery erneut vollständig aus. Das vermeidet einen nicht portablen persistenten `os.scandir`-Cursor. Bereits vor dem Interrupt verarbeitete unveränderte Dateien liegen jedoch als `FileRecord` und Fingerprint persistent vor; beim Resume werden sie als `UNCHANGED` erkannt und deshalb nicht erneut gehasht. Noch nicht erreichte Dateien werden normal verarbeitet.

Die `MISSING`-/`DELETED`-Phase läuft weiterhin erst nach erfolgreicher vollständiger Discovery. Ein unterbrochener Run kann dadurch weder nicht erreichte Dateien als `MISSING` markieren noch eine Deletion-Bestätigungsserie erhöhen. Die CLI verwendet `--resume-run <ScanRunId>`. ADR-0015 dokumentiert diese Entscheidung verbindlich.

### Hashing

Implementiert sind:

- gestuftes `HashMode.NONE`, `QUICK` und `FULL`;
- Quick Fingerprint über Dateigröße sowie begrenzte Head-/Tail-Bereiche;
- vollständiges SHA-256 als Streaming-Hash mit begrenztem Speicherverbrauch;
- Fingerprints werden gegen die konkrete `FileObservation` gespeichert;
- unveränderte Dateien werden nicht unnötig erneut gehasht;
- NEW, MODIFIED und REAPPEARED können neu fingerprinted werden.

### Generische ToolProvider Runtime

Implementiert sind:

- lokale Tool-Ausführung ohne Shell;
- Tool-Versionsermittlung;
- Timeouts und Cancellation;
- auditierbare FAILED-Ausführung bei fehlendem Tool oder Non-zero Exit;
- file-backed stdout/stderr mit `ToolArtifact`, Größe und SHA-256;
- begrenzte stdout/stderr Previews;
- Ablehnung absoluter lokaler Pfade als persistierte `ToolExecution.input_identity`;
- gehärtete Docker-Argumente für ToolProvider mit read-only Container-Dateisystem, `cap-drop=ALL`, `no-new-privileges` und standardmäßig deaktiviertem Netzwerk;
- ausschließlich read-only Input-Mounts und separatem beschreibbarem Work-Verzeichnis.

Konkrete calibre-, ffprobe-, fpcalc-, beets-, SongKong- oder Picard-Adapter sind noch nicht implementiert.

### Persistence

Die W1-Persistence wurde bisher über vier zusätzliche Alembic-Revisionen erweitert. Bereits gemergte Migrationen werden nicht rückwirkend verändert.

`0002_incremental_index` ergänzt insbesondere `file_scan_events`, `tool_artifacts`, Scan-/Tool-relevante Indizes und eindeutige logische `ScanRoot.name`-Werte.

`0003_deletion_confirmation` ergänzt `file_records` um `missing_since_at` und `consecutive_missing_scans`.

`0004_relocation_candidates` ergänzt `file_relocation_candidates` sowie Indizes für Run- und Source-/Target-Abfragen.

`0005_scan_resume_lineage` ergänzt `scan_runs.resumed_from_run_id` als nullable selbstreferenzierende Foreign-Key-Lineage sowie einen Query-Index.

Beim Upgrade einer bestehenden `0002`-Datenbank wird keine historische Abwesenheitsdauer oder Bestätigungsserie erfunden. Bestehende Datensätze beginnen konservativ mit `missing_since_at = NULL` und `consecutive_missing_scans = 0`; erst nachfolgende erfolgreiche Scans bauen neue Bestätigungsevidenz auf.

## Lizenz und Dokumentations-Governance

Die Lizenz- und Dokumentationsentscheidungen bleiben unverändert:

- `LICENSE.md` verwendet die vom Benutzer vorgegebene Custom Community & Attribution License nach dem Vorbild von `SQL_Server_Analyze`;
- FolioTone ist ausdrücklich **nicht Open Source**;
- die englische Lizenzfassung ist entsprechend `LICENSE.md` rechtlich maßgeblich;
- der zweisprachige Lizenzblock am Anfang der Root-README ist geschützter Inhalt;
- `docs/quality/DOCUMENTATION_STYLE.md` und `docs/quality/LANGUAGE_AND_TERMINOLOGY.md` sind verbindlich;
- `docs/reference/GLOSSARY.md` ist die kanonische Terminologiequelle;
- `tests/static/test_documentation_contracts.py` prüft konservativ bekannte Dokumentationsregressionen.

## Verifikation

### Grundlegender W2-Slice

Der finale PR-#5-Head `ef10290da1ed3522e5a261ccb33d5561e32eb497` wurde in GitHub Actions Run `31282820586` vollständig geprüft und anschließend als Merge-Commit `4362d60eca51c3e896ae3a6e4fb4485e644bbc4d` nach `main` übernommen. Install, Ruff, Mypy, 44 Pytest-Tests sowie Docker-Build, Migration, persistentes `/data`, Incremental Scan und Bootstrap waren erfolgreich.

### `W2-004` — automatisierte Verifikation

Der Implementierungs-Head `556055eb7848f3f682f0bd2363ba2dc98fceb7e5` von PR #7 wurde in GitHub Actions Run `31285157432` erfolgreich geprüft. Install, Ruff, Mypy, 48 Pytest-Tests und sämtliche Docker-Smoke-Schritte waren erfolgreich.

### `W2-006` — automatisierte Verifikation

Der Implementierungs-Head `c946dd336593b68ed281c530ab40117562d17831` von PR #8 wurde in GitHub Actions Run `31285662119` erfolgreich geprüft. Install, Ruff, Mypy, 52 Pytest-Tests und sämtliche Docker-Smoke-Schritte waren erfolgreich.

### `W2-007` — automatisierte Verifikation

Der Implementierungs-Head `8bfa20fb692727f03f8f0cd40b64385328e75d30` von PR #9 wurde in GitHub Actions Run `31286181807` erfolgreich geprüft. Install, Ruff, Mypy, Pytest sowie Docker-Build, Migration, persistentes `/data`, Incremental Scan und Bootstrap waren erfolgreich.

Die Resume-Integrationstests bestätigen insbesondere:

- partielle Arbeit und Fingerprints bleiben nach `INTERRUPTED` persistent;
- ein Resume erhält eine neue `ScanRun`-ID und die korrekte `resumed_from_run_id`;
- bereits verarbeitete unveränderte Dateien werden beim Resume nicht erneut gehasht;
- ein unterbrochener Scan erzeugt keine falsche `MISSING`-Evidenz für nicht erreichte bekannte Dateien;
- nur persistierte `INTERRUPTED`-Runs desselben `ScanRoot` sind resumierbar;
- Migration `0005` stellt Lineage-Spalte und Index bereit.

### Lokale Windows-/Docker-Verifikation

`W2-012` wurde am 2026-08-09 mit ausschließlich synthetischen Testdateien lokal ausgeführt. Verwendet wurden Docker Engine `29.6.2` und Docker Compose `v5.3.1`.

Empirisch bestätigt wurden Docker-Build und Bootstrap, persistentes beschreibbares `/data`, read-only `/media/ebooks`, die Zustandsfolge NEW/UNCHANGED/MODIFIED/MISSING/REAPPEARED sowie unavailable-root Schutz gegen falsche `MISSING`-Evidenz.

Die später implementierten `DELETED`-, Relocation- und Resume-Funktionen sind durch automatisierte Integrationstests abgedeckt und wurden in diesem lokalen Plattformtest nicht separat nachgestellt.

## Noch offen in W2

Als nächste fachliche W2-Arbeiten bleiben:

1. `W2-008` — versionierten `FilenameParser` und `PathContextAnalyzer` implementieren;
2. `W2-009` — Parsing-Regeln und Fixtures für Autor/Titel, Serie/Band, Track/Disc, Jahr und Sprache ergänzen;
3. `W2-011` — ToolProvider-Runtime um noch fehlende Tests für malformed structured output, Version Change und selective re-analysis erweitern.

## Nicht implementiert

Noch nicht vorhanden sind unter anderem:

- Filename-/Path-Parsing;
- konkrete E-Book- und Music-ToolProvider;
- calibre Library Reconciliation;
- Entity Resolution Engine;
- externe Knowledge Provider und Provider Cache;
- Classification Engine;
- Matching Engine;
- Review System;
- Consolidation Planning und Execution.

## Sicherheitsgrenze

W10 bleibt ausdrücklich blockiert. Es gibt keine FolioTone-native oder externe Tool-Operation zum Löschen, Verschieben, Umbenennen oder Retaggen von Source Media.

`DELETED`, `FileRelocationCandidate` und Scan-Resume sind ausschließlich Analyse-/Orchestrierungszustände. W9 darf später ausschließlich nicht ausführbare `ConsolidationPlan`-Einträge erzeugen.
