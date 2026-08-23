# Begrenzte E-Book-Duplikatquarantäne

Diese Anleitung beschreibt den aktuellen ADR-0056-Bedienstand. Verfügbar ist
ausschließlich `quarantine-authorize` für genau einen reviewten
`EXACT_DUPLICATE`-Candidate. Das Kommando verschiebt, kopiert, löscht oder
ändert keine Datei. `quarantine-execute` und `quarantine-recover` sind noch
nicht verfügbar und folgen in getrennten Arbeitspaketen.

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

Das Kommando nimmt keine Datenbank-, Source- oder Zielpfade als Argumente an.
Der lokale Prozess erhält stattdessen:

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
werden. Erst das getrennte künftige Execute-Kommando darf nach erneuter
vollständiger Revalidierung, zweiter Bestätigung über begrenztes `stdin` und
erworbener `CONSOLIDATION_QUARANTINE_RUN`-Lease den engen Interim-Executor
aufrufen. Rollback, Purge und automatische Bereinigung bleiben davon
unabhängig gesperrt.
