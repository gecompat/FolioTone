# FolioTone Dokumentationsübersicht

Die Dokumentation ist nach Nutzungssituation gegliedert. Für die Weiterentwicklung sind `AGENTS.md`, Projektstatus, Handover, Backlog und die relevanten ADRs maßgeblich. Für fachliche Nutzung führen Einstieg, Architektur und Referenzen von der allgemeinen Orientierung zu den technischen Details.

## Produktvision und langfristige Einordnung

- [Evidence-driven Collection Intelligence](vision/EVIDENCE_DRIVEN_COLLECTION_INTELLIGENCE.md) beschreibt als strategischer Entwurf die langfristige local-first Produktthese, Medienfolge und Informationsgrenzen. Das Dokument entscheidet keine neuen Architekturverträge oder Aufgabenstatus.
- [Future Capability Map](planning/FUTURE_CAPABILITY_MAP.md) ordnet strategische Fähigkeiten kollisionsfrei den bestehenden W-, EB-, EA-, CS- und FUT-Plänen zu. Die aktuelle Ausführungsfront steht ausschließlich im Backlog.
- [ADR-0042](decisions/ADR-0042-federated-object-identity-and-exchange.md) beschreibt als `Proposed` die noch zu entscheidenden Gates für portable Objekt-Lineage, bounded Austausch und konfliktbewusste Fusion mehrerer FolioTone-Systeme. Sie autorisiert keine Implementierung oder Mutation.
- [Persönliche Ideen und Gedankensammlungen](ideas/owner-notes/README.md) archivieren nichtkanonische Rohnotizen. Der Bereich ist im öffentlichen Repository ebenfalls öffentlich und darf keine vertraulichen Daten enthalten.

## Einstieg und aktueller Stand

1. [Projektstatus](planning/PROJECT_STATUS.md) beschreibt den tatsächlich implementierten Stand, Verifikation und nächste Arbeitsschritte.
2. [Handover](planning/HANDOVER.md) fasst den aktuellen Übergabepunkt für eine andere KI oder einen anderen Entwickler zusammen.
3. [Implementation Plan](planning/IMPLEMENTATION_PLAN.md) definiert die geplante Reihenfolge W0 bis W10.
4. [Backlog](planning/BACKLOG.md) enthält die konkreten Aufgaben und Statuswerte.
5. [E-Book-Roadmap W3-017 bis W9](planning/W3_017_EBOOK_ROADMAP.md) trennt den privaten Runtime-Cutover, synthetische Entwicklungs-Gates und die langfristige book-only Folgeplanung.
6. [E-Book-Endgame-Ausführungsplan](planning/EBOOK_ENDGAME_IMPLEMENTATION_PLAN.md) bündelt die bestehenden W-, E- und EA-Aufgaben in umsetzbare EB-Lieferpakete, ohne deren Status- oder ID-Hierarchie zu ersetzen.
7. [Kanonischer End-to-End-Plan der E-Book-Schreibpipeline](planning/EBOOK_WRITE_PIPELINE_PLAN.md) verbindet Scan, Analyse, Quality, Review, nicht ausführbare Korrektur-/Konsolidierungspläne, operation-spezifische W10-Gates, Verifikation und die spätere REST-/UI-Grenze. ADR-0061 erlaubt die kontrollierte Writer-Entwicklung, nicht aber eine pauschale reale Mutation.
8. [Atomare Arbeitspakete für die E-Book-Endgerade](planning/EBOOK_SPARK_WORK_PACKAGES.md) zerlegen geeignete EB-Teile in begrenzte Pull-Request-Pakete mit Frontier-Gates, Tests und Abbruchbedingungen; der Dateiname ist historisch, das aktuelle Routing ist vendor-neutral.
9. [Ausführungsauftrag für die aktuelle Wave](planning/W3_017_EBOOK_ROADMAP_PROMPT.md) verweist neue Coding-Agent-Tasks auf die kanonische Backlogfront; der Dateiname bleibt für bestehende Links erhalten.
10. [E-Book-Archive und kontrollierte Deduplizierung](planning/EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md) dokumentiert die abgeschlossene read-only Archivbasis, offene Extraction-/Secret-/Member-Byte-Gates und die getrennten W10-Grenzen.
11. [Lokaler W2-Smoke-Test](quality/LOCAL_SMOKE_TEST.md) dokumentiert den abgeschlossenen manuellen Windows-/Docker-Testpunkt mit ausschließlich synthetischen Dateien.
12. [E-Book-Toolchain unter Windows](operations/WINDOWS_EBOOK_TOOLCHAIN.md) beschreibt das explizite Docker-/WSL2-Provisioning und den formatspezifischen Doctor.

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
- [ADR-0026](decisions/ADR-0026-provider-access-and-cache-policy.md) trennt Providerzugriff und Cache-Policy, legt die kanonischen Literale fest und definiert die eindeutige Legacy-Abbildung des bisherigen Provider-Modus.
- [ADR-0027](decisions/ADR-0027-scan-root-write-lease-and-fencing.md) koordiniert alle rootbezogenen Runtime-Writer über eine gemeinsame `ScanRoot`-Lease mit monotoner Fence-Epoch.
- [ADR-0028](decisions/ADR-0028-persisted-resolution-and-review-core.md) definiert persistierte Resolution Candidates, materielle Evidence-Links und append-only Review-Entscheidungen.
- [ADR-0029](decisions/ADR-0029-bounded-ebook-candidate-blocking.md) definiert begrenztes read-only E-Book-Candidate-Blocking und book-only Relation Contracts.
- [ADR-0030](decisions/ADR-0030-versioned-ebook-matcher-profiles.md) definiert relation-spezifische E-Book-Matcherprofile und konservatives Review-Routing.
- [ADR-0031](decisions/ADR-0031-persisted-relation-candidates-and-review-reuse.md) definiert insert-only Relation-Candidate-Snapshots, konkrete Feature-Evidence und kompatible Matching-Review-Wiederverwendung.
- [ADR-0032](decisions/ADR-0032-bounded-offline-ebook-matching-workflow.md) definiert den begrenzten Offline-Matching-Workflow, path-freie Review-CLI und weiterhin deaktivierte bibliografische Auto-Confirmation.
- [ADR-0033](decisions/ADR-0033-read-only-calibredb-library-reconciliation.md) definiert die festen lokalen read-only `calibredb`-Shapes, konsistente Library-Snapshots sowie Calibre-Ownership- und Sidecar-Evidence.
- [ADR-0052](decisions/ADR-0052-immutable-archive-evidence-persistence.md) definiert die additive insert-only Archive-Evidence-Persistenz mit exakter Source-/Execution-/Wrapper-Lineage, Reuse und ScanRoot-Fencing.
- [ADR-0057](decisions/ADR-0057-docker-first-ebook-toolchain-provisioning.md) definiert das explizite, gelockte Docker-first-Provisioning der E-Book-Spezialwerkzeuge und deren pfadfreie Format-Readiness.
- [ADR-0058](decisions/ADR-0058-book-collection-state-and-local-projections.md) definiert die book-only Lieferfolge für rebuildbaren `CollectionState`, deterministischen Snapshot-Diff, begrenzte lokale Metadatensuche und mehrdimensionale `Library Health`.
- [ADR-0059](decisions/ADR-0059-collection-state-diff-and-metadata-query.md) definiert die festen Diff-Kategorien, den begrenzten Query-AST, den snapshotgebundenen Metadata-FTS-Index und das private Ausgabeprofil von `CS-02`.
- [ADR-0060](decisions/ADR-0060-multidimensional-library-health.md) definiert sieben unabhängige book-only Health-Dimensionen, feste Findings, insert-only Persistenz, bounded opaque Samples und den reproduzierbaren read-only Vergleich von `CS-03`.
- [ADR-0061](decisions/ADR-0061-controlled-ebook-write-development.md) hält die Owner-Freigabe für kontrollierte E-Book-Writer-Entwicklung mit synthetischen Fixtures fest und trennt sie von operation-spezifischer technischer und operativer Authorization.
- [ADR-0062](decisions/ADR-0062-non-executable-metadata-correction-plans.md) definiert immutable, content-addressed und reviewte `MetadataCorrectionCandidate`- und `MetadataCorrectionPlan`-Snapshots mit permanenter `NOT_EXECUTABLE`-Grenze.
- [ADR-0063](decisions/ADR-0063-bounded-epub-title-source-metadata-writer.md) entscheidet den ersten Source-Metadata-Writer ausschließlich für EPUB 3, einen `title`-`REPLACE`, einen lexikalischen rohwerterhaltenden Patch und Linux-`renameat2`-Exchange mit Same-Filesystem-Recovery.

## Qualität, Sprache und Dokumentationsregeln

- [Vendor-neutrale Wave-Orchestrierung](planning/AI_WORKFLOW.md) definiert Inventar, Isolation, Implementierung, Review, Git-Abschluss und Handover je Wave.
- [Modell- und Agenten-Routing](planning/MODEL_ROUTING_POLICY.md) definiert die Tiers `LOCAL`, `ECONOMICAL`, `BALANCED` und `FRONTIER` ohne dauerhafte Bindung an einen Anbieter oder Modellnamen.
- [Tool-Adapter für KI-Systeme](planning/AI_TOOL_ADAPTERS.md) beschreibt die dünne Discovery-Schicht für Codex, Copilot, Junie und Databricks Genie Code sowie die getrennte Rolle von Databricks Genie Agents.
- [Local-first-Teststrategie](quality/TEST_POLICY.md) definiert fokussierte lokale Nachweise und den einmaligen vollständigen PR-Gate.
- [Verbindlicher Schreibstil](quality/DOCUMENTATION_STYLE.md) regelt fachliche Präzision, Nachvollziehbarkeit und den geschützten README-Lizenzblock.
- [Sprach- und Terminologierichtlinie](quality/LANGUAGE_AND_TERMINOLOGY.md) definiert Deutsch als kanonische erklärende Dokumentationssprache und schützt technische Literale vor Übersetzung.
- [Kosten- und kontexteffiziente Entwicklung](quality/COST_EFFICIENT_DEVELOPMENT.md) definiert Local-first-Logauswertung, gestufte Tests, isolierte SQLite-Template-Kopien und begrenzte Agentenübergaben.
- [Glossar](reference/GLOSSARY.md) ist die zentrale Terminologiequelle.
- [Lokaler W2-Smoke-Test](quality/LOCAL_SMOKE_TEST.md) dokumentiert den abgeschlossenen manuellen W2-Plattformtest.
- [Synthetischer E-Book-Vergleichskorpus v1](../tests/fixtures/ebook_comparison/v1/README.md) dokumentiert die ursprüngliche Ground Truth für spätere Matching-Tests.
- [Synthetischer E-Book-Vergleichskorpus v2](../tests/fixtures/ebook_comparison/v2/README.md) ergänzt Multi-Format-, Sparse-, Malformed-, Distanz- und Skalierungsfälle.

Automatische Dokumentationsprüfungen sind bewusst konservativ. Sie verhindern bekannte Regressionen wie Änderungen am geschützten Lizenzblock oder alte Projektnamen, ersetzen aber kein fachliches oder sprachliches Review.

## Empfohlene Leserichtung für neue Entwickler oder KI-Systeme

1. Root-`AGENTS.md` lesen.
2. `planning/PROJECT_STATUS.md` und `planning/HANDOVER.md` gegen den Repositorystand prüfen.
3. `quality/DOCUMENTATION_STYLE.md` und `quality/LANGUAGE_AND_TERMINOLOGY.md` lesen, bevor Dokumentationsfreitext geändert wird.
4. `planning/AI_WORKFLOW.md`, `planning/MODEL_ROUTING_POLICY.md` und `quality/TEST_POLICY.md` vor Wave-, Modell-, Agenten- oder CI-Planung lesen.
5. `quality/COST_EFFICIENT_DEVELOPMENT.md` vor umfangreicher Test- oder Logauswertung lesen.
6. Für die aktuelle Aufgabe die relevanten Architektur- und ADR-Dokumente lesen.
7. Bei Tool- oder Provider-Arbeit zusätzlich die jeweilige Registry und aktuelle externe Primärdokumentation prüfen.
8. Code, Tests, Backlog und Projektstatus in einem konsistenten Stand halten.
