# Projektstatus

Stand: 2026-08-09

## Aktuelle Welle

**W2 — Incremental Index + Filename/Path Context + Tool Runtime**

W0 und W1 sind abgeschlossen. Der erste konsistente W2-Slice ist implementiert, in GitHub Actions vollständig verifiziert und zusätzlich lokal unter Windows/Docker Desktop geprüft. Die zuvor gesetzte lokale Verifikationssperre ist damit aufgehoben. Als nächster W2-Punkt folgt `W2-004`, die robuste `DELETED`-Bestätigung.

## Implementierter W2-Slice

### Incremental Index

Implementiert sind:

- persistente logische `ScanRoot`-Identitäten mit eindeutigem Namen;
- `ScanRun`-Lifecycle mit `RUNNING`, `COMPLETED`, `FAILED` und `INTERRUPTED`;
- streaming-basierte Filesystem Discovery über `os.scandir` ohne collection-weite Pfadliste im Speicher;
- `FileRecord`, `FileObservation` und auditierbare `FileScanEvent`-Einträge;
- Zustände `NEW`, `UNCHANGED`, `MODIFIED`, `MISSING` und `REAPPEARED`;
- Schutz vor falschem `MISSING`, wenn ein ScanRoot nicht verfügbar ist;
- `MISSING` bleibt ausdrücklich von `DELETED` getrennt;
- begrenzte Batch-Verarbeitung mit maximal 500 Dateien je Batch;
- read-only Scan-CLI `foliotone scan` für kontrollierte Smoke-Tests.

`DELETED`, `MOVED` und `RENAMED` sind bereits als Vokabular vorgesehen, werden aber noch nicht automatisch festgestellt.

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

Die bestehende W1-Persistence wurde über die neue Alembic-Revision `0002_incremental_index` erweitert. Die bereits gemergte Migration `0001_initial` wurde nicht verändert.

`0002_incremental_index` ergänzt insbesondere:

- `file_scan_events`;
- `tool_artifacts`;
- Scan-/Tool-relevante Indizes;
- eindeutige logische `ScanRoot.name`-Werte.

## Lizenz und Dokumentations-Governance

Die zuvor offene Lizenzentscheidung ist abgeschlossen:

- `LICENSE.md` verwendet die vom Benutzer vorgegebene Custom Community & Attribution License nach dem Vorbild von `SQL_Server_Analyze`;
- FolioTone ist ausdrücklich **nicht Open Source**;
- die englische Lizenzfassung ist entsprechend `LICENSE.md` rechtlich maßgeblich;
- der zweisprachige Lizenzblock am Anfang der Root-README ist geschützter Inhalt.

Aus `SQL_Server_Analyze` wurde das Governance-Muster für Dokumentation adaptiert:

- `docs/quality/DOCUMENTATION_STYLE.md` ist die verbindliche Schreibstilrichtlinie;
- `docs/quality/LANGUAGE_AND_TERMINOLOGY.md` definiert Deutsch als kanonische erklärende Dokumentationssprache und schützt technische Literale;
- `docs/reference/GLOSSARY.md` ist die kanonische Terminologiequelle;
- `docs/README.md` bietet eine aufgabenorientierte Dokumentationsnavigation;
- `.github/copilot-instructions.md` verweist auf dieselben Regeln;
- `tests/static/test_documentation_contracts.py` prüft konservativ bekannte Regressionen, insbesondere den geschützten README-Lizenzblock und alte Projektnamen.

Die automatische Prüfung ersetzt kein fachliches oder sprachliches Review.

## Verifikation

### GitHub Actions

Der finale PR-Head `ef10290da1ed3522e5a261ccb33d5561e32eb497` wurde in GitHub Actions Run `31282820586` vollständig geprüft und anschließend als Merge-Commit `4362d60eca51c3e896ae3a6e4fb4485e644bbc4d` nach `main` übernommen:

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

Der Docker Incremental Scan Smoke Test führt vier getrennte Containerläufe gegen dieselbe persistente SQLite-Datenbank aus und bestätigt:

```text
1. NEW: 2
2. UNCHANGED: 2
3. MODIFIED: 1 / MISSING: 1
4. UNCHANGED: 1 / REAPPEARED: 1
```

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

Die lokale Verifikation bestätigt den dokumentierten W2-Vertrag für den geprüften Windows-/Docker-Desktop-Pfad. Sie ist kein Test gegen eine reale Mediensammlung und keine Aussage über noch nicht implementierte `DELETED`-, Move-/Rename- oder Parsing-Funktionalität.

Die Source-Media-Verzeichnisse bleiben im Compose-Vertrag read-only. `/data` ist als persistenter Runtime-Bereich explizit read-write eingebunden.

## Noch offen in W2

Als nächste fachliche W2-Arbeiten bleiben:

1. `W2-004` — robuste `DELETED`-Bestätigung definieren und implementieren;
2. `W2-006` — Move-/Rename-Kandidaten erkennen, ohne vorschnell Identität zu behaupten;
3. `W2-007` — Interrupt/Resume-Verhalten vervollständigen; der unavailable-root Fall ist bereits implementiert und lokal bestätigt;
4. `W2-008` — versionierten `FilenameParser` und `PathContextAnalyzer` implementieren;
5. `W2-009` — Parsing-Regeln und Fixtures für Autor/Titel, Serie/Band, Track/Disc, Jahr und Sprache ergänzen;
6. `W2-011` — ToolProvider-Runtime um noch fehlende Tests für malformed structured output, Version Change und selective re-analysis erweitern.

## Nicht implementiert

Noch nicht vorhanden sind unter anderem:

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

W9 darf später ausschließlich nicht ausführbare `ConsolidationPlan`-Einträge erzeugen.
