# FolioTone Dokumentationsübersicht

Die Dokumentation ist nach Nutzungssituation gegliedert. Für die Weiterentwicklung sind `AGENTS.md`, Projektstatus, Handover, Backlog und die relevanten ADRs maßgeblich. Für fachliche Nutzung führen Einstieg, Architektur und Referenzen von der allgemeinen Orientierung zu den technischen Details.

## Einstieg und aktueller Stand

1. [Projektstatus](planning/PROJECT_STATUS.md) beschreibt den tatsächlich implementierten Stand, Verifikation und nächste Arbeitsschritte.
2. [Handover](planning/HANDOVER.md) fasst den aktuellen Übergabepunkt für eine andere KI oder einen anderen Entwickler zusammen.
3. [Implementation Plan](planning/IMPLEMENTATION_PLAN.md) definiert die geplante Reihenfolge W0 bis W10.
4. [Backlog](planning/BACKLOG.md) enthält die konkreten Aufgaben und Statuswerte.
5. [Lokaler W2-Smoke-Test](quality/LOCAL_SMOKE_TEST.md) beschreibt den aktuellen manuellen Windows-/Docker-Testpunkt mit ausschließlich synthetischen Dateien.

## Architektur

- [Architecture Overview](architecture/OVERVIEW.md) beschreibt Komponenten, Abhängigkeiten und Grenzen.
- [Domain Model](architecture/DOMAIN_MODEL.md) dokumentiert die fachlichen Identitätsebenen und Beziehungen.
- [Authority, Enrichment and Classification](architecture/AUTHORITY_ENRICHMENT_AND_CLASSIFICATION.md) trennt Authority Resolution, externe Anreicherung und Klassifikation.
- [Indexing and Matching](architecture/INDEXING_AND_MATCHING.md) beschreibt Indexierung, Kandidatenbildung und Matching-Prinzipien.
- [Persistence](architecture/PERSISTENCE.md) dokumentiert SQLite, SQLAlchemy Core, Alembic und Repository-Grenzen.
- [Safety](architecture/SAFETY.md) definiert die nicht destruktiven Sicherheits- und Datenschutzgrenzen.

## Externe Werkzeuge und Wissensquellen

- [External Analysis Tools](reference/EXTERNAL_TOOLS.md) führt mögliche `ToolProvider` wie calibre, ffprobe, Chromaprint, beets, SongKong und Picard auf.
- [External Data Sources](reference/EXTERNAL_DATA_SOURCES.md) dokumentiert Kandidaten für strukturierte Wissensquellen wie Open Library, GND, Wikidata, MusicBrainz und AcoustID.
- [Glossar](reference/GLOSSARY.md) definiert die kanonischen fachlichen Kernbegriffe von FolioTone.

Ein Eintrag in einer Tool- oder Provider-Registry ist keine automatische Abhängigkeit. Vor einer Integration werden aktuelle Primärdokumentation, Lizenz, Schnittstelle, Sicherheitsverhalten und Wartungsstatus erneut geprüft.

## Architekturentscheidungen

Die akzeptierten Entscheidungen liegen unter [`decisions/`](decisions/). Neue wesentliche Architekturentscheidungen werden als ADR dokumentiert; eine redaktionelle Änderung darf einen technischen Vertrag nicht stillschweigend ersetzen.

## Qualität, Sprache und Dokumentationsregeln

- [Verbindlicher Schreibstil](quality/DOCUMENTATION_STYLE.md) regelt fachliche Präzision, Nachvollziehbarkeit und den geschützten README-Lizenzblock.
- [Sprach- und Terminologierichtlinie](quality/LANGUAGE_AND_TERMINOLOGY.md) definiert Deutsch als kanonische erklärende Dokumentationssprache und schützt technische Literale vor Übersetzung.
- [Glossar](reference/GLOSSARY.md) ist die zentrale Terminologiequelle.
- [Lokaler W2-Smoke-Test](quality/LOCAL_SMOKE_TEST.md) ist der derzeit maßgebliche manuelle Plattformtest.

Automatische Dokumentationsprüfungen sind bewusst konservativ. Sie verhindern bekannte Regressionen wie Änderungen am geschützten Lizenzblock oder alte Projektnamen, ersetzen aber kein fachliches oder sprachliches Review.

## Empfohlene Leserichtung für neue Entwickler oder KI-Systeme

1. Root-`AGENTS.md` lesen.
2. `planning/PROJECT_STATUS.md` und `planning/HANDOVER.md` gegen den Repositorystand prüfen.
3. `quality/DOCUMENTATION_STYLE.md` und `quality/LANGUAGE_AND_TERMINOLOGY.md` lesen, bevor Dokumentationsfreitext geändert wird.
4. Für die aktuelle Aufgabe die relevanten Architektur- und ADR-Dokumente lesen.
5. Bei Tool- oder Provider-Arbeit zusätzlich die jeweilige Registry und aktuelle externe Primärdokumentation prüfen.
6. Code, Tests, Backlog und Projektstatus in einem konsistenten Stand halten.
