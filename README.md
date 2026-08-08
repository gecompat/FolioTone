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

FolioTone befindet sich in **W2 — Incremental Index + Filename/Path Context + Tool Runtime**.

W0 und W1 sind abgeschlossen. Der erste W2-Slice ist implementiert und in GitHub Actions verifiziert:

- persistente logische `ScanRoot`-Identitäten und `ScanRun`-Lifecycle;
- streaming Filesystem Discovery;
- NEW, UNCHANGED, MODIFIED, MISSING und REAPPEARED;
- gestuftes Quick-/Full-SHA-256-Hashing;
- Alembic `0002_incremental_index`;
- generische read-only ToolProvider Runtime für lokale Prozesse und gehärtete Containerläufe;
- `ToolArtifact`-Persistenz für stdout/stderr;
- read-only `foliotone scan` CLI;
- Custom Community & Attribution License;
- verbindliche Dokumentations-, Sprach- und Terminologieregeln.

Der nächste Schritt ist ein **lokaler Windows-/Docker-Smoke-Test**. Der Ablauf ist unter [Lokaler W2-Smoke-Test](docs/quality/LOCAL_SMOKE_TEST.md) dokumentiert. Danach werden die verbleibenden W2-Punkte wie `DELETED`-Bestätigung, Move/Rename-Erkennung und Filename/Path-Parsing fortgesetzt.

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
  NEW / UNCHANGED / MODIFIED / MISSING / REAPPEARED
  Quick Fingerprint / streamed SHA-256

Evidence
  Provenance / ValueAssertion
  ClassificationAssertion / Fingerprint / Relation / Evidence

Tool orchestration
  ToolProviderDescriptor / ToolExecution / ToolResult / ToolArtifact
  LocalCommand / ContainerCommand / ToolRuntime

Persistence
  Repository[T] / SQLiteRepository[T]
  SQLAlchemy Core
  Alembic 0001_initial + 0002_incremental_index
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

GitHub Actions prüft zusätzlich die Migration im gebauten Image, den persistenten `/data`-Write-Vertrag und einen mehrstufigen Incremental-Scan über getrennte Containerläufe.

## Safety Status

Der aktuelle Stand enthält keine Source-Media-Delete-, Move-, Rename-, Retag-, Calibre-Write- oder Consolidation-Execution-Operation. External ToolProvider bleiben durch W9 read-only. `MISSING` ist ausdrücklich keine `DELETED`-Bestätigung.

## License

FolioTone ist **nicht Open Source**. Die Nutzung richtet sich nach der projektspezifischen Community & Attribution License. Der vollständige und rechtlich maßgebliche Wortlaut steht in [LICENSE.md](./LICENSE.md).
