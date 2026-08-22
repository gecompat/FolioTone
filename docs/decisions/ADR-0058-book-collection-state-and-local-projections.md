# ADR-0058: Book-only CollectionState und lokale Produktprojektionen

- Status: Accepted
- Datum: 2026-08-22

## Kontext

FolioTone persistiert bereits Scan-, Analyse-, Quality-, Authority-,
Classification-, Matching-, Review-, Calibre-, Archive-, Consolidation- und
Quarantäne-Evidence. Die vorhandenen Reports beantworten jeweils eine
begrenzte technische Frage. Es fehlt jedoch eine gemeinsame, rebuildbare Sicht
auf den Zustand einer E-Book-Sammlung, auf der Zustandsvergleich, sichere
lokale Suche und eine mehrdimensionale `Library Health`-Auswertung aufbauen
können.

Die strategische Skizze in `FUTURE_CAPABILITY_MAP.md` reicht für eine
Implementierung nicht aus. Insbesondere sind Snapshot-Lineage, Staleness,
Privacy, Ausgabegrenzen und die Abhängigkeit zwischen den Produktprojektionen
noch nicht als verbindlicher Vertrag festgelegt.

## Entscheidung

FolioTone implementiert die nächsten book-only Produktprojektionen in drei
aufeinander aufbauenden Waves:

1. `CS-01` erzeugt `collection-state/v1` als immutable und vollständig
   rebuildbare Projektion über genau einen abgeschlossenen `ScanRun`;
2. `CS-02` ergänzt `collection-state-diff/v1` sowie einen validierten,
   begrenzten `collection-query/v1` für lokale Metadatensuche;
3. `CS-03` erzeugt `library-health/v1` aus unabhängigen, erklärbaren
   Zustandsdimensionen.

Diese Profile sind book-only. Eine spätere Music-Wave prüft, welche Teile
tatsächlich medienübergreifend stabil sind. Es wird kein universeller
`Asset`-Typ eingeführt.

## CollectionState v1

Ein `CollectionState`-Snapshot bindet mindestens:

- einen `ScanRoot` und genau einen erfolgreich abgeschlossenen `ScanRun`;
- das verwendete Collection-State-Profil;
- die einbezogenen Analyse-, Resolver-, Classification-, Matcher-, Review-,
  Calibre-, Archive-, Consolidation- und Quarantäne-Profilversionen;
- vollständige Summen sowie explizite Coverage-, Stale-, Conflict- und
  Truncation-Zustände;
- den kanonischen Content-Digest des Snapshots.

Der Builder öffnet keine Source Media, startet keine Tools oder Provider und
führt keine Mutation aus. Er liest ausschließlich persistierte Evidence. Ein
identischer Input erzeugt byteidentische kanonische Snapshotdaten. Geänderte
Evidence erzeugt einen neuen Snapshot; vorhandene Snapshots werden nicht
überschrieben.

Ein Snapshot behauptet keine zusätzliche Identity oder kanonische Metadaten.
Fehlende, widersprüchliche und technisch stale Eingaben bleiben sichtbar und
werden nicht durch Fallback-Heuristiken verdeckt.

## Diff und Query

`collection-state-diff/v1` vergleicht genau zwei kompatible Snapshots und
trennt mindestens hinzugefügte, verschwundene, technisch geänderte, neu
analysierte, neu aufgelöste, neu reviewte und neu blockierte Zustände. Der Diff
ist deterministisch sortiert und trifft keine Kausalitätsbehauptung, die nicht
aus der gebundenen Lineage folgt.

`collection-query/v1` akzeptiert ausschließlich einen validierten Query-AST
mit fester Feld- und Operator-Allowlist, Sortierung, Keyset-Pagination und
harten Ergebnisgrenzen. Freie SQL-Fragmente und ungeprüfte Spaltennamen sind
verboten. Der erste Slice indexiert nur ausgewählte Metadaten, opaque IDs,
Finding-Codes und Statuswerte. Content-Volltext, OCR, Query-History und
Netzwerkzugriffe bleiben ausgeschlossen.

## Library Health v1

`library-health/v1` besitzt keinen Gesamtscore. Die Projektion hält mindestens
folgende Dimensionen getrennt:

- Scan-/Fixity-Zustand;
- Analyse- und Toolabdeckung;
- Metadaten-, Authority- und Classification-Lücken;
- offene Reviewfälle;
- Duplicate-/Variant-Evidence;
- Calibre-, Sidecar- und Archive-Abhängigkeiten;
- blockierte Consolidation- und Quarantänefälle.

Jedes Finding bindet Profil, Eingabe-Snapshot und nachvollziehbare
Evidence-Kategorien. `Library Health` bestätigt keine Identity und autorisiert
keine W10-Operation.

## Ausgabe- und Privacy-Vertrag

Die maschinenlesbaren Vertragsreports bleiben immer pfadfrei und enthalten
nur opaque IDs, feste Literale, Counts, Profilangaben, Coverage und
Truncation-Marker. Die lokale interaktive CLI darf Metadatenwerte nur nach
explizitem `--private-details` ausgeben. Absolute Pfade bleiben auch dann
ausgeschlossen. Private Detailausgaben werden weder persistiert noch als
CI-Artefakt erzeugt.

Die geplanten CLI-Kommandos sind:

```text
collection-state-build
collection-state-report
collection-state-diff
collection-search
library-health-report
```

## Persistenz und Migration

Jede Wave verwendet eine additive Migration nach dem dann aktuellen
Schema-Head. Snapshot-Parents und zugehörige Werte sind insert-only.
Rebuilds, Wiederholungen, Kollisionen und injizierte Fehler müssen atomar und
idempotent behandelt werden. Read-only Reports verwenden eine echte
SQLite-Read-only-Verbindung und dürfen weder Verzeichnisse noch eine
Datenbankdatei anlegen.

## Abnahmefolge

- `CS-01`: deterministischer Rebuild, idempotente Wiederholung, explizite
  Stale-/Incomplete-Fälle, bounded Keyset-Reads und Upgrade vom vorherigen
  Schema-Head;
- `CS-02`: deterministischer Diff, begrenzter Query-AST, ungültige und
  übergroße Queries fail-closed sowie gemessener synthetischer Skalierungslauf;
- `CS-03`: nachvollziehbare Findings, keine Doppelzählung, explizite Coverage
  und reproduzierbarer Vergleich zweier Snapshots.

Alle Tests verwenden ausschließlich synthetische Daten. Der private
Collection-Abschluss bleibt ein getrenntes lokales Betriebsverfahren und ist
kein CI-Nachweis.

## Folgen

- Vorhandene Evidence liefert unmittelbaren CLI-Nutzen, bevor eine neue
  Mediendomäne begonnen wird.
- Music W4 bleibt die nächste vollständige Mediendomäne nach diesen
  Produktprojektionen.
- ADR-0042 bleibt für portablen Austausch und Multi-Instanz-Fusion zuständig;
  `CollectionState` führt keine portable Objektidentität ein.
- W10 und die parallele Quarantäne-Bedienkette bleiben unabhängig von den
  read-only Produktprojektionen.

## Nicht autorisiert

Diese Entscheidung autorisiert keine Source-Media-, Calibre-, Sidecar- oder
externe Library-Mutation, keine Online-Suche, keine Content-Volltextindizierung,
keine API, kein MCP, keine UI und keine medienübergreifende Generalisierung.
