# ADR-0025: Wiederherstellbare `ScanRun`-Leases

- Status: Accepted
- Datum: 2026-08-16

## Kontext

ADR-0015 setzt einen kontrollierten `KeyboardInterrupt` persistent auf
`INTERRUPTED`. Ein harter Prozessabbruch, Hostverlust oder externes Beenden kann
diesen Cleanup jedoch umgehen. Der letzte durable Zustand bleibt dann
`RUNNING`, obwohl kein Prozess mehr arbeitet. Ein solcher Lauf ist nach dem
bisherigen Vertrag nicht resumierbar und kann den realen Collection-Workflow
blockieren.

Eine automatische Übernahme jedes alten `RUNNING`-Laufs wäre unsicher. Ein
langsamer, aber aktiver Scanner darf nicht gleichzeitig von einem zweiten
Prozess fortgesetzt werden. Prozess-IDs sind dafür kein portabler
Persistenzvertrag, weil Datenbank und Source Root auch über Container- oder
Hostgrenzen verwendet werden können.

## Entscheidung

Jeder neu gestartete `ScanRun` erhält eine zufällige prozesslokale
`lease_token` und eine `lease_expires_at`-Zeit. Die Standarddauer beträgt 30
Minuten. Der Scanner erneuert die Lease vor und nach jedem begrenzten
Discovery-/Hash-Batch sowie vor und nach der Abwesenheits- und
Relocation-Phase. Der terminale Übergang entfernt beide Lease-Felder.

Der explizite CLI-Schalter `foliotone scan --recover-stale-running` führt genau
folgende atomare Operation aus:

1. Er wählt den neuesten `RUNNING`-Lauf desselben logischen `ScanRoot`.
2. Eine noch nicht abgelaufene Lease blockiert die Recovery.
3. Eine abgelaufene Lease oder ein aus einer älteren Migration stammender
   ungeleaster `RUNNING`-Lauf wird genau einmal auf `INTERRUPTED` gesetzt.
4. Anschließend beginnt ein neuer `ScanRun` mit
   `resumed_from_run_id` zum wiederhergestellten Vorgänger.

Der Schalter ist eine ausdrücklich angeforderte Recovery. Vor seiner Verwendung
muss betrieblich geprüft werden, dass der frühere Prozess nicht mehr aktiv ist.
Ein normaler Scan übernimmt keinen fremden Lauf implizit.

Alembic `0009_scan_run_leases` ergänzt die beiden nullable Lease-Spalten und
den Index `ix_scan_runs_root_status_lease`. Nullable Felder erhalten die
Lesbarkeit vorhandener terminaler Läufe und machen vor der Migration
liegengebliebene `RUNNING`-Datensätze ausdrücklich recoverbar.

## Resume- und I/O-Vertrag

Die Recovery ändert ADR-0015 nicht: Der neue Lauf wiederholt die vollständige
streaming-basierte Filesystem Discovery, weil kein portabler persistenter
`os.scandir`-Cursor eingeführt wird. Bereits verarbeitete unveränderte Dateien
werden nicht erneut für Hashing geöffnet. Die vollständige jüngste
Fingerprint-Evidence wird auf die neue `FileObservation` projiziert; nur
fehlende jüngste Evidence wird selektiv neu berechnet.

Die `MISSING`-/`DELETED`-Phase bleibt an eine vollständig erfolgreiche
Discovery gebunden. Der wiederhergestellte partielle Vorgänger erzeugt deshalb
keine Abwesenheitsentscheidung.

## Fehler- und Konkurrenzfälle

- Eine aktive Lease erzeugt einen technischen Fehler ohne Statusänderung.
- Heartbeat und Recovery verwenden bedingte atomare Updates. Gewinnt ein
  Heartbeat die Konkurrenz, scheitert die Recovery; gewinnt die Recovery, kann
  der frühere Besitzer den Lauf nicht mehr terminal überschreiben.
- Ein kontrollierter `KeyboardInterrupt` und sonstige abfangbare
  Prozessunterbrechungen setzen den Lauf weiter unmittelbar auf `INTERRUPTED`.
- Ein interner `Exception`-Fehler setzt den Lauf weiterhin auf `FAILED`, sofern
  die Invocation ihre Lease noch besitzt.
- Nicht abfangbare Prozessbeendigungen werden nach Lease-Ablauf recoverbar.

## Konsequenzen

- Ein hart verwaister realer Scan blockiert die Pipeline nicht dauerhaft.
- Ein aktiver Scanner ist gegen eine zweite Recovery-Invocation geschützt.
- Resume-Lineage und partielle Evidence bleiben vollständig auditierbar.
- Es entsteht kein collection-weites Cursor- oder Pfad-Checkpointing.
- Source Media bleibt read-only; Lease, Recovery und Resume verändern nur
  private Runtime-Persistenz.
