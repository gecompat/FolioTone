# Sprach- und Terminologierichtlinie

**Status:** verbindlich  
**Geltungsbereich:** Repository-Dokumentation, technische Erklärtexte und Übersetzungen

## Grundsatz

Die kanonische erklärende Projektdokumentation unter `docs/` wird grundsätzlich auf Deutsch verfasst. Etablierte technische Fachbegriffe, öffentliche Vertragswerte und Eigennamen bleiben in ihrer kanonischen Form erhalten, wenn eine Übersetzung die technische Eindeutigkeit verschlechtern würde.

Bestehende englische Dokumente müssen nicht allein aufgrund dieser Richtlinie übersetzt werden. Bei einer fachlichen Überarbeitung eines bestehenden englischen Dokuments ist zu entscheiden, ob es weiterhin ausdrücklich englischsprachig bleibt oder schrittweise in die kanonische deutsche Dokumentation überführt wird. Unverbundene Massenübersetzungen sind zu vermeiden.

## Technische Begriffe

Technische Bezeichner werden nicht künstlich eingedeutscht. Dazu gehören insbesondere:

- `ToolProvider`, `ToolExecution`, `ToolArtifact` und `ToolResult`;
- `Entity Resolution`, `Matching`, `Fingerprint`, `Evidence` und `Provenance`;
- `Work`, `Edition`, `MusicWork`, `Recording`, `ReleaseGroup` und `Release`;
- `ScanRoot`, `ScanRun`, `FileObservation` und `FileScanEvent`;
- `Dry Run`, `Cache`, `Container`, `CLI`, `API` und `DTO`;
- Produkt-, Provider- und Toolnamen wie calibre, MusicBrainz, Picard, beets, SongKong, FFmpeg und Chromaprint.

Der umgebende Erklärungstext bleibt deutsch. Beispiel:

> Ein `ToolProvider` kapselt die dokumentierte Automationsschnittstelle eines externen Werkzeugs. Das Ergebnis einer konkreten Ausführung wird mit `ToolExecution`-Provenance gespeichert.

## Öffentliche technische Literale

Folgende Inhalte werden niemals nur aus Übersetzungs- oder Stilgründen verändert:

- Enum- und Statuswerte wie `OBSERVED`, `DERIVED`, `EXTERNAL`, `CANONICAL` oder `USER_CONFIRMED`;
- `RelationType`-Werte wie `SAME_RECORDING` oder `SAME_EDITION`;
- CLI-Kommandos, Optionen und Environment Variables;
- Klassen-, Methoden-, Tabellen-, Spalten- und Feldnamen;
- Provider-, Tool-, Adapter-, Algorithmus- und Fingerprint-IDs;
- maschinenlesbare JSON-, YAML-, SQL- oder Konfigurationswerte.

Wenn eine technische Bezeichnung fachlich umbenannt werden soll, ist dies eine Vertragsänderung und keine Übersetzung.

## Kanonische Terminologie

Das Glossar unter `docs/reference/GLOSSARY.md` ist die zentrale Terminologiequelle für fachliche Kernbegriffe. Neue Synonyme für bereits definierte Konzepte werden nicht ohne fachlichen Grund eingeführt.

Ein Begriff darf in natürlicher Sprache erläutert werden, die technische Identität bleibt jedoch eindeutig. Beispielsweise kann `Recording` als „konkrete Aufnahme“ erklärt werden; `Recording` wird dadurch nicht in einen neuen technischen Typ `AufnahmeEntity` umbenannt.

## Übersetzungen

Wenn eine englische oder weitere Sprachfassung eines kanonischen Dokuments angelegt wird, gelten folgende Regeln:

1. Die kanonische Quelle wird im übersetzten Dokument eindeutig genannt.
2. Eine Übersetzung darf keine fachlichen Verträge ändern oder ergänzen.
3. Code, technische Literale, Enum-Werte, Pfade, Provider-IDs und CLI-Beispiele bleiben unverändert.
4. Tabellenstruktur und Abschnittsbeziehungen bleiben soweit sinnvoll vergleichbar.
5. Eine fachliche Änderung erfolgt zuerst in der kanonischen Quelle und anschließend in den Übersetzungen.
6. Bei einem Widerspruch gilt die ausdrücklich benannte kanonische Fassung.
7. Der Versions- oder Änderungsstand einer Übersetzung muss nachvollziehbar sein.

FolioTone erzeugt derzeit keine vollständige parallele englische Spiegel-Dokumentation. Eine solche Struktur wird erst eingeführt, wenn ein tatsächlicher Nutzungsbedarf den zusätzlichen Synchronisationsaufwand rechtfertigt.

## Ausnahmen

Die Root-README ist eine öffentliche Projekteinstiegsseite und darf englische Abschnitte enthalten. Der zweisprachige Lizenzblock am Anfang der Datei ist geschützt und wird nur auf ausdrücklichen Auftrag verändert.

`LICENSE.md` ist eine rechtliche Sonderregel. Entsprechend ihrem eigenen Wortlaut ist die englische Fassung die rechtlich bindende Master-Version; Übersetzungen besitzen dort nicht denselben Status.

Source-Code-Bezeichner und bestehende englische Docstrings müssen nicht aus Dokumentationsgründen übersetzt werden. Die Richtlinie betrifft primär erklärende Repository-Dokumentation.

## Präzision vor Mischsprache

Unklare halb übersetzte Kunstbegriffe sind zu vermeiden. Ein etablierter englischer Fachbegriff ist einer spontanen Mischform vorzuziehen.

Beispiele:

- `Entity Resolution` statt „Entitäten-Resolver-Verfahren“;
- `ToolProvider` statt „Tool-Anbieter-Plugin“;
- `Matching Engine` statt „Matching-Abgleichssystem“;
- `Review Queue` statt „Review-Warteschlangen-Engine“.

Eine deutsche Erklärung ist dennoch erwünscht, wenn sie die fachliche Bedeutung verbessert.

## Neue Begriffe

Vor der Einführung eines neuen fachlichen Kernbegriffs ist zu prüfen:

1. Existiert bereits ein Eintrag im Glossar?
2. Existiert ein etablierter Begriff im verwendeten Standard, Tool oder Datenmodell?
3. Bezeichnet der neue Begriff tatsächlich ein neues Konzept oder nur ein Synonym?
4. Muss der Begriff als öffentlicher technischer Vertrag stabil bleiben?

Neue kanonische Begriffe werden bei Bedarf gleichzeitig im Glossar dokumentiert.
