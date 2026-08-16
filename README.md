# FolioTone

---
---
# ⚠️ READ BEFORE USE

## License notice

**NOTICE: This software is NOT Open Source. Use is governed by a custom Community & Attribution License.**

1. **NO RESALE:** Selling or charging for access to this software is strictly prohibited.
2. **ATTRIBUTION REQUIRED:** You must preserve the copyright notice for **gecompat - Gerhard Pisch**.
3. **NO LIABILITY:** Use this software at your own risk. The author is **NOT liable** for any damages, data loss, or business interruptions.

Full legal terms can be found in the [LICENSE.md](./LICENSE.md) file.

---
## Lizenzhinweis

**NOTIZ: FolioTone ist keine Open-Source-Software. Die Nutzung richtet sich nach der projektspezifischen Community & Attribution License.**

1. **NO RESALE:** Der Verkauf der Software und das Entgelt für den Zugang zur Software sind untersagt.
2. **ATTRIBUTION REQUIRED:** Der Copyright-Hinweis für **gecompat – Gerhard Pisch** muss erhalten bleiben.
3. **NO LIABILITY:** Die Nutzung erfolgt auf eigenes Risiko; der Autor **haftet nicht** für Schäden, Datenverlust oder Betriebsunterbrechungen.

Maßgeblich ist der vollständige Wortlaut in [LICENSE.md](./LICENSE.md).

# ⚠️ READ BEFORE USE

---
---

FolioTone ist eine **Orchestration- und Reconciliation-Plattform für große E-Book- und Musiksammlungen**. Das Projekt verbindet etablierte Spezialwerkzeuge und strukturierte Wissensquellen, normalisiert deren Ergebnisse als Provenance-erhaltende Evidence und baut darauf Entity Resolution, Duplicate Matching, Qualitäts-/Vollständigkeitsanalysen, Review und später sichere Consolidation Plans auf.

## Aktueller Stand

FolioTone hat **W2 — Incremental Index + Filename/Path Context + Tool Runtime**
abgeschlossen. In W3 sind die E-Book-Toolchain-Bewertung, feste read-only
calibre-/Poppler-Analysepfade für EPUB, MOBI, AZW, AZW3 und PDF sowie die
Provenance-erhaltende OPF2-/OPF3-Metadatenprojektion und ein versionierter,
synthetischer E-Book-Vergleichskorpus umgesetzt. `W3-008` ergänzt feste
read-only EPUBCheck-Konformitäts-Evidence. `W3-009` ergänzt optionale,
quellisolierte Embedded-Cover-Extraktion und einen versionierten
FolioTone-dHash. `W3-010` bündelt die vorhandenen Adapter formatabhängig im
read-only CLI-Befehl `ebook-analyze`, ohne Teilfehler oder Provenance zu
verdecken. `W3-011` ergänzt das Profil `ebook-analysis-workflow/v2`: Nur exakt
passende erfolgreiche Evidence mit reproduzierbaren Ableitungen und intakten
Pflichtartefakten wird wiederverwendet; sonst läuft ausschließlich der
betroffene Workflow-Schritt neu. `--fresh` erzwingt einen vollständigen neuen
Lauf. `W3-012` ergänzt `ebook-analysis-workflow/v3` und die separate Projektion
`ebook-quality/v1`: Metadaten, Text, Cover, Struktur und Formatrisiken werden
ohne skalaren Score und ohne Identitätsaussage als nachvollziehbare Dimensionen
und feste Befundcodes ausgegeben. `W3-013` ergänzt den read-only CLI-Befehl
`ebook-compare`: Persistierte Datei-, Text-, Metadaten-, Struktur- und Cover-
Evidence zweier Beobachtungen wird provider-neutral verglichen, ohne Source-
Zugriff, rohe Werte, Relation oder Identitätsurteil. Auf Benutzerentscheidung
bleibt die Entwicklung zunächst bei E-Books. `W3-014` ergänzt einen
synthetischen Multi-Format-/Sparse-/Malformed-Korpus und ersetzt
collection-weite Vergleichsreads durch begrenzte, indexgestützte Evidence-
Abfragen. `W3-015` ergänzt den fortsetzbaren CLI-Collection-Batch über einen
stabilen abgeschlossenen Scan-Snapshot, begrenzte Worker, per-File-
Fehlerfortsetzung und exakte Evidence-Wiederverwendung. `W3-016` ergänzt den
deterministischen privaten CLI-Sammlungsbericht ohne erneuten Source-Zugriff
und ohne Identitätsurteil. `W3-017` härtet den realen read-only
Collection-Betrieb: unveränderte Hash-Evidence wird ohne erneuten Source-Read
übernommen, Scan- und Fingerprint-Batches werden begrenzt parallel und
set-orientiert persistiert, verwaiste `RUNNING`-Scans sind über eine
abgesicherte Lease ausdrücklich wiederherstellbar, und Pilotpläne können alle
vorhandenen Formate abdecken. Vollständiges SHA-256 wird selektiv auf Quick-
Duplikatkandidaten begrenzt. Ein scanweiter privater Inventarbericht liefert
Format-/Größenverteilung, Hash-Abdeckung, offene Quick-Kandidaten und exakt
bestätigte Duplikatgruppen bereits vor der vollständigen Tiefenanalyse. Die
Music-Toolchain bleibt zurückgestellt.

W0 bis W2 stellen die verifizierte technische Grundlage bereit:

- persistente logische `ScanRoot`-Identitäten und `ScanRun`-Lifecycle;
- streaming Filesystem Discovery;
- NEW, UNCHANGED, MODIFIED, MISSING, REAPPEARED und opt-in DELETED;
- konservative `FileRelocationCandidate`-Evidence, auditable Resume-Lineage
  und wiederherstellbare `ScanRun`-Leases;
- gestuftes Quick-/Full-SHA-256-Hashing;
- Alembic-Migrationen für Incremental Index, Abwesenheitsstatus, Relocation-Kandidaten und Resume-Lineage;
- versionierte Filename-/Path-Kandidaten und konfigurierbare Regex-Parsing-Profile;
- generische read-only ToolProvider Runtime für lokale Prozesse und gehärtete Containerläufe;
- `ToolArtifact`-Persistenz für stdout/stderr, begrenzte JSON-Auswertung und konservative Reanalyse-Entscheidungen;
- read-only `foliotone scan` CLI;
- allowlist-basierter Docker-Build-Kontext ohne lokale `data/`- oder `media/`-Inhalte;
- Custom Community & Attribution License;
- verbindliche Dokumentations-, Sprach- und Terminologieregeln.

Der aktive W3-Stand ergänzt die CLI-Analyse und ihre Testgrundlage:

- feste read-only calibre-Metadaten- und Textpfade für EPUB/MOBI/AZW/AZW3;
- feste Poppler-PDF-Metadaten-, Seiten- und Textanalyse;
- feste read-only EPUBCheck-Konformitätsanalyse mit begrenzter JSON-Evidence;
- einen FolioTone-eigenen normalisierten E-Book-Textfingerprint;
- optionale Embedded-Cover-Fakten und einen FolioTone-eigenen, versionierten
  `EBOOK_COVER_DHASH` für EPUB/MOBI/AZW/AZW3;
- einen einheitlichen, formatbewussten `ebook-analyze`-Workflow für EPUB,
  MOBI, AZW, AZW3 und PDF mit explizitem `PARTIAL_FAILURE`;
- konservative exakte Evidence-Wiederverwendung, gezielten Schritt-Retry,
  sichtbare `REUSED`-/`EXECUTED`-Aktionen und einen expliziten `--fresh`-Modus;
- ein versioniertes `EbookQualityAssessment` mit `METADATA`, `TEXT`, `COVER`,
  `STRUCTURE` und `FORMAT_RISK`, festen Befundcodes und getrennten Zuständen
  für unvollständige Analyse, Review und erforderliche Maßnahmen;
- `ebook-comparison/v1` und CLI `ebook-compare` mit getrennten Zuständen und
  Evidence-Coverage für Datei-Bytes, normalisierten Text, Metadaten, Struktur
  und Cover, ausdrücklich ohne Match- oder Identitätsentscheidung;
- begrenzte, indexgestützte Observation-Evidence-Abfragen mit festen
  Historiengrenzen statt collection-weiter Vorabladung;
- `ebook-collection-analysis/v1` und CLI `ebook-collection-analyze` mit
  persistentem Plan, Lease, kontrollierter Teil-Invocation und Resume ohne
  erneute Planung abgeschlossener Items sowie `--plan-per-format` für
  begrenzte heterogene Piloten;
- `ebook-collection-report/v1` und CLI `ebook-collection-report` mit
  vollständigen Summenzählern, priorisierten Review-Items sowie begrenzten
  Exact-Duplicate- und Content-Variant-Kandidaten in privaten
  JSON-/CSV-/Checksum-Artefakten;
- `ebook-duplicate-hash/v1` und CLI `ebook-hash-candidates` für begrenztes,
  fortsetzbares vollständiges SHA-256 ausschließlich bei aktuellen
  mehrfach belegten Quick-Fingerprint-Gruppen;
- `ebook-inventory-report/v1` und CLI `ebook-inventory-report` für einen
  deterministischen scanweiten Format-, Größen-, Hash-Abdeckungs- und
  Exact-Duplicate-Bericht ohne erneuten Source-Media-Zugriff;
- rohe OPF-Beobachtungen und versionierte, gruppierte Kandidaten für ISBN und
  andere Identifier, Contributors/Rollen/Sortiernamen, Sprache, Verlag,
  Publikationsdatum, Serie und weitere Felder;
- exakte Links jedes Metadatenkandidaten auf `ToolExecution` und
  `FileObservation`, ohne automatische Kanonisierung oder Entity Resolution;
- einen reproduzierbaren Vergleichskorpus für byte-identische Dateien,
  Metadatenänderungen, dieselbe `Edition`, Übersetzungen und widersprüchliche
  Tool-Beobachtungen sowie einen additiven v2-Korpus für alle fünf
  unterstützten Formate, Sparse-/Malformed-Evidence und kalibrierte Cover-
  Distanzen, ohne eine Matching Engine vorwegzunehmen.

Die anfängliche Produktoberfläche bleibt ausschließlich die CLI. Eine Web-API, Desktop-Oberfläche oder ein Dashboard gehört nicht zum aktuellen Scope. [ADR-0016](docs/decisions/ADR-0016-cli-first-product-surface.md) hält diese Entscheidung fest.

Siehe außerdem [Projektstatus](docs/planning/PROJECT_STATUS.md), [Backlog](docs/planning/BACKLOG.md) und [Dokumentationsübersicht](docs/README.md).

## Positionierung: Spezialisten orchestrieren statt neu erfinden

FolioTone prüft vor einer eigenen format- oder medienspezifischen Implementierung, ob eine gepflegte Spezialsoftware die Aufgabe bereits über eine stabile dokumentierte Schnittstelle zuverlässig lösen kann.

Wichtige ToolProvider-Kandidaten sind:

- calibre CLI / Content Server für E-Book-Metadaten und Library-Zugriff;
- FFmpeg / `ffprobe` für technische Media-Observations;
- Chromaprint / `fpcalc` für Acoustic Fingerprints;
- beets für Musik-Metadaten, Duplicate- und Completeness-Evidence;
- SongKong für optionale automatisierte Status-/Report-/Preview-Evidence;
- MusicBrainz Picard als optionaler zusätzlicher Validator;
- später optional ein lokaler MusicBrainz-Mirror, wenn Sammlung und Last den Infrastrukturaufwand rechtfertigen.

Diese Werkzeuge bleiben austauschbare Spezialisten. Ihre Ergebnisse werden zu Evidence. FolioTone behält Provenance, Cross-Tool Reconciliation, Entity Resolution, Canonical Decisions, Matching, Review Knowledge und Safety.

Siehe [External Analysis Tools](docs/reference/EXTERNAL_TOOLS.md) und [ADR-0010](docs/decisions/ADR-0010-tool-provider-orchestration.md).

## Kernprinzipien

- Python 3.12+; Docker/Linux ist der primäre Runtime-Kontext.
- Die anfängliche Produktoberfläche ist ausschließlich die CLI; die CLI bleibt ein dünner Adapter zu Anwendungs- und Core-Verträgen.
- Runtime State liegt host-persistent unter `/data`.
- Source Media wird read-only unter `/media` eingebunden.
- SQLite ist die initiale Persistence Engine; SQLAlchemy Core und Alembic bleiben auf die Persistence-Schicht begrenzt.
- External Tool-/Provider-Ergebnisse sind Evidence und keine ungeprüfte kanonische Wahrheit.
- Observed, Derived, External, Canonical und User-confirmed Values bleiben getrennt und nachvollziehbar.
- Autoren, Interpreten und Komponisten werden als `Agent`-Identitäten mit Rollen modelliert.
- Buch-`Work`/`Edition` und Musik-`MusicWork`/`Recording`/`ReleaseGroup`/`Release` bleiben getrennte Identitätsebenen.
- Matching ist kandidatengesteuert, versioniert, erklärbar und reviewbar.
- Source-Media-Mutationen bleiben bis W10 blockiert.

## Zielarchitektur

```text
                      Specialist tools
       calibre / ffprobe / fpcalc / beets / SongKong / Picard
                              |
                              v
                         ToolProviders
                              |
Filesystem -> Index -> Parsing -> Media analysis/orchestration
                              |
                              +----------------------+
                              |                      |
                              v                      v
                   Knowledge Providers        Tool Evidence
                              |                      |
                              +----------+-----------+
                                         v
                              Authority / Entity Resolution
                                         |
                                         v
                                  Classification
                                         |
                                         v
                                  Matching Engine
                                         |
                                         v
                                       Review
                                         |
                                         v
                            Consolidation Planning (W9)
                                         |
                                         v
                          [future gated execution: W10]
```

## W1/W2 Foundation

```text
Core identity
  Agent / AgentName / ExternalIdentifier / Contribution
  Work / Edition / Series / SeriesMembership
  MusicWork / Recording / ReleaseGroup / Release / ReleaseRecording

Physical/index
  ScanRoot / ScanRun / FileRecord / FileObservation / FileScanEvent
  NEW / UNCHANGED / MODIFIED / MISSING / REAPPEARED / opt-in DELETED
  FileRelocationCandidate / ScanRun resume lineage / recoverable lease
  Quick Fingerprint / streamed SHA-256

Parsing
  FilenameParser / PathContextAnalyzer / RuleBasedFilenameParser
  versioned FilenameParsingProfile / FilenameParsingRule

Evidence
  Provenance / ValueAssertion
  ClassificationAssertion / Fingerprint / Relation / Evidence

Tool orchestration
  ToolProviderDescriptor / ToolExecution / ToolResult / ToolArtifact
  LocalCommand / ContainerCommand / ToolRuntime
  bounded strict-JSON Artifact loading / conservative re-analysis decision

Persistence
  Repository[T] / SQLiteRepository[T]
  SQLAlchemy Core
  Alembic 0001_initial through 0009_scan_run_leases
```

## Repository-Dokumentation

- [`AGENTS.md`](AGENTS.md) — verbindlicher Arbeitsvertrag für KI-Systeme und Contributors.
- [`docs/README.md`](docs/README.md) — aufgabenorientierter Dokumentationsindex.
- [`docs/quality/DOCUMENTATION_STYLE.md`](docs/quality/DOCUMENTATION_STYLE.md) — verbindlicher Schreibstil.
- [`docs/quality/LANGUAGE_AND_TERMINOLOGY.md`](docs/quality/LANGUAGE_AND_TERMINOLOGY.md) — Sprach- und Terminologieregeln.
- [`docs/reference/GLOSSARY.md`](docs/reference/GLOSSARY.md) — kanonische Fachbegriffe.
- [`docs/reference/EXTERNAL_TOOLS.md`](docs/reference/EXTERNAL_TOOLS.md) — ToolProvider-Kandidaten und Integrationsregeln.
- [`docs/reference/EXTERNAL_DATA_SOURCES.md`](docs/reference/EXTERNAL_DATA_SOURCES.md) — externe Knowledge-Provider-Kandidaten.
- [`docs/planning/PROJECT_STATUS.md`](docs/planning/PROJECT_STATUS.md) — autoritativer aktueller Stand.
- [`docs/planning/BACKLOG.md`](docs/planning/BACKLOG.md) — Aufgaben und Status nach Welle.

## Qualitätstests

```bash
python -m pip install -e '.[dev]'
ruff check .
mypy src/foliotone
pytest
```

Docker:

```bash
docker compose build
docker compose run --rm foliotone status
```

GitHub Actions führt die vollständige Prüfung einschließlich Migration im
gebauten Image, persistentem `/data`-Write-Vertrag und mehrstufigem
Incremental-Scan genau einmal am Pull Request aus. Nach dem Merge nach `main`
läuft nur der kurze Merge-/Whitespace-Integritätsvertrag; ein erneuter
vollständiger Testlauf findet dort nicht statt.

## Safety Status

Der aktuelle Stand enthält keine Source-Media-Delete-, Move-, Rename-, Retag-, Calibre-Write- oder Consolidation-Execution-Operation. External ToolProvider bleiben durch W9 read-only. `MISSING` ist ausdrücklich keine `DELETED`-Bestätigung.

## License

FolioTone ist **nicht Open Source**. Die Nutzung richtet sich nach der projektspezifischen Community & Attribution License. Der vollständige und rechtlich maßgebliche Wortlaut steht in [LICENSE.md](./LICENSE.md).
