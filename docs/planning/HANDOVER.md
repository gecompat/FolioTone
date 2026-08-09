# Handover / Fortsetzungsleitfaden

## Orientierung

FolioTone ist eine Orchestration- und Reconciliation-Plattform für große E-Book- und Musiksammlungen. Das Projekt kombiniert Filesystem-Evidenz, etablierte Spezialwerkzeuge, strukturierte Wissensquellen, Entity Resolution, Classification und Fingerprints in einem Provenance-erhaltenden Modell.

W0 und W1 sind abgeschlossen. Der grundlegende W2-Slice für Incremental Index, Hashing und generische read-only ToolProvider Runtime ist implementiert, in GitHub Actions vollständig verifiziert und zusätzlich lokal unter Windows/Docker Desktop geprüft. `W2-004` ergänzt eine konservative, opt-in `DELETED`-Bestätigung, ohne eine Source-Media-Schreiboperation einzuführen.

**Der nächste Schritt ist `W2-006`: Move-/Rename-Kandidaten erkennen, ohne aus ähnlichen Dateien vorschnell eine Identität abzuleiten.**

## Vor Änderungen lesen

1. `AGENTS.md`.
2. `docs/planning/PROJECT_STATUS.md`.
3. `docs/planning/BACKLOG.md`.
4. `docs/quality/DOCUMENTATION_STYLE.md` und `docs/quality/LANGUAGE_AND_TERMINOLOGY.md`, wenn Dokumentation berührt wird.
5. `docs/reference/GLOSSARY.md`, wenn fachliche Terminologie berührt wird.
6. Relevante Dateien unter `docs/architecture/` und `docs/decisions/`.
7. `docs/reference/EXTERNAL_TOOLS.md`, bevor ein konkreter externer ToolProvider implementiert wird.

## Verifizierter aktueller Stand

### Grundlegender W2-Slice

Der finale W2-PR-#5-Head `ef10290da1ed3522e5a261ccb33d5561e32eb497` hat in GitHub Actions Run `31282820586` bestanden und wurde als Merge-Commit `4362d60eca51c3e896ae3a6e4fb4485e644bbc4d` nach `main` übernommen:

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

Der automatisierte Docker Incremental Scan Smoke Test verwendet dieselbe persistente SQLite-Datenbank über vier getrennte Containerläufe und bestätigt:

```text
NEW: 2
UNCHANGED: 2
MODIFIED: 1 / MISSING: 1
UNCHANGED: 1 / REAPPEARED: 1
```

### `W2-004`

Der Implementierungs-Head `556055eb7848f3f682f0bd2363ba2dc98fceb7e5` von PR #7 hat in GitHub Actions Run `31285157432` bestanden:

```text
Install
Ruff
Mypy (49 source files)
Pytest (48 Tests)
Docker build
Docker migration smoke test
Docker persistent data write test
Docker incremental scan smoke test
Docker bootstrap/status
```

Die zusätzlichen Tests decken die Deletion-Policy, Failed-Scan-Unterbrechung der Bestätigungsserie, Reappearance nach `DELETED` und das konservative Upgrade von `0002` nach `0003` ab.

### Lokale Windows-/Docker-Verifikation

`W2-012` wurde am 2026-08-09 mit synthetischen Dateien erfolgreich lokal ausgeführt. Verwendet wurden Docker Engine `29.6.2` und Docker Compose `v5.3.1`.

Empirisch bestätigt wurden:

- erfolgreicher Compose-Build und `foliotone status`;
- persistentes, beschreibbares `/data` über getrennte Containerläufe;
- read-only `/media/ebooks`; ein Schreibversuch aus dem Container scheiterte wie vorgesehen;
- `NEW: 2` beim Erstscan;
- `UNCHANGED: 2` beim unveränderten Folgescan;
- `MODIFIED: 1 / MISSING: 1` nach kontrollierter Änderung und Abwesenheit;
- `UNCHANGED: 1 / REAPPEARED: 1` nach Wiederauftauchen;
- ein unavailable `ScanRoot` beendet den Scan fehlerhaft, ohne anschließend falsches `MISSING` zu erzeugen; der nächste gültige Scan meldete `UNCHANGED: 2`.

Die opt-in `DELETED`-Bestätigung wurde im lokalen Plattform-Smoke-Test nicht künstlich durch verkürzte Zeitgrenzen nachgestellt; sie ist automatisiert durch Integrationstests geprüft.

## W2 aktuell implementiert

### Index

- stabile logische `ScanRoot`-Identität über einen eindeutigen Namen;
- `ScanRun`-Lifecycle;
- streaming Filesystem Discovery;
- `FileObservation` und `FileScanEvent`;
- NEW, UNCHANGED, MODIFIED, MISSING, REAPPEARED und opt-in DELETED;
- unavailable-root Schutz gegen falsches MISSING;
- read-only `foliotone scan` CLI;
- begrenzte Batch-Verarbeitung;
- persistente Abwesenheitsserie über `missing_since_at` und `consecutive_missing_scans`.

### `DELETED`-Policy

`DeletionConfirmationPolicy` ist standardmäßig nicht aktiv. Bei expliziter Aktivierung müssen sowohl eine konfigurierte Anzahl aufeinanderfolgender erfolgreicher `MISSING`-Scans als auch eine konfigurierte Mindestdauer erfüllt sein. Die Policy selbst verwendet als Default drei Scans und 24 Stunden; die CLI aktiviert sie erst durch `--confirm-deleted-after-missing-scans`.

Failed oder interrupted Scans erhöhen die Serie nicht. Ein bestätigtes `DELETED` erzeugt keine Filesystem-Operation. Taucht der Pfad später wieder auf, entsteht `REAPPEARED` und die Abwesenheitsserie wird zurückgesetzt. Die verbindliche Entscheidung steht in `docs/decisions/ADR-0013-deletion-confirmation.md`.

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

- Alembic `0002_incremental_index` ergänzt Scan-Events, Tool-Artefakte und W2-Indizes;
- Alembic `0003_deletion_confirmation` ergänzt die persistente Abwesenheitsserie auf `FileRecord`;
- beim Upgrade von `0002` wird keine historische Deletion-Serie erfunden; vorhandene Records starten konservativ mit leerem Tracking.

Bereits gemergte Migrationen werden nicht rückwirkend verändert.

## Danach weiterarbeiten

Die nächste sinnvolle Reihenfolge ist:

1. `W2-006` — Move-/Rename-Kandidaten erkennen.
2. `W2-007` — Interrupt/Resume vervollständigen; unavailable-root ist bereits implementiert und lokal bestätigt.
3. `W2-008` — `FilenameParser` und `PathContextAnalyzer`.
4. `W2-009` — Parsing-Regeln und synthetische Fixtures.
5. `W2-011` — verbleibende ToolRuntime-Tests für malformed output, Version Changes und selective re-analysis.

Erst danach beginnt W3 mit der konkreten E-Book-Toolauswahl und dem ersten calibre Vertical Slice.

## Verbindliche Sicherheitsgrenzen

- `/data` ist persistent read-write.
- Source Media unter `/media` bleibt read-only.
- Keine Source-Media-Delete-/Move-/Rename-/Retag-Operation durch W0 bis W9.
- `DELETED` ist ein Indexzustand und keine Delete-Operation.
- Keine automatische Calibre-Modifikation.
- Keine write-capable externe Tooloperation.
- `MISSING` ist keine Löschbestätigung; `DELETED` benötigt bei aktivierter Policy mehrere erfolgreiche Abwesenheitsbestätigungen plus Mindestdauer.
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
