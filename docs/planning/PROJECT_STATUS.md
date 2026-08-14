# Projektstatus

Stand: 2026-08-14

## Aktuelle Welle

**W2 abgeschlossen — nächster Schritt W3: E-Book Analysis / Tool Orchestration**

W0 bis W2 sind abgeschlossen. Der Incremental Index, die generische read-only ToolProvider Runtime, Filename-/Path-Kandidaten und versionierte Parsing-Profile wurden vollständig lokal geprüft. `W2-011` ergänzt begrenzte strict-JSON-Auswertung persistierter Tool-Artefakte und eine konservative Reanalyse-Entscheidung. Der Docker-Build-Kontext ist durch eine allowlist-basierte `.dockerignore` auf die tatsächlich paketierten Anwendungsdateien begrenzt.

Die anfängliche Produktoberfläche bleibt auf ausdrückliche Benutzerentscheidung ausschließlich die CLI. ADR-0016 dokumentiert diese Grenze. W3 beginnt mit `W3-001`, der aktuellen Bewertung der calibre CLI und ergänzender EPUB-/PDF-Werkzeuge.

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

### Filename- und Path-Context-Kandidaten

`W2-008` implementiert einen bewusst kleinen, versionierten Basisvertrag für abgeleitete `FieldCandidate`-Werte. Die Komponenten setzen keine kanonischen Metadaten und interpretieren noch keine sammlungsspezifischen Namenskonventionen; diese Regeln gehören zu `W2-009`.

- `FilenameParser` akzeptiert genau einen Dateinamen ohne Pfadseparatoren und erzeugt aus dessen Stem einen `title`-Kandidaten mit `source_location = filename.stem` und Confidence `0.2`.
- `PathContextAnalyzer` akzeptiert ausschließlich sichere, `ScanRoot`-relative Pfade, normalisiert Windows- und POSIX-Separatoren und erzeugt aus dem direkten Parent einen `path_context`-Kandidaten mit `source_location = path.parent` und Confidence `0.1`.
- Jeder Kandidat enthält `Provenance` mit `source_kind = derived`, Komponentenname, Beobachtungszeitpunkt und expliziter Parser-Version. Absolute oder Traversal-Pfade werden abgewiesen; absolute Hostpfade werden dadurch nicht als Kandidateninhalt oder Source Location weitergegeben.

`W2-009` ergänzt `FilenameParsingProfile`, geordnete `FilenameParsingRule`-Regex-Regeln und `RuleBasedFilenameParser`. Die erste vollständig passende Regel erzeugt Kandidaten aus benannten Capture Groups. Profilversion, Regelname, Confidence und Source Location bleiben erhalten; ohne Treffer wird kein Wert geraten. Synthetische Tests decken Autor/Titel, Serie/Band, Track/Disc, Jahr und Sprache ab.

### Generische ToolProvider Runtime

Implementiert sind:

- lokale Tool-Ausführung ohne Shell;
- Tool-Versionsermittlung;
- Timeouts und Cancellation;
- auditierbare FAILED-Ausführung bei fehlendem Tool oder Non-zero Exit;
- file-backed stdout/stderr mit `ToolArtifact`, Größe und SHA-256;
- begrenzte stdout/stderr Previews;
- begrenzte, strikt als UTF-8 JSON validierte Auswertung eines persistierten stdout-`ToolArtifact` einschließlich Size-/SHA-256-Integritätsprüfung;
- `StructuredOutputError` bei fehlender, zu großer, veränderter oder malformed strukturierter Ausgabe, ohne eine erfolgreiche Prozessausführung rückwirkend umzudeuten;
- konservative `requires_reanalysis`-Entscheidung: Wiederverwendung ist nur bei erfolgreicher vorheriger Ausführung und exakt gleicher Provider-, Capability-, Input-, Tool-, Adapter- und expliziter Konfigurationsidentität zulässig;
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

### W2-Abschlussprüfung

**Empirisch:** Am 2026-08-14 wurden die vollständigen lokalen Quality Gates mit Python 3.12.10 ausgeführt. `ruff check .`, `mypy src/foliotone` für 56 Source-Dateien und 86 Pytest-Tests waren erfolgreich. Die Tests decken insbesondere die W2-009-Parsing-Profile sowie die W2-011-Fälle malformed JSON, fehlende/zu große Ausgabe, Artifact-Integrität, fehlgeschlagene frühere Ausführungen und Reanalyse nach Tool-, Adapter-, Input- oder Konfigurationsänderung ab.

Der Linux-Container wurde über Docker Engine 29.7.2 und Docker Compose 5.4.0 in WSL2 gebaut. Container-Bootstrap und Alembic-Head-Migration waren erfolgreich. Der allowlist-basierte Docker-Build-Kontext enthält ausschließlich `Dockerfile`, `pyproject.toml`, `README.md` und `src/`; lokale Runtime-, Medien-, Secret-, Test- und Git-Daten werden nicht übertragen.

## W2-Abschluss und nächster Schritt

In W2 verbleibt kein offener Backlog-Eintrag. `W3-001` ist `NEXT`: Vor der Implementierung eines konkreten E-Book-Adapters werden aktuelle offizielle Dokumentation, Wartungsstatus, Lizenz, Automationsschnittstelle, Ausgabeformate und read-only Sicherheitsverhalten der calibre CLI sowie geeigneter EPUB-/PDF-Werkzeuge geprüft.

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
- Web-API, Desktop-Oberfläche oder Dashboard; die aktuelle Produktoberfläche ist gemäß ADR-0016 ausschließlich die CLI.

## Sicherheitsgrenze

W10 bleibt ausdrücklich blockiert. Es gibt keine FolioTone-native oder externe Tool-Operation zum Löschen, Verschieben, Umbenennen oder Retaggen von Source Media.

`DELETED`, `FileRelocationCandidate` und Scan-Resume sind ausschließlich Analyse-/Orchestrierungszustände. W9 darf später ausschließlich nicht ausführbare `ConsolidationPlan`-Einträge erzeugen.
