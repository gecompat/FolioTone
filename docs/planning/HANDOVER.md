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
EPUB/MOBI/AZW/AZW3-Allowlist. `W3-006` ergänzt eine OPF2-/OPF3-Feld- und
Rollenprojektion mit provider-neutralen, Provenance-verknüpften Kandidaten.
`W3-007` ergänzt einen versionierten synthetischen Vergleichskorpus für Datei-,
Inhalts-, `Edition`-, `Work`- und Tool-Disagreement-Ground-Truth. `W3-008`
ergänzt feste EPUBCheck-JSON-Strukturvalidierung und provider-spezifische
akzeptierte Exitcodes. `W3-009` ergänzt eine quellisolierte
EPUB/MOBI/AZW/AZW3-Embedded-Cover-Extraktion, explizites
`NO_EMBEDDED_COVER` und einen versionierten FolioTone-dHash. `W3-010` ergänzt
den formatbewussten, einheitlichen CLI-Workflow `ebook-analyze`. `W3-011`
ergänzt dessen konservative exakte Evidence-Wiederverwendung, gezielten
Schritt-Retry und `--fresh`. Auf Benutzerentscheidung bleibt die Entwicklung
bis zur Reife der E-Book-Pipeline bei E-Books; `W3-012` ist als Nächstes
vorgesehen, Music W4 ist zurückgestellt.

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

### W3-001 bis W3-009

Der am 2026-08-15 aktualisierte Snapshot wählt calibre 9.13.0 für dateibezogene Metadaten,
EPUBCheck 5.3.0 für implementierte EPUB-Konformität, Poppler 26.07.0 für implementierte
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

Der gezielte W3-006-Lauf bestand alle 26 calibre-Metadaten-Tests einschließlich
OPF-2-Attributen, OPF-3-Refinements, ISBN-/Identifier-Namespace,
Contributor-Gruppierung, MARC-Rollen, Sortiernamen, Series-Gruppierung und
bewusst nicht normalisierten fremden Rollen-Schemes. Der vollständige Stand
bestand lokal `ruff check .`, Mypy für 64 Source-Dateien und alle 152
Pytest-Tests in 8 Minuten 45 Sekunden.

Der read-only CLI-Smoke-Test mit calibre 9.13 und einem ausschließlich
synthetischen, DRM-freien MOBI persistierte unter `ebook-meta-opf/2` elf rohe
Beobachtungen und 21 Kandidaten. Alle Ergebnisse verwiesen auf genau eine
`ToolExecution` und `FileObservation`; die Tabellen für `Agent`, `Work`,
`Edition` und `Series` blieben leer. Das OPF-Artefakt war persistent, das
ephemere Work-Verzeichnis nach Abschluss leer.

`W3-007` stellt unter `tests/fixtures/ebook_comparison/v1/` fünf synthetische
Items und fünf Szenarien bereit. Kontrolliert werden byte-identische Dateien,
eine Metadatenänderung bei gleichem normalisiertem Text, dieselbe `Edition` als
EPUB-/MOBI-Variante, eine Übersetzung als andere `Edition` desselben `Work` und
zwei widersprüchliche versionsgebundene Tool-Werte ohne kanonische Auswahl.
Die drei gezielten Fixture-Tests sowie der vollständige Stand mit Ruff, Mypy
für 64 Source-Dateien und 155 Pytest-Tests in 8 Minuten 25 Sekunden waren
lokal erfolgreich.

Der Implementierungscommit `352eb8567c542e709e77f98de42c222f21dd3f75`
von PR #17 bestand die GitHub-Actions-Runs `31844049430` und `31844093222`;
beide `quality`-Jobs waren nach jeweils 52 Sekunden erfolgreich.

`W3-008` implementiert `foliotone epub-validate` über den festen
`epubcheck-json/1`-Vertrag. Eine unveränderte EPUB-`FileObservation` wird mit
EPUBCheck 5.3.0 in einem privaten headless Java-Workspace geprüft. Der maximal
8 MiB große `EPUBCHECK_JSON`-Report bleibt privates `ToolArtifact`; persistierte
Evidence enthält nur `CONFORMANT`/`NONCONFORMANT`, fünf Severity-Counts und
aggregierte Severity-/Diagnosecode-Counts. Meldungstexte, Publication-Daten
und lokale Pfade erscheinen nicht in `ToolResult` oder CLI-Ausgabe.

ADR-0017 lässt für einen festen Adapter dokumentierte Nonzero-Domain-Exitcodes
zu, während der Standard `{0}` bleibt. EPUBCheck akzeptiert `{0, 1}`: Ein
Prüflauf mit Konformitätsfehlern ist ausführungsseitig `SUCCEEDED`, behält den
Exitcode und persistiert den negativen Befund getrennt. Fehlender oder
ungültiger Report, andere Exitcodes und Timeouts bleiben technische Fehler.

Temurin JRE 21.0.12+8 und EPUBCheck 5.3.0 wurden nur portabel und
SHA-256-verifiziert unter `C:\rep\cache\FolioTone` bereitgestellt. Der echte
CLI-Smoke-Test mit dem synthetischen EPUB persistierte bei Exitcode `1`
`NONCONFORMANT` und die drei Codes `PKG-006`, `PKG-007` und `RSC-005`. Die
Quelldatei blieb bytegleich und das Work-Verzeichnis leer. 15 Adaptertests und
37 gezielte Runtime-/Toolingtests bestanden; der gezielte Mypy-Lauf war
fehlerfrei.

Der vollständige W3-008-Stand bestand mit Python 3.12.10 lokal `ruff check .`,
Mypy für 66 Source-Dateien und alle 175 Pytest-Tests in 9 Minuten 23 Sekunden.

Der Implementierungscommit `e80b1d9cba28e2d883daaa2627b4fc0ef795d11c`
von PR #18 bestand die GitHub-Actions-Runs `31866746326` und `31866764769`;
beide `quality`-Jobs waren nach 58 beziehungsweise 50 Sekunden erfolgreich.

`foliotone ebook-cover` akzeptiert ausschließlich eine unveränderte EPUB-,
MOBI-, AZW- oder AZW3-`FileObservation`. Der feste
`calibre-debug-cover/1`-Helper wird über `calibre-debug -e` ausgeführt, kopiert
die Source in den privaten Workspace und übergibt nur diese Kopie an den
calibre-Reader. Gerenderte EPUB-Ersatzcover sind deaktiviert. Das erforderliche
JSON-Ergebnis enthält Status, Covergröße und Source-SHA-256; das optionale,
maximal 32 MiB große Raster bleibt privates `CALIBRE_EMBEDDED_COVER`-
`ToolArtifact`.

Pillow 12.3.x dekodiert nur JPEG, PNG, WebP oder GIF unter einer
40-Megapixel-Grenze. FolioTone normalisiert EXIF-orientiert in Graustufen auf
9 x 8 Pixel mit Lanczos und speichert einen versionierten horizontalen
64-Bit-`EBOOK_COVER_DHASH`. `NO_EMBEDDED_COVER` ist ein erfolgreicher Befund
ohne Fingerprint. Coverähnlichkeit bleibt unterstützende Evidence und ist kein
Identitätsbeweis.

Der echte CLI-Smoke-Test unter
`C:\rep\tmp\FolioTone\w3-009-smoke-01` verwendete zwei ausschließlich
synthetische EPUBs. Ein eingebettetes JPEG ergab `COVER_EXTRACTED`,
1240 x 1752 Pixel und dHash `4000000000000000`; das zweite EPUB ergab
`NO_EMBEDDED_COVER`. Beide Source-SHA-256 blieben unverändert. Die 13 neuen
Cover-Tests plus zwei Bootstrap-Tests, Ruff und Mypy für 69 Source-Dateien
waren lokal erfolgreich.

Der vollständige W3-009-Stand bestand mit Python 3.12.10 lokal
`ruff check .`, Mypy für 69 Source-Dateien und alle 188 Pytest-Tests in
11 Minuten 31 Sekunden. Das gebaute Wheel enthielt Adapter, dHash-Logik und
den paketierten calibre-Helper.

Der Implementierungscommit `a55b553445b223ea6219a522cdaafeff98165aa7`
von PR #19 bestand die GitHub-Actions-Runs `31871971678` und `31871990590`;
die beiden `quality`-Jobs waren nach 58 beziehungsweise 63 Sekunden
erfolgreich.

`foliotone ebook-analyze` verwendet das Profil
`ebook-analysis-workflow/v1`. EPUB wird nacheinander über Metadaten, Text,
Cover und EPUBCheck geführt; MOBI/AZW/AZW3 über Metadaten, Text und Cover; PDF
über die bestehende kombinierte Poppler-Analyse. Die Workflow-Schicht enthält
keine eigenen Parser oder Toolargumente. Sie erhält jede konkrete
ToolExecution und deren Evidence unverändert.

Alle für das konkrete Format notwendigen Adapter werden vor dem ersten Lauf
geprüft. Erwartete Adapterfehler oder fehlgeschlagene/abgebrochene
ToolExecutions stoppen unabhängige Folgeschritte nicht. Schrittzustände bleiben
als `SUCCEEDED`, `FAILED`, `CANCELLED` oder `ERROR` sichtbar; der Gesamtzustand
ist `SUCCEEDED`, `PARTIAL_FAILURE` oder `FAILED`. Nur vollständiger technischer
Erfolg liefert Exitcode 0. `NONCONFORMANT` ist weiterhin ein fachlicher
EPUBCheck-Befund innerhalb eines technisch erfolgreichen Schritts.

Die CLI druckt ausschließlich eine begrenzte Allowlist aus Zählern,
Statuswerten und Fingerprints sowie ToolExecution-ID/-Status/-Version. Rohe
Artefakte, Diagnosetexte und absolute Source-Pfade bleiben privat. Das
historische Profil `ebook-analysis-workflow/v1` erzeugt bei jedem Aufruf
frische Evidence. `W3-011` ersetzt diesen Default durch den nachfolgend
dokumentierten konservativen `v2`-Planer.

Die gezielte W3-010-Suite aus Workflow-, Bootstrap- und CLI-Integrationstests
bestand mit 18 Tests; Ruff und Mypy für 71 Source-Dateien waren erfolgreich.
Der echte Smoke unter `C:\rep\tmp\FolioTone\w3-010-smoke-01` führte zwei
ausschließlich synthetische EPUBs durch jeweils vier erfolgreiche Schritte.
Insgesamt wurden acht erfolgreiche ToolExecutions, 79 ToolResults und sieben
Fingerprints persistiert. `COVER_EXTRACTED` und `NO_EMBEDDED_COVER` blieben
getrennt; beide synthetisch unvollständigen EPUBs ergaben erwartbar
`NONCONFORMANT`. Beide Source-SHA-256 blieben unverändert, der ephemere
Work-Ordner war anschließend leer.

Der vollständige W3-010-Stand bestand mit Python 3.12.10 lokal
`ruff check .`, Mypy für 71 Source-Dateien und alle 204 Pytest-Tests in
11 Minuten 16 Sekunden. Das Wheel unter
`C:\rep\artifacts\FolioTone\w3-010-wheel-01` enthielt die beiden neuen
`foliotone.workflows`-Module; sein SHA-256 ist
`3ad24961dc47512721a06053ab40504b2534a8979effb9a43e713c4e501aff24`.

Der veröffentlichte Implementierungscommit
`2f8cb144617433855f51c39c4525603b9aa1004a` liegt in PR #20. Seine
GitHub-Actions-Runs `31874601676` (Push) und `31874615476` (Pull Request)
waren erfolgreich; die `quality`-Jobs einschließlich aller Docker-Smoke-Tests
liefen 62 beziehungsweise 59 Sekunden.

Der echte W3-011-Smoke unter
`C:\rep\tmp\FolioTone\w3-011-smoke-01` verwendete ausschließlich ein
synthetisches EPUB. Der Erstlauf erzeugte vier erfolgreiche ToolExecutions;
der identische Zweitlauf verwendete alle vier mit unveränderten IDs wieder.
Nach absichtlicher Beschädigung nur des privaten `CALIBRE_TEXT`-Artefakts lief
ausschließlich der Textschritt neu. `--fresh` führte danach alle vier Schritte
neu aus. Die Execution-Zählerfolge war 4, 4, 5, 9. Die Source-SHA-256 blieb
`41070cdea56904647215b069f15af3f6e46d6d94b81795974e247a337464b6ea`;
der ephemere Work-Ordner war leer. Verwendet wurden calibre 9.13, EPUBCheck
5.3.0 und Temurin JRE 21.0.12+8.

Der vollständige W3-011-Stand bestand lokal `ruff check .`, Mypy für 73
Source-Dateien und alle 216 Pytest-Tests in 11 Minuten 35 Sekunden. Das Wheel
`C:\rep\artifacts\FolioTone\w3-011-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`ab6064b05035a8cddd4f033a493c3f9d76ce43b37fe89dba5d790f142ad9e62e`
und enthält `ebook.py`, `evidence.py` und `reuse.py`.

Calibres dokumentiertes `calibre-debug --diff` startet ein GUI-Modul ohne
headless JSON-/Reportvertrag und wurde deshalb nicht adaptiert. Ein späterer
provider-neutraler Book-Diff soll persistierte Datei-, Text-, Metadaten-,
Struktur- und Cover-Evidence vergleichen. qpdf bleibt bis zu einem zusätzlichen
PDF-Struktur-Gap zurückgestellt.

## Aktuell implementiert

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
- FAILED-Erfassung bei fehlendem Tool und nicht adapter-akzeptiertem Exitcode;
- unveränderliche provider-spezifische `accepted_exit_codes`-Allowlist mit
  Standard `{0}` und Erhaltung des tatsächlich beobachteten Exitcodes;
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
- rohe OPF2-/OPF3-Beobachtungen unter `calibre_metadata`;
- provider-neutrale `ebook_metadata_candidate`-Ergebnisse unter dem
  versionierten Profil `ebook-metadata-candidate/v1`;
- stabile Gruppenpfade für Identifier-Namespace/-Wert,
  Contributor-Name/-Quelle/-MARC-Rolle/-Sortiername und Series-Name/-Position;
- direkte Kandidaten für Titel, Sprache, Verlag, Publikationsdatum, Subject,
  Beschreibung, Rechte, Typ, Titelsortierung und Rating;
- exakter `ToolExecution`-/`FileObservation`-Link ohne Anlage kanonischer
  `Agent`-, `Work`-, `Edition`- oder `Series`-Entitäten;
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

### Synthetischer E-Book-Vergleichskorpus

- Manifestversion `foliotone-ebook-comparison-fixture/v1` mit ausschließlich
  sicheren relativen Fixture-Pfaden;
- reproduzierbare SHA-256-Werte für Container-Surrogate und extrahierte
  Text-Artefakte;
- byte-stabile Git-Attribute für binäre Container-Surrogate und LF-normalisierte
  Text-Artefakte;
- produktiver `EBOOK_NORMALIZED_TEXT`-Fingerprint für Inhaltsvergleich;
- getrennte Ground Truth für `File`, normalisierten Inhalt, `Edition` und
  `Work`;
- gelabelte `RelationType`-Erwartungen für spätere W6-Kalibrierung;
- versionsgebundene synthetische Tool-Beobachtungen, die bei Widerspruch
  erhalten bleiben und keinen kanonischen Wert erzeugen;
- keine Matching Engine, kein Scoring, keine automatische Review-Entscheidung
  und keine zusätzliche Produktoberfläche.

### EPUBCheck-Strukturvalidierung

- `EpubCheckAnalyzer` und CLI `foliotone epub-validate`;
- ausschließlich unveränderte EPUB-`FileObservation`-Eingaben;
- `ToolCapability.STRUCTURAL_VALIDATION` und Adapterversion
  `epubcheck-json/1`;
- feste headless Java/JAR-Befehlsform ohne caller-kontrollierte
  EPUBCheck-Optionen;
- EPUBCheck 5.3.0 als Mindestversion;
- JVM-Tempdaten und Report ausschließlich im ephemeren Tool-Workspace;
- maximal 8 MiB großes privates, integritätsgeprüftes
  `EPUBCHECK_JSON`-Artefakt und höchstens 10.000 Meldungen;
- `CONFORMANT`/`NONCONFORMANT`, fünf Severity-Counts und aggregierte
  Diagnosecode-Counts mit exaktem Execution-/Observation-Link;
- keine Meldungstexte, Publication-Metadaten oder lokalen Pfade in
  `ToolResult` und CLI-Ausgabe;
- `{0, 1}` als feste akzeptierte Exitcodes, wobei ein Konformitätsfehler
  Evidence und kein technischer Prozessfehler ist;
- kein calibre-GUI-Diff-Adapter und kein qpdf-Adapter ohne zusätzlichen
  maschinenlesbaren Vergleichs- oder PDF-Strukturbedarf.

### calibre-Embedded-Cover und FolioTone-dHash

- `CalibreCoverAnalyzer` und CLI `foliotone ebook-cover`;
- feste EPUB/MOBI/AZW/AZW3-Allowlist unter `ToolCapability.FINGERPRINT`;
- paketierter `calibre-debug -e`-Helper mit privater Source-Kopie, ohne
  `ebook-meta`-Setter oder caller-kontrollierte Python-/calibre-Argumente;
- deaktivierte gerenderte EPUB-Ersatzcover und explizites
  `NO_EMBEDDED_COVER` ohne Fingerprint;
- erforderliches, maximal 1 KiB großes JSON-Ergebnis mit Source-SHA-256 sowie
  erneuter Digest-Prüfung nach dem Lauf;
- optionales, maximal 32 MiB großes privates
  `CALIBRE_EMBEDDED_COVER`-Artefakt;
- Pillow-12.3-Rasterdekodierung für JPEG/PNG/WebP/GIF mit
  Decompression-Bomb- und 40-Megapixel-Grenze;
- EXIF-orientierter 9-x-8-Graustufen-Lanczos-Normalisierer und versionierter
  horizontaler 64-Bit-`EBOOK_COVER_DHASH`;
- Coverähnlichkeit ausschließlich als unterstützende Evidence, ohne
  automatische Datei-/`Edition`-/`Work`-Identität.

### Einheitliche E-Book-Analyse

- `EbookAnalysisOrchestrator` und CLI `foliotone ebook-analyze`;
- aktuelles Profil `ebook-analysis-workflow/v2` und feste Allowlist EPUB/MOBI/AZW/AZW3/PDF;
- ausschließlich Komposition der bestehenden calibre-, EPUBCheck- und
  Poppler-Adapter, ohne neue Toolargumente oder Parser;
- Format-Routing: EPUB vier Schritte, MOBI/AZW/AZW3 drei Schritte, PDF ein
  Adapterergebnis mit zwei getrennten ToolExecutions;
- Fortsetzung unabhängiger Schritte nach erwarteten Adapter-/Toolfehlern;
- explizite Schritt- und Gesamtzustände sowie Exitcode 0 nur bei vollständig
  technisch erfolgreicher Analyse;
- begrenzte CLI-Zusammenfassung ohne rohe Artefakte, Diagnosetexte oder
  absolute Source-Pfade;
- nicht persistierender read-only Versionsprobe vor Wiederverwendung;
- exakter Vergleich von Provider, Tool-Version, Adapter, Capability,
  FileObservation-Input und Konfigurationsidentität;
- ausschließlich neuester exakt passender erfolgreicher Lauf; ein neuerer
  fehlgeschlagener exakter Versuch erzwingt Retry;
- adapter-spezifische Größen-/SHA-256-Prüfung jedes Pflichtartefakts und
  deterministische Rekonstruktion der persistierten Ergebnisse/Fingerprints;
- `REUSED`/`EXECUTED` je Schritt und `--fresh` zum vollständigen Bypass;
- atomarer PDF-Workflow-Schritt: Beide getrennten Poppler-Ausführungen werden
  gemeinsam wiederverwendet oder gemeinsam neu ausgeführt.

### Persistence

- Alembic `0002_incremental_index` ergänzt Scan-Events, Tool-Artefakte und W2-Indizes;
- Alembic `0003_deletion_confirmation` ergänzt die persistente Abwesenheitsserie;
- Alembic `0004_relocation_candidates` ergänzt persistente Relocation-Kandidaten;
- Alembic `0005_scan_resume_lineage` ergänzt `scan_runs.resumed_from_run_id` und den zugehörigen Index.

Bereits gemergte Migrationen werden nicht rückwirkend verändert.

## Danach weiterarbeiten

Die nächste sinnvolle Reihenfolge ist:

1. `W3-012` — ein versioniertes E-Book-Qualitätsprofil getrennt von
   Datei-/`Edition`-/`Work`-Identität implementieren.
2. `W3-013` und `W3-014` — provider-neutralen Book-Diff sowie erweiterte
   synthetische Edge-/Performance-/Distanz-Fälle umsetzen.

Music W4 bleibt geplant, wird aber erst nach der E-Book-Vertiefung und den
book-spezifischen Teilen von Authority Resolution, Matching, Review und
Calibre-Library-Reconciliation fortgesetzt.

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
