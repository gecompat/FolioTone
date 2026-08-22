# ADR-0056: Gefencete Quarantäne als erste W10-Operation

- Status: Accepted
- Datum: 2026-08-21

## Kontext

W0 bis W9 analysieren Source Media read-only. ADR-0034 liefert mit
`consolidation-plan/v1` vollständige, aber ausdrücklich nicht ausführbare
Pläne. Ein Plan kann einen bestätigten exakten File-Duplikatfall, Keeper und
Candidate, zwei akzeptierte Reviews, vollständige Preconditions sowie spätere
Operation-Intents beschreiben. Er ist trotzdem keine Mutationsfreigabe.

Der nächste E-Book-Schritt soll Datenverlust nicht durch eine sofortige
Löschung riskieren. Die erste W10-Operation wird deshalb ausschließlich eine
restartbare Quarantäne eines einzelnen Candidate-Files. Purge, Metadatenwrite,
Calibre-Mutation, Sidecar-/Archiv-Umschreibung und Verzeichnisbereinigung
bleiben getrennte spätere Entscheidungen.

Eine sichere Quarantäne darf nicht von ext4, NTFS, Btrfs, XFS oder einem
anderen konkreten Dateisystem abhängen. Entscheidend ist eine vor Ausführung
mechanisch bewiesene Capability: derselbe Volume-/Filesystem-Kontext und ein
atomarer Move ohne Überschreiben. Fehlt dieser Beweis, bleibt die Operation
`TOOL_UNAVAILABLE`.

## Entscheidung

W10 wird in kleine, getrennte Pakete geöffnet. ADR-0056 akzeptiert zunächst
Vertrag, Persistenz und read-only Status einer Quarantäneoperation.

### Interim amendment (2026-08-22)

Für den eng begrenzten ersten Executor ist eine reale Ein-Datei-Quarantäne
zulässig. Er verwendet ausschließlich `os.rename` innerhalb desselben vom
Betriebssystem gemeldeten Filesystems, prüft das opaque Ziel unmittelbar davor
auf Abwesenheit und führt weder Copy+Delete noch einen Cross-Volume-Fallback
aus. Er persistiert `PREPARED` vor der Mutation sowie `MOVED`, `VERIFIED` und
`COMPLETED` danach und prüft am Ziel erneut den vollständigen SHA-256.

Diese Zielprüfung ist auf einigen Plattformen **nicht atomar**: Zwischen
Prüfung und `os.rename` bleibt eine konkurrierende Erzeugungs-/Replace-Race
möglich. Der Interim-Executor behauptet deshalb keine atomare No-Replace-
Semantik und ist kein generischer Move-Backendvertrag. `FG-W10-MOVE-BACKEND`
bleibt als getrennte Frontier-Härtung im Backlog; erst dort werden atomarer
No-Replace, no-follow Elternverzeichnisse sowie Crash-, Race- und
Cross-Device-Nachweise verbindlich. Bis dahin dürfen keine weiteren
Mutationstypen oder Fallbacks hinzukommen.

### Zulässiger Gegenstand

`quarantine-execution/v1` akzeptiert genau einen Plan, wenn unmittelbar vor
der Autorisierung und erneut unmittelbar vor der Mutation gilt:

1. `ConsolidationPlan.profile == consolidation-plan/v1`;
2. Planstatus `APPROVED_NON_EXECUTABLE`, Execution-State `NOT_EXECUTABLE` und
   keine Blocker;
3. Identity ist `EXACT_DUPLICATE`, FILE/FILE und `CONFIRMED`;
4. Keeper und Candidate sind verschieden, gerichtet und besitzen vollständige
   aktuelle File-/Observation-/Full-SHA-256-/Size-/Modified-Preconditions;
5. beide erforderlichen Reviews sind die neuesten kompatiblen `ACCEPT`-
   Entscheidungen und unverändert;
6. Candidate-Dependencies `CALIBRE`, `SIDECAR` und `ARCHIVE` sind jeweils
   `KNOWN_NONE`; `UNKNOWN`, `NOT_APPLICABLE` oder `KNOWN_PRESENT` blockieren;
7. der Keeper ist präsent, lesbar und sein vollständiger SHA-256 stimmt;
8. der Candidate ist eine einzelne reguläre Datei, präsent und sein
   vollständiger SHA-256 stimmt; der vollständige no-follow-Nachweis bleibt
   Teil der späteren `FG-W10-MOVE-BACKEND`-Härtung;
9. Plan, Root, Scan, FileRecord, FileObservation, Reviews und Dependencies
   gehören exakt zur gebundenen Generation.

Es gibt keine Batchausführung. Eine Authorization und ein Execution-Run
bezeichnen genau einen Candidate. Archive-Member, Wrapper, Verzeichnisse,
Symlinks, Reparse Points, Hardlink-Mehrfachreferenzen, Special Files und
extern verwaltete Calibre-Dateien sind in v1 nicht ausführbar.

### Separate, ausdrückliche Authorization

Ein vorhandener W9-Plan wird niemals umgedeutet. Vor einer Ausführung wird ein
neuer insert-only `quarantine-authorization/v1`-Snapshot erzeugt. Er bindet:

```text
id
profile
plan_id
plan_content_hash
scan_root_id
keeper_file_id
candidate_file_id
keeper_observation_id
candidate_observation_id
keeper_full_sha256
candidate_full_sha256
quarantine_capability_id
review_fingerprint
authorized_at
expires_at
content_hash
```

Die CLI verlangt dabei die explizite Angabe von Plan-ID und vollständigem
Plan-Content-Hash. Der getrennte Ausführungsaufruf ist interaktiv und verlangt
über den nicht geloggten Standard-Input die vollständige Authorization-ID und
Plan-ID erneut. Es gibt keinen Secret-/Nonce-Wert in argv, Shell-History,
Environment, Log oder öffentlichem DTO. Ein append-only Bestätigungs-Event
bindet durch `confirmation_digest` nur die kanonischen opaque IDs,
Authorization-Content-Hash und den Zeitpunkt dieser zweiten Bestätigung.
Authorization ist höchstens 15 Minuten gültig, einmal verwendbar und wird bei
jeder materiellen Plan-/Review-/Precondition-/Capability-Änderung effektiv
`STALE`.

Ein Konfigurationsschalter, eine Plan-ACCEPT-Decision oder der bloße Besitz
einer Plan-ID reicht nicht. Fehler und öffentliche Reports geben weder
Bestätigungseingabe, Hashes, Pfade noch Dateinamen aus.

### Quarantäne-Capability

Der Operator provisioniert pro ScanRoot einen privaten Quarantänebereich.
FolioTone speichert und berichtet nur eine opaque `quarantine_capability_id`.
Absolute Pfade, Volume-Namen und Mountpunkte bleiben private Konfiguration.

Der Interim-Executor muss vor jedem Lauf beweisen:

- Source und Quarantäneziel liegen im selben Volume-/Filesystem-Kontext;
- Ziel liegt weder im ScanRoot noch ober- oder unterhalb davon;
- der opaque Zielpfad ist unmittelbar vor `os.rename` abwesend;
- kein Copy+Delete-, Shell-, generischer Callback- oder ToolProvider-Fallback
  existiert;
- nach dem Move können File-Identity, Byteanzahl und vollständiger SHA-256 am
  Ziel erneut bewiesen werden.

Diese Zielprüfung ist nicht atomar und schließt keine konkurrierende Race aus.
Der Vertrag verlangt kein bestimmtes Dateisystem. `FG-W10-MOVE-BACKEND` muss
für einen späteren Adapter beide Elternverzeichnisse no-follow und unverändert
beweisen, das Ziel exklusiv ohne Überschreiben erzeugen sowie einen atomaren
No-Replace-Move mit synthetischen Crash-, Collision- und Race-Tests
nachweisen. Cross-Volume-Moves und Backends ohne diesen späteren Nachweis
ergeben `TOOL_UNAVAILABLE`, nicht einen schwächeren Ersatzpfad.

### Fencing und Ablauf

Der Executor verwendet die bestehende Root-Lease mit einer neuen Owner-Klasse
`CONSOLIDATION_QUARANTINE_RUN`. Der Ablauf ist exakt:

1. zweite Bestätigung, Authorization, Plan und aktuelle Root-/Scan-/Review-
   Lineage read-only revalidieren und den Bestätigungs-Event persistieren;
2. Root-Lease erwerben und in einer kurzen Transaktion fencesicher einen
   `PREPARED`-Run mit deterministischem opaque Zielnamen persistieren;
3. Keeper und Candidate über private Runtimepfade erneut vollständig prüfen;
   no-follow Handles bleiben Teil von `FG-W10-MOVE-BACKEND`;
4. Same-Filesystem, Ziel-Abwesenheit und Source-Revalidierung des
   Interim-Executors beweisen; no-follow und unveränderte Eltern bleiben Teil
   von `FG-W10-MOVE-BACKEND`;
5. genau einen `os.rename`-Move ohne atomare No-Replace-Behauptung ausführen;
6. Source-Abwesenheit, Ziel-File-Identity, Größe und Full-SHA-256 beweisen;
7. Root-Lease erneut fencen und einen terminalen Run-Event anhängen;
8. append-only Verbrauchsevent persistieren und Lease freigeben.

Filesystem und SQLite bilden keine gemeinsame Transaktion. Deshalb wird
`PREPARED` vor der Mutation dauerhaft geschrieben. Nach Crash oder Timeout
entscheidet Recovery ausschließlich anhand desselben gebundenen Source- und
Ziel-Entries:

- Source vorhanden, Ziel abwesend: noch nicht bewegt, erneute Preconditions;
- Source abwesend, Ziel exakt gebunden: Move erfolgt, Verifikation fortsetzen;
- beide vorhanden, beide abwesend oder fremdes Zielmaterial: `MANUAL_REVIEW`,
  keine weitere Mutation.

Stale Lease, Fencingverlust, Cleanupfehler oder unklare File-Identity darf nie
als Erfolg gelten. Ein bereits verifizierter Zielbestand wird bei einem
späteren DB-Fehler nicht automatisch zurückbewegt; Recovery bleibt
deterministisch und no-overwrite.

### Persistenz und Status

Das Folgepaket `S-W10-02` erhält eine additive Migration `0022` nach der
inzwischen vorhandenen Revision `0021` mit
separaten immutable Tabellen für Authorization und Execution-Run sowie einer
append-only, lückenlos sequenzierten Eventtabelle. `PREPARED`, Move-/
Verifikationsfortschritt, Verbrauch, Stale- und Terminalzustände werden nur
durch neue Events dargestellt; Authorization oder Run werden nie in-place
umgeschrieben. Pfade, Dateinamen, Bestätigungseingabe, Dateiinhalte und private
Volume-Locators sind verboten. Materielle Hashes sind ausschließlich intern
und fehlen im öffentlichen Report.

Feste Runstatus:

```text
PREPARED
MOVED
VERIFIED
COMPLETED
STALE
TOOL_UNAVAILABLE
VALIDATION_FAILED
FENCED_OUT
MANUAL_REVIEW
CANCELLED
```

`CANCELLED` ist nur vor dem Move zulässig. Nach beobachteter Mutation wird
immer Recovery bis zu einem belegten terminalen Zustand versucht. Der
read-only Reporter zeigt ausschließlich Run-ID, Plan-ID, Status,
Authorization-Status, opaque Keeper-/Candidate-IDs, Zeitpunkte und feste
Finding-Literale.

### Rollback, Purge und Rescan

Nach `COMPLETED` bleibt die Datei in Quarantäne. Der Executor löscht nichts und
ändert FileRecord-/ScanRun-Evidence nicht nachträglich. Ein neuer normaler Scan
beobachtet die Source-Abwesenheit. Der Quarantäne-Run bleibt die unabhängige
Rekonstruktionsprovenienz.

Rollback benötigt eine eigene Authorization und einen späteren Vertrag. Es
darf nur no-replace zum ursprünglichen, weiterhin freien und erneut
revalidierten Ort erfolgen. Purge, Retention, Empty-Directory-Cleanup,
Metadatenwrite, eingebettete Identifier, Sidecarwrite und Calibrewrite sind
nicht Teil von ADR-0056.

### Bedien- und Recoverykette (W10-005)

S-W10-01 bis S-W10-04 stellen Vertrag, Persistenz, Interim-Executor und
read-only Status bereit. Sie stellen noch keine vollständige
Operator-Bedienkette bereit. `W10-005` darf diese Lücke schließen, ohne den
erlaubten Mutationstyp zu erweitern.

Ein `QuarantineCapabilityResolver` lädt eine geschützte lokale
Runtimekonfiguration außerhalb von Git und SQLite. Der CLI-Prozess erhält den
Konfigurationsdateipfad ausschließlich über
`FOLIOTONE_QUARANTINE_CAPABILITIES_FILE`; argv und öffentliche Reports
enthalten keinen Pfad. Die bounded JSON-Datei ordnet eine opaque
`quarantine_capability_id` genau einem `scan_root_id`, einem privaten
ScanRoot-Verzeichnis und einem privaten Quarantäneverzeichnis zu. Unbekannte
Felder, doppelte IDs, relative Pfade, überlappende Roots, Symlink-/Reparse-
Komponenten, nicht reguläre Verzeichnisse oder nicht nachweisbar geschützte
Dateiberechtigungen ergeben `TOOL_UNAVAILABLE`. Konfigurationswerte werden
nicht persistiert oder ausgegeben.

Die Bedienkette besteht aus vier festen Kommandos:

1. `quarantine-authorize` akzeptiert opaque Plan-ID, vollständigen
   Plan-Content-Hash und Capability-ID. Es lädt Plan, aktuelle Evidence,
   Reviews und Dependencies, baut `quarantine-authorization/v1` und
   persistiert ausschließlich einen erfolgreichen Snapshot.
2. `quarantine-execute` liest Authorization-ID und Plan-ID ein zweites Mal
   über nicht geloggtes `stdin`, revalidiert Ablauf, Verbrauch, Plan,
   Evidence, Reviews, Capability und Root-Lineage, erwirbt danach die
   `CONSOLIDATION_QUARANTINE_RUN`-Lease und ruft den engen Interim-Executor.
3. `quarantine-recover` akzeptiert nur eine opaque Run-ID. Es erwirbt dieselbe
   Root-Lease und klassifiziert Source/Ziel ausschließlich nach der in diesem
   ADR festgelegten Recovery-Matrix. Ein unklarer Zustand endet ohne weitere
   Mutation als `MANUAL_REVIEW`.
4. `quarantine-status` bleibt die einzige maschinenlesbare öffentliche
   Statusprojektion.

Kein Kommando akzeptiert freie Source-/Zielpfade, Command-Fragmente,
Callbacks, Batchlisten oder ToolProvider-Argumente. CLI-Fehler bleiben
pfadfrei. Eine Capability-Konfiguration, Authorization oder erfolgreiche
Recovery autorisiert weder Rollback noch Purge.

## Arbeitspakete

1. `S-W10-01`: reine DTOs, kanonische Hashes, Authorization-/Statusreducer und
   Preconditions; kein I/O.
2. `S-W10-02`: additive immutable Parent-/append-only Eventpersistenz,
   Root-Lease-Owner, bounded Store und Recovery-State; keine Source-Mutation.
3. `S-W10-03`: Interim-Executor mit `os.rename`, Same-Filesystem-Prüfung,
   Ziel-Abwesenheitsprüfung und Revalidierung; keine atomare No-Replace-
   Behauptung.
4. `FG-W10-MOVE-BACKEND`: spätere Frontier-Härtung für atomaren No-Replace-
   Move, no-follow Elternverzeichnisse und Crash-/Race-/Cross-Device-Nachweis.
5. `S-W10-04`: read-only Status/Report und fokussierter End-to-End-Abschluss.
6. `W10-005`: Capability Resolver, feste Authorize-/Execute-/Recovery-CLI und
   synthetische Crash-/Recovery-Abnahme; keine neuen Mutationstypen.

Jedes Paket erhält einen eigenen kleinen PR. Vollständige Tests laufen einmal
im PR-Gate; lokal werden nur betroffene Unit-, Schema- und Integrationsknoten
ausgeführt.

## Nicht autorisiert

Außer der im Interim amendment beschriebenen Ein-Datei-Quarantäne bleiben
insbesondere verboten:

- Copy+Delete, Überschreiben, Cross-Volume-Fallback und generische Pfad- oder
  Command-APIs;
- Delete, Purge, automatische Retention und leere-Verzeichnis-Bereinigung;
- Metadaten-, Sidecar-, Archive-, Calibre- oder externe Toolwrites;
- Quarantäne von Dependencies, mehreren Dateien oder nicht regulären Files;
- Umgehung der zweiten interaktiven Bestätigung oder Wiederverwendung einer
  verbrauchten Authorization;
- Ausgabe privater Pfade, Dateinamen, Bestätigungseingaben oder Materialhashes.

## Folgen

W10-001 wechselt von `BLOCKED` zu `DECISION`; W10-002 und der eng begrenzte
S-W10-03-Executor dürfen die dokumentierte Interim-Quarantäne ausführen.
`FG-W10-MOVE-BACKEND`, W10-004 und alle Metadatenwrites bleiben getrennte
Arbeit. Die bestehende W9-Non-Execution-Grenze wird nicht gelockert;
ausschließlich die neuen W10-Profile dürfen eine ausdrücklich autorisierte
Quarantäne ausführen.
