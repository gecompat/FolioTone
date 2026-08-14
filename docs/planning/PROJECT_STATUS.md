# Projektstatus

Stand: 2026-08-14

## Aktuelle Welle

**W3 aktiv — calibre EPUB/MOBI/AZW/AZW3 und Poppler PDF abgeschlossen; Feld-/Rollenabbildung als Nächstes**

W0 bis W2 sind abgeschlossen. Der Incremental Index, die generische read-only ToolProvider Runtime, Filename-/Path-Kandidaten und versionierte Parsing-Profile wurden vollständig lokal geprüft. `W2-011` ergänzt begrenzte strict-JSON-Auswertung persistierter Tool-Artefakte und eine konservative Reanalyse-Entscheidung. Der Docker-Build-Kontext ist durch eine allowlist-basierte `.dockerignore` auf die tatsächlich paketierten Anwendungsdateien begrenzt.

Die anfängliche Produktoberfläche bleibt auf ausdrückliche Benutzerentscheidung
ausschließlich die CLI. ADR-0016 dokumentiert diese Grenze. `W3-001` bewertet
calibre, EPUBCheck, Poppler und qpdf; `W3-002` implementiert die erste feste,
read-only `ebook-meta`-Befehlsform. `W3-003` ergänzt feste EPUB-
Textextraktion und einen FolioTone-eigenen normalisierten Text-Fingerprint.
`W3-004` ergänzt feste Poppler-PDF-Metadaten-, Seiten- und Textpfade mit
explizitem `NO_TEXT`. `W3-005` erweitert den unveränderlichen calibre-
Analysepfad ohne nativen Formatparser auf MOBI, AZW und AZW3. `W3-006` ist der
nächste Backlog-Eintrag.

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

Der W3-Slice ergänzt deklarierte, begrenzte Workspace-Ausgaben und eine
Adapter-Version-Policy vor dem Öffnen von Source Media. Konkrete ffprobe-,
fpcalc-, beets-, SongKong- oder Picard-Adapter sind noch nicht implementiert.

### Persistence

Die W1-Persistence wurde bisher über vier zusätzliche Alembic-Revisionen erweitert. Bereits gemergte Migrationen werden nicht rückwirkend verändert.

`0002_incremental_index` ergänzt insbesondere `file_scan_events`, `tool_artifacts`, Scan-/Tool-relevante Indizes und eindeutige logische `ScanRoot.name`-Werte.

`0003_deletion_confirmation` ergänzt `file_records` um `missing_since_at` und `consecutive_missing_scans`.

`0004_relocation_candidates` ergänzt `file_relocation_candidates` sowie Indizes für Run- und Source-/Target-Abfragen.

`0005_scan_resume_lineage` ergänzt `scan_runs.resumed_from_run_id` als nullable selbstreferenzierende Foreign-Key-Lineage sowie einen Query-Index.

Beim Upgrade einer bestehenden `0002`-Datenbank wird keine historische Abwesenheitsdauer oder Bestätigungsserie erfunden. Bestehende Datensätze beginnen konservativ mit `missing_since_at = NULL` und `consecutive_missing_scans = 0`; erst nachfolgende erfolgreiche Scans bauen neue Bestätigungsevidenz auf.

## Implementierter W3-Slice

### Aktuelle E-Book-Toolbewertung

`W3-001` ist mit einem Snapshot vom 2026-08-14 abgeschlossen:

- calibre 9.13.0 wird für dateibezogene Metadaten sowie die
  EPUB/MOBI/AZW/AZW3-Textextraktion wiederverwendet;
- EPUBCheck 5.3.0 ist für spätere EPUB-Konformitäts-Evidence ausgewählt;
- Poppler 26.07.0 ist für PDF-Metadaten-, Seiten- und Textanalyse implementiert;
- qpdf 12.4.0 bleibt eine optionale zweite Quelle für PDF-Struktur und
  Integrität, nicht für Textextraktion;
- MuPDF und native Formatparser werden erst bei einem nachgewiesenen Gap erneut
  bewertet.

Die verbindliche Begründung einschließlich Lizenz- und Distributionsgrenzen
steht in `docs/reference/EBOOK_TOOL_EVALUATION.md`.

### calibre `ebook-meta`

`W3-002` implementiert `CalibreMetadataAnalyzer` und den CLI-Befehl
`foliotone ebook-metadata`. Der Adapter besitzt nur die feste Befehlsform
`ebook-meta FILE --to-opf metadata.opf`; Calibre-Setter und frei übergebbare
Zusatzargumente sind nicht verfügbar.

Vor dem Öffnen der Source-Datei wird die calibre-Version geprüft. Unbekannte
Versionen und Versionen kleiner als 9.10.0 werden wegen
`GHSA-2j4m-2q7x-2c47`/`CVE-2026-53511` als auditierbare `FAILED`-Ausführung
abgelehnt. Versionsabfrage und Analyse verwenden ein ephemeres
`CALIBRE_CONFIG_DIRECTORY`.

Die generische Runtime übernimmt deklarierte Workspace-Ausgaben vor dem
Cleanup, begrenzt ihre Größe und persistiert Pfad, Größe und SHA-256 als
`ToolArtifact`. Der calibre-Adapter akzeptiert genau ein maximal 4 MiB großes
`CALIBRE_OPF`-Artefakt, prüft dessen Integrität, verweigert XML-Dokumenttyp- und
Entity-Deklarationen und speichert ausgewählte rohe OPF-Felder als `ToolResult`
gegen die konkrete `FileObservation`. Diese Werte bleiben Evidence und werden
nicht kanonisiert.

`calibredb` ist bewusst zurückgestellt. Die dokumentierten read-oriented
Subcommands `list --for-machine` und `show_metadata --as-opf` stehen neben
zahlreichen mutierenden Befehlen. Eine spätere Integration benötigt daher eine
enge Read-Command-Allowlist und einen konkreten Library-Reconciliation-Vertrag.

### calibre EPUB/MOBI/AZW/AZW3-Text und normalisierter Fingerprint

`W3-003` implementiert `CalibreTextAnalyzer` und den CLI-Befehl
`foliotone ebook-text` zunächst für EPUB. `W3-005` erweitert denselben Adapter
auf die explizite Allowlist EPUB, MOBI, AZW und AZW3. Die unveränderliche
`ebook-convert FILE content.txt`-Befehlsform verwendet `plain`-Ausgabe, UTF-8,
Unix-Zeilenenden und deaktivierte Zeilenaufteilung. Aufrufende Komponenten
können keine calibre-Konvertierungsoptionen ergänzen. KFX, AZW1, AZW4 und
weitere Formate gehören nicht zu diesem Textvertrag.

Die Sicherheitsuntergrenze calibre 9.10.0, das ephemere
`CALIBRE_CONFIG_DIRECTORY` und `CALIBRE_ALLOW_PYTHON_TEMPLATES=0` gelten auch
für diesen Adapter. Die Ausgabe wird vor dem Workspace-Cleanup als privates,
maximal 64 MiB großes `CALIBRE_TEXT`-Artefakt mit Größe und SHA-256 übernommen.
Der Rohtext wird nicht über die CLI ausgegeben. DRM-Entfernung oder -Umgehung
gehört nicht zum Vertrag. Ein DRM-geschütztes, beschädigtes oder anderweitig
nicht konvertierbares Buch bleibt eine fehlgeschlagene `ToolExecution`; nur
eine erfolgreiche leere Extraktion darf `NO_TEXT` erzeugen.

Nach UTF-8- und Artifact-Integritätsprüfung normalisiert FolioTone den Text mit
Unicode `NFKC`, reduziert Unicode-Whitespace-Folgen und bildet SHA-256. Der
`Fingerprint` besitzt `kind = EBOOK_NORMALIZED_TEXT`, verweist auf die konkrete
`FileObservation` und `ToolExecution` und führt die Unicode-Datenversion im
`algorithm_version`-Profil. `ToolResult` hält `TEXT_EXTRACTED` oder `NO_TEXT`
sowie die normalisierte Zeichenzahl. Für `NO_TEXT` entsteht kein Fingerprint.
Der neue `ToolCapability`-Wert lautet `EXTRACT_TEXT`.

### Poppler PDF-Metadaten, Seitenzahl und Text

`W3-004` implementiert `PopplerPdfAnalyzer` und den CLI-Befehl
`foliotone pdf-analyze`. Der Adapter akzeptiert ausschließlich eine
unveränderte PDF-`FileObservation`. `pdfinfo` und `pdftotext` besitzen feste
Argumentformen, separate `ToolExecution`-Records und getrennte Capabilities.
Unbekannte Poppler-Versionen und Versionen kleiner als 26.07.0 werden vor dem
Öffnen der Source-Datei abgelehnt.

Die UTF-8-Ausgabe von `pdfinfo` wird auf 1 MiB begrenzt und nur über eine
Feld-Allowlist importiert. Seitenzahl, gemeldete Dateigröße, PDF-Version und
ausgewählte technische Metadaten bleiben rohe Evidence; die Dateigröße wird
gegen die konkrete Observation geprüft. `pdftotext` schreibt ausschließlich
`content.txt` in den privaten Workspace. Maximal 64 MiB werden als
integritätsgeprüftes `POPPLER_TEXT`-Artefakt übernommen.

PDF und EPUB verwenden danach denselben FolioTone-eigenen, versionierten
`NFKC`-/Whitespace-Normalisierer und `EBOOK_NORMALIZED_TEXT`-Fingerprint.
Erfolgreich extrahierter leerer Text ist `NO_TEXT` und erzeugt keinen
Fingerprint; Poppler-Fehler bleiben dagegen fehlgeschlagene Toolausführungen.
Die CLI gibt keinen Rohtext aus. OCR, Passwortargumente, frei übergebbare
Poppler-Optionen und schreibende PDF-Operationen sind nicht exponiert. qpdf
bleibt bis zu einem konkreten strukturellen Evidence-Gap zurückgestellt.

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

### W3-001 bis W3-005 lokale Verifikation

**Empirisch:** Am 2026-08-14 wurde das offizielle calibre-9.13.0-MSI nach
SHA-256- und Authenticode-Prüfung als separates administratives Abbild unter
`C:\rep\cache\FolioTone` bereitgestellt. `ebook-meta.exe --version` meldete
calibre 9.13. Der MSI-Export endete mit Status 0; Codex wurde weder beendet noch
neu gestartet.

Ein End-to-End-Lauf mit ausschließlich einem synthetischen EPUB unter
`C:\rep\tmp\FolioTone` bestätigte:

- erfolgreicher `foliotone scan` und eine konkrete `FileObservation`;
- erfolgreiche `foliotone ebook-metadata`-Ausführung;
- ein persistiertes, integritätsgeprüftes `CALIBRE_OPF`-Artefakt;
- sechs persistierte rohe Metadatenbeobachtungen;
- leeres ephemeres Tool-Work-Verzeichnis nach Abschluss;
- keine echte Medien- oder Calibre-Library als Testeingabe.

Die vollständigen lokalen Quality Gates des W3-Slice waren erfolgreich:
`ruff check`, Mypy für 57 Source-Dateien und 107 Pytest-Tests.

**Remote:** Der Implementierungscommit
`1a02dc146919db7294b7b88ad6d9f6a7a6e60e04` bestand GitHub Actions Run
`31794835407`. Erfolgreich waren Install, Ruff, Mypy, Pytest, Docker-Build,
Migration, persistentes `/data`, Incremental-Scan-Smoke und Bootstrap.

**Empirisch für W3-003:** Ein weiterer End-to-End-Lauf mit demselben
ausschließlich synthetischen EPUB und calibre 9.13.0 bestätigte eine erfolgreiche
`ebook-text`-`ToolExecution`, ein 49 Byte großes `CALIBRE_TEXT`-Artefakt,
`TEXT_EXTRACTED`, 43 normalisierte Zeichen, einen
`EBOOK_NORMALIZED_TEXT`-Fingerprint und ein nach Abschluss leeres ephemeres
Work-Verzeichnis.

Repository-Ruff, Mypy für 59 Source-Dateien und 115 Pytest-Tests waren lokal
erfolgreich. Die gezielten 42 calibre-/Runtime-/CLI-Tests waren ebenfalls
erfolgreich. Der W3-003-Implementierungscommit
`dc2cd09ffbc07098e0c296bea231532c4f38051b` bestand GitHub Actions Run
`31809375485` für PR #13. Erfolgreich waren Install, Ruff, Mypy, Pytest,
Docker-Build, Migration, persistentes `/data`, Incremental-Scan-Smoke und
Bootstrap.

**Empirisch für W3-004:** Poppler 26.07.0 wurde außerhalb des Repositorys unter
`C:\rep\cache\FolioTone` verifiziert. Ein End-to-End-Lauf unter
`C:\rep\tmp\FolioTone` verwendete ausschließlich ein synthetisches Text-PDF
und ein synthetisches leeres PDF. Beide erzeugten erfolgreiche, getrennte
`pdfinfo`-/`pdftotext`-Ausführungen, jeweils 20 Metadatenbeobachtungen und
`page_count = 1`. Das Text-PDF lieferte `TEXT_EXTRACTED`, 45 normalisierte
Zeichen und einen `EBOOK_NORMALIZED_TEXT`-Fingerprint. Das leere PDF lieferte
`NO_TEXT`, null normalisierte Zeichen und keinen Fingerprint. Die gezielten 18
Poppler-Unit-Tests waren erfolgreich; die ephemeren Work-Verzeichnisse waren
nach Abschluss leer.

Der vollständige W3-004-Stand bestand anschließend lokal `ruff check .`, Mypy
für 63 Source-Dateien und alle 133 Pytest-Tests in 6 Minuten 35 Sekunden.

**Empirisch für W3-005:** Ein End-to-End-Lauf mit calibre 9.13.0 und
ausschließlich synthetischen, DRM-freien EPUB-, MOBI-, AZW- und AZW3-Dateien
bestätigte vier erfolgreiche Metadaten- sowie vier erfolgreiche Text-
`ToolExecution`-Records. Alle vier Textläufe lieferten `TEXT_EXTRACTED`, 43
normalisierte Zeichen und denselben `EBOOK_NORMALIZED_TEXT`-Fingerprint. Der
Adapterstand `ebook-convert-text/2` war viermal erfolgreich persistiert. Das
ephemere Work-Verzeichnis war nach Abschluss leer; Rohtext wurde nicht über die
CLI ausgegeben. Die gezielten 32 calibre-/CLI-Tests sowie Ruff und Mypy für 63
Source-Dateien waren erfolgreich.

Der vollständige W3-005-Stand bestand anschließend lokal `ruff check .`, Mypy
für 63 Source-Dateien und alle 142 Pytest-Tests in 8 Minuten 50 Sekunden.

## W3-Stand und nächster Schritt

In W2 verbleibt kein offener Backlog-Eintrag. `W3-001` bis `W3-005` sind
abgeschlossen. `W3-006` ist `NEXT`: ISBN, Contributors, Sprache, Verlag, Serie
und weitere Felder werden als Provenance-erhaltende Beobachtungen und
Kandidaten detaillierter abgebildet.

## Nicht implementiert

Noch nicht vorhanden sind unter anderem:

- weitere Formate außerhalb der expliziten EPUB/MOBI/AZW/AZW3-Text-Allowlist
  sowie alle Music-ToolProvider;
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
