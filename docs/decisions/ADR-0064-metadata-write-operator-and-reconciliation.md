# ADR-0064: Bedien- und Reconciliation-Vertrag des EPUB-Titelwriters

- Status: Accepted
- Datum: 2026-08-23

## Kontext

ADR-0063 begrenzt den ersten Source-Metadata-Writer auf genau einen reviewten
EPUB-3-`title`-`REPLACE`. `S-W10-MW01` bis `S-W10-MW04` liefern Preflight,
privates Staging, Authorization, Journal, Linux-Exchange und Recovery, öffnen
aber absichtlich keinen operativen Einstiegspunkt. Der interne Executor endet
bei `ORIGINAL_PRESERVED`.

Für `S-W10-MW05` müssen drei bisher nur als Ziel formulierte Grenzen
konkretisiert werden:

1. der genaue CLI- und zweite Bestätigungsvertrag;
2. die unmittelbare Verifikation der tatsächlich ausgetauschten Source;
3. der sichere Übergang von der `METADATA_WRITE_RUN`-Lease zu einem neuen
   `ScanRun` und zurück zu einer frischen Fence für den Abschluss.

Ein Scan kann die Root-Lease nicht gleichzeitig mit dem Metadata-Write-Run
halten. Ein ungeprüftes Freigeben der Lease würde dagegen eine Lücke zwischen
Source-Mutation, Scan und `VERIFIED` erzeugen. Der Abschluss benötigt deshalb
einen expliziten, crash-resumierbaren Lease-Handoff.

## Entscheidung

### Feste Bedienoberfläche

MW05 ergänzt ausschließlich diese CLI-Kommandos:

```text
metadata-write-authorize
  --plan-id UUID
  --plan-content-hash SHA256
  --capability-id UUID

metadata-write-execute
  --plan-id UUID
  --plan-content-hash SHA256
  --capability-id UUID
  --authorization-id UUID

metadata-write-recover
  --plan-id UUID
  --plan-content-hash SHA256
  --capability-id UUID
  --authorization-id UUID

metadata-write-status --run-id UUID
```

`--output text|json` darf ausschließlich die Darstellung wählen. Datenbank,
privater Stagingbereich, Capability-Konfiguration und feste Toolpfade stammen
aus lokaler Runtime-Konfiguration beziehungsweise den bereits bestehenden
Environment-Verträgen. Source-, Recovery- oder Stagingpfade sind keine
CLI-Argumente.

Standardausgabe, JSON und Fehler enthalten nur opaque IDs, Profile, Zustände,
Zeitpunkte, Counts und feste Fehlercodes. Insbesondere bleiben Titel, Pfade,
Dateinamen, Source-/Output-Hashes, Confirmation-Digests und Capability-Inhalte
privat.

### Authorize

`metadata-write-authorize` revalidiert vor Source-I/O Plan-ID, Plan-Content-
Hash und Capability-ID. Unter einer kurzlebigen
`METADATA_WRITE_PREPARATION`-Lease ermittelt der Store den aktuellen privaten
Observation-Locator, während derselben Fence bleibt der W9-Plan einschließlich
Review- und Dependency-Lineage aktuell.

Die Source wird no-follow und bounded über die Capability geöffnet. Der
Prepare-Schritt baut den deterministischen Output im owner-only privaten
Staging, prüft Input und Output mit den festen ADR-0063-Validatoren und
persistiert erst danach die höchstens 15 Minuten gültige Authorization. Eine
abgebrochene Vorbereitung erzeugt weder Authorization noch Run und mutiert die
Source nicht.

### Zweite Bestätigung und Runerzeugung

Die zweite Bestätigung gehört unmittelbar vor die einmalige Runerzeugung in
`metadata-write-execute`, nicht vor den nicht mutierenden Prepare-Schritt. Die
CLI zeigt ausschließlich den festen Satz

```text
CONFIRM METADATA WRITE <Authorization-ID>
```

und akzeptiert ihn exakt als eine Zeile über `stdin`. Er ist kein Argument,
keine Environment-Variable und wird weder ausgegeben noch geloggt. Ein
domänengetrennter SHA-256 bindet die bestätigte Authorization zusammen mit
Plan-ID, Plan-Content-Hash und Capability-ID. Nur dieser Digest wird im
`CREATED`-Event gespeichert. Ein fehlender oder abweichender Satz erzeugt
keinen Run.

Ein Retry derselben bereits verbrauchten Authorization darf nur denselben Run
fortsetzen. `PREPARED`, `EXCHANGED` oder ein uneindeutiger Status wird nicht
durch Execute übersprungen, sondern auf den festen Recovery-Pfad verwiesen.

### Unmittelbare Post-write-Verifikation

Nach `RENAME_EXCHANGE` und `RENAME_NOREPLACE`, aber vor dem erfolgreichen
`ORIGINAL_PRESERVED`-Abschluss, liest der weiterhin gefencete Executor die
tatsächliche Source no-follow zurück. Er verlangt den exakten autorisierten
Output, dieselben regulären Datei-, Owner-, Group-, Mode-, Link- und
Xattr-Grenzen und Bytegleichheit mit dem zuvor vollständig verifizierten
Staging-Output. Der feste Metadaten-, EPUBCheck-, Text- und Cover-Validator
wird danach erneut ausgeführt. Seine Evidence muss exakt der an die
Authorization gebundenen Evidence entsprechen.

Schlägt diese Verifikation fehl, bleibt der Run nicht erfolgreich bei
`ORIGINAL_PRESERVED`. Solange die physische Hashverteilung eindeutig ist,
wird innerhalb derselben autorisierten Operation das Original
wiederhergestellt; andernfalls folgt `MANUAL_RECOVERY_REQUIRED`.

### Lease-Handoff, Scan und Collection-Reconciliation

Nach erfolgreicher unmittelbarer Verifikation und `ORIGINAL_PRESERVED` gilt
folgende feste Folge:

1. Die `METADATA_WRITE_RUN`-Lease wird explizit freigegeben.
2. Ein neuer vollständiger, aber inkrementell wiederverwendender Scan mit
   einem Hash-Worker erzeugt einen `COMPLETED`-`ScanRun`. Unveränderte Dateien
   werden nicht erneut gehasht; die geänderte Source benötigt einen neuen
   vollständigen SHA-256.
3. Der Scan muss dieselbe `FileRecord`-Lineage, eine neue
   `FileObservation` und exakt den autorisierten Output-Hash belegen.
4. Aus genau diesem Scan entsteht ein immutable `collection-state/v1`.
   Vorhandene Analysis-, Resolution-, Classification-, Matching-, Review-,
   Calibre-, Archive-, Consolidation- und Quarantine-Evidence wird darin
   korrekt als `CURRENT`, `STALE`, `UNSCOPED` oder `MISSING` neu projiziert.
   MW05 startet keine unbeschränkte automatische Vollanalyse und übernimmt
   keine alte Evidence still als aktuell.
5. Der Metadata-Write-Run erwirbt dieselbe Root unter einer neuen
   `METADATA_WRITE_RUN`-Fence. Er revalidiert den physischen Output erneut und
   bindet Scan, neue Observation und `CollectionState` immutable in
   `metadata-write-reconciliation/v1`.
6. Reconciliation-Insert und `VERIFIED`-Event entstehen atomar unter dieser
   frischen Fence.

Ein bereits abgeschlossener passender Scan nach `ORIGINAL_PRESERVED` darf bei
einem crashbedingten Retry wiederverwendet werden. Ein älterer Scan, eine
abweichende Observation, ein fehlender Full-Hash, ein nicht passender
`CollectionState` oder ein inzwischen veränderter physischer Zustand blockiert
`VERIFIED`.

### Recovery-Reconciliation

`metadata-write-recover` verwendet weiterhin ausschließlich die einmal
autorisierte Exact-State-Recovery aus ADR-0063. Nach `RECOVERED` führt dieselbe
Scan-/`CollectionState`-Folge den wiederhergestellten Original-Hash nach. Die
Reconciliation wird immutable mit Outcome `RECOVERED` gespeichert; es entsteht
kein `VERIFIED`-Event. Damit kann ein Crash nach physischer Wiederherstellung,
aber vor dem Scan, durch denselben Recovery-Aufruf sicher fortgesetzt werden.

`VERIFIED` bleibt irreversibel für diese Authorization. Eine fachliche
Rücknahme danach ist weiterhin ein separat geplanter Rollback mit neuer
Authorization.

## Persistenz

Migration `0029_metadata_write_reconciliation` ergänzt genau eine immutable
Reconciliation je Run. Sie bindet ausschließlich:

- Run und Outcome `VERIFIED` oder `RECOVERED`;
- den abgeschlossenen neuen `ScanRun`;
- die neue `FileObservation`;
- den content-addressed `CollectionState`;
- einen privaten Physical-Confirmation-Digest;
- Zeitpunkt und content-addressed Reconciliation-Digest.

Update und Delete bleiben per Trigger gesperrt. Der Store prüft die aktuelle
Fence, die vollständige Run-/Authorization-Lineage, den letzten Journalstatus,
Scan-/Observation-/Full-Hash-Lineage sowie den passenden
`CollectionState`-Eintrag in derselben Transaktion. Ein belegter Zustand
blockiert den Downgrade.

## Folgen

- Der erste Source-Metadata-Write besitzt nach MW05 eine vollständige CLI-
  Bedien-, Verifikations-, Scan-, Reconciliation- und Recoverykette.
- Der notwendige Scan unterbricht die Root-Exklusivität nicht still, sondern
  ist ein expliziter Lease-Handoff mit erneuter physischer Prüfung.
- `CollectionState` macht veraltete abgeleitete Evidence sichtbar; MW05
  behauptet keine kostenintensive vollständige Neuanalyse der Sammlung.
- REST-API und GUI bleiben gemäß FUT-011 geschlossen und dürfen später nur
  dieselben Application-Verträge aufrufen.
- Andere Formate, Felder, Zielträger und Mutationstypen bleiben hinter ihren
  eigenen Gates geschlossen.

## Verifikation

MW05 verwendet ausschließlich synthetische EPUBs, SQLite-Datenbanken und
temporäre Dateisysteme. Lokale Tests bleiben auf Confirmation, CLI-Privacy,
Store-/Migration-Invarianten, Post-write-Read-back, Lease-Handoff, Scan-
Lineage, Crash-Retry und Recovery-Reconciliation begrenzt. Der stabile
Pull-Request-Head erhält genau einen vollständigen CI-Gate einschließlich des
bereits vorhandenen Linux-`renameat2`-Konformitätsnachweises.
