# Projektstatus

Stand: 2026-08-15

## Aktuelle Welle

**W3 E-Book-Vertiefung aktiv — deterministische private Collection-Berichte implementiert; read-only Sammlungspilot als Nächstes**

W0 bis W2 sind abgeschlossen. Der Incremental Index, die generische read-only ToolProvider Runtime, Filename-/Path-Kandidaten und versionierte Parsing-Profile wurden vollständig lokal geprüft. `W2-011` ergänzt begrenzte strict-JSON-Auswertung persistierter Tool-Artefakte und eine konservative Reanalyse-Entscheidung. Der Docker-Build-Kontext ist durch eine allowlist-basierte `.dockerignore` auf die tatsächlich paketierten Anwendungsdateien begrenzt.

Die anfängliche Produktoberfläche bleibt auf ausdrückliche Benutzerentscheidung
ausschließlich die CLI. ADR-0016 dokumentiert diese Grenze. `W3-001` bewertet
calibre, EPUBCheck, Poppler und qpdf; `W3-002` implementiert die erste feste,
read-only `ebook-meta`-Befehlsform. `W3-003` ergänzt feste EPUB-
Textextraktion und einen FolioTone-eigenen normalisierten Text-Fingerprint.
`W3-004` ergänzt feste Poppler-PDF-Metadaten-, Seiten- und Textpfade mit
explizitem `NO_TEXT`. `W3-005` erweitert den unveränderlichen calibre-
Analysepfad ohne nativen Formatparser auf MOBI, AZW und AZW3. `W3-006` ergänzt
rohe OPF2-/OPF3-Beobachtungen und provider-neutrale, gruppierte
Metadatenkandidaten mit exakten `ToolExecution`-/`FileObservation`-Links.
`W3-007` ergänzt einen versionierten synthetischen Vergleichskorpus für
Datei-, Inhalts-, `Edition`-, `Work`- und Tool-Disagreement-Ground-Truth.
`W3-008` ergänzt feste read-only EPUBCheck-JSON-Validierung, einen neuen
`STRUCTURAL_VALIDATION`-Evidence-Vertrag und provider-spezifische akzeptierte
Exitcodes. `W3-009` ergänzt optionale, quellisolierte Embedded-Cover-
Extraktion für EPUB/MOBI/AZW/AZW3, explizites `NO_EMBEDDED_COVER` und einen
FolioTone-eigenen versionierten `EBOOK_COVER_DHASH`. `W3-010` ergänzt den
formatbewussten CLI-Workflow `ebook-analyze` mit getrennten Schritt- und
Gesamtzuständen. `W3-011` ergänzt exakte, integritätsgeprüfte Evidence-
Wiederverwendung, gezielten Schritt-Retry und `--fresh`. `W3-012` ergänzt die
separate, mehrdimensionale Projektion `ebook-quality/v1` mit festen
Befundcodes. `W3-013` ergänzt `ebook-comparison/v1` und den read-only CLI-
Paarvergleich persistierter Datei-, Text-, Metadaten-, Struktur- und Cover-
Evidence ohne Relation oder Identitätsurteil. Auf Benutzerentscheidung bleibt
die aktive Entwicklung bei E-Books. `W3-014` ergänzt den synthetischen v2-
Edge-Korpus sowie begrenzte, indexgestützte Evidence-Abfragen. `W3-015`
ergänzt einen fortsetzbaren Collection Batch mit persistentem Snapshot-Plan,
Lease, begrenzten Workern und per-File-Fehlerfortsetzung. `W3-016` ergänzt
deterministische private JSON-/CSV-Sammlungsberichte, persistierte
Befundprovenance und begrenzte Duplicate-/Varianten-Review-Kandidaten.
`W3-017` ist `NEXT`; die Music-Welle W4 bleibt geplant und zurückgestellt.

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
- auditierbare FAILED-Ausführung bei fehlendem Tool oder einem vom Adapter nicht
  akzeptierten Exitcode; standardmäßig wird ausschließlich `0` akzeptiert;
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

Die W1-Persistence wurde bisher über sieben zusätzliche Alembic-Revisionen erweitert. Bereits gemergte Migrationen werden nicht rückwirkend verändert.

`0002_incremental_index` ergänzt insbesondere `file_scan_events`, `tool_artifacts`, Scan-/Tool-relevante Indizes und eindeutige logische `ScanRoot.name`-Werte.

`0003_deletion_confirmation` ergänzt `file_records` um `missing_since_at` und `consecutive_missing_scans`.

`0004_relocation_candidates` ergänzt `file_relocation_candidates` sowie Indizes für Run- und Source-/Target-Abfragen.

`0005_scan_resume_lineage` ergänzt `scan_runs.resumed_from_run_id` als nullable selbstreferenzierende Foreign-Key-Lineage sowie einen Query-Index.

`0006_ebook_evidence_lookup_indexes` ergänzt drei additive Indizes für
zielgerichtete `ToolExecution`-, `ToolResult`- und `Fingerprint`-Abfragen des
E-Book-Paarvergleichs. Bestehende Domain-Datensätze werden nicht umgeschrieben.

`0007_ebook_collection_batches` ergänzt `ebook_collection_runs` und
`ebook_collection_items` sowie Indizes für Root-/Status- und
Run-/Status-/Ordinal-Abfragen. Die Batch-Tabellen speichern Observation-IDs,
Lifecycle und begrenzte Zähler, aber keine Pfade oder Metadatenwerte.

`0008_ebook_collection_reports` ergänzt geordnete Item-Ausführungs- und
Quality-Befundprojektionen einschließlich exakter `ToolExecution`-Quellen
sowie den belegten Fingerprint-Gruppierungsindex. Die Tabellen speichern keine
Source-Pfade, Metadatenwerte oder extrahierten Inhalte.

Beim Upgrade einer bestehenden `0002`-Datenbank wird keine historische Abwesenheitsdauer oder Bestätigungsserie erfunden. Bestehende Datensätze beginnen konservativ mit `missing_since_at = NULL` und `consecutive_missing_scans = 0`; erst nachfolgende erfolgreiche Scans bauen neue Bestätigungsevidenz auf.

## Implementierter W3-Slice

### Aktuelle E-Book-Toolbewertung

Die Toolauswahl wurde am 2026-08-15 für `W3-009` erneut geprüft:

- calibre 9.13.0 wird für dateibezogene Metadaten sowie die
  EPUB/MOBI/AZW/AZW3-Text- und Embedded-Cover-Extraktion wiederverwendet;
- Pillow 12.3.0 übernimmt die begrenzte Rasterdekodierung und
  Lanczos-Normalisierung; die dHash-Semantik bleibt FolioTone-eigen;
- EPUBCheck 5.3.0 ist für EPUB-Konformitäts-Evidence implementiert;
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

`W3-006` hebt den Metadatenadapter auf `ebook-meta-opf/2` und behält die rohen
`calibre_metadata`-Ergebnisse bei. Der provider-neutrale Vertrag
`ebook-metadata-candidate/v1` projiziert zusätzlich OPF-2-Attribute und
OPF-3-Refinements in stabile Feldpfade. Gruppiert werden Identifier-
Namespace/-Wert, Contributor-Name/-Quelle/-Rolle/-Sortiername sowie
Serienname/-position. Direkte Kandidaten umfassen Titel, Sprache, Verlag,
Publikationsdatum, Subject, Beschreibung, Rechte, Typ, Titelsortierung und
calibre-Rating, soweit vorhanden.

Explizite ISBN-Schemes, `urn:isbn` und die ONIX-Codelist-5-Werte 02/15 werden
als ISBN-Namespace erkannt. Die unterstützten MARC-Relator-Codes decken Autor,
Book Producer, Contributor, Editor, Illustrator, Narrator, Other und Translator
ab. Unbekannte Rollen-Schemes bleiben rohe Source-Evidence und erzeugen keine
geratene normalisierte Rolle. Jeder Kandidat verweist auf die exakte
`ToolExecution` und `FileObservation`; der Adapter legt keine `Agent`-,
`Work`-, `Edition`- oder `Series`-Entität an.

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

### Versionierter E-Book-Vergleichskorpus

`W3-007` stellt unter `tests/fixtures/ebook_comparison/v1/` fünf vollständig
synthetische Items und fünf gelabelte Szenarien bereit. Das Manifest
`foliotone-ebook-comparison-fixture/v1` bindet ausschließlich sichere relative
Pfade sowie SHA-256-Werte der Container-Surrogate und extrahierten
Text-Artefakte. Der produktive `EBOOK_NORMALIZED_TEXT`-Vertrag erzeugt daraus
die versionierten Inhalts-Fingerprints. `.gitattributes` verhindert dabei eine
plattformabhängige Zeilenendenkonvertierung der checksum-behafteten Fixtures.

Die Ground Truth unterscheidet:

- zwei byte-identische Dateien;
- unterschiedliche Dateibytes nach einer Metadatenänderung bei identischem
  normalisiertem Text und derselben `Edition`;
- dieselbe `Edition` als EPUB-/MOBI-Formatvariante;
- eine Übersetzung als andere `Edition` desselben `Work`;
- zwei widersprüchliche synthetische Tool-Beobachtungen für denselben
  Identifier mit getrennten Tool-, Adapter- und Kandidatenprofilversionen.

Die Container-Surrogate sind bewusst keine echten EPUB-/MOBI-Dateien und
testen deshalb keine Drittanbieterparser nach. Das Disagreement-Szenario setzt
keinen kanonischen Wert. Die deklarierten `RelationType`-Werte dienen als
kontrollierte Eingabe für spätere W6-Tests; Candidate Blocking, Scoring,
Confidence-Schwellen und automatische Review-Entscheidungen sind nicht Teil
von W3-007. Der Slice ergänzt keine Produktoberfläche und verändert keine
Source Media.

### EPUBCheck-Strukturvalidierung

`W3-008` implementiert `EpubCheckAnalyzer` und den CLI-Befehl
`foliotone epub-validate`. Der Adapter akzeptiert nur eine unveränderte
EPUB-`FileObservation` und ruft eine separat bereitgestellte Java-Runtime plus
`epubcheck.jar` über eine feste Headless-Befehlsform auf. JVM-Tempdaten und
`report.json` entstehen ausschließlich im privaten ephemeren Tool-Workspace.
Zusätzliche EPUBCheck-Optionen sind nicht über die CLI verfügbar.

EPUBCheck 5.3.0 ist die Mindestversion. Der maximal 8 MiB große JSON-Report wird
als integritätsgeprüftes `EPUBCHECK_JSON`-`ToolArtifact` übernommen. Der
strikte Parser begrenzt die Meldungszahl auf 10.000 und verifiziert Dateiname,
Tool-/Reportversion, deklarierte Counts, Severity-Allowlist sowie Diagnose-IDs.
Persistiert werden `CONFORMANT` oder `NONCONFORMANT`, fünf Severity-Counts und
aggregierte Severity-/Diagnosecode-Counts gegen die exakte `ToolExecution` und
`FileObservation`. Meldungstext, Publication-Metadaten und lokale Pfade werden
nicht in `ToolResult` oder CLI-Ausgabe projiziert.

ADR-0017 erweitert den generischen Runtime-Vertrag um eine unveränderliche
`accepted_exit_codes`-Allowlist mit Standard `{0}`. Der EPUBCheck-Befehl
akzeptiert dokumentiert `{0, 1}`, weil Exitcode `1` einen abgeschlossenen
Prüflauf mit Konformitätsfehlern bezeichnet. Der Code bleibt in
`ToolExecution.exit_code` erhalten; der negative Befund steht getrennt in
`ToolResult`. Nicht erlaubte Codes, Timeout sowie fehlende, ungültige oder zu
große Pflichtartefakte bleiben technische Fehler.

`calibre-debug --diff` wurde nicht integriert: Die dokumentierte Option startet
das GUI-Diff-Modul und besitzt keinen headless, maschinenlesbaren Report- oder
stabilen Exitcode-Vertrag. Spätere Inhaltsvergleiche sollen die bereits
provider-neutral persistierte Evidence aus Datei-Hash, normalisiertem Text,
Metadaten, Struktur und Cover-Fingerprints verwenden. qpdf 12.4.0
bleibt bis zu einem zusätzlichen PDF-Struktur-Gap zurückgestellt.

### calibre Embedded-Cover und FolioTone-dHash

`W3-009` implementiert `CalibreCoverAnalyzer` und den CLI-Befehl
`foliotone ebook-cover` für die explizite EPUB/MOBI/AZW/AZW3-Allowlist. Ein
fester, paketierter Helper läuft über das dokumentierte
`calibre-debug -e SCRIPT -- ...`-Interface. Er kopiert die unveränderte
Observation zuerst in den privaten ephemeren Workspace; erst dort öffnet der
calibre-Metadatenreader die Datei. Für EPUB ist das Rendering der ersten Seite
als Ersatzcover deaktiviert. Ein Buch ohne eingebettetes Cover erzeugt deshalb
`NO_EMBEDDED_COVER` statt eines erfundenen Titelbilds.

Der direkte `ebook-meta --get-cover`-Pfad wurde bewusst verworfen. Ohne
Unterdrückung rendert calibre bei coverlosen EPUBs die erste Seite. Der lokale
9.13-Test zeigte außerdem, dass `--disallow-rendered-cover` von `ebook-meta`
als schreibende Option behandelt wird und die Eingabedatei verändern kann.
Der Helper verwendet daher keine `ebook-meta`-Setter-Schnittstelle und gibt
dem calibre-Reader ausschließlich die private Arbeitskopie.

Ein erforderliches, maximal 1 KiB großes JSON-Ergebnis hält Status,
Covergröße und SHA-256 der gestagten Source. FolioTone vergleicht diesen Digest
nach dem Toollauf erneut mit der konkreten `FileObservation`. Das optionale
Raster bleibt als privates, maximal 32 MiB großes
`CALIBRE_EMBEDDED_COVER`-`ToolArtifact` erhalten. JPEG, PNG, WebP und GIF
werden mit Pillow 12.3.x dekodiert; eine 40-Megapixel-Grenze, Pillow-
Decompression-Bomb-Prüfung, EXIF-Orientierung und ausschließlich der erste
Frame begrenzen und determinieren die Verarbeitung.

FolioTone normalisiert das Bild in Graustufen auf 9 x 8 Pixel mit Lanczos und
vergleicht je Zeile acht horizontale Nachbarpaare. Das Ergebnis ist ein
64-Bit-`dhash-64` mit `kind = EBOOK_COVER_DHASH`. Das
`algorithm_version`-Profil enthält Richtung, Farbraum, Rastergröße,
Resampling-Verfahren und exakte Pillow-Version. ImageHash 4.3.2 wurde für
diesen kleinen festen Vertrag nicht übernommen, weil sein Gesamtpaket NumPy,
SciPy und PyWavelets einzieht. Coverähnlichkeit bleibt unterstützende Evidence;
sie beweist weder gleiche Datei noch gleiche `Edition` oder gleiches `Work`.
PDF-Seitenrendering und Music-Release-Artwork gehören nicht zu diesem Slice.

### Einheitlicher formatbewusster E-Book-Workflow

`W3-010` implementiert `ebook-analysis-workflow/v1` und den CLI-Befehl
`foliotone ebook-analyze`. Die Workflow-Schicht enthält keinen neuen Parser und
keine eigene Toolausführung. Sie ruft ausschließlich die bereits gehärteten
Adapter in fester, formatabhängiger Reihenfolge auf:

- EPUB: calibre-Metadaten, normalisierter Text, Embedded-Cover und EPUBCheck;
- MOBI/AZW/AZW3: calibre-Metadaten, normalisierter Text und Embedded-Cover;
- PDF: die bestehenden `pdfinfo`- und `pdftotext`-Ausführungen von Poppler.

Vor dem ersten Schritt wird geprüft, ob alle für das konkrete Format nötigen
Adapter konfiguriert sind. Erwartete Adapterfehler und fehlgeschlagene oder
abgebrochene ToolExecutions blockieren unabhängige Folgeschritte nicht. Jeder
Schritt bleibt separat als `SUCCEEDED`, `FAILED`, `CANCELLED` oder `ERROR`
sichtbar. Der Workflow fasst dies zu `SUCCEEDED`, `PARTIAL_FAILURE` oder
`FAILED` zusammen; nur vollständiger technischer Erfolg liefert CLI-Exitcode
0. Ein EPUBCheck-Befund `NONCONFORMANT` bleibt dabei ein erfolgreich erzeugter
fachlicher Befund und wird nicht als Prozessfehler umgedeutet.

Jeder Aufruf erzeugt zunächst bewusst frische versions- und
konfigurationsgebundene ToolExecutions. Unsichere Wiederverwendung wird nicht
implizit eingeführt. `W3-011` soll auf der konservativen W2-Entscheidungslogik
aufbauen und ausschließlich exakt passende, erfolgreiche und weiterhin
integritätsprüfbare Evidence wiederverwenden.

Die CLI-Zusammenfassung ist begrenzt und druckt nur Format, Workflow-Profil,
ToolExecution-ID/-Status/-Version sowie allowlist-basierte Zähler, Statuswerte
und Fingerprints. Rohe OPF-, Text-, Cover- und EPUBCheck-Artefakte,
Diagnosetexte und absolute Source-Pfade werden nicht ausgegeben.

### Konservative Schrittplanung und Evidence-Wiederverwendung

`W3-011` hebt den einheitlichen Vertrag auf
`ebook-analysis-workflow/v2`. Standardmäßig prüft jeder Adapter zunächst nur
die Version seines fest konfigurierten lokalen Werkzeugs. Dieser Probe öffnet
keine Source Media und persistiert keine ToolExecution. Ein früherer Schritt
wird ausschließlich dann wiederverwendet, wenn der zeitlich neueste Lauf mit
exakt gleicher Provider-, Tool-, Adapter-, Capability-, FileObservation-Input-
und Konfigurationsidentität erfolgreich war.

Die Identität allein genügt nicht: Jedes vom Adapter deklarierte
Pflichtartefakt muss weiterhin vorhanden sein und seine Größen- und SHA-256-
Grenzen erfüllen. Anschließend rekonstruiert FolioTone die normalisierten
ToolResults und Fingerprints deterministisch aus dem privaten Artefakt und
vergleicht sie inhaltsgleich mit der Persistenz. Dadurch wird weder ein bloßes
`SUCCEEDED` noch ein unvollständig importierter oder nachträglich beschädigter
Stand als wiederverwendbar behandelt.

Fehlende, fehlgeschlagene, abgebrochene, laufende, versionsfremde,
artefaktbeschädigte oder inkonsistente Schritte werden normal read-only neu
ausgeführt. Unabhängige exakte Schritte bleiben dabei wiederverwendet. Die CLI
weist jeden Schritt als `REUSED` oder `EXECUTED` aus; die ursprünglichen
ToolExecution-IDs bleiben bei Wiederverwendung unverändert. `--fresh` umgeht
die gesamte Wiederverwendungsplanung und führt alle anwendbaren Schritte neu
aus. Der vorhandene PDF-Adapter bleibt ein atomarer Workflow-Schritt: Sind
`pdfinfo` oder `pdftotext` nicht exakt wiederverwendbar, laufen beide getrennt
provenance-gebundenen Poppler-Ausführungen neu.

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

### W3-001 bis W3-009 lokale Verifikation

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

**Empirisch für W3-006:** Der gezielte OPF2-/OPF3-Testlauf bestand alle 26
calibre-Metadaten-Tests. Er deckt gruppierte ISBN-/Identifier-, Contributor-,
MARC-Rollen-, Sortier-, Sprach-, Verlags-, Datums-, Subject-, Beschreibungs-,
Rechte-, Typ- und Series-Kandidaten sowie das bewusste Nicht-Mapping eines
fremden Rollen-Schemes ab.

Ein read-only End-to-End-Smoke-Test mit calibre 9.13 und einem ausschließlich
synthetischen, DRM-freien MOBI erzeugte eine erfolgreiche `ToolExecution` unter
`ebook-meta-opf/2`, elf rohe `calibre_metadata`-Beobachtungen und 21
`ebook_metadata_candidate`-Ergebnisse. Alle Ergebnisse verwiesen auf genau
diese Ausführung und `FileObservation`; `Agent`, `Work`, `Edition` und `Series`
blieben leer. Das private OPF-Artefakt wurde übernommen, und das ephemere
Work-Verzeichnis war nach Abschluss leer.

Der vollständige W3-006-Stand bestand lokal `ruff check .`, Mypy für 64
Source-Dateien und alle 152 Pytest-Tests in 8 Minuten 45 Sekunden.

**Empirisch für W3-007:** Die drei gezielten Fixture-Vertragsprüfungen
bestanden. Sie prüfen Schema-Version und Provenance, sichere relative Pfade,
alle deklarierten Datei-/Text-SHA-256-Werte, den produktiven normalisierten
Text-Fingerprint, die vier paarweisen Identitätsabgrenzungen und die Erhaltung
zweier widersprüchlicher Tool-Werte ohne Kanonisierung.

Der vollständige W3-007-Stand bestand lokal `ruff check .`, Mypy für 64
Source-Dateien und alle 155 Pytest-Tests in 8 Minuten 25 Sekunden.

**Remote für W3-007:** Der Implementierungscommit
`352eb8567c542e709e77f98de42c222f21dd3f75` von PR #17 bestand die beiden durch
Push und Pull Request ausgelösten GitHub-Actions-Runs `31844049430` und
`31844093222`. Beide `quality`-Jobs waren nach jeweils 52 Sekunden erfolgreich.

**Empirisch für W3-008:** Temurin JRE 21.0.12+8 und EPUBCheck 5.3.0 wurden als
portable, SHA-256-verifizierte Runtime-Abhängigkeiten unter
`C:\rep\cache\FolioTone` bereitgestellt. Es gab keine systemweite Installation,
keinen Neustart und keinen Eingriff in Codex.

Der echte CLI-Smoke-Test verwendete ausschließlich das vorhandene synthetische
EPUB. EPUBCheck meldete drei Konformitätsfehler und Exitcode `1`; FolioTone
persistierte eine erfolgreiche `STRUCTURAL_VALIDATION`-Ausführung,
`NONCONFORMANT`, fünf Severity-Counts und die Codes `PKG-006`, `PKG-007` und
`RSC-005`. Die Source-Datei blieb bytegleich, der Report wurde privat
übernommen und das Work-Verzeichnis vollständig bereinigt. Die 15 neuen
Adaptertests sowie 37 gezielten Runtime-/Toolingtests waren erfolgreich; der
gezielte Mypy-Lauf für Adapter, Runtime und CLI war fehlerfrei.

Der vollständige W3-008-Stand bestand anschließend mit Python 3.12.10 lokal
`ruff check .`, Mypy für 66 Source-Dateien und alle 175 Pytest-Tests in
9 Minuten 23 Sekunden.

**Remote für W3-008:** Der Implementierungscommit
`e80b1d9cba28e2d883daaa2627b4fc0ef795d11c` von PR #18 bestand die durch Push
und Pull Request ausgelösten GitHub-Actions-Runs `31866746326` und
`31866764769`. Beide `quality`-Jobs waren nach 58 beziehungsweise 50 Sekunden
erfolgreich.

**Empirisch für W3-009:** Pillow 12.3.0 wurde ausschließlich in der
projektbezogenen Python-Umgebung unter `C:\rep\cache\FolioTone` installiert;
es gab keine systemweite Installation und keinen Neustart. Die 13 neuen
Cover-Unit-Tests sowie die beiden aktualisierten Bootstrap-Tests bestanden in
85 Sekunden. Repository-Ruff und Mypy für 69 Source-Dateien waren erfolgreich.

Der echte CLI-Smoke-Test unter
`C:\rep\tmp\FolioTone\w3-009-smoke-01` verwendete ausschließlich zwei
synthetische EPUBs. Das Buch mit eingebettetem JPEG lieferte
`COVER_EXTRACTED`, Format `JPEG`, 1240 x 1752 Pixel und den 64-Bit-dHash
`4000000000000000`. Das coverlose Buch lieferte erfolgreich
`NO_EMBEDDED_COVER` und keinen Fingerprint. Beide `ToolExecution`-Records
meldeten calibre 9.13, beide CLI-Aufrufe endeten mit Exitcode 0, und die
SHA-256-Werte beider Source-Dateien waren vor und nach der Analyse identisch.

Der vollständige W3-009-Stand bestand mit Python 3.12.10 lokal
`ruff check .`, Mypy für 69 Source-Dateien und alle 188 Pytest-Tests in
11 Minuten 31 Sekunden. Ein lokaler Wheel-Build war erfolgreich und enthielt
den Cover-Adapter, die FolioTone-Hashlogik und den paketierten calibre-Helper.

Der Implementierungscommit `a55b553445b223ea6219a522cdaafeff98165aa7`
von PR #19 bestand die GitHub-Actions-Runs `31871971678` und `31871990590`;
die beiden `quality`-Jobs waren nach 58 beziehungsweise 63 Sekunden
erfolgreich.

**Empirisch für W3-010:** Die gezielte Suite aus Workflow-, Bootstrap- und
CLI-Integrationstests bestand mit 18 Tests. Ruff war erfolgreich; Mypy prüfte
71 Source-Dateien ohne Befund. Der CLI-Integrationstest bestätigt, dass vier
fehlende EPUB-Werkzeuge als vier getrennte fehlgeschlagene
ToolExecutions sichtbar bleiben, alle Schritte ausgeführt werden und weder
Source- noch absolute Runtime-Pfade in der Zusammenfassung erscheinen.

Der echte CLI-Smoke-Test unter
`C:\rep\tmp\FolioTone\w3-010-smoke-01` verwendete ausschließlich die beiden
synthetischen EPUBs mit und ohne eingebettetes Cover. Beide einheitlichen
Analysen endeten mit Exitcode 0 und jeweils vier erfolgreichen ToolExecutions.
Persistiert wurden insgesamt acht erfolgreiche ToolExecutions, 79 ToolResults
und sieben Fingerprints. Metadaten, Text und EPUBCheck waren für beide Dateien
erfolgreich; das Cover-Ergebnis blieb korrekt `COVER_EXTRACTED` beziehungsweise
`NO_EMBEDDED_COVER`. Die synthetisch unvollständigen EPUBs lieferten erwartbar
`NONCONFORMANT` mit je drei Fehlercodes, ohne den technischen Workflowstatus zu
verfälschen. Beide Source-SHA-256 blieben unverändert, und der ephemere
Work-Ordner war nach den Läufen leer.

Der vollständige W3-010-Stand bestand mit Python 3.12.10 lokal
`ruff check .`, Mypy für 71 Source-Dateien und alle 204 Pytest-Tests in
11 Minuten 16 Sekunden. Das Wheel
`C:\rep\artifacts\FolioTone\w3-010-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`3ad24961dc47512721a06053ab40504b2534a8979effb9a43e713c4e501aff24` und
enthält beide Dateien des neuen `foliotone.workflows`-Pakets.

**Empirisch für W3-011:** Der echte CLI-Smoke-Test unter
`C:\rep\tmp\FolioTone\w3-011-smoke-01` verwendete ausschließlich ein
synthetisches EPUB mit eingebettetem Cover. Der Erstlauf erzeugte vier
erfolgreiche ToolExecutions. Ein identischer zweiter Lauf markierte alle vier
Schritte als `REUSED`, behielt dieselben ToolExecution-IDs und erhöhte den
Datenbankzähler nicht. Nach absichtlicher SHA-256-Inkonsistenz ausschließlich
des privaten `CALIBRE_TEXT`-Artefakts wurde nur der Textschritt neu ausgeführt;
der Zähler stieg von vier auf fünf. Ein anschließender Lauf mit `--fresh`
führte alle vier Schritte neu aus und erhöhte ihn auf neun.

Verwendet wurden calibre 9.13, EPUBCheck 5.3.0 und Temurin JRE 21.0.12+8. Die
Source-SHA-256 blieb
`41070cdea56904647215b069f15af3f6e46d6d94b81795974e247a337464b6ea`;
der ephemere Work-Ordner war nach allen Läufen leer.

Der vollständige W3-011-Stand bestand mit Python 3.12.10 lokal
`ruff check .`, Mypy für 73 Source-Dateien und alle 216 Pytest-Tests in
11 Minuten 35 Sekunden. Das Wheel
`C:\rep\artifacts\FolioTone\w3-011-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`ab6064b05035a8cddd4f033a493c3f9d76ce43b37fe89dba5d790f142ad9e62e`
und enthält die Workflow-Module `ebook.py`, `evidence.py` und `reuse.py`.

Der W3-011-Implementierungscommit
`2f08bcc4f3b13517ec70e92e3eb25416ce56e6e4` liegt in PR #21. Für diesen
exakten Stand waren die GitHub-Actions-Runs `31886119562` (Push) und
`31886140176` (Pull Request) erfolgreich. Ihre `quality`-Jobs einschließlich
Ruff, Mypy, Tests, Docker-Build, Migration, persistentem `/data`,
Incremental-Scan-Smoke und Bootstrap liefen 56 beziehungsweise 63 Sekunden.

Der veröffentlichte Implementierungscommit
`2f8cb144617433855f51c39c4525603b9aa1004a` liegt in PR #20. Für diesen
exakten Stand waren die GitHub-Actions-Runs `31874601676` (Push) und
`31874615476` (Pull Request) erfolgreich; ihre `quality`-Jobs einschließlich
Ruff, Mypy, Tests und aller Docker-Smoke-Tests liefen 62 beziehungsweise
59 Sekunden.

**Empirisch für W3-012:** Die gezielten lokalen Tests decken ein vollständiges
EPUB, metadata-arme und nicht konforme EPUB-Evidence, ein verschlüsseltes
textloses PDF, fehlgeschlagene Tool-Evidence, widersprüchliche Text-Evidence
und die begrenzte CLI-Ausgabe ab. Alle 26 gezielten Tests waren erfolgreich;
der vollständige Stand bestand `ruff check .`, Mypy für 74 Source-Dateien und
alle 222 Pytest-Tests in 9 Minuten 23 Sekunden.

Der echte CLI-Smoke verwendete ausschließlich die synthetische EPUB unter
`C:\rep\tmp\FolioTone\w3-011-smoke-01`. Alle vier technischen Schritte wurden
mit denselben ToolExecution-IDs `REUSED`; der Datenbankzähler blieb bei neun.
`ebook-quality/v1` meldete wegen 43 normalisierten Zeichen
`TEXT_VERY_SHORT` und wegen drei EPUBCheck-Errors
`EPUB_VALIDATION_ERRORS`, insgesamt `ACTION_REQUIRED`, während der technische
Workflow korrekt `SUCCEEDED` blieb. Die Source-SHA-256 blieb
`41070cdea56904647215b069f15af3f6e46d6d94b81795974e247a337464b6ea` und
der Work-Ordner leer.

Das Wheel
`C:\rep\artifacts\FolioTone\w3-012-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`a02e033db35e6e2acfe0d374961597e257e3070198bb3f503854425a17a95457` und
enthält das neue Workflow-Modul `quality.py`.

**Empirisch für W3-013:** Der vorhandene vollständig synthetische Korpus prüft
exakte Dateikopien, reine Metadatenänderung, EPUB/MOBI-Formatvariante,
Übersetzung, Cover-dHash-Distanz, EPUB-Strukturunterschiede und gleichzeitig
erhaltene Provider-Disagreement-Evidence. Ein neuerer fehlgeschlagener
Textprovider-Lauf macht ältere Text-Evidence korrekt `INDETERMINATE`. Die fünf
gezielten Vergleichs-/CLI-/Bootstrap-Tests waren erfolgreich; Ruff und Mypy
für 75 Source-Dateien waren ebenfalls erfolgreich. Der vollständige Stand
bestand alle 225 Pytest-Tests in 13 Minuten 27 Sekunden.

Der echte CLI-Smoke unter `C:\rep\tmp\FolioTone\w3-013-smoke-01` verwendete
zwei bytegleiche Kopien einer ausschließlich synthetischen EPUB. Acht
ToolExecutions analysierten beide Beobachtungen erfolgreich. `ebook-compare`
meldete `COMPLETE` und in allen fünf Dimensionen `SAME`; ein von calibre pro
Extraktion neu erzeugter interner `identifier.calibre` wurde nach empirischer
Gegenprüfung nicht als bibliografischer Unterschied verwendet. Beide Source-
SHA-256 blieben
`41070cdea56904647215b069f15af3f6e46d6d94b81795974e247a337464b6ea`, der
Work-Ordner blieb leer und die Relation-Tabelle enthielt null Datensätze.

Das Wheel
`C:\rep\artifacts\FolioTone\w3-013-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`985e84dbf06e8bcad2e23468af3cd096a6ef9c0469300ae357a016854da669fe` und
enthält `foliotone/workflows/comparison.py`.

**Empirisch für W3-014:** Der additive synthetische v2-Korpus deckt alle
aktuell unterstützten Formate EPUB, MOBI, AZW, AZW3 und PDF, vollständig
fehlende sowie gezielt inkompatible/unvollständige Evidence und Cover-dHash-
Distanzen von 0, 1, 8, 32 und 64 Bit ab. Sechs neue Paar-Szenarien liefern die
deklarierten Zustände; Sparse- und Malformed-Fälle bleiben technisch
`INDETERMINATE` und erzeugen keine `Relation`.

Der synthetische Skalierungstest ergänzt 10.000 nicht angeforderte Records je
Evidence-Tabelle. Der Read lädt trotzdem nur die drei angeforderten Records
über genau drei gefilterte SQL-Abfragen. SQLite verwendet alle drei Indizes
aus `0006_ebook_evidence_lookup_indexes`; der isolierte Read blieb unter dem
Regression Guard von zwei Sekunden. Feste Grenzen von 1.024
`ToolExecution`-, 16.384 `ToolResult`- und 4.096 `Fingerprint`-Records
verhindern eine unbeschränkte Historienladung.

Die gezielte Korpus-, Evidence-, Migrations- und Vergleichssuite bestand mit
12 Tests in 2 Minuten 39 Sekunden. `ruff check .` war erfolgreich; Mypy
prüfte 77 Source-Dateien ohne Befund. Der vollständige Stand bestand alle 229
Pytest-Tests in 15 Minuten 46 Sekunden.

Das Wheel
`C:\rep\artifacts\FolioTone\w3-014-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`8c39c43917d55fbd7e241cc6b4610afc64642a0f5b92b3032f8f92fc8605a3a3`
und enthält `persistence/evidence_queries.py`, Alembic
`0006_ebook_evidence_lookup_indexes` sowie den aktualisierten
Paarvergleich.

**Empirisch für W3-015:** Sieben gezielte Batch-Integrationstests bestätigen
den stabil gefilterten Multi-Format-Plan, kontrolliertes `--max-items`-
Unterbrechen, exaktes Resume ohne Wiederholung abgeschlossener Items,
per-File-Fehlerfortsetzung ohne Pfadleck, eine Workergrenze, Lease-Konflikt und
stale Claim Recovery sowie `Ctrl+C`-Resume. Der synthetische Skalierungsfall
plant 1.201 Beobachtungen über genau einen gestreamten SELECT und drei
begrenzte Inserts mit 500, 500 und 201 Items. Die Suite bestand in 1 Minute
20 Sekunden.

Die fünf gezielten CLI-/Bootstrap-Tests bestanden in 28 Sekunden. Sie prüfen
eine kontrollierte Teil-Invocation, Resume, path-freie Summen, unveränderte
Source-Dateien und die Ablehnung beschreibbarer Runtime-Pfade innerhalb des
Source Root. Der thread-sichere, ausschließlich im Batch-Modus aktivierte
Tool-Versionsprobe-Cache bestand seinen erneuten Parallelitätstest. Ruff war
für den aktuellen Source-Stand erfolgreich; Mypy prüfte 82 Source-Dateien
ohne Befund. Der vollständige W3-015-Stand bestand mit Python 3.12.10 alle
239 Pytest-Tests in 18 Minuten 43 Sekunden. Der maschinenlesbare JUnit-Bericht
liegt außerhalb von Git unter
`C:\rep\artifacts\FolioTone\w3-015-test-results\pytest-full.xml`.

Das Wheel
`C:\rep\artifacts\FolioTone\w3-015-wheel-01\foliotone-0.1.0-py3-none-any.whl`
ist 134.583 Byte groß, hat SHA-256
`3a4d98aa852769c83dc2019f1e986cbacd41931ec38558f38b02ef6b3fd99a2e`
und enthält Collection-Domainmodell, Persistenz, Workflow und Alembic
`0007_ebook_collection_batches`.

**Remote für W3-015:** Commit
`9a6b2d1ace10b1ef57c4402439ba782ede233b04` bestand in PR #25 Ruff, Mypy,
239 Pytest-Tests und alle Docker-Smoke-Schritte. Der PR wurde als Merge-Commit
`fe3672a7002137859607dacb12072eeae35e268a` nach `main` übernommen; GitHub
Actions Run `31900550819` war erfolgreich. Die dabei sichtbare dreifache
Vollausführung durch Branch-Push, Pull Request und Main-Push wird im
nachfolgenden CI-Vertrag auf einen autoritativen PR-Gate plus kurzen
Post-Merge-Vertrag reduziert.

**CI-Ausführungsvertrag:** Commit
`0237861bb1a02455fa65d2a5f754e46bb4530d92` bestand als PR #26 genau einen
vollständigen `quality`-Lauf. Merge-Commit
`111267f8a3c66e629cfd4b61d006c1731a9d9b12` löste auf `main` nur den
dreisekündigen `post-merge-contract` in GitHub Actions Run `31900986647` aus;
der vollständige Job wurde dort übersprungen.

**Empirisch für W3-016:** `ebook-collection-report/v1` erzeugt für einen
persistierten nicht aktiven Collection-Lauf byte-stabile private JSON-,
Review-CSV-, Exact-Duplicate-CSV-, Content-Variant-CSV- und Checksum-
Artefakte. Der Bericht enthält vollständige Format-/Analyse-/Quality-/Befund-
Summen, eine begrenzte priorisierte Review-Liste und getrennte technische
Kandidatengruppen. Rohe Fingerprints werden nicht ausgegeben; Findings
behalten ihre exakten verfügbaren `ToolExecution`-Quellen. Der Befehl öffnet
keine Source Media und erzeugt keine `Relation` oder Identitätsentscheidung.

Der gezielte Berichtstest bestand nach der finalen Projektionsprüfung in 21,33
Sekunden und prüft unter anderem
Determinismus, Begrenzung/Truncation, Provenance, Checksum-Integrität,
CSV-Formelneutralisierung, path-freie CLI-Ausgabe und unveränderte
synthetische Source-Dateien. Der direkt betroffene Head-Migrationstest bestand
in 19,38 Sekunden. Ruff war für die geänderten Source-/Testdateien
erfolgreich; Mypy prüfte 85 Source-Dateien ohne Befund. Ein weiterer
vollständiger lokaler Pytest-Lauf wurde gemäß dem schlanken Prüfvertrag nicht
wiederholt; der vollständige Gate läuft einmal am Pull Request.

Das Wheel
`C:\rep\artifacts\FolioTone\w3-016-wheel-01\foliotone-0.1.0-py3-none-any.whl`
ist 147.477 Byte groß, hat SHA-256
`7b69ea169d1f07adfe1780a4acc91ee19ef6298b51237c45dc85142a164a0482`
und enthält Report-Query, Workflow, CLI-Anbindung und Alembic
`0008_ebook_collection_reports`.

## Aktiver W3-Stand und nächster Schritt

W2 ist abgeschlossen; `W3-001` bis `W3-016` sind abgeschlossen. W3-015 stellt
den fortsetzbaren Collection-Plan bereit. W3-016 ergänzt
`ebook-collection-report/v1`, die CLI `ebook-collection-report`, persistierte
Item-Ausführungs-/Befundprovenance und Alembic
`0008_ebook_collection_reports`. Berichtabfragen streamen sortierte
Kandidatendaten, halten nur begrenzte Detailmengen und weisen vollständige
Gesamtzahlen sowie Kürzungen aus.

`W3-017` ist `NEXT`: Die bestätigte lokale E-Book-Sammlung wird zuerst in
einem read-only Pilotlauf und danach vollständig analysiert und berichtet.
Music W4 bleibt geplant, aber bis zur E-Book-Reife zurückgestellt. Die
Produktoberfläche bleibt ausschließlich die CLI.

## Nicht implementiert

Noch nicht vorhanden sind unter anderem:

- weitere Formate außerhalb der expliziten EPUB/MOBI/AZW/AZW3-Text-Allowlist
  sowie alle Music-ToolProvider;
- calibre Library Reconciliation;
- Entity Resolution Engine;
- externe Knowledge Provider und Provider Cache;
- Classification Engine;
- Matching Engine;
- vollständiger realer Sammlungslauf und zusätzliche qpdf-Struktur-Evidence;
- Review System;
- Consolidation Planning und Execution;
- Web-API, Desktop-Oberfläche oder Dashboard; die aktuelle Produktoberfläche ist gemäß ADR-0016 ausschließlich die CLI.

## Sicherheitsgrenze

W10 bleibt ausdrücklich blockiert. Es gibt keine FolioTone-native oder externe Tool-Operation zum Löschen, Verschieben, Umbenennen oder Retaggen von Source Media.

`DELETED`, `FileRelocationCandidate` und Scan-Resume sind ausschließlich Analyse-/Orchestrierungszustände. W9 darf später ausschließlich nicht ausführbare `ConsolidationPlan`-Einträge erzeugen.
