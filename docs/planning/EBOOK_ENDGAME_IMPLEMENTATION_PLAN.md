# FolioTone – detaillierte Planung der nächsten E-Book-Wellen

**Planungsstand:** 2026-08-20
**Basis:** maßgeblicher Implementierungsstand aus `PROJECT_STATUS.md` und
`BACKLOG.md` zum genannten Planungsstand
**Scope:** E-Book-Linie einschließlich Authority Resolution, Enrichment,
Classification, Matching, Review, Calibre-Reconciliation, nicht ausführbarer
Konsolidierungsplanung und anschließender Archive-Erweiterung.

---

## Einordnung, Vorrang und kollisionsfreie Zuordnung

Dieser Plan ist eine ausführbare Paketierung der bereits bestehenden
E-Book-Roadmaps. Er führt keine konkurrierende Status- oder ID-Hierarchie ein:

1. `PROJECT_STATUS.md` und `BACKLOG.md` sind maßgeblich für den tatsächlich
   implementierten Stand und die kanonischen Aufgabenstatus.
2. `IMPLEMENTATION_PLAN.md` bleibt maßgeblich für die Programmfolge W0 bis W10.
3. `W3_017_EBOOK_ROADMAP.md` bleibt maßgeblich für die book-only Wellen E1 bis
   E12.
4. `EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md` bleibt maßgeblich für Semantik und
   Status der Archivwellen EA1 bis EA12.
5. Die EB-Bezeichnungen dieses Dokuments bündeln diese Aufgaben lediglich in
   umsetzbare Entwicklungs- und Pull-Request-Pakete. Bei einer Abweichung gilt
   die jeweils vorgenannte maßgebliche Quelle.

| Ausführungspaket | Kanonische Zuordnung |
|---|---|
| EB-00 | Dokumentationsabgleich sowie noch offene Korrektur von W5B-001 |
| EB-01 | E4 |
| EB-02 | E6 sowie W5A-004/W5A-005 und ein minimaler W7-Review-Core |
| EB-03A/EB-03B | E7 und W5B |
| EB-04 | E8 und W5C-004 |
| EB-05/EB-06 | E9/E10 und W6/W7 |
| EB-07 | E11 und W8 |
| EB-08 | E12 und W9 |
| EB-A1 | Lieferbündel aus EA1 bis EA3 |
| EB-A2 | Lieferbündel aus EA4 bis EA7 |
| EB-A3 | Lieferbündel aus EA8 bis EA10 |

EA11 und EA12 gehören weiterhin zur gesperrten W10-Strecke. Keine EB-Welle
autorisiert Source-Media-Mutationen, Quarantäne, Löschung oder Verzeichnis-
bereinigung.

Die für Codex Spark geeigneten Teile dieser Lieferpakete sind im
[`Spark-Arbeitspaketkatalog`](EBOOK_SPARK_WORK_PACKAGES.md) in 58 atomare
Pakete zerlegt. Der Katalog enthält verbindliche Frontier-Gates und delegiert
EB-01, EB-02, EB-05, EB-06, die reale Archive-Extraction sowie W10 nicht
autonom an Spark.

---

## 1. Ausgangslage

Die eigentliche E-Book-Analysebasis ist inzwischen weit entwickelt:

- W3-001 bis W3-017 sind gemäß `BACKLOG.md` abgeschlossen; E4 sowie E6 bis
  E12 sind davon getrennte book-only Folgewellen.
- EB-00, EB-01/E4, EB-02, EB-05, EB-06, EB-07 und EB-08/W9 sind abgeschlossen;
- inkrementeller Scan, Resume und Recovery sind vorhanden;
- Quick- und Full-Hashing sind vorhanden;
- selektives SHA-256-Hashing für Duplicate Candidates ist vorhanden;
- E-Book-Metadaten-, Text-, Cover-, Structural- und Quality-Evidence sind vorhanden;
- ein synthetischer E-Book-Vergleichskorpus ist vorhanden;
- `ebook-comparison/v1` liefert bereits provider-neutrale Vergleichsfakten;
- Collection-Analyse und deterministische Reports sind vorhanden;
- lokale Name-/Identifier-Normalisierung und erste Entity Candidates sind vorhanden;
- persistierte Resolution Candidates, Evidence-Links sowie append-only
  ACCEPT-/REJECT-/DEFER-Entscheidungen sind vorhanden;
- begrenztes Candidate Blocking, versionierte Matcherprofile, persistierte
  Relation Candidates und der book-only Offline-Matching-Workflow sind
  vorhanden;
- strukturierte Knowledge-Provider-Verträge sind vorhanden;
- multidimensionale Classification-Verträge sind vorhanden.
- die persistierte read-only Calibre-Library-Reconciliation, die Keep Preference
  und ein pfadfreier, nicht ausführbarer `ConsolidationPlan` sind vorhanden.

Noch nicht vorhanden bzw. nicht vollständig:

- persistenter Provider Cache;
- realer Book Knowledge Provider;
- vollständige persistierte Classification-Projektion;
- kanonische Relation-Projektion aus bestätigten book-only
  Relation Candidates;
- reale Archive-Runtime, Archive-Persistenz und Collection-Orchestrierung;
  die synthetischen S-EBA-01 bis S-EBA-07 und FG-A-RUNTIME sind
  abgeschlossen.

`foliotone.matching` und `foliotone.review` besitzen die book-only Verträge
und Workflows aus EB-05/EB-06. ADR-0034 ist mit S-EB08-01 bis S-EB08-09
vollständig umgesetzt: `foliotone.consolidation` enthält ausschließlich
immutable DTOs, reine Planung und Validierung, insert-only Persistenz sowie
pfadfreie read-only Projektionen. Bis zu einer späteren akzeptierten W10-ADR
bleibt jeder Plan `NOT_EXECUTABLE` und es existiert kein Mutationspfad.

---

# 2. Zentrale Architekturentscheidung

## Hauptempfehlung

Die abgeschlossene kritische Kette bleibt provider- und Calibre-unabhängig.
EB-03A, EB-03B, EB-04 sowie die book-only Kette bis EB-08 sind abgeschlossen.
In der getrennten Archivstrecke sind FG-A und S-EBA-01 bis S-EBA-07
abgeschlossen. FG-A-RUNTIME, FG-A-IMAGE und FG-A-RUNTIME-AVAILABILITY sind
akzeptiert; S-EBAR-01 bis S-EBAR-03A, EBAR-04 sowie S-EBAR-02A,
S-EBAR-02B und S-EBAR-02B2 sind umgesetzt. FG-A-STORAGE-FAMILY ist durch
ADR-0046 und FG-A-FORMAT-LOCK durch ADR-0047 entschieden. S-EBAR-02C ist der
nächste Schritt.

Empfohlene kritische Kette:

```text
EB-00 Status-/Contract-Bereinigung
    ↓
EB-01 ScanRoot Write Lease / Fencing
    ↓
EB-02 Persistierte Entity Resolution + Review Core
    ↓
EB-05 Candidate Blocking
    ↓
EB-06 Scoring + Matching Review
    ↓
EB-07 Calibre Reconciliation
    ↓
EB-08 Consolidation Planning
```

Parallel dazu:

```text
                 ┌─ EB-03A Provider Cache
EB-02 ───────────┼─ EB-03B erster realer Provider
                 └─ EB-04 Classification Projection
```

und unabhängig als vorbereitende Parallelstrecke:

```text
EB-01
  ↓
Archive Research / EA1
  ↓
später Archive Inventory und Member Evidence
  ↓
erst nach EB-06 → archive-aware Matching
```

### Begründung

Identity Resolution und Matching müssen auch vollständig offline funktionieren.

Ein externer Provider verbessert Evidence, darf aber keine technische
Voraussetzung für Duplicate Detection oder Entity Resolution werden.

Das hat mehrere Vorteile:

1. Ein Provider-Ausfall blockiert FolioTone nicht.
2. Große Collections erzeugen nicht automatisch tausende Online Requests.
3. Bereits vorhandene lokale Evidence wird maximal genutzt.
4. Provider-Wechsel verändert nicht das Domain Model.
5. Der spätere Archive-Pfad kann dieselben Matching- und Review-Verträge verwenden.
6. Calibre bleibt Evidence Source und wird nicht versehentlich zur kanonischen Datenbank.

---

# 3. EB-00 – Status- und Contract-Bereinigung

**Priorität:** P0 – sehr klein, aber vor weiterer Implementierung sinnvoll
**Art:** Dokumentation / Contract Alignment
**Keine funktionale Erweiterung**

## Gelöste Dokumentationskollision: W3-017/E3-Status

Der Abgleich dieser Planungswelle stellt klar: W3-017 und E1 bis E3 sind
abgeschlossen. E4 sowie E6 bis E12 sind eigenständige Folgewellen. Der
vollständige private Sammlungslauf bleibt betriebliche Arbeit und ändert den
implementierten Status von W3-017 nicht.

## Gelöste Vertragsentscheidung: Provider Modes

Der kanonische Zielvertrag aus ADR-0009 bezeichnet folgende Zugriffsarten:

- `OFFLINE`
- `LOCAL_DATASETS`
- `ONLINE_STRUCTURED`
- `ONLINE_WEB_RESEARCH`

Der aktuelle Code modelliert dagegen:

- `OFFLINE`
- `ONLINE`
- `CACHE`

Das war nicht nur ein Naming-Problem.

`CACHE` beschreibt keine Datenquelle, sondern eine Cache Policy.

### Verbindlicher Vertrag

Zwei getrennte Dimensionen verwenden:

```text
ProviderAccessMode
------------------
OFFLINE
LOCAL_DATASETS
ONLINE_STRUCTURED
ONLINE_WEB_RESEARCH
```

und gemäß ADR-0026:

```text
ProviderCachePolicy
-------------------
USE_IF_FRESH
REFRESH_IF_STALE
FORCE_REFRESH
NO_CACHE
```

`ONLINE_WEB_RESEARCH` bleibt weiterhin separat aktiviert und
Candidate-/Evidence-only.

ADR-0026 legt zusätzlich die Legacy-Abbildung fest: `OFFLINE` wird zu
`OFFLINE`/`NO_CACHE`, `ONLINE` zu `ONLINE_STRUCTURED`/`NO_CACHE` und `CACHE`
zu `OFFLINE`/`USE_IF_FRESH`. W5B-001 bleibt bis zur Implementierung und
Verifikation durch S-EB00-01 bis S-EB00-04 offen.

## Abnahme

- Roadmap, Backlog und Project Status widersprechen sich beim W3-017-Status
  nicht mehr.
- W5B-001 bleibt offen, bis Provider Access Mode und Cache Policy im Code
  semantisch getrennt und verifiziert sind.
- Noch kein realer Provider wird angebunden.

---

# 4. EB-01 – gemeinsame ScanRoot Write Lease und vollständiges Fencing

**entspricht:** E4
**Priorität:** P0 – Safety/Correctness
**Komplexität:** hoch
**Muss vor neuen langfristigen Runtime-Writer-Strecken abgeschlossen werden.**

**Stand:** Abgeschlossen durch ADR-0027 und Alembic `0012`. Die Umsetzung
umfasst Scanner, Kandidaten-Hashing, Collection-Analyse und einzelne
E-Book-Analyse als rootbezogene Writer; EB-02 baut darauf als abgeschlossener
persistierter Resolution-/Review-Core auf.

## Ziel

Für einen `ScanRoot` existiert zu einem Zeitpunkt genau ein legitimer
rootbezogener Writer.

SQLite serialisiert zwar physische Writes, verhindert aber nicht, dass zwei
logisch konkurrierende Prozesse abwechselnd gültige Transaktionen schreiben.

Deshalb reicht SQLite-Locking als fachliches Ownership-Modell nicht aus.

## Persistenz

Additive Migration nach der aktuell letzten Alembic-Revision.

Vorgesehen:

```text
scan_root_write_leases
----------------------
scan_root_id
owner_kind
owner_run_id
lease_token
fence_epoch
lease_expires_at
heartbeat_at
acquired_at
```

### Wichtig

Neben einem zufälligen `lease_token` sollte ein **monoton steigender
`fence_epoch`** verwendet werden.

Damit kann ein alter Prozess auch nach einem ABA-artigen
Acquire/Release/Acquire-Szenario keine gültige Transaktion mehr committen.

## Zu fence-nde Writes

Mindestens:

- `FileRecord`
- `FileObservation`
- `FileScanEvent`
- Fingerprint Writes
- `MISSING`
- `DELETED`
- Relocation Candidates
- Scan Heartbeat
- Scan Finish
- Scan Interrupt
- Candidate Hash Batch
- Candidate Hash Heartbeat
- Candidate Hash Finish

## Transaktionsregel

Nicht:

```text
check lease
→ work
→ commit
```

sondern:

```text
BEGIN
→ verify lease token + fence epoch
→ write data
→ verify/fence as Teil derselben logischen Transaktion
→ COMMIT
```

Ein stale Writer darf nach einem Lease Takeover **keinen einzigen
rootbezogenen Write mehr committen**.

## Long-running Hash

Für lange Full-SHA256-Operationen benötigt der Scanner einen getrennten
Lease Keeper.

Wenn Lease Renewal fehlschlägt:

- laufendes Lesen darf kontrolliert beendet werden;
- der berechnete Hash darf aber nicht mehr persistiert werden;
- vor dem nächsten Commit muss Ownership erneut bewiesen werden.

## Tests

Keine Sleep-basierten Race Tests.

Verwenden:

- Threads/Processes;
- getrennte SQLite Connections;
- `Barrier`;
- `Event`;
- deterministische Takeover-Sequenzen.

Mindestfälle:

1. Scanner A hält Lease.
2. Scanner B kann Lease nicht übernehmen.
3. Lease A wird stale.
4. B übernimmt.
5. A versucht File Batch → blockiert.
6. A versucht Fingerprint → blockiert.
7. A versucht Missing → blockiert.
8. A versucht Relocation → blockiert.
9. A versucht Finish → blockiert.
10. Candidate Hasher kann nicht gleichzeitig rootbezogen schreiben.
11. Crash vor Commit.
12. Crash nach Commit.
13. Keeper Failure.
14. Recovery nach Process Abort.

## Definition of Done

- eigene ADR;
- additive Migration;
- deterministische Concurrency Tests;
- bestehende Scan-/Hash-Tests weiterhin grün;
- keine Source-Media-Mutation;
- keine Timing-Heuristik als Correctness-Mechanismus.

---

# 5. EB-02 – persistierte E-Book Entity Resolution + gemeinsamer Review Core

**entspricht:** Rest E6 / W5A-004 book-only / W5A-005
**zusätzlich:** kleiner vorgezogener W7-Core
**Priorität:** P0
**Komplexität:** hoch

**Stand:** Abgeschlossen durch ADR-0028 und Alembic `0013`. Persistierte
Resolution Candidates, konkrete Evidence-Links, generische Review Items und
append-only ACCEPT-/REJECT-/DEFER-Historie sind implementiert. AUTO_SAFE ist
auf exakt kompatible frühere ACCEPT-Entscheidungen begrenzt.

## Warum Review bereits hier beginnen?

E6 verlangt bereits:

- bestätigte Authority-Zuordnungen;
- abgelehnte Authority-Zuordnungen;
- Wiederverwendung lokaler Entscheidungen.

Würde dafür jetzt ein Authority-spezifischer Decision Store entwickelt und
später W7 einen zweiten generischen Review Store bekommen, entstünde
unnötige Doppelarchitektur.

Deshalb sollte jetzt bereits ein minimaler generischer Review-/Decision-Layer
entstehen.

---

## 5.1 Entity Resolution Pipeline

```text
Observed Metadata
    ↓
FieldCandidate
    ↓
Normalization
    ↓
Entity Candidate Generation
    ↓
Evidence Aggregation
    ↓
Resolution Candidate
    ↓
AUTO-SAFE / REVIEW_REQUIRED
    ↓
Review Decision
    ↓
Local resolved knowledge
```

Source Observations bleiben unverändert.

---

## 5.2 Identity-Ebenen strikt trennen

### Agent

Beispiele:

- Autor;
- Herausgeber;
- Übersetzer;
- Organisation.

Ein gleicher normalisierter Name reicht niemals für einen Merge.

### Work

Abstraktes Werk.

Beispiel:

```text
Frankenstein
```

### Edition

Konkrete Ausgabe beziehungsweise sprachliche/bibliografische Edition.

Beispiele:

```text
Frankenstein, englische Ausgabe X
Frankenstein, deutsche Übersetzung Y
```

### Series

Eigene Entity mit Membership.

---

## 5.3 Identifier-Regeln

Identifier erhalten eine definierte fachliche Ziel-Ebene.

Beispiele:

```text
ISBN      → primär Edition Evidence
OpenLibrary Work ID → Work Evidence
OpenLibrary Edition ID → Edition Evidence
GND ID    → je Entitätstyp Agent/Work/etc.
```

Ein Identifier darf nicht nur deshalb auf die falsche Entity-Ebene
hochgezogen werden, weil zwei Dateien denselben Wert besitzen.

Auch ISBN wird als starke Evidence behandelt, nicht als mathematisch
unfehlbare Identität.

---

## 5.4 Persistierte Resolution Candidates

Empfehlung:

Keine kanonischen Felder direkt aus einem Resolver überschreiben.

Stattdessen persistieren:

```text
ResolutionCandidate
-------------------
candidate_id
subject_kind
subject_id
candidate_kind
candidate_entity_id
resolver_name
resolver_version
evidence_fingerprint
confidence
created_at
```

Dazu Evidence Links auf konkrete:

- Value Assertions;
- Tool Results;
- Fingerprints;
- External Identifiers;
- Provider Results;
- bereits bestätigte lokale Knowledge.

---

# 6. Minimaler generischer Review-Vertrag

## ReviewItem

```text
ReviewItem
----------
id
review_type
subject_kind
subject_id
candidate_kind
candidate_id
producer_name
producer_version
evidence_fingerprint
state
created_at
```

Mögliche `review_type`:

```text
AUTHORITY_RESOLUTION
CLASSIFICATION
MATCH_RELATION
KEEP_PREFERENCE
CONSOLIDATION_CANDIDATE
```

## ReviewDecision

Append-only:

```text
ReviewDecision
--------------
id
review_item_id
decision
decision_reason
evidence_fingerprint
decided_at
```

Decision:

```text
ACCEPT
REJECT
DEFER
```

Optional sollte der lokale User nicht mit Name/E-Mail persistiert werden müssen.
Ein technischer `actor_kind=USER` genügt standardmäßig.

---

## 6.1 Wiederverwendung von Entscheidungen

Ein bereits entschiedener Fall soll nicht erneut erscheinen, wenn:

- Subject gleich;
- Candidate gleich;
- materielle Evidence gleich;
- relevante Resolution-Semantik kompatibel ist.

### Wichtig

Die Matcher-/Resolver-Version sollte gespeichert werden.

Eine rein technische Versionsänderung sollte aber nicht automatisch jede
menschliche Entscheidung ungültig machen.

Dafür empfiehlt sich zusätzlich ein:

```text
decision_compatibility_version
```

Eine Entscheidung wird stale, wenn sich beispielsweise ändert:

- Entity-Ebene;
- relevante Evidence;
- Identifier-Zuordnung;
- Candidate Identity;
- Relation-Semantik.

Nicht zwingend bei einer reinen internen Refaktorierung.

---

## 6.2 False-Positive-Korpus

Mindestens synthetisch abdecken:

- gleicher Name, zwei unterschiedliche Personen;
- `Nachname, Vorname`;
- `Vorname Nachname`;
- Diakritika;
- Initialen;
- Namenspartikel;
- Alias;
- Pseudonym;
- `credited_as`;
- Übersetzer vs. Autor;
- gleicher Titel, unterschiedliche Autoren;
- gleicher Autor, unterschiedliche Works mit ähnlichem Titel;
- Übersetzung = gleiches Work, andere Edition;
- unterschiedliche Editionen;
- Serienname mit/ohne Nummer;
- widersprüchliche Identifier;
- wiederverwendeter/falsch eingetragener Identifier.

## Definition of Done

- Entity Candidates persistent;
- Source Evidence unverändert;
- Accept/Reject/Defer persistent;
- Decision History append-only;
- Homonyme erzeugen keinen Auto-Merge;
- Resolution komplett offline testbar;
- synthetischer negativer Korpus vorhanden.

---

# 7. EB-03A – Provider Cache und Provider Runtime vervollständigen

**entspricht:** W5B-002, W5B-008 und Teil E7
**Priorität:** P1
**Kann nach EB-01 teilweise parallel zu EB-02 entstehen.**

## Ziel

Ein realer Provider darf erst angebunden werden, wenn Cache,
Offline-Verhalten und Provenance korrekt modelliert sind.

## Trennung

```text
Provider Fetch
      ↓
Transport Cache
      ↓
Provider Mapping
      ↓
FolioTone Evidence
```

Provider Fetch und Provider Mapping sind getrennt zu versionieren.

Dadurch kann eine Mapping-Änderung einen vorhandenen zulässigen Cache erneut
auswerten, ohne erneut Netzwerkverkehr zu erzeugen.

## Cache Key

Mindestens:

```text
provider_id
provider_adapter_version
query_fingerprint
provider_schema/source_version
mapping_profile_version
```

## Cache Metadaten

```text
fetched_at
expires_at
http_status
result_status
content_hash
mapping_version
```

Provider-spezifisch muss entschieden werden, ob gespeichert werden darf:

- Raw Response;
- nur normalisierte DTOs;
- nur Result/Fingerprint.

Die Lizenz-/Cache-Regeln des Providers sind Teil seines Descriptors.

## Negative Cache

`NOT_FOUND` darf begrenzt gecacht werden.

Aber:

- kürzere Lebensdauer als stabile positive Treffer;
- Provider Failure ist nicht `NOT_FOUND`;
- Rate Limit ist nicht `NOT_FOUND`;
- Timeout ist nicht `NOT_FOUND`.

## Netzwerkregeln

`OFFLINE`:

```text
keine Netzwerkverbindung
```

Das muss als Testvertrag technisch bewiesen werden.

Nicht:

```text
"wir rufen normalerweise nichts auf"
```

sondern Tests müssen einen unerwarteten Socket-/HTTP-Aufruf fehlschlagen lassen.

## Fehlerbehandlung

Getrennte Zustände:

```text
SUCCESS
NOT_FOUND
RATE_LIMITED
TEMPORARY_FAILURE
PERMANENT_FAILURE
INVALID_RESPONSE
CACHE_HIT
STALE_CACHE
```

## Retry

Nur für geeignete temporäre Fehler.

- begrenzt;
- kein Endlos-Retry;
- `Retry-After` beachten, wenn Provider dies liefert;
- kein Retry bei semantisch ungültiger Anfrage.

## Definition of Done

- Cache unter Runtime `/data`, nie im Repository;
- Offline Test;
- Cache Hit Test;
- Cache Stale Test;
- Refresh Test;
- Negative Cache Test;
- Provider Failure Test;
- Rate Limit Test;
- Mapping-Reanalysis ohne erneuten Fetch.

---

# 8. EB-03B – erster realer Book Provider

**entspricht:** W5B-004, book-only Teil W5B-007
**Priorität:** P1

## Hauptempfehlung: Open Library als erster bibliografischer Vertical Slice

Begründung:

- explizites Work-/Edition-Modell;
- strukturierte JSON APIs;
- Identifier Lookup;
- Author IDs;
- Search kann Work- und Edition-Daten liefern;
- monatliche Data Dumps stehen für Bulk-Szenarien zur Verfügung.

Aber:

Die öffentliche API soll laut Open-Library-Dokumentation für
low-volume/high-value Lookups verwendet werden und nicht als
permanenter Bulk-Backend-Ersatz.

Deshalb:

```text
Local resolved knowledge
    ↓
Local Provider Cache
    ↓
Identifier Lookup
    ↓
nur wenn ungelöst:
structured title/author lookup
```

und **nicht**:

```text
for every file:
    call Open Library
```

## Query-Reihenfolge

1. Open Library ID vorhanden → direkter Lookup.
2. ISBN/OCLC/LCCN vorhanden → Identifier Lookup.
3. Titel + bestätigter/resolved Author.
4. Nur Titel → standardmäßig kein automatischer High-Confidence Resolve.

## Privacy

Online Query bevorzugt:

```text
identifier
```

vor:

```text
title + author
```

Absolute Pfade oder private Collection-Strukturen werden nie übertragen.

Online-Betrieb bleibt ausdrücklich konfiguriert.

## Provider Output

Immer:

```text
ValueState.EXTERNAL
```

Nicht:

```text
CANONICAL
USER_CONFIRMED
```

---

# 9. Zweiter Authority Provider: GND/DNB

## Empfehlung

GND/DNB nicht anstelle von Open Library, sondern als zweite spezialisierte
Authority Source einplanen.

Stärken:

- Personen-/Organisation-/Work-Authority;
- stabile GND-Identifier;
- freie GND-Daten;
- mehrere offizielle Bezugswege;
- Bulk-/Local-Dataset-Nutzung möglich.

Für FolioTone besonders interessant:

```text
Agent Resolution
Work Authority
Alias / Preferred Name
Cross-Identifier
```

Der aktuelle DNB-SPARQL-Service ist als BETA gekennzeichnet.

Deshalb sollte FolioTone nicht davon abhängig werden.

Bevorzugte langfristige Richtung:

```text
GND local dataset/import
       +
optional structured online lookup
```

## Wikidata

Wikidata würde ich erst als dritten Provider einsetzen:

- Cross-Identifier;
- ergänzende Authority Links;
- alternative Namen;
- zusätzliche Classification Evidence.

Nicht als erste bibliografische Quelle.

---

# 10. EB-04 – persistierte Classification und lokale Projection

**entspricht:** Rest E8 / W5C-004
**Priorität:** P1
**Komplexität:** mittel

**Verbindlicher Vertrag:** [ADR-0037](../decisions/ADR-0037-book-classification-assertions-and-projections.md)
erhält die seit Migration `0001` vorhandenen `classification_assertions` und
ergänzt mit `0018` ausschließlich fehlende immutable Lineage- und Projection-
Tabellen. Legacy-Assertions ohne Profil werden nicht umgedeutet. Der EB-04-
Store ist insert-only und darf den generischen Update-by-ID-Pfad nicht nutzen.
Die exakten Facets, Source-/Priority-/Confidence-Regeln, Konfliktliterale,
Bounds, Profile, Compatibility, Reprojection und Privacy-Grenzen stehen in der
ADR. W5C-001 und W5C-002 bleiben `DONE`; EB-04 schließt nur W5C-004.

Die DTO-Verträge existieren bereits.

Jetzt fehlen vor allem:

- Persistence Workflow;
- Konfliktbehandlung;
- Projection.

## Assertion Layer

Alle Aussagen bleiben erhalten:

```text
LOCAL_DERIVED: topic=database
OPEN_LIBRARY: subject=databases
GND: subject=relationale Datenbank
USER: domain=Informatik
```

Keine Quelle überschreibt eine andere.

## Projection Layer

Eine versionierte Projection erzeugt daraus eine lokale Sicht.

Beispiel:

```text
domain: Informatik
genre: Fachbuch
topics:
  - Datenbanken
  - SQL
audience:
  - professional
language:
  - de
form:
  - reference
```

Die Projection ist abgeleitet und jederzeit neu berechenbar.

## Konflikte

Beispiel:

```text
Provider A → Fiction
Provider B → Computer Science
Local Tool → Technical reference
```

Ergebnis darf nicht sein:

```text
Computer Science gewinnt, Rest löschen
```

sondern:

```text
Assertions:
  A: Fiction
  B: Computer Science
  Local: Technical reference

Projection:
  REVIEW_REQUIRED
```

## Identity-Regel

Classification ist:

```text
supporting evidence
```

nicht:

```text
identity proof
```

Sie darf Candidate Blocking unterstützen, aber allein niemals:

- SAME_WORK;
- SAME_EDITION;
- EXACT_DUPLICATE

bestätigen.

---

# 11. EB-05 – Matching Foundation und Candidate Blocking

**entspricht:** E9 Teil 1 / W6-001, W6-002, Teil W6-004
**Priorität:** P0 – zentrale Produktfunktion
**Komplexität:** hoch

**Stand:** Abgeschlossen durch ADR-0029. Der read-only Reader erzeugt
begrenzte, path-freie Blocks aus vollständigem File-Hash, Edition-Identifier,
akzeptierter Edition-/Work-/Series-Resolution, Agent/Titel und normalisiertem
Text. Große Blocks werden nicht paarweise expandiert; exakte Duplikate
verwenden einen Representative. Die book-only Relation Contracts validieren
Endpoint-Ebene und Evidence-Anforderungen. EB-05 fügt keine Persistenz oder
Migration hinzu; Relation Candidates, Scoring und Review folgen in EB-06.

## Wichtigste Designentscheidung

Nicht direkt:

```text
all files × all files
```

und auch nicht unkontrolliert:

```text
all members of block × all members of block
```

Für große Duplicate-Gruppen würde auch das quadratisch explodieren.

## CandidateBlock

Deshalb zuerst eine Block-Abstraktion:

```text
CandidateBlock
--------------
block_type
block_key_hash
block_version
members
evidence
```

Beispiele:

```text
FILE_SHA256
EDITION_IDENTIFIER
RESOLVED_EDITION
RESOLVED_WORK
AUTHOR_TITLE
TEXT_FINGERPRINT
SERIES_CONTEXT
```

## Blocking Priority

### Level 1 – deterministisch technisch

```text
FILE_SHA256
```

Bytegleiche Dateien.

### Level 2 – starke bibliografische Keys

```text
resolved Edition
ISBN + compatible evidence
external Edition identifiers
```

### Level 3 – Work-Ebene

```text
resolved Work
resolved Agent + normalized title
```

### Level 4 – Content

```text
text fingerprint bucket
```

### Level 5 – unterstützend

```text
series
classification
cover fingerprint
```

Letztere niemals allein als Identity Proof.

---

## 11.1 Große Blocks

Ein Block erhält ein hartes konfigurierbares Größenlimit.

Bei Überschreitung:

```text
secondary blocking
```

statt:

```text
quadratic pair explosion
```

Beispiel:

```text
Work
  ↓
language
  ↓
Edition identifier
  ↓
text fingerprint bucket
```

Die konkrete Default-Grenze soll durch synthetische Skalierungstests
festgelegt werden und nicht durch Schätzung.

---

## 11.2 Exact-Duplicate-Cluster

Bei 1.000 bytegleichen Dateien sind:

```text
999 * 1000 / 2
```

Paarrelationen für den eigentlichen Zweck unnötig.

Empfehlung:

```text
Duplicate Group
    ↓
deterministischer Representative
    ↓
bounded membership edges
```

oder eine explizite Match-Group-Repräsentation.

Damit bleibt die Komplexität näher an O(n) für exakte Duplikatgruppen.

---

## 11.3 Wiederverwendung des bestehenden Vergleichs

`ebook-comparison/v1` sollte Feature Source werden.

Nicht erneut implementieren:

- Hash comparison;
- Text comparison;
- Metadata comparison;
- Structural comparison;
- Cover comparison.

Stattdessen:

```text
persisted Evidence
      ↓
ebook-comparison
      ↓
feature vector
      ↓
matcher
```

---

# 12. Relation Taxonomy

Vor Scoring müssen die bestehenden Relation Types formal validiert werden.

Für E-Books mindestens:

```text
EXACT_DUPLICATE
CONTENT_DUPLICATE
SAME_EDITION
SAME_WORK
DIFFERENT_EDITION
FORMAT_VARIANT
QUALITY_VARIANT
```

Semantik muss eindeutig sein.

Beispielsweise:

```text
DIFFERENT_EDITION
```

sollte explizit bedeuten:

```text
same Work, but demonstrably different Edition
```

und nicht lediglich:

```text
not same Edition
```

Sonst wäre die Relation logisch zu breit.

## Invarianten

Beispiele:

```text
EXACT_DUPLICATE
→ File Ebene
→ gleicher vollständiger File Hash

SAME_EDITION
→ Edition Ebene
→ kann unterschiedliche Dateiformate besitzen

SAME_WORK + DIFFERENT_EDITION
→ Work gleich
→ Edition verschieden

FORMAT_VARIANT
→ technische Repräsentation
→ bibliografische Identität separat belegen

QUALITY_VARIANT
→ Qualitätseigenschaft
→ sagt allein nichts über bibliografische Identität
```

---

# 13. EB-06 – versioniertes Scoring, Explanation und vollständiger Review Workflow

**entspricht:** Rest E9 + E10 / W6-003 bis W6-006 / W7
**Priorität:** P0
**Komplexität:** hoch

## Kein universeller Gesamtscore

Ein einzelner Score für alle Relation Types wäre fachlich gefährlich.

Stattdessen:

```text
MatcherProfile: SAME_EDITION/v1
MatcherProfile: SAME_WORK/v1
MatcherProfile: EXACT_DUPLICATE/v1
```

Jeder Matcher besitzt:

- eigene Features;
- eigene positive Evidence;
- eigene Contradictions;
- eigene Coverage-Anforderungen;
- eigene Thresholds.

---

## 13.1 Features

Beispiel `SAME_EDITION`:

```text
+ identical strong edition identifier
+ same resolved Work
+ same resolved Agent
+ title compatible
+ language compatible
+ text strongly compatible

- contradictory edition identifier
- incompatible language
- material text contradiction
- contradictory publication evidence
```

## Wichtig

Provider Agreement darf widersprüchliche lokale Evidence nicht überstimmen.

Beispiel:

```text
Open Library: same edition
Provider B: same edition

aber:

Text Evidence: materially different
Language: different
```

→ nicht automatisch `SAME_EDITION`.

---

# 14. Statusmodell

Vorschlag:

```text
CONFIRMED
PROBABLE
POSSIBLE
REVIEW_REQUIRED
REJECTED
```

## Automatische Confirmation

Konservativ.

`EXACT_DUPLICATE` kann bei gleichem vollständigen SHA-256 auf File-Ebene
technisch sehr stark behandelt werden.

Für bibliografische Relationen wie `SAME_EDITION` sollte automatische
Confirmation erst nach erfolgreicher Kalibrierung aktiviert werden.

Initial sinnvoll:

```text
high confidence → REVIEW_REQUIRED
medium confidence → REVIEW_REQUIRED
strong contradiction → REJECTED candidate
```

und erst später kontrollierte Auto-Confirmation für eindeutig belegte Fälle.

---

# 15. Calibration

Bestehende synthetische Fixtures erweitern um adversarial cases.

Mindestfälle:

- exakt gleiche Bytes;
- gleiche Edition, EPUB/PDF;
- gleiche Edition, EPUB/MOBI;
- Metadaten verändert, Inhalt gleich;
- Work gleich, Übersetzung verschieden;
- Work gleich, Edition verschieden;
- Titel gleich, Work verschieden;
- Autorname gleich, Agent verschieden;
- Identifier gleich, restliche Evidence widersprüchlich;
- Cover ähnlich, Work verschieden;
- Text ähnlich durch Vorwort/Boilerplate;
- sparse Metadata;
- malformed Metadata;
- Provider Disagreement;
- Tool Disagreement.

### Abnahmekriterium

Für automatisch bestätigte bibliografische Beziehungen:

```text
0 bekannte False Positives im kontrollierten/adversarial Korpus
```

Das ist sinnvoller als eine künstlich genaue Prozentzahl auf einem kleinen
Fixture Set.

---

# 16. Explanation Persistence

Jede Relation muss beantworten können:

```text
Warum wurde dieser Vorschlag erzeugt?
```

Beispiel:

```text
Relation: SAME_EDITION
Status: REVIEW_REQUIRED
Matcher: ebook-same-edition/v2

Positive:
  ISBN compatible
  resolved Work identical
  normalized text highly compatible

Negative:
  publisher differs

Unknown:
  publication date unavailable

Evidence:
  ...
```

Keine privaten absoluten Pfade in Reports.

---

# 17. Review-Reuse

Eine bestätigte oder abgelehnte Entscheidung wird erneut verwendet, wenn die
materielle Evidence unverändert ist.

Matcher-Neuberechnung darf nicht dazu führen, dass der User dieselben
offensichtlichen Fälle immer wieder bestätigt.

Eine neue Review ist erforderlich, wenn beispielsweise:

- neues starkes Evidence hinzukommt;
- bisheriges Evidence verschwindet;
- Entity Resolution sich ändert;
- Relationsebene geändert wird;
- Decision Compatibility geändert wird.

---

# 18. EB-07 – read-only Calibre Library Reconciliation

**entspricht:** E11 / W8
**Priorität:** P1
**Komplexität:** mittel bis hoch

## Architekturentscheidung

Calibre bleibt:

```text
Evidence Source
```

und wird nicht:

```text
Canonical Database
```

## Tool-Sicherheit

`calibredb` enthält sowohl lesende als auch mutierende Befehle.

Deshalb keine generische Command-Passthrough-API.

Nur vollständige Allowlist fester Command Shapes.

Initial beispielsweise:

```text
list
search
show_metadata
list_categories
```

Jede zusätzliche Operation muss separat auf Side Effects geprüft werden.

Nicht freigeben:

```text
add
remove
add_format
remove_format
set_metadata
embed_metadata
backup_metadata
restore_database
...
```

Auch `export` gehört nicht in den W8-Analyseadapter, weil er Dateien schreibt.

---

# 19. Calibre Reconciliation Cases

## A – Datei im FolioTone Index, nicht in Calibre

```text
FILESYSTEM_ONLY
```

## B – Calibre Record ohne zuordenbare Datei

```text
CALIBRE_RECORD_WITHOUT_FILE
```

## C – mehrere Calibre Records mit identischen Bytes

```text
CALIBRE_DUPLICATE_RECORD_CANDIDATE
```

## D – ein Calibre Record mit mehreren Formaten

Normalfall:

```text
EPUB
PDF
MOBI
```

Nicht automatisch Duplicate.

## E – Metadatenkonflikt

```text
Calibre title != embedded title
```

als Evidence, nicht automatische Korrektur.

## F – Authority Conflict

```text
Calibre author
vs.
resolved Agent
```

Review Candidate.

## G – Sidecars

Mindestens modellieren:

- `metadata.opf`;
- cover;
- zusätzliche Calibre-Datendateien;
- weitere bekannte Sidecars.

---

# 20. Calibre Ownership / Dependency Evidence

Vor Keep Preference muss klar sein:

```text
File
 ├─ belongs to Calibre Record?
 ├─ is one format of multi-format Record?
 ├─ metadata.opf dependency?
 ├─ cover dependency?
 └─ other sidecar dependency?
```

Eine spätere Mutation darf niemals eine Calibre-verwaltete Datei einfach am
Dateisystem vorbei löschen.

---

# 21. EB-08 – nicht ausführbarer ConsolidationPlan

**entspricht:** E12 / W9
**Priorität:** P0 – eigentliches Analyse-Endprodukt
**Komplexität:** mittel bis hoch

**Status:** `DONE`. FG-08 ist durch ADR-0034 akzeptiert. S-EB08-01 bis
S-EB08-09 implementieren den Vertrag vollständig; W9 erzeugt ausschließlich
persistierte `NOT_EXECUTABLE`-Pläne.

## Zentrale Regel

```text
Identity != Quality != Keep Preference != Physical Operation
```

Diese vier Ebenen bleiben getrennt.

---

## 21.1 Beispiel

```text
A.epub
B.epub
```

Matching:

```text
EXACT_DUPLICATE
```

Quality:

```text
A: 0.92
B: 0.87
```

Keep Preference:

```text
prefer A
```

Consolidation Plan:

```text
candidate B
keeper A
```

Noch immer:

```text
KEINE Dateisystemoperation
```

---

# 22. Keep Preference

Mögliche Inputs:

## Hard Constraints

- protected Source Root;
- Calibre Ownership;
- Archive Membership;
- fehlende Sidecar Information;
- unresolved identity;
- fehlende Review Approval.

## Quality Evidence

- Structural Validity;
- Text Availability;
- Metadata Completeness;
- Cover Quality;
- Format Preference;
- corruption findings.

## Benutzerkonfiguration

Formatpräferenz muss konfigurierbar sein.

Nicht universell:

```text
EPUB > PDF
```

Ein Fachbuch mit komplexem Layout kann beispielsweise als PDF die bessere
Repräsentation sein.

## Speichergröße

Dateigröße höchstens Tie-Breaker.

Nicht:

```text
größer = besser
```

---

# 23. ConsolidationPlan Daten

Mindestens:

```text
plan_id
plan_version
content_hash
created_at

keeper_entity
candidate_entity

identity_relation
identity_evidence

keep_preference
quality_evidence

required_reviews

preconditions
future_operation_intent
blockers
```

## Preconditions

Für Candidate:

```text
FileRecord ID
FileObservation ID
ScanRoot lineage
expected full SHA-256
expected size
expected presence state
expected observation generation
```

Für Keeper:

```text
exists
expected full SHA-256
still readable
```

Zusätzlich:

```text
Calibre relationship unchanged
Sidecar relationship unchanged
Archive relationship unchanged
Review approvals unchanged
```

---

# 24. Content Addressing

Der Plan sollte aus einer kanonischen serialisierten Darstellung einen Hash
erhalten.

Damit gilt:

```text
gleiche Inputs + gleiche Planversion
→ gleicher Plan Hash
```

Wenn sich relevante Evidence ändert:

```text
→ neuer Plan Hash
```

## Wichtig

Der exportierte Plan braucht keine absoluten Source Paths.

Interne IDs und sichere Root-relative Referenzen reichen.

---

# 25. Technisch nicht ausführbar

`foliotone.consolidation` enthält in W9:

- DTOs;
- Planner;
- Validator;
- Serializer;
- Reporter.

Nicht:

- `unlink`;
- `remove`;
- `rename`;
- `replace`;
- `move`;
- mutierendes Calibre;
- Shell Commands für Löschung.

Ein statischer adversarial Test prüft das vollständige Package gegen direkte,
dynamische und injizierte Mutationsformen, gegen öffentliche Ausführungs- oder
Passthrough-Surfaces sowie gegen mutierende Calibre-Command-Shapes. Er ist ein
zusätzlicher Regressionstest und ersetzt keine W10-Autorisierung.

W10 bleibt ausdrücklich blockiert.

---

# 26. Parallelstrecke: Archive

Die separate Archive-Roadmap ist fachlich sinnvoll, sollte aber nicht die
generische Matching-/Review-Architektur duplizieren.

Für Semantik, Reihenfolge und Status der EA1- bis EA12-Wellen bleibt
`EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md` maßgeblich. EB-A1 bis EB-A3 sind nur
Lieferbündel und ersetzen oder nummerieren die EA-Wellen nicht neu.

Das Sicherheits- und Vertragsgate FG-A ist durch
[ADR-0038](../decisions/ADR-0038-safe-archive-container-analysis.md)
akzeptiert. Es legt die Container-/Formatmatrix, 7-Zip-26.02-Entscheidung,
read-only Command Shapes, Statuswerte, Profile, Budgets, Memberpfade,
`SecretHandle`-Grenze und Reuse-Identität fest. Die produktive Listing- und
Extraction-Orchestrierung ist durch das separate
[FG-A-RUNTIME](../decisions/ADR-0039-safe-archive-runtime-and-secret-channel.md)
für unverschlüsselte Archive vertraglich freigegeben. Reale Passwortversuche
bleiben bis FG-A-SECRET blockiert.
S-EBAR-01 bis S-EBAR-03A und EBAR-04 sind umgesetzt. FG-A-IMAGE ist durch
[ADR-0040](../decisions/ADR-0040-reproducible-archive-runtime-image.md)
akzeptiert. FG-A-RUNTIME-AVAILABILITY ist durch
[ADR-0041](../decisions/ADR-0041-offline-archive-runtime-availability.md)
akzeptiert. S-EBAR-03A implementiert den reviewten Release-Acceptance-Record,
kontrollierte Erstprovisionierung, Rotation/Revocation und die Per-Run-
Offline-Revalidierung von Custom SLSA, SPDX, Manifest, OCI-Config und RootFS.
S-EBAR-02B ist abgeschlossen;
[ADR-0045](../decisions/ADR-0045-archive-7zip-format-lock.md) stuft dessen
Happy-Path-Messung als diagnostisch ein. S-EBAR-02B2 ist umgesetzt, ADR-0046
entscheidet FG-A-STORAGE-FAMILY und ADR-0047 den finalen Formatlock.
S-EBAR-02C und EBAR-05 sind umgesetzt.
[ADR-0048](../decisions/ADR-0048-private-archive-extraction-lifecycle.md)
entscheidet vor EBAR-06 den privaten Listing-/CRC-Handoff, den reinen internen
Extraction-Validator, ein separates Gate für einen harten Workspace-Cap
und den Runner-owned Workspace-Consumer-Lifecycle. S-EBAR-05A und S-EBAR-06A
sind umgesetzt. ADR-0049 akzeptiert die dateisystemneutrale
Workspace-Capability; das neutrale S-EBAR-04Q ist umgesetzt.
[ADR-0050](../decisions/ADR-0050-linux-docker-workspace-backend-unavailable.md)
schließt FG-A-WORKSPACE-BACKEND negativ und hält die Adapter-Allowlist leer.
S-EBAR-04A und EBAR-06 bleiben bis zu einem erfolgreichen Revalidation-Gate
mit konkretem Backend und echtem Linux-/Docker-Conformancehost
`TOOL_UNAVAILABLE`.
ADR-0051 entscheidet FG-A-WRAPPER-PIPELINE für eine getrennte bounded
read-only Streamingstrecke. S-EBAR-W01 bis S-EBAR-W04 sind abgeschlossen.
Für die vier äußeren Kompressionsstreams dürfen nur Listing und Integrity
starten; Source-Recognition bleibt
`OUTER_COMPRESSION_ONLY`, EBAR-06 und Extraction bleiben ausgeschlossen.
Der erste freigegebene Backendvertrag ist
`archive-linux-container-runner/v1` für die primäre Docker/Linux-Runtime. Er
verwendet ein digest-gepinntes Image mit exakt verifizierter eingebetteter
`7zzs`-26.02-Identität, opaque vollhashgeprüftes Input-Staging statt eines
ScanRoot-Mounts und einen getrennten Output-Workspace. Native Windows-
Ausführung bleibt bis zum akzeptierten `FG-A-WINDOWS-SANDBOX`
`TOOL_UNAVAILABLE`; Job Objects und Handle-Allowlisten allein genügen nicht.

## Empfehlung

### Sofort parallel möglich

```text
EA1 Tool-/Formatresearch
```

### Ebenfalls relativ früh

```text
EA2 Archive Inventory
EA3 Secret/Password Candidate Contracts
EA4 bounded Listing
EA5 private Test Extraction
EA6 Member Evidence
```

### Warten auf generisches Matching/Review

```text
EA8 archive-aware Matching
EA9 Archive/Calibre Keep Preference
EA10 kompletter Deduplication Plan
```

---

# 27. EB-A1 – Archive Discovery, Sidecars und Secret Boundary

**entspricht:** EA1–EA3
**Priorität:** P1
**Kann nach EB-01 parallel laufen.**
**Verbindlicher Vertrag:** ADR-0038

## Containerklassen

Unterscheiden:

### Publication Container

```text
EPUB
CBZ
CBR
```

### Generic Archive

```text
ZIP
RAR
7z
TAR
compressed TAR variants
```

Ein EPUB darf nicht allein deshalb als löschbarer ZIP-Container behandelt
werden, weil sein internes Format ZIP-basiert ist.

---

## Signature First

Erkennung:

```text
magic/signature
    +
suffix
```

Abweichungen werden Evidence:

```text
suffix=.zip
signature=RAR
```

nicht stillschweigend korrigiert.

---

# 28. SecretProvider

Passwörter niemals persistieren als:

```text
plaintext
```

Statt:

```text
SecretHandle
```

Persistiert werden darf beispielsweise:

```text
secret_handle
secret_version
candidate_source
candidate_rank
tested_at
result
```

Nicht:

```text
password
```

## Kritischer Security Gate

Das ausgewählte Archivtool muss beweisen, dass Passwörter **nicht**
in folgenden Kanälen sichtbar werden:

- command line arguments;
- stdout;
- stderr;
- normale Logs;
- Report Artifacts;
- SQLite Plaintext.

Falls ein Tool keinen sicheren Secret Channel unterstützt, bleibt
Password Handling mit diesem Tool blockiert.

Die Sicherheitsanforderung darf nicht gelockert werden, nur damit ein
bestimmtes Tool verwendet werden kann.

Für die gewählte 7-Zip-26.02-CLI ist diese Blockade eingetreten: Der
dokumentierte `-p{password}`-Parameter würde das Secret in argv offenlegen;
die aktuelle `ToolRuntime` besitzt keinen Secret-Kanal. S-EBA-01 bis
S-EBA-07 modellieren deshalb nur `SECURE_CHANNEL_UNAVAILABLE`. ADR-0039 gibt
die unverschlüsselte Runtime getrennt frei. Eine echte Passwortprüfung
benötigt FG-A-SECRET und einen isolierten Helper-/Pipe-/Handle-Vertrag. Eine
undokumentierte stdin-, PTY- oder Environment-Lösung ist ausgeschlossen.

---

# 29. Lokale Passwortkandidaten

Reihenfolge:

1. expliziter Secret Handle;
2. bereits bestätigtes Secret für dieselbe Release Identity;
3. Archive Comment;
4. Sidecar NFO;
5. TXT;
6. DIZ;
7. INFO;
8. URL;
9. HTML;
10. SFV;
11. extensionless README/PASSWORD;
12. explizit konfigurierte lokale Password List.

Kein:

- Brute Force;
- Dictionary Expansion;
- Kombinatorik aus privaten Filenames;
- unbeschränktes Crawling.

---

# 30. EB-A2 – bounded Listing, Integrity und private Extraction

**entspricht:** EA4–EA6
**Priorität:** P1

ADR-0038 setzt für `archive-safety-policy/v1` exakte Defaults, darunter
10.000 Member, 8 GiB Gesamtgröße, 2 GiB je Member, Ratio 1.000, keine
Nested-Verarbeitung (`max_nested_depth=0`), feste Laufzeit-/Ausgabegrenzen
und höchstens zwei parallele Archive Jobs. Abweichende Profile benötigen ein
neues Security Review.

## Sicherheitsbudgets

Profile müssen harte Grenzen definieren:

```text
max_member_count
max_total_uncompressed_bytes
max_single_member_bytes
max_compression_ratio
max_path_length
max_runtime
max_nested_depth
max_stdout_bytes
max_stderr_bytes
```

Nested Archive Processing standardmäßig restriktiv.

---

## Abzuweisen

- `../` Traversal;
- absolute Paths;
- Device Paths;
- Windows ADS;
- Symlinks;
- Reparse Points;
- Hardlinks, FIFOs, Sockets und Device Members;
- NFC-/Casefold-/Separator-normalisierte Zielkollisionen;
- Root Escape.

---

## Extraction

Immer:

```text
Source Archive: read-only
        ↓
private bounded Workspace
```

Niemals:

```text
extract beside source archive
```

Jedes extrahierte Member wird gestreamt gehasht.

Nachweis:

```text
listed members
==
extracted members
```

unter Berücksichtigung des Tool-/Formatvertrags.

ADR-0048 teilt die fehlende Lifecycle-Brücke in mechanische Vorpakete und ein
separates Frontier-Gate.
S-EBAR-05A reicht Locator und CRC ausschließlich underscore-intern aus
demselben EBAR-05-Lauf weiter. S-EBAR-06A implementiert daraus den exakten
reinen Extraction-Consumer ohne Tool- oder Filesystemzugriff.
FG-A-EXTRACTION-QUOTA ist durch ADR-0049 als dateisystemneutrale, atomar
begrenzte Workspace-Capability entschieden. S-EBAR-04Q implementiert deren
neutralen Provider-, Lease-, Capability-, Return- und Quarantänevertrag.
ADR-0050 akzeptiert keinen der aktuell untersuchten Linux-/Docker-Kandidaten:
Byte-, Objekt-, Reserve- und Consumer-Lifecycle sind nicht gemeinsam belegt.
Die Allowlist bleibt leer; ein konkretes Backend folgt frühestens nach einem
erfolgreichen docs-only Revalidation-Gate. Periodisches Scannen ist lediglich
Frühabbruch. Erst danach lässt S-EBAR-04A
nur diesen privaten Extraction-Consumer zwischen bewiesener
Container-Abwesenheit und
Runner-owned Cleanup auf eine borrowed no-follow-Workspace-Capability
zugreifen. Polling-Limits beenden früh den Prozessbaum; erst erfolgreiches
Cleanup, leere Slot-Revalidierung und Return geben vollständige Member-Hashes
frei. Unsichere Slots werden quarantänisiert. EBAR-06 bleibt auf direkte
unverschlüsselte ZIP-/RAR4-/RAR5-/7z-/TAR-Fälle beschränkt.

---

# 31. ArchiveMember ist kein FileRecord

Wichtig:

Ein Archivmitglied darf nicht vortäuschen, eine normale physische
Source-Datei zu sein.

Eigene Entity/Evidence:

```text
ArchiveMemberObservation
------------------------
archive_observation_id
volume_group_fingerprint
member_ordinal
member_identity
member_path_safe
member_kind
declared_compressed_bytes
declared_uncompressed_bytes
observed_uncompressed_bytes
member_sha256
crc_status
encryption_status
listing_execution_id
extraction_execution_id
listing_profile
extraction_profile
safety_profile
secret_version
```

Damit bleibt Provenance eindeutig.

---

# 32. Evidence Reuse

Archive Member Evidence kann wiederverwendet werden, wenn identisch:

```text
archive full SHA-256
archive volume set
ToolProvider und Toolversion
Adapter-/Parserversion
Listing-, Extraction- und Safety-Profil
Secret-Version oder `NONE`
```

Die exakten Reuse-Profile heißen `archive-listing-reuse/v1` und
`archive-member-reuse/v1`. Ein neueres terminales Fehler- oder Limitresultat
darf ältere Evidence nicht still als aktuell erscheinen lassen.

Ändert sich eines davon, wird nur die betroffene Ableitung stale.

---

# 33. EB-A3 – archive-aware Matching und finale Deduplication Integration

**entspricht:** EA8–EA10
**Abhängigkeit:** EB-06 + EB-07 + EB-A2

Jetzt kann die generische Matching Engine wiederverwendet werden.

Vergleichsebenen:

```text
Archive bytes
Archive member bytes
Physical file bytes
Edition
Work
```

Beispiele:

### Fall A

```text
archive member SHA256 == physical EPUB SHA256
```

→ bytegleiche Repräsentation.

### Fall B

```text
archive.zip enthält book.epub
filesystem enthält gleiches book.epub
```

→ Member/File Duplicate Evidence.

Nicht automatisch:

```text
archive.zip löschen
```

Das Archiv könnte weitere relevante Inhalte besitzen.

### Fall C

```text
CBZ == publication container
```

→ nicht als redundante Verpackung behandeln.

---

# 34. Archive + Calibre

Keep Preference muss erkennen:

```text
Archive
 ├─ publication container?
 ├─ generic collection?
 ├─ contains Calibre-managed file?
 ├─ contains unique members?
 ├─ multipart?
 └─ sidecars?
```

Eine bestätigte Member/File-Duplicate Relation reicht nicht aus,
den Container als Ganzes als entbehrlich zu klassifizieren.

---

# 35. Finale E-Book-Analysekette

Nach Abschluss sollte die E-Book-Pipeline so aussehen:

```text
Filesystem
    ↓
Incremental Scan
    ↓
Quick Hash
    ↓
Selective Full SHA-256
    ↓
E-Book Tool Evidence
    ├─ Metadata
    ├─ Text
    ├─ Structure
    ├─ Cover
    └─ Quality
    ↓
Filename / Path Evidence
    ↓
Local Entity Resolution
    ↓
Local confirmed Authority Knowledge
    ↓
Provider Cache / Local Dataset
    ↓
optional Structured Provider
    ↓
Classification Assertions
    ↓
Candidate Blocking
    ↓
Feature Extraction
    ↓
Versioned Matcher
    ↓
Relations + Explanations
    ↓
Review
    ↓
Calibre Reconciliation
    ↓
Quality / Keep Preference
    ↓
Archive/Sidecar Dependencies
    ↓
ConsolidationPlan
```

Bis hier:

```text
SOURCE MEDIA READ-ONLY
```

---

# 36. Empfohlene konkrete Entwicklungsreihenfolge

EB-00 bis EB-08/W9 einschließlich EB-03A, EB-03B und EB-04 sind in ihrem
book-only Scope abgeschlossen. In der Archivstrecke sind FG-A und S-EBA-01 bis
S-EBA-07 abgeschlossen; FG-A-RUNTIME, FG-A-IMAGE und
FG-A-RUNTIME-AVAILABILITY sind akzeptiert. S-EBAR-01 bis S-EBAR-03A, EBAR-04
sowie S-EBAR-02A, S-EBAR-02B und S-EBAR-02B2 sind umgesetzt.
FG-A-STORAGE-FAMILY, FG-A-FORMAT-LOCK und die direkten read-only Pakete bis
EBAR-05 sind abgeschlossen. ADR-0050 hält die reale Extractionstrecke mangels
Backend fail-closed gesperrt. ADR-0051 entscheidet die davon unabhängige
read-only Wrapperstrecke; S-EBAR-W01 bis S-EBAR-W04 sind abgeschlossen.
ADR-0052 entscheidet FG-A-PERSISTENCE mit Migration
`0019_archive_evidence`, dedizierten insert-only Snapshottabellen, gebundenem
Reuse und ScanRoot-Fencing. S-EBAR-07 ist umgesetzt. Vor EBAR-08 schließt
ADR-0053 schließt FG-A-COLLECTION-ORCHESTRATION mit stabilem Multi-Volume-
Plan, Lease/Fencing, Resume und path-freiem Status. S-EBAR-08A bis 08D sowie
EBAR-09 sind umgesetzt. ADR-0054 entscheidet FG-A3-MATCHING: S-EBA3-01 bis
S-EBA3-03 dürfen ausschließlich generische Archive-Source-Dependencies in den
nicht ausführbaren Plan integrieren. Member-Byte-Identity bleibt bis
FG-A3-MEMBER-BYTE blockiert.
Die Tabelle bleibt als Abhängigkeitsfolge maßgeblich; sie ist keine zweite
Statusquelle.

| Reihenfolge | Welle | Inhalt | Priorität | Abhängigkeit |
|---:|---|---|---|---|
| 0 | EB-00 | Status-/Provider-Contract bereinigen | P0 | keine |
| 1 | EB-01 | gemeinsame ScanRoot Lease + Fencing | P0 | EB-00 |
| 2 | EB-02 | persistierte Entity Resolution + Review Core | P0 | EB-01 |
| 3a | EB-03A | Provider Cache + Runtime | P1 | EB-01 |
| 3b | EB-04 | Classification Persistence/Projection | P1 | EB-02 |
| 4 | EB-03B | Open-Library-Adapter | P1 | EB-02 + EB-03A |
| 5 | EB-05 | Candidate Blocking + Relation Contracts | P0 | EB-02 |
| 6 | EB-06 | Scoring + Explanation + vollständiges Review | P0 | EB-05 |
| 7 | EB-07 | Calibre Reconciliation | P1 | EB-05; final mit EB-06 |
| 8 | EB-08 | nicht ausführbarer ConsolidationPlan | P0 | EB-06 + EB-07 |
| parallel | EB-A1 | Archive Discovery + Secret Boundary | P1 | EB-01 |
| parallel | EB-A2 | Listing + Sandbox + Member Evidence | P1 | EB-A1 |
| danach | EB-A3 | Archive-aware Matching + Planning | P1 | EB-A2 + EB-06 + EB-07 |

---

# 37. Was ausdrücklich nicht auf dem Critical Path liegen soll

Folgende Dinge dürfen die E-Book-Deduplication nicht blockieren:

- Open Library erreichbar;
- GND erreichbar;
- Wikidata erreichbar;
- generische Web Research;
- Archive Password Provider;
- Music-Welle;
- W10 Executor.

Eine komplett lokale Collection muss bis zum Review-/ConsolidationPlan
verarbeitet werden können.

Fehlende externe Evidence reduziert Confidence beziehungsweise Coverage,
führt aber nicht zum technischen Scheitern der Pipeline.

---

# 38. Globale Teststrategie der folgenden Wellen

## Unit Tests

Für:

- Normalization;
- Resolver Rules;
- Matcher Features;
- Classification Projection;
- Provider Mapping;
- Keep Preference;
- Preconditions.

## Integration Tests

Für:

- SQLite/Alembic;
- Lease/Fencing;
- Resume;
- Review Persistence;
- Provider Cache;
- Candidate Blocking;
- Relation Persistence;
- Calibre Adapter;
- ConsolidationPlan.

## Adversarial Fixtures

Ausschließlich synthetisch oder öffentlich lizenzierte Daten.

Keine privaten:

- Pfade;
- Buchnamen aus privater Collection;
- Hashes;
- Counts;
- Calibre-Daten;
- Archive Passwörter

in Git Fixtures übernehmen.

## Performance Tests

Synthetisch:

- viele Scan Generations;
- große Exact-Duplicate-Gruppe;
- große ISBN-/Title Blocks;
- sparse Metadata;
- sehr viele Authority Aliases;
- große Review History;
- großer Provider Cache.

Besonders wichtig:

```text
kein unbegrenztes N² Pair Materialization
```

---

# 39. Globales Definition-of-Done je Welle

Eine Welle ist erst abgeschlossen, wenn:

1. Domain Contracts konsistent sind.
2. Migration additiv und getestet ist.
3. Unit Tests grün sind.
4. relevante Integration Tests grün sind.
5. Restart-/Failure-Verhalten getestet ist.
6. Source Media read-only bleibt.
7. private Daten nicht als Fixtures eingecheckt wurden.
8. CLI-/Report-Ausgaben keine unerlaubten absoluten Pfade enthalten.
9. Dokumentation dem Code entspricht.
10. Backlog/Project Status aktualisiert sind.
11. keine temporäre Parallelarchitektur zurückbleibt.
12. der nächste Agent aus Repository und Doku eindeutig erkennen kann,
    was als Nächstes zu tun ist.

---

# 40. Bewertung der Alternativen

## Alternative A – zuerst reale Provider

### Vorteil

- schnell sichtbare zusätzliche Metadata;
- früher Test mit realen Authority Sources.

### Nachteile

- noch keine persistierte Resolution;
- Provider Cache noch nicht fertig;
- Review-Entscheidungen noch nicht modelliert;
- Gefahr provider-spezifischer Domainlogik;
- Online-Verfügbarkeit könnte versehentlich Teil der Kernpipeline werden.

### Bewertung

**Nicht empfohlen.**

Provider Research darf parallel laufen; die echte Integration sollte aber auf
EB-02/EB-03A aufbauen.

---

## Alternative B – zuerst Calibre

### Vorteil

Calibre enthält vermutlich bereits sehr viel nützliche Metadata.

### Nachteile

- FolioTone würde früh auf die bestehende Calibre-Sicht geprägt;
- Dateien außerhalb Calibre würden strukturell benachteiligt;
- Authority- und Matching-Modell wären noch nicht fertig;
- Duplicate Identity könnte mit Calibre Records verwechselt werden.

### Bewertung

**Nicht empfohlen.**

Calibre sollte erst in ein bereits provider-neutrales Matchingmodell Evidence
einspeisen.

---

## Alternative C – zuerst Archive

### Vorteil

Archive können einen relevanten Teil des tatsächlichen Bestands erklären.

### Nachteile

- archive-aware Matching benötigt dieselben Relation-/Review-Verträge;
- Gefahr einer zweiten Duplicate Engine;
- Secret-/Sandbox-Thematik erhöht Sicherheitskomplexität erheblich.

### Bewertung

**EA1 Research parallel: ja.**

Vollständiges archive-aware Matching vor EB-06: **nein**.

---

# 41. Gesamtbewertung

Der aktuelle FolioTone-Stand ist an einem wichtigen Übergang:

Die technische Evidence Acquisition ist inzwischen ausreichend weit
entwickelt.

Der nächste Engpass ist nicht mehr:

```text
Wie lese ich ein EPUB/PDF/MOBI?
```

sondern:

```text
Wie transformiere ich widersprüchliche Evidence
in nachvollziehbare Entity-, Relation- und Review-Entscheidungen?
```

Deshalb sollte der Schwerpunkt jetzt von Tool Integration auf folgende
Schichten wechseln:

1. Concurrency Correctness;
2. Resolution;
3. Decision Persistence;
4. Candidate Blocking;
5. Explainable Matching;
6. Human Review;
7. Reconciliation;
8. Planning.

Erst danach entsteht aus FolioTone mehr als ein sehr guter Analyse-Indexer:
eine belastbare, auditierbare E-Book-Konsolidierungsengine – zunächst bewusst
ohne die Fähigkeit, Source Media zu verändern.

---

# 42. Empfohlener unmittelbarer nächster Implementierungsschritt

Die book-only Wellen EB-00 bis EB-08/W9 sind abgeschlossen. FG-A,
S-EBA-01 bis S-EBA-07, FG-A-RUNTIME, S-EBAR-01 bis S-EBAR-03A, FG-A-IMAGE,
FG-A-RUNTIME-AVAILABILITY, EBAR-04, S-EBAR-02A, S-EBAR-02B und S-EBAR-02B2
sind abgeschlossen. ADR-0046 entscheidet FG-A-STORAGE-FAMILY. ADR-0045 ist
akzeptiert, hält FG-A-FORMAT-LOCK aber ausdrücklich offen. Unmittelbar als
Nächstes folgt:

**FG-A-FORMAT-LOCK – finaler maschinenlesbarer Storage-Family-/Fall-Lock mit
getrenntem Digest und strikt verify-only Workflowprüfung.**

Danach folgt S-EBAR-02C strikt in Katalogreihenfolge.
Die produktive Formatparserstrecke ist noch nicht implementiert.
Passwortversuche bleiben bis FG-A-SECRET blockiert. Jede
Filesystem-Mutation, mutierende Calibre-Operation und ausführbare W10-Strecke
bleibt ausgeschlossen.

---

# Quellen für die Provider-/Tool-Entscheidungen

Diese Links sind zeitgebundene Recherchehinweise. Vor EB-03B beziehungsweise
einer Tool- oder Provider-Integration müssen Primärdokumentation, Zugriff,
Lizenz, Datenschutz, Sicherheitsverhalten und Wartungsstatus erneut geprüft
und die Entscheidung im Repository festgehalten werden.

Open Library (2026), *APIs / Usage Guidelines / Rate Limits / Bulk Access*
https://openlibrary.org/developers/api

Open Library (2025), *Search API – Work and Edition data*
https://openlibrary.org/dev/docs/api/search

Open Library, *Data Dumps*
https://openlibrary.org/developers/dumps

Open Library, *Licensing*
https://openlibrary.org/developers/licensing

Deutsche Nationalbibliothek, *Gemeinsame Normdatei (GND)*
https://www.dnb.de/gnd

Deutsche Nationalbibliothek, *GND / Metadatendienste und Gesamtabzüge*
https://www.dnb.de/DE/Professionell/Metadatendienste/Metadatendienste.html

DNB, *SPARQL Service – BETA*
https://sparql.dnb.de/gnd

Wikidata, *Data access*
https://www.wikidata.org/wiki/Wikidata:Data_access

Wikimedia Foundation, *User-Agent Policy*
https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy

calibre, *calibredb documentation*
https://manual.calibre-ebook.com/generated/en/calibredb.html
