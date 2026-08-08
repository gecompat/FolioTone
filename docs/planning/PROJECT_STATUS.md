# Projektstatus

Stand: 2026-08-09

## Aktuelle Welle

**W2 — Incremental Index + Filename/Path Context + Tool Runtime**

W0 und W1 sind abgeschlossen. Der erste konsistente W2-Slice ist implementiert und in GitHub Actions vollständig verifiziert. Vor der Fortsetzung mit `DELETED`-Bestätigung, Move/Rename-Erkennung und Filename/Path-Parsing soll der aktuelle Stand zusätzlich lokal unter Windows/Docker Desktop geprüft werden.

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

Der W2-Head `39ff205ab14c4e886362303f4ee883022a9face5` wurde in GitHub Actions Run `31282677449` vollständig geprüft:

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

Die Source-Media-Verzeichnisse bleiben im Compose-Vertrag read-only. `/data` ist als persistenter Runtime-Bereich explizit read-write eingebunden.

## Lokaler Testpunkt

Der aktuelle Stand ist für einen lokalen Windows-/Docker-Test geeignet. Der reproduzierbare Ablauf ist unter `docs/quality/LOCAL_SMOKE_TEST.md` dokumentiert und verwendet ausschließlich synthetische Dateien unter dem von Git ignorierten Verzeichnis `media/ebooks`.

Der lokale Test soll insbesondere bestätigen:

- Docker-Compose-Build unter der lokalen Plattform;
- persistente `/data`-Nutzung über mehrere Containerläufe;
- read-only `/media/ebooks`;
- NEW/UNCHANGED/MODIFIED/MISSING/REAPPEARED-Verhalten unter Docker Desktop.

## Noch offen in W2

Als nächste fachliche W2-Arbeiten bleiben:

1. `W2-004` — robuste `DELETED`-Bestätigung definieren und implementieren;
2. `W2-006` — Move-/Rename-Kandidaten erkennen, ohne vorschnell Identität zu behaupten;
3. `W2-007` — Interrupt/Resume-Verhalten vervollständigen; der unavailable-root Fall ist bereits getestet;
4. `W2-008` — versionierten `FilenameParser` und `PathContextAnalyzer` implementieren;
5. `W2-009` — Parsing-Regeln und Fixtures für Autor/Titel, Serie/Band, Track/Disc, Jahr und Sprache ergänzen;
6. `W2-011` — ToolProvider-Runtime um noch fehlende Tests für malformed structured output, Version Change und selective re-analysis erweitern.

Diese Punkte werden erst nach dem lokalen Smoke-Test des aktuellen Slices fortgesetzt.

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
