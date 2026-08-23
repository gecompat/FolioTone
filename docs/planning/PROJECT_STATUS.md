# Projektstatus

Stand: 2026-08-23

## Aktuelle Welle

**FG-W10-RENAME entschieden — ADR-0066 begrenzt den ersten Rename-Writer**

ADR-0066 akzeptiert ausschließlich einen byte-identischen `FILE_RENAME` auf
einen historisch unbenutzten Basename im selben vorhandenen Parent und
`ScanRoot`. `FILE_REORGANIZE` bleibt wegen zweier Parentverzeichnisse,
getrennter Haltbarkeit und möglicher Verzeichniserzeugung hinter dem neuen
`FG-W10-REORGANIZE`. Das docs-only Gate öffnet selbst keine Mutation.

Der Vertrag bindet eine private einzelne Rename-Capability, aktuelle Plan-/
Review-/Dependency-Scope- und Scan-Lineage, bereits NFC-kanonische relative
Locator, reguläre Dateien mit Linkanzahl eins und ein festes Linux-x86_64-
glibc-Backend. `KNOWN_PRESENT`, `UNKNOWN` und bloß fehlende Dependency-Zeilen
blockieren; `NOT_APPLICABLE` benötigt einen expliziten aktuellen owner-only
Scope. Der einzige Mutationsaufruf ist später
`renameat2(RENAME_NOREPLACE)` relativ zu einem mit `openat2` no-follow und
beneath geöffneten Same-Parent-FD. Ungeeignete oder remote Filesysteme,
Target-Collision, Cross-Device, Copy+Delete, Overwrite, `os.rename`, Shell und
ToolProvider besitzen keinen Fallback.

Preparation, höchstens 15 Minuten gültige One-use-Authorization, zweite
Bestätigung, rootweites Fencing, gapless Journal, unmittelbare Inode-/Byte-/
Attributverifikation, Parent-`fsync` und eine feste Exact-State-Recovery-
Matrix sind entschieden. Nach Erfolg erzeugt ein neuer Scan getrennt den
alten `MISSING`-Source-`FileRecord` und einen neuen `NEW`-Target-`FileRecord`;
`EbookRenameReconciliationSnapshot` verbindet diese Historie, ohne
`FileRecord`-Identitäten zu vereinigen. Nach Reverse-Recovery bindet derselbe
Vertrag stattdessen die wieder aktuelle `PRESENT`-Source und die weiterhin
historische Target-Abwesenheit, bevor `RECOVERED` terminal wird. REST/UI und
andere Operationsarten bleiben geschlossen.

Die nächsten vier kleinen Waves sind `S-W10-RN01` bis `S-W10-RN04`. RN01
liefert zuerst die bislang fehlende nicht mutierende Proposal-/private-
Preview-/Review-/Plan-Oberfläche; danach folgen Authority/Persistenz,
Linux-Backend/Recovery und zuletzt die Bedien-/Scan-/Reconciliation-Kette.

Die 23 gezielt betroffenen Planungsfront-, Dokumentations- und W10-Safety-
Verträge bestanden auf dem finalen Stand in 0,11 Sekunden. Ruff war für die
einzige geänderte Python-Testdatei grün; `git diff --check` war sauber. Der
erste Pytest-Aufruf
sammelte wegen fehlendem lokalen `PYTHONPATH=src` keine Tests und wurde mit
dieser repositoryüblichen Importkonfiguration exakt im selben kleinen Scope
wiederholt. Reale E-Books, private Runtime-Daten, Source-Mutation, SQLite-
Runtime, Docker, externe Tools und die vollständige lokale Suite wurden nicht
verwendet. Der vollständige PR-CI-Gate bleibt dem exakten stabilen Head
vorbehalten.

**S-W9-007C implementiert — W9-007 besitzt eine echte read-only Oberfläche**

`ebook-operation-recipe-report` nimmt genau eine opaque Plan-ID sowie die
Darstellungswahl entgegen und öffnet eine bereits vorhandene SQLite-Datenbank
ausschließlich über `mode=ro` und `query_only=ON`. Der Reader migriert nicht,
rehydriert den Candidate-/Plan-Graph bounded über den insert-only Store und
öffnet weder Source Media noch Ziel-Slots oder Tools.

Text und JSON enthalten ausschließlich opaque Plan-/Candidate-IDs, Plan- und
Candidate-Profil, Operationstyp, Plan- und Execution-Status, feste Counts,
Reviewstatus und Blockerliterale. Private Locator, Source-/Target-/Evidence-
IDs, Format-/Processorwerte, Content-/Materialhashes, Zeitpunkte und
Datenbankpfade sind ausgeschlossen. Fehlender Plan, altes Schema,
Datenbankausfall und unerwartete interne Fehler ergeben ausschließlich feste,
detailfreie Fehlercodes. Es gibt keine `--private-details`-, Execute-, Apply-
oder Write-Fläche.

Zehn neue beziehungsweise direkt betroffene CLI-, JSON-/Text-Privacy-,
Read-only-, Older-Schema-, Fehler-, Bootstrap- und statische Safety-Fälle
bestanden in 14,38 Sekunden. Der zusätzliche akzeptierte Reviewpfad belegt in
7,85 Sekunden einen blockerfreien Report mit genau einem Review Item und
einer Decision. Ruff war für den geänderten Python-Scope grün; Mypy prüfte die
fünf betroffenen Source-/Testdateien ohne Befund. Reale E-Books, private
Runtime-Daten, Docker, externe Tools und die vollständige lokale Suite wurden
nicht verwendet. Zusätzlich bestanden die 22 gezielt gebündelten
Planungsfront-, Dokumentations-, Testeffizienz- und Report-Safety-Fälle in
1,17 Sekunden. Der stabile Remote-Head
`e0f9645fc2ce851282776820735a6f710c038528` bestand Quality-Run
`32617699743` und E-Book-Toolchain-Run `32617699707`. PR #244 wurde als
`0a249e7230680aa03ac868d02065dab9ddb1e07d` auf `main` integriert;
Post-Merge-Run `32617838103` war ebenfalls grün.

`W9-007` ist damit vollständig und weiterhin dauerhaft nicht ausführbar. Als
nächste book-only Wave folgte das docs-only Frontier-Gate
`FG-W10-RENAME`, das ADR-0066 inzwischen ausschließlich für Same-Parent-Rename
entschieden hat.

**S-W9-007B implementiert — Review und Recipe-Historie sind insert-only**

Der generische Review-Core besitzt jetzt die feste bidirektionale Paarung
`EBOOK_OPERATION_RECIPE` und `EBOOK_OPERATION_RECIPE_CANDIDATE`.
`SQLiteResolutionReviewStore` nimmt einen Recipe-Review nur für den
persistierten Candidate, dessen Primärdatei, Producer-/Compatibility-Vertrag
und exakte Evidence-/Content-Bindung an. Migration
`0030_ebook_operation_recipe_plans` rekonstruiert die SQLite-Review-
Constraints additiv und erhält bestehende Review Items, Decisions,
Consolidation- und Metadata-Correction-Planreviews einschließlich vorhandener
Trigger.

Zehn neue Tabellen persistieren Candidate, bis zu 32 Sources, fünf
Dependency-Achsen, Verification-Codes und Evidence sowie Plan, Review,
Preconditions und Blocker-Evidence. Alle Tabellen sind per Trigger
No-Update/No-Delete; Parent-Counts begrenzen jeden Child-Insert. Der
content-addressed Store revalidiert Komponenten-, Candidate- und Planhashes,
UUIDv5-Identitäten, den kanonischen Reducer, aktuelle Source-/Observation-/
Full-SHA-256-Lineage, lokale Evidence, bekannte Dependencies, verwaltete
Ziel-Scopes und die neueste kompatible Reviewentscheidung. Idempotente Retries
geben ausschließlich den bereits persistierten identischen Snapshot zurück.

Die Persistenz öffnet weder Source Media noch Ziel-Slots und startet keine
Tools. Private relative Locator liegen nur in SQLite und fehlen in `repr` und
Storefehlern; externe Endpoint-IDs bleiben opaque. In der finalen fokussierten
Ausführung bestanden sieben neue synthetische Upgrade-/Downgrade-, Multi-
Source-Roundtrip-, Review-/Plan-, Evidence-Lineage-, Privacy-,
Datenbankfehler-, Bounds-, Immutability- und Rollback-Fälle in 15,90 Sekunden.
58 unveränderte betroffene Regressionen waren grün, bevor
eine erwartungsgemäß veraltete Schema-Head-Assertion auffiel; nach ihrer
mechanischen Aktualisierung bestanden sechs unmittelbar betroffene
Migrations-, Review- und Fixture-Fälle in 17,40 Sekunden. Zusätzlich waren 19
statische Planungs-, Dokumentations- und Testeffizienzverträge auf dem finalen
Stand in 1,08 Sekunden sowie neun gezielt ausgewählte ältere Migrationspfade
in zwei begrenzten Läufen grün. Ruff war für den gesamten Source-Scope und alle
geänderten Tests erfolgreich; Mypy prüfte alle 243 Source-Dateien ohne
Befund. Reale E-Books, private Runtime-Daten, Docker, externe Tools und die
vollständige lokale Suite wurden nicht verwendet. Der stabile Remote-Head
`ab2318ab61a9bb7b79445faff8b874d1f1301038` bestand Quality-Run
`32616719567` und E-Book-Toolchain-Run `32616719527`. PR #243 wurde als
`0c3e60c2688a8d902d4646ac38c8660539a4ab1d` auf `main` integriert;
Post-Merge-Run `32616869792` war ebenfalls grün.

**S-W9-007A implementiert — operationstypisierte Rezepte bleiben nicht ausführbar**

ADR-0065 definiert die Candidate-Review-Plan-Trennung für genau sechs
E-Book-Operationsfamilien: `FILE_RENAME`, `FILE_REORGANIZE`, `FILE_IMPORT`,
`FILE_EXPORT`, `FORMAT_TRANSFORM` und `ARCHIVE_REWRITE`. Der neue reine
Package-Scope `foliotone.ebook_operation_recipes` enthält immutable und
bounded Source-, Target-, Output-, Processor-, Dependency-, Evidence-,
Review-, Precondition-, Blocker-, Candidate- und Plan-DTOs. Ein Candidate
bindet einen abgeschlossenen `ScanRun`, vollständige Source-/Output-SHA-256,
private relative Source-/Ziel-Locators und die operationstypisierte Collision-,
Workspace-, Recovery- und Verification-Matrix.

Die Builder berechnen alle materiellen Component-, Evidence-, Candidate- und
Plan-Fingerprints über Unicode-NFC-normalisiertes `canonical-json/v1`.
Candidate- und Plan-ID entstehen deterministisch per UUIDv5 aus dem jeweiligen
Content Hash; Auditzeitpunkte ändern die Identität nicht. Der Reducer bildet
fehlende oder stale Reviews, unbekannte Dependencies und unvollständige
Lineage-/Target-/Output-/Processor-/Precondition-/Recovery-/Verification-
Nachweise auf feste Blocker ab. Auch ein vollständig kompatibles `ACCEPT`
ergibt ausschließlich `APPROVED_NON_EXECUTABLE`; der einzige Execution-State
bleibt `NOT_EXECUTABLE`.

Byte-erhaltende Dateioperationen binden Format, Größe und Full-SHA-256 der
Primärquelle und verlangen einen nativen semantischen Processor. ToolProvider-
Anforderungen für Transformation oder Archive-Rewrite enthalten nur
Provider-, Tool-, Adapter- und Konfigurationsidentität, aber weder Command,
argv, Executable-Pfad noch Environment. Nur `ARCHIVE_REWRITE` darf bounded
Companion-Sources desselben `ScanRoot` und `ScanRun` binden. Absolute,
Drive-relative oder mehrdeutige Locator werden abgewiesen; private Locator
und Materialhashes fehlen in `repr` und im Planpayload.

Ein statischer Non-Execution-Gate verbietet dem gesamten Package CLI-,
Persistence-, Tooling-, Adapter-, Filesystem-, Prozess- und Tempimporte,
mutierende Calls, bekannte externe Write-Commands und öffentliche Apply-/
Delete-/Execute-/Move-/Purge-/Quarantine-/Rename-/Write-Flächen. Lokal
bestanden 48 fokussierte synthetische Contract-, Determinismus-, Privacy-,
Review-, Blocker- und Non-Execution-Tests in 0,21 Sekunden. Repository-Ruff
war grün; Mypy prüfte 240 Source-Dateien ohne Befund, `compileall` war
erfolgreich und `git diff --check` war sauber. Zusammen mit den betroffenen
Planungs-, Dokumentations- und W10-Safety-Verträgen bestanden 70 Fälle in
0,45 Sekunden. Reale E-Books, private Runtime-Daten, SQLite, Docker und externe
Tools wurden nicht verwendet. Der stabile Remote-Head
`6ac7e08a28a4325d0f8cfc994063e97164201f31` bestand Quality-Run
`32614478464` und E-Book-Toolchain-Run `32614478470`. PR #242 wurde als
`658563c1a1351a91546789e5e5c2b1160686ffb1` auf `main` integriert;
Post-Merge-Run `32614626362` war ebenfalls grün.

`S-W9-007C` ergänzt den echten SQLite-Read-only-Report und schließt `W9-007`
ab. Kein W9-007-Paket öffnet einen Writer; jedes spätere W10-Backend benötigt
weiterhin seine eigene technische ADR und Capability-/Authorize-/Execute-/
Recovery-Kette.

**S-W10-05D implementiert — Quarantäne-Recovery schließt W10-005**

`quarantine-recover` vervollständigt die durch ADR-0056 erlaubte
Interim-Ein-Datei-Quarantänekette. Das Kommando akzeptiert ausschließlich eine
opaque Run-ID und die Darstellungswahl. Plan-, Content-Hash-, Capability- und
Authorization-Binder, Datenbankpfad sowie freie Source-/Zielpfade sind keine
Argumente. Standardausgabe und Fehler bleiben auf Profil, feste Status-
beziehungsweise Fehlercodes und opaque IDs begrenzt.

Der Operator rehydriert Run, einmalig verbrauchte Authorization, exakten
Plan, bestätigtes `PREPARED`-Event und den historischen Observation-Locator.
Eine inzwischen abgelaufene Authorization und ein später geänderter aktueller
`FileRecord` verhindern die Beweissicherung nicht. Ein unbestätigter, direkt
über die niedrige Persistenzschicht erzeugter Run ist dagegen nicht
recoveryfähig. Unter einer frischen oder ausschließlich für denselben Run
übernommenen abgelaufenen `CONSOLIDATION_QUARANTINE_RUN`-Lease werden reguläre
Einzeldatei, Modified-Zeitpunkt, Größe und Full-SHA-256 erneut geprüft.

Recovery führt selbst kein `os.rename`, Copy, Delete, Overwrite oder externes
Tool aus. Bei `PREPARED` plus exakter Source und abwesendem Ziel prüft sie den
Zustand unmittelbar erneut und hängt `CANCELLED` an. Bei abwesender Source und
exaktem Ziel ergänzt sie nach erneuter Prüfung vor jedem Schritt nur die noch
fehlenden Ereignisse `MOVED`, `VERIFIED` und `COMPLETED`. Alle anderen
Verteilungen enden ohne Dateisystemmutation bei `MANUAL_REVIEW`.
`COMPLETED` und `CANCELLED` sind idempotent. Das Journal akzeptiert für Erfolg
nur noch `PREPARED -> MOVED -> VERIFIED -> COMPLETED`; ein lückenloser, aber
widersprüchlicher Verlauf blockiert Recovery vor einem weiteren Event.

Auf dem aktuellen Stand bestanden 14 synthetische Recovery-Matrix-
Integrationsfälle zusammen in 33,29 Sekunden sowie der zusätzliche
Capability-Ausfall in 8,98 Sekunden. Die insgesamt 15 Fälle decken den
unveränderten Abbruch, den
Abschluss ab `PREPARED`/`MOVED`/`VERIFIED`, vier uneindeutige physische
Verteilungen, aktiven Root-Writer, Capability-Ausfall mit erhaltener Run-ID,
historische Locator nach Ablauf und FileRecord-Drift, idempotenten Terminal-
Retry, unbestätigtes `PREPARED`, abgelaufene Same-Run-Lease-Übernahme und ein
widersprüchliches Journal ab.
Zusätzlich bestanden 45 fokussierte Recovery-/CLI-/Bootstrap-/Planungs- und
Dokumentationsverträge in 1,24 Sekunden. Die vollständige lokale Suite und
Docker wurden gemäß Test Policy nicht gestartet. Es wurden ausschließlich
kleine synthetische temporäre Dateien und SQLite-Datenbanken verwendet; reale
E-Books und private Runtime-Daten wurden nicht geöffnet. Der vollständige
PR-CI-Gate wurde anschließend ausschließlich für den exakten korrigierten
stabilen Head ausgeführt und ist unten dokumentiert.

Der erste PR-Gate auf Head `6567a7ed2d5dbefecebc311ececa4445276e2271`
erreichte nach grünen Install-, Ruff- und Mypy-Schritten die Test-Collection
und stoppte vor jeder Testausführung. Unit- und Integrationstest der Recovery
hatten denselben Modulbasename `test_quarantine_recovery.py`; ohne getrennte
Unterpakete kollidierten ihre Linux-Pytest-Imports. Der Unit-Test heißt nun
eindeutig `test_quarantine_recovery_inspection.py`. Die vollständige lokale
Collection erfasste danach alle 2.099 Tests ohne Fehler; ausgeführt wurden
weiterhin nur die fokussierten Fälle. Produktionscode und
Sicherheitsverhalten änderten sich durch die Umbenennung nicht.

Der korrigierte stabile Head
`45dca9a9762eafeed8b46397595237c1bff75755` bestand Quality-Run
`32612809402` und Linux-Image-Run `32612809367`. PR #241 wurde als
`7c5f50ee298cc606c657da52bb361394365d84d2` auf `main` integriert; dessen
Eltern sind der exakte Base- und Feature-Head. Auch Post-Merge-Run
`32612937625` war grün.

`W10-005` ist damit funktional vollständig; die bewusst nicht atomare
No-Replace-Grenze des Interim-Executors und `FG-W10-MOVE-BACKEND` bleiben
unverändert sichtbar. `W9-007` hat danach mit dem vorangestellten reinen
`S-W9-007A`-Vertrag begonnen. Die gesamte Wave definiert ausschließlich nicht
ausführbare, reproduzierbare Operationsrezepte und öffnet keinen weiteren
Writer.

**S-W10-05C implementiert — Quarantäne-Execute ist einmalig und gefencet**

`quarantine-execute` ergänzt die zweite feste ADR-0056-Bedienstufe. Das
Kommando akzeptiert ausschließlich opaque Plan-, Capability- und
Authorization-IDs, den vollständigen Plan-Content-Hash und die
Darstellungswahl. Danach fordert es exakt
`CONFIRM QUARANTINE <Authorization-ID> <Plan-ID>` als eine höchstens 256
Zeichen lange, nicht geloggte `stdin`-Zeile. Freie Pfade, Dateinamen,
Batchlisten, Nonces, Command-Fragmente oder Bestätigung in argv und Environment
sind nicht verfügbar.

Vor dem Prompt werden Plan, Authorization, Capability und aktuelle
Persistenz-Lineage gebunden. Nach der Bestätigung löst der Operator die
Capability erneut auf, erwirbt eine
`CONSOLIDATION_QUARANTINE_RUN`-Lease und revalidiert darunter Plan, neueste
Reviews, Dependencies, File-/Observation-Lineage sowie Keeper und Candidate
streaming-basiert gegen Größe, Modified-Zeitpunkt und Full-SHA-256. Eine kurze
SQLite-Transaktion fences die Lease, prüft die aktuelle Plan-Lineage nochmals
und persistiert Run und bestätigtes `PREPARED`-Event atomar. Die eindeutige
Authorization-Bindung macht den Snapshot genau einmal verbrauchbar; ein Retry
mit derselben Authorization startet keinen zweiten Run.
Eine abgelaufene Quarantäne-Lease vor `PREPARED` darf nur in einer sofort
serialisierten SQLite-Transaktion gefencet übernommen werden, wenn zu ihrer
Owner-Run-ID nachweislich kein persistierter Run existiert. Sobald ein Run
existiert, bleibt auch eine abgelaufene Lease ausschließlich dem Recovery-Pfad
vorbehalten.

Erst danach ruft der Workflow ausschließlich den vorhandenen
Interim-Executor auf. Dieser prüft Candidate, Same-Filesystem und
Zielabwesenheit erneut, führt genau ein `os.rename` aus und verifiziert
Source-Abwesenheit sowie den vollständigen Ziel-SHA-256. Standardausgabe und
Fehler bleiben pfad-, dateinamen- und materialhashfrei; nach erzeugtem Run darf
nur dessen opaque ID für Status und spätere Recovery erscheinen. Die bewusst
nicht atomare Ziel-Abwesenheitsprüfung, `FG-W10-MOVE-BACKEND` und das Verbot von
Copy+Delete, Cross-Volume-Fallback, Overwrite, Rollback und Purge bleiben
unverändert.

Lokal bestanden 19 neue Confirmation-/CLI-/Lease-Unit-Tests, zehn neue
synthetische Execution-Integrationsfälle sowie 20 direkt betroffene bestehende
Quarantäne-Verträge. Die Abnahme belegt echten Ein-Datei-Move, gespeicherten
Confirmation-Digest, One-use, erneute Capability-Auflösung, Ablauf während
der Revalidierung, Review- und physische Source-Drift, aktive Root-Fence,
atomare orphaned-Lease-Übernahme, Recovery-only nach persistiertem
`PREPARED`, die erneute Executor-Revalidierung nach künstlicher TOCTOU-Drift,
pfadfreies `MANUAL_REVIEW` nach unerwartetem Executorfehler sowie unveränderte
Persistenz-/Authorization-/Contract-Grenzen. Ruff war für den
geänderten Python-Scope grün. Ein vollständiger Mypy-Lauf über 235 Source-
Dateien war grün; nach der finalen Race-Härtung wurden die beiden nochmals
geänderten Source-Module erneut ohne Befund geprüft.
Verwendet wurden ausschließlich synthetische temporäre Dateien und
SQLite-Datenbanken. Reale E-Books und private Runtime-Daten wurden nicht
geöffnet; eine vollständige lokale Suite wurde gemäß Test Policy nicht
gestartet. Zusätzlich bestanden 22 betroffene Planungs-, Dokumentations-,
W10- und Bootstrap-Verträge. Der stabile Head
`3ed588d5aca013bce47896e3716f3e5747121841` bestand Quality-Run
`32610844152` und Linux-Image-Run `32610844212`. PR #240 wurde als
`b86bc878f0e3000ba31d79f93573146149c58740` auf `main` integriert; auch
Post-Merge-Run `32610996492` war grün.

ADR-0056 wurde ohne Erweiterung der Entscheidung an den bereits akzeptierten
Persistenzvertrag angeglichen: Der Confirmation-Digest gehört zum atomaren
`PREPARED`-Event, und die eindeutige Run-Bindung stellt den Verbrauch dar. Die
veralteten Aussagen zu separaten Bestätigungs- und Verbrauchsevents wurden
entfernt; außerhalb der Interim-Ein-Datei-Quarantäne bleibt die Write-Grenze
unverändert.

`S-W10-05D` ergänzt darauf aufbauend die no-move Exact-State-Recovery und
schließt `W10-005`; diese aktuelle Wave ist im vorangestellten Abschnitt
dokumentiert.

**S-W10-05B implementiert — Quarantäne-Authorization ist operativ erreichbar**

`quarantine-authorize` vervollständigt den ersten Teil der festen
ADR-0056-Bedienkette. Das Kommando akzeptiert ausschließlich opaque Plan- und
Capability-IDs, den vollständigen kleingeschriebenen Plan-Content-Hash und die
Darstellungswahl. Datenbank und private Capability-Konfiguration stammen aus
lokaler Runtime-Konfiguration; freie Source-/Zielpfade, Batchlisten und
Command-Fragmente sind keine Argumente.

Vor jeder erfolgreichen Authorization rehydriert der Operator den exakten
persistierten `ConsolidationPlan`, prüft Status, bestätigte
`EXACT_DUPLICATE`-Identity, gerichtete Keeper-/Candidate-Entscheidung, neueste
kompatible Reviews, `KNOWN_NONE`-Dependencies und die aktuelle
File-/Observation-Lineage. Keeper und Candidate werden anschließend über
private relative Locator als stabile reguläre Einzeldateien ohne
Hardlink-Mehrfachreferenz streaming-basiert gegen Größe, Modified-Zeitpunkt und
vollständigen SHA-256 geprüft. Dieselbe aktuelle Plan-Lineage wird in der
SQLite-Transaktion unmittelbar vor dem insert-only Authorization-Insert erneut
validiert. Bei Plan-, Review-, Dependency-, Locator- oder physischer Drift
entsteht kein Datensatz.

Die höchstens 15 Minuten gültige Ausgabe enthält nur Authorization-, Plan- und
ScanRoot-ID, Profil, Status und Zeitfenster. Pfade, Dateinamen,
Material-/Review-Hashes und Capability-Inhalte bleiben privat. Authorize liest
Source Media ausschließlich und ruft weder `os.rename` noch den vorhandenen
Interim-Executor auf. `S-W10-05C` ergänzt darauf aufbauend Execute, zweite
Bestätigung und One-use-Fencing; `quarantine-recover` folgt getrennt in
`S-W10-05D`. Die begrenzte nicht atomare Interim-Semantik und
`FG-W10-MOVE-BACKEND` bleiben unverändert.

Lokal bestanden sieben neue Source-/CLI-Unit-Tests, vier neue
Authorization-/SQLite-Integrationsfälle sowie 24 direkt betroffene bestehende
Quarantäne-Verträge; ein hostabhängiger Symlink-Fall wurde auf Windows wie
vorgesehen übersprungen. Zusätzlich bestanden 20 betroffene Planungs- und
Dokumentationsverträge. Repository-Ruff war grün, Mypy prüfte 234
Source-Dateien ohne Befund. Verwendet
wurden ausschließlich synthetische temporäre Dateien und SQLite-Datenbanken;
reale E-Books und private Runtime-Daten wurden nicht geöffnet. Der vollständige
PR-CI-Gate bleibt dem exakten stabilen Head vorbehalten.

Der erste 05B-PR-Gate erreichte erfolgreich Install, Ruff und Mypy, stoppte
aber während der Test-Collection: Auf dem Linux-Runner wurde das lokale
Namespace-Verzeichnis `tests` durch ein fremdes installiertes Paket gleichen
Namens verdeckt. `tests/__init__.py` markiert den bestehenden Testbaum nun
explizit als lokales Paket; Produktionscode und Sicherheitsverhalten blieben
unverändert. Die lokale Collection fand danach 2.051 Tests fehlerfrei; die vier
neuen Autorisierungs-Integrationsfälle blieben grün. Der zweite Gate erreichte
anschließend 2.042 erfolgreiche Tests bei acht erwarteten Skips; nur der
explizite Statusausgabe-Vertrag erwartete die neue
`quarantine-authorize`-Zeile noch nicht. Die Erwartung wurde mit der bereits
implementierten, mutationsfreien Statusausgabe synchronisiert. Der finale
05B-Head `bb9ef78` bestand danach Quality- und Linux-Image-Gate. PR #239 wurde
als Merge-Commit `5f5b068` auf `main` integriert; auch der Post-Merge-Contract
war grün.

**S-W10-MW05 implementiert — EPUB-Titelwriter besitzt Bedienung und Reconciliation**

ADR-0064 schließt die Bedien- und Reconciliation-Grenze des einzigen durch
ADR-0063 erlaubten Source-Metadata-Writers. Die vier festen Kommandos
`metadata-write-authorize`, `metadata-write-execute`,
`metadata-write-recover` und `metadata-write-status` akzeptieren nur opaque
IDs, den gebundenen Plan-Content-Hash und die Darstellungswahl. Datenbank,
privater Stagingbereich, Capability-Konfiguration und feste Toolpfade stammen
aus lokaler Runtime-Konfiguration. Source-, Recovery- und Stagingpfade sowie
Titelwerte erscheinen weder als Argument noch in Standardausgaben.

Authorize benötigt einen vorhandenen aktuellen, reviewten
`MetadataCorrectionPlan`. Unter einer kurzen Preparation-Lease liest der
Operator die Source no-follow und bounded, erzeugt den deterministischen
privaten Output und verlangt EPUBCheck-Konformität sowie die festen Metadaten-,
Text-, Cover- und Preserved-Field-Read-backs. Execute fordert unmittelbar vor
der einmaligen Runerzeugung exakt `CONFIRM METADATA WRITE <Authorization-ID>`
als eine nicht geloggte `stdin`-Zeile. Der persistierte domänengetrennte Digest
bindet Authorization, Plan-ID, Plan-Content-Hash und Capability-ID; eine
abweichende Eingabe erzeugt keinen Run.

Der MW04-Executor liest nach Exchange und Originalerhalt die tatsächliche
Source erneut no-follow, verlangt exakte Outputbytes und führt die festen
Validatoren ein zweites Mal aus. Bei eindeutigem Verifikationsfehler stellt er
das Original wieder her; unklare Hashverteilungen bleiben ohne weitere
Mutation `MANUAL_RECOVERY_REQUIRED`. Nach `ORIGINAL_PRESERVED` gibt der
Operator die Run-Lease explizit frei, startet genau einen vollständigen,
inkrementell wiederverwendenden Scan mit einem Hash-Worker und baut aus dessen
neuer Observation einen `collection-state/v1`-Snapshot. Unter einer neuen
Run-Fence werden physischer Zustand, Scan, Observation, Full-SHA-256 und
`CollectionState` erneut geprüft.

Migration `0029_metadata_write_reconciliation` speichert genau eine immutable
Reconciliation je Run. Insert und `VERIFIED`-Event entstehen atomar; ein
Recovery bindet den wiederhergestellten Originalhash durch dieselbe Scanfolge
und endet ausschließlich bei `RECOVERED`. Status bleibt SQLite-read-only und
pfadfrei. Es gibt weiterhin keinen Delete-, Copy+Delete-, Overwrite-,
Cross-Volume-, Purge-, Sidecar-, Calibre-, Rename- oder Archivewrite-Fallback.
REST-API und grafische Oberfläche bleiben hinter ihrer eigenen
Produktoberflächenentscheidung.

Der zusammengefasste lokale MW05-Lauf bestand 46 fokussierte Unit-, SQLite-,
Migrations-, Privacy-, Operator-, Reconciliation-, Recovery- und statische
Tests in 30,07 Sekunden; sieben echte Linux-/tmpfs-Fälle wurden auf Windows
erwartungsgemäß ausgelassen und 14 nicht zum Fokus gehörende Fälle
abgewählt. Zwei ergänzende Composition-Tests für Runtime-Toolkonfiguration und
Engine-Freigabe nach fehlgeschlagener Erzeugung bestanden separat.
Nach der strikten Scan-Zeitgrenze bestanden außerdem der betroffene
Persistenzfall sowie beide vollständigen synthetischen Operatorpfade zu
`VERIFIED` und `RECOVERED` erneut. Der vollständige Head-Tabelleninventarfall
bestätigte danach Revision und neue Reconciliation-Tabelle.
Ruff war für den gesamten geänderten Python-Scope sowie nach dieser Ergänzung
für CLI und CLI-Test grün; Mypy prüfte zunächst zehn betroffene Source-Dateien
und danach erneut CLI und Operator-Workflow ohne Befund. `compileall` war für
den geänderten Source-Scope auch nach den Härtungen erfolgreich. Verwendet
wurden ausschließlich synthetische EPUBs, temporäre SQLite-Datenbanken und
synthetische Dateisysteme; reale E-Books und produktive Runtime-Datenbanken
wurden nicht geöffnet. Der stabile Pull-Request-Head erhält
ressourcenschonend genau einen vollständigen Linux-PR-CI-Gate.

Der erste PR-Gate des MW05-Heads bestand 2.030 Tests bei acht erwarteten
Skips und fand genau eine veraltete statische Erwartung: `W10-005` wurde nach
dem Abschluss von MW05 weiterhin als `READY` statt als kanonisches `NEXT`
erwartet. Der Vertragsassert wurde ohne Produktionscodeänderung auf die bereits
dokumentierte Ausführungsfront synchronisiert; der korrigierte Head benötigt
erneut den vollständigen Gate.

`S-W10-05C` und `S-W10-05D` ergänzen inzwischen die bereits durch ADR-0056
erlaubte Interim-Ein-Datei-Quarantäne um Execute, zweite Bestätigung,
One-use-Fencing und no-move Recovery. Die separate
`FG-W10-MOVE-BACKEND`-Härtung und alle weiteren Mutationstypen bleiben davon
unberührt.

**S-W10-MW04 implementiert — Linux-Exchange und Recovery bleiben ohne Bedienpfad**

`foliotone.metadata_write.linux_backend` implementiert ausschließlich
`epub-source-replace-linux-renameat2/v1` für Linux x86_64 mit glibc. Das
Backend öffnet Capability- und Source-Verzeichnisse komponentenweise über
no-follow Directory-FDs, akzeptiert nur dieselbe lokale ext-, Btrfs-, tmpfs-
oder XFS-Instanz und prüft `RENAME_EXCHANGE` sowie `RENAME_NOREPLACE` in einem
capability-eigenen persistenten Probe-Slot. Native Windows-Ausführung,
read-only oder nicht unterstützte Filesysteme, fremde Owner, Symlinks,
Hardlinks, Special Bits und nicht leere beziehungsweise nicht prüfbare xattrs
schlagen fail-closed fehl.

Der Executor rekonstruiert den autorisierten Output erneut im privaten
Staging, vergleicht alle gebundenen Hashes, Größen, Toolversionen und den
Validator-Fingerprint und erzeugt danach exklusiv einen internen Draft neben
der Source. Unmittelbar vor Source-Draft, `PREPARED`, atomarem Exchange,
Originalerhalt und Restore werden eine frische Root-Fence und mindestens zwei
Minuten verbleibende Lease-Zeit verlangt. Das separate
`PREPARED`-Execution-Gate prüft vor dem ersten Exchange zusätzlich die noch
gültige Authorization, aktuelle Plan-/Review-/File-Lineage und den festen
Backend-Binding-Snapshot. Erfolg endet absichtlich bei
`ORIGINAL_PRESERVED`; `VERIFIED` gehört zu `S-W10-MW05`.

Migration `0028_metadata_write_backend` ergänzt genau einen immutable,
pfadfreien Backend-/Probe-Binding-Snapshot je Run. Die Recovery verwendet
unter einer neuen Fence ausschließlich den historischen autorisierten
Observation-Locator und exakte Full-SHA-256-Verteilungen. Sie darf deshalb
auch nach Authorization-Ablauf oder späterer Änderung des aktuellen
`FileRecord` den ursprünglichen Zustand derselben Operation wiederherstellen.
Uneindeutige Verteilungen führen ohne weitere Mutation zu
`MANUAL_RECOVERY_REQUIRED`. Es existiert kein Copy+Delete-, Overwrite-,
Cross-Volume-, Delete- oder Cleanup-Fallback; Draft-, Recovery- und
Probe-Artefakte bleiben erhalten.

Der zusammengefasste lokale MW04-Lauf bestand 37 fokussierte Unit-, SQLite-,
Migrations-, Privacy-, Planungs- und statische Tests in 23,83 Sekunden; sieben
echte tmpfs-/`renameat2`-Fälle wurden auf Windows erwartungsgemäß ausgelassen.
Nach den abschließenden eng begrenzten Gate- und Cleanup-Härtungen bestanden
zusätzlich acht Executor-Fälle, der betroffene Store-Fall sowie sieben
Backend-Fälle; die sechs Backend-Linux-Fälle blieben dabei
ausgelassen. Weitere 17 Dokumentationsverträge waren grün. Ruff war für den
gesamten geänderten Python-Scope grün, Mypy prüfte zwölf direkt betroffene
Source-Dateien ohne Befund und `git diff --check` war sauber. Die ausgelassenen
Fälle müssen im einmaligen vollständigen Linux-PR-CI-Gate des stabilen Heads
grün werden. Verwendet wurden ausschließlich synthetische EPUBs und temporäre
Datenbanken im vorgesehenen Projekt-Tempbereich; reale E-Books und produktive
Runtime-Datenbanken wurden nicht geöffnet.

Zum Abschluss von MW04 war `S-W10-MW05` der nächste reguläre Slice: feste
Authorize-/Execute-/Recover-CLI, zweite Bestätigung über nicht geloggtes
`stdin`, unmittelbare Post-write-Verifikation, neuer Scan und Collection-
Reconciliation. Diese Lücke ist inzwischen geschlossen; REST-API, grafische
Oberfläche, Music und Bilder bleiben weiterhin außerhalb dieses Writers.

**S-W10-MW03 abgeschlossen — Authorization und Journal bleiben nicht ausführbar**

`foliotone.metadata_write` ergänzt `metadata-write-preparation/v1` und
`metadata-write-authorization/v1`. Der content-addressed Prepare-Snapshot
bindet den verifizierten privaten Staging-Output an den exakten aktuellen
`MetadataCorrectionPlan`, Input-/Outputidentität, `dcterms:modified`,
Writer-/Patcher-/Staging-/Validatorprofile, konkrete Toolversionen,
Capability-ID sowie die tatsächlich gehaltene Preparation-Fence. Die daraus
abgeleitete Authorization ist höchstens 15 Minuten gültig und kann nur von
genau einem Run verbraucht werden.

Der private `MetadataWriteCapabilityResolver` löst
`FOLIOTONE_METADATA_WRITE_CAPABILITIES_FILE` bounded und fail-closed auf. Die
owner-only geschützte POSIX-Konfiguration wird no-follow geöffnet und nach dem
Open erneut über Inode, Owner, Mode und Linkzahl geprüft. Sie darf nur opaque
Capability-/`ScanRoot`-IDs, das feste Writerprofil und zwei existierende,
disjunkte absolute Verzeichnisse desselben gemeldeten Filesystems enthalten.
Pfade bleiben aus DTO-Repräsentationen, Persistenz und Reports ausgeschlossen;
native Windows-Auflösung bleibt `TOOL_UNAVAILABLE`.

Migration `0027_metadata_write_operations` ergänzt die Lease-Owner
`METADATA_WRITE_PREPARATION` und `METADATA_WRITE_RUN` sowie drei insert-only
Tabellen für Authorization, einmaligen Run und gapless Events. Trigger
verhindern Update und Delete; ein belegter Zustand sperrt den Downgrade.
`SQLiteMetadataWriteStore` revalidiert vor Authorization und Run den
unveränderten W9-Plan, seine aktuelle Source-/Evidence-/Dependency-Lineage und
die neueste kompatible akzeptierte Review Decision. Preparation, Runerzeugung
und jedes Folgeevent sind an eine tatsächlich aktuelle Root-Fence gebunden;
Run und `CREATED`-Event entstehen atomar. Ungültige oder nicht monotone
Statusfolgen schlagen auch beim Lesen fail-closed fehl.

`metadata-write-status-report/v1` ist eine interne echte Read-only-Projektion.
Sie selektiert nur opaque IDs, Profile, Zeitpunkte und Zustände und enthält
keine Pfade, Titelwerte, Hashes, Capability-Inhalte, Fences, Findings oder
Confirmation-Digests. Es gibt weiterhin keine CLI, keinen Source-Commit,
keinen `renameat2`-Adapter, keinen Executor und keine Recovery. Reale E-Books
und produktive Runtime-Datenbanken wurden nicht verwendet. Änderungen an den
gebundenen Writer-, Patcher-, Staging-, Validator- oder Toolversionen erfordern
eine neue Preparation und Authorization.

Vor der abschließenden reinen Test-Fixture-Optimierung bestanden 71 fokussierte
synthetische MW01-/MW02-/MW03-, Capability-, Privacy-, Fencing-, Migration-,
Journal-, Status- und Non-Execution-Tests in 34,17 Sekunden. Ruff war für den
gesamten geänderten Python-Scope grün; Mypy prüfte 12 direkt betroffene
Source-Dateien ohne Befund. Auf dem finalen lokalen Stand bestanden zusätzlich
der Datenbank-Testeffizienzvertrag und die vier davon betroffenen
Integrationsfälle, insgesamt 5 Tests in 18,33 Sekunden. `git diff --check` war
sauber. Die vollständige lokale Suite wird ressourcenschonend nicht
dupliziert; der stabile Pull-Request-Head erhält genau einen vollständigen
CI-Gate.

`S-W10-MW04` implementiert inzwischen das interne Linux-`renameat2`-Backend,
den Ein-Datei-Executor und idempotente Crash-Recovery auf synthetischen
Filesystemen. `S-W10-MW05` ergänzt inzwischen die begrenzte CLI und
Reconciliation; diese Aussage ändert den historischen MW03-Scope nicht.

**S-W10-MW02 abgeschlossen — privates EPUB-Staging ist unabhängig verifizierbar**

`foliotone.metadata_write` ergänzt den reinen MW01-Preflight/Patch um
`epub3-title-private-staging/v1`. Der Builder erhält keinen Source-Pfad,
sondern ausschließlich einen Bytestrom, kopiert ihn einmal bounded und mit
Full-SHA-256-Revalidierung in einen exklusiv neu angelegten privaten Ordner
und erzeugt dort feste `input.epub`-/`output.epub`-Einträge ohne
Überschreiben. Unveränderte ZIP-Member werden komprimiert roh und inkrementell
kopiert; nur das gebundene Package Document wird gemäß seiner bisherigen
Stored-/Deflate-Methode neu komprimiert.

Entry-Menge und -Reihenfolge, rohe Namen, General-Purpose-Flags,
Kompressionsmethoden, DOS-Zeitwerte, lokale und zentrale Extra Fields,
Entry-/Archivkommentare sowie interne/externe Attribute bleiben erhalten.
Data Descriptors werden unterstützt, ZIP64 bleibt geschlossen. Der
anschließende streaming-basierte Read-back berechnet jeden unkomprimierten
Memberhash neu, verlangt den exakten Zwei-Spannen-Patch und liefert denselben
`EpubTitleArchiveDiff`-Vertrag wie die reine kleine Bytes-Prüfung.

`FixedEpubTitleStagingValidator` führt danach genau sieben feste, nicht
persistierende Prüfungen ausschließlich gegen die privaten Kopien aus:
`ebook-meta` für Input und Output, EPUBCheck für den Output, `ebook-convert`
für beide Textprojektionen sowie den bestehenden `calibre-debug`-Coverhelper
für beide Coverprojektionen. Prozesse laufen ohne Shell, mit festen
Argumenten, isolierten Calibre-/Temp-Verzeichnissen, Version Policy, Timeout
und bounded privaten Artefakten. Calibre bleibt Reader, nicht Writer.

Der Validator verlangt den normalisierten ausgewählten Titel, identische
nicht zielbezogene Metadatenprojektionen, `CONFORMANT` durch EPUBCheck,
identische normalisierte Textfingerprints und identische Coverzustände/-
fingerprints. Input und Output werden vor und nach allen Toolaufrufen erneut
vollständig gehasht. `epub3-title-staged-validation/v1` speichert im Ergebnis
nur Hashes, Status und Toolversionen; Pfade und Titel sind nicht repräsentiert
und nichts wird in SQLite persistiert. Nur Calibres bei jedem OPF-Export neu
erzeugte volatile `identifier:calibre`-Projektion wird aus dem unabhängigen
Preserved-Field-Vergleich entfernt; der native Memberdiff belegt weiterhin den
Erhalt jedes Source-Identifier-Bytes.

Der Slice besitzt weiterhin keine Capability, Authorization, Lease,
Run-/Eventpersistenz, CLI, Source-Ersetzung oder Recovery. Reale E-Books und
produktive Runtime-Datenbanken wurden nicht verwendet. Am finalen lokalen
Stand bestanden 76 fokussierte synthetische MW01-/MW02-, Privacy-, Non-
Execution-, W10- und Dokumentationsvertragstests in 0,63 Sekunden. Ruff war
für den geänderten Python-Scope grün, Mypy prüfte 219 Source-Dateien ohne
Befund und `git diff --check` war sauber. Ein zusätzlich begonnener breiterer
Windows-Lauf erreichte 71 erfolgreiche Fälle und stoppte ausschließlich am
bereits dokumentierten `\\?\`-Pfadpräfix der unveränderten Calibre-Analyzer-
Regression; der Linux-PR-Gate bleibt dafür kanonisch. Die vollständige lokale
Suite wird nicht dupliziert; der stabile Pull-Request-Head erhält genau einen
vollständigen CI-Gate.

`S-W10-MW03` ergänzt inzwischen immutable Authorization-/Run-/
Eventpersistenz, private Capability-Auflösung, `ScanRootWriteLease`-/
Fence-Vertrag und privacy-begrenzten read-only Status. `S-W10-MW04` ergänzt
Linux-Commit und Recovery; `S-W10-MW05` ergänzt inzwischen die begrenzte CLI
und Reconciliation. Die älteren Slices bleiben für sich nicht ausführbar.

**S-W9-006C abgeschlossen — Metadatenkorrekturpläne sind read-only berichtbar**

Das neue Paket `foliotone.metadata_correction` implementiert immutable,
path-free und bounded DTOs für `MetadataCorrectionCandidate` und
`MetadataCorrectionPlan`. Der Candidate bindet genau eine aktuelle E-Book-
Observation, Full-SHA-256, beobachtete und ausgewählte private Werte, einen von
fünf strikt getrennten Zielträgern, alle drei Dependency-Achsen sowie eine
semantische Writeranforderung ohne Tool- oder Commandbindung. Eine feste
Feldgrammatik deckt einfache, Contributor-, Identifier- und Series-Felder ab,
ohne freie JSON-Pfade zu öffnen.

Reine Builder erzeugen Feldselektions-, Evidence-, Candidate- und Planhashes
über Unicode-NFC-normalisiertes `canonical-json/v1`. Candidate- und Plan-ID
werden deterministisch per UUIDv5 aus dem jeweiligen Content Hash abgeleitet;
Auditzeitpunkte ändern ihre Identität nicht. Der Reducer bindet Candidate und
Review-Snapshot an feste Preconditions und Post-write-Verifikation und liefert
nur `BLOCKED`, `REVIEW_REQUIRED` oder `APPROVED_NON_EXECUTABLE`. Der einzige
Execution-State bleibt permanent `NOT_EXECUTABLE`.

Der Review-Core enthält additiv `ReviewType.METADATA_CORRECTION` und
`ReviewCandidateKind.METADATA_CORRECTION_CANDIDATE` mit fester Paarung.
Migration `0026_metadata_correction_plans` erhält vorhandene Review- und
Consolidation-Review-Historien beim Constraint-Rebuild und ergänzt 14
normalisierte Candidate-/Plan-Tabellen. Parent- und Childzeilen sind durch
Trigger immutable; deklarierte Counts begrenzen jeden Child-Graph. Ein
Downgrade wird bei vorhandenen Metadata-Correction-Daten oder Reviewfällen
verweigert.

`SQLiteMetadataCorrectionStore` persistiert Candidate und Plan atomar,
rehydriert alle Values, Evidence, Dependencies, Reviews, Preconditions,
Verifikation und Blocker bounded und berechnet Candidate-, Evidence-, Feld-,
Writer- und Planidentitäten erneut. Vor einem Insert prüft er den
abgeschlossenen book-only `ScanRun`, File-/Observation-Snapshot,
`FILE_SHA256`, polymorphe Evidence, Dependency- und Ziel-Lineage sowie die
neueste kompatible Review Decision in derselben kurzen Transaktion. Der Plan
muss zusätzlich dem kanonischen Reducer entsprechen. Exakte Retries verwenden
den vorhandenen Snapshot; abweichende Payloads schlagen fail-closed fehl.

Private Metadatenwerte liegen nur in den dafür vorgesehenen Runtime-
Valuezeilen und erscheinen weder in Fehlern noch in Standardrepräsentationen.
Der erweiterte Non-Execution-Gate bestätigt auch für den Store: kein
Filesystem-/Subprocessimport, keine Source-Media-Öffnung und keine öffentliche
Apply-/Execute-/Write-Fläche. Es gibt weiterhin keinen Writer.

`ebook-metadata-correction-report` liest genau einen persistierten Plan über
eine echte SQLite-Read-only-Verbindung mit `mode=ro` und `query_only=ON`.
Text und JSON enthalten ausschließlich Plan-/Candidate-ID, Plan-/Candidate-
Profil, Status, Execution-State, Plan-Content-Hash, Zielträger, Format,
Feldpfade, Operationen, Counts, Reviewstatus und Blockerliterale. Private
Werte, Pfade, File-/Observation-/Root-IDs, Dateinamen, Source-/Target-
Fingerprints und Evidence-Materialien bleiben ausgeschlossen. Fehlende
Datenbanken, ältere Schemas, fehlende Pläne und interne Lesefehler ergeben nur
feste pfadfreie Fehlercodes; der Report migriert oder bootstrapt kein Schema.

Der neue echte Read-only-Fall deckte eine zu strenge historische
Reviewprüfung auf: Ein korrekt persistierter `MISSING`-Snapshot besitzt kein
`ReviewItem`. Der Store akzeptiert diesen vertraglichen Zustand beim Lesen
nun ausdrücklich; andere Reviewzustände bleiben an ihre persistierten
`ReviewItem`-/`ReviewDecision`-Lineage gebunden.

`W9-006` ist abgeschlossen. ADR-0063 hat `FG-W10-METADATA-WRITE` anschließend
für den begrenzten EPUB-3-Titelwriter entschieden; `S-W10-MW01` und
`S-W10-MW02` liefern Patch, privates Staging und unabhängige Verifikation;
`S-W10-MW03` liefert Authorization, Journal, Capability/Fencing und read-only
Status. `S-W10-MW04` liefert den internen Linux-Executor und Recovery;
`S-W10-MW05` schließt Bedienung und Reconciliation ab.
`W10-005` und `W9-007` sind ebenfalls abgeschlossen. Als nächster Schritt ist
`FG-W10-RENAME` ausschließlich als dokumentarische Frontier-Entscheidung
vorgesehen; ein Rename-Executor wird dadurch noch nicht aktiviert. Allgemeine
reale Mutation, Music, Bilder, REST-API und grafische Oberfläche werden durch
diesen Abschluss nicht aktiviert. Am
finalen lokalen Stand von S-W9-006C bestanden 41
fokussierte Report-, Privacy-, Schema-, Bootstrap-, Store-, Consolidation-
Regression- und statische Tests in 26,36 Sekunden. Ruff war für alle
geänderten Python-Dateien und Mypy für die drei betroffenen Source-Module grün;
`git diff --check` war ohne
Befund. Eine vollständige lokale Suite wurde ressourcenschonend nicht
dupliziert; der stabile Pull-Request-Head erhält genau einen vollständigen
CI-Gate.

**CS-03 abgeschlossen — die book-only Produktprojektionen sind vollständig**

`collection-state-build` erzeugt `collection-state/v1` deterministisch aus
der bereits persistierten Evidence genau eines abgeschlossenen book-only
`ScanRun`. Die additive Migration `0023` speichert Snapshot, Komponenten,
vollständige Zähler und itembezogene Zustände insert-only; Update und Delete
werden durch Datenbank-Trigger abgewiesen. Coverage, Freshness, Konflikte und
Kürzungen bleiben je Komponente explizit. Ein identischer Rebuild verwendet
denselben content-addressed Snapshot, geänderte Evidence erzeugt einen neuen.

`collection-state-report` liest ausschließlich über eine echte SQLite-
Read-only-Verbindung und gibt keine Pfade, Metadatenwerte oder internen
Evidence-Digests aus. Builder und Report öffnen keine Source Media, starten
keine Tools oder Provider und besitzen keine Mutation Authority.

`collection-state-diff` vergleicht zwei kompatible Snapshots deterministisch
und trennt hinzugefügte, verschwundene, technisch geänderte, neu analysierte,
neu aufgelöste, neu reviewte und neu blockierte Zustände. Vollständige Counts
und begrenzte, nach opaque `File`-ID paginierte Details bleiben pfadfrei.

Migration `0024` ergänzt den insert-only, snapshotgebundenen
`collection-query-index/v1`. `collection-search` akzeptiert ausschließlich den
validierten `collection-query/v1`-AST mit festen Feldern und Operatoren,
`AND`/`OR`, `FILE_ID_ASC`, Keyset-Pagination und harten Grenzen. FTS5 enthält
nur ausgewählte Metadaten-Candidates; Content, OCR, Netzwerk und Query-History
bleiben ausgeschlossen. JSON bleibt metadatenwertfrei. Private Metadatenwerte
benötigen ausdrücklich `--private-details` mit interaktiver Textausgabe;
absolute Pfade werden auch dort unterdrückt.

ADR-0060 und Migration `0025` ergänzen `library-health/v1`. Die immutable,
content-addressed Projektion bindet genau einen `CollectionState` und dessen
Query-Index. Sie trennt Scan/Fixity, Analyseabdeckung,
Metadaten/Authority/Classification, offene Reviews, Duplicate-/Varianten-
Evidence, Dependencies und blockierte Operationen. Jede Dimension besitzt
eigene Coverage und eigenen Status; es gibt keinen Gesamtscore.

`collection-state-build` erzeugt oder verifiziert State, Query-Index und
Health atomar. Findings behalten vollständige Counts und höchstens 64 nach
opaque `File`-ID sortierte File-/Observation-Samples. `library-health-report`
öffnet SQLite tatsächlich read-only, gibt keine Pfade, Metadatenwerte,
Fingerprints oder Evidence-Digests aus und kann zwei kompatible Snapshots
desselben `ScanRoot` ohne Kausalitätsbehauptung vergleichen. Weder Projektion
noch Report erzeugen Identity-, Keep- oder Mutationsentscheidungen.

Nach Abschluss von `CS-01` bis `CS-03` ist keine weitere Medienlinie
automatisch aktiviert. Music W4 und Bilder bleiben geplant. FUT-011 verlangt
vor REST-API oder grafischer Oberfläche eine eigene Produktoberflächen-ADR
mit getrennten Einstiegspunkten je Medienlinie und strikt separaten W10-
Capabilities; die aktive Oberfläche bleibt die CLI.

`EBOOK_WRITE_PIPELINE_PLAN.md` dokumentiert nun zusätzlich die vollständige
book-only Leserichtung von Scan, Analyse, Quality, Resolution, Matching und
Review über nicht ausführbare Metadatenkorrektur-/Konsolidierungspläne bis zu
operation-spezifischen W10-Gates, Revalidierung, Fencing, Verifikation,
Recovery und der späteren REST-/UI-Grenze. ADR-0061 autorisiert ihre
kontrollierte Entwicklung, nicht eine pauschale reale Mutation. `W9-006` und
`W9-007` sind abgeschlossen. Der erste Metadata-Write-Vertrag ist
abgeschlossen. ADR-0066 hat das rein dokumentarische `FG-W10-RENAME`
inzwischen nur für Same-Parent-`FILE_RENAME` entschieden; `S-W10-RN01` ist
der nächste Slice. Reorganisation, Sidecar-, externe Library- und Archive-
Write-Gates bleiben getrennte technische `DECISION`s.

**W10-Interim abgeschlossen — Executor und read-only Quarantänestatus sind vorhanden**

ADR-0056 akzeptiert als erste W10-Grenze ausschließlich reine Quarantäne-
DTOs sowie immutable Authorization-/Run- und lückenlose Event-Persistenz.
S-W10-02 liefert die additive Migration `0022`, die neue Root-Lease-Owner-
Klasse `CONSOLIDATION_QUARANTINE_RUN`, Fence-Prüfungen und bounded Reads.
S-W10-03 ergänzt den bewusst engen Interim-Executor: nur `os.rename` im
gleichen vom Betriebssystem gemeldeten Filesystem, Ziel-Abwesenheitsprüfung,
vollständige SHA-256-Revalidierung und kein Copy+Delete-/Cross-Volume-
Fallback. Die Zielprüfung ist nicht atomar; `FG-W10-MOVE-BACKEND` bleibt als
spätere Frontier-Härtung für atomaren No-Replace, no-follow und Race-/Crash-
Nachweise im Backlog.
S-W10-04 ergänzt `quarantine-status`: eine echte SQLite-Read-only-Projektion
pro Run mit ausschließlich opaken IDs, Statuswerten und Zeitpunkten. Weder
Pfade, Namen, Materialhashes, `target_token`, `confirmation_digest` noch
Finding-Eingaben gelangen in die Ausgabe.

`S-W10-05A` ist abgeschlossen: Der private, bounded und fail-closed
`QuarantineCapabilityResolver` löst ausschließlich über die geschützte lokale
`FOLIOTONE_QUARANTINE_CAPABILITIES_FILE` opaque Capability- zu ScanRoot-IDs
und privaten Laufzeitverzeichnissen auf. Fehler bleiben `TOOL_UNAVAILABLE` und
pfadfrei; CLI, Persistenz und Executor-Aufrufe gehören weiterhin nicht dazu.
Die nicht atomare Zielprüfung und alle weiteren W10-Sperren bleiben unverändert
sichtbar.

**Abgeschlossene Voraussetzungen:** EB-04 DONE; EB-03B DONE.

Der unabhängige operative Punkt W3-026 ist abgeschlossen. ADR-0057 ergänzt ein
gelocktes Docker-first-Image für calibre, Poppler, Java und EPUBCheck, einen
expliziten Windows-/WSL2-Provisioning-Schritt sowie den pfadfreien
`ebook-tools-doctor` mit Readiness je unterstütztem E-Book-Format. Kein
Analysekommando installiert oder aktualisiert Werkzeuge. Die aktive W10-
Vertragsfrontier S-W10-01 bleibt dadurch unverändert.

Die lokale Windows-Verifikation am 2026-08-21 verwendete Docker Engine 29.7.2
in `Codex-Ubuntu-24.04` unter WSL2. Die automatische Backendwahl, der
vollständige gelockte Image-Build und der anschließende offline/read-only
Doctor waren erfolgreich; alle sieben Komponentenprobes und alle fünf
Formatprofile meldeten `READY`. Die fokussierte Suite einschließlich der
betroffenen `main`-Regressionen bestand mit 26 Tests; Ruff, Mypy für 180
Source-Dateien, Compose- und Dokumentationsverträge waren
ebenfalls grün.

EB-04 ist mit S-EB04-01 bis S-EB04-07 abgeschlossen. Die additive Migration
0018, der immutable profiled Assertion-/Lineage-Store, bounded Target-/Profile-
Queries, der deterministische Projection-Reducer, immutable Reprojection-
Snapshots und die pfadfreie read-only CLI-Zusammenfassung sind umgesetzt.
Die CLI gibt ausschließlich feste Labels, opaque interne IDs, Counts, Profile,
Status sowie Conflict-/Truncation-Marker aus; Values, Taxonomien, Quellen,
References, Pfade und Rohdaten bleiben ausgeschlossen. Alle CLI-Berichtsreads
verwenden eine echte SQLite-Read-only-Verbindung und scheitern bei fehlender
oder inkonsistenter Projektion geschlossen. Classification bestätigt
keine Identity Relation und autorisiert keine W10-Operation.

Die Scan-CLI zeigt auf einem interaktiven Terminal standardmäßig einen
pfadfreien Datei-, Datenmengen- und Durchsatzfortschritt auf `stderr`;
`--progress` und `--no-progress` erlauben eine ausdrückliche Steuerung. Der
Default `--hash-workers auto` verwendet höchstens die Hälfte der sichtbaren
CPU-Anzahl und bleibt auf 1 bis 8 begrenzt. Ein `KeyboardInterrupt` beendet die
CLI ohne Traceback mit Exitcode 130; ein bereits gestarteter `ScanRun` wird
weiterhin persistent `INTERRUPTED`, und aktive In-Process-Hashreads erhalten
ein kooperatives Abbruchsignal. Die Batchgröße bleibt bewusst bounded und
explizit statt durch eine nicht reproduzierbare Laufzeitheuristik verändert zu
werden. `migrate()` repariert ausschließlich schemaidentische, leere
0016-Tabellen, die vor dem Alembic-Revisionseintrag durch einen Abbruch
zurückblieben; abweichende oder befüllte Strukturen bleiben fail-closed.

Die gezielten CLI-/Static-Tests sowie die betroffenen Regressionen, Ruff,
Mypy, Dokumentationsprüfungen und `git diff --check` sind vor dem PR-Gate
auszuführen; ein vollständiger Gate bleibt dem koordinierenden PR vorbehalten.

FG-A ist durch ADR-0038 akzeptiert. Die mechanischen Pakete S-EBA-01 bis
S-EBA-07 sind auf `main` abgeschlossen und bleiben strikt synthetisch
beziehungsweise Fake-only. Sie liefern Fixture-, Signatur-, Sidecar-, lokale
Secret-Candidate-, `SecretHandle`-, Safety-Policy- und Fake-Workflow-Verträge,
starten aber kein reales Archivtool.

FG-A-RUNTIME ist durch ADR-0039 akzeptiert. S-EBAR-01 implementiert getrennte
Listing-, Integrity- und Extraction-Provenance; S-EBAR-02 implementiert den
bounded `archive-7zip-slt-parser/v1`. Beide Pakete sind auf `main`
abgeschlossen und verwenden ausschließlich synthetische Daten.

FG-A-IMAGE ist durch ADR-0040 akzeptiert. Das projekt-eigene Image verwendet
für genau `linux/amd64` `FROM scratch`, den unveränderten offiziellen
statischen `7zzs`-26.02-Tar-Member mit festem Upstream-SHA-256, vollständige Lizenzhinweise
und `USER 65532:65532`. Der Upstream-Release besitzt keinen unabhängigen
Signaturnachweis; FolioTone dokumentiert ihn deshalb als
`UNSIGNED_UPSTREAM_RELEASE`. S-EBAR-03 hat das Offline-Rezept, den statischen
ELF-Nachweis, das gepinnte Buildx-/BuildKit-Profil, den zweifachen
reproduzierbaren Single-Platform-Build, `archive-image-lock/v1`, SPDX,
Custom-SLSA-Provenance, Toolmanifest und feste Command Builder umgesetzt. Der
gemessene Plattform-Manifest-Digest lautet
`sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287`.

FG-A-RUNTIME-AVAILABILITY ist durch ADR-0041 akzeptiert und S-EBAR-03A ist auf
`main` umgesetzt. `BOOTSTRAP_LOCKED` und lokales Image Inspect sind keine
Runtime-Authority. Der reviewte `archive-runtime-release/v1`-Record, exakt
gehashte Custom-SLSA-/SPDX-Evidence, kontrollierte Erstprovisionierung,
monotoner lokaler State und vollständige Offline-Revalidierung von OCI-Layout,
Docker Config und RootFS sind implementiert. Public Visibility und
Source-Association werden beim Provisioning und Refresh geprüft, nicht bei
jedem Lauf. Fehlende oder beschädigte Evidence, Generation-/Clock-Rollback,
Revocation oder Ablauf nach höchstens 90 Tagen ergeben fail-closed
`TOOL_UNAVAILABLE`.

EBAR-04 ist auf `main` umgesetzt. Der Linux-Container-Runner verwendet den
festen akzeptierten Image-Digest, kein Netzwerk, genau zwei kontrollierte
Mounts, `--log-driver=none`, bounded Streaming sowie vollständiges
Kill-/Remove-/no-follow-Cleanup. Native Windows bleibt `TOOL_UNAVAILABLE`.

Das EBAR-05-Preflight hat im gepinnten 7-Zip-26.02-Quellcode nachgewiesen,
dass `-ba` den vom Parser v1 verlangten Archive-Header unterdrückt und ein
leeres Archiv erfolgreich 0 stdout-Bytes erzeugt. ADR-0043 akzeptiert deshalb
vor EBAR-05 das kleine Paket S-EBAR-02A mit einem additiven Member-only-Parser
v2. stderr-Prosa und grobe 7-Zip-Exitcodes bleiben ausdrücklich keine
Ursachen-Authority; nicht strukturierte Fehler werden `TOOL_FAILED`.

S-EBAR-02A ist auf `main` umgesetzt. Die anschließend vorgeschriebene reale
Golden-Prüfung hat den vorgesehenen Stop ausgelöst: Parser v2 lehnt bei
7-Zip 26.02 alle neun Formatfamilien geschlossen ab. Direkte Container liefern
formatabhängig zusätzliche, fehlende oder leere technische Felder; gzip,
bzip2, xz und zstd zeigen zunächst nur den äußeren komprimierten Stream.
ADR-0044 legt deshalb vor EBAR-05 S-EBAR-02B, FG-A-FORMAT-LOCK und
S-EBAR-02C fest. Parser v2 bleibt lesbar, ist aber kein reales
Produktionsprofil. Legacy-RAR/RAR5 werden über zwei kleine, ausdrücklich
redistribuierbare, CC0-freigegebene und hashgebundene
`ssokolow/rar-test-files`-Fixtures vermessen; alle übrigen Testdaten bleiben
synthetisch. Ein ausschließlich übersprungener PR-Gate-Lauf ist unzulässig.

S-EBAR-02B ist auf `main` umgesetzt. Das geschützte Linux-Gate hat die
wertfreie Beobachtung `archive-7zip-format-measurement/v1` für ZIP, RAR4,
RAR5, 7z, TAR sowie die vier äußeren komprimierten Streams bestätigt.
Das Review hat diese Messung jedoch als Happy-Path-only und noch nicht
lockfähig eingeordnet. Außerdem klassifizierte der damalige Messhelper
`Commented`, `Split Before` und `Split After` fälschlich als technische statt
als `VT_BOOL`-Felder, und `ArchiveFormatKind` trennte Publication Kind nicht
von der RAR4-/RAR5-/ZIP-Storage-Familie. ADR-0045 akzeptierte deshalb die neue
Folge S-EBAR-02B2, FG-A-STORAGE-FAMILY, finaler FG-A-FORMAT-LOCK und danach
S-EBAR-02C. Measurement SHA-256 `40a6ee...` und Vorabkandidat `fdebe71...`
bleiben ausschließlich diagnostisch. gzip, bzip2, xz und zstd bleiben als
Source-Beobachtung dauerhaft `OUTER_COMPRESSION_ONLY`; ADR-0051 entscheidet
ihre separate read-only Streamingstrecke.

S-EBAR-02B2 ist auf `main` umgesetzt. Das geschlossene v2-Messmanifest enthält
die vollständige 5×8-Matrix aus `MEASURED`, `FORMAT_UNSUPPORTED` und
`EVIDENCE_UNAVAILABLE`; 18 öffentliche beziehungsweise synthetische Fixtures
decken die akzeptierten direkten Fälle und die vier äußeren Wrapper ab. Die
Klassifikation behandelt `Commented`, `Split Before` und `Split After` als
strikte `VT_BOOL`-Felder und verwirft positive private Linkziele ohne deren
Werte zu serialisieren. Zwei reale Messläufe mit dem gelockten 7-Zip-Image und
die eingecheckte Erwartungsdatei sind byteidentisch; ihr SHA-256 ist
`da01ed9108a5ea63097cd1894aa4fbb264f658d65a833e8db3cb526180f2d266`.
Der geschützte Workflow misst dieselben Fixturebytes zweimal und vergleicht
beide Resultate mit der eingecheckten Erwartung. PR #154 wurde mit normalem
Merge-Commit integriert; Quality-, Recipe-, Publish- und Post-Merge-Gates sind
grün.

FG-A-STORAGE-FAMILY ist durch ADR-0046 entschieden, unabhängig geprüft und auf
`main` integriert.
`archive-signature-observer/v2` trennt Publication Kind
`NONE/EPUB/CBZ/CBR`, direkte Storage Family
`ZIP/RAR4/RAR5/SEVEN_Z/TAR/UNKNOWN` und äußere Kompression
`NONE/GZIP/BZIP2/XZ/ZSTD`. Suffixe liefern Publication- und normalisierte
Suffix-Evidence, aber niemals Storage-Authority; Signaturebytes liefern
ausschließlich Storage oder äußere Kompression.
Widersprüche bleiben `SIGNATURE_SUFFIX_MISMATCH`; Wrapper behalten als
Source-Beobachtung Storage `UNKNOWN`. Profil v1 bleibt legacy-read-only und
darf keinen neuen Runtimelauf autorisieren.

FG-A-FORMAT-LOCK ist durch ADR-0047 entschieden. Der kanonische
`archive-7zip-format-lock/v1` bindet alle 40 Capability-Zellen, 21 geordnete
Recordprojektionen, Measurement-, Fixture-, Image-, Tool-, Command-,
Signatur- und Compatibility-Identitäten. Sein SHA-256 ist
`4270fbf6ba7782c3b2fb1025137581ce07a1bc271664e19692dce388a617e061`.
Der geschützte Workflow verifiziert Lock und getrennten Digest ausschließlich
read-only.

S-EBAR-02C und EBAR-05 sind auf `main` umgesetzt. Der Produktionsparser bindet
die direkten `MEASURED`-Zellen exakt an den finalen Lock; der Provider führt
unverschlüsseltes Listing und Integrity mit getrennten Executions aus,
verwirft Rawstreams und startet für Wrapper oder nicht autorisierte Zellen
keinen Lauf. Der öffentliche Provider-Outcome bleibt locatorfrei.

FG-A-EXTRACTION-LIFECYCLE ist durch ADR-0048 entschieden. Die Prüfung des
aktuellen Runners hat gezeigt, dass er Output vor einer Extraction-
Revalidierung bereinigt und sein bisheriges `verify_after_run` einen leeren
Output verlangt. Außerdem verwirft die öffentliche EBAR-05-Projektion die für
listed/extracted- und CRC-Prüfung notwendigen privaten Werte. Deshalb folgen
vor EBAR-06 zuerst S-EBAR-05A mit einem underscore-internen Handoff desselben
Listing-/Integrity-Laufs, S-EBAR-06A mit dem reinen internen
Extraction-Validator, FG-A-EXTRACTION-QUOTA für einen atomar durchgesetzten
neutralen Workspace-Cap, S-EBAR-04Q für dessen Provider-/Capability-Vertrag,
ein reales Plattformadapter-Gate und erst danach S-EBAR-04A mit einem privaten synchronen
Workspace-Consumer zwischen bewiesener Container-Abwesenheit und Runner-owned
Cleanup. Polling beendet früh den Prozessbaum, ist aber kein Ersatz für den
harten Cap; vorläufige Hashes werden erst nach Cleanup, leerer
Slot-Revalidierung und erfolgreichem Return freigegeben. Unsichere Slots werden
quarantänisiert. EBAR-06 bleibt auf direkte
unverschlüsselte ZIP-/RAR4-/RAR5-/7z-/TAR-Fälle beschränkt. gzip, bzip2, xz
und zstd besitzen nach S-EBAR-W03 einen getrennten read-only Providerlauf,
erhalten aber weiterhin keinen Extraction-Lauf.

FG-A-WRAPPER-PIPELINE und S-EBAR-W01 bis S-EBAR-W04 sind abgeschlossen. Die
vier Wrapper verwenden ausschließlich read-only TAR-Streaming ohne
Zwischen-Datei: feste äußere Dekompression, bounded TAR-Rahmenprüfung und
getrennte innere Listing-/Integrity-Läufe mit identischer Bytelänge und
SHA-256. Extraction-Handoff, Persistenz und Writes bleiben gesperrt.

FG-A-PERSISTENCE ist durch ADR-0052 und S-EBAR-07 vollständig umgesetzt. Die
additive Migration `0019_archive_evidence` erhält fünf dedizierte insert-only
Tabellen für
Archive-, Source-, Execution-, Member- und optionale Wrapper-Lineage. Der
Store bindet vollständige Sourcehashes, Tool-/Parser-/Formatlockprofile,
vollständige Signature-/Suffix-/Parserfall-Achsen, Wrapper-Innenstream und
bestehendes ScanRoot-Fencing. Fehler-Snapshots bleiben
auditierbar, maskieren aber keinen älteren exakt kompatiblen Erfolg.
FG-A-COLLECTION-ORCHESTRATION ist durch
[ADR-0053](../decisions/ADR-0053-restartable-archive-collection-orchestration.md)
abgeschlossen. S-EBAR-08A bis 08D setzen als vier kleine Wellen Models/Store,
den stabilen Multi-Volume-Plan, Lease/Fencing, Heartbeat, stale Resume,
bounded Ausführung und den path-freien read-only Status mechanisch um.
S-EBAR-08A ist mit Migration `0020`, geschlossenem Store und Fencing auf
`main` abgeschlossen; S-EBAR-08B hat den restartbaren Plan versiegelt und
S-EBAR-08C die bounded Ausführung mit Reuse, Heartbeat und Resume umgesetzt.
S-EBAR-08D ergänzt den strikt read-only geöffneten, bounded aggregierenden und
path-/locator-/hash-/secret-freien Statusbericht. EBAR-09 synchronisiert den
Abschluss und den Übergang. [ADR-0054](../decisions/ADR-0054-archive-aware-matching-frontier.md)
schließt FG-A3-MATCHING: Die belegbare generische Archive-Source-Beziehung
wird als Consolidation-Dependency projiziert; Member-/File-Identity bleibt
ohne vollständige Member-SHA-256 `UNKNOWN`. S-EBA3-01 implementiert als
nächste kleine Welle ausschließlich den reinen Source-Dependency-Vertrag.
Extraction, Secretkanal und Source-Mutation bleiben gesperrt.

`archive-tar-stream-frame/v1` validiert den
inneren TAR-Strom inkrementell in 512-Byte-Blöcken, begrenzt Chunk-, Stream-,
Header- und Payloadmengen, verlangt gültige Headerchecksummen sowie mindestens
zwei Endblöcke und weist partielle, verkettete oder nichtnull nachlaufende
Streams ab. Drei feste no-shell Commands definieren äußere stdout-
Dekompression und innere TAR-Listing-/Integrity-Läufe über stdin. Der bounded
Duplex-Broker führt die getrennten Containerläufe mit Backpressure und
vollständigem Cleanup aus; der Provider bindet beide Ergebnisse an dieselbe
innere Bytelänge und denselben SHA-256.

S-EBAR-05A und S-EBAR-06A sind auf `main` umgesetzt. Der private Handoff
bindet Locator, CRC und Memberidentität an denselben EBAR-05-Lauf; der reine
Extraction-Validator prüft Workspaceprojektion, Größen, CRC, SHA-256,
Deadline und Keine-Partial-Evidence ohne Tool- oder Filesystemauthority.

FG-A-EXTRACTION-QUOTA ist durch ADR-0049 entschieden. S-EBAR-04Q implementiert
den dateisystemneutralen Provider-, Lease-, Capability-,
Empty-Revalidation-, Return- und Quarantänevertrag. Die feste
Adapter-Allowlist ist leer; damit kann dieses Paket allein kein reales Backend
freigeben. Direkte Konstruktion, Kopie, Serialisierung, fremder Return,
Überschreitung von zwei Leases, ungültige Attestation und fehlgeschlagener
Return werden geschlossen abgewiesen beziehungsweise quarantänisiert.

[ADR-0050](../decisions/ADR-0050-linux-docker-workspace-backend-unavailable.md)
schließt FG-A-WORKSPACE-BACKEND als negative, fail-closed Entscheidung ab.
Bind-Mount, Docker-Layer, `tmpfs` und eine nicht konkret live attestierte
Linux-Quota belegen den kombinierten Byte-, Objekt-, Reserve- und
Consumer-Lifecycle nicht vollständig. Die Adapter-Allowlist bleibt leer.
FolioTone erhält weder `root` noch `CAP_SYS_ADMIN`, Device- oder Mountzugriff;
kein Dateisystem und FIEMAP werden Kernvoraussetzung. S-EBAR-04A und EBAR-06
bleiben bis zu einem späteren erfolgreichen
FG-A-WORKSPACE-BACKEND-REVALIDATION auf einem echten Linux-/Docker-
Conformancehost `TOOL_UNAVAILABLE`.

Fokussiert verifiziert wurden 18 Unit-Tests sowie Ruff und Mypy nur für den
neuen Scope; der vollständige Gate läuft genau einmal am stabilen PR.

Die spezialisierte Runtime darf anschließend ausschließlich unverschlüsselte
Archive über bounded Streaming ohne Raw-Artefakt oder Preview verarbeiten.
Reale Passwortversuche bleiben bis zu einem separaten FG-A-SECRET mit
belegtem Helper-/Pipe-/Handle-Vertrag `SECURE_CHANNEL_UNAVAILABLE`. Dieser
Archive-Slice autorisiert unabhängig davon keine W10-Operation; die spätere
enge Ausnahme steht ausschließlich in ADR-0056.
Der erste Runtimebackend ist `archive-linux-container-runner/v1` für die
primäre Docker/Linux-Runtime. Er verwendet ausschließlich ein
digest-gepinntes Image mit verifizierter eingebetteter `7zzs`-26.02-Identität,
opaque privates Input-Staging statt eines ScanRoot-Mounts und eine getrennte
Output-Sandbox. Native Windows-Ausführung bleibt `TOOL_UNAVAILABLE`, bis
`FG-A-WINDOWS-SANDBOX` Netzwerk- und Filesystemisolation nachweist; Job
Objects und Handle-Allowlisten allein genügen nicht.

ADR-0036 akzeptiert Open Library als ersten realen, optionalen und begrenzten
Book Provider. Der Vertrag erlaubt nur feste JSON-Endpoints für `Work`,
`Edition`, referenzierte `Author`-Records, ISBN, OCLC/LCCN und einen auf zwei
Seiten begrenzten Titel-plus-resolved-Author-Fallback. Ein identifizierender
`User-Agent`, genau ein Request pro Sekunde, Concurrency 1, feste Timeouts und
Responsegrenzen sowie ein strikt normalisierter Minimal-DTO-Cache sind
verbindlich. Rohantworten, reale Response-Fixtures, Archive.org-Inhaltszugriff
und Open Library als Collection- oder Bulk-Backend bleiben verboten; größere
Mengen wechseln nach einem getrennten Gate zu den offiziellen Monats-Dumps.
Die Open-Library-Lizenzseite begründet keine Redistribution einzelner
Beiträge, weshalb v1 ausschließlich private normalisierte Cache-Daten mit
bounded Retention zulässt.

EB-03B ist mit S-EB03B-01 bis S-EB03B-08 abgeschlossen. Der bounded
Open-Library-Vertical-Slice verwendet ausschließlich die festgelegten
JSON-Routen, einen identifizierenden `User-Agent`, Concurrency 1, die
Transport- und Payload-Grenzen aus ADR-0036 sowie normalisierte
`openlibrary-source-record/v2`-Cache-DTOs. Die Provider-/Cache-Matrix deckt
Fresh-Hit, Offline-Hit/Miss, negative und technische Failure-TTLs,
Mapping-Reanalyse ohne Refetch, getrennte v1/v2-Keys und die
`BULK_DATASET_REQUIRED`-Schwellen ab. Query, Cache, Fehler und Reports bleiben
frei von lokalen Pfaden, Filenames, Rohantworten, Inventaren und nicht
freigegebenen Archive.org-/Cover-/Availability-Daten. Es wurden ausschließlich
synthetische Daten und Fake-Transporte verwendet; es gab keinen Live-
Netzwerkzugriff und keine Runtime- oder Source-Media-Änderung.

ADR-0035 legt für den künftigen Provider Cache den kanonischen
`provider-cache-entry/v1`-Vertrag fest: Result-Status, Payload-Kind,
Freshness-Triade, getrennte Source-/Mapping-Keys, Negative-Cache-Regeln,
Mapping-Reanalyse ohne Refetch, generation-gefencetes CAS und bounded
Retention. Das Gate autorisiert weiterhin keinen realen
Provider und keinen Netzwerkzugriff; S-EB03A-01 bis S-EB03A-09 wurden in dieser Welle
mit rein synthetischen Tests abgeschlossen.

**Abgeschlossene Voraussetzung: EB-08 — nicht ausführbarer ConsolidationPlan**

ADR-0034 ist vollständig umgesetzt. `foliotone.consolidation` liefert
immutable `ConsolidationPlan`-DTOs, `canonical-json/v1`, reine
Precondition-/Blocker-Builder, die reviewpflichtige Keep Preference, Migration
`0016`, insert-only Persistenz, den deterministischen pfadfreien Report
`ebook-consolidation-report` und einen statischen Non-Execution-Gate-Test
gegen Filesystem-Mutationen, mutierende Calibre-Command-Shapes und öffentliche
Ausführungssurfaces. W9 ist damit `DONE`; jeder Plan bleibt dauerhaft
`NOT_EXECUTABLE`.

**Abgeschlossene Voraussetzung: EB-07 — persistierte read-only Calibre Library Reconciliation**

Das Frontier-Gate ADR-0033 legt feste lokale read-only
`calibredb`-Command-Shapes, Snapshot-Konsistenz, Calibre-Ownership,
Sidecar-Evidence und die Finding-Fälle A bis G fest. S-EB07-01 bis S-EB07-08
implementieren die synthetischen Adapter-, Snapshot-, Persistenz- und
Mapper-Verträge. S-EB07-09 ergänzt den SELECT-only
`SQLiteCalibreLibraryReportReader`, den pfadfreien Report
`calibre-reconciliation-report/v1` und die CLI
`calibre-reconciliation-report`. Die CLI verwendet ausschließlich eine
SQLite-Read-only-Verbindung; sie führt keine Migration, keine Calibre-
Capture und keine schreibende Operation aus.

Die Persistenz-, Report- und read-only Capture-Strecke von EB-07 ist damit
abgeschlossen. Der Capture-Service erwirbt die `EBOOK_ANALYSIS`-Lease, bindet
den neuesten abgeschlossenen EBOOK-Scan und persistiert den terminalen
Snapshotgraphen atomar. EB-08, die Archivstrecke und die W10-Sperre bleiben
unverändert.

Die langfristige Produktausrichtung und Medienfolge wurden als ausdrücklich
nicht statussetzender Entwurf in
`docs/vision/EVIDENCE_DRIVEN_COLLECTION_INTELLIGENCE.md` und
`docs/planning/FUTURE_CAPABILITY_MAP.md` konsolidiert. Der Entwurf ändert
weder die EB-Reihenfolge noch die W10-Sperre.

Der langfristige Entwurf umfasst jetzt zusätzlich portable Objekt-Lineage und
den bounded, idempotenten Austausch zwischen mehreren FolioTone-Systemen.
ADR-0042 ist `Proposed`; FUT-010 bleibt deshalb `DECISION`. Vorgesehen sind
getrennte Frontier-Gates für Knoten-/Objektreferenzen, Austauschpaket,
Merge-/Trust-/Conflict-Regeln und read-only Kennzeichnungsträger. Es wurde
keine Persistenz, kein Export/Import, kein Sync und kein Kennzeichnungs- oder
Calibre-Write implementiert. Die aktive E-Book-/Archive-Reihenfolge sowie die
W10-Sperre bleiben unverändert.

Die repositoryweite Ausführungsrichtlinie
`docs/planning/MODEL_ROUTING_POLICY.md` ordnet jeden Arbeitsschritt
vendor-neutral `LOCAL`, `ECONOMICAL`, `BALANCED` oder `FRONTIER` zu. Konkrete
Modellnamen, Preise, Kontingente und Reasoning-Bezeichner sind nur
Runtime-Eigenschaften der dünnen Tool-Adapter. Neue Waves müssen Risikoklasse,
Tier, erlaubte Dateien, Checks und Stopbedingungen vor der Implementierung
festlegen. `AI_WORKFLOW.md` definiert Branch-, Worktree-, Review-, PR- und
Handover-Ablauf; `TEST_POLICY.md` definiert die Local-first-Teststufen und den
einmaligen vollständigen PR-Gate. Historische Modellnamen in akzeptierten ADRs
und im Legacy-Dateinamen `EBOOK_SPARK_WORK_PACKAGES.md` bleiben lesbare
Ausführungsnotizen, sind für neue Läufe aber nicht normativ. Die Richtlinien
ändern keinen fachlichen Wellenstatus und autorisieren keine
Source-Media-Mutation.

**Lokale Verifikation der Agentenstrategie:** Am 2026-08-21 bestanden die
neun statischen Dokumentationsvertrags-Tests, `ruff check .` und Mypy für 182
Source-Dateien. Die relativen Links der geänderten Markdown-Dateien und
`git diff --check` waren ohne Befund. Der vollständige lokale Pytest-Lauf
endete nach 14 Minuten 8 Sekunden mit 47 Fehlern, die auf dem unveränderten
`main` reproduzierbar sind: Git wendet CRLF auf bytegehashte Archive-Evidence
an, und die Windows-Laufzeit fügt erwarteten Toolpfaden den `\\?\`-Präfix
hinzu. Die Agentendokumentation berührt weder diese Evidence noch die
Pfadbildung. Der vollständige Quality-Gate muss daher für den exakten
aktualisierten Pull-Request-Head in GitHub erneut grün verifiziert werden.

**Abgeschlossene Voraussetzung: EB-06 — versioniertes E-Book-Matching und Review**

EB-06A ergänzt mit ADR-0030 zunächst reine, relation-spezifische
Matcherprofile für `EXACT_DUPLICATE`, `SAME_EDITION` und `SAME_WORK`.
Nur gleicher vollständiger `FILE_SHA256` darf automatisch `CONFIRMED`
erzeugen. Erstmalige bibliografische Kandidaten bleiben immer
`REVIEW_REQUIRED`; harte lokale Contradictions können nicht durch Provider-
oder Tool-Agreement überstimmt werden.

EB-06B ergänzt mit ADR-0031 und Alembic `0014` insert-only
`RelationCandidate`-Snapshots und konkrete Feature-Evidence-Links. Der Store
reproduziert das Matcher-Ergebnis vor dem Insert, validiert abgeschlossene
Scan-Lineage und persistierte Evidence atomar und reiht bibliografische Fälle
in den bestehenden append-only Review-Core ein. Semantisch kompatible ACCEPT-
und REJECT-Entscheidungen können trotz neuer technischer Matcher-Version
wiederverwendet werden; DEFER bleibt reviewbar.

EB-06C schließt die Welle mit ADR-0032 und
`ebook-matching-workflow/v1` ab. Der bounded Offline-Orchestrator verarbeitet
`FILE_SHA256`, `EDITION_IDENTIFIER` und `AGENT_TITLE` ohne Source-Zugriff.
Exakte Hashgruppen werden repräsentantenbasiert statt quadratisch erweitert;
bibliografische Kandidaten bleiben reviewpflichtig. `ebook-match`,
`ebook-match-review-list` und `ebook-match-review-decide` stellen den
path-freien CLI-Vertrag für Ausführung, Explanation und optimistisch
gefencete ACCEPT-/REJECT-/DEFER-Entscheidungen bereit. Eine kanonische
`Relation`-Projektion bleibt bewusst aus, bis ein eigener Projektionsvertrag
vorliegt.

**Empirisch für EB-06A:** Der gezielte Matching-/Blocking-Verbundlauf bestand
24 synthetische Tests in 62,55 Sekunden. Er prüft vollständige Hash-
Confirmation, harte lokale Contradictions, unvermeidbares Review erstmaliger
bibliografischer Kandidaten, Übersetzungs- und Text-Fingerprint-Grenzen,
Fingerprint-Stabilität sowie den bestehenden Candidate-Blocking-Vertrag.
Ruff war für das Repository erfolgreich; Mypy prüfte 110 Source-Dateien ohne
Befund. Der vollständige Gate läuft genau einmal am Pull Request.

**Empirisch für EB-06B vor dem PR-Gate:** Der fokussierte Persistenz-,
Migrations-, Review- und Matching-Verbundlauf bestand 36 synthetische Tests in
284,37 Sekunden. Ruff war für den betroffenen Scope erfolgreich; Mypy prüfte
114 Source-Dateien ohne Befund. Es wurden keine realen Sammlungsdaten und
keine Runtime-Datenbank verwendet.

**Empirisch für EB-06C vor dem PR-Gate:** Der gezielte Workflow-, CLI-,
Blocking-, Persistenz- und Scoring-Verbundlauf bestand 30 synthetische Tests
in 182,08 Sekunden. Ruff war erfolgreich; Mypy prüfte 115 Source-Dateien ohne
Befund. Die adversarial Profile bestätigen weiterhin ausschließlich gleiche
vollständige File-Hashes automatisch.

Der kontrollierte Runtime-Cutover, die Trennung zwischen synthetischen
Entwicklungs-Gates und privatem Hintergrundlauf sowie die langfristige
book-only Fortsetzung bis W9 sind in
[`W3_017_EBOOK_ROADMAP.md`](W3_017_EBOOK_ROADMAP.md) geplant. Der Plan ändert
keinen implementierten Status und autorisiert W10 nicht.

Die damals vorgemerkte read-only Archiv- und vollständige
Deduplizierungsstrecke ist in
[`EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md`](EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md)
geplant und inzwischen bis zur read-only Source-Dependency-Planintegration
umgesetzt. Lokale Passwortkandidaten, optionale separat aktivierte
Providerrecherche und archive-aware Matching führen weiterhin ausschließlich
zu Evidence, Review und nicht ausführbaren W9-Plänen. ADR-0056 erlaubt davon
getrennt nur die Interim-Ein-Datei-Quarantäne; Purge und
Leer-Verzeichnis-Bereinigung bleiben blockiert.

Die lokalen Authority-Grundlagen aus `PR #36`, der synthetische E5-
Performance-/Restart-Vertrag aus `PR #37`, die strukturierten Provider-
Verträge aus `PR #38` und die mehrdimensionalen E-Book-Klassifikationsverträge
aus `PR #39` sind auf `main` integriert. Persistierte Authority-
Entscheidungen, Provider Cache und der begrenzte Open-Library-Adapter sind
inzwischen ebenfalls umgesetzt; weitere Provider bleiben geplant.

ADR-0026 ist durch S-EB00-01 bis S-EB00-04 umgesetzt. `ProviderAccessMode`
trennt die vier Zugriffsarten aus ADR-0009 vom unabhängigen
`ProviderCachePolicy`-Vertrag. Descriptor, Response und synthetischer Provider
verwenden die getrennten Dimensionen; Privacy-DTOs geben `access_mode` und
`cache_policy` aus. `KnowledgeProviderMode` bleibt ohne Runtime-Warnung nur als
deprecated Eingabe der eindeutigen Legacy-Abbildung importierbar. W5B-001 ist
damit `DONE`; Provider-Cache-Laufzeit und reale Provider bleiben Gegenstand der
folgenden E-Book-Wellen.

W0 bis W2 sind abgeschlossen. Der Incremental Index, die generische read-only ToolProvider Runtime, Filename-/Path-Kandidaten und versionierte Parsing-Profile wurden vollständig lokal geprüft. `W2-011` ergänzt begrenzte strict-JSON-Auswertung persistierter Tool-Artefakte und eine konservative Reanalyse-Entscheidung. Der Docker-Build-Kontext ist durch eine allowlist-basierte `.dockerignore` auf die tatsächlich paketierten Anwendungsdateien begrenzt.

Die anfängliche Produktoberfläche bleibt auf ausdrückliche Benutzerentscheidung
ausschließlich die CLI. ADR-0016 dokumentiert diese Grenze. `W3-001` bewertet
calibre, EPUBCheck, Poppler und qpdf; `W3-002` implementiert die erste feste,
read-only `ebook-meta`-Befehlsform. `W3-003` ergänzt feste EPUB-
Textextraktion und einen FolioTone-eigenen normalisierten Text-Fingerprint.
`W3-004` ergänzt feste Poppler-PDF-Metadaten-, Seiten- und Textpfade mit
explizitem `NO_TEXT`. `W3-005` erweitert den unveränderlichen calibre-
Analysepfad ohne nativen Formatparser auf MOBI, AZW und AZW3. `W3-006` ergänzt
rohe OPF2-/OPF3-Beobachtungen und provider-neutrale, gruppierte
Metadatenkandidaten mit exakten `ToolExecution`-/`FileObservation`-Links.
`W3-007` ergänzt einen versionierten synthetischen Vergleichskorpus für
Datei-, Inhalts-, `Edition`-, `Work`- und Tool-Disagreement-Ground-Truth.
`W3-008` ergänzt feste read-only EPUBCheck-JSON-Validierung, einen neuen
`STRUCTURAL_VALIDATION`-Evidence-Vertrag und provider-spezifische akzeptierte
Exitcodes. `W3-009` ergänzt optionale, quellisolierte Embedded-Cover-
Extraktion für EPUB/MOBI/AZW/AZW3, explizites `NO_EMBEDDED_COVER` und einen
FolioTone-eigenen versionierten `EBOOK_COVER_DHASH`. `W3-010` ergänzt den
formatbewussten CLI-Workflow `ebook-analyze` mit getrennten Schritt- und
Gesamtzuständen. `W3-011` ergänzt exakte, integritätsgeprüfte Evidence-
Wiederverwendung, gezielten Schritt-Retry und `--fresh`. `W3-012` ergänzt die
separate, mehrdimensionale Projektion `ebook-quality/v1` mit festen
Befundcodes. `W3-013` ergänzt `ebook-comparison/v1` und den read-only CLI-
Paarvergleich persistierter Datei-, Text-, Metadaten-, Struktur- und Cover-
Evidence ohne Relation oder Identitätsurteil. Auf Benutzerentscheidung bleibt
die aktive Entwicklung bei E-Books. `W3-014` ergänzt den synthetischen v2-
Edge-Korpus sowie begrenzte, indexgestützte Evidence-Abfragen. `W3-015`
ergänzt einen fortsetzbaren Collection Batch mit persistentem Snapshot-Plan,
Lease, begrenzten Workern und per-File-Fehlerfortsetzung. `W3-016` ergänzt
deterministische private JSON-/CSV-Sammlungsberichte, persistierte
Befundprovenance und begrenzte Duplicate-/Varianten-Review-Kandidaten.
`W3-017` ist `DONE`: inkrementelle Scan-/Hash-Persistenz wurde aus dem
realen Pilot gehärtet, heterogene Pilotpläne und selektives vollständiges
Hashing von Quick-Duplikatkandidaten sind implementiert. Neue `ScanRun`-Leases
mit Heartbeats und expliziter stale-`RUNNING`-Recovery schließen die im realen
Lauf beobachtete Lücke nach einem externen harten Prozessabbruch.
Für E5 wurden zusätzlich synthetische Skalierungs- und Restart-Vertragsfälle ergänzt:
genau eine Kandidatenmaterialisierung je Invocation, indexgestützte
`EXPLAIN QUERY PLAN`-Prüfung und getrennte Messung von Auswahllaufzeit,
Hashing-I/O und Commitzeit.
W3-017 sowie E1 bis E5 sind abgeschlossen. E6 bis E12 bleiben davon
getrennte langfristige book-only Folgewellen; der vollständige private
Sammlungslauf bleibt betriebliche Arbeit und ändert diesen Status nicht.
Music-Welle W4
bleibt geplant und zurückgestellt.

EB-01/E4 ergänzt mit ADR-0027 und Alembic `0012` einen dauerhaften
`ScanRoot`-Write-Lease-Slot mit monotoner Fence-Epoch. Scanner,
Kandidaten-Hashing, Collection-Analyse und einzelne E-Book-Analyse können für
denselben Root nicht mehr gleichzeitig legitim schreiben. Root-Fence,
Run-Fence und Fachdaten liegen in derselben SQLite-Transaktion; stale Writer
können nach einer Übernahme weder Fingerprints, Scanstatus, Missing-/Deleted-
Übergänge, Relocation- noch Analyse-Evidence committen. Keeper schützen lange
Hash- und Analysearbeit, ohne Datenbanktransaktionen offen zu halten. Die
Migration verweigert Upgrade oder Downgrade bei aktiven Writern.

EB-02 ergänzt mit ADR-0028 und Alembic `0013` persistierte book-only
`ResolutionCandidate`-Snapshots, konkrete Evidence-Links, generische
`ReviewItem`-Datensätze und append-only ACCEPT-/REJECT-/DEFER-Entscheidungen.
Erstmalige Kandidaten bleiben immer reviewpflichtig. Nur eine semantisch exakt
kompatible frühere ACCEPT-Entscheidung darf AUTO_SAFE wiederverwendet werden;
REJECT unterdrückt den unveränderten Fall und DEFER bleibt reviewbar. Source
Evidence, kanonische Metadaten und Source Media bleiben unverändert.

EB-05 ergänzt mit ADR-0029 begrenzte, read-only `CandidateBlock`-Projektionen
für vollständige File-Hashes, Edition-Identifier, akzeptierte Edition-, Work-
und Series-Resolution, Agent/Titel sowie normalisierte Textfingerprints.
Große Blocks erhalten `SECONDARY_REQUIRED`; exakte File-Duplikate werden als
bounded Group mit Representative statt als quadratische Paarliste dargestellt.
Book-only Relation Contracts fixieren Endpoint-Ebene, Identity-Effekt und
erforderliche Evidence-Codes. Es gibt weder neue Persistenz noch Migration,
Scoring, automatische Relation oder Source-Media-Zugriff.

## Implementierter W2-Slice

### Incremental Index

Implementiert sind:

- persistente logische `ScanRoot`-Identitäten mit eindeutigem Namen;
- `ScanRun`-Lifecycle mit `RUNNING`, `COMPLETED`, `FAILED` und `INTERRUPTED`;
- streaming-basierte Filesystem Discovery über `os.scandir` ohne collection-weite Pfadliste im Speicher;
- `FileRecord`, `FileObservation` und auditierbare `FileScanEvent`-Einträge;
- Zustände `NEW`, `UNCHANGED`, `MODIFIED`, `MISSING`, `REAPPEARED` und opt-in `DELETED`;
- Schutz vor falschem `MISSING`, wenn ein `ScanRoot` nicht verfügbar ist;
- `MISSING` bleibt ausdrücklich von `DELETED` getrennt;
- begrenzte Batch-Verarbeitung mit maximal 500 Dateien je Batch;
- read-only Scan-CLI `foliotone scan` für kontrollierte Smoke-Tests;
- persistente `FileRelocationCandidate`-Records für konservative Move-/Rename-Kandidaten;
- explizite Resume-Lineage über `ScanRun.resumed_from_run_id` und CLI `--resume-run`.

`MOVED` und `RENAMED` bleiben als `FileChangeState`-Vokabular reserviert. W2-006 emittiert diese Werte nicht als bestätigte Scan-Zustände, sondern speichert getrennte Relocation-Kandidaten.

### `DELETED`-Bestätigung

`W2-004` implementiert `DeletionConfirmationPolicy` als konservative, ausdrücklich zu aktivierende Policy. Eine Datei wird nur dann als `DELETED` klassifiziert, wenn gleichzeitig:

1. eine konfigurierte Mindestanzahl aufeinanderfolgender erfolgreicher Scans die Datei als `MISSING` bestätigt hat; die Policy akzeptiert mindestens 2 Scans;
2. eine konfigurierte Mindestdauer seit Beginn dieser aktuellen Abwesenheitsserie verstrichen ist.

Die Policy besitzt bei expliziter Konstruktion die Defaultwerte drei erfolgreiche `MISSING`-Scans und 24 Stunden. Die CLI aktiviert die Bestätigung jedoch nicht automatisch. Dafür stehen die Optionen `--confirm-deleted-after-missing-scans` und optional `--confirm-deleted-after-hours` zur Verfügung.

`FileRecord.missing_since_at` und `FileRecord.consecutive_missing_scans` halten den aktuellen Abwesenheitszustand persistent. Failed oder interrupted Scans erhöhen die Serie nicht. Nach bestätigtem `DELETED` wird bei fortbestehender Abwesenheit nicht in jedem Scan erneut ein `DELETED`-Event erzeugt. Taucht derselbe relative Pfad später wieder auf, entsteht `REAPPEARED`, der Zustand wird auf `PRESENT` zurückgesetzt und die Abwesenheitsserie gelöscht.

`DELETED` ist ausschließlich eine Indexklassifikation. Die Funktion löscht, verschiebt, benennt oder verändert keine Source-Media-Datei. ADR-0013 dokumentiert diese Entscheidung verbindlich.

### Move-/Rename-Kandidaten

`W2-006` implementiert `FileRelocationCandidate` als zusätzliche, nicht kanonische Evidence. Ein Kandidat entsteht nur zwischen zwei weiterhin getrennten `FileRecord`-Datensätzen desselben `ScanRoot`, wenn im selben erfolgreichen Scan:

- die Source erstmals `MISSING` wird (`consecutive_missing_scans == 1`);
- das Target `NEW` ist;
- die letzte prior Source-Observation und die aktuelle Target-Observation denselben unterstützten versionierten File-Fingerprint besitzen;
- der jeweilige Fingerprint-Block genau eine Source und genau ein Target enthält.

Unterstützt werden zunächst `QUICK_FILE` und `FILE_SHA256`. Wenn beide dasselbe eindeutige Paar stützen, wird `FILE_SHA256` als stärkere technische Evidence im Kandidaten referenziert. Der Kandidat verweist auf die konkreten Source-/Target-`Fingerprint`-IDs sowie Algorithmus und Version.

One-to-many-, many-to-one- und many-to-many-Blöcke werden nicht automatisch aufgelöst. Ebenso werden ältere `MISSING`-Records nicht rückwirkend mit später auftauchenden Dateien verknüpft. Das verhindert willkürliche Zuordnungen bei echten identischen Kopien.

`RelocationCandidateKind` beschreibt nur die Pfadform:

- `RENAMED`: gleicher Parent-Pfad, anderer Dateiname;
- `MOVED`: anderer Parent-Pfad, gleicher Dateiname;
- `MOVED_AND_RENAMED`: Parent-Pfad und Dateiname verändert.

Source bleibt `MISSING`, Target bleibt `NEW`; es findet weder ein Identity Merge noch eine Source-Media-Operation statt. ADR-0014 dokumentiert diese Entscheidung verbindlich.

### Interrupt/Resume

`W2-007` modelliert ein Resume als neuen `ScanRun` mit `resumed_from_run_id`. Ein Run kann nur dann als Resume-Quelle verwendet werden, wenn er persistent existiert, Status `INTERRUPTED` besitzt und zum selben `ScanRoot` gehört. `COMPLETED`, `FAILED`, `RUNNING` oder fremde Roots werden abgelehnt.

ADR-0025 ergänzt den Crash-Recovery-Vertrag. Neue `RUNNING`-Läufe besitzen
eine 30-Minuten-Lease, die vor und nach begrenzten Scannerphasen erneuert wird.
`--recover-stale-running` darf ausschließlich den neuesten ungeleasten oder
abgelaufenen Lauf desselben `ScanRoot` atomar auf `INTERRUPTED` setzen und ihn
anschließend über einen neuen Run fortsetzen. Eine aktive Lease blockiert die
Recovery. Vor dem expliziten Aufruf muss betrieblich geprüft sein, dass der
frühere Prozess nicht mehr aktiv ist.

Resume öffnet den unterbrochenen Run nicht erneut. Der neue Run führt die streaming-basierte Discovery erneut vollständig aus. Das vermeidet einen nicht portablen persistenten `os.scandir`-Cursor. Bereits vor dem Interrupt verarbeitete unveränderte Dateien liegen jedoch als `FileRecord` und Fingerprint persistent vor; beim Resume werden sie als `UNCHANGED` erkannt und deshalb nicht erneut gehasht. Noch nicht erreichte Dateien werden normal verarbeitet.

Die `MISSING`-/`DELETED`-Phase läuft weiterhin erst nach erfolgreicher vollständiger Discovery. Ein unterbrochener Run kann dadurch weder nicht erreichte Dateien als `MISSING` markieren noch eine Deletion-Bestätigungsserie erhöhen. Die CLI verwendet `--resume-run <ScanRunId>`. ADR-0015 dokumentiert diese Entscheidung verbindlich.

### Hashing

Implementiert sind:

- gestuftes `HashMode.NONE`, `QUICK` und `FULL`;
- Quick Fingerprint über Dateigröße sowie begrenzte Head-/Tail-Bereiche;
- vollständiges SHA-256 als Streaming-Hash mit begrenztem Speicherverbrauch;
- Fingerprints werden gegen die konkrete `FileObservation` gespeichert;
- unveränderte Dateien werden nicht unnötig erneut gehasht;
- NEW, MODIFIED und REAPPEARED können neu fingerprinted werden.

### Filename- und Path-Context-Kandidaten

`W2-008` implementiert einen bewusst kleinen, versionierten Basisvertrag für abgeleitete `FieldCandidate`-Werte. Die Komponenten setzen keine kanonischen Metadaten und interpretieren noch keine sammlungsspezifischen Namenskonventionen; diese Regeln gehören zu `W2-009`.

- `FilenameParser` akzeptiert genau einen Dateinamen ohne Pfadseparatoren und erzeugt aus dessen Stem einen `title`-Kandidaten mit `source_location = filename.stem` und Confidence `0.2`.
- `PathContextAnalyzer` akzeptiert ausschließlich sichere, `ScanRoot`-relative Pfade, normalisiert Windows- und POSIX-Separatoren und erzeugt aus dem direkten Parent einen `path_context`-Kandidaten mit `source_location = path.parent` und Confidence `0.1`.
- Jeder Kandidat enthält `Provenance` mit `source_kind = derived`, Komponentenname, Beobachtungszeitpunkt und expliziter Parser-Version. Absolute oder Traversal-Pfade werden abgewiesen; absolute Hostpfade werden dadurch nicht als Kandidateninhalt oder Source Location weitergegeben.

`W2-009` ergänzt `FilenameParsingProfile`, geordnete `FilenameParsingRule`-Regex-Regeln und `RuleBasedFilenameParser`. Die erste vollständig passende Regel erzeugt Kandidaten aus benannten Capture Groups. Profilversion, Regelname, Confidence und Source Location bleiben erhalten; ohne Treffer wird kein Wert geraten. Synthetische Tests decken Autor/Titel, Serie/Band, Track/Disc, Jahr und Sprache ab.

### Generische ToolProvider Runtime

Implementiert sind:

- lokale Tool-Ausführung ohne Shell;
- Tool-Versionsermittlung;
- Timeouts und Cancellation;
- auditierbare FAILED-Ausführung bei fehlendem Tool oder einem vom Adapter nicht
  akzeptierten Exitcode; standardmäßig wird ausschließlich `0` akzeptiert;
- file-backed stdout/stderr mit `ToolArtifact`, Größe und SHA-256;
- begrenzte stdout/stderr Previews;
- begrenzte, strikt als UTF-8 JSON validierte Auswertung eines persistierten stdout-`ToolArtifact` einschließlich Size-/SHA-256-Integritätsprüfung;
- `StructuredOutputError` bei fehlender, zu großer, veränderter oder malformed strukturierter Ausgabe, ohne eine erfolgreiche Prozessausführung rückwirkend umzudeuten;
- konservative `requires_reanalysis`-Entscheidung: Wiederverwendung ist nur bei erfolgreicher vorheriger Ausführung und exakt gleicher Provider-, Capability-, Input-, Tool-, Adapter- und expliziter Konfigurationsidentität zulässig;
- Ablehnung absoluter lokaler Pfade als persistierte `ToolExecution.input_identity`;
- gehärtete Docker-Argumente für ToolProvider mit read-only Container-Dateisystem, `cap-drop=ALL`, `no-new-privileges` und standardmäßig deaktiviertem Netzwerk;
- ausschließlich read-only Input-Mounts und separatem beschreibbarem Work-Verzeichnis.

Der W3-Slice ergänzt deklarierte, begrenzte Workspace-Ausgaben und eine
Adapter-Version-Policy vor dem Öffnen von Source Media. Konkrete ffprobe-,
fpcalc-, beets-, SongKong- oder Picard-Adapter sind noch nicht implementiert.

### Persistence

Die W1-Persistence wurde bisher über neun zusätzliche Alembic-Revisionen
erweitert. Bereits gemergte Migrationen werden nicht rückwirkend verändert.

`0002_incremental_index` ergänzt insbesondere `file_scan_events`, `tool_artifacts`, Scan-/Tool-relevante Indizes und eindeutige logische `ScanRoot.name`-Werte.

`0003_deletion_confirmation` ergänzt `file_records` um `missing_since_at` und `consecutive_missing_scans`.

`0004_relocation_candidates` ergänzt `file_relocation_candidates` sowie Indizes für Run- und Source-/Target-Abfragen.

`0005_scan_resume_lineage` ergänzt `scan_runs.resumed_from_run_id` als nullable selbstreferenzierende Foreign-Key-Lineage sowie einen Query-Index.

`0006_ebook_evidence_lookup_indexes` ergänzt drei additive Indizes für
zielgerichtete `ToolExecution`-, `ToolResult`- und `Fingerprint`-Abfragen des
E-Book-Paarvergleichs. Bestehende Domain-Datensätze werden nicht umgeschrieben.

`0007_ebook_collection_batches` ergänzt `ebook_collection_runs` und
`ebook_collection_items` sowie Indizes für Root-/Status- und
Run-/Status-/Ordinal-Abfragen. Die Batch-Tabellen speichern Observation-IDs,
Lifecycle und begrenzte Zähler, aber keine Pfade oder Metadatenwerte.

`0008_ebook_collection_reports` ergänzt geordnete Item-Ausführungs- und
Quality-Befundprojektionen einschließlich exakter `ToolExecution`-Quellen
sowie den belegten Fingerprint-Gruppierungsindex. Die Tabellen speichern keine
Source-Pfade, Metadatenwerte oder extrahierten Inhalte.

`0009_scan_run_leases` ergänzt `scan_runs.lease_token`,
`scan_runs.lease_expires_at` und den Root-/Status-/Lease-Index. Bestehende
terminale Läufe bleiben nullable; ein vor der Migration verwaister
`RUNNING`-Lauf wird dadurch ausdrücklich wiederherstellbar.

`0010_candidate_hash_lookup_index` ergänzt den gemessenen profilierten
Fingerprint-Lookup für das selektive Vollhashing. Die Kandidatenabfrage
schränkt zuerst auf den aktuellen Scan ein und materialisiert die konsistenten
Quick-Gruppen einmal pro Invocation in einer verbindungslokalen Temp-Tabelle,
statt die historische Fingerprint-Tabelle für Statistik, jeden Batch und den
Abschluss erneut zu aggregieren.

`0011_candidate_hash_run_leases` ergänzt persistente
`ebook_candidate_hash_runs` mit genau einem aktiven Lauf pro `ScanRoot`.
Run-ID, Phase, Heartbeat-/Lease-Zeitpunkte und begrenzte Zähler bleiben
pfadfrei. Ein separater Keeper erneuert die Lease während langer Hashes;
Fingerprint-Insert und Fortschritt eines Batches werden in derselben durch
Token, Status und Ablaufzeit gefenceten Transaktion persistiert. Ein stale
Vorgänger kann nach atomarer Übernahme keine Evidence mehr schreiben. Die
read-only CLI `ebook-hash-status` liest den neuesten Zustand ohne Migration
oder Source-Zugriff.

Beim Upgrade einer bestehenden `0002`-Datenbank wird keine historische Abwesenheitsdauer oder Bestätigungsserie erfunden. Bestehende Datensätze beginnen konservativ mit `missing_since_at = NULL` und `consecutive_missing_scans = 0`; erst nachfolgende erfolgreiche Scans bauen neue Bestätigungsevidenz auf.

## Implementierter W3-Slice

### Aktuelle E-Book-Toolbewertung

Die Toolauswahl wurde am 2026-08-15 für `W3-009` erneut geprüft:

- calibre 9.13.0 wird für dateibezogene Metadaten sowie die
  EPUB/MOBI/AZW/AZW3-Text- und Embedded-Cover-Extraktion wiederverwendet;
- Pillow 12.3.0 übernimmt die begrenzte Rasterdekodierung und
  Lanczos-Normalisierung; die dHash-Semantik bleibt FolioTone-eigen;
- EPUBCheck 5.3.0 ist für EPUB-Konformitäts-Evidence implementiert;
- Poppler 26.07.0 ist für PDF-Metadaten-, Seiten- und Textanalyse implementiert;
- qpdf 12.4.0 bleibt eine optionale zweite Quelle für PDF-Struktur und
  Integrität, nicht für Textextraktion;
- MuPDF und native Formatparser werden erst bei einem nachgewiesenen Gap erneut
  bewertet.

Die verbindliche Begründung einschließlich Lizenz- und Distributionsgrenzen
steht in `docs/reference/EBOOK_TOOL_EVALUATION.md`.

### calibre `ebook-meta`

`W3-002` implementiert `CalibreMetadataAnalyzer` und den CLI-Befehl
`foliotone ebook-metadata`. Der Adapter besitzt nur die feste Befehlsform
`ebook-meta FILE --to-opf metadata.opf`; Calibre-Setter und frei übergebbare
Zusatzargumente sind nicht verfügbar.

Vor dem Öffnen der Source-Datei wird die calibre-Version geprüft. Unbekannte
Versionen und Versionen kleiner als 9.10.0 werden wegen
`GHSA-2j4m-2q7x-2c47`/`CVE-2026-53511` als auditierbare `FAILED`-Ausführung
abgelehnt. Versionsabfrage und Analyse verwenden ein ephemeres
`CALIBRE_CONFIG_DIRECTORY`.

Die generische Runtime übernimmt deklarierte Workspace-Ausgaben vor dem
Cleanup, begrenzt ihre Größe und persistiert Pfad, Größe und SHA-256 als
`ToolArtifact`. Der calibre-Adapter akzeptiert genau ein maximal 4 MiB großes
`CALIBRE_OPF`-Artefakt, prüft dessen Integrität, verweigert XML-Dokumenttyp- und
Entity-Deklarationen und speichert ausgewählte rohe OPF-Felder als `ToolResult`
gegen die konkrete `FileObservation`. Diese Werte bleiben Evidence und werden
nicht kanonisiert.

`W3-006` hebt den Metadatenadapter auf `ebook-meta-opf/2` und behält die rohen
`calibre_metadata`-Ergebnisse bei. Der provider-neutrale Vertrag
`ebook-metadata-candidate/v1` projiziert zusätzlich OPF-2-Attribute und
OPF-3-Refinements in stabile Feldpfade. Gruppiert werden Identifier-
Namespace/-Wert, Contributor-Name/-Quelle/-Rolle/-Sortiername sowie
Serienname/-position. Direkte Kandidaten umfassen Titel, Sprache, Verlag,
Publikationsdatum, Subject, Beschreibung, Rechte, Typ, Titelsortierung und
calibre-Rating, soweit vorhanden.

Explizite ISBN-Schemes, `urn:isbn` und die ONIX-Codelist-5-Werte 02/15 werden
als ISBN-Namespace erkannt. Die unterstützten MARC-Relator-Codes decken Autor,
Book Producer, Contributor, Editor, Illustrator, Narrator, Other und Translator
ab. Unbekannte Rollen-Schemes bleiben rohe Source-Evidence und erzeugen keine
geratene normalisierte Rolle. Jeder Kandidat verweist auf die exakte
`ToolExecution` und `FileObservation`; der Adapter legt keine `Agent`-,
`Work`-, `Edition`- oder `Series`-Entität an.

Die read-only `calibredb`-Allowlist und der Library-Reconciliation-Vertrag sind
mit ADR-0033 umgesetzt. `S-EB07-10` schließt zusätzlich die zuvor nur deklarierte
Outputgrenze: Die generische ToolRuntime begrenzt stdout/stderr schon während
des Prozesses, beendet Überläufe fail-closed und die vier fachlichen
`calibredb`-Shapes binden exakt 64 MiB, 1 MiB, 4 MiB beziehungsweise 16 MiB.
`S-EB07-11A` ergänzt die fehlende Capture-Grenze: `last_modified` ist nun
verpflichtende UTC-normalisierte Inventory-Evidence, Exact-ID-Suche und
Kategorie-CSV werden strikt und begrenzt geparst, und der kanonische
`calibre-library-inventory-digest/v1` bindet ID, UUID, Änderungszeit sowie
Formattyp und relativen Locator. `S-EB07-11B1` validiert außerdem jedes
begrenzte OPF-Dokument, bindet dessen exakte Bytes als Metadatenfingerprint und
projiziert Capture-Evidence rein und fail-closed in den bestehenden atomaren
Record-/Format-Snapshotgraphen. `S-EB07-11B2A` führt nun die vollständige,
global begrenzte Read-Sequenz mit Keyset-Pagination, Exact-ID-, Kategorie- und
OPF-Läufen aus, bindet alle Ausführungen an dieselbe opake Capture-Identität
und fencet jeden Tool-Write unter einer bestehenden `EBOOK_ANALYSIS`-Lease.
`S-EB07-11B2B` schließt die Orchestrierung: Der Service erwirbt und erneuert
selbst die `EBOOK_ANALYSIS`-Lease, bindet nach Erwerb den neuesten
abgeschlossenen EBOOK-Scan, persistiert den terminalen Record-/Formatgraphen
atomar und gibt die Lease auch auf Fehlerpfaden frei. Die read-only
Calibre-Capture-Schiene aus ADR-0033 ist damit vollständig implementiert.

### calibre EPUB/MOBI/AZW/AZW3-Text und normalisierter Fingerprint

`W3-003` implementiert `CalibreTextAnalyzer` und den CLI-Befehl
`foliotone ebook-text` zunächst für EPUB. `W3-005` erweitert denselben Adapter
auf die explizite Allowlist EPUB, MOBI, AZW und AZW3. Die unveränderliche
`ebook-convert FILE content.txt`-Befehlsform verwendet `plain`-Ausgabe, UTF-8,
Unix-Zeilenenden und deaktivierte Zeilenaufteilung. Aufrufende Komponenten
können keine calibre-Konvertierungsoptionen ergänzen. KFX, AZW1, AZW4 und
weitere Formate gehören nicht zu diesem Textvertrag.

Die Sicherheitsuntergrenze calibre 9.10.0, das ephemere
`CALIBRE_CONFIG_DIRECTORY` und `CALIBRE_ALLOW_PYTHON_TEMPLATES=0` gelten auch
für diesen Adapter. Die Ausgabe wird vor dem Workspace-Cleanup als privates,
maximal 64 MiB großes `CALIBRE_TEXT`-Artefakt mit Größe und SHA-256 übernommen.
Der Rohtext wird nicht über die CLI ausgegeben. DRM-Entfernung oder -Umgehung
gehört nicht zum Vertrag. Ein DRM-geschütztes, beschädigtes oder anderweitig
nicht konvertierbares Buch bleibt eine fehlgeschlagene `ToolExecution`; nur
eine erfolgreiche leere Extraktion darf `NO_TEXT` erzeugen.

Nach UTF-8- und Artifact-Integritätsprüfung normalisiert FolioTone den Text mit
Unicode `NFKC`, reduziert Unicode-Whitespace-Folgen und bildet SHA-256. Der
`Fingerprint` besitzt `kind = EBOOK_NORMALIZED_TEXT`, verweist auf die konkrete
`FileObservation` und `ToolExecution` und führt die Unicode-Datenversion im
`algorithm_version`-Profil. `ToolResult` hält `TEXT_EXTRACTED` oder `NO_TEXT`
sowie die normalisierte Zeichenzahl. Für `NO_TEXT` entsteht kein Fingerprint.
Der neue `ToolCapability`-Wert lautet `EXTRACT_TEXT`.

### Poppler PDF-Metadaten, Seitenzahl und Text

`W3-004` implementiert `PopplerPdfAnalyzer` und den CLI-Befehl
`foliotone pdf-analyze`. Der Adapter akzeptiert ausschließlich eine
unveränderte PDF-`FileObservation`. `pdfinfo` und `pdftotext` besitzen feste
Argumentformen, separate `ToolExecution`-Records und getrennte Capabilities.
Unbekannte Poppler-Versionen und Versionen kleiner als 26.07.0 werden vor dem
Öffnen der Source-Datei abgelehnt.

Die UTF-8-Ausgabe von `pdfinfo` wird auf 1 MiB begrenzt und nur über eine
Feld-Allowlist importiert. Seitenzahl, gemeldete Dateigröße, PDF-Version und
ausgewählte technische Metadaten bleiben rohe Evidence; die Dateigröße wird
gegen die konkrete Observation geprüft. `pdftotext` schreibt ausschließlich
`content.txt` in den privaten Workspace. Maximal 64 MiB werden als
integritätsgeprüftes `POPPLER_TEXT`-Artefakt übernommen.

PDF und EPUB verwenden danach denselben FolioTone-eigenen, versionierten
`NFKC`-/Whitespace-Normalisierer und `EBOOK_NORMALIZED_TEXT`-Fingerprint.
Erfolgreich extrahierter leerer Text ist `NO_TEXT` und erzeugt keinen
Fingerprint; Poppler-Fehler bleiben dagegen fehlgeschlagene Toolausführungen.
Die CLI gibt keinen Rohtext aus. OCR, Passwortargumente, frei übergebbare
Poppler-Optionen und schreibende PDF-Operationen sind nicht exponiert. qpdf
bleibt bis zu einem konkreten strukturellen Evidence-Gap zurückgestellt.

### Versionierter E-Book-Vergleichskorpus

`W3-007` stellt unter `tests/fixtures/ebook_comparison/v1/` fünf vollständig
synthetische Items und fünf gelabelte Szenarien bereit. Das Manifest
`foliotone-ebook-comparison-fixture/v1` bindet ausschließlich sichere relative
Pfade sowie SHA-256-Werte der Container-Surrogate und extrahierten
Text-Artefakte. Der produktive `EBOOK_NORMALIZED_TEXT`-Vertrag erzeugt daraus
die versionierten Inhalts-Fingerprints. `.gitattributes` verhindert dabei eine
plattformabhängige Zeilenendenkonvertierung der checksum-behafteten Fixtures.

Die Ground Truth unterscheidet:

- zwei byte-identische Dateien;
- unterschiedliche Dateibytes nach einer Metadatenänderung bei identischem
  normalisiertem Text und derselben `Edition`;
- dieselbe `Edition` als EPUB-/MOBI-Formatvariante;
- eine Übersetzung als andere `Edition` desselben `Work`;
- zwei widersprüchliche synthetische Tool-Beobachtungen für denselben
  Identifier mit getrennten Tool-, Adapter- und Kandidatenprofilversionen.

Die Container-Surrogate sind bewusst keine echten EPUB-/MOBI-Dateien und
testen deshalb keine Drittanbieterparser nach. Das Disagreement-Szenario setzt
keinen kanonischen Wert. Die deklarierten `RelationType`-Werte dienen als
kontrollierte Eingabe für spätere W6-Tests; Candidate Blocking, Scoring,
Confidence-Schwellen und automatische Review-Entscheidungen sind nicht Teil
von W3-007. Der Slice ergänzt keine Produktoberfläche und verändert keine
Source Media.

### EPUBCheck-Strukturvalidierung

`W3-008` implementiert `EpubCheckAnalyzer` und den CLI-Befehl
`foliotone epub-validate`. Der Adapter akzeptiert nur eine unveränderte
EPUB-`FileObservation` und ruft eine separat bereitgestellte Java-Runtime plus
`epubcheck.jar` über eine feste Headless-Befehlsform auf. JVM-Tempdaten und
`report.json` entstehen ausschließlich im privaten ephemeren Tool-Workspace.
Zusätzliche EPUBCheck-Optionen sind nicht über die CLI verfügbar.

EPUBCheck 5.3.0 ist die Mindestversion. Der maximal 8 MiB große JSON-Report wird
als integritätsgeprüftes `EPUBCHECK_JSON`-`ToolArtifact` übernommen. Der
strikte Parser begrenzt die Meldungszahl auf 10.000 und verifiziert Dateiname,
Tool-/Reportversion, deklarierte Counts, Severity-Allowlist sowie Diagnose-IDs.
Persistiert werden `CONFORMANT` oder `NONCONFORMANT`, fünf Severity-Counts und
aggregierte Severity-/Diagnosecode-Counts gegen die exakte `ToolExecution` und
`FileObservation`. Meldungstext, Publication-Metadaten und lokale Pfade werden
nicht in `ToolResult` oder CLI-Ausgabe projiziert.

ADR-0017 erweitert den generischen Runtime-Vertrag um eine unveränderliche
`accepted_exit_codes`-Allowlist mit Standard `{0}`. Der EPUBCheck-Befehl
akzeptiert dokumentiert `{0, 1}`, weil Exitcode `1` einen abgeschlossenen
Prüflauf mit Konformitätsfehlern bezeichnet. Der Code bleibt in
`ToolExecution.exit_code` erhalten; der negative Befund steht getrennt in
`ToolResult`. Nicht erlaubte Codes, Timeout sowie fehlende, ungültige oder zu
große Pflichtartefakte bleiben technische Fehler.

`calibre-debug --diff` wurde nicht integriert: Die dokumentierte Option startet
das GUI-Diff-Modul und besitzt keinen headless, maschinenlesbaren Report- oder
stabilen Exitcode-Vertrag. Spätere Inhaltsvergleiche sollen die bereits
provider-neutral persistierte Evidence aus Datei-Hash, normalisiertem Text,
Metadaten, Struktur und Cover-Fingerprints verwenden. qpdf 12.4.0
bleibt bis zu einem zusätzlichen PDF-Struktur-Gap zurückgestellt.

### calibre Embedded-Cover und FolioTone-dHash

`W3-009` implementiert `CalibreCoverAnalyzer` und den CLI-Befehl
`foliotone ebook-cover` für die explizite EPUB/MOBI/AZW/AZW3-Allowlist. Ein
fester, paketierter Helper läuft über das dokumentierte
`calibre-debug -e SCRIPT -- ...`-Interface. Er kopiert die unveränderte
Observation zuerst in den privaten ephemeren Workspace; erst dort öffnet der
calibre-Metadatenreader die Datei. Für EPUB ist das Rendering der ersten Seite
als Ersatzcover deaktiviert. Ein Buch ohne eingebettetes Cover erzeugt deshalb
`NO_EMBEDDED_COVER` statt eines erfundenen Titelbilds.

Der direkte `ebook-meta --get-cover`-Pfad wurde bewusst verworfen. Ohne
Unterdrückung rendert calibre bei coverlosen EPUBs die erste Seite. Der lokale
9.13-Test zeigte außerdem, dass `--disallow-rendered-cover` von `ebook-meta`
als schreibende Option behandelt wird und die Eingabedatei verändern kann.
Der Helper verwendet daher keine `ebook-meta`-Setter-Schnittstelle und gibt
dem calibre-Reader ausschließlich die private Arbeitskopie.

Ein erforderliches, maximal 1 KiB großes JSON-Ergebnis hält Status,
Covergröße und SHA-256 der gestagten Source. FolioTone vergleicht diesen Digest
nach dem Toollauf erneut mit der konkreten `FileObservation`. Das optionale
Raster bleibt als privates, maximal 32 MiB großes
`CALIBRE_EMBEDDED_COVER`-`ToolArtifact` erhalten. JPEG, PNG, WebP und GIF
werden mit Pillow 12.3.x dekodiert; eine 40-Megapixel-Grenze, Pillow-
Decompression-Bomb-Prüfung, EXIF-Orientierung und ausschließlich der erste
Frame begrenzen und determinieren die Verarbeitung.

FolioTone normalisiert das Bild in Graustufen auf 9 x 8 Pixel mit Lanczos und
vergleicht je Zeile acht horizontale Nachbarpaare. Das Ergebnis ist ein
64-Bit-`dhash-64` mit `kind = EBOOK_COVER_DHASH`. Das
`algorithm_version`-Profil enthält Richtung, Farbraum, Rastergröße,
Resampling-Verfahren und exakte Pillow-Version. ImageHash 4.3.2 wurde für
diesen kleinen festen Vertrag nicht übernommen, weil sein Gesamtpaket NumPy,
SciPy und PyWavelets einzieht. Coverähnlichkeit bleibt unterstützende Evidence;
sie beweist weder gleiche Datei noch gleiche `Edition` oder gleiches `Work`.
PDF-Seitenrendering und Music-Release-Artwork gehören nicht zu diesem Slice.

### Einheitlicher formatbewusster E-Book-Workflow

`W3-010` implementiert `ebook-analysis-workflow/v1` und den CLI-Befehl
`foliotone ebook-analyze`. Die Workflow-Schicht enthält keinen neuen Parser und
keine eigene Toolausführung. Sie ruft ausschließlich die bereits gehärteten
Adapter in fester, formatabhängiger Reihenfolge auf:

- EPUB: calibre-Metadaten, normalisierter Text, Embedded-Cover und EPUBCheck;
- MOBI/AZW/AZW3: calibre-Metadaten, normalisierter Text und Embedded-Cover;
- PDF: die bestehenden `pdfinfo`- und `pdftotext`-Ausführungen von Poppler.

Vor dem ersten Schritt wird geprüft, ob alle für das konkrete Format nötigen
Adapter konfiguriert sind. Erwartete Adapterfehler und fehlgeschlagene oder
abgebrochene ToolExecutions blockieren unabhängige Folgeschritte nicht. Jeder
Schritt bleibt separat als `SUCCEEDED`, `FAILED`, `CANCELLED` oder `ERROR`
sichtbar. Der Workflow fasst dies zu `SUCCEEDED`, `PARTIAL_FAILURE` oder
`FAILED` zusammen; nur vollständiger technischer Erfolg liefert CLI-Exitcode
0. Ein EPUBCheck-Befund `NONCONFORMANT` bleibt dabei ein erfolgreich erzeugter
fachlicher Befund und wird nicht als Prozessfehler umgedeutet.

Jeder Aufruf erzeugt zunächst bewusst frische versions- und
konfigurationsgebundene ToolExecutions. Unsichere Wiederverwendung wird nicht
implizit eingeführt. `W3-011` soll auf der konservativen W2-Entscheidungslogik
aufbauen und ausschließlich exakt passende, erfolgreiche und weiterhin
integritätsprüfbare Evidence wiederverwenden.

Die CLI-Zusammenfassung ist begrenzt und druckt nur Format, Workflow-Profil,
ToolExecution-ID/-Status/-Version sowie allowlist-basierte Zähler, Statuswerte
und Fingerprints. Rohe OPF-, Text-, Cover- und EPUBCheck-Artefakte,
Diagnosetexte und absolute Source-Pfade werden nicht ausgegeben.

### Konservative Schrittplanung und Evidence-Wiederverwendung

`W3-011` hebt den einheitlichen Vertrag auf
`ebook-analysis-workflow/v2`. Standardmäßig prüft jeder Adapter zunächst nur
die Version seines fest konfigurierten lokalen Werkzeugs. Dieser Probe öffnet
keine Source Media und persistiert keine ToolExecution. Ein früherer Schritt
wird ausschließlich dann wiederverwendet, wenn der zeitlich neueste Lauf mit
exakt gleicher Provider-, Tool-, Adapter-, Capability-, FileObservation-Input-
und Konfigurationsidentität erfolgreich war.

Die Identität allein genügt nicht: Jedes vom Adapter deklarierte
Pflichtartefakt muss weiterhin vorhanden sein und seine Größen- und SHA-256-
Grenzen erfüllen. Anschließend rekonstruiert FolioTone die normalisierten
ToolResults und Fingerprints deterministisch aus dem privaten Artefakt und
vergleicht sie inhaltsgleich mit der Persistenz. Dadurch wird weder ein bloßes
`SUCCEEDED` noch ein unvollständig importierter oder nachträglich beschädigter
Stand als wiederverwendbar behandelt.

Fehlende, fehlgeschlagene, abgebrochene, laufende, versionsfremde,
artefaktbeschädigte oder inkonsistente Schritte werden normal read-only neu
ausgeführt. Unabhängige exakte Schritte bleiben dabei wiederverwendet. Die CLI
weist jeden Schritt als `REUSED` oder `EXECUTED` aus; die ursprünglichen
ToolExecution-IDs bleiben bei Wiederverwendung unverändert. `--fresh` umgeht
die gesamte Wiederverwendungsplanung und führt alle anwendbaren Schritte neu
aus. Der vorhandene PDF-Adapter bleibt ein atomarer Workflow-Schritt: Sind
`pdfinfo` oder `pdftotext` nicht exakt wiederverwendbar, laufen beide getrennt
provenance-gebundenen Poppler-Ausführungen neu.

## Lizenz und Dokumentations-Governance

Die Lizenz- und Dokumentationsentscheidungen bleiben unverändert:

- `LICENSE.md` verwendet die vom Benutzer vorgegebene Custom Community & Attribution License nach dem Vorbild von `SQL_Server_Analyze`;
- FolioTone ist ausdrücklich **nicht Open Source**;
- die englische Lizenzfassung ist entsprechend `LICENSE.md` rechtlich maßgeblich;
- der zweisprachige Lizenzblock am Anfang der Root-README ist geschützter Inhalt;
- `docs/quality/DOCUMENTATION_STYLE.md` und `docs/quality/LANGUAGE_AND_TERMINOLOGY.md` sind verbindlich;
- `docs/reference/GLOSSARY.md` ist die kanonische Terminologiequelle;
- `tests/static/test_documentation_contracts.py` prüft konservativ bekannte Dokumentationsregressionen.

## Verifikation

### Grundlegender W2-Slice

Der finale PR-#5-Head `ef10290da1ed3522e5a261ccb33d5561e32eb497` wurde in GitHub Actions Run `31282820586` vollständig geprüft und anschließend als Merge-Commit `4362d60eca51c3e896ae3a6e4fb4485e644bbc4d` nach `main` übernommen. Install, Ruff, Mypy, 44 Pytest-Tests sowie Docker-Build, Migration, persistentes `/data`, Incremental Scan und Bootstrap waren erfolgreich.

### `W2-004` — automatisierte Verifikation

Der Implementierungs-Head `556055eb7848f3f682f0bd2363ba2dc98fceb7e5` von PR #7 wurde in GitHub Actions Run `31285157432` erfolgreich geprüft. Install, Ruff, Mypy, 48 Pytest-Tests und sämtliche Docker-Smoke-Schritte waren erfolgreich.

### `W2-006` — automatisierte Verifikation

Der Implementierungs-Head `c946dd336593b68ed281c530ab40117562d17831` von PR #8 wurde in GitHub Actions Run `31285662119` erfolgreich geprüft. Install, Ruff, Mypy, 52 Pytest-Tests und sämtliche Docker-Smoke-Schritte waren erfolgreich.

### `W2-007` — automatisierte Verifikation

Der Implementierungs-Head `8bfa20fb692727f03f8f0cd40b64385328e75d30` von PR #9 wurde in GitHub Actions Run `31286181807` erfolgreich geprüft. Install, Ruff, Mypy, Pytest sowie Docker-Build, Migration, persistentes `/data`, Incremental Scan und Bootstrap waren erfolgreich.

Die Resume-Integrationstests bestätigen insbesondere:

- partielle Arbeit und Fingerprints bleiben nach `INTERRUPTED` persistent;
- ein Resume erhält eine neue `ScanRun`-ID und die korrekte `resumed_from_run_id`;
- bereits verarbeitete unveränderte Dateien werden beim Resume nicht erneut gehasht;
- ein unterbrochener Scan erzeugt keine falsche `MISSING`-Evidenz für nicht erreichte bekannte Dateien;
- nur persistierte `INTERRUPTED`-Runs desselben `ScanRoot` sind resumierbar;
- Migration `0005` stellt Lineage-Spalte und Index bereit.

### Lokale Windows-/Docker-Verifikation

`W2-012` wurde am 2026-08-09 mit ausschließlich synthetischen Testdateien lokal ausgeführt. Verwendet wurden Docker Engine `29.6.2` und Docker Compose `v5.3.1`.

Empirisch bestätigt wurden Docker-Build und Bootstrap, persistentes beschreibbares `/data`, read-only `/media/ebooks`, die Zustandsfolge NEW/UNCHANGED/MODIFIED/MISSING/REAPPEARED sowie unavailable-root Schutz gegen falsche `MISSING`-Evidenz.

Die später implementierten `DELETED`-, Relocation- und Resume-Funktionen sind durch automatisierte Integrationstests abgedeckt und wurden in diesem lokalen Plattformtest nicht separat nachgestellt.

### W2-Abschlussprüfung

**Empirisch:** Am 2026-08-14 wurden die vollständigen lokalen Quality Gates mit Python 3.12.10 ausgeführt. `ruff check .`, `mypy src/foliotone` für 56 Source-Dateien und 86 Pytest-Tests waren erfolgreich. Die Tests decken insbesondere die W2-009-Parsing-Profile sowie die W2-011-Fälle malformed JSON, fehlende/zu große Ausgabe, Artifact-Integrität, fehlgeschlagene frühere Ausführungen und Reanalyse nach Tool-, Adapter-, Input- oder Konfigurationsänderung ab.

Der Linux-Container wurde über Docker Engine 29.7.2 und Docker Compose 5.4.0 in WSL2 gebaut. Container-Bootstrap und Alembic-Head-Migration waren erfolgreich. Der allowlist-basierte Docker-Build-Kontext enthält ausschließlich `Dockerfile`, `pyproject.toml`, `README.md` und `src/`; lokale Runtime-, Medien-, Secret-, Test- und Git-Daten werden nicht übertragen.

### W3-001 bis W3-009 lokale Verifikation

**Empirisch:** Am 2026-08-14 wurde das offizielle calibre-9.13.0-MSI nach
SHA-256- und Authenticode-Prüfung als separates administratives Abbild unter
`C:\rep\cache\FolioTone` bereitgestellt. `ebook-meta.exe --version` meldete
calibre 9.13. Der MSI-Export endete mit Status 0; Codex wurde weder beendet noch
neu gestartet.

Ein End-to-End-Lauf mit ausschließlich einem synthetischen EPUB unter
`C:\rep\tmp\FolioTone` bestätigte:

- erfolgreicher `foliotone scan` und eine konkrete `FileObservation`;
- erfolgreiche `foliotone ebook-metadata`-Ausführung;
- ein persistiertes, integritätsgeprüftes `CALIBRE_OPF`-Artefakt;
- sechs persistierte rohe Metadatenbeobachtungen;
- leeres ephemeres Tool-Work-Verzeichnis nach Abschluss;
- keine echte Medien- oder Calibre-Library als Testeingabe.

Die vollständigen lokalen Quality Gates des W3-Slice waren erfolgreich:
`ruff check`, Mypy für 57 Source-Dateien und 107 Pytest-Tests.

**Remote:** Der Implementierungscommit
`1a02dc146919db7294b7b88ad6d9f6a7a6e60e04` bestand GitHub Actions Run
`31794835407`. Erfolgreich waren Install, Ruff, Mypy, Pytest, Docker-Build,
Migration, persistentes `/data`, Incremental-Scan-Smoke und Bootstrap.

**Empirisch für W3-003:** Ein weiterer End-to-End-Lauf mit demselben
ausschließlich synthetischen EPUB und calibre 9.13.0 bestätigte eine erfolgreiche
`ebook-text`-`ToolExecution`, ein 49 Byte großes `CALIBRE_TEXT`-Artefakt,
`TEXT_EXTRACTED`, 43 normalisierte Zeichen, einen
`EBOOK_NORMALIZED_TEXT`-Fingerprint und ein nach Abschluss leeres ephemeres
Work-Verzeichnis.

Repository-Ruff, Mypy für 59 Source-Dateien und 115 Pytest-Tests waren lokal
erfolgreich. Die gezielten 42 calibre-/Runtime-/CLI-Tests waren ebenfalls
erfolgreich. Der W3-003-Implementierungscommit
`dc2cd09ffbc07098e0c296bea231532c4f38051b` bestand GitHub Actions Run
`31809375485` für PR #13. Erfolgreich waren Install, Ruff, Mypy, Pytest,
Docker-Build, Migration, persistentes `/data`, Incremental-Scan-Smoke und
Bootstrap.

**Empirisch für W3-004:** Poppler 26.07.0 wurde außerhalb des Repositorys unter
`C:\rep\cache\FolioTone` verifiziert. Ein End-to-End-Lauf unter
`C:\rep\tmp\FolioTone` verwendete ausschließlich ein synthetisches Text-PDF
und ein synthetisches leeres PDF. Beide erzeugten erfolgreiche, getrennte
`pdfinfo`-/`pdftotext`-Ausführungen, jeweils 20 Metadatenbeobachtungen und
`page_count = 1`. Das Text-PDF lieferte `TEXT_EXTRACTED`, 45 normalisierte
Zeichen und einen `EBOOK_NORMALIZED_TEXT`-Fingerprint. Das leere PDF lieferte
`NO_TEXT`, null normalisierte Zeichen und keinen Fingerprint. Die gezielten 18
Poppler-Unit-Tests waren erfolgreich; die ephemeren Work-Verzeichnisse waren
nach Abschluss leer.

Der vollständige W3-004-Stand bestand anschließend lokal `ruff check .`, Mypy
für 63 Source-Dateien und alle 133 Pytest-Tests in 6 Minuten 35 Sekunden.

**Empirisch für W3-005:** Ein End-to-End-Lauf mit calibre 9.13.0 und
ausschließlich synthetischen, DRM-freien EPUB-, MOBI-, AZW- und AZW3-Dateien
bestätigte vier erfolgreiche Metadaten- sowie vier erfolgreiche Text-
`ToolExecution`-Records. Alle vier Textläufe lieferten `TEXT_EXTRACTED`, 43
normalisierte Zeichen und denselben `EBOOK_NORMALIZED_TEXT`-Fingerprint. Der
Adapterstand `ebook-convert-text/2` war viermal erfolgreich persistiert. Das
ephemere Work-Verzeichnis war nach Abschluss leer; Rohtext wurde nicht über die
CLI ausgegeben. Die gezielten 32 calibre-/CLI-Tests sowie Ruff und Mypy für 63
Source-Dateien waren erfolgreich.

Der vollständige W3-005-Stand bestand anschließend lokal `ruff check .`, Mypy
für 63 Source-Dateien und alle 142 Pytest-Tests in 8 Minuten 50 Sekunden.

**Empirisch für W3-006:** Der gezielte OPF2-/OPF3-Testlauf bestand alle 26
calibre-Metadaten-Tests. Er deckt gruppierte ISBN-/Identifier-, Contributor-,
MARC-Rollen-, Sortier-, Sprach-, Verlags-, Datums-, Subject-, Beschreibungs-,
Rechte-, Typ- und Series-Kandidaten sowie das bewusste Nicht-Mapping eines
fremden Rollen-Schemes ab.

Ein read-only End-to-End-Smoke-Test mit calibre 9.13 und einem ausschließlich
synthetischen, DRM-freien MOBI erzeugte eine erfolgreiche `ToolExecution` unter
`ebook-meta-opf/2`, elf rohe `calibre_metadata`-Beobachtungen und 21
`ebook_metadata_candidate`-Ergebnisse. Alle Ergebnisse verwiesen auf genau
diese Ausführung und `FileObservation`; `Agent`, `Work`, `Edition` und `Series`
blieben leer. Das private OPF-Artefakt wurde übernommen, und das ephemere
Work-Verzeichnis war nach Abschluss leer.

Der vollständige W3-006-Stand bestand lokal `ruff check .`, Mypy für 64
Source-Dateien und alle 152 Pytest-Tests in 8 Minuten 45 Sekunden.

**Empirisch für W3-007:** Die drei gezielten Fixture-Vertragsprüfungen
bestanden. Sie prüfen Schema-Version und Provenance, sichere relative Pfade,
alle deklarierten Datei-/Text-SHA-256-Werte, den produktiven normalisierten
Text-Fingerprint, die vier paarweisen Identitätsabgrenzungen und die Erhaltung
zweier widersprüchlicher Tool-Werte ohne Kanonisierung.

Der vollständige W3-007-Stand bestand lokal `ruff check .`, Mypy für 64
Source-Dateien und alle 155 Pytest-Tests in 8 Minuten 25 Sekunden.

**Remote für W3-007:** Der Implementierungscommit
`352eb8567c542e709e77f98de42c222f21dd3f75` von PR #17 bestand die beiden durch
Push und Pull Request ausgelösten GitHub-Actions-Runs `31844049430` und
`31844093222`. Beide `quality`-Jobs waren nach jeweils 52 Sekunden erfolgreich.

**Empirisch für W3-008:** Temurin JRE 21.0.12+8 und EPUBCheck 5.3.0 wurden als
portable, SHA-256-verifizierte Runtime-Abhängigkeiten unter
`C:\rep\cache\FolioTone` bereitgestellt. Es gab keine systemweite Installation,
keinen Neustart und keinen Eingriff in Codex.

Der echte CLI-Smoke-Test verwendete ausschließlich das vorhandene synthetische
EPUB. EPUBCheck meldete drei Konformitätsfehler und Exitcode `1`; FolioTone
persistierte eine erfolgreiche `STRUCTURAL_VALIDATION`-Ausführung,
`NONCONFORMANT`, fünf Severity-Counts und die Codes `PKG-006`, `PKG-007` und
`RSC-005`. Die Source-Datei blieb bytegleich, der Report wurde privat
übernommen und das Work-Verzeichnis vollständig bereinigt. Die 15 neuen
Adaptertests sowie 37 gezielten Runtime-/Toolingtests waren erfolgreich; der
gezielte Mypy-Lauf für Adapter, Runtime und CLI war fehlerfrei.

Der vollständige W3-008-Stand bestand anschließend mit Python 3.12.10 lokal
`ruff check .`, Mypy für 66 Source-Dateien und alle 175 Pytest-Tests in
9 Minuten 23 Sekunden.

**Remote für W3-008:** Der Implementierungscommit
`e80b1d9cba28e2d883daaa2627b4fc0ef795d11c` von PR #18 bestand die durch Push
und Pull Request ausgelösten GitHub-Actions-Runs `31866746326` und
`31866764769`. Beide `quality`-Jobs waren nach 58 beziehungsweise 50 Sekunden
erfolgreich.

**Empirisch für W3-009:** Pillow 12.3.0 wurde ausschließlich in der
projektbezogenen Python-Umgebung unter `C:\rep\cache\FolioTone` installiert;
es gab keine systemweite Installation und keinen Neustart. Die 13 neuen
Cover-Unit-Tests sowie die beiden aktualisierten Bootstrap-Tests bestanden in
85 Sekunden. Repository-Ruff und Mypy für 69 Source-Dateien waren erfolgreich.

Der echte CLI-Smoke-Test unter
`C:\rep\tmp\FolioTone\w3-009-smoke-01` verwendete ausschließlich zwei
synthetische EPUBs. Das Buch mit eingebettetem JPEG lieferte
`COVER_EXTRACTED`, Format `JPEG`, 1240 x 1752 Pixel und den 64-Bit-dHash
`4000000000000000`. Das coverlose Buch lieferte erfolgreich
`NO_EMBEDDED_COVER` und keinen Fingerprint. Beide `ToolExecution`-Records
meldeten calibre 9.13, beide CLI-Aufrufe endeten mit Exitcode 0, und die
SHA-256-Werte beider Source-Dateien waren vor und nach der Analyse identisch.

Der vollständige W3-009-Stand bestand mit Python 3.12.10 lokal
`ruff check .`, Mypy für 69 Source-Dateien und alle 188 Pytest-Tests in
11 Minuten 31 Sekunden. Ein lokaler Wheel-Build war erfolgreich und enthielt
den Cover-Adapter, die FolioTone-Hashlogik und den paketierten calibre-Helper.

Der Implementierungscommit `a55b553445b223ea6219a522cdaafeff98165aa7`
von PR #19 bestand die GitHub-Actions-Runs `31871971678` und `31871990590`;
die beiden `quality`-Jobs waren nach 58 beziehungsweise 63 Sekunden
erfolgreich.

**Empirisch für W3-010:** Die gezielte Suite aus Workflow-, Bootstrap- und
CLI-Integrationstests bestand mit 18 Tests. Ruff war erfolgreich; Mypy prüfte
71 Source-Dateien ohne Befund. Der CLI-Integrationstest bestätigt, dass vier
fehlende EPUB-Werkzeuge als vier getrennte fehlgeschlagene
ToolExecutions sichtbar bleiben, alle Schritte ausgeführt werden und weder
Source- noch absolute Runtime-Pfade in der Zusammenfassung erscheinen.

Der echte CLI-Smoke-Test unter
`C:\rep\tmp\FolioTone\w3-010-smoke-01` verwendete ausschließlich die beiden
synthetischen EPUBs mit und ohne eingebettetes Cover. Beide einheitlichen
Analysen endeten mit Exitcode 0 und jeweils vier erfolgreichen ToolExecutions.
Persistiert wurden insgesamt acht erfolgreiche ToolExecutions, 79 ToolResults
und sieben Fingerprints. Metadaten, Text und EPUBCheck waren für beide Dateien
erfolgreich; das Cover-Ergebnis blieb korrekt `COVER_EXTRACTED` beziehungsweise
`NO_EMBEDDED_COVER`. Die synthetisch unvollständigen EPUBs lieferten erwartbar
`NONCONFORMANT` mit je drei Fehlercodes, ohne den technischen Workflowstatus zu
verfälschen. Beide Source-SHA-256 blieben unverändert, und der ephemere
Work-Ordner war nach den Läufen leer.

Der vollständige W3-010-Stand bestand mit Python 3.12.10 lokal
`ruff check .`, Mypy für 71 Source-Dateien und alle 204 Pytest-Tests in
11 Minuten 16 Sekunden. Das Wheel
`C:\rep\artifacts\FolioTone\w3-010-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`3ad24961dc47512721a06053ab40504b2534a8979effb9a43e713c4e501aff24` und
enthält beide Dateien des neuen `foliotone.workflows`-Pakets.

**Empirisch für W3-011:** Der echte CLI-Smoke-Test unter
`C:\rep\tmp\FolioTone\w3-011-smoke-01` verwendete ausschließlich ein
synthetisches EPUB mit eingebettetem Cover. Der Erstlauf erzeugte vier
erfolgreiche ToolExecutions. Ein identischer zweiter Lauf markierte alle vier
Schritte als `REUSED`, behielt dieselben ToolExecution-IDs und erhöhte den
Datenbankzähler nicht. Nach absichtlicher SHA-256-Inkonsistenz ausschließlich
des privaten `CALIBRE_TEXT`-Artefakts wurde nur der Textschritt neu ausgeführt;
der Zähler stieg von vier auf fünf. Ein anschließender Lauf mit `--fresh`
führte alle vier Schritte neu aus und erhöhte ihn auf neun.

Verwendet wurden calibre 9.13, EPUBCheck 5.3.0 und Temurin JRE 21.0.12+8. Die
Source-SHA-256 blieb
`41070cdea56904647215b069f15af3f6e46d6d94b81795974e247a337464b6ea`;
der ephemere Work-Ordner war nach allen Läufen leer.

Der vollständige W3-011-Stand bestand mit Python 3.12.10 lokal
`ruff check .`, Mypy für 73 Source-Dateien und alle 216 Pytest-Tests in
11 Minuten 35 Sekunden. Das Wheel
`C:\rep\artifacts\FolioTone\w3-011-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`ab6064b05035a8cddd4f033a493c3f9d76ce43b37fe89dba5d790f142ad9e62e`
und enthält die Workflow-Module `ebook.py`, `evidence.py` und `reuse.py`.

Der W3-011-Implementierungscommit
`2f08bcc4f3b13517ec70e92e3eb25416ce56e6e4` liegt in PR #21. Für diesen
exakten Stand waren die GitHub-Actions-Runs `31886119562` (Push) und
`31886140176` (Pull Request) erfolgreich. Ihre `quality`-Jobs einschließlich
Ruff, Mypy, Tests, Docker-Build, Migration, persistentem `/data`,
Incremental-Scan-Smoke und Bootstrap liefen 56 beziehungsweise 63 Sekunden.

Der veröffentlichte Implementierungscommit
`2f8cb144617433855f51c39c4525603b9aa1004a` liegt in PR #20. Für diesen
exakten Stand waren die GitHub-Actions-Runs `31874601676` (Push) und
`31874615476` (Pull Request) erfolgreich; ihre `quality`-Jobs einschließlich
Ruff, Mypy, Tests und aller Docker-Smoke-Tests liefen 62 beziehungsweise
59 Sekunden.

**Empirisch für W3-012:** Die gezielten lokalen Tests decken ein vollständiges
EPUB, metadata-arme und nicht konforme EPUB-Evidence, ein verschlüsseltes
textloses PDF, fehlgeschlagene Tool-Evidence, widersprüchliche Text-Evidence
und die begrenzte CLI-Ausgabe ab. Alle 26 gezielten Tests waren erfolgreich;
der vollständige Stand bestand `ruff check .`, Mypy für 74 Source-Dateien und
alle 222 Pytest-Tests in 9 Minuten 23 Sekunden.

Der echte CLI-Smoke verwendete ausschließlich die synthetische EPUB unter
`C:\rep\tmp\FolioTone\w3-011-smoke-01`. Alle vier technischen Schritte wurden
mit denselben ToolExecution-IDs `REUSED`; der Datenbankzähler blieb bei neun.
`ebook-quality/v1` meldete wegen 43 normalisierten Zeichen
`TEXT_VERY_SHORT` und wegen drei EPUBCheck-Errors
`EPUB_VALIDATION_ERRORS`, insgesamt `ACTION_REQUIRED`, während der technische
Workflow korrekt `SUCCEEDED` blieb. Die Source-SHA-256 blieb
`41070cdea56904647215b069f15af3f6e46d6d94b81795974e247a337464b6ea` und
der Work-Ordner leer.

Das Wheel
`C:\rep\artifacts\FolioTone\w3-012-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`a02e033db35e6e2acfe0d374961597e257e3070198bb3f503854425a17a95457` und
enthält das neue Workflow-Modul `quality.py`.

**Empirisch für W3-013:** Der vorhandene vollständig synthetische Korpus prüft
exakte Dateikopien, reine Metadatenänderung, EPUB/MOBI-Formatvariante,
Übersetzung, Cover-dHash-Distanz, EPUB-Strukturunterschiede und gleichzeitig
erhaltene Provider-Disagreement-Evidence. Ein neuerer fehlgeschlagener
Textprovider-Lauf macht ältere Text-Evidence korrekt `INDETERMINATE`. Die fünf
gezielten Vergleichs-/CLI-/Bootstrap-Tests waren erfolgreich; Ruff und Mypy
für 75 Source-Dateien waren ebenfalls erfolgreich. Der vollständige Stand
bestand alle 225 Pytest-Tests in 13 Minuten 27 Sekunden.

Der echte CLI-Smoke unter `C:\rep\tmp\FolioTone\w3-013-smoke-01` verwendete
zwei bytegleiche Kopien einer ausschließlich synthetischen EPUB. Acht
ToolExecutions analysierten beide Beobachtungen erfolgreich. `ebook-compare`
meldete `COMPLETE` und in allen fünf Dimensionen `SAME`; ein von calibre pro
Extraktion neu erzeugter interner `identifier.calibre` wurde nach empirischer
Gegenprüfung nicht als bibliografischer Unterschied verwendet. Beide Source-
SHA-256 blieben
`41070cdea56904647215b069f15af3f6e46d6d94b81795974e247a337464b6ea`, der
Work-Ordner blieb leer und die Relation-Tabelle enthielt null Datensätze.

Das Wheel
`C:\rep\artifacts\FolioTone\w3-013-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`985e84dbf06e8bcad2e23468af3cd096a6ef9c0469300ae357a016854da669fe` und
enthält `foliotone/workflows/comparison.py`.

**Empirisch für W3-014:** Der additive synthetische v2-Korpus deckt alle
aktuell unterstützten Formate EPUB, MOBI, AZW, AZW3 und PDF, vollständig
fehlende sowie gezielt inkompatible/unvollständige Evidence und Cover-dHash-
Distanzen von 0, 1, 8, 32 und 64 Bit ab. Sechs neue Paar-Szenarien liefern die
deklarierten Zustände; Sparse- und Malformed-Fälle bleiben technisch
`INDETERMINATE` und erzeugen keine `Relation`.

Der synthetische Skalierungstest ergänzt 10.000 nicht angeforderte Records je
Evidence-Tabelle. Der Read lädt trotzdem nur die drei angeforderten Records
über genau drei gefilterte SQL-Abfragen. SQLite verwendet alle drei Indizes
aus `0006_ebook_evidence_lookup_indexes`; der isolierte Read blieb unter dem
Regression Guard von zwei Sekunden. Feste Grenzen von 1.024
`ToolExecution`-, 16.384 `ToolResult`- und 4.096 `Fingerprint`-Records
verhindern eine unbeschränkte Historienladung.

Die gezielte Korpus-, Evidence-, Migrations- und Vergleichssuite bestand mit
12 Tests in 2 Minuten 39 Sekunden. `ruff check .` war erfolgreich; Mypy
prüfte 77 Source-Dateien ohne Befund. Der vollständige Stand bestand alle 229
Pytest-Tests in 15 Minuten 46 Sekunden.

Das Wheel
`C:\rep\artifacts\FolioTone\w3-014-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`8c39c43917d55fbd7e241cc6b4610afc64642a0f5b92b3032f8f92fc8605a3a3`
und enthält `persistence/evidence_queries.py`, Alembic
`0006_ebook_evidence_lookup_indexes` sowie den aktualisierten
Paarvergleich.

**Empirisch für W3-015:** Sieben gezielte Batch-Integrationstests bestätigen
den stabil gefilterten Multi-Format-Plan, kontrolliertes `--max-items`-
Unterbrechen, exaktes Resume ohne Wiederholung abgeschlossener Items,
per-File-Fehlerfortsetzung ohne Pfadleck, eine Workergrenze, Lease-Konflikt und
stale Claim Recovery sowie `Ctrl+C`-Resume. Der synthetische Skalierungsfall
plant 1.201 Beobachtungen über genau einen gestreamten SELECT und drei
begrenzte Inserts mit 500, 500 und 201 Items. Die Suite bestand in 1 Minute
20 Sekunden.

Die fünf gezielten CLI-/Bootstrap-Tests bestanden in 28 Sekunden. Sie prüfen
eine kontrollierte Teil-Invocation, Resume, path-freie Summen, unveränderte
Source-Dateien und die Ablehnung beschreibbarer Runtime-Pfade innerhalb des
Source Root. Der thread-sichere, ausschließlich im Batch-Modus aktivierte
Tool-Versionsprobe-Cache bestand seinen erneuten Parallelitätstest. Ruff war
für den aktuellen Source-Stand erfolgreich; Mypy prüfte 82 Source-Dateien
ohne Befund. Der vollständige W3-015-Stand bestand mit Python 3.12.10 alle
239 Pytest-Tests in 18 Minuten 43 Sekunden. Der maschinenlesbare JUnit-Bericht
liegt außerhalb von Git unter
`C:\rep\artifacts\FolioTone\w3-015-test-results\pytest-full.xml`.

Das Wheel
`C:\rep\artifacts\FolioTone\w3-015-wheel-01\foliotone-0.1.0-py3-none-any.whl`
ist 134.583 Byte groß, hat SHA-256
`3a4d98aa852769c83dc2019f1e986cbacd41931ec38558f38b02ef6b3fd99a2e`
und enthält Collection-Domainmodell, Persistenz, Workflow und Alembic
`0007_ebook_collection_batches`.

**Remote für W3-015:** Commit
`9a6b2d1ace10b1ef57c4402439ba782ede233b04` bestand in PR #25 Ruff, Mypy,
239 Pytest-Tests und alle Docker-Smoke-Schritte. Der PR wurde als Merge-Commit
`fe3672a7002137859607dacb12072eeae35e268a` nach `main` übernommen; GitHub
Actions Run `31900550819` war erfolgreich. Die dabei sichtbare dreifache
Vollausführung durch Branch-Push, Pull Request und Main-Push wird im
nachfolgenden CI-Vertrag auf einen autoritativen PR-Gate plus kurzen
Post-Merge-Vertrag reduziert.

**CI-Ausführungsvertrag:** Commit
`0237861bb1a02455fa65d2a5f754e46bb4530d92` bestand als PR #26 genau einen
vollständigen `quality`-Lauf. Merge-Commit
`111267f8a3c66e629cfd4b61d006c1731a9d9b12` löste auf `main` nur den
dreisekündigen `post-merge-contract` in GitHub Actions Run `31900986647` aus;
der vollständige Job wurde dort übersprungen.

**Empirisch für W3-016:** `ebook-collection-report/v1` erzeugt für einen
persistierten nicht aktiven Collection-Lauf byte-stabile private JSON-,
Review-CSV-, Exact-Duplicate-CSV-, Content-Variant-CSV- und Checksum-
Artefakte. Der Bericht enthält vollständige Format-/Analyse-/Quality-/Befund-
Summen, eine begrenzte priorisierte Review-Liste und getrennte technische
Kandidatengruppen. Rohe Fingerprints werden nicht ausgegeben; Findings
behalten ihre exakten verfügbaren `ToolExecution`-Quellen. Der Befehl öffnet
keine Source Media und erzeugt keine `Relation` oder Identitätsentscheidung.

Der gezielte Berichtstest bestand nach der finalen Projektionsprüfung in 21,33
Sekunden und prüft unter anderem
Determinismus, Begrenzung/Truncation, Provenance, Checksum-Integrität,
CSV-Formelneutralisierung, path-freie CLI-Ausgabe und unveränderte
synthetische Source-Dateien. Der direkt betroffene Head-Migrationstest bestand
in 19,38 Sekunden. Ruff war für die geänderten Source-/Testdateien
erfolgreich; Mypy prüfte 85 Source-Dateien ohne Befund. Ein weiterer
vollständiger lokaler Pytest-Lauf wurde gemäß dem schlanken Prüfvertrag nicht
wiederholt; der vollständige Gate läuft einmal am Pull Request.

Das Wheel
`C:\rep\artifacts\FolioTone\w3-016-wheel-01\foliotone-0.1.0-py3-none-any.whl`
ist 147.477 Byte groß, hat SHA-256
`7b69ea169d1f07adfe1780a4acc91ee19ef6298b51237c45dc85142a164a0482`
und enthält Report-Query, Workflow, CLI-Anbindung und Alembic
`0008_ebook_collection_reports`.

**Empirisch für W3-017 Scan-Recovery:** Der abschließende gezielte Verbundlauf
bestand 25 CLI-, Resume-, Lease-, Migrations-, Persistenz- und
Dokumentationsvertrags-Tests in 2 Minuten 35 Sekunden. Er prüft insbesondere
die Blockierung einer aktiven Lease, die einmalige Recovery nach Ablauf, den
Schutz gegen einen nachträglichen terminalen Write des früheren Besitzers, das
Upgrade eines ungeleasten `RUNNING`-Laufs aus Revision `0008`, die CLI-Lineage
und unveränderte synthetische Source-Dateien. Ruff war für Source und direkt
betroffene Tests erfolgreich; Mypy prüfte die vier geänderten Kern-/CLI-Module
ohne Befund. Der vollständige Gate läuft genau einmal am Pull Request.

**Empirisch für W3-017 Kandidaten-Hash-Performance:** 13 gezielte Kandidaten-,
Migrations-, Query-Plan- und Dokumentationsvertrags-Tests bestanden in 1 Minute
28 Sekunden. Sie prüfen drei historische Scan-Generationen, genau eine schwere
Snapshot-Materialisierung trotz Batchgröße 1, widersprüchliche Quick-Evidence,
Resume, per-File-Fehler, das Upgrade von `0009` auf `0010` und die tatsächliche
Verwendung des neuen Lookup-Index. Ruff war für alle geänderten Source- und
Testdateien erfolgreich; Mypy prüfte die drei betroffenen Source-Module ohne
Befund.

Ein zusätzlicher ausschließlich synthetischer lokaler Skalierungscheck mit
100.000 historischen Quick-Fingerprint-Zeilen und drei aktuellen Dateien
benötigte 0,395 Sekunden für Kandidatenauswahl sowie zwei begrenzte
Hash-Batches. Die Projektion lieferte genau eine aktuelle Gruppe mit zwei
Beobachtungen und keinen Rest. Der vollständige Gate bleibt dem Pull Request
vorbehalten.

**Empirisch für W3-017 Kandidaten-Hash-Lease und -Heartbeat:** Der gezielte
Verbundlauf bestand 26 Lease-, Status-, Kandidaten-, Migrations-, Persistenz-
und Dokumentationsvertrags-Tests in 3 Minuten 56 Sekunden. Er prüft genau einen
Besitzer bei konkurrierender Acquisition, root-parallele Läufe, stale Takeover
mit gefenceten Writes, Lease-Verlängerung, atomaren Rollback von Fingerprints
und Zählern, pfadfreie read-only Statusabfragen sowie das Upgrade von `0010`
auf `0011` ohne neue Fingerprint-Eindeutigkeit. Ruff war für Repository,
Source und betroffene Tests erfolgreich; Mypy prüfte die vier geänderten
Kern-/CLI-Module ohne Befund. Der vollständige Gate läuft genau einmal am Pull
Request.

**Empirisch für W3-017 Runtime-Beobachtbarkeit und Abschlussprüfung:** Ein
kombinierter gezielter Lauf bestand 30 Persistenz-, Lease-, Kandidaten-Hash-,
Collection- und Postscan-Verifikationstests in 7 Minuten 2 Sekunden. Er deckt
echte SQLite-Read-only-Verbindungen, Keeper-Ausfall und Lease-Erneuerung bei
blockiertem Einzelhash, `KeyboardInterrupt`, einen harten synthetischen
Child-Prozessabbruch, bytegenaue Inventarprüfung und vollständige,
degradierte, ausstehende sowie ungültige Abschlusszustände ab. Nach der
dynamischen Bindung des Abschlussprüfers an den paketierten Alembic-Head
bestanden die fünf direkt betroffenen Unit-/Integrationstests erneut in 43,48
Sekunden; Ruff und Mypy waren für die betroffenen Dateien ohne Befund. Der
vollständige Gate läuft genau einmal am Pull Request.

**Empirisch für EB-01/E4 Root-Fencing:** Die gezielten Root-Lease-, Scan-
Resume-, Incremental-Index-, Collection- und Persistenzläufe bestanden 53
Integrationstests. Sie prüfen konkurrierende Owner, Cross-Workflow-
Blockierung, monotone Epoch und ABA-Schutz, atomaren Fence-Rollback,
path-freie Fehler, Keeper-Lifecycle, Schema-Constraints, Upgrade-Quiescence
und die Downgrade-Sperre bei aktivem Writer. Weitere Kandidaten-Hash-
Leasefälle waren bereits im direkt betroffenen 16-Test-Verbund grün. Alle
Daten sind synthetisch; Source Media und private Runtime-Datenbanken wurden
nicht geöffnet. Der vollständige Gate läuft genau einmal am Pull Request.

**Empirisch für EB-05 Candidate Blocking:** Der gezielte Domain-/Core-/SQLite-
Verbundlauf bestand 19 Tests in 66,45 Sekunden. Er prüft alle sieben
book-only Blockquellen, exakte Review-Fingerprint-Bindung, die Lineage des
neuesten abgeschlossenen Scans, harte Member-/Pairwise-Grenzen und eine
synthetische Exact-Duplicate-Gruppe mit 1.000 Mitgliedern ohne Paarliste.
Ruff war für das Repository erfolgreich; Mypy prüfte 109 Source-Dateien ohne
Befund. Alle Testdaten sind synthetisch; Source Media und private Runtime-
Datenbanken wurden nicht geöffnet. Der vollständige Gate läuft genau einmal
am Pull Request.

## Abgeschlossener W3-Stand und aktuelle Ausführungsfront

W2 ist abgeschlossen; `W3-001` bis `W3-016` sind abgeschlossen. W3-015 stellt
den fortsetzbaren Collection-Plan bereit. W3-016 ergänzt
`ebook-collection-report/v1`, die CLI `ebook-collection-report`, persistierte
Item-Ausführungs-/Befundprovenance und Alembic
`0008_ebook_collection_reports`. Berichtabfragen streamen sortierte
Kandidatendaten, halten nur begrenzte Detailmengen und weisen vollständige
Gesamtzahlen sowie Kürzungen aus.

`W3-017` ist `DONE`: Der reale read-only Vierformat-Pilot ist technisch
erfolgreich. Normale Wiederholungen verwenden exakte Evidence, ohne externe
Analyzer erneut zu starten. Der reale Collection-Pilot deckte dabei einen
collection-weiten `Fingerprint.list_all()`-Engpass im Reuse-Lesepfad auf; der
Lookup ist nun observation-spezifisch, begrenzt und indexgestützt.
Ein externer harter Abbruch des realen Scanners hinterließ außerdem einen
verwaisten `RUNNING`-Datensatz. Die Lease-/Heartbeat-Recovery schützt neue
Läufe gegen konkurrierende Übernahme und erlaubt die ausdrückliche atomare
Wiederherstellung abgelaufener oder älterer ungeleaster Läufe.
`--plan-per-format` erzeugt begrenzte heterogene
Collection-Pläne; `ebook-hash-candidates` bestätigt nur mehrfach belegte
Quick-Gruppen mit vollständigem SHA-256 und ist durch denselben Aufruf
fortsetzbar. Der reale Vollhashlauf belegte zusätzlich einen mehrstündigen
SQL-Engpass vor und nach dem Datei-I/O. Die aktuelle Implementierung
materialisiert deshalb den current-scan-first Kandidaten-Snapshot einmalig,
verwendet danach nur noch indexgestützte Temp-Keyset-Batches und gibt
pfadfreie Phasen- und Batch-Fortschritte sofort aus. Rootweite persistente
Run-Leases verhindern parallele Kandidaten-Hashläufe; gefencete atomare
Batch-Writes und ein separater Lease-Keeper schließen Writes eines stale
Vorgängers aus. `ebook-hash-status` macht Phase, Heartbeat und Zähler ohne
Source-Pfad sichtbar. Der Statusbefehl verwendet SQLite `mode=ro`, erzeugt
keine Verzeichnisse und bietet zusätzlich einen stabilen pfadfreien
JSON-Vertrag.
`ebook-inventory-report/v1` erzeugt aus einem abgeschlossenen Scan
bereits ohne Tiefenanalyse vollständige Format-/Byte-Summen, Hash-Abdeckung,
offene Quick-Kandidaten und begrenzte Exact-Duplicate-Details als
deterministische private Artefakte. `ebook-postscan-verify` prüft den
paketierten Schema-Head, die gemeinsame Scan-/Hash-/Collection-Lineage, die
Inventarartefakte bytegenau und die begrenzte Formatabdeckung über dieselbe
echte Read-only-Verbindung, ohne Source Media zu öffnen. Der vollständige
private Inventar-/Collection-Lauf und Bericht bleiben als `OPS-001` ein
getrenntes lokales Betriebsverfahren und sind kein Entwicklungs- oder CI-Gate.
EB-04, EB-06, EB-07 und EB-08 sind abgeschlossen. EB-07 liefert die persistierte
read-only Reconciliation, den pfadfreien CLI-Report und die vollständige
read-only Capture-Orchestrierung. EB-08 liefert den nicht ausführbaren,
content-addressed ConsolidationPlan einschließlich read-only Report und
statischem Non-Execution-Gate. FG-03A/EB-03A und EB-03B sind abgeschlossen.
In der getrennten Archivstrecke sind FG-A, S-EBA-01 bis S-EBA-07,
FG-A-RUNTIME, S-EBAR-01 bis S-EBAR-03A, FG-A-IMAGE,
FG-A-RUNTIME-AVAILABILITY, EBAR-04, S-EBAR-02A und S-EBAR-02B abgeschlossen.
FG-A-STORAGE-FAMILY und FG-A-FORMAT-LOCK sind abgeschlossen; S-EBAR-02C,
EBAR-05, S-EBAR-05A, S-EBAR-06A und S-EBAR-04Q sind auf `main`. ADR-0050
hält reale Extraction mangels Backend gesperrt. ADR-0051 entscheidet die
unabhängige read-only Wrapperstrecke; S-EBAR-W01 bis S-EBAR-W04 sind auf
`main` abgeschlossen. ADR-0052 entscheidet die immutable Archive-Persistenz;
S-EBAR-07, FG-A-COLLECTION-ORCHESTRATION, S-EBAR-08A bis 08D und EBAR-09 sind
abgeschlossen. ADR-0054 schließt das begrenzte FG-A3-MATCHING; S-EBA3-01 bis
S-EBA3-03 sind auf `main` umgesetzt. Sie liefern den reinen
Source-Dependency-Vertrag, bounded Query-/Store-Revalidierung und die strikt
nicht ausführbare Planintegration. Member-Byte-Identity,
EA9/EA10-Abschluss und Source-Operations bleiben getrennt. Reale
Passwortversuche bleiben bis FG-A-SECRET blockiert. W10 erlaubt ausschließlich
die in ADR-0056 dokumentierte Interim-Ein-Datei-Quarantäne; die atomare
No-Replace-Härtung bleibt als `FG-W10-MOVE-BACKEND` getrennt geplant. Music W4
bleibt bis nach den drei book-only Produktprojektionen zurückgestellt. Die
Produktoberfläche bleibt ausschließlich die CLI.

ADR-0055 und S-EBAR-07A schließen den historischen W3-019-Vertrag ab.
Archive-/Volume-Evidence, Missing-Volume-Findings, der pfadfreie
Collection-Bericht und ein insert-only, scan- und archivegebundener
Sidecar-Inventarsnapshot sind umgesetzt. Das Inventar speichert weder
Basename/Pfad noch Inhalt oder Secret und erweitert weder Toolstatus noch
CLI-Profil oder Ausführungsauthority. ADR-0056 entscheidet inzwischen das
enge W10-Vertragsgate für Quarantäne. S-W10-01 bis S-W10-04 sind
abgeschlossen: reine Authorization-/Eligibility-Verträge, immutable
Persistenz, Interim-Executor und read-only Status sind vorhanden. Der
Capability Resolver aus S-W10-05A, die current-state-gebundene
`quarantine-authorize`-CLI aus S-W10-05B, das gefencete, einmalige Execute aus
S-W10-05C und die no-move Exact-State-Recovery aus S-W10-05D sind ebenfalls
umgesetzt. Damit ist `W10-005` abgeschlossen.

ADR-0058 legt die aktuelle reguläre Produktfolge fest. `CS-01` ist
abgeschlossen und erzeugt `collection-state/v1` als immutable, rebuildbare
book-only Projektion. Der Builder bindet technische, Analyse-, Resolution-,
Classification-, Matching-, Review-, Calibre-, Archive-, Consolidation- und
Quarantäne-Evidence an genau einen abgeschlossenen `ScanRun`. Zwei
deterministische Keyset-Pässe erkennen zwischenzeitlich veränderte Evidence;
Persistenz und idempotente Wiederverwendung erfolgen atomar. `CS-02` ist
ebenfalls abgeschlossen. ADR-0059 bindet den deterministischen Snapshot-Diff,
den festen Query-AST und den durch Migration `0024` insert-only persistierten
Metadata-FTS-Index. `CS-03` ist ebenfalls abgeschlossen. ADR-0060 bindet
sieben feste Health-Dimensionen, Finding-Literale, Coverage-/Statusreduktion,
bounded opaque Samples und einen reproduzierbaren Baseline-Vergleich.
Migration `0025` persistiert die Projektion insert-only; der Report bleibt
echte SQLite-Read-only-Ausführung. Die kanonische Ausführungsfront steht
ausschließlich in `BACKLOG.md`.

**Empirisch für CS-01:** Die 16 dedizierten Contract-, Migrations-,
Persistenz-, Rollback-, Retry-, Collision-, Idempotenz-, Staleness-, Read-only-,
Privacy- und statischen Sicherheitsfälle bestanden. Der betroffene
Persistenz-/Planungsverbund bestand 60 Tests; nach der Volltest-Triage
bestanden die 32 direkt relevanten CollectionState-, Bootstrap- und
Dokumentationsfälle erneut. Nach Integration des parallelen S-W10-05A-
Commits bestand der exakte rebased Head 73 betroffene Tests; ein
hostprivilegabhängiger Symlink-Fall wurde übersprungen. Ruff war repositoryweit
ohne Befund; Mypy prüfte 194 Source-Dateien erfolgreich.

Der vollständige lokale Pytest-Lauf bestand 1.751 Tests und übersprang neun.
48 Windows-Fehler traten auf: Ein CS-01-eigener Bootstrap-Vertrag wurde
korrigiert und gezielt grün nachgewiesen. Die verbleibenden 47 Fehler
entsprechen exakt der bereits auf unverändertem `main` dokumentierten
Windows-Baseline: CRLF verändert bytegehashte Archive-Evidence und die
Windows-Laufzeit ergänzt erwarteten Toolpfaden den `\\?\`-Präfix. Alle Daten
waren synthetisch; Source Media, private Runtime-Datenbanken, Tools, Provider
und Netzwerk wurden für CS-01 nicht verwendet. Der kanonische vollständige
PR-CI-Gate steht für den stabilen Wave-Head noch aus.

**Empirisch für CS-02:** 28 dedizierte Contract-, Migration-, Diff-, FTS-,
AST-Limit-, Pagination-, Privacy-, Read-only-, CLI- und statische
Sicherheitsfälle bestanden. Der synthetische Skalierungsfall materialisierte
600 Dokumente und acht selektive Treffer; die begrenzte Suche blieb unter der
festen Drei-Sekunden-Grenze und der SQLite-Plan verwendete den FTS5-Virtual-
Table-Index. Der betroffene Persistenz-, Bootstrap- und
Dokumentationsverbund bestand am finalen lokalen Stand 98 Tests. Eine zunächst
fehlende FTS-Tabelleninventarisierung sowie nicht als Migration benannte
Migrationsszenarien wurden korrigiert und in diesem Verbund grün nachgewiesen.
Repository-Ruff, die statischen Vertragstests und Mypy für 201 Source-Dateien
waren ohne Befund.

Der vollständige lokale Pytest-Lauf bestand 1.788 Tests und übersprang zehn.
Die verbleibenden 47 Fehler entsprechen exakt der bereits auf unverändertem
Windows-`main` dokumentierten Baseline: CRLF verändert bytegehashte Archive-
Evidence und die Windows-Laufzeit ergänzt erwarteten Toolpfaden den `\\?\`-
Präfix. Keine CS-02-Datei und keine neue Fehlersignatur war betroffen. Der
vollständige PR-CI-Gate wird für den stabilen Head getrennt nachgewiesen.

**Empirisch für CS-03:** Die elf neuen Contract-, Migrations-, Persistenz-,
Rollback-, Idempotenz-, Vergleichs-, CLI-, Privacy-, Read-only- und statischen
Sicherheitsfälle wurden mit ausschließlich synthetischen Daten grün
nachgewiesen. Sechs unmittelbar betroffene Regressionen für Migrations-Head,
`CollectionState`, Migration `0024`, Backfill und Query-Index-Bindung sind
ebenfalls grün. Der fokussierte Ruff-Lauf war ohne Befund; Mypy prüfte die vier
neuen Source-Module erfolgreich. Nach Aufnahme des kanonischen Schreibplans
bestanden zusätzlich 15 betroffene Planungs-/Dokumentationsverträge.
Entsprechend `TEST_POLICY.md` und der ausdrücklichen Ressourcenanforderung
wurde keine weitere vollständige lokale Suite gestartet. Der vollständige
PR-CI-Gate bleibt genau ein Lauf auf dem stabilen Head und ist Voraussetzung
für den Merge.

## Nicht implementiert

Noch nicht vorhanden sind unter anderem:

- weitere Formate außerhalb der expliziten EPUB/MOBI/AZW/AZW3-Text-Allowlist
  sowie alle Music-ToolProvider;
- vollständiger Authority-/Alias-Review-CLI und Music-Review-Workflow;
- eine weitergehende Classification Engine über den abgeschlossenen EB-04-
  Assertion-/Projection-Vertrag hinaus;
- Music- und medienübergreifende Matching-Profile; das book-only Offline-
  Matching für `EXACT_DUPLICATE`, `SAME_EDITION` und `SAME_WORK` ist
  implementiert;
- operativer vollständiger privater Sammlungslauf gemäß `OPS-001` und
  zusätzliche qpdf-Struktur-Evidence;
- reale Archive-Extraction und Secretübergabe; read-only Runtime,
  Archive-Persistenz und Collection-Orchestrierung sind abgeschlossen;
- medienübergreifende Classification- und kanonische Relation-Projektion über
  den book-only EB-04-Vertrag hinaus;
- portable Knoten-/Objektreferenzen, Austauschpakete, Multi-Instanz-Merge,
  Trust-/Conflict-Regeln sowie jede eingebettete oder externe
  Bibliothekskennzeichnung; ADR-0042 ist nur `Proposed`;
- weitere externe Knowledge Provider über den implementierten Open-Library-
  Slice und den persistierten Provider Cache hinaus;
- atomarer generalisierter No-Replace-Move, Quarantäne-Rollback, Purge und
  Verzeichnisbereinigung; die enge Interim-Quarantäne einschließlich Execute
  und no-move Recovery sowie der begrenzte EPUB-Titelwriter sind operativ
  vorhanden, weitere Writer bleiben operation-spezifisch geschlossen;
- Web-API, Desktop-Oberfläche oder Dashboard; die aktuelle Produktoberfläche ist gemäß ADR-0016 ausschließlich die CLI.

## Sicherheitsgrenze

ADR-0056 erlaubt den engen Interim-Executor für genau eine ausdrücklich
autorisierte reguläre Datei im selben vom Betriebssystem gemeldeten
Filesystem. Die Ziel-Abwesenheitsprüfung vor `os.rename` ist nicht atomar;
der Executor bietet weder Copy+Delete noch Cross-Volume-Fallback und keine
allgemeine Move-/Rename-Schnittstelle. Getrennt davon erlauben ADR-0063 und
ADR-0064 ausschließlich den vollständigen EPUB-3-Titelwriter-Vertrag.

`DELETED`, `FileRelocationCandidate` und Scan-Resume sind ausschließlich
Analyse-/Orchestrierungszustände. W9 erzeugt weiterhin ausschließlich
dauerhaft nicht ausführbare `ConsolidationPlan`-,
`MetadataCorrectionPlan`- und `EbookOperationRecipePlan`-Einträge. Atomarer
No-Replace-Move, Rollback, Purge, Metadaten-/Sidecar-/Calibrewrite,
Archive-Umschreibung und Verzeichnisbereinigung bleiben operativ nicht
verfügbar. ADR-0061 erlaubt ihre getrennte Entwicklung, ersetzt aber keines
ihrer technischen Gates oder eine konkrete Runtime-Authorization.
