# E-Book-Schreibpipeline: kanonischer End-to-End-Plan

**Planungsstand:** 2026-08-23
**Scope:** ausschließlich E-Books; gemeinsame Produktoberfläche und spätere
Medienlinien werden nur an ihren Grenzen berücksichtigt
**Ausführungsstatus:** ADR-0061 autorisiert die kontrollierte Entwicklung der
E-Book-Writer mit synthetischen Fixtures. Reale Mutation bleibt an
`BACKLOG.md`, eine operation-spezifische akzeptierte technische ADR und die
vollständige Capability-/Authorize-/Execute-/Recovery-Kette gebunden.
ADR-0063 entscheidet davon nur den ersten EPUB-3-Titelwriter. `S-W10-MW01`
liefert dessen reine Preflight-, Patch- und Diff-Verträge, `S-W10-MW02` das
private Streaming-Staging und die unabhängige Verifikation. `S-W10-MW03`
liefert content-addressed Preparation/Authorization, einmaligen Run,
append-only Journal, private Capability-Auflösung, Root-Fencing und read-only
Status. `S-W10-MW04` liefert inzwischen das interne feste Linux-`renameat2`-
Backend, den gefenceten Ein-Datei-Executor und idempotente Exact-State-
Recovery. ADR-0064 und `S-W10-MW05` schließen genau dieses Profil mit fester
CLI, zweiter Bestätigung, unmittelbarer Verifikation, neuem Scan,
`CollectionState` und immutable Reconciliation ab. Alle anderen Writer
bleiben operation-spezifisch geschlossen. ADR-0066 hat inzwischen den ersten
Datei-Writer ausschließlich für byte-identischen Same-Parent-`FILE_RENAME`
entschieden. `S-W10-RN01` liefert die nicht mutierende Proposal-/Preview-/
Review-/Plan-Oberfläche; `S-W10-RN02` ergänzt die weiterhin nicht ausführende
Authority mit Capability, Probe, Fencing, insert-only Journal und read-only
Status. `S-W10-RN03` ergänzt das feste interne Linux-Backend, unmittelbare
Verifikation und Exact-State-Recovery. `S-W10-RN04` schließt inzwischen die
feste CLI, zweite Bestätigung, Scan-Handoff, `CollectionState` und immutable
Reconciliation ab. `FILE_REORGANIZE` bleibt getrennt hinter
`FG-W10-REORGANIZE`. Für die ADR-0056-Quarantäne sind
Capability-Auflösung, current-state-gebundenes `quarantine-authorize`, zweite
Bestätigung, gefencetes `quarantine-execute` und die no-move Exact-State-
Recovery durch `S-W10-05A` bis `S-W10-05D` vorhanden.

## Zweck und Autorität

Dieses Dokument führt die bisher über W3, W5 bis W10, EB, EA, CS und FUT
verteilten Schritte zu einer zusammenhängenden E-Book-Pipeline zusammen. Es
beantwortet insbesondere, wie aus Scan-, Analyse- und Review-Evidence später
kontrollierte Metadatenkorrekturen, Duplikatquarantäne und weitere
Schreiboperationen werden können, ohne die bereits geltenden Safety-Gates zu
umgehen.

Es führt keine zweite Statusachse ein:

1. `PROJECT_STATUS.md` beschreibt den tatsächlich implementierten Stand.
2. `BACKLOG.md` enthält die kanonischen Aufgaben und Statuswerte.
3. `IMPLEMENTATION_PLAN.md` legt die Programmfolge W0 bis W10 fest.
4. Akzeptierte ADRs entscheiden technische Verträge und erlaubte
   Operationen.
5. Dieses Dokument verbindet diese Quellen zur End-to-End-Leserichtung.

Außer der engen ADR-0056-Interim-Ein-Datei-Quarantäne bleiben
Source-Media-, Sidecar-, Archive-, Calibre- und externe Toolwrites sowie
Purge und Verzeichnisbereinigung operativ nicht verfügbar. ADR-0061 gibt ihre
getrennte Entwicklung frei, ersetzt aber weder das technische Gate noch eine
konkrete Ausführungs-Authorization. Eine geplante Stufe ist keine
Ausführungsfreigabe.

## Zielzustand der E-Book-Linie

Der Zielzustand ist keine in-place „Bereinigung auf Verdacht“, sondern eine
nachvollziehbare Folge:

```text
Read-only erfassen
  -> Evidence analysieren und Qualität bewerten
  -> Authority/Identity/Classification auflösen
  -> Duplicate- und Variantenkandidaten bewerten
  -> menschlich reviewen
  -> unveränderlichen Operationsplan erzeugen
  -> konkrete Capability und kurzlebige Authorization prüfen
  -> unmittelbar vor dem Write vollständig revalidieren
  -> genau eine erlaubte Operation gefencet ausführen
  -> Rescan, Verifikation und Reconciliation
  -> getrennt autorisiertes Recovery, Rollback oder späterer Purge
```

Jeder Pfeil besitzt einen persistierten, versionierten Vertrag. Ein späterer
Schritt darf fehlende Evidence nicht durch Annahmen ersetzen. Die Sammlung
bleibt auch dann nutzbar, wenn externe Tools, Provider oder Write-Capabilities
nicht verfügbar sind.

## 1. Read-only Erfassung und technische Bestandsaufnahme

Diese Stufe ist weitgehend implementiert.

1. `ebook-tools-doctor` prüft die explizit provisionierte Toolchain und die
   Formatbereitschaft für EPUB, MOBI, AZW, AZW3 und PDF. Analysebefehle
   installieren oder aktualisieren nichts.
2. Ein `ScanRun` erfasst reguläre Dateien in einem read-only `ScanRoot` und
   persistiert technische Beobachtungen inkrementell.
3. Quick Fingerprints bilden begrenzte Kandidatenmengen; vollständiges
   SHA-256 wird selektiv und streaming-basiert ergänzt.
4. Der abgeschlossene Scan ist der unveränderliche Bezug aller folgenden
   Collection-Projektionen. Ein `RUNNING`-Scan ist kein zulässiger
   Ausführungssnapshot.
5. Archive, Volumes und Sidecars werden über die getrennten read-only
   Verträge inventarisiert. Unbekannte Member-Byte-Identity bleibt
   ausdrücklich `UNKNOWN`.

Ergebnis sind technische File-, Hash-, Archive- und Dependency-Evidence mit
Lineage, nicht bereits eine Duplicate- oder Schreibentscheidung.

## 2. Analyse, Qualitätsbewertung und Sammlungszustand

Die implementierte E-Book-Analyse orchestriert die freigegebenen
`ToolProvider` je Format und speichert deren Resultate als Evidence mit Tool-,
Adapter-, Parser-, Input- und Profilversion. Metadaten, Text, Cover, Struktur
und Formatrisiken bleiben unabhängige Dimensionen.

Darauf bauen auf:

- `EbookQualityAssessment` ohne skalaren Gesamtscore;
- deterministische Collection-Berichte;
- `CollectionState`, Snapshot-Diff und begrenzte lokale Metadatensuche;
- `Library Health` mit sieben unabhängigen Dimensionen;
- Coverage-, Staleness-, Conflict- und Blocker-Sichten.

Diese Stufe darf Findings priorisieren, aber keine Identity bestätigen und
keine Operation autorisieren. Fehlende Tools oder Provider werden als
Coverage-Lücke sichtbar und lösen keine stillen Installationen oder
Netzwerkzugriffe aus.

## 3. Fachliche Auflösung, Matching und Review

Vor jeder möglichen Korrektur oder Deduplizierung gilt folgende Reihenfolge:

1. Rohwerte und `FieldCandidate`-Datensätze bleiben mit Provenance erhalten.
2. `Entity Resolution` ordnet Agents, Works, Editions und Series auf der
   richtigen Identitätsebene zu.
3. Candidate Blocking begrenzt den Suchraum vor teuren Vergleichen.
4. Matching trennt exakte Bytegleichheit, dieselbe Edition, dasselbe Work,
   Übersetzung, Formatvariante und bloße Ähnlichkeit.
5. Quality Ranking und `KeepPreferenceOutcome` bleiben von Duplicate Identity
   getrennt.
6. Unsichere, widersprüchliche oder folgenreiche Fälle erzeugen
   `ReviewItem`-Datensätze. Entscheidungen sind append-only und an die
   geprüften Candidate-/Evidence-Snapshots gebunden.

Ein einzelner Hash, Metadatenwert, Provider, Toolbefund, Score oder eine
KI-/Web-Inferenz genügt nie für eine destruktive Folgeoperation.

## 4. Korrektur- und Operationsplanung

Die Planung ist immer nicht ausführbar und content-addressed. Sie bindet den
abgeschlossenen Scan, alle materiellen Evidence-Versionen, Reviewentscheidungen,
Dependencies, erwarteten Source-Zustand und eine feste Operationsreihenfolge.

### 4.1 Metadatenkorrekturen

ADR-0062 trennt zuerst einen immutable `MetadataCorrectionCandidate` als
Reviewgegenstand vom daraus abgeleiteten `MetadataCorrectionPlan`. Das
verhindert einen zyklischen Hash zwischen Plan und Review. Beide Snapshots
sind content-addressed; der Plan bleibt selbst nach einem kompatiblen
`ACCEPT` dauerhaft `NOT_EXECUTABLE`. Je Feld unterscheiden sie:

- beobachteter Rohwert;
- abgeleitete oder externe Kandidaten;
- ausgewählter kanonischer beziehungsweise `USER_CONFIRMED`-Wert;
- Zielträger und dessen aktueller Fingerprint;
- Format-/Writerprofil und erwartete semantische Änderung;
- unveränderte Felder und explizit zu bewahrende Rohwerte;
- Konflikte, Dependencies und Reviewentscheidung;
- post-write erwartete technische und fachliche Verifikation.

Die Lieferfolge bleibt ebenfalls getrennt: `S-W9-006A` enthält nur DTOs,
Reducer und kanonische Serialisierung, `S-W9-006B` die insert-only Persistenz
und Review-Integration und `S-W9-006C` einen privacy-begrenzten echten
SQLite-Read-only-Report samt CLI. Keines der drei Pakete öffnet Source Media
oder stellt eine Write-/Execute-/Apply-Operation bereit.

ADR-0063 löst aus diesen allgemeinen Plänen ausschließlich einen einzelnen
EPUB-3-`title`-`REPLACE` für `SOURCE_METADATA` auf. Der Patch verändert im
Package Document bytegenau nur `dc:title` und das formatbedingt neue
`dcterms:modified`; alle anderen Package-Document-Bytes und alle
Nicht-Package-Entry-Inhalte müssen erhalten bleiben. calibre schreibt in
diesem Profil nicht, sondern liefert zusammen mit EPUBCheck unabhängige
Read-back- und Konformitäts-Evidence. Andere Felder, Formate und Zielträger
bleiben eigene spätere Verträge.

`S-W10-MW03` bindet den verifizierten privaten Output zuerst an einen
content-addressed Prepare-Snapshot unter einer kurz gehaltenen Root-Fence.
Die daraus bestätigte Authorization übernimmt exakt Plan, Input-/Output-
Identität, `dcterms:modified`, Capability-ID und technische Versionen, läuft
nach höchstens 15 Minuten ab und ist durch den persistierten Run genau einmal
verbrauchbar. Authorization, Run und gapless Events sind insert-only; jeder
Write auf diese Tabellen ist an die aktuelle Preparation- oder Run-Fence
gebunden. Die private Capability-Konfiguration und der read-only Status öffnen
keine Source Media. Der Status projiziert weder Pfade, Metadatenwerte, Hashes,
Capability-Inhalte, Fences noch private Findings oder Digests.

Die Zielträger bleiben getrennte Operationstypen:

1. ausschließlich interne FolioTone-Projektion;
2. neu erzeugter oder aktualisierter Sidecar;
3. eingebettete Source-Metadaten;
4. Calibre-Library-Datensatz;
5. anderes externes, write-capable Tool.

Eine Freigabe für einen Zielträger öffnet keinen anderen. Insbesondere ist ein
reviewter kanonischer Wert noch keine Erlaubnis, ihn in eine Source-Datei zu
schreiben.

### 4.2 Duplikate und Varianten

Der implementierte `ConsolidationPlan` bleibt dauerhaft `NOT_EXECUTABLE`. Er
enthält Keeper, Kandidat, Evidence, Keep Preference, Dependencies,
changed-since-analysis-Preconditions sowie spätere Quarantäne-, Verifikations-,
Rollback-, Retention-, Purge- und Cleanup-Schritte.

Die operative Reihenfolge bleibt:

1. mindestens einen unabhängigen, vollständig revalidierten Keeper belegen;
2. Calibre-, Sidecar-, Archive- und Volume-Dependencies prüfen;
3. genau einen Kandidaten in Quarantäne verschieben;
4. inkrementell neu scannen und Keeper sowie abhängige Systeme prüfen;
5. das Rollbackfenster offenhalten;
6. erst später und separat einen Purge genehmigen;
7. leere Verzeichnisse zuletzt in einer eigenen Operation behandeln.

Batchquarantäne, automatische Schleifen und implizites „nächster Kandidat“
sind für den ADR-0056-Interim-Executor ausgeschlossen.

### 4.3 Pfad-, Datei- und Containeroperationen

`W9-007` plant Rename, Reorganisation, Import, Export, Transformation und
Archive-/Containeränderungen als getrennte reproduzierbare Rezepte. Ein Rezept
enthält Inputidentität, Writer-/Toolversion, Konfiguration, erwartete
Outputidentität, Kollisionsregeln, temporären Workspace, Recovery und
Verifikation.

ADR-0065 trennt dafür einen content-addressed
`EbookOperationRecipeCandidate` als Reviewgegenstand vom daraus reduzierten
`EbookOperationRecipePlan`. Die sechs Operationstypen besitzen eine feste
Matrix für Zielart, Byteidentität, Collision Policy, privaten Workspace,
Recovery und Post-operation-Verifikation. Es gibt keine freie Pfad-,
Command-, argv-, Glob-, Batch- oder rekursive Verzeichnisfläche. Private
relative Source-/Ziel-Locators sind materieller Teil der Candidate-Identität,
bleiben aber aus `repr`, Standard-Reports und späteren normalen REST-/UI-
Projektionen ausgeschlossen.

`S-W9-007A` liefert ausschließlich immutable DTOs, reine Builder/Reducer,
`canonical-json/v1`, Golden Values und den statischen Non-Execution-Gate.
`S-W9-007B` ergänzt die feste Review-Paarung und eine bounded insert-only
Persistenz über Migration `0030`; `S-W9-007C` ergänzt den echten
SQLite-Read-only-Report und die CLI. Damit ist `W9-007` vollständig. Kein
Paket erzeugt eine Capability oder Authorization. Rename, Reorganisation,
Import, Export, Transformation und Archive-Rewrite bleiben jeweils an ihren
eigenen späteren W10-Vertrag gebunden.

ADR-0066 entscheidet davon nur `FILE_RENAME` und nur für einen anderen
Basename im selben vorhandenen Parent. Die Source muss aktuell, regulär,
hardlinkfrei und vollständig gehasht sein; alle fünf Dependency-Achsen müssen
durch aktuelle Coverage `KNOWN_NONE` oder durch einen expliziten aktuellen
Dependency-Scope nachweislich `NOT_APPLICABLE` sein. `KNOWN_PRESENT`,
`UNKNOWN` und bloß fehlende Zeilen blockieren. Der Target-Locator muss
physisch sowie historisch unbenutzt sein.
Source und Target sind bereits NFC-kanonisch, nicht case-only verschieden und
behalten exakt dieselbe E-Book-Dateiendung. Die bislang fehlende nicht
mutierende Proposal-/private-Preview-/Review-/Plan-Oberfläche entsteht vor
jeder W10-Authority in `S-W10-RN01`.

Rename ist kein Identitätsbeweis. Archive-Extraction in einen privaten
Workspace autorisiert weder Source-Rewrite noch Archivlöschung. Eine
erfolgreiche Konvertierung oder Extraktion macht den Ausgangsdatensatz nicht
automatisch entbehrlich.

## 5. Operation-spezifische Safety-Gates

Jeder Mutationstyp benötigt vor seinem Writer-Slice eine eigene akzeptierte
technische ADR. Die vorangehende Gate-Wave darf Vertrag, Threat Model und
synthetische Conformance-Matrix erarbeiten. Reale Ausführung benötigt
zusätzlich die vollständige Implementierung und eine konkrete lokale
Capability und Authorization.

| Operation | Aktueller Stand | Erforderlicher nächster Vertrag |
|---|---|---|
| interne Review-/Decision-Persistenz | append-only vorhanden | keine Source-Mutation daraus ableiten |
| nicht ausführbarer Duplicate-Plan | vorhanden | W9-Vertrag unverändert lassen |
| eine reguläre Same-Filesystem-Datei quarantänisieren | Capability, Authorize, zweite Bestätigung, gefencetes Execute, enger Interim-Executor, no-move Exact-State-Recovery und read-only Status vorhanden | abgeschlossen; optionale Härtung bleibt `FG-W10-MOVE-BACKEND` |
| atomarer/generalisierter Quarantäne-Move | nicht autorisiert | `FG-W10-MOVE-BACKEND` mit No-Replace, no-follow, Race- und Crash-Nachweis |
| Metadaten in Source Media schreiben | ADR-0063/ADR-0064 erlauben operativ nur EPUB 3 plus einen `title`-`REPLACE`; vollständige Bedien-, Verifikations-, Scan-, Reconciliation- und Recoverykette vorhanden | jedes weitere Feld, Format oder jeder andere Zielträger benötigt ein eigenes Gate |
| Sidecar erzeugen oder ändern | Entwicklung freigegeben; operativ nicht verfügbar | `FG-W10-SIDECAR-WRITE` |
| Calibre oder anderes externes System ändern | Entwicklung freigegeben; operativ nicht verfügbar | `FG-W10-EXTERNAL-LIBRARY-WRITE` |
| Datei im selben Parent umbenennen | ADR-0066 und RN01 bis RN04 liefern Planung, Authority/Persistenz, festes Backend/Recovery, CLI, Scan-Handoff, `CollectionState` und immutable Reconciliation | abgeschlossen für ausschließlich byte-identischen Same-Parent-`FILE_RENAME`; jede Erweiterung benötigt ein eigenes Gate |
| Datei in einen anderen Parent reorganisieren | Entwicklung freigegeben; operativ nicht verfügbar | `FG-W10-REORGANIZE` |
| Archiv oder Container umschreiben | Entwicklung freigegeben; operativ nicht verfügbar | `FG-W10-ARCHIVE-REWRITE` |
| Quarantäne-Rollback | Entwicklung freigegeben; operativ nicht verfügbar | W10-003 mit eigener Authorization und Zielrevalidierung |
| Purge nach Retention | Entwicklung freigegeben; operativ nicht verfügbar | W10-003 mit separater Approval- und Recoveryentscheidung |
| leere Verzeichnisse entfernen | Entwicklung freigegeben; operativ nicht verfügbar | W10-004 |

Kein Gate darf stillschweigend Copy+Delete, Cross-Volume-Fallback,
Überschreiben, Symlink-/Reparse-Following oder eine breitere Capability
einführen.

## 6. Gemeinsamer Write-Lifecycle

Soweit eine spätere ADR nichts Strengeres verlangt, muss jede einzelne
Write-Capability mindestens diese Zustandsfolge besitzen:

1. **Plan fixieren:** content-addressed, nicht ausführbar und vollständig
   erklärbar.
2. **Capability auflösen:** opaque Capability-ID wird ausschließlich lokal
   auf den engsten erlaubten Root, Zielträger und Operationstyp abgebildet.
3. **Authorize:** kurzlebig, einmal verwendbar, an Plan-Hash, Operation,
   Operatorbestätigung und Capability gebunden.
4. **Dry-run revalidieren:** Source, Keeper, Dependencies, Writerprofil,
   Zielabwesenheit beziehungsweise erwarteten Zielzustand und freien
   Recoveryraum unmittelbar prüfen.
5. **Root-Writer erwerben:** gemeinsame `ScanRootWriteLease` mit monotonem
   Fencing; stale Besitzer dürfen keine Mutation fortsetzen.
6. **Einzelschritt ausführen:** kein versteckter Batch und kein ungeplanter
   Fallback.
7. **Journal persistieren:** append-only Attempt-/Eventzustände vor und nach
   der irreversiblen Grenze; Partial Failure bleibt explizit.
8. **Post-write verifizieren:** Bytes, Format, Metadaten, Zielzustand und
   Dependencies gegen den Plan prüfen.
9. **Rescan und Reconciliation:** neuer `ScanRun`, neuer `CollectionState`,
   Health-/Calibre-/Sidecar-Abgleich und nachvollziehbarer Diff.
10. **Terminal entscheiden:** erfolgreich, Recovery erforderlich oder
    fail-closed blockiert. Rollback, Retention und Purge bleiben neue
    Authorizations.

Ein Retry verwendet keine verbrauchte Authorization. Unklarer physischer
Zustand endet nicht mit automatischem Weiterarbeiten, sondern mit Recovery
und read-only Diagnose.

## 7. REST-API und grafische Oberfläche

FUT-011 verlangt vor API- oder UI-Code eine eigene Produktoberflächen-ADR.
Bis zu deren Annahme bleibt die CLI der einzige aktive Adapter.

Der planbare Zielvertrag ist:

- versionierte REST-Routen über denselben Application-Commands und -Queries,
  keine zweite Domainlogik;
- OpenAPI-Schema, Authentisierung, rollen- und capability-basierte
  Autorisierung, Keyset-Pagination, harte Request-/Response-Limits,
  Idempotenz, Privacy-Redaction und Audit;
- standardmäßig read-only Endpunkte für Scanstatus, Evidence, Quality,
  CollectionState, Diff, Suche, Library Health, Review und Planvorschau;
- Write-Endpunkte ausschließlich für einzeln akzeptierte W10-Capabilities;
  nicht autorisierte Operationen existieren weder als versteckter Endpoint
  noch als aktivierbares UI-Control;
- eine grafische Oberfläche als dünner Client mit getrennten Ansichten für
  Evidence, Vorschlag, Review, Plan, Authorization, Ausführung, Verifikation
  und Recovery;
- keine absolute Source-Pfad-, Secret-, private Metadaten- oder
  Collection-Inventar-Ausgabe ohne ausdrücklich begrenztes lokales
  Berechtigungsprofil.

Die Produktoberfläche erhält eine medienneutrale Shell und eine Registry der
fachlichen Linien. `E-Books`, `Musik`, `Bilder` und spätere Linien besitzen
eigene Menü-/Navigationseinstiege, Capability-Sets und Application-Routen.
Anfangs ist nur `E-Books` aktiv. Gemeinsame Infrastruktur darf die getrennten
fachlichen Identitätsebenen nicht in einen universellen Asset-Vertrag
zusammenziehen.

## 8. Lieferfolge in kleinen Waves

ADR-0061, ADR-0062 und ADR-0063 aktivieren die folgenden getrennt prüfbaren Waves.
`BACKLOG.md` bleibt für ihren Status maßgeblich:

1. `S-W9-006A` hat die reinen Candidate-/Plan-Verträge und ihre kanonische
   content-addressed Serialisierung implementiert.
2. `S-W9-006B` hat Review-Literale, Migration `0026` und insert-only
   Persistenz mit vollständiger Lineage- und Idempotenzprüfung ergänzt.
3. `S-W9-006C` hat den privacy-begrenzten SQLite-Read-only-Report und die CLI
   ergänzt und damit `W9-006` abgeschlossen.
4. `S-W10-05A` bis `S-W10-05D` haben Capability-Auflösung, Authorize, das
   gefencete Execute und die feste no-move Exact-State-Recovery der
   Ein-Datei-Quarantäne abgeschlossen, ohne den Mutationstyp zu erweitern.
5. ADR-0063 hat `FG-W10-METADATA-WRITE` für genau EPUB 3,
   `SOURCE_METADATA` und einen einzelnen `title`-`REPLACE` entschieden. Der
   Vertrag verwendet einen lexikalischen `dc:title`-/`dcterms:modified`-
   Patch, memberweisen Diff, privates Staging und einen Linux-
   `renameat2`-Exchange mit Same-Filesystem-Recovery.
6. `S-W10-MW01` implementiert Preflight, Patch und Diff ohne Source-Commit;
   `S-W10-MW02` ergänzt Staging und unabhängige Verifikation. `S-W10-MW03`
   ergänzt Preparation/Authorization, Persistenz, Capability/Fencing und
   read-only Status. `S-W10-MW04` ergänzt Linux-Executor und Recovery;
   `S-W10-MW05` schließt CLI, zweite Bestätigung, unmittelbare Verifikation,
   neuen Scan, `CollectionState` und Reconciliation ab.
7. ADR-0065 sowie `S-W9-007A` bis `S-W9-007C` liefern die content-addressed
   Candidate-/Plan-Verträge, feste Review-Paarung, bounded insert-only
   Persistenz und den privacy-begrenzten SQLite-Read-only-Report für sechs
   Operationsfamilien. `W9-007` ist damit abgeschlossen.
8. ADR-0066 schließt `FG-W10-RENAME` ausschließlich für byte-identischen
   Same-Parent-`FILE_RENAME`. Es bindet private Capability,
   Linux-`openat2`/`renameat2(RENAME_NOREPLACE)`, One-use-Authorization,
   Fencing, Journal, Exact-State-Recovery, Scan und Reconciliation. Parent-
   wechsel bleiben hinter `FG-W10-REORGANIZE`.

RN01 bis RN04 sind abgeschlossen. Es gibt danach keine automatisch
freigegebene Implementierungswave:

1. `FUT-011` entscheidet vor jedem REST/API/UI-Code die medienneutrale Shell,
   getrennte E-Book-/Musik-/Bilder-Einstiege, OpenAPI, Authentisierung,
   Autorisierung, Pagination, Privacy, Audit und Deployment;
2. schreibende Controls benötigen zusätzlich die jeweils vollständig
   implementierte operation-spezifische W10-Kette;
3. Sidecar-, externe Library-, Reorganisations-, Archive-, Rollback-, Purge-
   und Cleanup-Writer bleiben bis zu ihrem eigenen Gate unerreichbar.

Music, Bilder und weitere Linien starten nur nach ausdrücklicher Aktivierung.

## 9. Ressourcenschonende Verifikation

Jede Wave folgt `TEST_POLICY.md` und `COST_EFFICIENT_DEVELOPMENT.md`:

1. reine Verträge und Reducer mit kleinen Unit-Tests;
2. Store und Migrationen mit isolierten synthetischen SQLite-Datenbanken;
3. Writer ausschließlich auf neuen temporären synthetischen Dateisystemen;
4. genau die betroffenen Failure-, Crash-, Retry-, Fencing- und
   Privacy-Fälle lokal;
5. keine private Sammlung und kein echter Source-Root als Entwicklungs- oder
   CI-Gate;
6. genau ein vollständiger CI-Gate am stabilen PR-Head.

Ein späterer lokaler Spiegel-Canary ist ein ausdrücklich autorisierter
Betriebsschritt, kein Ersatz für synthetische Tests und keine implizite
Freigabe der autoritativen Sammlung.

## 10. Definition des End-to-End-Abschlusses

Die E-Book-Schreibpipeline ist erst vollständig, wenn:

- Scan, Analyse, Quality, Resolution, Matching, Review und alle Dependencies
  einen reproduzierbaren Snapshot bilden;
- jede Korrektur oder Konsolidierung einen nicht ausführbaren,
  content-addressed Plan besitzt;
- jeder Mutationstyp eine eigene akzeptierte ADR und engste Capability hat;
- Authorization, Revalidierung, Fencing, Journal, Partial Failure und
  Recovery nachweisbar sind;
- nach jedem Write Rescan, technische und fachliche Verifikation sowie
  Reconciliation erfolgen;
- Rollback, Retention, Purge und Directory Cleanup getrennte Entscheidungen
  bleiben;
- REST und UI dieselben Application-Verträge verwenden und keine zusätzliche
  Mutation Authority erzeugen;
- private Daten, Secrets und Runtimeartefakte außerhalb von Git und CI
  bleiben;
- ein Fehlerpfad niemals alle bestätigten Repräsentationen eines Works oder
  einer Edition entfernen kann.

Bis alle Punkte für einen Operationstyp erfüllt sind, bleibt dieser Teil der
Pipeline geplant oder blockiert, auch wenn seine Analyse- und UI-Vorschau
bereits vollständig ist.
