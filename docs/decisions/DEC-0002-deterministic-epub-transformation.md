# DEC-0002: Deterministische EPUB-Transformation in einen getrennten Output-Root

- Status: Proposed
- Datum: 2026-08-25
- Artefakt: `urn:uuid:01a037f5-a7ed-7ca5-9663-152268a2b2b9`
- Entscheidungsgate: `GATE-0001`
- geplante Umsetzung: `WI-0004`

## Kontext

ADR-0065 und W9-007 liefern bereits immutable, content-addressed und dauerhaft
`NOT_EXECUTABLE` bleibende Rezepte für `FORMAT_TRANSFORM`. Sie entscheiden
weder einen konkreten ToolProvider noch eine W10-Capability, einen ausführbaren
Befehl oder die Veröffentlichung erzeugter Dateien.

Für eine ausführbare Transformation sind Reproduzierbarkeit, Metadatenumfang,
Tool- und Containeridentität, Output-Root, Collision Handling, Fencing,
Verifikation und Recovery gemeinsam zu entscheiden. Ein vorhandener
read-only calibre-Adapter oder der EPUB-Titelwriter darf nicht stillschweigend
zum allgemeinen Transformationsbackend erweitert werden.

## Vorgeschlagener Produktvertrag

Version 1 verarbeitet genau eine EPUB-3-Primärquelle und erzeugt eine neue
normalisierte EPUB-3-Ableitung. Die Quelle bleibt bytegleich. Das Ziel liegt in
einem getrennten, verwalteten E-Book-Output-`ScanRoot`; derselbe Source-Slot,
ein Source-Replacement und ein bereits vorhandenes Ziel sind unzulässig.

Die Ableitung darf ausschließlich Metadatenwerte einbetten, deren Auswahl
durch aktuelle kompatible Review-Evidence als `CANONICAL` oder
`USER_CONFIRMED` gebunden ist. Der Transformationsvertrag benötigt dafür einen
eigenen immutable Metadaten-Snapshot. Nicht ausgewählte Felder, normalisierter
Text, Lesereihenfolge und Cover-Evidence müssen im festgelegten
Äquivalenzprofil erhalten bleiben. Ein Tool-Exitcode allein ist kein
Erfolgsnachweis.

Dry Run und Replay müssen bei identischem Input, Toolchain-Image,
Tool-/Adapterversion und Konfigurationsfingerprint exakt dieselbe Bytelänge und
denselben vollständigen SHA-256 erzeugen. Diese Byte-Reproduzierbarkeit ist
eine harte Voraussetzung des vorhandenen W9-Outputvertrags und wird nicht auf
eine ungefähre semantische Gleichheit abgeschwächt.

## GATE-0001

`GATE-0001` qualifiziert vor jeder Writerimplementierung genau ein festes
Transformationsprofil mit ausschließlich synthetischen EPUB-Fixtures. calibre
9.13.0 aus dem gelockten E-Book-Toolchain-Image ist der erste Kandidat, aber
nicht vorab akzeptiert. Das Gate prüft mindestens:

- wiederholte byteidentische Ergebnisse in getrennten frischen, netzlosen
  Containerläufen;
- feste Command Shape ohne freie Optionen, Shell oder Host-Environment;
- Input-/Output-, Zeit-, Locale-, Image-, Tool-, Adapter- und
  Konfigurationsbindung;
- aktuelle offizielle Maintenance-, Automations-, Lizenz- und
  Security-Bedingungen;
- Ressourcenlimits, private Workspace-Grenze und bösartige EPUB-Fixtures;
- EPUBCheck-, Metadaten-, Text-, Lesereihenfolge-, Cover- und
  Preserved-Field-Verifikation.

Scheitert die exakte Reproduzierbarkeit, bleibt `DEC-0002` vorgeschlagen und
`WI-0004` blockiert. Dann benötigt eine FolioTone-eigene kanonische
EPUB-Verpackungsstufe oder ein anderer ToolProvider eine neue dokumentierte
Bewertung; das Gate wählt keine unbewiesene Alternative.

## Geplante W10-Kette

Nach einem akzeptierten Gate entstehen getrennte Waves für den erweiterten
W9-Transformations- und Metadaten-Snapshot, privaten Dry Run, immutable
Preparation/Authorization/Run/Event-Persistenz, eine enge Input-/Output-
Capability, rootübergreifendes Lease/Fencing, netzlosen Replay und
Target-absent/no-follow/no-replace-Publish.

Eine höchstens 15 Minuten gültige Authorization und eine exakte, nicht
geloggte Einzelbestätigung binden genau einen Output. Bounded Batch darf
ausschließlich Vorschau- und Dry-run-Jobs sammeln; Review, Authorization und
Publish bleiben pro Datei. Recovery darf private Stagingdaten verwerfen, einen
bereits exakt veröffentlichten Output reconciliieren oder einen fehlenden
Output erneut erzeugen. Ein abweichender vorhandener Output endet ohne
Mutation bei `MANUAL_REVIEW`. Delete, Overwrite, Purge, Source-Rewrite und
automatischer Batch-Publish bleiben ausgeschlossen.

CLI wird vor der Job-/REST-/Browser-Adaptierung geliefert. Der `surface-api`
erhält weder Source-/Output-Mount noch Capability; nur der netzlose
`operator-worker` darf nach Revalidierung die operation-spezifische Capability
auflösen. Diese vorgeschlagene Entscheidung ist bis zum positiven
`GATE-0001` keine W10-Authorization.
