# FolioTone Dokumentationsübersicht

Die Dokumentation ist nach Nutzungssituation gegliedert. Für die Weiterentwicklung sind `AGENTS.md`, Projektstatus, Handover, Backlog und die relevanten ADRs maßgeblich. Für fachliche Nutzung führen Einstieg, Architektur und Referenzen von der allgemeinen Orientierung zu den technischen Details.

## Einstieg und aktueller Stand

1. [Projektstatus](planning/PROJECT_STATUS.md) beschreibt den tatsächlich implementierten Stand, Verifikation und nächste Arbeitsschritte.
2. [Handover](planning/HANDOVER.md) fasst den aktuellen Übergabepunkt für eine andere KI oder einen anderen Entwickler zusammen.
3. [Implementation Plan](planning/IMPLEMENTATION_PLAN.md) definiert die geplante Reihenfolge W0 bis W10.
4. [Backlog](planning/BACKLOG.md) enthält die konkreten Aufgaben und Statuswerte.
5. [E-Book-Roadmap W3-017 bis W9](planning/W3_017_EBOOK_ROADMAP.md) trennt den privaten Runtime-Cutover, synthetische Entwicklungs-Gates und die langfristige book-only Folgeplanung.
6. [E-Book-Endgame-Ausführungsplan](planning/EBOOK_ENDGAME_IMPLEMENTATION_PLAN.md) bündelt die bestehenden W-, E- und EA-Aufgaben in umsetzbare EB-Lieferpakete, ohne deren Status- oder ID-Hierarchie zu ersetzen.
7. [Spark-Arbeitspakete für die E-Book-Endgerade](planning/EBOOK_SPARK_WORK_PACKAGES.md) zerlegen geeignete EB-Teile in 53 begrenzte Pull-Request-Pakete mit Frontier-Gates, Tests und Abbruchbedingungen.
8. [Ausführungs-Prompt für die E-Book-Roadmap](planning/W3_017_EBOOK_ROADMAP_PROMPT.md) enthält den wiederverwendbaren Auftrag für einen neuen Codex-Thread.
9. [E-Book-Archive und kontrollierte Deduplizierung](planning/EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md) plant read-only Archivanalyse, lokale Passwortkandidaten, archive-aware Matching und die weiterhin gesperrte spätere W10-Ausführung.
10. [Lokaler W2-Smoke-Test](quality/LOCAL_SMOKE_TEST.md) dokumentiert den abgeschlossenen manuellen Windows-/Docker-Testpunkt mit ausschließlich synthetischen Dateien.

## Architektur

- [Architecture Overview](architecture/OVERVIEW.md) beschreibt Komponenten, Abhängigkeiten und Grenzen.
- [Domain Model](architecture/DOMAIN_MODEL.md) dokumentiert die fachlichen Identitätsebenen und Beziehungen.
- [Authority, Enrichment and Classification](architecture/AUTHORITY_ENRICHMENT_AND_CLASSIFICATION.md) trennt Authority Resolution, externe Anreicherung und Klassifikation.
- [Indexing and Matching](architecture/INDEXING_AND_MATCHING.md) beschreibt Indexierung, Kandidatenbildung und Matching-Prinzipien.
- [Persistence](architecture/PERSISTENCE.md) dokumentiert SQLite, SQLAlchemy Core, Alembic und Repository-Grenzen.
- [Safety](architecture/SAFETY.md) definiert die nicht destruktiven Sicherheits- und Datenschutzgrenzen.

## Externe Werkzeuge und Wissensquellen

- [External Analysis Tools](reference/EXTERNAL_TOOLS.md) führt mögliche `ToolProvider` wie calibre, ffprobe, Chromaprint, beets, SongKong und Picard auf.
- [Bewertung der E-Book-Toolchain](reference/EBOOK_TOOL_EVALUATION.md) hält den zeitgebundenen W3-Toolentscheid, die Calibre-Sicherheitsuntergrenze sowie die implementierten EPUB-/PDF-Analyse- und Strukturvalidierungsrollen fest.
- [External Data Sources](reference/EXTERNAL_DATA_SOURCES.md) dokumentiert Kandidaten für strukturierte Wissensquellen wie Open Library, GND, Wikidata, MusicBrainz und AcoustID.
- [Glossar](reference/GLOSSARY.md) definiert die kanonischen fachlichen Kernbegriffe von FolioTone.

Ein Eintrag in einer Tool- oder Provider-Registry ist keine automatische Abhängigkeit. Vor einer Integration werden aktuelle Primärdokumentation, Lizenz, Schnittstelle, Sicherheitsverhalten und Wartungsstatus erneut geprüft.

## Architekturentscheidungen

Die akzeptierten Entscheidungen liegen unter [`decisions/`](decisions/). Neue wesentliche Architekturentscheidungen werden als ADR dokumentiert; eine redaktionelle Änderung darf einen technischen Vertrag nicht stillschweigend ersetzen.

- [ADR-0016](decisions/ADR-0016-cli-first-product-surface.md) legt die CLI als anfängliche Produktoberfläche fest und verschiebt Web-API, Desktop-Oberfläche und Dashboard aus dem aktiven Scope.
- [ADR-0017](decisions/ADR-0017-provider-accepted-exit-codes.md) trennt einen adapter-akzeptierten Domain-Befund mit Nonzero-Exitcode von technischen Toolfehlern.
- [ADR-0018](decisions/ADR-0018-versioned-ebook-quality-profile.md) definiert das versionierte, mehrdimensionale E-Book-Qualitätsprofil ohne skalaren Score oder Identitätsaussage.
- [ADR-0019](decisions/ADR-0019-provider-neutral-ebook-evidence-comparison.md) definiert den read-only Vergleich persistierter Datei-, Text-, Metadaten-, Struktur- und Cover-Evidence ohne Match- oder Identitätsurteil.
- [ADR-0020](decisions/ADR-0020-bounded-ebook-evidence-queries.md) begrenzt Paarvergleichs-Evidence auf zielgerichtete, indexgestützte SQLite-Abfragen und definiert den synthetischen Skalierungsvertrag.
- [ADR-0021](decisions/ADR-0021-resumable-ebook-collection-analysis.md) definiert Snapshot-Plan, Lease, Workergrenzen, Resume und path-freie Zustände der Collection-Analyse.
- [ADR-0022](decisions/ADR-0022-deterministic-private-ebook-collection-reports.md) definiert persistierte Befundprovenance, begrenzte Duplicate-/Varianten-Kandidaten und deterministische private Collection-Berichte.
- [ADR-0023](decisions/ADR-0023-selective-duplicate-candidate-hashing.md) begrenzt vollständiges SHA-256-Hashing auf aktuelle Quick-Duplikatkandidaten und definiert den fortsetzbaren read-only Evidence-Vertrag.
- [ADR-0024](decisions/ADR-0024-deterministic-scan-wide-ebook-inventory-report.md) definiert den deterministischen scanweiten Bestands-, Hash-Abdeckungs- und Exact-Duplicate-Bericht ohne erneuten Source-Zugriff.
- [ADR-0025](decisions/ADR-0025-recoverable-scan-run-leases.md) definiert Heartbeats, Konkurrenzschutz und die explizite Recovery verwaister `RUNNING`-Scans ohne Änderung des Resume-I/O-Vertrags.

## Qualität, Sprache und Dokumentationsregeln

- [Verbindlicher Schreibstil](quality/DOCUMENTATION_STYLE.md) regelt fachliche Präzision, Nachvollziehbarkeit und den geschützten README-Lizenzblock.
- [Sprach- und Terminologierichtlinie](quality/LANGUAGE_AND_TERMINOLOGY.md) definiert Deutsch als kanonische erklärende Dokumentationssprache und schützt technische Literale vor Übersetzung.
- [Glossar](reference/GLOSSARY.md) ist die zentrale Terminologiequelle.
- [Lokaler W2-Smoke-Test](quality/LOCAL_SMOKE_TEST.md) dokumentiert den abgeschlossenen manuellen W2-Plattformtest.
- [Synthetischer E-Book-Vergleichskorpus v1](../tests/fixtures/ebook_comparison/v1/README.md) dokumentiert die ursprüngliche Ground Truth für spätere Matching-Tests.
- [Synthetischer E-Book-Vergleichskorpus v2](../tests/fixtures/ebook_comparison/v2/README.md) ergänzt Multi-Format-, Sparse-, Malformed-, Distanz- und Skalierungsfälle.

Automatische Dokumentationsprüfungen sind bewusst konservativ. Sie verhindern bekannte Regressionen wie Änderungen am geschützten Lizenzblock oder alte Projektnamen, ersetzen aber kein fachliches oder sprachliches Review.

## Empfohlene Leserichtung für neue Entwickler oder KI-Systeme

1. Root-`AGENTS.md` lesen.
2. `planning/PROJECT_STATUS.md` und `planning/HANDOVER.md` gegen den Repositorystand prüfen.
3. `quality/DOCUMENTATION_STYLE.md` und `quality/LANGUAGE_AND_TERMINOLOGY.md` lesen, bevor Dokumentationsfreitext geändert wird.
4. Für die aktuelle Aufgabe die relevanten Architektur- und ADR-Dokumente lesen.
5. Bei Tool- oder Provider-Arbeit zusätzlich die jeweilige Registry und aktuelle externe Primärdokumentation prüfen.
6. Code, Tests, Backlog und Projektstatus in einem konsistenten Stand halten.
