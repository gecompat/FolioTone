# Handover / Fortsetzungsleitfaden

## Orientierung

FolioTone ist eine Orchestration- und Reconciliation-Plattform für große E-Book- und Musiksammlungen. Das Projekt kombiniert Filesystem-Evidenz, etablierte Spezialwerkzeuge, strukturierte Wissensquellen, Entity Resolution, Classification und Fingerprints in einem Provenance-erhaltenden Modell.

W0 bis W2 sind abgeschlossen. Der W2-Slice umfasst Incremental Index, Hashing, Filename-/Path-Kandidaten, konfigurierbare Parsing-Profile und eine generische read-only ToolProvider Runtime. `W2-004` ergänzt eine konservative, opt-in `DELETED`-Bestätigung. `W2-006` ergänzt konservative Move-/Rename-Kandidaten. `W2-007` ergänzt explizite Resume-Lineage für unterbrochene Scans, ohne einen instabilen Filesystem-Cursor einzuführen.

`W2-008` und `W2-009` sind vollständig validiert: Basisparser und konfigurierbare, versionierte Regex-Profile erzeugen ausschließlich Provenance-behaftete `FieldCandidate`-Werte und setzen keine kanonischen Metadaten. `W2-011` ergänzt begrenzte, strikte JSON-Auswertung aus `ToolArtifact`-Dateien und konservative Reanalyse-Entscheidungen. Der Docker-Build-Kontext ist auf die tatsächlich paketierten Anwendungsdateien beschränkt.

Die anfängliche Produktoberfläche ist gemäß Benutzerentscheidung und ADR-0016
ausschließlich die CLI. `W3-001` und `W3-002` sind abgeschlossen: Die aktuelle
E-Book-Toolchain ist bewertet, und der erste read-only calibre-Metadaten-Slice
ist implementiert. `W3-003` ergänzt einen festen read-only calibre-EPUB-
Textpfad und einen FolioTone-eigenen normalisierten Fingerprint. `W3-004`
ergänzt feste Poppler-PDF-Metadaten-, Seiten- und Textpfade mit explizitem
`NO_TEXT`. `W3-005` erweitert die vorhandenen calibre-Pfade auf eine explizite
EPUB/MOBI/AZW/AZW3-Allowlist. `W3-006` ist als Nächstes vorgesehen.

## Vor Änderungen lesen

1. `AGENTS.md`.
2. `docs/planning/PROJECT_STATUS.md`.
3. `docs/planning/BACKLOG.md`.
4. `docs/quality/DOCUMENTATION_STYLE.md` und `docs/quality/LANGUAGE_AND_TERMINOLOGY.md`, wenn Dokumentation berührt wird.
5. `docs/reference/GLOSSARY.md`, wenn fachliche Terminologie berührt wird.
6. Relevante Dateien unter `docs/architecture/` und `docs/decisions/`.
7. `docs/reference/EXTERNAL_TOOLS.md`, bevor ein konkreter externer ToolProvider implementiert wird.
8. `docs/reference/EBOOK_TOOL_EVALUATION.md` für die verbindlichen W3-Entscheidungen und die calibre-Sicherheitsuntergrenze.

## Verifizierter aktueller Stand

### Grundlegender W2-Slice

Der finale W2-PR-#5-Head `ef10290da1ed3522e5a261ccb33d5561e32eb497` hat in GitHub Actions Run `31282820586` bestanden. Der automatisierte Docker Incremental Scan Smoke Test bestätigt NEW → UNCHANGED → MODIFIED/MISSING → REAPPEARED über getrennte Containerläufe und persistente SQLite-Daten.

### `W2-004`

Der Implementierungs-Head `556055eb7848f3f682f0bd2363ba2dc98fceb7e5` von PR #7 hat in GitHub Actions Run `31285157432` bestanden. Die Tests decken Deletion-Policy, Failed-Scan-Unterbrechung der Bestätigungsserie, Reappearance nach `DELETED` und das konservative Upgrade von `0002` nach `0003` ab.

### `W2-006`

Der Implementierungs-Head `c946dd336593b68ed281c530ab40117562d17831` von PR #8 hat in GitHub Actions Run `31285662119` mit 52 Tests bestanden. Geprüft sind Rename-, Move- und kombinierte Move-/Rename-Kandidaten, Mehrdeutigkeitsunterdrückung und `FILE_SHA256`-Evidence-Präferenz.

### `W2-007`

Der Implementierungs-Head `8bfa20fb692727f03f8f0cd40b64385328e75d30` von PR #9 hat in GitHub Actions Run `31286181807` vollständig bestanden: Install, Ruff, Mypy, Pytest sowie alle Docker-/Migrations-Smoke-Schritte.

Die Resume-Tests bestätigen:

- ein partiell verarbeiteter Scan endet als `INTERRUPTED`, ohne die erfolgreiche Abwesenheitsphase auszuführen;
- ein Resume erzeugt einen neuen `ScanRun` mit `resumed_from_run_id`;
- vor dem Interrupt bereits verarbeitete unveränderte Dateien werden beim Resume als `UNCHANGED` erkannt und nicht erneut gehasht;
- nicht erreichte bekannte Dateien werden durch den unterbrochenen Run nicht als `MISSING` markiert;
- nur ein persistierter `INTERRUPTED`-Run desselben `ScanRoot` kann als Resume-Quelle verwendet werden;
- `0005_scan_resume_lineage` stellt die persistente Lineage bereit.

### Lokale Windows-/Docker-Verifikation

`W2-012` wurde am 2026-08-09 mit synthetischen Dateien erfolgreich lokal ausgeführt. Verwendet wurden Docker Engine `29.6.2` und Docker Compose `v5.3.1`. Empirisch bestätigt wurden Compose-Build, persistentes `/data`, read-only `/media/ebooks`, die grundlegenden Incremental-States und unavailable-root Schutz.

Die später ergänzten `DELETED`-, Relocation- und Resume-Funktionen wurden in diesem lokalen Plattform-Smoke-Test nicht separat nachgestellt; sie sind automatisiert durch Integrationstests geprüft.

### W2-Abschlussprüfung

Am 2026-08-14 bestanden lokal `ruff check .`, `mypy src/foliotone` für 56 Source-Dateien und 86 Pytest-Tests mit Python 3.12.10. Der Linux-Container-Build über Docker Engine 29.7.2 und Docker Compose 5.4.0 in WSL2 sowie Container-Bootstrap und Alembic-Head-Migration waren erfolgreich.

Die Abschlussprüfung bestätigt zusätzlich:

- W2-009-Profile für Autor/Titel, Serie/Band, Track/Disc, Jahr und Sprache;
- `StructuredOutputError` bei malformed, zu großer, fehlender oder integritätsverletzter JSON-Ausgabe, während die ursprüngliche `ToolExecution` auditierbar bleibt;
- Reanalyse bei Tool-, Adapter-, Input- oder Konfigurationsänderung;
- keine Wiederverwendung ohne explizite Konfigurationsidentität;
- allowlist-basierten Docker-Build-Kontext ohne lokale Runtime-, Medien-, Secret-, Test- oder Git-Daten.

### W3-001 bis W3-005

Der Snapshot vom 2026-08-14 wählt calibre 9.13.0 für dateibezogene Metadaten,
EPUBCheck 5.3.0 für spätere EPUB-Konformität, Poppler 26.07.0 für implementierte
PDF-Metadaten-/Seiten-/Textanalyse und qpdf 12.4.0 als optionale strukturelle
PDF-Evidence. Details und Lizenzen stehen in
`docs/reference/EBOOK_TOOL_EVALUATION.md`.

`foliotone ebook-metadata` analysiert eine persistierte `FileObservation` über
die unveränderliche Befehlsform `ebook-meta FILE --to-opf metadata.opf`.
Unbekannte calibre-Versionen sowie Versionen kleiner als 9.10.0 werden wegen
`GHSA-2j4m-2q7x-2c47` vor dem Dateiöffnen abgelehnt. Calibre-Konfiguration ist
ephemer; das maximal 4 MiB große OPF wird als integritätsgeprüftes
`CALIBRE_OPF`-Artefakt gespeichert. Ausgewählte Felder werden als rohe
`ToolResult`-Evidence gegen die konkrete Observation persistiert.

Ein lokaler End-to-End-Smoke-Test mit einem ausschließlich synthetischen EPUB
und einer separat geprüften calibre-9.13-Installation war erfolgreich. Die
vollständigen lokalen Quality Gates bestanden mit Ruff, Mypy für 57
Source-Dateien und 107 Pytest-Tests. Der Implementierungscommit
`1a02dc146919db7294b7b88ad6d9f6a7a6e60e04` bestand GitHub Actions Run
`31794835407` einschließlich aller Docker-Smoke-Schritte.

`foliotone ebook-text` akzeptiert eine unveränderte EPUB-, MOBI-, AZW- oder
AZW3-`FileObservation`. Der Adapter ruft `ebook-convert` mit einer festen
Plaintext-/UTF-8-/Unix-Befehlsform auf und übernimmt maximal 64 MiB als privates
`CALIBRE_TEXT`-Artefakt. FolioTone normalisiert mit Unicode `NFKC`, reduziert
Whitespace und speichert SHA-256 als `EBOOK_NORMALIZED_TEXT`-`Fingerprint` mit
`ToolExecution`-Link und versioniertem Unicode-Datenprofil. `TEXT_EXTRACTED`
und `NO_TEXT` sind explizite `ToolResult`-Werte; `NO_TEXT` entsteht nur nach
erfolgreicher leerer Extraktion und erzeugt keinen Fingerprint. DRM-Umgehung
gehört nicht zum Vertrag. Rohtext erscheint nicht in der CLI-Ausgabe.

Ein lokaler End-to-End-Smoke-Test mit calibre 9.13.0 und ausschließlich dem
synthetischen EPUB bestätigte `TEXT_EXTRACTED`, 43 normalisierte Zeichen, ein
49 Byte großes Text-Artefakt, einen 64-stelligen Fingerprint und ein leeres
ephemeres Work-Verzeichnis. Repository-Ruff, Mypy für 59 Source-Dateien und 115
Pytest-Tests waren erfolgreich. Der Implementierungscommit
`dc2cd09ffbc07098e0c296bea231532c4f38051b` bestand GitHub Actions Run
`31809375485` für PR #13 einschließlich aller Docker-Smoke-Schritte.

`foliotone pdf-analyze` akzeptiert ausschließlich eine unveränderte PDF-
`FileObservation`. Der Adapter führt feste `pdfinfo`- und `pdftotext`-Befehle
als zwei getrennte `ToolExecution`-Records aus, begrenzt und validiert die
Metadatenausgabe und übernimmt maximal 64 MiB als privates `POPPLER_TEXT`-
Artefakt. PDF verwendet denselben FolioTone-eigenen normalisierten
`EBOOK_NORMALIZED_TEXT`-Fingerprint wie EPUB. Erfolgreiche leere Extraktion ist
`NO_TEXT`; Fehler werden nicht in diesen Zustand umgedeutet. Poppler-Versionen
unter 26.07.0 und unbekannte Versionen werden vor dem Dateiöffnen abgelehnt.

Ein lokaler End-to-End-Smoke-Test mit Poppler 26.07.0 und ausschließlich zwei
synthetischen PDFs bestätigte für beide je 20 Metadatenbeobachtungen und
`page_count = 1`. Das Text-PDF lieferte `TEXT_EXTRACTED`, 45 normalisierte
Zeichen und einen Fingerprint; das leere PDF lieferte `NO_TEXT`, null Zeichen
und keinen Fingerprint. Die gezielten 18 Poppler-Unit-Tests bestanden, und die
ephemeren Work-Verzeichnisse waren nach Abschluss leer.

Der vollständige W3-004-Stand bestand lokal `ruff check .`, Mypy für 63
Source-Dateien und alle 133 Pytest-Tests in 6 Minuten 35 Sekunden.

Der lokale W3-005-End-to-End-Smoke verwendete ausschließlich synthetische,
DRM-freie EPUB-, MOBI-, AZW- und AZW3-Dateien. Mit calibre 9.13.0 entstanden
jeweils vier erfolgreiche Metadaten- und Textausführungen. Alle Textläufe
lieferten `TEXT_EXTRACTED`, 43 normalisierte Zeichen und denselben
`EBOOK_NORMALIZED_TEXT`-Fingerprint; das Work-Verzeichnis war danach leer. Die
gezielten 32 calibre-/CLI-Tests sowie Ruff und Mypy für 63 Source-Dateien waren
erfolgreich.

Der vollständige W3-005-Stand bestand lokal `ruff check .`, Mypy für 63
Source-Dateien und alle 142 Pytest-Tests in 8 Minuten 50 Sekunden.

## W2 aktuell implementiert

### Index

- stabile logische `ScanRoot`-Identität über einen eindeutigen Namen;
- `ScanRun`-Lifecycle mit auditablem `resumed_from_run_id`;
- streaming Filesystem Discovery;
- `FileObservation` und `FileScanEvent`;
- NEW, UNCHANGED, MODIFIED, MISSING, REAPPEARED und opt-in DELETED;
- unavailable-root Schutz gegen falsches MISSING;
- read-only `foliotone scan` CLI einschließlich `--resume-run`;
- begrenzte Batch-Verarbeitung;
- persistente Abwesenheitsserie über `missing_since_at` und `consecutive_missing_scans`;
- persistente `FileRelocationCandidate`-Records für eindeutige NEW/erstmalig-MISSING Fingerprint-Paare im selben erfolgreichen Scan.

### `DELETED`-Policy

`DeletionConfirmationPolicy` ist standardmäßig nicht aktiv. Bei expliziter Aktivierung müssen sowohl eine konfigurierte Anzahl aufeinanderfolgender erfolgreicher `MISSING`-Scans als auch eine konfigurierte Mindestdauer erfüllt sein. Failed oder interrupted Scans erhöhen die Serie nicht. Ein bestätigtes `DELETED` erzeugt keine Filesystem-Operation. ADR-0013 ist verbindlich.

### Relocation-Kandidaten

`FileRelocationCandidate` ist zusätzliche Evidence, keine bestätigte File-Identität. Source bleibt ein eigener `MISSING`-Record und Target ein eigener `NEW`-Record. Kandidaten werden nur innerhalb desselben `ScanRoot` und Scans aus eindeutigen versionierten `QUICK_FILE`-/`FILE_SHA256`-Blöcken gebildet. ADR-0014 ist verbindlich.

### Interrupt/Resume

Resume wird als neuer `ScanRun` modelliert. `resumed_from_run_id` verweist auf den persistierten `INTERRUPTED`-Vorgänger desselben `ScanRoot`. Discovery läuft erneut vollständig und streaming-basiert; ein persistenter `os.scandir`-Cursor wird bewusst nicht verwendet. Bereits persistierte unveränderte Teilverarbeitung wird durch den normalen Incremental-Vergleich wiederverwendet und nicht erneut gehasht. Erst ein vollständig erfolgreicher Resume-Run darf `MISSING`/`DELETED` klassifizieren. ADR-0015 ist verbindlich.

### Hashing

- NONE, QUICK und FULL;
- Quick Fingerprint mit begrenztem Datei-I/O;
- vollständiges SHA-256 als Streaming-Hash;
- Fingerprints gegen konkrete `FileObservation`;
- kein unnötiges Rehashing unveränderter Dateien, auch nicht bei Resume bereits verarbeiteter unveränderter Files.

### Filename- und Path-Context-Kandidaten

`FilenameParser` erzeugt aus einem Dateinamen ohne Pfadseparatoren einen niedrig gewichteten `title`-Kandidaten. `PathContextAnalyzer` verarbeitet nur sichere relative Pfade und erzeugt aus dem direkten Parent einen niedrig gewichteten `path_context`-Kandidaten. Beide Komponenten speichern die Parser-Version, den Komponentenname und den beobachteten Zeitpunkt in `Provenance`; sie geben keine absoluten Hostpfade aus. `RuleBasedFilenameParser` wendet geordnete, versionierte Regex-Profile auf sammlungsspezifische Konventionen für Autor, Titel, Serie, Band, Track, Disc, Jahr und Sprache an.

### ToolProvider Runtime

- lokale Ausführung ohne Shell;
- Version Detection;
- Timeout/Cancellation;
- FAILED-Erfassung bei fehlendem Tool und Non-zero Exit;
- stdout/stderr als `ToolArtifact` mit SHA-256;
- begrenzte, strikte JSON-Auswertung aus persistiertem stdout-`ToolArtifact` mit Größen-/SHA-256-Integritätsprüfung;
- konservative Reanalyse anhand erfolgreicher früherer Ausführung und exakter Provider-, Capability-, Input-, Tool-, Adapter- und Konfigurationsidentität;
- Privacy-Schutz für persistierte Input-Identitäten;
- gehärtete Containerargumente mit read-only Input-Mounts, deaktiviertem Netzwerk als Default und isoliertem Work-Verzeichnis.
- deklarierte, größenbegrenzte Workspace-Ausgaben, die vor dem ephemeren Cleanup
  als `ToolArtifact` mit SHA-256 übernommen werden;
- Adapter-Version-Policies, die unsichere Versionen vor der Source-Analyse
  auditierbar ablehnen können.

### calibre-Metadaten

- `CalibreMetadataAnalyzer` und CLI `foliotone ebook-metadata`;
- feste read-only `ebook-meta FILE --to-opf`-Argumentform ohne Setter;
- Sicherheitsuntergrenze calibre 9.10.0 vor dem Öffnen der Eingabe;
- ephemere `CALIBRE_CONFIG_DIRECTORY` für Versionsabfrage und Analyse;
- begrenztes, integritätsgeprüftes OPF-Artefakt;
- rohe Titel-, Creator-, Identifier-, Sprach-, Verlags-, Datums-, Subject- und
  Series-Beobachtungen mit `ToolExecution`-Link;
- kein `calibredb` bis zu einem konkreten read-only Library-Reconciliation-Vertrag.

### calibre-EPUB/MOBI/AZW/AZW3-Text

- `CalibreTextAnalyzer` und CLI `foliotone ebook-text`;
- explizite EPUB/MOBI/AZW/AZW3-Allowlist und eine feste
  `ebook-convert FILE content.txt`-Befehlsform ohne frei übergebbare Optionen;
- `ToolCapability.EXTRACT_TEXT` sowie Sicherheitsuntergrenze calibre 9.10.0;
- UTF-8-Plaintext, Unix-Zeilenenden und deaktivierte Zeilenaufteilung;
- maximal 64 MiB großes privates, integritätsgeprüftes `CALIBRE_TEXT`-Artefakt;
- FolioTone-eigene versionierte `NFKC`-/Whitespace-Normalisierung und SHA-256;
- `EBOOK_NORMALIZED_TEXT` gegen konkrete `FileObservation` und `ToolExecution`;
- explizite Zustände `TEXT_EXTRACTED` und `NO_TEXT`, ohne Fingerprint bei
  fehlendem Text;
- keine DRM-Entfernung oder -Umgehung; Konvertierungsfehler bleiben
  fehlgeschlagene `ToolExecution`-Records und werden nicht zu `NO_TEXT`;
- keine Ausgabe des extrahierten Rohtexts über die CLI.

### Poppler-PDF

- `PopplerPdfAnalyzer` und CLI `foliotone pdf-analyze`;
- ausschließlich PDF sowie feste `pdfinfo`-/`pdftotext`-Argumentformen;
- separate `ToolExecution`-Records für technische Metadaten und Text;
- Sicherheitsuntergrenze Poppler 26.07.0 vor dem Öffnen der Eingabe;
- maximal 1 MiB allowlist-geparste `pdfinfo`-Ausgabe und validierte Dateigröße;
- maximal 64 MiB großes privates, integritätsgeprüftes `POPPLER_TEXT`-Artefakt;
- gemeinsamer versionierter `NFKC`-/Whitespace-Normalisierer und
  `EBOOK_NORMALIZED_TEXT`-Fingerprint;
- explizites `NO_TEXT` nur nach erfolgreicher leerer Extraktion;
- kein Rohtext, OCR, Passwortargument, frei übergebbares Poppler-Argument oder
  PDF-Schreibpfad über die CLI;
- qpdf bis zu einem konkreten Bedarf an zusätzlicher Struktur-Evidence
  zurückgestellt.

### Persistence

- Alembic `0002_incremental_index` ergänzt Scan-Events, Tool-Artefakte und W2-Indizes;
- Alembic `0003_deletion_confirmation` ergänzt die persistente Abwesenheitsserie;
- Alembic `0004_relocation_candidates` ergänzt persistente Relocation-Kandidaten;
- Alembic `0005_scan_resume_lineage` ergänzt `scan_runs.resumed_from_run_id` und den zugehörigen Index.

Bereits gemergte Migrationen werden nicht rückwirkend verändert.

## Danach weiterarbeiten

Die nächste sinnvolle Reihenfolge ist:

1. `W3-006` — detailliertere Feld-/Rollenabbildung als Provenance-erhaltende
   Beobachtungen und Kandidaten.
2. `W3-007` — synthetische/öffentliche Vergleichs-Fixtures für Editionen,
   Übersetzungen, Metadatenänderungen und Tool-Disagreement.
3. `W3-008` — strukturelle Validierungs- und Book-Diff-Evidence bewerten.

Die Produktoberfläche bleibt dabei ausschließlich die CLI. Externe Tool-Ergebnisse werden weiterhin als Evidence behandelt und nicht direkt zu kanonischen Metadaten.

## Verbindliche Sicherheitsgrenzen

- `/data` ist persistent read-write.
- Source Media unter `/media` bleibt read-only.
- Keine Source-Media-Delete-/Move-/Rename-/Retag-Operation durch W0 bis W9.
- `DELETED` ist ein Indexzustand und keine Delete-Operation.
- `FileRelocationCandidate` ist Evidence und keine Move-/Rename-Ausführung oder Identitätszusammenführung.
- Scan-Resume ist Orchestrierung und verändert Source Media nicht.
- Keine automatische Calibre-Modifikation.
- Keine write-capable externe Tooloperation.
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
