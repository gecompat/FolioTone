# Begrenzte E-Book-Duplikatquarantäne

Diese Anleitung beschreibt den aktuellen ADR-0056-Bedienstand. Verfügbar sind
`quarantine-authorize` und `quarantine-execute` für genau einen reviewten
`EXACT_DUPLICATE`-Candidate. Authorize verändert Source Media nicht; Execute
darf nach der vollständigen zweiten Prüfung genau diesen Candidate in den
privaten Same-Filesystem-Quarantänebereich verschieben. `quarantine-recover`
ist noch nicht verfügbar und folgt in einem getrennten Arbeitspaket.

Die Authorization öffnet keine allgemeine Move-, Rename-, Purge-, Calibre-,
Sidecar-, Archiv- oder Metadaten-Schreibschnittstelle. Die nicht atomare
Ziel-Abwesenheitsprüfung des vorhandenen Interim-Executors bleibt durch
`FG-W10-MOVE-BACKEND` sichtbar begrenzt.

## Voraussetzungen

Vor `quarantine-authorize` müssen alle folgenden Bedingungen erfüllt sein:

- ein persistierter `ConsolidationPlan` mit Status
  `APPROVED_NON_EXECUTABLE`, Execution-State `NOT_EXECUTABLE` und ohne
  Blocker;
- eine bestätigte FILE/FILE-Relation `EXACT_DUPLICATE` und eine gerichtete
  Keeper-/Candidate-Entscheidung;
- die jeweils neuesten kompatiblen `ACCEPT`-Entscheidungen für Keep
  Preference und Consolidation Candidate;
- Candidate-Dependencies `CALIBRE`, `SIDECAR` und `ARCHIVE` jeweils als
  `KNOWN_NONE`;
- aktuelle FileRecord-, FileObservation-, Größen-, Modified- und vollständige
  SHA-256-Preconditions derselben Plan-Generation;
- Keeper und Candidate als vorhandene, lesbare reguläre Einzeldateien ohne
  Symlink, Reparse Point, Special-File-Typ oder Hardlink-Mehrfachreferenz;
- eine beschreibbare Runtime-Datenbank sowie eine private lokale
  Quarantäne-Capability für denselben `ScanRoot`.

Authorize lädt Plan und aktuelle Lineage aus SQLite, ermittelt die beiden
relativen Locator ausschließlich intern und streamt beide Dateien für die
vollständige SHA-256-Prüfung. Bei einem Fehler entsteht kein
`quarantine-authorization/v1`-Datensatz. Source Media wird dabei nur gelesen.

## Runtime-Konfiguration

Keines der Kommandos nimmt Datenbank-, Source- oder Zielpfade als Argumente
an. Der lokale Prozess erhält stattdessen:

| Variable | Bedeutung | Standard |
|---|---|---|
| `FOLIOTONE_DATABASE` | Beschreibbare Runtime-SQLite-Datenbank. | `/data/foliotone.db` |
| `FOLIOTONE_QUARANTINE_CAPABILITIES_FILE` | Absolute Datei mit der privaten Capability-Zuordnung. | keiner |

Die Capability-Datei ist eine reguläre POSIX-Datei des aktuellen Users mit
Mode `0600`, genau einem Hardlink und ohne Symlink-/Reparse-Komponenten. Sie
ist auf 64 KiB und 128 Einträge begrenzt. Native Windows-Auflösung schlägt
fail-closed mit `TOOL_UNAVAILABLE` fehl; der operative Zielpfad ist
Docker/Linux.

Ein syntaktisches Beispiel mit ausschließlich fiktiven IDs und Pfaden lautet:

```json
{
  "capabilities": [
    {
      "quarantine_capability_id": "10000000-0000-0000-0000-000000000001",
      "scan_root_id": "20000000-0000-0000-0000-000000000001",
      "scan_root_directory": "/operator/source",
      "quarantine_directory": "/operator/quarantine"
    }
  ]
}
```

Alle Source- und Quarantäneverzeichnisse der Datei müssen paarweise disjunkt
sein. Für eine erfolgreiche Authorization müssen Source und Quarantäne auf
derselben vom Betriebssystem gemeldeten Filesysteminstanz liegen. Absolute
Pfade, Mountpunkte und Volume-Namen werden weder persistiert noch ausgegeben.

## Authorization

Die drei Binder stammen aus dem lokalen Planbericht und der privaten
Capability-Verwaltung:

```text
foliotone quarantine-authorize \
  --plan-id <Plan-ID> \
  --plan-content-hash <64-stelliger-kleingeschriebener-SHA-256> \
  --capability-id <Capability-ID> \
  --output json
```

Die erfolgreiche Ausgabe enthält ausschließlich Authorization-, Plan- und
ScanRoot-ID, Profil, Status sowie Beginn und Ende des höchstens 15 Minuten
offenen Zeitfensters. Sie enthält keine Pfade, Dateinamen, Materialhashes,
Review-Digests oder Capability-Inhalte.

Intrinsische Planblocker werden als feste öffentliche Blocker-Codes
ausgegeben. `PLAN_UNAVAILABLE`, `PLAN_MISMATCH`, `CAPABILITY_MISMATCH`,
`TOOL_UNAVAILABLE` und `STALE` bleiben ebenfalls materialfrei. `STALE`
bedeutet, dass aktuelle persistierte oder physische Evidence nicht mehr exakt
zur gebundenen Plan-Generation passt.

Eine Authorization darf nicht als erfolgreicher Quarantänelauf interpretiert
werden. Sie ist höchstens 15 Minuten gültig und kann genau einen Execution-Run
erzeugen.

## Execute

Execute verwendet dieselben drei Binder und zusätzlich die opaque
Authorization-ID:

```text
foliotone quarantine-execute \
  --plan-id <Plan-ID> \
  --plan-content-hash <64-stelliger-kleingeschriebener-SHA-256> \
  --capability-id <Capability-ID> \
  --authorization-id <Authorization-ID> \
  --output json
```

Das Kommando schreibt genau eine pfadfreie Bestätigungsaufforderung nach
`stderr`:

```text
CONFIRM QUARANTINE <Authorization-ID> <Plan-ID>
```

Der Operator muss exakt diese eine Zeile über `stdin` zurückgeben. Die Eingabe
ist auf 256 Zeichen einschließlich Zeilenende begrenzt, wird nicht als
Argument oder Environment Variable angenommen und weder persistiert noch in
der Ausgabe wiederholt. Ein domänengetrennter Digest bindet die kanonischen
IDs, den Authorization-Content-Hash, die Capability-ID und den Zeitpunkt der
Bestätigung.

Nach der Eingabe prüft der Operator Authorization-Ablauf und -Verbrauch,
Plan, aktuelle Reviews und Dependencies, Capability, Keeper und Candidate
erneut. Keeper und Candidate werden unter einer
`CONSOLIDATION_QUARANTINE_RUN`-Lease streaming-basiert gegen Größe,
Modified-Zeitpunkt und vollständigen SHA-256 geprüft. Erst danach entstehen
Execution-Run und bestätigtes `PREPARED`-Event atomar unter derselben Fence-
Epoch. Die eindeutige Authorization-Bindung verhindert einen zweiten Run.
Eine abgelaufene Quarantäne-Lease darf Execute nur in einer sofort
serialisierten SQLite-Transaktion mit einer neuen Fence-Epoch übernehmen, wenn
für ihre Owner-Run-ID noch kein persistierter Run existiert. Bei vorhandenem
Run ist ausschließlich die spätere Recovery zuständig.

Der vorhandene Interim-Executor prüft Candidate, Same-Filesystem und
Zielabwesenheit erneut, führt genau ein `os.rename` aus und verifiziert am
Ziel vollständigen SHA-256 sowie Source-Abwesenheit. Die Zielprüfung ist
weiterhin nicht atomar und darf nicht als No-Replace-Garantie interpretiert
werden. Es gibt keinen Copy+Delete-, Cross-Volume- oder Overwrite-Fallback.

Eine erfolgreiche Ausgabe enthält ausschließlich Authorization-, Run-, Plan-
und ScanRoot-ID, Profil und `COMPLETED`. Feste Fehlercodes bleiben pfad-,
dateinamen- und materialhashfrei. Falls bereits ein Run existiert oder nach
`PREPARED` ein Fehler beobachtet wurde, kann zusätzlich dessen opaque Run-ID
ausgegeben werden. Eine verbrauchte Authorization darf nicht erneut
ausgeführt werden. Bis `S-W10-05D` Recovery bereitstellt, muss ein nicht
abgeschlossener Run über `quarantine-status` read-only untersucht und ohne
weitere Mutation gestoppt werden.

Rollback, Purge und automatische Bereinigung bleiben unabhängig gesperrt.
