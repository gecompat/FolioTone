# Projektstatus

Stand: 2026-08-09

## Aktuelle Welle

**W2 — Incremental Index + Filename/Path Context + Tool Runtime**

W0 und W1 sind abgeschlossen. Der grundlegende W2-Index-/ToolRuntime-Slice wurde in GitHub Actions und zusätzlich lokal unter Windows/Docker Desktop geprüft. `W2-004` ergänzt eine konservative, standardmäßig deaktivierte `DELETED`-Bestätigung. `W2-006` ergänzt persistente Move-/Rename-Kandidaten, ohne `FileRecord`-Identitäten zusammenzuführen. Als nächster W2-Punkt folgt `W2-007`, die Vervollständigung des Interrupt/Resume-Verhaltens.

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
- persistente `FileRelocationCandidate`-Records für konservative Move-/Rename-Kandidaten.

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

Die W1-Persistence wurde bisher über drei zusätzliche Alembic-Revisionen erweitert. Bereits gemergte Migrationen werden nicht rückwirkend verändert.

`0002_incremental_index` ergänzt insbesondere:

- `file_scan_events`;
- `tool_artifacts`;
- Scan-/Tool-relevante Indizes;
- eindeutige logische `ScanRoot.name`-Werte.

`0003_deletion_confirmation` ergänzt `file_records` um:

- `missing_since_at`;
- `consecutive_missing_scans`.

`0004_relocation_candidates` ergänzt:

- `file_relocation_candidates`;
- eindeutige Source-/Target-Paare pro `ScanRun`;
- Indizes für Run- und Source-/Target-Abfragen.

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

Der finale PR-#5-Head `ef10290da1ed3522e5a261ccb33d5561e32eb497` wurde in GitHub Actions Run `31282820586` vollständig geprüft und anschließend als Merge-Commit `4362d60eca51c3e896ae3a6e4fb4485e644bbc4d` nach `main` übernommen:

```text
Install                              PASS
Ruff                                 PASS
Mypy                                 PASS
Pytest                               PASS (44 Tests)
Prepare Docker mount placeholders    PASS
Docker build                         PASS
Docker migration smoke test          PASS
Docker persistent data write test    PASS
Docker incremental scan smoke test   PASS
Docker bootstrap/status              PASS
```

### `W2-004` — automatisierte Verifikation

Der Implementierungs-Head `556055eb7848f3f682f0bd2363ba2dc98fceb7e5` von PR #7 wurde in GitHub Actions Run `31285157432` erfolgreich geprüft:

```text
Install                              PASS
Ruff                                 PASS
Mypy                                 PASS (49 source files)
Pytest                               PASS (48 Tests)
Prepare Docker mount placeholders    PASS
Docker build                         PASS
Docker migration smoke test          PASS
Docker persistent data write test    PASS
Docker incremental scan smoke test   PASS
Docker bootstrap/status              PASS
```

### `W2-006` — automatisierte Verifikation

Der Implementierungs-Head `c946dd336593b68ed281c530ab40117562d17831` von PR #8 wurde in GitHub Actions Run `31285662119` erfolgreich geprüft:

```text
Install                              PASS
Ruff                                 PASS
Mypy                                 PASS (52 source files)
Pytest                               PASS (52 Tests)
Prepare Docker mount placeholders    PASS
Docker build                         PASS
Docker migration smoke test          PASS
Docker persistent data write test    PASS
Docker incremental scan smoke test   PASS
Docker bootstrap/status              PASS
```

Die neuen Integrationstests bestätigen Rename-, Move- und kombinierte Move-/Rename-Kandidaten, die Unterdrückung mehrdeutiger identischer Fingerprint-Blöcke sowie die Bevorzugung von `FILE_SHA256` gegenüber `QUICK_FILE` für dasselbe eindeutige Paar.

### Lokale Windows-/Docker-Verifikation

`W2-012` wurde am 2026-08-09 mit ausschließlich synthetischen Testdateien lokal ausgeführt. Verwendet wurden Docker Engine `29.6.2` und Docker Compose `v5.3.1`.

**Empirisch bestätigt wurden:**

- `docker compose build` erfolgreich;
- `foliotone status` erfolgreich;
- `/data` ist aus dem Container beschreibbar und über getrennte Containerläufe persistent;
- `/media/ebooks` ist read-only; ein absichtlicher Schreibversuch scheiterte mit `Read-only file system` und Non-zero Exit;
- erster Scan: `NEW: 2`;
- unveränderter Folgescan: `UNCHANGED: 2`;
- nach Änderung einer Datei und Entfernen einer zweiten: `MODIFIED: 1 / MISSING: 1`;
- nach Wiederanlegen der fehlenden Datei: `UNCHANGED: 1 / REAPPEARED: 1`;
- ein nicht vorhandener Scan-Pfad beendet den Scan mit Fehler und Non-zero Exit;
- der unmittelbar folgende gültige Scan meldete wieder `UNCHANGED: 2` und erzeugte damit keine falsche `MISSING`-Evidenz.

Die lokale Verifikation bestätigt den grundlegenden W2-Vertrag für den geprüften Windows-/Docker-Desktop-Pfad. Die später implementierten `DELETED`- und Relocation-Funktionen sind durch automatisierte Integrationstests abgedeckt und wurden in diesem lokalen Test nicht separat nachgestellt.

Die Source-Media-Verzeichnisse bleiben im Compose-Vertrag read-only. `/data` ist als persistenter Runtime-Bereich explizit read-write eingebunden.

## Noch offen in W2

Als nächste fachliche W2-Arbeiten bleiben:

1. `W2-007` — Interrupt/Resume-Verhalten vervollständigen; der unavailable-root Fall ist bereits implementiert und lokal bestätigt;
2. `W2-008` — versionierten `FilenameParser` und `PathContextAnalyzer` implementieren;
3. `W2-009` — Parsing-Regeln und Fixtures für Autor/Titel, Serie/Band, Track/Disc, Jahr und Sprache ergänzen;
4. `W2-011` — ToolProvider-Runtime um noch fehlende Tests für malformed structured output, Version Change und selective re-analysis erweitern.

## Nicht implementiert

Noch nicht vorhanden sind unter anderem:

- explizite Scan-Resume-Lineage und Resume-CLI;
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

`FileRelocationCandidate` ist ausschließlich Analyse-Evidence. W9 darf später ausschließlich nicht ausführbare `ConsolidationPlan`-Einträge erzeugen.
