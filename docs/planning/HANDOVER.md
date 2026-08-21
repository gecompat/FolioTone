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
Schritt-Retry und `--fresh`. `W3-012` ergänzt das separate versionierte
E-Book-Qualitätsprofil mit fünf Dimensionen und festen Befundcodes.
`W3-013` ergänzt den provider-neutralen read-only Evidence-Paarvergleich ohne
Relation oder Identitätsurteil. `W3-014` ergänzt den vollständig synthetischen
v2-Edge-Korpus und begrenzte, indexgestützte Evidence-Abfragen. `W3-015`
ergänzt die fortsetzbare Collection-Analyse über einen persistenten Snapshot-
Plan, begrenzte Worker und per-File-Fehlerfortsetzung. `W3-016` ergänzt
deterministische private Collection-Berichte, persistierte Befundprovenance
und begrenzte Duplicate-/Varianten-Kandidaten ohne Identitätsurteil. Auf
Benutzerentscheidung bleibt die Entwicklung bis zur Reife der E-Book-Pipeline
bei E-Books; `W3-017` einschließlich des E5-Performance-/Restart-Vertrags ist
abgeschlossen. Die lokalen Authority-Grundlagen, strukturierten Provider-
Verträge und E-Book-Klassifikationsverträge wurden mit `PR #36` bis `PR #39`
auf `main` integriert. EB-01/E4 ergänzt die gemeinsame Root-Write-Lease aus
ADR-0027 und Migration `0012`; Scan, Kandidaten-Hashing, Collection-Analyse
und Einzelanalyse sind damit für denselben `ScanRoot` atomar gefencet. Reale
Provider, Matching und die späteren Classification-/Relation-Review-Slices
bleiben offen. EB-02 ergänzt persistierte book-only Resolution Candidates,
Evidence-Links und append-only Authority-Entscheidungen. Music W4 bleibt
zurückgestellt.

Der reale `W3-017`-Scan zeigte zusätzlich einen Lifecycle-Gap: Ein externer
harter Prozessabbruch kann den Cleanup umgehen und einen `ScanRun` als
`RUNNING` hinterlassen. ADR-0025 und Alembic `0009_scan_run_leases` ergänzen
deshalb 30-Minuten-Leases, Heartbeats und eine explizite atomare Recovery für
abgelaufene oder aus älteren Versionen stammende ungeleaste Läufe.

Die per-Run-Leases bleiben zusätzliche Laufzeitbelege. Die gemeinsame
`scan_root_write_leases`-Tombstone-Zeile ist seit EB-01 das maßgebliche
Cross-Workflow-Fence. Migration `0012` darf nur bei vollständig ruhenden
Scan-, Candidate-Hash- und Collection-Writern ausgeführt werden; ungefencte
Legacy-`RUNNING`-Zustände werden nicht automatisch übernommen.

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

### Archive-Extraction-Fortsetzung

S-EBAR-05A, S-EBAR-06A und S-EBAR-04Q sind auf `main` abgeschlossen. ADR-0049
entscheidet FG-A-EXTRACTION-QUOTA als dateisystemneutrale, atomar begrenzte
Workspace-Capability. FolioTone erhält keine Mount-, Device-, `root`- oder
`CAP_SYS_ADMIN`-Authority.

[ADR-0050](../decisions/ADR-0050-linux-docker-workspace-backend-unavailable.md)
schließt FG-A-WORKSPACE-BACKEND negativ und fail-closed ab: Für den
kombinierten Byte-, Objekt-, Reserve- und Consumer-Lifecycle ist noch kein
unprivilegiert live attestierbares Linux-/Docker-Backend belegt. Die
Adapter-Allowlist bleibt leer. S-EBAR-04A, EBAR-06 und jede reale Extraction
bleiben `TOOL_UNAVAILABLE`. Ein späteres docs-only
FG-A-WORKSPACE-BACKEND-REVALIDATION beginnt erst mit einem konkreten
administrativ vorprovisionierten Backend und einem echten Linux-/Docker-
Conformancehost; es autorisiert selbst noch keine Implementierung.

[ADR-0051](../decisions/ADR-0051-bounded-archive-wrapper-streaming.md)
schließt FG-A-WRAPPER-PIPELINE für eine unabhängige read-only Strecke ab.
S-EBAR-W01 bis S-EBAR-W04 sind abgeschlossen und implementieren
TAR-Rahmenprüfung, bounded Duplex-Containerstreaming, Providerintegration und
den fokussierten Abschluss. Die Wrapperstrecke erzeugt weder
Extraction-Handoff noch Persistenz oder Schreiboperationen.

[ADR-0052](../decisions/ADR-0052-immutable-archive-evidence-persistence.md)
und ADR-0053 sind mit S-EBAR-07, S-EBAR-08A bis 08D und EBAR-09 umgesetzt.
[ADR-0054](../decisions/ADR-0054-archive-aware-matching-frontier.md) schließt
danach FG-A3-MATCHING. Als Nächstes implementiert S-EBA3-01 ausschließlich
den reinen Source-Dependency-Vertrag. Member-Byte-Identity bleibt ohne
vollständige Member-SHA-256 `UNKNOWN`; Extraction, Secrets und
Source-Mutationsauthority bleiben gesperrt.

### `W3-017` (E5 synthetischer Performance-/Restart-Vertrag)

Die E5-Verifikation wurde auf Testebene ergänzt: neue synthetische
Skalierungs- und Restart-Szenarien prüfen genau eine Kandidatenmaterialisierung
pro Invocation, den Einsatz des `ix_fingerprints_target_profile_id_value`-Indexes
in der Kandidatenabfrage sowie deterministisches Fortschreiten mit `max_items`
und anschließendem Wiederaufnahme-Lauf.

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

Der W3-011-Implementierungscommit
`2f08bcc4f3b13517ec70e92e3eb25416ce56e6e4` liegt in PR #21. Seine
GitHub-Actions-Runs `31886119562` (Push) und `31886140176` (Pull Request)
waren erfolgreich; die `quality`-Jobs einschließlich aller Docker-Smoke-Tests
liefen 56 beziehungsweise 63 Sekunden.

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
- interaktiver pfadfreier Scan-Fortschritt auf `stderr`, mit
  `--progress`/`--no-progress` ausdrücklich steuerbar;
- begrenzte Batch-Verarbeitung;
- set-orientierte `FileRecord`-/`FileObservation`-/`FileEvent`-Persistenz je Discovery-Batch;
- 1 bis 8 begrenzte Hash-Worker über `--hash-workers`; `auto` verwendet
  standardmäßig höchstens die Hälfte der sichtbaren CPU-Anzahl;
- atomare Fingerprint-Persistenz je Discovery-Batch;
- sauberer CLI-Abbruch mit Exitcode 130, persistentem `INTERRUPTED` nach
  Run-Start und kooperativem Abbruch aktiver In-Process-Hashreads;
- isolierte Hash-I/O-Teilfehler mit selektivem Retry im nächsten Scan;
- persistente Abwesenheitsserie über `missing_since_at` und `consecutive_missing_scans`;
- persistente `FileRelocationCandidate`-Records für eindeutige NEW/erstmalig-MISSING Fingerprint-Paare im selben erfolgreichen Scan.

### `DELETED`-Policy

`DeletionConfirmationPolicy` ist standardmäßig nicht aktiv. Bei expliziter Aktivierung müssen sowohl eine konfigurierte Anzahl aufeinanderfolgender erfolgreicher `MISSING`-Scans als auch eine konfigurierte Mindestdauer erfüllt sein. Failed oder interrupted Scans erhöhen die Serie nicht. Ein bestätigtes `DELETED` erzeugt keine Filesystem-Operation. ADR-0013 ist verbindlich.

### Relocation-Kandidaten

`FileRelocationCandidate` ist zusätzliche Evidence, keine bestätigte File-Identität. Source bleibt ein eigener `MISSING`-Record und Target ein eigener `NEW`-Record. Kandidaten werden nur innerhalb desselben `ScanRoot` und Scans aus eindeutigen versionierten `QUICK_FILE`-/`FILE_SHA256`-Blöcken gebildet. ADR-0014 ist verbindlich.

### Interrupt/Resume

Resume wird als neuer `ScanRun` modelliert. `resumed_from_run_id` verweist auf
den persistierten `INTERRUPTED`-Vorgänger desselben `ScanRoot`. Discovery läuft
erneut vollständig und streaming-basiert; ein persistenter `os.scandir`-Cursor
wird bewusst nicht verwendet. Vollständige Hash-Evidence der jeweils jüngsten
unveränderten Observation wird auf die neue Observation projiziert, ohne die
Source erneut zu öffnen. Nur eine dort fehlende Evidence wird gezielt
nachgehasht; stale ältere Hashes werden nicht übersprungen. Erst ein vollständig
erfolgreicher Resume-Run darf `MISSING`/`DELETED` klassifizieren. ADR-0015 ist
verbindlich.

Neue Scan-Invocations besitzen zusätzlich eine Lease. Der Scanner erneuert sie
vor und nach begrenzten Discovery-/Hash- und Abschlussphasen. Nach einem
nachweislich beendeten Prozess setzt `--recover-stale-running` nur den neuesten
ungeleasten oder abgelaufenen `RUNNING`-Lauf desselben `ScanRoot` atomar auf
`INTERRUPTED` und startet danach den normalen Resume-Vertrag. Eine aktive Lease
blockiert die Übernahme. ADR-0025 ist verbindlich.

### Hashing

- NONE, QUICK und FULL;
- Quick Fingerprint mit begrenztem Datei-I/O;
- vollständiges SHA-256 als Streaming-Hash;
- Fingerprints gegen konkrete `FileObservation`;
- kein unnötiges Rehashing unveränderter Dateien, auch nicht bei Resume bereits verarbeiteter unveränderter Files;
- fehlende jüngste Hash-Evidence wird selektiv ergänzt;
- atomare Fingerprint-Batches und ausdrücklich begrenzte Hash-Parallelität.

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
- aktuelles Profil `ebook-analysis-workflow/v3` und feste Allowlist EPUB/MOBI/AZW/AZW3/PDF;
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
- separate, deterministische Projektion `ebook-quality/v1` ohne zusätzlichen
  Toollauf oder Persistenzmigration;
- `EbookQualityAssessment` mit stabil geordneten Dimensionen `METADATA`,
  `TEXT`, `COVER`, `STRUCTURE` und `FORMAT_RISK`;
- feste Befundcodes mit exakten verfügbaren ToolExecution-IDs sowie getrennte
  Zustände `INCOMPLETE`, `REVIEW` und `ACTION_REQUIRED`;
- kein skalarer Quality Score, keine Identitätsableitung und keine Änderung der
  technischen `ebook-analyze`-Exitcodes durch Qualitätsbefunde.

**Empirisch für W3-012:** Der echte CLI-Smoke mit der synthetischen EPUB unter
`C:\rep\tmp\FolioTone\w3-011-smoke-01` verwendete alle vier vorhandenen
ToolExecutions wieder und erzeugte keinen neuen Lauf. `ebook-quality/v1`
meldete `TEXT_VERY_SHORT` und `EPUB_VALIDATION_ERRORS` als
`ACTION_REQUIRED`; der technische Workflow blieb `SUCCEEDED`. Die Source-
SHA-256 blieb
`41070cdea56904647215b069f15af3f6e46d6d94b81795974e247a337464b6ea`, der
Work-Ordner blieb leer und der ToolExecution-Zähler blieb bei neun.

Der vollständige W3-012-Stand bestand mit Python 3.12.10 lokal
`ruff check .`, Mypy für 74 Source-Dateien und alle 222 Pytest-Tests in
9 Minuten 23 Sekunden. Das Wheel unter
`C:\rep\artifacts\FolioTone\w3-012-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`a02e033db35e6e2acfe0d374961597e257e3070198bb3f503854425a17a95457` und
enthält `foliotone/workflows/quality.py`.

### Provider-neutraler E-Book-Evidence-Vergleich

- `EbookComparisonService`, Profil `ebook-comparison/v1` und CLI
  `foliotone ebook-compare`;
- ausschließlich persistierte Evidence zweier expliziter FileObservation-IDs,
  ohne Source Root, Medienzugriff oder neuen Toollauf;
- stabil geordnete Dimensionen `FILE_BYTES`, `NORMALIZED_TEXT`, `METADATA`,
  `STRUCTURE` und `COVER`;
- getrennte Dimension States und Evidence-Coverage statt Matchscore oder
  Identitätsentscheidung;
- vollständige Datei-SHA-256 und kompatible versionierte Text-/Cover-
  Fingerprints; `QUICK_FILE` genügt nicht für Bytegleichheit;
- Metadatenvergleich über provider-neutrale Feldkandidaten, mit Feldpfaden und
  Counts statt rohen Werten;
- Ausschluss des empirisch volatilen internen `identifier.calibre` aus dem
  bibliografischen Vergleich bei unveränderter Raw-Evidence;
- EPUB-Strukturvergleich über Konformität, Severity-Counts und Diagnostic-
  Codes; Cover-dHash-Distanz ohne Ähnlichkeitsschwelle;
- neueste Ausführung je Provider/Capability; ein neuerer fehlgeschlagener Lauf
  verhindert die Verwendung älterer Evidence desselben Providers;
- keine persistierte `Relation`, Confidence, Review-Entscheidung oder
  kanonische Metadaten.

**Empirisch für W3-013:** Die fünf gezielten Korpus-, CLI- und Bootstrap-Tests
waren erfolgreich; Ruff und Mypy für 75 Source-Dateien waren ebenfalls
erfolgreich. Der vollständige Stand bestand alle 225 Pytest-Tests in
13 Minuten 27 Sekunden. Der echte CLI-Smoke unter
`C:\rep\tmp\FolioTone\w3-013-smoke-01` analysierte zwei bytegleiche
synthetische EPUB-Kopien in insgesamt acht erfolgreichen ToolExecutions.
`ebook-compare` meldete `COMPLETE` und fünfmal `SAME`. Beide Source-SHA-256
blieben
`41070cdea56904647215b069f15af3f6e46d6d94b81795974e247a337464b6ea`, der
Work-Ordner blieb leer und es wurde keine Relation persistiert. Das Wheel unter
`C:\rep\artifacts\FolioTone\w3-013-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`985e84dbf06e8bcad2e23468af3cd096a6ef9c0469300ae357a016854da669fe` und
enthält `foliotone/workflows/comparison.py`.

### Persistence

- Alembic `0002_incremental_index` ergänzt Scan-Events, Tool-Artefakte und W2-Indizes;
- Alembic `0003_deletion_confirmation` ergänzt die persistente Abwesenheitsserie;
- Alembic `0004_relocation_candidates` ergänzt persistente Relocation-Kandidaten;
- Alembic `0005_scan_resume_lineage` ergänzt `scan_runs.resumed_from_run_id` und den zugehörigen Index.
- Alembic `0006_ebook_evidence_lookup_indexes` ergänzt drei additive Indizes für begrenzte Observation-Evidence-Abfragen.
- Alembic `0007_ebook_collection_batches` ergänzt fortsetzbare Collection-
  Runs und Items mit Root-/Status- und Run-/Status-/Ordinal-Indizes, ohne
  Pfade oder Metadatenwerte in den Batch-Tabellen zu speichern.
- Alembic `0008_ebook_collection_reports` ergänzt geordnete Item-Ausführungen,
  Quality-Befunde, deren exakte `ToolExecution`-Quellen und den belegten
  Fingerprint-Gruppierungsindex, weiterhin ohne Source-Pfade oder Inhalte in
  den Collection-Tabellen.
- Alembic `0009_scan_run_leases` ergänzt nullable Lease-Felder und einen
  Root-/Status-/Lease-Index für sichere Heartbeats und explizite Recovery
  verwaister Scans.

### Begrenzter Evidence-Lesepfad und synthetischer v2-Korpus

- `load_observation_evidence()` lädt ausschließlich Records expliziter
  `FileObservation`-IDs und führt keinen collection-weiten `list_all()`-Read
  aus;
- Paarvergleich und exakte Collection-Evidence-Wiederverwendung teilen diesen
  indexgestützten Lesepfad; Reuse fordert genau eine Observation sowie
  höchstens 64 Artefakte der ausgewählten Ausführung an;
- feste `LIMIT maximum + 1`-Grenzen schützen `ToolExecution`, `ToolResult`
  und `Fingerprint` vor unbeschränkter Historienladung;
- eine Überschreitung erzeugt einen technischen Fehler ohne Full-Table-
  Fallback;
- der v2-Korpus ergänzt AZW, AZW3, PDF, Sparse-/Malformed-Evidence und
  Cover-dHash-Distanzen 0/1/8/32/64;
- der Skalierungstest verwendet 10.000 synthetische Fremdrecords je Evidence-
  Tabelle und bestätigt genau drei gefilterte, indexgestützte Reads;
- 12 gezielte Tests bestanden in 2 Minuten 39 Sekunden; Ruff, Mypy für 77
  Source-Dateien und alle 229 Pytest-Tests in 15 Minuten 46 Sekunden waren
  erfolgreich.
- das gebaute Wheel unter
  `C:\rep\artifacts\FolioTone\w3-014-wheel-01` hat SHA-256
  `8c39c43917d55fbd7e241cc6b4610afc64642a0f5b92b3032f8f92fc8605a3a3`
  und enthält Query-Modul, Migration und Vergleichsworkflow.

### Fortsetzbare E-Book-Collection-Analyse

- `EbookCollectionService`, Profil `ebook-collection-analysis/v1` und CLI
  `foliotone ebook-collection-analyze`;
- unveränderlicher Plan aus dem neuesten `COMPLETED`-`ScanRun` eines
  aktivierten EBOOK-`ScanRoot`;
- ausschließlich aktuelle `PRESENT`-Beobachtungen mit exakt gleichem relativem
  Pfad, Größe und Änderungszeitpunkt für EPUB/MOBI/AZW/AZW3/PDF;
- im Default genau ein gestreamter Plan-Read mit höchstens 500 Items je
  Insert-Batch und optionalem `--plan-limit` für globale deterministische
  Piloten;
- alternativ `--plan-per-format N` für höchstens N stabil sortierte Items je
  vorhandenem unterstütztem Format; gegenseitig exklusiv zu `--plan-limit`;
- persistente Lease, 1 bis 8 Worker, höchstens zwei beanspruchte Workerwellen
  und 30-Sekunden-SQLite-`busy_timeout`;
- kontrollierte Teil-Invocation über `--max-items` sowie Resume desselben Plans
  über `--resume-run`, ohne abgeschlossene Items zu wiederholen;
- exakte Evidence-Wiederverwendung oder `--fresh` für den gesamten neuen Lauf;
- per-File-Fehlerfortsetzung mit pfadfreien Fehlercodes und begrenzten
  Analyse-/Quality-Zählern;
- prozesslokaler thread-sicherer Versionsprobe-Cache ausschließlich im
  Batch-Modus;
- keine Source-Media-Mutation, keine `Relation`, keine Confidence und keine
  kanonischen Metadaten.

Sieben Batch-Integrationstests bestanden in 1 Minute 20 Sekunden. Der
Skalierungsfall bestätigt einen Plan-SELECT und Insert-Batches von 500, 500
und 201 für 1.201 synthetische Beobachtungen. Fünf CLI-/Bootstrap-Tests
bestanden in 28 Sekunden und prüfen Teil-Invocation, Resume, path-freie
Ausgabe, unveränderte Source-Dateien und getrennte beschreibbare Runtime-Pfade.
Der verfeinerte Tool-Versionsprobe-Cache bestand seinen gezielten
Parallelitätstest. ADR-0021 dokumentiert den Vertrag.

Der vollständige W3-015-Stand bestand mit Python 3.12.10 lokal
`ruff check .`, Mypy für 82 Source-Dateien und alle 239 Pytest-Tests in
18 Minuten 43 Sekunden. Der JUnit-Bericht liegt unter
`C:\rep\artifacts\FolioTone\w3-015-test-results\pytest-full.xml`. Das Wheel
`C:\rep\artifacts\FolioTone\w3-015-wheel-01\foliotone-0.1.0-py3-none-any.whl`
ist 134.583 Byte groß, hat SHA-256
`3a4d98aa852769c83dc2019f1e986cbacd41931ec38558f38b02ef6b3fd99a2e`
und enthält Collection-Domainmodell, Persistenz, Workflow und Migration
`0007_ebook_collection_batches`.

Commit `9a6b2d1ace10b1ef57c4402439ba782ede233b04` bestand in PR #25 den
vollständigen Remote-Gate mit Ruff, Mypy, 239 Pytest-Tests und allen Docker-
Smokes. Merge-Commit `fe3672a7002137859607dacb12072eeae35e268a` und GitHub
Actions Run `31900550819` auf `main` waren erfolgreich. Der anschließend
versionierte CI-Vertrag führt die Vollsuite nur am PR oder manuell aus; ein
`main`-Push erhält nur den kurzen Merge-/Whitespace-Vertrag.

### Deterministischer privater Collection-Bericht

- `EbookCollectionReportService`, Profil `ebook-collection-report/v1` und CLI
  `foliotone ebook-collection-report`;
- konsistenter read-only Snapshot eines persistierten, nicht mehr `RUNNING`
  befindlichen Collection-Laufs ohne Source-Media- oder Toolzugriff;
- vollständige Format-, Analyse-, Quality- und Befundzähler sowie begrenzte,
  priorisierte Review-Items mit exakten verfügbaren `ToolExecution`-Quellen;
- Exact-Duplicate-Kandidaten für gleiche vollständige `FILE_SHA256`-Werte und
  Content-Variant-Kandidaten für gleichen normalisierten Text bei
  unterschiedlichen vollständigen Datei-Hashes;
- sortierte Streaming-Abfragen mit `fetchmany(500)`, begrenzte Top-Gruppen und
  explizite Gesamt-/Truncation-Angaben;
- byte-stabile private JSON-/CSV-/Checksum-Artefakte in einem
  inhaltsadressierten Verzeichnis außerhalb des Source Root;
- keine rohen Fingerprints, keine `Relation`, keine Confidence und keine
  Identitätsentscheidung.

Der einzelne umfassende Berichtstest bestand nach der finalen
Projektionsprüfung in 21,33 Sekunden; der direkt
betroffene Head-Migrationstest bestand in 19,38 Sekunden. Ruff war für die
geänderten Source-/Testdateien erfolgreich, Mypy für 85 Source-Dateien. Ein
erneuter vollständiger lokaler Pytest-Lauf wurde bewusst nicht dupliziert. Der
CI-Vertrag verlangt genau einen vollständigen `quality`-Lauf am Pull Request
und nach dem Merge nur den kurzen `post-merge-contract`. Commit
`0237861bb1a02455fa65d2a5f754e46bb4530d92` wurde über PR #26 als
`111267f8a3c66e629cfd4b61d006c1731a9d9b12` gemergt; der Main-Lauf
`31900986647` benötigte für den Post-Merge-Job drei Sekunden.

Das Wheel
`C:\rep\artifacts\FolioTone\w3-016-wheel-01\foliotone-0.1.0-py3-none-any.whl`
ist 147.477 Byte groß, hat SHA-256
`7b69ea169d1f07adfe1780a4acc91ee19ef6298b51237c45dc85142a164a0482`
und enthält Report-Query, Workflow, CLI-Anbindung und Migration `0008`.

Bereits gemergte Migrationen werden nicht rückwirkend verändert.

### Reale Collection-Härtung und selektive Duplikatbestätigung

- unveränderte Scan-Observationen übernehmen vollständige jüngste
  Hash-Evidence ohne erneuten Source-Read; fehlende Evidence wird selektiv
  ergänzt;
- 1 bis 8 begrenzte Hash-Worker, set-orientierte Indexwrites und atomare
  Fingerprint-Batches beseitigen die gemessenen Persistenzengpässe;
- per-File-Hash-I/O-Fehler bleiben isoliert und werden durch den nächsten
  normalen Scan ausschließlich für die fehlenden Objekte erneut versucht;
- `--plan-per-format N` ergänzt einen gegenseitig exklusiven,
  formatabdeckenden Pilotmodus neben dem globalen `--plan-limit`;
- `ebook-duplicate-hash/v1` und `foliotone ebook-hash-candidates` berechnen
  vollständiges SHA-256 nur für aktuelle Mitglieder mehrfach belegter
  `QUICK_FILE`-Gruppen ohne vorhandenen Vollhash;
- der reale Vollhashlauf belegte eine wiederholte historische
  Fingerprint-Aggregation als mehrstündigen SQL-Engpass; die Auswahl schränkt
  nun zuerst auf den aktuellen Scan ein und materialisiert genau einen
  verbindungslokalen Temp-Snapshot pro Invocation;
- der gemessene Index `ix_fingerprints_target_profile_id_value`, stabile
  Temp-Keyset-Batches, `--max-items`, 1 bis 8 Worker und atomare Writes machen
  die Duplikatbestätigung begrenzt und durch denselben Aufruf fortsetzbar;
- pfadfreie, sofort geleerte Phasen- und Batch-Ausgaben machen auch die
  Kandidatenauswahl und den Migrationsschritt beobachtbar;
- `ebook_candidate_hash_runs`, eine rootweite partielle Active-Run-
  Eindeutigkeit und ein separater Lease-Keeper verhindern konkurrierende
  Kandidaten-Hashläufe und halten auch lange Einzelhashes lebendig;
- Fingerprint-Insert und Fortschrittszähler werden pro Batch in derselben
  gefenceten Transaktion persistiert; ein stale übernommener Vorgänger kann
  keine nachträgliche Evidence schreiben;
- `foliotone ebook-hash-status` liest Run-ID, Phase, Heartbeat, Lease-Ablauf
  und Zähler pfadfrei über SQLite `mode=ro`, erzeugt keine Verzeichnisse und
  migriert die Datenbank ausdrücklich nicht; der optionale JSON-Vertrag gibt
  nur freigegebene IDs, Zeitpunkte, Lease-Zustand und Zähler aus;
- Observation-Prüfung vor und nach dem Hash verhindert, dass inzwischen
  veränderte Source-Dateien falsche Evidence erhalten;
- ein privater read-only Vierformat-Pilot bestätigte reale EPUB-, PDF-, AZW3-
  und MOBI-Verarbeitung sowie exakte Evidence-Wiederverwendung, ohne private
  Pfade, Inhalte oder Sammlungskennzahlen in Git zu übernehmen.
- `ebook-inventory-report/v1` und `foliotone ebook-inventory-report` erzeugen
  aus dem neuesten abgeschlossenen Scan ohne Source-Zugriff vollständige
  Format-/Byte-Summen, Hash-Abdeckung, offene Quick-Kandidaten und exakte
  Duplikatsummen;
- Gruppen-/Mitgliederlimits begrenzen private Pfaddetails, während vollständige
  Summen und Kürzungsmarker erhalten bleiben; rohe Hashwerte, Relation,
  Keep-Präferenz und Identitätsurteil werden nicht ausgegeben.
- `foliotone ebook-postscan-verify` prüft den paketierten Alembic-Head,
  Source-Scan- und Kandidaten-Hash-Lineage, bytegenaue Inventarartefakte sowie
  die begrenzte Formatabdeckung eines expliziten `EbookCollectionRun` über
  dieselbe echte Read-only-Verbindung und öffnet keine Source Media;
- 25 gezielte CLI-, Resume-, Lease-, Migrations-, Persistenz- und
  Dokumentationsvertrags-Tests bestanden; Ruff und der gezielte Mypy-Lauf waren
  ohne Befund. Der vollständige Gate bleibt dem Pull Request vorbehalten.
- 26 gezielte Kandidaten-Hash-Lease-, Status-, Migrations-, Persistenz- und
  Dokumentationsvertrags-Tests bestanden in 3 Minuten 56 Sekunden. Sie decken
  konkurrierende Besitzer, root-parallele Läufe, stale Takeover, atomaren
  Batch-Rollback und die read-only Statusabfrage ab; Ruff und der gezielte
  Mypy-Lauf waren ohne Befund.
- 30 gezielte Persistenz-, Lease-, Kandidaten-Hash-, Collection- und
  Postscan-Verifikationstests bestanden in 7 Minuten 2 Sekunden. Sie decken
  echte Read-only-Verbindungen, lange Einzelhashes, Keeper-Ausfall,
  `KeyboardInterrupt`, harten synthetischen Prozessabbruch und die
  Abschlusszustände `COMPLETE`, `PENDING`, `DEGRADED` und `INVALID` ab. Nach
  der dynamischen Bindung an den paketierten Alembic-Head bestanden die fünf
  direkt betroffenen Tests erneut in 43,48 Sekunden; Ruff und Mypy waren ohne
  Befund.

ADR-0015, ADR-0021, ADR-0023, ADR-0024 und ADR-0025 dokumentieren die
verbindlichen Resume-, Lease-, Plan-, Hash- und Inventarverträge. Die
vollständige lokale Testsuite wird nicht während jeder Iteration wiederholt;
gezielte Source-/
Integrationstests laufen während der Entwicklung, der vollständige Gate genau
einmal am Pull Request.

Die gezielte Performance-Verifikation bestand 13 Kandidaten-, Migrations-,
Query-Plan- und Dokumentationsvertrags-Tests in 1 Minute 28 Sekunden. Ruff und
der gezielte Mypy-Lauf waren ohne Befund. Ein zusätzlicher synthetischer Lauf
mit 100.000 historischen Quick-Fingerprint-Zeilen materialisierte genau eine
aktuelle Gruppe und verarbeitete zwei Batchgrößen-1-Kandidaten in 0,395
Sekunden. Private Collection-Pfade oder Laufzeitkennzahlen wurden nicht in Git
übernommen.

## Danach weiterarbeiten

Die langfristige E-Book-Folgestrecke für Archive und einen vollständigen
Deduplizierungsworkflow steht in
[`EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md`](EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md).
Sie beginnt mit Toolbewertung, read-only Archiv-/Volume-/Sidecar-Inventar und
lokalen Passwortkandidaten aus Containerkommentaren sowie
begrenzten NFO-/TXT-/DIZ-/INFO-/URL-/HTML-/SFV-/README-Quellen. Der vom
Benutzer genannte Name `Newzcrabber` ist vor einer Providerplanung zunächst
einer konkreten dokumentierten Schnittstelle zuzuordnen. Online-Recherche
bleibt getrennt aktivierbar und darf weder Pfade noch Passwortmaterial loggen.
W9 erzeugt nur nicht ausführbare Pläne; jede Quarantäne-, Lösch- oder
Verzeichnisoperation bleibt W10-blockiert.

EB-07 und EB-08 sind abgeschlossen. ADR-0034 ist vollständig umgesetzt;
S-EB08-01 bis S-EB08-09 sowie W9 sind `DONE`. `foliotone.consolidation`
liefert immutable DTOs, `canonical-json/v1`, reine Preconditions und Blocker,
die reviewpflichtige Keep Preference, Migration `0016`, insert-only Persistenz,
den read-only Report `ebook-consolidation-report` und den statischen
Non-Execution-Gate gegen Filesystem-Mutationen, mutierende
Calibre-Command-Shapes und öffentliche Ausführungssurfaces. Jede
Filesystem-Mutation, mutierende Calibre-Operation und ausführbare W10-Strecke
bleibt ausgeschlossen.

FG-03A ist jetzt durch ADR-0035 akzeptiert. Das Gate legt den
`provider-cache-entry/v1`-Vertrag mit Result-Status, Payload-Kind,
Freshness-Triade, getrenntem vierteiligen Source- und fünfteiligen
Mapping-Input-Key, Negative-Cache-Regeln, Mapping-Reanalyse ohne Refetch,
generation-gefencetem CAS und bounded Retention fest. Der nächste
maßgebliche Implementierungsschritt gemäß
`EBOOK_ENDGAME_IMPLEMENTATION_PLAN.md` ist S-EB03A-01 mit immutable
Cache-DTOs und den in ADR-0035 festgelegten Result-/Freshness-Literalen.

EB-00, EB-01/E4, EB-02, EB-05, EB-06, EB-07 und EB-08 sind abgeschlossen. Die
Reihenfolge, Stop-Gates und zulässigen Spark-Pakete stehen in
`EBOOK_ENDGAME_IMPLEMENTATION_PLAN.md` und
`EBOOK_SPARK_WORK_PACKAGES.md`. Modell-, Thinking- und Agentenauswahl folgen
repositoryweit `MODEL_ROUTING_POLICY.md`; insbesondere werden Statusprüfungen
mit 5.6 Luna, atomare festgelegte Coding-Pakete bevorzugt mit 5.3 Codex Spark
und Frontier-/Security-Verträge nur mit der dort festgelegten höheren
Risikoklasse ausgeführt. Private Pfade, Runtime-Daten, Kennzahlen und Berichte
bleiben außerhalb von Git; Source Media bleibt unverändert.

Die langfristige Produktvision und Medienfolge stehen als nicht statussetzende
Entwürfe in `docs/vision/EVIDENCE_DRIVEN_COLLECTION_INTELLIGENCE.md` und
`docs/planning/FUTURE_CAPABILITY_MAP.md`. Sie ersetzen weder Backlog noch
ADRs. Die unveränderte Roh-Ideensammlung liegt im ausdrücklich
nichtkanonischen öffentlichen Bereich
`docs/ideas/owner-notes/raw/Gedanken_für_die_Zukunft.md`.

ADR-0042 und FUT-010 integrieren als vorgeschlagene Querschnittsfortsetzung die
portable Objekt-Lineage sowie bounded, idempotenten Austausch und
konfliktbewusste Fusion mehrerer FolioTone-Systeme. Vor Code sind getrennte
Gates für Knoten-/Objektreferenzen, Clone-/Restore-Semantik,
Austauschpaket, Merge/Trust/Decision Compatibility und read-only
Kennzeichnungsträger erforderlich. Ein Tag, Pfad oder Hash ist dabei keine
alleinige Identitätsautorität. ADR-0042 ist `Proposed`; es existiert weder ein
Export-/Import-/Sync-Workflow noch ein Kennzeichnungs- oder External-Library-
Write. Die aktive Archive-Welle und W10 bleiben unverändert.

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
