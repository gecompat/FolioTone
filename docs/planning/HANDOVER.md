# Handover / Fortsetzungsleitfaden

## Orientierung

FolioTone ist eine Orchestration- und Reconciliation-Plattform für große E-Book- und Musiksammlungen. Das Projekt kombiniert Filesystem-Evidenz, etablierte Spezialwerkzeuge, strukturierte Wissensquellen, Entity Resolution, Classification und Fingerprints in einem Provenance-erhaltenden Modell.

W0 und W1 sind abgeschlossen. Der erste W2-Slice für Incremental Index, Hashing und generische read-only ToolProvider Runtime ist implementiert und in GitHub Actions vollständig verifiziert.

**Der nächste Schritt ist der lokale Windows-/Docker-Smoke-Test gemäß `docs/quality/LOCAL_SMOKE_TEST.md`.** Erst danach werden die verbleibenden W2-Funktionen weiterentwickelt.

## Vor Änderungen lesen

1. `AGENTS.md`.
2. `docs/planning/PROJECT_STATUS.md`.
3. `docs/planning/BACKLOG.md`.
4. `docs/quality/DOCUMENTATION_STYLE.md` und `docs/quality/LANGUAGE_AND_TERMINOLOGY.md`, wenn Dokumentation berührt wird.
5. `docs/reference/GLOSSARY.md`, wenn fachliche Terminologie berührt wird.
6. Relevante Dateien unter `docs/architecture/` und `docs/decisions/`.
7. `docs/reference/EXTERNAL_TOOLS.md`, bevor ein konkreter externer ToolProvider implementiert wird.

## Verifizierter aktueller Stand

Der aktuelle W2-Slice hat in GitHub Actions bestanden:

```text
Install
Ruff
Mypy
Pytest (44 Tests)
Docker build
Docker migration smoke test
Docker persistent data write test
Docker incremental scan smoke test
Docker bootstrap/status
```

Der Docker Incremental Scan Smoke Test verwendet dieselbe persistente SQLite-Datenbank über vier getrennte Containerläufe und bestätigt:

```text
NEW: 2
UNCHANGED: 2
MODIFIED: 1 / MISSING: 1
UNCHANGED: 1 / REAPPEARED: 1
```

## W2 aktuell implementiert

### Index

- stabile logische `ScanRoot`-Identität über einen eindeutigen Namen;
- `ScanRun`-Lifecycle;
- streaming Filesystem Discovery;
- `FileObservation` und `FileScanEvent`;
- NEW, UNCHANGED, MODIFIED, MISSING und REAPPEARED;
- unavailable-root Schutz gegen falsches MISSING;
- read-only `foliotone scan` CLI;
- begrenzte Batch-Verarbeitung.

### Hashing

- NONE, QUICK und FULL;
- Quick Fingerprint mit begrenztem Datei-I/O;
- vollständiges SHA-256 als Streaming-Hash;
- Fingerprints gegen konkrete `FileObservation`;
- kein unnötiges Rehashing unveränderter Dateien.

### ToolProvider Runtime

- lokale Ausführung ohne Shell;
- Version Detection;
- Timeout/Cancellation;
- FAILED-Erfassung bei fehlendem Tool und Non-zero Exit;
- stdout/stderr als `ToolArtifact` mit SHA-256;
- Privacy-Schutz für persistierte Input-Identitäten;
- gehärtete Containerargumente mit read-only Input-Mounts, deaktiviertem Netzwerk als Default und isoliertem Work-Verzeichnis.

### Persistence

Alembic `0002_incremental_index` ergänzt den W1-Stand. Bereits gemergte Migrationen werden nicht rückwirkend verändert.

## Lokale Verifikation

Der Benutzer führt den lokalen Test auf Windows/Docker Desktop aus. Der genaue Ablauf steht in `docs/quality/LOCAL_SMOKE_TEST.md`.

Für den Test werden ausschließlich synthetische Dateien in den von Git ignorierten Runtime-Verzeichnissen verwendet. Es werden keine realen E-Books oder Musikdateien benötigt.

Nach erfolgreicher lokaler Verifikation wird `W2-012` auf DONE gesetzt.

## Danach weiterarbeiten

Nach dem lokalen Smoke-Test ist die nächste sinnvolle Reihenfolge:

1. `W2-004` — `DELETED`-Bestätigung definieren; MISSING darf nicht automatisch DELETED bedeuten.
2. `W2-006` — Move-/Rename-Kandidaten erkennen.
3. `W2-007` — Interrupt/Resume vervollständigen.
4. `W2-008` — `FilenameParser` und `PathContextAnalyzer`.
5. `W2-009` — Parsing-Regeln und synthetische Fixtures.
6. `W2-011` — verbleibende ToolRuntime-Tests für malformed output, Version Changes und selective re-analysis.

Erst danach beginnt W3 mit der konkreten E-Book-Toolauswahl und dem ersten calibre Vertical Slice.

## Verbindliche Sicherheitsgrenzen

- `/data` ist persistent read-write.
- Source Media unter `/media` bleibt read-only.
- Keine Source-Media-Delete-/Move-/Rename-/Retag-Operation durch W0 bis W9.
- Keine automatische Calibre-Modifikation.
- Keine write-capable externe Tooloperation.
- `MISSING` ist keine Löschbestätigung.
- Externe Tool-/Provider-Ergebnisse sind Evidence, nicht kanonische Wahrheit.
- Absolute private Pfade werden nicht als persistierte Tool-Input-Identität gespeichert.
- W10 bleibt bis zu einer späteren expliziten ADR blockiert.

## Dokumentations- und Lizenzregeln

- Die kanonische erklärende Dokumentation ist grundsätzlich deutsch; etablierte technische Begriffe bleiben in kanonischer Form.
- `docs/reference/GLOSSARY.md` ist für fachliche Kernbegriffe maßgeblich.
- Der zweisprachige Lizenzblock am Anfang der Root-README ist geschützt und darf nur auf ausdrücklichen Benutzerauftrag geändert werden.
- `LICENSE.md` bestimmt, dass die englische Lizenzfassung rechtlich maßgeblich ist.

## Handover-Qualitätsregel

Am Ende einer substanziellen Arbeit müssen `PROJECT_STATUS.md` und `BACKLOG.md` den realen Repositoryzustand wiedergeben. Tests dürfen nur als bestanden dokumentiert werden, wenn sie tatsächlich ausgeführt wurden. Ein zukünftiges KI-System darf zur Fortsetzung nicht auf den bisherigen Chat angewiesen sein.
