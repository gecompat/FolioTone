# W3-017 E-Book-Schiene: Runtime-Cutover und langfristige Roadmap

## Status und Geltungsbereich

**Status:** In Bearbeitung (W3-017, E4 und E5 abgeschlossen; E6-E8 teilweise integriert; E9-E12 offen)

**Stand:** 2026-08-17

**Scope:** E-Book-Schiene von W3-017 bis zur nicht ausführbaren
Konsolidierungsplanung W9

Die anschließende archive-aware Analyse- und vollständige
Deduplizierungsstrecke ist separat in
[`EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md`](EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md)
geplant. Sie ändert die W10-Sperre dieses Dokuments nicht.

Der
[`E-Book-Endgame-Ausführungsplan`](EBOOK_ENDGAME_IMPLEMENTATION_PLAN.md)
verfeinert diese E-Wellen zu umsetzbaren EB-Lieferpaketen. Die EB-Bezeichnungen
ersetzen weder die E1- bis E12-Semantik dieses Dokuments noch kanonische
Backlog-IDs.

Dieser Plan trennt Entwicklung, synthetische Verifikation und den privaten
Hintergrundbetrieb. Er plant keine Music-Implementierung. W4 bleibt außerhalb
dieses Dokuments zurückgestellt. W10 bleibt gesperrt und wird durch diesen Plan
weder vorbereitet noch autorisiert.

## Planungsentscheidung

Für die Entwicklung muss nicht die gesamte private Sammlung verarbeitet
werden. Der vollständige private Lauf ist ein betrieblicher Langzeittest und
liefert reale Größen-, I/O- und Tool-Evidence. Funktionskorrektheit,
Restart-Verhalten, Konkurrenzschutz, Query-Pläne und Performance-Regressionen
werden dagegen mit kleinen synthetischen Fixtures und begrenzten synthetischen
Skalierungsdatenbanken geprüft.

Ein laufender privater Vollhash darf kontrolliert beendet und mit der bereits
gemergten, fortsetzbaren Implementierung neu gestartet werden, wenn die
Cutover-Voraussetzungen dieses Plans erfüllt sind. Bereits persistierte
`FILE_SHA256`-Evidence wird beim neuen Aufruf wiederverwendet. Verloren gehen
kann höchstens ein noch nicht atomar persistierter Batch. Mehrere zu einem
Prozessbaum gehörende PIDs sind dabei kein Beleg für mehrere konkurrierende
Hash-Invocations; vor einem Cutover muss der Prozessbaum eindeutig zugeordnet
werden.

## Verbindliche Grenzen

- Source Media bleibt durchgängig read-only.
- Runtime-Datenbank, Backups, Logs, Reports, Benchmarks mit privaten Daten und
  Prozessinformationen bleiben unter `C:\rep\artifacts\FolioTone`,
  `C:\rep\cache\FolioTone` oder `C:\rep\tmp\FolioTone` und außerhalb von Git.
- Private Pfade, reale Sammlungswerte, Hashwerte, Dateinamen und Runtime-Zähler
  werden nicht in Repository-Dokumentation, Commits, Pull Requests oder CI
  übernommen.
- Ein Cutover beendet nur den zuvor eindeutig verifizierten alten
  Kandidaten-Hash-Prozessbaum und dessen obsolete Supervisoren. Codex,
  fremde Prozesse, andere Projekte und Source-Media-Prozesse bleiben
  unangetastet.
- Schemaänderungen werden nie parallel zu einem aktiven Writer ausgeführt.
- Jede Entwicklungswelle verwendet gezielte lokale Tests und genau einen
  vollständigen Pull-Request-CI-Gate. Der kurze Post-Merge-Vertrag bleibt
  davon getrennt.
- Der private Gesamtlauf ist keine CI-Abhängigkeit und blockiert unabhängige
  E-Book-Entwicklung nicht.

## Test- und Betriebsmodell

| Ebene | Zweck | Datenumfang | Gate |
|---|---|---:|---|
| Unit-Tests | Zustände, Zähler, Payloads, Fehlerabbildung | einzelne Objekte | bei jeder betroffenen Änderung |
| Integrationstests | Migration, SQLite-Transaktionen, Resume, Fencing, CLI | kleine synthetische Datenbanken | gezielt pro Welle |
| Synthetischer Skalierungstest | Query-Plan, Materialisierung, Bounded Memory | viele künstliche historische Evidence-Zeilen, wenige aktuelle Kandidaten | gezielt bei Query-/Indexänderung |
| Format-Smoke-Test | EPUB/MOBI/AZW/AZW3/PDF-Orchestrierung | höchstens wenige synthetische Dateien je Format | vor Merge einer Tool-/Workflow-Welle |
| Vollständiger PR-Gate | Install, Ruff, Mypy, Pytest, Docker und Migration | ausschließlich Repository-Fixtures | genau einmal pro Pull Request |
| Privater Hintergrundlauf | reale I/O-, Tool- und Betriebsvalidierung | gesamte private Sammlung | kein Entwicklungs- oder CI-Gate |

Zeitbasierte Performance-Grenzen werden nur mit großzügiger
Regressionstoleranz verwendet. Stabilere Verträge haben Vorrang: genau eine
schwere Kandidatenmaterialisierung, indexgestützte Lookups, begrenzte Batches,
keine erneute Verarbeitung vorhandener Vollhash-Evidence und keine
collection-weite Python-Liste.

## Roadmap der E-Book-Schiene

Die Bezeichnungen `E1` bis `E12` sind lokale Planungswellen. Sie ersetzen
keine bestehenden Backlog-IDs und führen keine Architekturentscheidung
stillschweigend ein.

### E1 — Runtime-Beobachtbarkeit und Abbruchtests abschließen

**Ziel:** Der Cutover ist vor einer Prozessbeendigung maschinenlesbar,
read-only und deterministisch prüfbar.

Umfang:

1. `ebook-hash-status` erhält eine echte SQLite-Read-only-Verbindung mit
   `mode=ro`, ohne Verzeichniserzeugung, Migration oder schreibende PRAGMAs.
2. Der Befehl erhält einen stabilen, pfadfreien JSON-Vertrag mit Run-ID,
   Source-Scan-ID, Phase, Status, Heartbeat, Lease-Zustand und Zählern.
3. Deterministische Tests decken einen Keeper-Fehler während eines langen
   Hashes, Lease-Erneuerung während einer blockierten Einzeldatei,
   `KeyboardInterrupt` und einen harten Child-Prozessabbruch ab.
4. Ein read-only Abschlussprüfer validiert Schema, Source-Scan-Lineage,
   Kandidaten-Hash-Run, Inventarartefakte und die begrenzte Formatabdeckung der
   Collection-Analyse, ohne die Source zu öffnen.
5. JSON- und Textausgaben enthalten weder Datenbank-/Source-/Reportpfade noch
   Dateinamen, Hashwerte, Lease-Token oder rohe Exceptions.

Abnahme:

- alle direkt betroffenen Tests, Ruff und Mypy sind grün;
- Read-only-Tests bestätigen bytegleiche Datenbank und unverändertes
  Artefaktverzeichnis;
- genau ein vollständiger PR-Gate ist grün und der exakte Head wird nach
  `main` gemergt;
- der kurze Post-Merge-Vertrag ist grün.

### E2 — Kontrollierter Cutover auf den optimierten Kandidaten-Hasher

**Ziel:** Der alte Lauf wird bewusst beendet und die bereits persistierte
Arbeit mit der gemergten optimierten und gefenceten Variante fortgesetzt.

Voraussetzungen:

- E1 ist gemergt oder die äquivalenten read-only Status- und Abbruchtests sind
  nachweislich auf `main` vorhanden;
- `origin/main` enthält die current-scan-first
  Kandidatenmaterialisierung, den Lookup-Index, persistente
  `EbookCandidateHashRun`-Leases und atomare gefencete Batch-Writes;
- der vorgesehene Runtime-Worktree ist clean und auf einen verifizierten
  `origin/main`-Commit fixiert;
- neuester `ScanRun` ist `COMPLETED`;
- Prozessbaum, Datenbank und Supervisorzustand sind eindeutig zugeordnet;
- es läuft kein Scan- oder zweiter Kandidaten-Hash-Writer für denselben
  `ScanRoot`.

Cutover-Ablauf:

1. Status, Prozessbaum, Schema-Revision und pfadfreie Baseline-Zähler werden
   read-only in einem privaten Runtime-Bericht festgehalten.
2. Der exakt zugeordnete alte Kandidaten-Hash-Prozessbaum wird kontrolliert
   beendet. Anschließend wird verifiziert, dass kein zugehöriger Writer mehr
   lebt. Der erwartete `BLOCKED`-Zustand alter Supervisoren ist kein
   Datenbankfehler.
3. Erst nach Writer-Stillstand wird über die SQLite-Backup-API ein konsistentes
   privates Datenbank-Backup erstellt. `PRAGMA integrity_check`, Dateigröße und
   Backup-Digest werden privat geprüft.
4. Die gemergte CLI migriert auf den paketierten Alembic-Head. Revision,
   kritische Tabellen und Indizes werden read-only verifiziert.
5. Ein begrenzter Canary verarbeitet höchstens 100 noch offene Kandidaten mit
   konservativ zwei Workern und einem kleinen atomaren Batch. Der konkrete
   Batchwert wird nach dem synthetischen Test festgelegt und im privaten
   Runner dokumentiert.
6. Der Canary muss Heartbeats, steigende Fortschrittszähler, keine
   Doppelverarbeitung vorhandener Vollhash-Evidence, null Lease-Konflikte und
   ausschließlich isolierte per-File-Fehler zeigen.
7. Danach setzt ein neuer identischer Aufruf ohne `--max-items` die offenen
   Kandidaten im Hintergrund fort. Bereits vollständige Kandidaten erscheinen
   als `already_hashed` und werden nicht erneut geöffnet.
8. Ein einziger privater Supervisor steuert den weiteren Ablauf. Alte
   Supervisoren und Watcher werden nach bestätigtem Übergang nicht
   wiederverwendet, weil ihr Erfolgsvertrag vom sauberen Ende des alten Laufs
   abhängt.

Beobachtung:

- Heartbeat und Fortschritt werden höchstens alle fünf Minuten gelesen.
- Gemeldet werden nur Phasenwechsel, belastbarer Zählerfortschritt,
  Failure-Anstieg, Lease-Verlust, Prozessende oder ein blockierter Zustand.
- Die kumulative Prozess-CPU wird nicht als momentane CPU-Auslastung
  interpretiert. Für eine Auslastungsprobe wird die CPU-Zeit über ein kurzes
  Intervall differenziert.

Rollback:

- Vor Migration oder Canary wird bei einer nicht eindeutigen Prozesszuordnung
  abgebrochen.
- Ein fehlgeschlagener Canary wird nicht durch Datenbanküberschreiben
  kaschiert. Der persistierte Run bleibt auditierbar und wird nach
  Ursachenbehebung fortgesetzt oder stale übernommen.
- Das Backup wird nur nach separater Integritäts- und Lineage-Prüfung zur
  Wiederherstellung verwendet. Eine automatische Rückkopie ist nicht Teil des
  Cutovers.
- Source Media wird in keinem Rollbackpfad geschrieben.

### E3 — W3-017 betrieblich abschließen

**Stand (abgeschlossen):** Die E3-Betriebssequenz wurde mit einem privaten
real-world read-only Durchlauf abgeschlossen; die verknüpfte Scan-, Hash-,
Inventar- und Collection-Pipeline ist für die dokumentierten Grenzen
(`RUNNING`-Recovery, Quick-Duplikat-Hashing, Determinismus und Read-Only-Verify)
in Welle 1 abgeschlossen.

**Ziel:** Der private Hintergrundlauf liefert die vorgesehenen
Bestands-, Hash- und formatabdeckenden Ergebnisse, ohne die Entwicklung zu
blockieren.

Reihenfolge:

1. Kandidaten-Hashing erreicht `COMPLETED` mit null offenen Kandidaten und
   null nicht erklärten Failures.
2. Der scanweite private Inventarbericht wird mit festen Limits erzeugt und
   byte-/checksumgenau verifiziert. Offene Quick-Kandidaten ohne Vollhash
   müssen null sein.
3. Die Collection-Analyse plant für jedes im Inventar vorhandene unterstützte
   Format exakt `min(N, format_count)` Items. Der erste Betriebswert bleibt
   `N = 5`, solange kein dokumentierter Grund für eine Änderung besteht.
4. Der begrenzte Lauf wird bis zu einem terminalen Zustand fortgesetzt. Bereits
   terminale Items werden beim Resume nicht wiederholt.
5. Der private Collection-Bericht wird erzeugt und sein
   inhaltsadressiertes Artefakt verifiziert.
6. Der Abschlussprüfer bestätigt Migration, Source-Scan, Kandidaten-Hash,
   Inventarbericht und Collection-Analyse mit identischer Lineage.

W3-017 ist erst abgeschlossen, wenn Code, Dokumentation, private
Betriebsverifikation und bekannte Fehlergrenzen konsistent dokumentiert sind.
Private Kennzahlen werden nur abstrakt als bestanden, degradiert oder offen
beschrieben.

### E4 — Gemeinsame `ScanRoot`-Write-Lease und vollständiges Scan-Fencing

**Stand (abgeschlossen):** ADR-0027 und Alembic `0012` führen einen
dauerhaften Root-Lease-Slot mit monotoner Fence-Epoch ein. Scan,
Kandidaten-Hashing, Collection-Analyse und einzelne E-Book-Analyse sind für
denselben Root gegenseitig ausgeschlossen; ihre Datenbankwrites werden in der
jeweiligen Fachtransaktion gefencet. Scanner und Collection-Analyse erneuern
Root- und Run-Lease während langer Arbeit über getrennte Keeper.

**Ziel:** Scan und Kandidaten-Hashing desselben `ScanRoot` können nicht mehr
gleichzeitig schreiben.

Diese Welle wird nicht mit E2 vermischt. Sie benötigt eine eigene ADR und eine
additive Migration. Das kleinste korrekte Design umfasst eine gemeinsame
`scan_root_write_leases`-Mutex-Tabelle, eine partielle Active-Run-
Eindeutigkeit für `scan_runs`, atomare Acquisition/Recovery und Fencing jeder
rootbezogenen Scan-Schreibtransaktion.

Zu fencen sind mindestens:

- Scan-Batches mit `FileRecord`, `FileObservation` und Events;
- Fingerprint-Batches;
- Missing-/Deleted-Übergänge;
- Relocation-Kandidaten;
- Heartbeat, Finish und Interrupt;
- Kandidaten-Hash-Batches zusätzlich zur bestehenden Run-Lease.

Der Scanner erhält einen separaten Lease-Keeper für lange Einzelhashes. Tests
verwenden Threads, Barriers und Events statt Timing-Sleeps und beweisen, dass
ein stale Besitzer nach Übernahme weder Batch, Fingerprint, Missing,
Relocation noch Finish committen kann.

### E5 — Dauerhafter synthetischer Performance- und Restart-Vertrag

**Ziel:** Zukünftige Query- oder Persistenzänderungen können den behobenen
Engpass nicht unbemerkt wieder einführen.

Umfang:

- wiederverwendbarer synthetischer Benchmark-Builder unter Test-/Tooling-Code;
- historische Scan-Generationen mit vielen Quick-Fingerprints und wenigen
  aktuellen Kandidaten;
- SQL-Event-Vertrag für genau eine schwere Materialisierung pro Invocation;
- `EXPLAIN QUERY PLAN`-Prüfung der profilierten Indizes;
- deterministische Restart-Fälle für `--max-items`, per-File-Fehler,
  `KeyboardInterrupt`, Keeper-Fehler und harten Prozessabbruch;
- getrennte Messung von Auswahlzeit, Hash-I/O und Commitzeit;
- kein privater Pfad, Hashwert oder Sammlungssnapshot als Fixture.

E5 ist ein Entwicklungsvertrag und wartet nicht auf E3. Die Welle darf in
einem isolierten Worktree parallel zum privaten Hintergrundlauf entstehen,
solange sie dessen Datenbank und Prozesse nicht verändert.

**Stand (abgeschlossen):** `PR #37` integriert die synthetischen Skalierungs-,
Index-, Phasenmessungs- und deterministischen `max-items`-Restart-Verträge.

### E6 — E-Book-Authority und lokale Entity Resolution (W5A, book-only)

**Ziel:** Provider-neutrale lokale Kandidaten für `Agent`, `Work`, `Edition`
und `Series` werden erklärbar aufgelöst, ohne Source-Beobachtungen zu
überschreiben.

Reihenfolge:

1. versionierte Unicode-, Namens- und Identifier-Normalisierung;
2. Alias-, Pseudonym-, Sortiername- und `credited_as`-Kandidaten;
3. Homonym-Schutz: gleiche normalisierte Namen erzeugen keinen Auto-Merge;
4. `Work`-/`Edition`-/`Series`-Kandidaten aus lokalen Metadaten- und
   Inhalts-Evidence;
5. persistierte bestätigte und abgelehnte lokale Zuordnungen getrennt von
   beobachteten Werten;
6. synthetische False-Positive-, Übersetzungs-, Editions- und
   Serienfixtures.

Abnahme erfordert nachvollziehbare Rule-/Resolver-Versionen, Confidence und
Evidence-Links. Es entsteht noch kein Duplicate-Matching.

**Stand (Teilabschluss):** `PR #36` integriert versionierte lokale Namens- und
Identifier-Normalisierung, Agent-/Buchkandidaten und einen konservativen
Homonym-Guard. Persistierte bestätigte/abgelehnte Zuordnungen und der breitere
synthetische False-Positive-Korpus bleiben offen.

### E7 — Strukturierte E-Book-Knowledge-Provider (W5B, book-only)

**Ziel:** Mindestens ein strukturierter Buch-/Authority-Provider ergänzt
lokale Kandidaten privacy-minimiert und offline-fähig.

**Stand (Vertragsgrundlage integriert):** `w5b: add synthetic structured book knowledge provider` wurde in
`PR #38` (Merge-Commit `08371f2b3cbd8d49c6b8fbe1308577520cee5be4`) erfolgreich
integriert. Die neuen privacy-minimierten Provider-Verträge und Offline-Synthese-Fixtures
sind in `src/foliotone/enrichment/contracts.py`, `src/foliotone/enrichment/providers.py`
und `tests/unit/test_enrichment.py` verifiziert.
Persistenter Cache, aktuelle reale Provider-Auswahl und der erste reale Adapter
bleiben offen.

Vor der Implementierung werden aktuelle offizielle Zugangs-, Lizenz-,
Attributions-, Rate-Limit-, Cache- und Bulk-Daten-Regeln erneut geprüft. Die
Auswahl wird nicht aus diesem zeitlich statischen Plan abgeleitet.

Umfang:

- Provider-Interface und explizite Betriebsmodi;
- persistenter versionierter Cache außerhalb von Git;
- DTOs ohne absolute Pfade oder collection-weite Inventare;
- mindestens ein book-spezifischer Adapter nach aktueller Bewertung;
- Offline-, Cache-Hit-, Refresh-, Rate-Limit- und Provider-Ausfalltests;
- externe Ergebnisse bleiben `EXTERNAL` Evidence und werden nicht
  automatisch kanonisch.

### E8 — Mehrdimensionale E-Book-Klassifikation (W5C, book-only)

**Ziel:** Domain, Genre, Subgenre, Topic, Audience, Language und Form werden
als getrennte, Provenance-behaftete Assertions modelliert.

**Stand (abgeschlossen):** `w5c: add multidimensional book classification contracts` wurde in
`PR #39` (Merge-Commit `6023fbebe514526fa7a0612e6ca5bc7f28c53a96`) erfolgreich
integriert. Die neuen Assertions-DTOs und Verifikationstests liegen in
`src/foliotone/classification/contracts.py` und `tests/unit/test_classification.py`.

Konflikte zwischen lokaler Ableitung, ToolProvider und Knowledge Provider
bleiben erhalten. Klassifikation ist keine Identitätsevidence und darf weder
`Work`-/`Edition`-Merges noch Duplicate-Beziehungen allein bestätigen.

### E9 — Erklärbares E-Book-Matching (W6, book-only)

**Ziel:** Aus begrenzten Kandidatenblöcken entstehen versionierte,
erklärbare Relation-Vorschläge auf der richtigen Identitätsebene.

Blocking verwendet vollständige Dateihashes, normalisierte Textfingerprints,
Identifier, aufgelöste lokale Entitäten und geeignete strukturierte Evidence.
Es gibt kein globales All-vs-All. Die Kalibrierung priorisiert
False-Positive-Schutz und trennt mindestens:

- exakte Dateikopie;
- gleiche `Edition` mit unterschiedlicher Repräsentation;
- gleiches `Work` mit unterschiedlicher `Edition` oder Übersetzung;
- technische/qualitative Variante ohne belegte bibliografische Identität.

Tool- oder Provider-Übereinstimmung darf widersprüchliche Inhalts- oder
Edition-Evidence nicht verdecken.

### E10 — Persistierte E-Book-Review-Workflows (W7, book-only)

**Ziel:** Unsichere Authority-, Classification- und Matching-Kandidaten werden
akzeptiert, abgelehnt oder zurückgestellt, ohne bei unveränderter Evidence
unnötig erneut vorgelegt zu werden.

Entscheidungen behalten Historie, Evidence-, Tool-, Provider-, Resolver- und
Matcher-Versionen. Bestätigte lokale Authority-Kenntnis wird wiederverwendet,
ändert aber keine Source-Beobachtung rückwirkend.

### E11 — Read-only Calibre-Library-Reconciliation (W8)

**Ziel:** Eine konfigurierte Calibre Library wird als zusätzliche Evidence-
Quelle mit dem FolioTone-Index abgeglichen.

Nur dokumentierte read-oriented `calibredb`-Befehle erhalten eine enge
Allowlist. Mutierende Befehle sind nicht erreichbar. Der Adapter erkennt
Dateien ohne Calibre-Record, Records ohne Datei, Duplicate-Hinweise,
Metadatenkonflikte und Authority-Konflikte. Calibre wird weder Pflichtsystem
noch kanonische Datenbank.

### E12 — Nicht ausführbare E-Book-Konsolidierungsplanung (W9)

**Ziel:** Bestätigte Relations und getrennte Quality-Evidence können
`ConsolidationPlan`-Kandidaten mit Preconditions erzeugen.

Die Pläne sind technisch nicht ausführbar. Identität und Keep-Präferenz
bleiben getrennt. Jede mögliche spätere Operation enthält eine
changed-since-analysis-Precondition. W10 bleibt blockiert, bis eine neue
ausdrücklich akzeptierte ADR Sicherheits-, Audit-, Recovery- und
Benutzerbestätigungsregeln festlegt.

## Parallelisierung

Sicher parallelisierbar sind:

- E3 als privater Hintergrundbetrieb;
- E5 als rein synthetischer Entwicklungsvertrag;
- Dokumentations- und Fixture-Arbeit für E6 in isolierten Worktrees.

Nicht parallel auf derselben Runtime-Datenbank laufen dürfen:

- Migration und aktiver Writer;
- zwei Kandidaten-Hash-Invocations desselben `ScanRoot`;
- Scan und Kandidaten-Hashing desselben `ScanRoot`; seit E4 weist die
  gemeinsame Root-Lease den zweiten Writer automatisch ab;
- Inventar-/Abschlussverifikation während einer Schemaänderung.

Code-Wellen werden in getrennten Worktrees entwickelt. Laufzeitcode wird erst
nach Merge, grünem PR-Gate und Clean-Commit-Verifikation auf den privaten
Bestand angewendet.

## Entscheidungs- und Stop-Gates

Eine Welle stoppt ohne riskante Annahme, wenn:

- Prozess-, Root-, Datenbank- oder Run-Lineage nicht eindeutig ist;
- ein Writer während einer geplanten Migration lebt;
- ein Read-only-Befehl Speicher anlegt oder verändert;
- Lease/Fencing nicht atomar mit dem Nutzdatenwrite geprüft wird;
- ein Artefaktpfad aus seinem privaten Root entkommt oder Symlinks enthält;
- Providerregeln, Lizenz oder notwendige Credentials nicht geklärt sind;
- ein Schritt Source-Media-Schreibrechte erfordern würde;
- W9 in ausführbare Operationen übergehen würde.

Ein privater Langläufer ohne neuen Fortschritt ist nicht automatisch ein
Entwicklungsblocker. Er wird anhand Heartbeat, CPU-Differenz, Lease,
Prozesszustand und atomaren Fortschrittszählern bewertet.

## Definition des Abschlusses der E-Book-Schiene

Die E-Book-Schiene dieses Plans ist abgeschlossen, wenn:

1. W3-017 betrieblich und dokumentarisch abgeschlossen ist;
2. Scan- und Kandidaten-Hash-Schreibkonkurrenz gefencet ist;
3. synthetische Performance-/Restart-Verträge dauerhaft bestehen;
4. lokale und mindestens eine strukturierte Authority-/Enrichment-Schicht
   provider-neutral und privacy-bounded funktioniert;
5. E-Book-Klassifikation, Matching und Review mit synthetischer Ground Truth
   und False-Positive-Schutz verfügbar sind;
6. Calibre Library read-only als zusätzliche Evidence-Quelle abgeglichen
   werden kann;
7. W9 ausschließlich nicht ausführbare, revalidierbare Plan-Kandidaten
   erzeugt;
8. W10 weiterhin technisch und dokumentarisch gesperrt ist.
