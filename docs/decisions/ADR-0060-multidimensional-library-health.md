# ADR-0060: Mehrdimensionale book-only Library Health

- Status: Accepted
- Datum: 2026-08-22

## Kontext

ADR-0058 beauftragt `CS-03` mit `library-health/v1` über dem immutable
`collection-state/v1` und dem snapshotgebundenen
`collection-query-index/v1`. Für eine Implementierung fehlen noch feste
Dimensionen, Finding-Literale, Aggregationsregeln, Persistenz- und
Vergleichssemantik. Ein einzelner Score würde unabhängige Lücken verdecken.
Eine live gegen veränderliche Evidence ausgeführte Auswertung würde ältere
Sammlungszustände nachträglich umdeuten.

## Wave-Vertrag

`CS-03` basiert auf `origin/main`-Commit
`4a5f140f0ca6a99a5b5249ccfafa054ac8974ced`. Die neue Persistenz- und
Privacy-Grenze wird als `FRONTIER` entschieden; die anschließende festgelegte
Umsetzung ist mechanische, schichtübergreifende Arbeit.

Erlaubt sind ausschließlich:

- der book-only Health-Vertrag und seine reine Auswertung;
- die additive Migration `0025`;
- insert-only Persistenz, read-only Workflow und CLI;
- synthetische fokussierte Tests und unmittelbar betroffene
  Planungsdokumentation.

Ausgeschlossen sind Source-Media-Zugriff, Tools, Provider, Netzwerk,
kanonische Metadaten, neue Identity-Entscheidungen, W10-Autorisierung,
Mutation, API, MCP, UI, Content/OCR und eine Music-Generalisierung. Eine
dieser Grenzen oder eine nicht durch den vorhandenen Snapshot belegbare
Semantik stoppt die Implementierungs-Wave.

Die lokale Abnahme verwendet nur die neuen Contract-, Migrations-,
Persistenz-, Read-only-, Privacy-, Vergleichs- und statischen
Sicherheitsfälle sowie direkt betroffene Bootstrap-/Dokumentationsverträge.
Der vollständige Gate läuft genau einmal am stabilen Pull-Request-Head.

## Entscheidung

`library-health/v1` ist eine immutable, content-addressed und rebuildbare
book-only Projektion. Sie bindet genau einen `CollectionState`-Snapshot und
den exakt dazu gehörenden `collection-query-index/v1`. Der
`CollectionState`-Builder erzeugt oder verifiziert beide Eingaben und die
Health-Projektion in derselben SQLite-Transaktion.

Ein vor Migration `0025` erzeugter Snapshot erhält die Projektion nur durch
einen erneuten `collection-state-build`. Dieser Lauf revalidiert zuerst den
vollständigen `CollectionState` gegen die aktuelle persistierte Evidence.
`library-health-report` ergänzt weder Schema noch Projektion und öffnet die
Datenbank tatsächlich read-only.

## Dimensionen und Status

Die feste Reihenfolge lautet:

1. `SCAN_FIXITY`;
2. `ANALYSIS_TOOL_COVERAGE`;
3. `METADATA_AUTHORITY_CLASSIFICATION`;
4. `OPEN_REVIEWS`;
5. `DUPLICATE_VARIANT_EVIDENCE`;
6. `DEPENDENCIES`;
7. `BLOCKED_OPERATIONS`.

Jede Dimension weist `COMPLETE`, `PARTIAL` oder `NONE` als Coverage aus. Der
separate Dimensionsstatus ist genau einer der folgenden Werte:

- `CLEAR`: keine Finding-Evidence;
- `OBSERVED`: ausschließlich informative Evidence;
- `ATTENTION`: mindestens ein fachlich zu prüfender Befund;
- `INCOMPLETE`: die Evidence reicht für die Dimension nicht aus;
- `BLOCKED`: ein expliziter Konflikt oder Operationsblocker ist belegt.

Die Priorität lautet `BLOCKED`, `INCOMPLETE`, `ATTENTION`, `OBSERVED`,
`CLEAR`. Diese Reihenfolge ist nur eine deterministische Statusreduktion und
kein numerischer oder vergleichbarer Gesamtscore. Es gibt keinen
dimensionsübergreifenden Roll-up.

## Finding-Vertrag

Ein Finding verwendet eine feste Dimension, einen stabilen Code, die
Severity `INFO`, `ATTENTION`, `INCOMPLETE` oder `BLOCKED`, vollständige
betroffene Item-Counts und eine oder mehrere feste Evidence-Kategorien. Die
erste Profilversion kennt folgende Codes:

| Dimension | Finding-Codes |
|---|---|
| `SCAN_FIXITY` | `FULL_FIXITY_MISSING`, `FULL_FIXITY_CONFLICT` |
| `ANALYSIS_TOOL_COVERAGE` | `ANALYSIS_MISSING`, `ANALYSIS_STALE_OR_UNSCOPED`, `ANALYSIS_CONFLICT`, `ANALYSIS_QUALITY_FINDING_PRESENT` |
| `METADATA_AUTHORITY_CLASSIFICATION` | `TITLE_METADATA_MISSING`, `CONTRIBUTOR_METADATA_MISSING`, `IDENTIFIER_METADATA_MISSING`, `LANGUAGE_METADATA_MISSING`, `PUBLISHER_METADATA_MISSING`, `METADATA_INDEX_TRUNCATED`, `AUTHORITY_RESOLUTION_COVERAGE_GAP`, `AUTHORITY_RESOLUTION_CONFLICT`, `CLASSIFICATION_COVERAGE_GAP`, `CLASSIFICATION_CONFLICT` |
| `OPEN_REVIEWS` | `PENDING_REVIEW`, `DEFERRED_REVIEW` |
| `DUPLICATE_VARIANT_EVIDENCE` | `DUPLICATE_OR_VARIANT_EVIDENCE_PRESENT`, `MATCHING_COVERAGE_GAP`, `MATCHING_CONFLICT` |
| `DEPENDENCIES` | `CALIBRE_DEPENDENCY_PRESENT`, `SIDECAR_DEPENDENCY_PRESENT`, `ARCHIVE_DEPENDENCY_PRESENT`, `DEPENDENCY_COVERAGE_GAP`, `CALIBRE_CONFLICT`, `ARCHIVE_CONFLICT` |
| `BLOCKED_OPERATIONS` | `CONSOLIDATION_BLOCKED`, `QUARANTINE_BLOCKED` |

`FULL_FIXITY_MISSING` bedeutet ausschließlich, dass für die exakte
`FileObservation` kein kompatibler vollständiger `FILE_SHA256`-Fingerprint
vorliegt. Mehrere verschiedene kompatible Werte ergeben
`FULL_FIXITY_CONFLICT`. Es wird weder Bit Rot noch eine Ursache behauptet.

`DUPLICATE_OR_VARIANT_EVIDENCE_PRESENT` bedeutet nur, dass die gebundene
Matching-Komponente aktuelle Candidate-Evidence enthält. Das Finding ist
keine `Relation`, kein Duplicate-Verdict und keine Keep Preference.

Calibre-, Sidecar- und Archive-Findings kennzeichnen vorhandene
Abhängigkeitsevidence. Sie behaupten weder, dass eine Datei entbehrlich ist,
noch autorisieren sie eine spätere Operation. Die Sidecar-Kategorie wird nur
aus expliziter Calibre- oder Archive-Sidecar-Evidence abgeleitet.

Ein Item wird je Finding-Code höchstens einmal gezählt. Der
`affected_item_count` einer Dimension zählt die Vereinigung ihrer betroffenen
Items und verhindert Doppelzählung zwischen mehreren Findings. Die Summe der
Finding-Counts darf deshalb größer als der Dimensionscount sein und wird
nicht als Gesamtzahl verwendet.

## Bounded Details und Privacy

Für jedes Finding werden höchstens 64 deterministisch nach opaque `File`-ID
sortierte Samples persistiert. Der vollständige betroffene Count und ein
Truncation-Marker bleiben erhalten. Ein Sample enthält ausschließlich opaque
`File`- und `FileObservation`-IDs. Pfade, Namen, Metadatenwerte,
Fingerprints, Evidence-Digests, Query-Werte und Inhalte sind ausgeschlossen.

Der maschinenlesbare `library-health-report/v1` gibt feste Literale, Profile,
opaque IDs, Counts, Coverage, Status und begrenzte Samples aus. Eine private
Detailoption ist nicht erforderlich und wird in v1 nicht angeboten.

## Reproduzierbarer Vergleich

`library-health-report` akzeptiert optional einen älteren
`CollectionState`-Snapshot desselben `ScanRoot` als Baseline. Das Profil
`library-health-comparison/v1` vergleicht genau zwei verschiedene immutable
Health-Projektionen. Es gibt pro Dimension und Finding-Code nur Vorher-,
Nachher- und Delta-Counts sowie die jeweiligen festen Status- und
Coverage-Werte aus. Der Vergleich ist deterministisch und trifft keine
Kausalitätsbehauptung.

## Persistenz

Migration `0025_library_health` ergänzt vier Tabellen für Snapshot,
Dimensionen, Findings und begrenzte Samples. Parent- und Child-Datensätze sind
insert-only. Deklarierte Counts, begrenzte Ordinale, eindeutige Keys sowie
Update-/Delete-Trigger sperren nachträgliche Umdeutung; jeder Read prüft
Vollständigkeit und Content-Digests fail-closed.

Die Projection bindet mindestens das `CollectionState`-Content-Digest und das
`collection-query-index/v1`-Content-Digest. Ein geändertes Eingangsmaterial
erzeugt zuerst einen neuen `CollectionState` und danach eine neue Health-
Projektion. Ein vorhandener Health-Snapshot wird vollständig verifiziert oder
der Vorgang scheitert atomar.

## Abnahme

Die Wave weist mindestens nach:

- alle sieben Dimensionen, feste Findings und die Statuspriorität;
- vollständige Counts ohne Doppelzählung und begrenzte Samples;
- deterministischen Rebuild und atomare idempotente Persistenz;
- explizite Coverage und fail-closed beschädigte oder fehlende Projektionen;
- einen reproduzierbaren Vergleich zweier kompatibler Snapshots;
- echte SQLite-Read-only-Ausführung ohne Datenbank- oder Verzeichnisanlage;
- pfad-, metadatenwert-, Fingerprint- und Evidence-Digest-freie JSON-Ausgabe.

Alle Tests verwenden ausschließlich synthetische Daten.

## Folgen

- Die book-only E-Book-Linie besitzt nach `CS-03` eine konsistente lokale
  Produktprojektion von Scan bis zu Review-, Abhängigkeits- und
  Operationsblockern.
- Music W4 kann später eigene Einstiegspunkte und domänenspezifische
  Dimensionen erhalten; `library-health/v1` wird nicht vorab verallgemeinert.
- Eine spätere REST-API oder UI kann denselben Application-Vertrag verwenden,
  benötigt aber weiterhin eine eigene Produktoberflächen- und
  Privacy-Entscheidung.

## Nicht autorisiert

Diese Entscheidung autorisiert keinen Source-Media-Zugriff, keine Tool- oder
Provider-Ausführung, keine Netzwerkabfrage, keine Identity-Confirmation,
keine Mutation, keine API, kein MCP, keine UI und keine Music-
Generalisierung.
