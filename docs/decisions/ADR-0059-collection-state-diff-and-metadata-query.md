# ADR-0059: Deterministischer CollectionState-Diff und lokale Metadatensuche

- Status: Accepted
- Datum: 2026-08-22

## Kontext

ADR-0058 beauftragt für `CS-02` einen deterministischen Vergleich zweier
`CollectionState`-Snapshots und eine begrenzte lokale Metadatensuche. Für die
Implementierung müssen die genaue Diff-Semantik, der erlaubte Query-AST, die
Indexbindung, Pagination und private Ausgabe feststehen. Eine live gegen
veränderliche Tool-Ergebnisse ausgeführte Suche würde alte Snapshots
nachträglich umdeuten. Freies SQL oder ungeprüfte FTS-Syntax würde zudem die
lokale SQLite-Datenbank unnötig gefährden.

## Entscheidung

`CS-02` implementiert `collection-state-diff/v1` und `collection-query/v1`
book-only. Beide Pfade lesen ausschließlich lokale Persistenz. Sie öffnen
keine Source Media, starten keine Tools oder Provider, verwenden kein Netzwerk
und besitzen keine Mutation Authority.

### Snapshot-Diff

Ein Diff vergleicht genau zwei verschiedene `collection-state/v1`-Snapshots
desselben `ScanRoot`. Die Ausgabe ist nach opaque `File`-ID sortiert und
unterscheidet folgende feste Kategorien:

- `ADDED`;
- `DISAPPEARED`;
- `TECHNICALLY_CHANGED`;
- `NEWLY_ANALYZED`;
- `NEWLY_RESOLVED`;
- `NEWLY_REVIEWED`;
- `NEWLY_BLOCKED`.

Ein Element kann mehrere Kategorien tragen. `NEWLY_ANALYZED`,
`NEWLY_RESOLVED` und `NEWLY_REVIEWED` bedeuten nur, dass die jeweilige
Komponente von einem nicht aktuellen in einen aktuellen Zustand gewechselt
ist. `NEWLY_BLOCKED` bedeutet nur, dass Consolidation- oder Quarantäne-Evidence
erstmals einen Konfliktzustand im verglichenen Snapshot trägt.

Ein neuer `FileObservation` allein beweist keine technische Änderung.
`TECHNICALLY_CHANGED` wird deshalb nur bei verändertem Format, veränderter
Bytezahl oder bei verändertem technischen Evidence-Digest derselben
`FileObservation` ausgegeben. Weitere Ursachen werden nicht behauptet.

Der Report zählt den vollständigen Diff, gibt Details aber höchstens in Seiten
von 1 bis 1.000 Elementen aus. Der Keyset-Cursor ist die letzte opaque
`File`-ID. Er ist weder Offset noch Pfad.

### Query-AST

`collection-query/v1` akzeptiert genau einen JSON-AST mit `AND`- und
`OR`-Gruppen. `NOT`, Match-all, freie SQL-Fragmente, Spaltennamen und
ungeprüfte FTS-Syntax sind nicht erlaubt. Der Vertrag begrenzt den AST auf
höchstens vier Ebenen, 16 Prädikate, 256 Zeichen je Suchwert und 100 Treffer je
Seite. Die einzige Sortierung in v1 ist `FILE_ID_ASC`; Pagination verwendet
eine opaque `after_file_id`.

Die feste Feld-Allowlist lautet:

```text
file_id
observation_id
format
analysis_status
resolution_status
classification_status
matching_status
review_status
calibre_status
archive_status
consolidation_status
quarantine_status
finding_code
title
contributor
identifier
language
publisher
```

Alle Felder unterstützen `EQ`. Nur die fünf ausgewählten Metadatenfelder
`title`, `contributor`, `identifier`, `language` und `publisher` unterstützen
zusätzlich `PREFIX` und `MATCH`. FTS-Ausdrücke werden ausschließlich aus
normalisierten Worttokens erzeugt und als gebundene SQLite-Parameter
ausgeführt.

### Snapshotgebundener Metadatenindex

Migration `0024_collection_state_diff_query` ergänzt eine insert-only
`collection-query-index/v1`-Projektion. Sie bindet genau einen immutable
`CollectionState`-Snapshot und speichert:

- opaque File- und Observation-IDs;
- Format- und Komponentenzustände;
- aktuelle `EbookCollectionFinding`-Codes;
- ausgewählte, ausdrücklich nicht kanonische
  `ebook_metadata_candidate`-Werte;
- vollständige Counts, Coverage, Kürzungszustand und Content-Digests.

Der Index wird innerhalb derselben SQLite-Transaktion wie ein neuer
`CollectionState` erzeugt. Beim idempotenten Rebuild wird eine vorhandene
Projektion vollständig verifiziert oder für einen vor Migration `0024`
erzeugten Snapshot einmalig ergänzt. Werte und Parents sind danach durch
Update-/Delete-Trigger unveränderlich. Deklarierte Dokument- und Wertanzahlen,
begrenzte Ordinale und Eindeutigkeit sperren außerdem spätere Appends in einen
fertigen Index. FTS5 übernimmt ausschließlich Werte mit
`METADATA_CANDIDATE`; technische Filter und Finding-Codes bleiben in den
normalen Indexzeilen. Content-Volltext und OCR bleiben ausgeschlossen.

Pro Dokument werden höchstens 256 ausgewählte Metadatenwerte und 128
Finding-Codes aufgenommen. Zu lange oder überzählige Werte werden nicht
gekürzt oder umgedeutet, sondern ausgelassen und als `PARTIAL` sowie
`VALUE_LIMIT` gezählt.

### Privacy und Ausgabe

Maschinenlesbare Diff- und Query-Reports enthalten nur opaque IDs, feste
Literale, Counts, Profile, Coverage und Truncation-Marker. Suchwerte werden
nicht zurückgespiegelt und Query-History wird nicht persistiert.

`--private-details` ist ausschließlich mit interaktiver Textausgabe erlaubt.
Es zeigt nur ausgewählte lokale Metadaten-Candidates und kennzeichnet sie als
`METADATA_CANDIDATE`. Absolute POSIX- und Windows-Pfade werden auch dann
ausgefiltert. JSON-Ausgabe mit `--private-details` schlägt fail-closed fehl.

`collection-state-diff` und `collection-search` öffnen eine vorhandene
SQLite-Datenbank mit `mode=ro` und `query_only=ON`. Sie führen keine Migration
aus und legen weder Verzeichnis noch Datenbank an.

## Abnahme

Die Wave weist mindestens nach:

- deterministische Kategorien, Sortierung, Counts und Keyset-Seiten;
- Inkompatibilitäts- und Größenfehler ohne partielle Ausgabe;
- atomaren Index-Build, idempotente Wiederverwendung und insert-only Trigger;
- `EQ`, `PREFIX`, FTS-`MATCH`, `AND` und `OR` ausschließlich über validierte
  Felder und Operatoren;
- pfadfreie JSON-Ausgabe und explizite private Textausgabe;
- echte SQLite-Read-only-Ausführung;
- einen synthetischen Skalierungslauf mit mindestens 600 Dokumenten und
  Nutzung des FTS5-Virtual-Table-Index.

## Folgen

- Alte Snapshots behalten reproduzierbare Suchergebnisse, auch wenn später
  neue Tool-Evidence entsteht.
- Der lokale Index enthält private Metadaten und gehört wie die Runtime-
  Datenbank weder in Git noch in CI-Artefakte.
- `CS-03` kann Diff-, Status- und Finding-Evidence verwenden, ohne Query-Text
  oder private Metadaten in `Library Health` zu übernehmen.
- Eine spätere API, UI oder natürlichsprachliche Suche muss denselben
  validierten Application-Vertrag verwenden und benötigt weiterhin eine
  eigene Produktoberflächen- beziehungsweise Privacy-Entscheidung.

## Nicht autorisiert

Diese Entscheidung autorisiert keine Content- oder OCR-Indizierung, keine
Query-History, keine Netzwerk- oder Provider-Suche, keine Music-
Generalisierung, keine API, kein MCP, keine UI und keine Mutation.
