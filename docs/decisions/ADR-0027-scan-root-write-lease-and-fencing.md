# ADR-0027: Gemeinsame `ScanRoot`-Write-Lease und monotones Fencing

- Status: Accepted
- Datum: 2026-08-17

## Kontext

Die bisherigen Leases für `ScanRun`, `EbookCandidateHashRun` und
`EbookCollectionRun` schützen jeweils nur Läufe derselben Art. Sie verhindern
nicht, dass Scanner, selektives Vollhashing, Collection-Analyse oder eine
einzelne E-Book-Analyse für denselben `ScanRoot` abwechselnd gültige SQLite-
Transaktionen schreiben. SQLite serialisiert physische Writer, stellt aber
kein fachliches Besitzrecht bereit. Ein abgelaufener Prozess kann zudem nach
einer Übernahme weiterrechnen und ohne zusätzliches Fencing verspätete
Ergebnisse speichern.

## Entscheidung

Alembic `0012_scan_root_write_leases` führt einen dauerhaften Mutex-/Sequencer-
Slot je `ScanRoot` ein. Die Tabelle `scan_root_write_leases` besitzt den
`scan_root_id` als Primär- und Fremdschlüssel sowie Owner-Art, Owner-Run-ID,
geheimes Lease-Token, Zeitpunkte und einen monoton steigenden `fence_epoch`.
Ein freier Slot bleibt als inaktive Tombstone-Zeile erhalten; dadurch geht die
Epoch-Historie bei Release und erneutem Acquire nicht verloren.

Zulässige Owner-Arten sind:

- `SCAN_RUN`;
- `EBOOK_CANDIDATE_HASH_RUN`;
- `EBOOK_COLLECTION_RUN`;
- `EBOOK_ANALYSIS`.

`owner_run_id` ist bewusst polymorph und besitzt keinen SQL-Fremdschlüssel.
Eine einzelne Spalte kann in SQLite nicht abhängig von `owner_kind` auf vier
verschiedene Tabellen zeigen. Der jeweilige Workflow validiert Owner,
`scan_root_id`, Laufstatus und Token in derselben Schreibtransaktion. Der
`scan_root_id` bleibt durch einen echten Fremdschlüssel geschützt.

Ein Acquire erhöht `fence_epoch` exakt um eins. Release und Heartbeat ändern
die Epoch nicht. Selbst bei absichtlich wiederverwendetem Token und Owner-ID
weist die neue Epoch einen alten Besitzer ab. Ein Epoch-Überlauf wird
verweigert und niemals zurückgesetzt.

## Transaktions- und Takeover-Regel

Jede rootbezogene Schreibtransaktion führt als erste Schreiboperation ein
bedingtes `UPDATE` auf dem Root-Lease-Slot aus. Die Bedingung umfasst
`scan_root_id`, Owner-Art, Owner-ID, Token, Epoch und eine noch nicht
abgelaufene Lease. Erst danach folgen Lauf-Fence und Fachdaten. Dadurch nimmt
die Prüfung zugleich den SQLite-Writer-Lock; ein vorgelagertes `SELECT` wäre
kein ausreichendes Fence.

Acquisition, Owner-Run-Anlage und fachliche Ausgangsvalidierung bilden eine
Transaktion. Heartbeat erneuert Root- und vorhandene Run-Lease atomar. Finish
setzt zuerst den Lauf terminal und gibt den Root-Slot zuletzt in derselben
Transaktion frei. Fingerprint- und Fortschrittswrites des Kandidaten-Hashers
bleiben ebenfalls atomar.

Eine aktive Lease blockiert jeden anderen Writer desselben Roots. Ein
abgelaufener Cross-Kind-Owner wird nicht still überschrieben. Candidate-
Hashing darf einen abgelaufenen früheren Candidate-Lauf nur zusammen mit
dessen atomarem Übergang auf `INTERRUPTED` übernehmen. Collection-Resume darf
nur denselben persistierten Collection-Lauf übernehmen. Scan-Recovery bleibt
explizit und terminalisiert ausschließlich den passenden abgelaufenen
`ScanRun`. Fehlende, widersprüchliche oder ungefencte Altzustände schlagen
geschlossen fehl.

## Abgedeckte Writes und lange Arbeit

Der gemeinsame Fence schützt Scan-Batches, Observations und Events,
Fingerprint-Batches, `MISSING`-/`DELETED`-Übergänge, Relocation-Kandidaten,
Candidate-Hash-Fortschritt sowie Collection-Lauf-, Item- und Evidence-Writes.
Generische Evidence-Repositories erhalten während eines Collection-Workers
einen explizit im Worker gesetzten Write-Scope; eine implizite Weitergabe über
Thread-Grenzen findet nicht statt.

Scanner und Collection-Analyse besitzen wie das Kandidaten-Hashing einen
separaten Lease-Keeper. Hashing, Dateilesen und Toolausführung halten keine
lang laufende Datenbanktransaktion offen. Ein Keeper-Fehler wird vor dem
nächsten Commit sichtbar; der abschließende Fence verhindert auch dann jeden
späten Write. Keeper und Worker werden vor dem terminalen Finish vollständig
beendet.

## Migration und Betrieb

Migration `0012` ist additiv und ergänzt außerdem den partiellen Unique-Index
`uq_scan_runs_active_root` für höchstens einen `RUNNING`-Scan je Root. Vor dem
DDL müssen Scanner, Candidate-Hasher und Collection-Analyse vollständig
ruhen. Die Migration verweigert ein Upgrade bei einem `RUNNING`-Lauf, weil ein
alter Prozess die neue Lease nicht besitzen kann. Ein Downgrade wird bei
einem aktiven Root-Slot ebenfalls verweigert; es verliert die Epoch-Historie
und ist nur bei vollständig gestoppten Writern zulässig.

Die Migration legt keine privaten Pfade, Dateinamen oder Hashwerte ab. Tokens
werden weder in `repr`, Statusausgaben noch Fehlermeldungen ausgegeben.
Kollisionen und Lease-Verlust werden path-frei gemeldet.

## Konsequenzen und Grenzen

- Für einen `ScanRoot` kann genau einer der benannten Runtime-Writer legitim
  Datenbankänderungen committen.
- Verschiedene Roots bleiben logisch unabhängig; kurze SQLite-Writer-
  Serialisierung bleibt eine Eigenschaft der einzelnen Datenbankdatei.
- Das Modell ist kein verteiltes Lock außerhalb derselben SQLite-Datenbank.
- Source Media bleiben read-only. Die W10-Sperre für Mutation, Quarantäne und
  Löschung bleibt unverändert.
- Die Collection-Plananlage bleibt in EB-01 eine atomare Transaktion. Eine
  spätere persistierte, gebatchte Planning-Phase kann die Writer-Haltezeit
  reduzieren, ändert aber nicht den Fencing-Vertrag.

## Verifikation

Deterministische Tests mit getrennten Engines, Threads, Barriers und
synthetischen Daten prüfen Einzelbesitz, Root-Isolation, Cross-Workflow-
Kollisionen, monotone Epochs, ABA-Schutz, stale Fencing, atomaren Rollback,
Keeper- und Prozessabbruchpfade, Migration-Quiescence, Schema-Constraints und
Downgrade-Sperre. Timing-Sleeps und reale Sammlungsdaten sind kein Bestandteil
des Correctness-Vertrags.
