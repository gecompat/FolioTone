# Handover / Fortsetzungsleitfaden

## Orientierung

FolioTone ist eine Orchestration- und Reconciliation-Plattform für große E-Book- und Musiksammlungen. Das Projekt kombiniert Filesystem-Evidenz, etablierte Spezialwerkzeuge, strukturierte Wissensquellen, Entity Resolution, Classification und Fingerprints in einem Provenance-erhaltenden Modell.

W0-013 integriert AI Repository Foundation `1.2.0` semantisch. Vor
Projektarbeit ist über den verwalteten Block im Root-`AGENTS.md` die
namespacete Baseline unter `.ai/foundation/` zu lesen; für Projektfakten,
Domain, Architektur, Status und bewusst strengere Privacy-, Test-, Git- und
W10-Grenzen bleiben das Root-`AGENTS.md` und seine FolioTone-Einstiegspunkte
autoritativ. ADR-0068 dokumentiert die Klassen des Abgleichs. Die vorhandenen
Copilot-/Junie-Adapter, `LICENSE.md` und der geschützte README-Lizenzblock
wurden nicht ersetzt. Ein Foundation-Update erfordert erneut einen
semantischen Review; der repository-only Fresh-Agent-Transfer ist noch
`pending manual validation`.

Der Foundation-Validator bestand im Profil `full` mit zwei Scope-Hinweisen
und ohne Warnung, Fehler oder Blocker; alle 14 übernommenen Core-/
Attributionsdateien sind bytegleich zum geprüften Foundation-Stand. Alle 62
FolioTone-Static-Contracts einschließlich der 12 direkt betroffenen
Dokumentationsverträge bestanden. Ruff war für die geänderte Testdatei grün,
`git diff --check` sauber; Root-`README.md` und `LICENSE.md` blieben
bytegleich. Mypy, Docker, Runtime-Tests, reale E-Books und private Daten waren
für den Governance-Scope nicht erforderlich. Der einmalige vollständige
PR-CI-Gate ist noch nicht ausgeführt.

FUT-011 ist durch ADR-0067 entschieden. Der akzeptierte erste Surface-Scope
ist `local-single-operator/v1`: loopback-only same-origin REST unter
`/api/v1`, deutschsprachige responsive Browser-UI, lokaler One-time-
Bootstrap für genau ein Username/Argon2id-Passwort-Administratorkonto,
serverseitige Sessions, Passwort-Reauthentisierung, höchstens 15 Minuten
gültige Private-/Operator-Grants, OpenAPI 3.1, Keyset-Pagination, Privacy,
append-only Audit und dauerhafte Jobs.

Die Prozessgrenze ist bindend. `surface-api` besitzt keinen Source-Media-
Mount und keine W10-Capability-Datei. Ein getrennter `analysis-worker`
verarbeitet read-only Aufgaben; nur der netzlose `operator-worker` darf einen
ausdrücklich registrierten W10-Command und dessen engste vorhandene
Capability erhalten. Joblease, HTTP-Session und `OperatorGrant` ersetzen
weder `ScanRootWriteLease` noch eine operation-spezifische Authorization.
Absolute Pfade bleiben auch in privaten `no-store`-Projektionen verboten.

Die freigegebene Reihenfolge lautet `S-FUT11-01` bis `S-FUT11-04`:
Application-Grenze/Media-Registry, lokale Auth/API/Worker-Basis, read-only
E-Book-UI und danach ausschließlich der ADR-0066-Same-Parent-Rename als erster
GUI-Writer. Titelwriter und Interim-Quarantäne benötigen spätere getrennte
Surface-Waves. Music, Bilder, Remote-/Mehrbenutzerbetrieb, MCP und alle
anderen Writer werden nicht aktiviert. Die ADR selbst implementiert noch
keinen Server, Benutzer, Worker oder Browserclient.

`S-W10-RN01` bis `S-W10-RN04` sind umgesetzt. Das ausschließlich durch
ADR-0066 freigegebene Same-Parent-`FILE_RENAME` besitzt jetzt Proposal,
private Preview, append-only Review, Plan, owner-only Capability, Probe,
Preparation, höchstens 15 Minuten gültige One-use-Authorization, feste
Execute-/Recovery-Matrix, Scan-Handoff, Folgescan, `CollectionState`,
immutable Reconciliation und SQLite-read-only Status.

Die öffentlichen Befehle sind `ebook-rename-authorize`,
`ebook-rename-execute`, `ebook-rename-recover` und `ebook-rename-status`.
Execute verlangt genau `CONFIRM EBOOK RENAME <Authorization-ID>` über eine
bounded, nicht geloggte `stdin`-Zeile. Nach unmittelbarer Verifikation wird
die Run-Lease vor dem neuen inkrementellen Vollscan mit genau einem
Hash-Worker freigegeben. Erst nach frischer physischer und persistenter
Revalidierung werden Reconciliation und `VERIFIED` oder `RECOVERED` atomar
gespeichert. Forward erhält die alte Source-Identität als `MISSING` und legt
für das historisch freie Target eine getrennte `NEW`-Identität an; Recovery
erhält die Source-Identität `PRESENT` und erfindet keine Target-Historie.

Migration `0033_local_surface_foundation` ist der aktuelle Head. Die
vorausgehende Rename-Reconciliation ist insert-only, content-addressed, pro Run eindeutig und an
genau einen abgeschlossenen Folgescan sowie `CollectionState` gebunden.
Statusausgaben bleiben ohne Locator, Basenames, Pfade, Hashes, Attribute,
Capability-Inhalte, Fences und Confirmation-Digests. Reale E-Books sind für
Tests nicht erforderlich; RN04 ist mit kleinen synthetischen Dateien und
temporären SQLite-Datenbanken prüfbar.

Lokal bestanden 93 Fälle des fokussierten Rename-/Migration-/Planfront-
Verbunds; ein einzelnes nach der Dokumentationsaktualisierung fehlendes
Planfront-Literal wurde korrigiert und gezielt grün wiederholt. Elf weitere
Dokumentations- und Testeffizienzverträge bestanden. Ruff war für alle
geänderten Python-Dateien grün, Mypy für 260 Source-Dateien ohne Befund und
`git diff --check` sauber. Ein irrtümlich mit Unix-Zeilenfortsetzungen
gestarteter PowerShell-Testaufruf wurde wegen potenziell zu breiter Collection
ohne Ergebnis abgebrochen; danach lief kein Pytest-Prozess weiter. Die
vollständige lokale Suite blieb unberührt. Der einmalige PR-CI-Gate ist auf
dem stabilen Head abgeschlossen: Head
`97791b6acef00548cc864bad85bf45e0d87db7e9` bestand Quality-Run
`32631068788` und Linux-Image-Run `32631068820`. PR #250 wurde als regulärer
Zwei-Eltern-Merge-Commit `dad693b7e07d34736141f64066c11b3527345eac`
integriert; Merge- und Feature-Tree sind identisch. Post-Merge-Run
`32631240306` bestand den kurzen Vertrag.

S-FUT11-01 ist implementiert. `application-contracts/v1` stellt
adapterneutrale `ApplicationCommand`-/`ApplicationQuery`-/Context-/Error-
Verträge, die Composition Root und eine E-Book-only Media-Line-Registry bereit.
Die bestehenden `ebook-tools-doctor`- und `library-health-report`-CLI-Wege
delegieren die ersten read-only Queries über diese Grenze, ohne ihre Ausgabe
oder Privacy-Projektion zu ändern. HTTP, Frontend, Auth, Jobs, Worker,
Migrationen und Source-Media-Mutation wurden nicht ergänzt.

17 fokussierte Application-, Doctor- und Library-Health-Fälle sowie 26
betroffene statische Planungs-, Safety- und Dokumentationsverträge bestanden.
Ruff war für den geänderten Python-/Testscope grün, Mypy für 264
Source-Dateien ohne Befund und `git diff --check` sauber. Docker, reale
E-Books, private Runtime-Daten und die vollständige lokale Suite waren für
diesen begrenzten Application-Scope nicht erforderlich. Der vollständige
PR-CI-Gate ist für den stabilen Head noch auszuführen.

S-FUT11-02 ist implementiert. FastAPI, Uvicorn und `argon2-cffi` sind
versionsbegrenzt gepinnt; FastAPI erzeugt den per Digest getesteten
OpenAPI-`3.1.0`-Vertrag. Migration `0033_local_surface_foundation` ergänzt
die lokale Auth-, Session-, Grant-, Audit-, Job-, Event- und Lease-Basis.
`surface-api`, `analysis-worker` und der netzlose, capability-freie
`operator-worker` sind getrennt konfiguriert. Es wurde kein W10-Command
registriert und keine Source-Media-Mutation ergänzt.

Zwölf gezielte Security-, API-, Migrations- und Job-Fencing-Tests bestanden;
Ruff und Mypy über 273 Quelldateien waren grün. Die vollständige lokale Suite,
der Compose-Start und der einmalige PR-CI-Gate sind noch auszuführen.
`S-FUT11-03` und `S-FUT11-04` beginnen erst nach erfolgreichem Abschluss
ihrer jeweiligen Vorgängerwave. Alle weiteren Writer bleiben hinter ihrem
eigenen W10-Gate; ADR-0067 leitet aus RN04 keine allgemeine Write-Capability
ab.

Für die FUT-011-Entscheidungswave bestanden lokal 21 Planungs-/
Dokumentationsverträge und 21 direkt betroffene W10-/Rename-/Titelwrite-/
`Library Health`-Sicherheitsverträge. Ruff war für die geänderte statische
Testdatei grün, `git diff --check` sauber. Ein erster Pytest-Aufruf ohne
`PYTHONPATH=src` endete vor der Collection; die korrekt konfigurierte
Zielauswahl bestand vollständig. Mypy, Docker, reale E-Books und die
vollständige lokale Suite waren für diesen docs-only Scope nicht erforderlich.
Der vollständige PR-CI-Gate läuft genau einmal auf dem stabilen Head und ist
vor dem Merge noch nachzuweisen.

## Historische Nachweise

`S-W10-RN01`, `S-W10-RN02` und `S-W10-RN03` sind umgesetzt. RN01 liefert
Proposal, private
Preview, append-only Review und den dauerhaft `NOT_EXECUTABLE` bleibenden Plan
für genau einen aktuellen Same-Parent-`FILE_RENAME`. RN02 bindet diesen Plan
an content-addressed Preparation und höchstens 15 Minuten gültige
Authorization, eine owner-geschützte einzelne Capability, erfolgreichen
persistenten Probe, Root-Fence, genau einen Run, immutable Backend-Binding und
höchstens 16 gapless append-only Events.

Migration `0031_ebook_rename_operations` ergänzt sechs insert-only Tabellen
und die beiden Lease-Owner `EBOOK_RENAME_PREPARATION` und
`EBOOK_RENAME_RUN`. Unmittelbar vor Authorization werden exakter W9-Plan,
neueste abgeschlossene Scan-/Observation-/Full-SHA-256-Lineage, aktueller
Review, alle fünf Dependencies samt Scope-Material, historische Target-
Abwesenheit, Probe und Fence geprüft. Die unter derselben Fence vorab
erhobene physische Source- und Target-Evidence wird unveränderlich gebunden;
RN03 erhebt und vergleicht sie unmittelbar vor jeder Mutation erneut.
Run, Binding und bestätigtes `PREPARED` verbrauchen die Authorization atomar.
Ein Retry kann nur denselben Run fortsetzen; `VERIFIED` und `RECOVERED`
bleiben RN04
vorbehalten. Trigger blockieren Update, Delete, Eventlücken, illegale
Übergänge und den Downgrade belegter Daten.

Capability-Zuordnung sowie Source-Root- und Probeverzeichnispfad stehen nur in
der owner-geschützten Datei `FOLIOTONE_EBOOK_RENAME_CAPABILITIES_FILE`; sie
werden nicht persistiert. Der read-only Status selektiert nur opaque IDs, Profile,
Zeitpunkte, Zustände und feste Finding-Codes. Locator, Basenames, Hashes,
Inodes, Attribute, Capability-Inhalte, Fences und Confirmation-Digests bleiben
ausgeschlossen. RN02 besitzt allein keinen Executor. RN03 ergänzt inzwischen
den internen Executor und Recovery, aber weiterhin keine neue CLI.

Das RN03-Backend ist fest auf Linux x86_64 plus glibc begrenzt. Es prüft Root
und privates Probeverzeichnis als dieselbe lokale `ext4`-, `btrfs`-, `xfs`-
oder `tmpfs`-Instanz, verwendet ausschließlich eigene zufällige
Probe-Fixtures und öffnet den Same-Parent-FD mit Raw-`openat2` beneath,
no-follow, no-magiclink und no-xdev. Source-Evidence umfasst Inode,
Linkanzahl eins, Mode, Owner, Group, Größe, `mtime_ns`, vollständigen SHA-256,
Format und bounded Xattr-Digest. Der einzige Forward- und gegebenenfalls
pre-success Reverse-Aufruf ist Raw-`renameat2(RENAME_NOREPLACE)` mit Source-
und Parent-`fsync`; es existiert kein Fallback.

Der Executor revalidiert aktuellen Plan, Capability, Probe, Backend-Binding,
Authorization und Fence unmittelbar vor dem Forward-Rename und stoppt bei
`IMMEDIATE_VERIFIED`. Recovery verwendet den unveränderlichen historischen
Plan und eine frische Run-Fence. Exakte unveränderte Source wird `CANCELLED`,
exakt verschobene Source wird vor Erfolg no-replace zurückbenannt und
`RECOVERY_VERIFIED`; jede uneindeutige Verteilung bleibt ohne weitere
Mutation `MANUAL_RECOVERY_REQUIRED`. RN04 besitzt exklusiv CLI, zweite
Bestätigung, Scan-Handoff, `CollectionState`, Reconciliation sowie die
terminalen Zustände `VERIFIED` und `RECOVERED`.

Eine Änderung an `ebook-file-rename-linux-renameat2-noreplace/v1`,
`ebook-file-rename-capability-probe/v1`, `linux-x86_64-glibc/v1`,
`ebook-file-xattrs/v1` oder der Capability-Konfiguration invalidiert die
gebundene Probe beziehungsweise Preparation. RN04 darf sie nicht still
wiederverwenden, sondern muss neu vorbereiten und autorisieren.

Für RN03 bestanden lokal 53 direkt betroffene Authority-, Capability-,
Executor-, Persistenz-, Safety-, Planfront- und Dokumentationsfälle in 16,05
Sekunden. Zwei native Raw-Syscall-/Recovery-Fälle sind unter Windows
erwartungsgemäß übersprungen und liefen im einmaligen Linux-PR-CI-Gate des
stabilen Heads. Ruff war für elf geänderte Python-Dateien grün, Mypy für fünf
geänderte Source-Dateien ohne Befund und `git diff --check` sauber.
Der vollständige lokale Testbestand, reale E-Books, private Runtime-Daten,
Docker und externe Tools wurden bewusst nicht verwendet. Der vollständige
PR-CI-Gate ist abgeschlossen: Head
`b0283d0215be75a26590c104eff9bb569be57111` bestand Quality-Run
`32628627937` und Linux-Image-Run `32628627929`; PR #249 wurde als
Zwei-Eltern-Merge `be825f39e12fdb11a478a3cd1436b587c1b8b27c`
integriert und Post-Merge-Run `32628774073` war grün.

Vor RN04 war kein weiterer Blocker offen. ADR-0066 bleibt `Accepted`, und RN03
ändert keine Provider-, Tool-, Lizenz- oder Netzwerkannahme.

63 direkt betroffene Unit-, Planungs-, Safety-, Dokumentations-, Persistenz-,
Migrations- und Testeffizienzfälle bestanden gezielt. Alle fünf RN02-
Persistenzfälle, Head-Schema, isolierter Datenbank-Clone und mehrstufiger
Lease-Downgrade sind enthalten. Ruff war für den geänderten Python-Scope grün;
Mypy war für sieben betroffene Source-Dateien ohne Befund. Zwei erste
Negativchecks fanden nur überlappende Trigger-Testannahmen beziehungsweise
eine noch nicht um RN02 ergänzte Head-Tabellen-Erwartung; nach Präzisierung
bestanden die einzelnen Wiederholungen. Die 23 Dokumentations-, Planfront-
und Safety-Verträge wurden nach der Statusaktualisierung erneut erfolgreich
ausgeführt; `git diff --check` war sauber. Ausschließlich synthetische Daten
wurden verwendet. Reale E-Books und die vollständige lokale Suite waren
nicht erforderlich.

Die vorangegangene RN01-Merge-Reconciliation ist abgeschlossen. Remote-Head
`857063e` bestand Quality-Run `32622295396` und E-Book-Toolchain-Run
`32622295434`. PR #247 wurde als regulärer Zwei-Eltern-Merge-Commit
`a08ed166f4fbb3db0f908023a2085237167709ac` integriert; Post-Merge-Run
`32622474216` war grün.

ADR-0066 schließt `FG-W10-RENAME` als docs-only Frontier-Gate. Akzeptiert ist
ausschließlich ein byte-identischer `FILE_RENAME` auf einen historisch
unbenutzten Basename im selben vorhandenen Parent und `ScanRoot`.
`FILE_REORGANIZE` bleibt wegen des breiteren Zwei-Parent-/Haltbarkeits-/
Verzeichnisvertrags hinter `FG-W10-REORGANIZE`. Das Gate selbst implementiert
noch keinen Writer.

Der umgesetzte feste Backendvertrag ist Linux x86_64 plus glibc,
`openat2`-Auflösung beneath/no-follow/no-xdev und genau ein
`renameat2(RENAME_NOREPLACE)` relativ zu demselben Parent-FD. Source und
Target müssen bereits NFC-kanonisch, casefold-verschieden und im engen
Basenamevertrag liegen; die Source ist regulär, besitzt Linkanzahl eins und
wird über Inode, Attribute, Format, Größe und Full-SHA-256 gebunden. Alle fünf
Recipe-Dependency-Achsen müssen durch aktuelle Coverage `KNOWN_NONE` oder über
einen expliziten aktuellen Dependency-Scope `NOT_APPLICABLE` sein;
`KNOWN_PRESENT`, `UNKNOWN` und bloß fehlende Zeilen blockieren. Nur eine
private einzelne Rename-Capability, eine höchstens 15 Minuten gültige
One-use-Authorization, zweite `stdin`-Bestätigung, Root-Fence und das
append-only Journal dürfen
später genau diesen Aufruf öffnen. Es gibt keinen `os.rename`-, Copy+Delete-,
Overwrite-, Shell-, ToolProvider- oder Cross-Device-Fallback.

Recovery storniert einen nachweislich unveränderten `PREPARED`-Run oder führt
vor `IMMEDIATE_VERIFIED` ausschließlich den atomaren Reverse-Rename aus.
Danach wird nur vorwärts über neuen Scan und Reconciliation abgeschlossen;
uneindeutige Verteilungen verlangen `MANUAL_RECOVERY_REQUIRED`. Der Folgescan
behält den alten Source-`FileRecord` als `MISSING` und erzeugt am neuen Locator
einen getrennten `NEW`-Target-`FileRecord`. Der immutable
`EbookRenameReconciliationSnapshot` verbindet beide, ohne Identitäten zu
vereinigen. Nach einem Reverse-Rename bindet die Recovery-Reconciliation
stattdessen die wieder aktuelle `PRESENT`-Source und den weiterhin historisch
freien Target-Slot, bevor `RECOVERED` terminal wird.

RN01 liefert Proposal, explizite private Preview, append-only Review und den
nicht ausführbaren Plan. RN02 liefert Authority, Capability, Probe, Fencing,
Persistenz und read-only Status; RN03 Backend, Executor und Exact-State-
Recovery. `S-W10-RN04` schließt Bedienoberfläche, zweite Bestätigung, Scan,
`CollectionState` und Reconciliation ab. Reale E-Books werden dafür nicht
benötigt. Vor REST/API/UI oder einem weiteren Writer steht nun ein eigenes
Entscheidungsgate.

Für das Gate bestanden 23 gezielt betroffene Planungsfront-, Dokumentations-
und W10-Safety-Verträge auf dem finalen Stand in 0,11 Sekunden. Ruff für die
einzige geänderte Python-Testdatei und `git diff --check` waren grün. Ein
vorausgehender
Pytest-Aufruf sammelte mangels lokalem `PYTHONPATH=src` keine Tests; die
identische kleine Auswahl wurde danach mit dieser repositoryüblichen
Importkonfiguration erfolgreich ausgeführt. Reale E-Books, private Runtime-
Daten, Source-Mutation, SQLite-Runtime, Docker, externe Tools und die
vollständige lokale Suite wurden ressourcenschonend nicht verwendet. Der
stabile Remote-Head `41f9ab9b178b59b97c59147d9bbd09b8f8c77729` bestand
Quality-Run `32619355986` und E-Book-Toolchain-Run `32619355944`. PR #245
wurde als `5dd9c5d5829c8241e5de709e705810cec8a5481c` auf `main`
integriert; Post-Merge-Run `32619517705` war ebenfalls grün.

`S-W9-007C` schließt `W9-007` mit dem echten SQLite-read-only Befehl
`ebook-operation-recipe-report` ab. Er nimmt genau eine opaque Plan-ID, öffnet
die bestehende Datenbank über `mode=ro` und `query_only=ON`, migriert nicht und
rehydriert den bounded insert-only Graph über denselben Store. Text und JSON
projizieren ausschließlich Plan-/Candidate-ID, Profile, Operationstyp,
Plan-/Execution-Status, Counts, Reviewstatus und Blockerliterale. Locator,
Source-/Target-/Evidence-IDs, Hashes, Material-, Format-, Processor- und
Zeitwerte bleiben ausgeschlossen; alle Fehler sind detailfrei.

Zehn neue beziehungsweise direkt betroffene CLI-, Privacy-, Read-only-,
Older-Schema-, Fehler-, Bootstrap- und statische Safety-Fälle bestanden in
14,38 Sekunden. Der ergänzende akzeptierte Reviewpfad bestand in 7,85
Sekunden. Gezieltes Ruff und Mypy waren grün. Reale E-Books, private
Runtime-Daten, Docker, externe Tools und die vollständige lokale Suite wurden
ressourcenschonend nicht verwendet. Zusätzlich bestanden die 22 gezielt
gebündelten Planungsfront-, Dokumentations-, Testeffizienz- und Report-Safety-
Fälle in 1,17 Sekunden. Der stabile Remote-Head
`e0f9645fc2ce851282776820735a6f710c038528` bestand Quality-Run
`32617699743` und E-Book-Toolchain-Run `32617699707`. PR #244 wurde als
`0a249e7230680aa03ac868d02065dab9ddb1e07d` auf `main` integriert;
Post-Merge-Run `32617838103` war ebenfalls grün.

`S-W10-RN01` setzt die rein nicht mutierende Proposal-/Preview-/Review-/Plan-
Wave nach dem akzeptierten ADR-0066-Gate um. RN02 ergänzt die Authority-/
Persistenzschicht, RN03 den internen Executor samt Recovery und RN04 die feste
Bedien-/Scan-/Reconciliation-Kette.

`S-W9-007B` ergänzt den reinen ADR-0065-Vertrag um die feste Review-Paarung,
Migration `0030_ebook_operation_recipe_plans` und zehn bounded insert-only
Tabellen für den vollständigen Candidate-/Plan-Graph. Der SQLite-Rebuild
erhält vorhandene Review-Historie, abhängige Consolidation-/Metadata-
Correction-Reviews und deren Trigger. Der neue Store revalidiert Content-
Identitäten, kanonischen Reducer, Source-/Full-SHA-256-/Evidence-/Dependency-/
Target-/Review-Lineage und idempotente Retries atomar, ohne Source Media,
Ziel-Slots oder Tools zu öffnen.

Sieben neue fokussierte synthetische Fälle bestanden zuletzt in 15,90 Sekunden;
darunter kapselt ein erzwungener SQLite-Child-Insert-Fehler private Parameter
pfadfrei und rollt Candidate sowie Children vollständig zurück. Ein fremder,
aber vorhandener Reviewentscheid wird als Recipe-Evidence ohne gebundene
Source-Datei fail-closed abgewiesen.
Nach 58 grünen betroffenen Regressionen wurde nur eine veraltete Schema-Head-
Erwartung gefunden; die gezielt wiederholten sechs Migrations-, Review- und
Fixture-Fälle bestanden in 17,40 Sekunden. Zusätzlich waren 19 statische
Planungs-, Dokumentations- und Testeffizienzverträge auf dem finalen Stand in
1,08 Sekunden sowie neun gezielt ausgewählte ältere Migrationspfade in zwei
begrenzten Läufen grün. Ruff war für den gesamten Source-Scope und alle
geänderten Tests erfolgreich; Mypy prüfte alle 243 Source-Dateien ohne Befund.
Reale E-Books, private Runtime-Daten, Docker, externe Tools und die
vollständige lokale Suite wurden ressourcenschonend nicht verwendet. Der
stabile B-Head `ab2318ab61a9bb7b79445faff8b874d1f1301038` bestand
Quality-Run `32616719567` und E-Book-Toolchain-Run `32616719527`. PR #243
wurde als `0c3e60c2688a8d902d4646ac38c8660539a4ab1d` auf `main` integriert;
Post-Merge-Run `32616869792` war grün.

ADR-0065 und `S-W9-007A` liefern den reinen Vertrag für dauerhaft nicht
ausführbare E-Book-Operationsrezepte. `EbookOperationRecipeCandidate` trennt
sechs feste Operationstypen und bindet abgeschlossene Source-Lineage,
vollständige Source-/Outputidentität, einen privaten bounded relativen
Ziel-Slot, fünf Dependency-Achsen sowie Processor-, Collision-, Workspace-,
Recovery- und Verification-Anforderungen. Nach einem kompatiblen append-only
Review reduziert der reine Planner daraus einen content-addressed
`EbookOperationRecipePlan`, dessen einziger Execution-State
`NOT_EXECUTABLE` bleibt.

`foliotone.ebook_operation_recipes` besitzt keine CLI-, Persistence-, Tooling-,
Adapter-, Filesystem-, Prozess- oder Tempabhängigkeit und keine öffentliche
mutierende Surface. Der statische Gate prüft zusätzlich bekannte externe
Write-Commands. Private relative Locator sind materieller Teil der Candidate-
Identität, fehlen aber in `repr` und im Planpayload. Für 48 fokussierte
synthetische Unit- und Non-Execution-Fälle waren Pytest, Repository-Ruff,
Mypy über 240 Source-Dateien, `compileall` und `git diff --check` grün; reale
E-Books, Runtime-Daten, SQLite, Docker und externe Tools wurden nicht
verwendet. Einschließlich der betroffenen Planungs-, Dokumentations- und
W10-Safety-Verträge bestanden 70 Fälle in 0,45 Sekunden. Der stabile A-Head
bestand Quality-Run `32614478464` und E-Book-Toolchain-Run `32614478470`;
PR #242 und Post-Merge-Run `32614626362` integrierten ihn auf `main`.

`S-W9-007C` ergänzt den SQLite-Read-only-Report und schließt `W9-007` ab.
Keines der Pakete erzeugt eine W10-Capability oder Authorization.

ADR-0061 hält seit 2026-08-22 die ausdrückliche Owner-Freigabe für die
kontrollierte Entwicklung der E-Book-Schreibstrecke fest. Die Gate-Wave ist
über PR #228 auf `main` integriert; der exakte PR-Head und der anschließende
Merge-Head bestanden ihre CI-Gates. Writer-Code und End-to-End-Tests dürfen
ausschließlich synthetische temporäre Dateien mutieren. Für reale Source Media
bleiben eine eigene technische Operations-ADR, die vollständige Capability-/
Authorize-/Execute-/Recovery-Kette und eine konkrete lokale Authorization
verpflichtend.

ADR-0062 schließt `FG-W9-006` und ist über PR #229 einschließlich grünem
Post-Merge-Contract auf `main` integriert. Vor jedem Metadata-Writer entsteht
zuerst ein immutable `MetadataCorrectionCandidate` als Gegenstand eines
append-only Reviews. Erst die neueste kompatible Review Decision wird in einen
separaten, content-addressed `MetadataCorrectionPlan` gebunden. Candidate und
Plan bleiben bounded, path-free und dauerhaft `NOT_EXECUTABLE`.

ADR-0063 schließt `FG-W10-METADATA-WRITE` für genau
`ebook-source-metadata-write/epub3-title-replace/v1`. Der einzige kompatible
Plan verwendet EPUB 3, `SOURCE_METADATA`, einen `title`-`REPLACE` und genau
einen ausgewählten Wert; Calibre-, Sidecar- und Archive-Dependencies müssen
nachweislich fehlen. Der FolioTone-eigene lexikalische Patch darf im Package
Document nur `dc:title` und `dcterms:modified` ändern. Alle anderen Package-
Document-Bytes und alle Nicht-Package-Entry-Inhalte bleiben erhalten.

calibre 9.13.0 wurde nicht als Writer gewählt. Sein `ebook-meta`-Setter wendet
das vollständige nichtleere Metadatenobjekt erneut an, erzeugt bei `--title`
zusätzlich `title_sort`, serialisiert das OPF neu und schreibt in-place;
`ebook-polish --opf` übernimmt ebenfalls einen vollständigen OPF-
Metadatensatz. `ebook-meta-opf/2` und EPUBCheck 5.3.0 bleiben unabhängige
read-only Validatoren.

`S-W10-MW01` implementiert den ersten Teilvertrag als reines Paket
`foliotone.metadata_write`. Der Preflight revalidiert den vollständigen W9-
Plan einschließlich seiner content-addressed Identitäten, Dependency-Achsen,
Input-Größe und Full-SHA-256. Zusätzlich bindet er positive EPUBCheck-5.3.0-
und `EPUB3`-Evidence an denselben Hash und prüft bounded Single-Disk-ZIP-,
OCF-, Container- und Package-Document-Verträge.

Der namespacebewusste lexikalische Scanner bestimmt genau die Textspannen
von `dc:title` und `dcterms:modified`, ohne das XML zu serialisieren. Der
Patch ersetzt nur diese Spannen. Der anschließende Diff verlangt identische
Entry-Reihenfolge, Archiv-/Membermetadaten sowie identische Inhalte aller
Nicht-Package-Entries. Das Paket nimmt und liefert nur Bytes und immutable
DTOs; es besitzt keine Datei-, Persistenz-, Tool-, CLI-, Capability-,
Authorization- oder Execute-Fläche.

`S-W10-MW02` ergänzt `epub3-title-private-staging/v1`. Der Builder erhält
keinen Source-Pfad, erstellt einen exklusiven privaten Ordner und kopiert den
Input einmal streaming-basiert mit vollständiger Hash-/Größenrevalidierung.
Beim Containerneuaufbau werden alle Nicht-Package-Member komprimiert roh
gestreamt; nur das gebundene Package Document wird mit der vorhandenen
Stored-/Deflate-Methode neu komprimiert. Reihenfolge, Namen, Flags,
Zeitstempel, Extra Fields, Kommentare und Attribute bleiben erhalten. Ein
zweiter streaming-basierter Read-back berechnet alle Memberhashes neu.

`FixedEpubTitleStagingValidator` führt ausschließlich gegen die privaten
Kopien je zwei feste `ebook-meta`-, Text- und Cover-Read-backs sowie einmal
EPUBCheck gegen den Output aus. Alle Prozesse laufen ohne Shell, mit Version
Policy, Timeout, isolierten Calibre-/Temp-Verzeichnissen und bounded privaten
Artefakten. Der Vertrag verlangt Titel-Read-back, identische Preserved Fields,
Text- und Coverfingerprints sowie `CONFORMANT` und hasht Input/Output danach
erneut. `EpubTitleStagedValidation` enthält keine Pfade oder Metadatenwerte und
wird nicht persistiert. Der Preserved-Field-Vergleich ignoriert ausschließlich
Calibres pro OPF-Export neu erzeugte `identifier:calibre`-Projektion; andere
Identifier bleiben prüfpflichtig, während der native Memberdiff alle Source-
Bytes erhält.

`S-W10-MW03` ergänzt die nicht ausführende Authority-Schicht. Der
content-addressed `EpubTitleWritePreparationSnapshot` bindet den verifizierten
privaten Output, den aktuellen W9-Plan, Input-/Outputidentität,
`dcterms:modified`, technische Profile/Versionen und Capability-ID an eine
kurz gehaltene Preparation-Fence. Der daraus erzeugte
`MetadataWriteAuthorizationSnapshot` ist höchstens 15 Minuten gültig und über
die Persistenz genau einmal verbrauchbar. Run und `CREATED`-Event entstehen
atomar unter einer neuen `METADATA_WRITE_RUN`-Lease; jedes Folgeevent bindet
die tatsächlich aktuelle Fence-Epoch und einen erlaubten gapless Übergang.

Migration `0027_metadata_write_operations` speichert Authorization, Run und
Events insert-only und sperrt Update, Delete sowie verlustbehafteten
Downgrade. Der Store revalidiert Planidentität, aktuelle Source-/Evidence-/
Dependency-Lineage und neueste kompatible Reviewfreigabe. Der private,
bounded Capability-Resolver verwendet eine owner-only geschützte no-follow
POSIX-Konfiguration; Pfade werden weder persistiert noch berichtet. Der
read-only Status enthält nur opaque IDs, Profile, Zeitpunkte und Zustände.
Source-/Output-Hashes, Metadatenwerte, Capability-Inhalte, Fences, Findings
und Digests bleiben privat.

Für `S-W10-MW03` bestanden vor der abschließenden reinen Test-Fixture-
Optimierung 71 fokussierte
synthetische MW01-/MW02-/MW03-, Capability-, Privacy-, Fencing-, Migration-,
Journal-, Status- und Non-Execution-Tests in 34,17 Sekunden. Ruff war für den
gesamten geänderten Python-Scope grün; Mypy prüfte 12 direkt betroffene
Source-Dateien ohne Befund. Auf dem finalen lokalen Stand bestanden zusätzlich
der Datenbank-Testeffizienzvertrag und die vier davon betroffenen
Integrationsfälle, insgesamt 5 Tests in 18,33 Sekunden. Reale E-Books und
produktive Runtime-Datenbanken wurden nicht verwendet. Provider-/Toolzugang
und Lizenzannahmen änderten sich nicht. Geänderte Writer-, Patcher-, Staging-,
Validator- oder Toolversionen machen eine vorhandene Preparation/Authorization
unbrauchbar und verlangen eine neue Vorbereitung. Die vollständige lokale
Suite wird nicht dupliziert; der stabile Pull-Request-Head erhält genau einen
vollständigen CI-Gate.

`S-W10-MW04` implementiert den internen Source-Commit Linux/Docker-only.
`epub-source-replace-linux-renameat2/v1` verlangt Linux x86_64 mit glibc,
no-follow Directory-FDs, dieselbe erlaubte lokale ext-, Btrfs-, tmpfs- oder
XFS-Instanz und einen erfolgreichen persistenten
`renameat2-capability-probe/v1`. Der vollständig verifizierte exklusive
Same-Directory-Draft wird per `RENAME_EXCHANGE` atomar mit der Source
getauscht; das Original wandert anschließend per `RENAME_NOREPLACE` unter
einen content-addressed Namen in den Capability-Recoverybereich. Es gibt
keinen Delete-, Copy+Delete-, Overwrite- oder Cross-Volume-Fallback.

Migration `0028_metadata_write_backend` bindet genau dieses Backend und
Probeprofil immutable und pfadfrei an den Run. Vor Draft und `PREPARED` gelten
weiterhin die live Plan-/Review-/File-/Authorization-Gates. Unmittelbar vor
dem Exchange prüft ein separates `PREPARED`-Gate dieselben aktuellen
Preconditions und die frische Root-Fence erneut. Nach einem begonnenen
Exchange darf der historische Recovery-Pfad Authorization-Ablauf oder ein
später geändertes aktuelles `FileRecord` ignorieren, aber nur unter einer
neuen Fence und nur für die exakten gebundenen Original-/Output-
Hashverteilungen. Uneindeutige Zustände werden ohne weitere Mutation als
`MANUAL_RECOVERY_REQUIRED` journalisiert.

Der MW04-Erfolgszustand ist absichtlich `ORIGINAL_PRESERVED`, nicht
`VERIFIED`. `S-W10-MW05` ist die nächste reguläre Wave: feste Authorize-/
Execute-/Recover-CLI, zweite Bestätigung über nicht geloggtes `stdin`,
unmittelbare Post-write-Verifikation, neuer Scan und Collection-
Reconciliation. Bis dahin gibt es keinen operativen Source-Metadata-Write-
Einstiegspunkt. Die echten Linux-tmpfs-/`renameat2`-Fälle bleiben lokal auf
Windows ausgelassen und sind durch den einmaligen vollständigen Linux-PR-CI-
Gate des stabilen Heads zu bestätigen.

`S-W10-MW05` implementiert inzwischen ADR-0064 und schließt genau diesen
Operatorpfad. Authorize erzeugt unter einer Preparation-Lease aus einem
vorhandenen aktuellen, reviewten Plan und der privaten Capability einen
vollständig validierten Output und eine höchstens 15 Minuten gültige
Authorization. Execute fordert exakt
`CONFIRM METADATA WRITE <Authorization-ID>` als eine nicht geloggte
`stdin`-Zeile; der persistierte Digest bindet zusätzlich Plan-ID,
Plan-Content-Hash und Capability-ID. Die tatsächliche Source wird nach dem
Exchange bytegenau und mit allen festen Validatoren erneut gelesen.

Nach `ORIGINAL_PRESERVED` erfolgt ein expliziter Lease-Handoff zu genau einem
vollständigen inkrementellen Scan mit einem Worker. Eine neue Observation mit
dem autorisierten Full-SHA-256 und der daraus gebaute `CollectionState` werden
unter einer neuen Run-Fence erneut physisch geprüft. Migration
`0029_metadata_write_reconciliation` persistiert diesen Snapshot immutable;
Reconciliation und `VERIFIED`-Event entstehen atomar. Recovery verwendet
dieselbe Folge für den Originalhash und endet bei `RECOVERED` ohne
`VERIFIED`. Die vier festen CLI-Kommandos sind in
`docs/operations/EBOOK_METADATA_WRITE.md` beschrieben; sie öffnen keine
anderen Felder, Formate oder Zielträger.

Für MW05 bestanden lokal 46 fokussierte Fälle; sieben Linux-/tmpfs-Fälle
blieben auf Windows erwartungsgemäß ausgelassen und 14 nicht betroffene Fälle
abgewählt. Zwei zusätzliche Composition-Tests für Runtime-Toolkonfiguration
und Engine-Freigabe nach fehlgeschlagener Erzeugung waren ebenfalls grün.
Der strikte Nachher-Zeitpunkt des Reconciliation-Scans sowie beide
vollständigen synthetischen Operatorpfade zu `VERIFIED` und `RECOVERED` wurden
nach den Härtungen gezielt erneut bestätigt. Der Head-Tabelleninventarfall
bestätigte Revision und neue Reconciliation-Tabelle.
Ruff und Mypy waren für den betroffenen Scope ohne Befund, `compileall` war
erfolgreich. Reale E-Books und produktive Runtime-Datenbanken wurden nicht
verwendet. PR #238 ist auf `main` integriert; der exakte stabile Head und der
anschließende Main-Run waren grün. Danach begann `W10-005`; die Wave bleibt von
`FG-W10-MOVE-BACKEND` getrennt.

Der erste PR-Gate bestand 2.030 Tests bei acht erwarteten Skips und scheiterte
ausschließlich an einer noch auf `W10-005 | READY` festgelegten statischen
Erwartung. Sie wurde auf die bereits dokumentierte kanonische Front
`W10-005 | NEXT` synchronisiert; Produktionscode war nicht betroffen. Der
korrigierte stabile Head bestand den vollständigen Gate vor dem Merge.

`S-W10-05B` implementiert inzwischen den mutationsfreien ersten Bedienpunkt
der Quarantänekette. `quarantine-authorize` nimmt nur Plan-ID, vollständigen
Plan-Content-Hash und Capability-ID entgegen. Vor dem insert-only Snapshot
werden der exakte aktuelle Plan, neueste Reviews, Dependencies, FileRecord und
FileObservation revalidiert; Keeper und Candidate werden als stabile reguläre
Einzeldateien streaming-basiert gegen Größe, Modified-Zeitpunkt und Full-
SHA-256 geprüft. Die SQLite-Transaktion prüft die Plan-Lineage ein zweites Mal.
Ausgabe und Fehler bleiben pfad-, dateinamen- und materialhashfrei. Authorize
ruft weder `os.rename` noch den Interim-Executor auf.

Lokal bestanden für 05B sieben neue Unit-, vier neue Integrations- und 24
direkt betroffene bestehende Fälle; ein hostabhängiger Symlink-Fall wurde auf
Windows ausgelassen. Zusätzlich bestanden 20 betroffene Planungs- und
Dokumentationsverträge. Repository-Ruff und Mypy für 234 Source-Dateien waren
grün. Es wurden nur synthetische temporäre Dateien und SQLite-Datenbanken
verwendet. Der stabile 05B-Head benötigt genau einen vollständigen PR-CI-Gate.

Der erste 05B-Gate stoppte nach grünen Install-, Ruff- und Mypy-Schritten bei
der Test-Collection, weil ein installiertes Fremdpaket das bisher implizite
lokale `tests`-Namespace verdeckte. Ein explizites `tests/__init__.py` behebt
nur diese Importauflösung; Produktionscode blieb unverändert. Die lokale
Collection fand danach 2.051 Tests fehlerfrei, und die vier neuen
Autorisierungs-Integrationsfälle blieben grün. Im zweiten Gate waren 2.042
Tests erfolgreich und acht erwartungsgemäß übersprungen; ausschließlich der
explizite Statusausgabe-Vertrag enthielt die neue
`quarantine-authorize`-Zeile noch nicht. Die Test-Erwartung ist nun mit der
bereits implementierten, mutationsfreien Statusausgabe synchronisiert. Der
finale Head `bb9ef78` bestand danach Quality- und Linux-Image-Gate. PR #239
wurde als Merge-Commit `5f5b068` auf `main` integriert; auch der Post-Merge-
Contract war grün.

`S-W10-05C` implementiert inzwischen den einmaligen Execute-Bedienpunkt.
`quarantine-execute` nimmt zusätzlich zur Authorization-ID dieselben opaque
Plan-/Hash-/Capability-Binder wie Authorize entgegen und fordert exakt
`CONFIRM QUARANTINE <Authorization-ID> <Plan-ID>` über eine begrenzte, nicht
geloggte `stdin`-Zeile. Vor dem Prompt wird die aktuelle Persistenz-Lineage
geprüft; danach werden Capability, Plan, Reviews, Dependencies, Keeper und
Candidate unter einer frischen `CONSOLIDATION_QUARANTINE_RUN`-Lease erneut
aufgelöst und vollständig revalidiert.

Run und bestätigtes `PREPARED`-Event entstehen in einer gefenceten
Transaktion, die die aktuelle Plan-Lineage ein weiteres Mal prüft. Der Unique-
Vertrag auf der Authorization macht sie genau einmal verbrauchbar. Erst danach
ruft der Workflow den vorhandenen Interim-Executor auf; es existiert kein
zweiter Move-, Copy-, Delete-, Callback- oder Toolpfad. Bei einem bereits
erzeugten oder nach `PREPARED` fehlgeschlagenen Run darf die feste
Fehlerprojektion dessen opaque Run-ID ausgeben, aber niemals Pfad, Dateiname,
Materialhash, Confirmation-Text oder Fence.

Eine abgelaufene Quarantäne-Lease vor `PREPARED` kann Execute nur in einer
sofort serialisierten SQLite-Transaktion mit erhöhter Fence-Epoch übernehmen,
wenn für ihre Owner-Run-ID kein persistierter Run existiert. Eine Lease mit
persistiertem Run bleibt auch nach Ablauf Recovery-only. Ein unerwarteter
Fehler ab dem Executor-Aufruf endet konservativ bei `MANUAL_REVIEW` und gibt
die opaque Run-ID für Status beziehungsweise Recovery aus.

Lokal bestanden 19 neue Confirmation-/CLI-/Lease-Unit-Tests, zehn neue
synthetische Execution-Integrationsfälle und 20 direkt betroffene bestehende
Quarantäne-Verträge. Die Tests verwenden nur temporäre synthetische Dateien
und SQLite-Datenbanken; reale E-Books und private Runtime-Daten wurden nicht
geöffnet. Ruff war für den geänderten Python-Scope grün. Ein vollständiger
Mypy-Lauf über 235 Source-Dateien war grün; nach der finalen Race-Härtung
wurden die beiden nochmals geänderten Source-Module erneut ohne Befund
geprüft. Zusätzlich bestanden 22 betroffene Planungs-, Dokumentations-, W10-
und Bootstrap-Verträge. Der stabile Head
`3ed588d5aca013bce47896e3716f3e5747121841` bestand Quality-Run
`32610844152` und Linux-Image-Run `32610844212`. PR #240 wurde als
`b86bc878f0e3000ba31d79f93573146149c58740` auf `main` integriert; auch
Post-Merge-Run `32610996492` war grün.

ADR-0056 wurde dabei nur an den bereits akzeptierten Schema- und
Ausführungsvertrag angeglichen: `confirmation_digest` liegt im atomaren
`PREPARED`-Event, die eindeutige Run-Bindung verbraucht die Authorization, und
eine preparedless abgelaufene Lease wird nur atomar ohne vorhandenen Run
übernommen. Es wurde keine zusätzliche Mutation entschieden.

`S-W10-05D` vervollständigt inzwischen `W10-005` mit
`quarantine-recover`. Die CLI nimmt ausschließlich eine opaque Run-ID. Der
Operator rehydriert bestätigten Run, Authorization, Plan, historisch
gebundenen Observation-Locator und Capability, erwirbt eine frische oder
sicher übernommene Same-Run-Lease und klassifiziert Source und Ziel erneut
gegen Modified-Zeitpunkt, Größe und Full-SHA-256.

Recovery führt selbst keinen Move aus. `PREPARED` plus exakte Source und
abwesendes Ziel wird nach einer zweiten Prüfung `CANCELLED`; bei abwesender
Source und exaktem Ziel werden nur fehlende `MOVED`-, `VERIFIED`- und
`COMPLETED`-Events append-only ergänzt. Jede andere Verteilung endet ohne
Dateisystemmutation bei `MANUAL_REVIEW`. Abgelaufene Authorization oder ein
später verändertes aktuelles `FileRecord` blockieren die historische
Beweissicherung nicht; ein unbestätigter niedriger `PREPARED`-Insert schon.
Die Erfolgsfolge ist auf `PREPARED -> MOVED -> VERIFIED -> COMPLETED`
gehärtet, sodass auch ein lückenloses widersprüchliches Journal vor jedem
weiteren Recovery-Event scheitert.

Auf dem 05D-Stand bestanden 14 synthetische Recovery-Matrix-
Integrationsfälle zusammen in 33,29 Sekunden, der zusätzliche Capability-
Ausfall in 8,98 Sekunden und 45 fokussierte Recovery-/CLI-/Bootstrap-/
Planungs-/Dokumentationsverträge in 1,24 Sekunden. Reale E-Books,
private Runtime-Datenbanken, die vollständige lokale Suite und Docker wurden
nicht verwendet. Der korrigierte stabile Head
`45dca9a9762eafeed8b46397595237c1bff75755` bestand Quality-Run
`32612809402` und Linux-Image-Run `32612809367`. PR #241 wurde als
`7c5f50ee298cc606c657da52bb361394365d84d2` auf `main` integriert; auch
Post-Merge-Run `32612937625` war grün. Danach begann W9-007 mit dem reinen
Operationsrezeptvertrag; er öffnet keinen weiteren Writer.

Der erste PR-Gate auf Head `6567a7ed2d5dbefecebc311ececa4445276e2271`
stoppte vor der Testausführung bei 2.099 gesammelten Tests, weil Unit- und
Integrationstest denselben Modulbasename `test_quarantine_recovery.py`
trugen. Der Unit-Test wurde ohne Produktionscodeänderung in
`test_quarantine_recovery_inspection.py` umbenannt. Danach waren die sechs
betroffenen Unit-Fälle und die vollständige lokale Collection aller 2.099
Tests grün. Der anschließend ausgeführte korrigierte PR-Gate ist im
vorhergehenden Absatz mit seinen finalen Run-IDs dokumentiert.

Für `S-W10-MW01` bestanden lokal 114 fokussierte neue und direkt betroffene
Unit-, Privacy-, Non-Execution- und Dokumentationsvertragstests in 0,57
Sekunden. Ruff war für das neue Paket und seine Tests grün; Mypy meldete für
die drei neuen Source-Dateien keine Findings. Die vollständige lokale Suite,
Docker-/Toolchain-Läufe, reale E-Books und produktive Runtime-Datenbanken
wurden nicht verwendet. Der stabile Pull-Request-Head benötigt genau einen
vollständigen CI-Gate.

Für `S-W10-MW02` decken fokussierte synthetische Tests Streamgrenzen,
Stored/Deflate, Data Descriptors, Metadatenerhalt, Kollisionen, Privacy und
alle unabhängigen Mismatch-Codes ab. Am finalen lokalen Stand bestanden 76
dieser direkt betroffenen Tests in 0,63 Sekunden. Ruff war für den geänderten
Python-Scope grün, Mypy prüfte 219 Source-Dateien ohne Befund und
`git diff --check` war sauber. Ein breiterer Windows-Lauf stoppte nach 71
erfolgreichen Fällen ausschließlich an der bereits dokumentierten
`\\?\`-Pfadpräfix-Baseline eines unveränderten Calibre-Analyzer-Tests; die
vollständige lokale Suite wurde nicht dupliziert.

Ein einzelner zusätzlicher Offline-Smoke führte den aktuellen Code über das
bereits gebaute gelockte Linux-Toolchain-Image tatsächlich durch `ebook-meta`
9.13, EPUBCheck 5.3.0, `ebook-convert` 9.13.0 und `calibre-debug` 9.13;
Outputstatus war `CONFORMANT`. Dabei wurde Calibres volatiler, bei jedem OPF-
Export neu erzeugter `identifier:calibre` sichtbar und anschließend eng aus
dem Preserved-Field-Projektionsvergleich ausgeschlossen. Reale E-Books wurden
nicht geöffnet. In dieser MW02-Welle erfolgte noch kein Linux-`renameat2`-
oder Source-Writer-Lauf; dieser Nachweis gehört inzwischen zu MW04. Der stabile
Pull-Request-Head erhält genau einen vollständigen Linux-CI-Gate.

`S-W9-006A` ist umgesetzt. `foliotone.metadata_correction` enthält die reinen
Candidate-/Plan-DTOs, fünf getrennte Zielträger, drei vollständige Dependency-
Achsen, eine bounded E-Book-Feldgrammatik, private mehrwertige Feldselektionen,
reine Reducer sowie deterministische UUIDv5-/`canonical-json/v1`-Identitäten.
Der Plan bildet feste Source-, Target-, Dependency-, Review- und Writer-
Preconditions sowie die Post-write-Verifikation ab, bietet aber ausschließlich
den Execution-State `NOT_EXECUTABLE` an.

`S-W9-006B` ist ebenfalls umgesetzt. Der Review-Core besitzt die fest gepaarten
Metadata-Correction-Literale. Migration `0026_metadata_correction_plans`
erhält bestehende Review-/Decision- und Consolidation-Review-Zeilen, ergänzt
14 normalisierte insert-only Tabellen mit bounded Child-Counts und verweigert
einen datenverlustbehafteten Downgrade. Der Store rehydriert den vollständigen
Graph bounded, prüft alle content-addressed Identitäten, den kanonischen
Reducer sowie Source-, Full-SHA-, Evidence-, Dependency-, Target- und neueste
Review-Lineage in einer kurzen Transaktion. Exakte Retries sind idempotent;
abweichende Payloads und fehlende oder fremde Lineage schlagen atomar fehl.

Private Werte werden ausschließlich in Runtime-Valuezeilen gespeichert und
nicht in Fehlermeldungen übernommen. Der Store besitzt keinen Pfadparameter,
öffnet keine Source Media und bietet keine Execute-/Apply-/Write-Fläche.

`S-W9-006C` ist umgesetzt und schließt `W9-006` ab.
`ebook-metadata-correction-report` liest genau einen Plan mit `mode=ro` und
`query_only=ON`. Seine Text- und JSON-Projektionen zeigen ausschließlich die
durch ADR-0062 erlaubten IDs, Profile, Statuswerte, den Plan-Content-Hash,
Zielträger, Format, Feldpfade, Operationen, Counts, Reviewstatus und
Blockerliterale. Private Werte, Pfade, Dateinamen, File-/Observation-/Root-IDs,
Source-/Target-Fingerprints und Evidence-Materialien werden nicht ausgegeben.
Der CLI-Pfad führt keine Migration aus und liefert für Bootstrap-, Schema-,
Plan- und interne Lesefehler nur feste pfadfreie Codes.

Die Reportintegration korrigiert außerdem den historischen Read-Path für
persistierte `MISSING`-Review-Snapshots ohne `ReviewItem`; andere Zustände
bleiben an ihre Review-Lineage gebunden. Am finalen lokalen Stand bestanden
41 fokussierte Report-, Privacy-, Schema-, Bootstrap-, Store-, Consolidation-
Regression- und statische Tests in 26,36 Sekunden. Ruff war für alle
geänderten Python-Dateien und Mypy für die drei betroffenen Source-Module
grün; `git diff --check` war ohne Befund. Die vollständige lokale Suite wird
nicht dupliziert; genau ein vollständiger PR-CI-Gate bleibt
Merge-Voraussetzung.

`FG-W10-METADATA-WRITE` ist durch ADR-0063 entschieden; `S-W10-MW01` bis
`S-W10-MW05` sind umgesetzt und schließen genau den begrenzten EPUB-
Titelwriter. `S-W10-05B` schließt Quarantäne-Authorize; `S-W10-05C` ist der
gefencete Execute-Slice und `S-W10-05D` schließt die no-move Recovery ab.
In `W9-007` sind `S-W9-007A` bis `S-W9-007C` umgesetzt; ADR-0066 und
`S-W10-RN01` bis `S-W10-RN04` sind ebenfalls abgeschlossen. Allgemeine Source-Media-
Mutation, Music, Bilder, REST-API und
grafische Oberfläche werden weder durch W9-006/W9-007 noch durch den einen
operation-spezifischen Writer aktiviert.

W0 bis W2 sind abgeschlossen. Der W2-Slice umfasst Incremental Index, Hashing, Filename-/Path-Kandidaten, konfigurierbare Parsing-Profile und eine generische read-only ToolProvider Runtime. `W2-004` ergänzt eine konservative, opt-in `DELETED`-Bestätigung. `W2-006` ergänzt konservative Move-/Rename-Kandidaten. `W2-007` ergänzt explizite Resume-Lineage für unterbrochene Scans, ohne einen instabilen Filesystem-Cursor einzuführen.

W3-026 schließt die operative Windows-Lücke Docker-first. Das explizite Skript
`scripts/provision-ebook-tools.ps1` baut über eine native Linux-Docker-Engine
oder WSL2 das gelockte E-Book-Toolchain-Image. `ebook-tools-doctor` prüft
calibre, Poppler, Java und EPUBCheck sowie die Readiness je EPUB, MOBI, AZW,
AZW3 und PDF, ohne Medien/Datenbank zu öffnen oder etwas zu installieren. Die
Anleitung steht unter `docs/operations/WINDOWS_EBOOK_TOOLCHAIN.md`.

Der lokale WSL2-Build wurde am 2026-08-21 mit Docker Engine 29.7.2 vollständig
ausgeführt. Der gehärtete Offline-Doctor im fertigen Image meldete sieben
bereite Komponenten und `READY` für alle fünf Formatprofile.

`W2-008` und `W2-009` sind vollständig validiert: Basisparser und konfigurierbare, versionierte Regex-Profile erzeugen ausschließlich Provenance-behaftete `FieldCandidate`-Werte und setzen keine kanonischen Metadaten. `W2-011` ergänzt begrenzte, strikte JSON-Auswertung aus `ToolArtifact`-Dateien und konservative Reanalyse-Entscheidungen. Der Docker-Build-Kontext ist auf die tatsächlich paketierten Anwendungsdateien beschränkt.

Die anfängliche Produktoberfläche war gemäß Benutzerentscheidung und ADR-0016
ausschließlich die CLI. `W3-001` und `W3-002` sind abgeschlossen: Die aktuelle
E-Book-Toolchain ist bewertet, und der erste read-only calibre-Metadaten-Slice
ist implementiert. `W3-003` ergänzt einen festen read-only calibre-EPUB-
Textpfad und einen FolioTone-eigenen normalisierten Fingerprint. `W3-004`
ergänzt feste Poppler-PDF-Metadaten-, Seiten- und Textpfade mit explizitem
`NO_TEXT`. `W3-005` erweitert die vorhandenen calibre-Pfade auf eine explizite
EPUB/MOBI/AZW/AZW3-Allowlist. `W3-006` ergänzt eine OPF2-/OPF3-Feld- und
Rollenprojektion mit provider-neutralen, Provenance-verknüpften Kandidaten.
`W3-007` ergänzt einen versionierten synthetischen Vergleichskorpus für Datei-,
Inhalts-, `Edition`-, `Work`- und Tool-Disagreement-Ground-Truth. `W3-008`
ergänzt feste EPUBCheck-JSON-Strukturvalidierung und provider-spezifische
akzeptierte Exitcodes. `W3-009` ergänzt eine quellisolierte
EPUB/MOBI/AZW/AZW3-Embedded-Cover-Extraktion, explizites
`NO_EMBEDDED_COVER` und einen versionierten FolioTone-dHash. `W3-010` ergänzt
den formatbewussten, einheitlichen CLI-Workflow `ebook-analyze`. `W3-011`
ergänzt dessen konservative exakte Evidence-Wiederverwendung, gezielten
Schritt-Retry und `--fresh`. `W3-012` ergänzt das separate versionierte
E-Book-Qualitätsprofil mit fünf Dimensionen und festen Befundcodes.
`W3-013` ergänzt den provider-neutralen read-only Evidence-Paarvergleich ohne
Relation oder Identitätsurteil. `W3-014` ergänzt den vollständig synthetischen
v2-Edge-Korpus und begrenzte, indexgestützte Evidence-Abfragen. `W3-015`
ergänzt die fortsetzbare Collection-Analyse über einen persistenten Snapshot-
Plan, begrenzte Worker und per-File-Fehlerfortsetzung. `W3-016` ergänzt
deterministische private Collection-Berichte, persistierte Befundprovenance
und begrenzte Duplicate-/Varianten-Kandidaten ohne Identitätsurteil. Auf
Benutzerentscheidung bleibt die Entwicklung bis zur Reife der E-Book-Pipeline
bei E-Books; `W3-017` einschließlich des E5-Performance-/Restart-Vertrags ist
abgeschlossen. Die lokalen Authority-Grundlagen, strukturierten Provider-
Verträge und E-Book-Klassifikationsverträge wurden mit `PR #36` bis `PR #39`
auf `main` integriert. EB-01/E4 ergänzt die gemeinsame Root-Write-Lease aus
ADR-0027 und Migration `0012`; Scan, Kandidaten-Hashing, Collection-Analyse
und Einzelanalyse sind damit für denselben `ScanRoot` atomar gefencet. Reale
Provider, Matching und die späteren Classification-/Relation-Review-Slices
bleiben offen. EB-02 ergänzt persistierte book-only Resolution Candidates,
Evidence-Links und append-only Authority-Entscheidungen. Music W4 bleibt
zurückgestellt.

Der reale `W3-017`-Scan zeigte zusätzlich einen Lifecycle-Gap: Ein externer
harter Prozessabbruch kann den Cleanup umgehen und einen `ScanRun` als
`RUNNING` hinterlassen. ADR-0025 und Alembic `0009_scan_run_leases` ergänzen
deshalb 30-Minuten-Leases, Heartbeats und eine explizite atomare Recovery für
abgelaufene oder aus älteren Versionen stammende ungeleaste Läufe.

Die per-Run-Leases bleiben zusätzliche Laufzeitbelege. Die gemeinsame
`scan_root_write_leases`-Tombstone-Zeile ist seit EB-01 das maßgebliche
Cross-Workflow-Fence. Migration `0012` darf nur bei vollständig ruhenden
Scan-, Candidate-Hash- und Collection-Writern ausgeführt werden; ungefencte
Legacy-`RUNNING`-Zustände werden nicht automatisch übernommen.

## Vor Änderungen lesen

1. `AGENTS.md`.
2. `docs/planning/PROJECT_STATUS.md`.
3. `docs/planning/BACKLOG.md`.
4. `docs/quality/DOCUMENTATION_STYLE.md` und `docs/quality/LANGUAGE_AND_TERMINOLOGY.md`, wenn Dokumentation berührt wird.
5. `docs/reference/GLOSSARY.md`, wenn fachliche Terminologie berührt wird.
6. Relevante Dateien unter `docs/architecture/` und `docs/decisions/`.
7. `docs/reference/EXTERNAL_TOOLS.md`, bevor ein konkreter externer ToolProvider implementiert wird.
8. `docs/reference/EBOOK_TOOL_EVALUATION.md` für die verbindlichen W3-Entscheidungen und die calibre-Sicherheitsuntergrenze.

## Verifizierter aktueller Stand

### Archive-Extraction-Fortsetzung

S-EBAR-05A, S-EBAR-06A und S-EBAR-04Q sind auf `main` abgeschlossen. ADR-0049
entscheidet FG-A-EXTRACTION-QUOTA als dateisystemneutrale, atomar begrenzte
Workspace-Capability. FolioTone erhält keine Mount-, Device-, `root`- oder
`CAP_SYS_ADMIN`-Authority.

[ADR-0050](../decisions/ADR-0050-linux-docker-workspace-backend-unavailable.md)
schließt FG-A-WORKSPACE-BACKEND negativ und fail-closed ab: Für den
kombinierten Byte-, Objekt-, Reserve- und Consumer-Lifecycle ist noch kein
unprivilegiert live attestierbares Linux-/Docker-Backend belegt. Die
Adapter-Allowlist bleibt leer. S-EBAR-04A, EBAR-06 und jede reale Extraction
bleiben `TOOL_UNAVAILABLE`. Ein späteres docs-only
FG-A-WORKSPACE-BACKEND-REVALIDATION beginnt erst mit einem konkreten
administrativ vorprovisionierten Backend und einem echten Linux-/Docker-
Conformancehost; es autorisiert selbst noch keine Implementierung.

[ADR-0051](../decisions/ADR-0051-bounded-archive-wrapper-streaming.md)
schließt FG-A-WRAPPER-PIPELINE für eine unabhängige read-only Strecke ab.
S-EBAR-W01 bis S-EBAR-W04 sind abgeschlossen und implementieren
TAR-Rahmenprüfung, bounded Duplex-Containerstreaming, Providerintegration und
den fokussierten Abschluss. Die Wrapperstrecke erzeugt weder
Extraction-Handoff noch Persistenz oder Schreiboperationen.

[ADR-0052](../decisions/ADR-0052-immutable-archive-evidence-persistence.md)
und ADR-0053 sind mit S-EBAR-07, S-EBAR-08A bis 08D und EBAR-09 umgesetzt.
[ADR-0054](../decisions/ADR-0054-archive-aware-matching-frontier.md) schließt
danach FG-A3-MATCHING. Als Nächstes implementiert S-EBA3-01 ausschließlich
den reinen Source-Dependency-Vertrag. Member-Byte-Identity bleibt ohne
vollständige Member-SHA-256 `UNKNOWN`; Extraction, Secrets und
Source-Mutationsauthority bleiben gesperrt.

### `W3-017` (E5 synthetischer Performance-/Restart-Vertrag)

Die E5-Verifikation wurde auf Testebene ergänzt: neue synthetische
Skalierungs- und Restart-Szenarien prüfen genau eine Kandidatenmaterialisierung
pro Invocation, den Einsatz des `ix_fingerprints_target_profile_id_value`-Indexes
in der Kandidatenabfrage sowie deterministisches Fortschreiten mit `max_items`
und anschließendem Wiederaufnahme-Lauf.

### Grundlegender W2-Slice

Der finale W2-PR-#5-Head `ef10290da1ed3522e5a261ccb33d5561e32eb497` hat in GitHub Actions Run `31282820586` bestanden. Der automatisierte Docker Incremental Scan Smoke Test bestätigt NEW → UNCHANGED → MODIFIED/MISSING → REAPPEARED über getrennte Containerläufe und persistente SQLite-Daten.

### `W2-004`

Der Implementierungs-Head `556055eb7848f3f682f0bd2363ba2dc98fceb7e5` von PR #7 hat in GitHub Actions Run `31285157432` bestanden. Die Tests decken Deletion-Policy, Failed-Scan-Unterbrechung der Bestätigungsserie, Reappearance nach `DELETED` und das konservative Upgrade von `0002` nach `0003` ab.

### `W2-006`

Der Implementierungs-Head `c946dd336593b68ed281c530ab40117562d17831` von PR #8 hat in GitHub Actions Run `31285662119` mit 52 Tests bestanden. Geprüft sind Rename-, Move- und kombinierte Move-/Rename-Kandidaten, Mehrdeutigkeitsunterdrückung und `FILE_SHA256`-Evidence-Präferenz.

### `W2-007`

Der Implementierungs-Head `8bfa20fb692727f03f8f0cd40b64385328e75d30` von PR #9 hat in GitHub Actions Run `31286181807` vollständig bestanden: Install, Ruff, Mypy, Pytest sowie alle Docker-/Migrations-Smoke-Schritte.

Die Resume-Tests bestätigen:

- ein partiell verarbeiteter Scan endet als `INTERRUPTED`, ohne die erfolgreiche Abwesenheitsphase auszuführen;
- ein Resume erzeugt einen neuen `ScanRun` mit `resumed_from_run_id`;
- vor dem Interrupt bereits verarbeitete unveränderte Dateien werden beim Resume als `UNCHANGED` erkannt und nicht erneut gehasht;
- nicht erreichte bekannte Dateien werden durch den unterbrochenen Run nicht als `MISSING` markiert;
- nur ein persistierter `INTERRUPTED`-Run desselben `ScanRoot` kann als Resume-Quelle verwendet werden;
- `0005_scan_resume_lineage` stellt die persistente Lineage bereit.

### Lokale Windows-/Docker-Verifikation

`W2-012` wurde am 2026-08-09 mit synthetischen Dateien erfolgreich lokal ausgeführt. Verwendet wurden Docker Engine `29.6.2` und Docker Compose `v5.3.1`. Empirisch bestätigt wurden Compose-Build, persistentes `/data`, read-only `/media/ebooks`, die grundlegenden Incremental-States und unavailable-root Schutz.

Die später ergänzten `DELETED`-, Relocation- und Resume-Funktionen wurden in diesem lokalen Plattform-Smoke-Test nicht separat nachgestellt; sie sind automatisiert durch Integrationstests geprüft.

### W2-Abschlussprüfung

Am 2026-08-14 bestanden lokal `ruff check .`, `mypy src/foliotone` für 56 Source-Dateien und 86 Pytest-Tests mit Python 3.12.10. Der Linux-Container-Build über Docker Engine 29.7.2 und Docker Compose 5.4.0 in WSL2 sowie Container-Bootstrap und Alembic-Head-Migration waren erfolgreich.

Die Abschlussprüfung bestätigt zusätzlich:

- W2-009-Profile für Autor/Titel, Serie/Band, Track/Disc, Jahr und Sprache;
- `StructuredOutputError` bei malformed, zu großer, fehlender oder integritätsverletzter JSON-Ausgabe, während die ursprüngliche `ToolExecution` auditierbar bleibt;
- Reanalyse bei Tool-, Adapter-, Input- oder Konfigurationsänderung;
- keine Wiederverwendung ohne explizite Konfigurationsidentität;
- allowlist-basierten Docker-Build-Kontext ohne lokale Runtime-, Medien-, Secret-, Test- oder Git-Daten.

### W3-001 bis W3-009

Der am 2026-08-15 aktualisierte Snapshot wählt calibre 9.13.0 für dateibezogene Metadaten,
EPUBCheck 5.3.0 für implementierte EPUB-Konformität, Poppler 26.07.0 für implementierte
PDF-Metadaten-/Seiten-/Textanalyse und qpdf 12.4.0 als optionale strukturelle
PDF-Evidence. Details und Lizenzen stehen in
`docs/reference/EBOOK_TOOL_EVALUATION.md`.

`foliotone ebook-metadata` analysiert eine persistierte `FileObservation` über
die unveränderliche Befehlsform `ebook-meta FILE --to-opf metadata.opf`.
Unbekannte calibre-Versionen sowie Versionen kleiner als 9.10.0 werden wegen
`GHSA-2j4m-2q7x-2c47` vor dem Dateiöffnen abgelehnt. Calibre-Konfiguration ist
ephemer; das maximal 4 MiB große OPF wird als integritätsgeprüftes
`CALIBRE_OPF`-Artefakt gespeichert. Ausgewählte Felder werden als rohe
`ToolResult`-Evidence gegen die konkrete Observation persistiert.

Ein lokaler End-to-End-Smoke-Test mit einem ausschließlich synthetischen EPUB
und einer separat geprüften calibre-9.13-Installation war erfolgreich. Die
vollständigen lokalen Quality Gates bestanden mit Ruff, Mypy für 57
Source-Dateien und 107 Pytest-Tests. Der Implementierungscommit
`1a02dc146919db7294b7b88ad6d9f6a7a6e60e04` bestand GitHub Actions Run
`31794835407` einschließlich aller Docker-Smoke-Schritte.

`foliotone ebook-text` akzeptiert eine unveränderte EPUB-, MOBI-, AZW- oder
AZW3-`FileObservation`. Der Adapter ruft `ebook-convert` mit einer festen
Plaintext-/UTF-8-/Unix-Befehlsform auf und übernimmt maximal 64 MiB als privates
`CALIBRE_TEXT`-Artefakt. FolioTone normalisiert mit Unicode `NFKC`, reduziert
Whitespace und speichert SHA-256 als `EBOOK_NORMALIZED_TEXT`-`Fingerprint` mit
`ToolExecution`-Link und versioniertem Unicode-Datenprofil. `TEXT_EXTRACTED`
und `NO_TEXT` sind explizite `ToolResult`-Werte; `NO_TEXT` entsteht nur nach
erfolgreicher leerer Extraktion und erzeugt keinen Fingerprint. DRM-Umgehung
gehört nicht zum Vertrag. Rohtext erscheint nicht in der CLI-Ausgabe.

Ein lokaler End-to-End-Smoke-Test mit calibre 9.13.0 und ausschließlich dem
synthetischen EPUB bestätigte `TEXT_EXTRACTED`, 43 normalisierte Zeichen, ein
49 Byte großes Text-Artefakt, einen 64-stelligen Fingerprint und ein leeres
ephemeres Work-Verzeichnis. Repository-Ruff, Mypy für 59 Source-Dateien und 115
Pytest-Tests waren erfolgreich. Der Implementierungscommit
`dc2cd09ffbc07098e0c296bea231532c4f38051b` bestand GitHub Actions Run
`31809375485` für PR #13 einschließlich aller Docker-Smoke-Schritte.

`foliotone pdf-analyze` akzeptiert ausschließlich eine unveränderte PDF-
`FileObservation`. Der Adapter führt feste `pdfinfo`- und `pdftotext`-Befehle
als zwei getrennte `ToolExecution`-Records aus, begrenzt und validiert die
Metadatenausgabe und übernimmt maximal 64 MiB als privates `POPPLER_TEXT`-
Artefakt. PDF verwendet denselben FolioTone-eigenen normalisierten
`EBOOK_NORMALIZED_TEXT`-Fingerprint wie EPUB. Erfolgreiche leere Extraktion ist
`NO_TEXT`; Fehler werden nicht in diesen Zustand umgedeutet. Poppler-Versionen
unter 26.07.0 und unbekannte Versionen werden vor dem Dateiöffnen abgelehnt.

Ein lokaler End-to-End-Smoke-Test mit Poppler 26.07.0 und ausschließlich zwei
synthetischen PDFs bestätigte für beide je 20 Metadatenbeobachtungen und
`page_count = 1`. Das Text-PDF lieferte `TEXT_EXTRACTED`, 45 normalisierte
Zeichen und einen Fingerprint; das leere PDF lieferte `NO_TEXT`, null Zeichen
und keinen Fingerprint. Die gezielten 18 Poppler-Unit-Tests bestanden, und die
ephemeren Work-Verzeichnisse waren nach Abschluss leer.

Der vollständige W3-004-Stand bestand lokal `ruff check .`, Mypy für 63
Source-Dateien und alle 133 Pytest-Tests in 6 Minuten 35 Sekunden.

Der lokale W3-005-End-to-End-Smoke verwendete ausschließlich synthetische,
DRM-freie EPUB-, MOBI-, AZW- und AZW3-Dateien. Mit calibre 9.13.0 entstanden
jeweils vier erfolgreiche Metadaten- und Textausführungen. Alle Textläufe
lieferten `TEXT_EXTRACTED`, 43 normalisierte Zeichen und denselben
`EBOOK_NORMALIZED_TEXT`-Fingerprint; das Work-Verzeichnis war danach leer. Die
gezielten 32 calibre-/CLI-Tests sowie Ruff und Mypy für 63 Source-Dateien waren
erfolgreich.

Der vollständige W3-005-Stand bestand lokal `ruff check .`, Mypy für 63
Source-Dateien und alle 142 Pytest-Tests in 8 Minuten 50 Sekunden.

Der gezielte W3-006-Lauf bestand alle 26 calibre-Metadaten-Tests einschließlich
OPF-2-Attributen, OPF-3-Refinements, ISBN-/Identifier-Namespace,
Contributor-Gruppierung, MARC-Rollen, Sortiernamen, Series-Gruppierung und
bewusst nicht normalisierten fremden Rollen-Schemes. Der vollständige Stand
bestand lokal `ruff check .`, Mypy für 64 Source-Dateien und alle 152
Pytest-Tests in 8 Minuten 45 Sekunden.

Der read-only CLI-Smoke-Test mit calibre 9.13 und einem ausschließlich
synthetischen, DRM-freien MOBI persistierte unter `ebook-meta-opf/2` elf rohe
Beobachtungen und 21 Kandidaten. Alle Ergebnisse verwiesen auf genau eine
`ToolExecution` und `FileObservation`; die Tabellen für `Agent`, `Work`,
`Edition` und `Series` blieben leer. Das OPF-Artefakt war persistent, das
ephemere Work-Verzeichnis nach Abschluss leer.

`W3-007` stellt unter `tests/fixtures/ebook_comparison/v1/` fünf synthetische
Items und fünf Szenarien bereit. Kontrolliert werden byte-identische Dateien,
eine Metadatenänderung bei gleichem normalisiertem Text, dieselbe `Edition` als
EPUB-/MOBI-Variante, eine Übersetzung als andere `Edition` desselben `Work` und
zwei widersprüchliche versionsgebundene Tool-Werte ohne kanonische Auswahl.
Die drei gezielten Fixture-Tests sowie der vollständige Stand mit Ruff, Mypy
für 64 Source-Dateien und 155 Pytest-Tests in 8 Minuten 25 Sekunden waren
lokal erfolgreich.

Der Implementierungscommit `352eb8567c542e709e77f98de42c222f21dd3f75`
von PR #17 bestand die GitHub-Actions-Runs `31844049430` und `31844093222`;
beide `quality`-Jobs waren nach jeweils 52 Sekunden erfolgreich.

`W3-008` implementiert `foliotone epub-validate` über den festen
`epubcheck-json/1`-Vertrag. Eine unveränderte EPUB-`FileObservation` wird mit
EPUBCheck 5.3.0 in einem privaten headless Java-Workspace geprüft. Der maximal
8 MiB große `EPUBCHECK_JSON`-Report bleibt privates `ToolArtifact`; persistierte
Evidence enthält nur `CONFORMANT`/`NONCONFORMANT`, fünf Severity-Counts und
aggregierte Severity-/Diagnosecode-Counts. Meldungstexte, Publication-Daten
und lokale Pfade erscheinen nicht in `ToolResult` oder CLI-Ausgabe.

ADR-0017 lässt für einen festen Adapter dokumentierte Nonzero-Domain-Exitcodes
zu, während der Standard `{0}` bleibt. EPUBCheck akzeptiert `{0, 1}`: Ein
Prüflauf mit Konformitätsfehlern ist ausführungsseitig `SUCCEEDED`, behält den
Exitcode und persistiert den negativen Befund getrennt. Fehlender oder
ungültiger Report, andere Exitcodes und Timeouts bleiben technische Fehler.

Temurin JRE 21.0.12+8 und EPUBCheck 5.3.0 wurden nur portabel und
SHA-256-verifiziert unter `C:\rep\cache\FolioTone` bereitgestellt. Der echte
CLI-Smoke-Test mit dem synthetischen EPUB persistierte bei Exitcode `1`
`NONCONFORMANT` und die drei Codes `PKG-006`, `PKG-007` und `RSC-005`. Die
Quelldatei blieb bytegleich und das Work-Verzeichnis leer. 15 Adaptertests und
37 gezielte Runtime-/Toolingtests bestanden; der gezielte Mypy-Lauf war
fehlerfrei.

Der vollständige W3-008-Stand bestand mit Python 3.12.10 lokal `ruff check .`,
Mypy für 66 Source-Dateien und alle 175 Pytest-Tests in 9 Minuten 23 Sekunden.

Der Implementierungscommit `e80b1d9cba28e2d883daaa2627b4fc0ef795d11c`
von PR #18 bestand die GitHub-Actions-Runs `31866746326` und `31866764769`;
beide `quality`-Jobs waren nach 58 beziehungsweise 50 Sekunden erfolgreich.

`foliotone ebook-cover` akzeptiert ausschließlich eine unveränderte EPUB-,
MOBI-, AZW- oder AZW3-`FileObservation`. Der feste
`calibre-debug-cover/1`-Helper wird über `calibre-debug -e` ausgeführt, kopiert
die Source in den privaten Workspace und übergibt nur diese Kopie an den
calibre-Reader. Gerenderte EPUB-Ersatzcover sind deaktiviert. Das erforderliche
JSON-Ergebnis enthält Status, Covergröße und Source-SHA-256; das optionale,
maximal 32 MiB große Raster bleibt privates `CALIBRE_EMBEDDED_COVER`-
`ToolArtifact`.

Pillow 12.3.x dekodiert nur JPEG, PNG, WebP oder GIF unter einer
40-Megapixel-Grenze. FolioTone normalisiert EXIF-orientiert in Graustufen auf
9 x 8 Pixel mit Lanczos und speichert einen versionierten horizontalen
64-Bit-`EBOOK_COVER_DHASH`. `NO_EMBEDDED_COVER` ist ein erfolgreicher Befund
ohne Fingerprint. Coverähnlichkeit bleibt unterstützende Evidence und ist kein
Identitätsbeweis.

Der echte CLI-Smoke-Test unter
`C:\rep\tmp\FolioTone\w3-009-smoke-01` verwendete zwei ausschließlich
synthetische EPUBs. Ein eingebettetes JPEG ergab `COVER_EXTRACTED`,
1240 x 1752 Pixel und dHash `4000000000000000`; das zweite EPUB ergab
`NO_EMBEDDED_COVER`. Beide Source-SHA-256 blieben unverändert. Die 13 neuen
Cover-Tests plus zwei Bootstrap-Tests, Ruff und Mypy für 69 Source-Dateien
waren lokal erfolgreich.

Der vollständige W3-009-Stand bestand mit Python 3.12.10 lokal
`ruff check .`, Mypy für 69 Source-Dateien und alle 188 Pytest-Tests in
11 Minuten 31 Sekunden. Das gebaute Wheel enthielt Adapter, dHash-Logik und
den paketierten calibre-Helper.

Der Implementierungscommit `a55b553445b223ea6219a522cdaafeff98165aa7`
von PR #19 bestand die GitHub-Actions-Runs `31871971678` und `31871990590`;
die beiden `quality`-Jobs waren nach 58 beziehungsweise 63 Sekunden
erfolgreich.

`foliotone ebook-analyze` verwendet das Profil
`ebook-analysis-workflow/v1`. EPUB wird nacheinander über Metadaten, Text,
Cover und EPUBCheck geführt; MOBI/AZW/AZW3 über Metadaten, Text und Cover; PDF
über die bestehende kombinierte Poppler-Analyse. Die Workflow-Schicht enthält
keine eigenen Parser oder Toolargumente. Sie erhält jede konkrete
ToolExecution und deren Evidence unverändert.

Alle für das konkrete Format notwendigen Adapter werden vor dem ersten Lauf
geprüft. Erwartete Adapterfehler oder fehlgeschlagene/abgebrochene
ToolExecutions stoppen unabhängige Folgeschritte nicht. Schrittzustände bleiben
als `SUCCEEDED`, `FAILED`, `CANCELLED` oder `ERROR` sichtbar; der Gesamtzustand
ist `SUCCEEDED`, `PARTIAL_FAILURE` oder `FAILED`. Nur vollständiger technischer
Erfolg liefert Exitcode 0. `NONCONFORMANT` ist weiterhin ein fachlicher
EPUBCheck-Befund innerhalb eines technisch erfolgreichen Schritts.

Die CLI druckt ausschließlich eine begrenzte Allowlist aus Zählern,
Statuswerten und Fingerprints sowie ToolExecution-ID/-Status/-Version. Rohe
Artefakte, Diagnosetexte und absolute Source-Pfade bleiben privat. Das
historische Profil `ebook-analysis-workflow/v1` erzeugt bei jedem Aufruf
frische Evidence. `W3-011` ersetzt diesen Default durch den nachfolgend
dokumentierten konservativen `v2`-Planer.

Die gezielte W3-010-Suite aus Workflow-, Bootstrap- und CLI-Integrationstests
bestand mit 18 Tests; Ruff und Mypy für 71 Source-Dateien waren erfolgreich.
Der echte Smoke unter `C:\rep\tmp\FolioTone\w3-010-smoke-01` führte zwei
ausschließlich synthetische EPUBs durch jeweils vier erfolgreiche Schritte.
Insgesamt wurden acht erfolgreiche ToolExecutions, 79 ToolResults und sieben
Fingerprints persistiert. `COVER_EXTRACTED` und `NO_EMBEDDED_COVER` blieben
getrennt; beide synthetisch unvollständigen EPUBs ergaben erwartbar
`NONCONFORMANT`. Beide Source-SHA-256 blieben unverändert, der ephemere
Work-Ordner war anschließend leer.

Der vollständige W3-010-Stand bestand mit Python 3.12.10 lokal
`ruff check .`, Mypy für 71 Source-Dateien und alle 204 Pytest-Tests in
11 Minuten 16 Sekunden. Das Wheel unter
`C:\rep\artifacts\FolioTone\w3-010-wheel-01` enthielt die beiden neuen
`foliotone.workflows`-Module; sein SHA-256 ist
`3ad24961dc47512721a06053ab40504b2534a8979effb9a43e713c4e501aff24`.

Der veröffentlichte Implementierungscommit
`2f8cb144617433855f51c39c4525603b9aa1004a` liegt in PR #20. Seine
GitHub-Actions-Runs `31874601676` (Push) und `31874615476` (Pull Request)
waren erfolgreich; die `quality`-Jobs einschließlich aller Docker-Smoke-Tests
liefen 62 beziehungsweise 59 Sekunden.

Der echte W3-011-Smoke unter
`C:\rep\tmp\FolioTone\w3-011-smoke-01` verwendete ausschließlich ein
synthetisches EPUB. Der Erstlauf erzeugte vier erfolgreiche ToolExecutions;
der identische Zweitlauf verwendete alle vier mit unveränderten IDs wieder.
Nach absichtlicher Beschädigung nur des privaten `CALIBRE_TEXT`-Artefakts lief
ausschließlich der Textschritt neu. `--fresh` führte danach alle vier Schritte
neu aus. Die Execution-Zählerfolge war 4, 4, 5, 9. Die Source-SHA-256 blieb
`41070cdea56904647215b069f15af3f6e46d6d94b81795974e247a337464b6ea`;
der ephemere Work-Ordner war leer. Verwendet wurden calibre 9.13, EPUBCheck
5.3.0 und Temurin JRE 21.0.12+8.

Der vollständige W3-011-Stand bestand lokal `ruff check .`, Mypy für 73
Source-Dateien und alle 216 Pytest-Tests in 11 Minuten 35 Sekunden. Das Wheel
`C:\rep\artifacts\FolioTone\w3-011-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`ab6064b05035a8cddd4f033a493c3f9d76ce43b37fe89dba5d790f142ad9e62e`
und enthält `ebook.py`, `evidence.py` und `reuse.py`.

Der W3-011-Implementierungscommit
`2f08bcc4f3b13517ec70e92e3eb25416ce56e6e4` liegt in PR #21. Seine
GitHub-Actions-Runs `31886119562` (Push) und `31886140176` (Pull Request)
waren erfolgreich; die `quality`-Jobs einschließlich aller Docker-Smoke-Tests
liefen 56 beziehungsweise 63 Sekunden.

Calibres dokumentiertes `calibre-debug --diff` startet ein GUI-Modul ohne
headless JSON-/Reportvertrag und wurde deshalb nicht adaptiert. Ein späterer
provider-neutraler Book-Diff soll persistierte Datei-, Text-, Metadaten-,
Struktur- und Cover-Evidence vergleichen. qpdf bleibt bis zu einem zusätzlichen
PDF-Struktur-Gap zurückgestellt.

## Aktuell implementiert

### Index

- stabile logische `ScanRoot`-Identität über einen eindeutigen Namen;
- `ScanRun`-Lifecycle mit auditablem `resumed_from_run_id`;
- streaming Filesystem Discovery;
- `FileObservation` und `FileScanEvent`;
- NEW, UNCHANGED, MODIFIED, MISSING, REAPPEARED und opt-in DELETED;
- unavailable-root Schutz gegen falsches MISSING;
- read-only `foliotone scan` CLI einschließlich `--resume-run`;
- interaktiver pfadfreier Scan-Fortschritt auf `stderr`, mit
  `--progress`/`--no-progress` ausdrücklich steuerbar;
- begrenzte Batch-Verarbeitung;
- set-orientierte `FileRecord`-/`FileObservation`-/`FileEvent`-Persistenz je Discovery-Batch;
- 1 bis 8 begrenzte Hash-Worker über `--hash-workers`; `auto` verwendet
  standardmäßig höchstens die Hälfte der sichtbaren CPU-Anzahl;
- atomare Fingerprint-Persistenz je Discovery-Batch;
- sauberer CLI-Abbruch mit Exitcode 130, persistentem `INTERRUPTED` nach
  Run-Start und kooperativem Abbruch aktiver In-Process-Hashreads;
- isolierte Hash-I/O-Teilfehler mit selektivem Retry im nächsten Scan;
- persistente Abwesenheitsserie über `missing_since_at` und `consecutive_missing_scans`;
- persistente `FileRelocationCandidate`-Records für eindeutige NEW/erstmalig-MISSING Fingerprint-Paare im selben erfolgreichen Scan.

### `DELETED`-Policy

`DeletionConfirmationPolicy` ist standardmäßig nicht aktiv. Bei expliziter Aktivierung müssen sowohl eine konfigurierte Anzahl aufeinanderfolgender erfolgreicher `MISSING`-Scans als auch eine konfigurierte Mindestdauer erfüllt sein. Failed oder interrupted Scans erhöhen die Serie nicht. Ein bestätigtes `DELETED` erzeugt keine Filesystem-Operation. ADR-0013 ist verbindlich.

### Relocation-Kandidaten

`FileRelocationCandidate` ist zusätzliche Evidence, keine bestätigte File-Identität. Source bleibt ein eigener `MISSING`-Record und Target ein eigener `NEW`-Record. Kandidaten werden nur innerhalb desselben `ScanRoot` und Scans aus eindeutigen versionierten `QUICK_FILE`-/`FILE_SHA256`-Blöcken gebildet. ADR-0014 ist verbindlich.

### Interrupt/Resume

Resume wird als neuer `ScanRun` modelliert. `resumed_from_run_id` verweist auf
den persistierten `INTERRUPTED`-Vorgänger desselben `ScanRoot`. Discovery läuft
erneut vollständig und streaming-basiert; ein persistenter `os.scandir`-Cursor
wird bewusst nicht verwendet. Vollständige Hash-Evidence der jeweils jüngsten
unveränderten Observation wird auf die neue Observation projiziert, ohne die
Source erneut zu öffnen. Nur eine dort fehlende Evidence wird gezielt
nachgehasht; stale ältere Hashes werden nicht übersprungen. Erst ein vollständig
erfolgreicher Resume-Run darf `MISSING`/`DELETED` klassifizieren. ADR-0015 ist
verbindlich.

Neue Scan-Invocations besitzen zusätzlich eine Lease. Der Scanner erneuert sie
vor und nach begrenzten Discovery-/Hash- und Abschlussphasen. Nach einem
nachweislich beendeten Prozess setzt `--recover-stale-running` nur den neuesten
ungeleasten oder abgelaufenen `RUNNING`-Lauf desselben `ScanRoot` atomar auf
`INTERRUPTED` und startet danach den normalen Resume-Vertrag. Eine aktive Lease
blockiert die Übernahme. ADR-0025 ist verbindlich.

### Hashing

- NONE, QUICK und FULL;
- Quick Fingerprint mit begrenztem Datei-I/O;
- vollständiges SHA-256 als Streaming-Hash;
- Fingerprints gegen konkrete `FileObservation`;
- kein unnötiges Rehashing unveränderter Dateien, auch nicht bei Resume bereits verarbeiteter unveränderter Files;
- fehlende jüngste Hash-Evidence wird selektiv ergänzt;
- atomare Fingerprint-Batches und ausdrücklich begrenzte Hash-Parallelität.

### Filename- und Path-Context-Kandidaten

`FilenameParser` erzeugt aus einem Dateinamen ohne Pfadseparatoren einen niedrig gewichteten `title`-Kandidaten. `PathContextAnalyzer` verarbeitet nur sichere relative Pfade und erzeugt aus dem direkten Parent einen niedrig gewichteten `path_context`-Kandidaten. Beide Komponenten speichern die Parser-Version, den Komponentenname und den beobachteten Zeitpunkt in `Provenance`; sie geben keine absoluten Hostpfade aus. `RuleBasedFilenameParser` wendet geordnete, versionierte Regex-Profile auf sammlungsspezifische Konventionen für Autor, Titel, Serie, Band, Track, Disc, Jahr und Sprache an.

### ToolProvider Runtime

- lokale Ausführung ohne Shell;
- Version Detection;
- Timeout/Cancellation;
- FAILED-Erfassung bei fehlendem Tool und nicht adapter-akzeptiertem Exitcode;
- unveränderliche provider-spezifische `accepted_exit_codes`-Allowlist mit
  Standard `{0}` und Erhaltung des tatsächlich beobachteten Exitcodes;
- stdout/stderr als `ToolArtifact` mit SHA-256;
- begrenzte, strikte JSON-Auswertung aus persistiertem stdout-`ToolArtifact` mit Größen-/SHA-256-Integritätsprüfung;
- konservative Reanalyse anhand erfolgreicher früherer Ausführung und exakter Provider-, Capability-, Input-, Tool-, Adapter- und Konfigurationsidentität;
- Privacy-Schutz für persistierte Input-Identitäten;
- gehärtete Containerargumente mit read-only Input-Mounts, deaktiviertem Netzwerk als Default und isoliertem Work-Verzeichnis.
- deklarierte, größenbegrenzte Workspace-Ausgaben, die vor dem ephemeren Cleanup
  als `ToolArtifact` mit SHA-256 übernommen werden;
- Adapter-Version-Policies, die unsichere Versionen vor der Source-Analyse
  auditierbar ablehnen können.

### calibre-Metadaten

- `CalibreMetadataAnalyzer` und CLI `foliotone ebook-metadata`;
- feste read-only `ebook-meta FILE --to-opf`-Argumentform ohne Setter;
- Sicherheitsuntergrenze calibre 9.10.0 vor dem Öffnen der Eingabe;
- ephemere `CALIBRE_CONFIG_DIRECTORY` für Versionsabfrage und Analyse;
- begrenztes, integritätsgeprüftes OPF-Artefakt;
- rohe OPF2-/OPF3-Beobachtungen unter `calibre_metadata`;
- provider-neutrale `ebook_metadata_candidate`-Ergebnisse unter dem
  versionierten Profil `ebook-metadata-candidate/v1`;
- stabile Gruppenpfade für Identifier-Namespace/-Wert,
  Contributor-Name/-Quelle/-MARC-Rolle/-Sortiername und Series-Name/-Position;
- direkte Kandidaten für Titel, Sprache, Verlag, Publikationsdatum, Subject,
  Beschreibung, Rechte, Typ, Titelsortierung und Rating;
- exakter `ToolExecution`-/`FileObservation`-Link ohne Anlage kanonischer
  `Agent`-, `Work`-, `Edition`- oder `Series`-Entitäten;
- kein `calibredb` bis zu einem konkreten read-only Library-Reconciliation-Vertrag.

### calibre-EPUB/MOBI/AZW/AZW3-Text

- `CalibreTextAnalyzer` und CLI `foliotone ebook-text`;
- explizite EPUB/MOBI/AZW/AZW3-Allowlist und eine feste
  `ebook-convert FILE content.txt`-Befehlsform ohne frei übergebbare Optionen;
- `ToolCapability.EXTRACT_TEXT` sowie Sicherheitsuntergrenze calibre 9.10.0;
- UTF-8-Plaintext, Unix-Zeilenenden und deaktivierte Zeilenaufteilung;
- maximal 64 MiB großes privates, integritätsgeprüftes `CALIBRE_TEXT`-Artefakt;
- FolioTone-eigene versionierte `NFKC`-/Whitespace-Normalisierung und SHA-256;
- `EBOOK_NORMALIZED_TEXT` gegen konkrete `FileObservation` und `ToolExecution`;
- explizite Zustände `TEXT_EXTRACTED` und `NO_TEXT`, ohne Fingerprint bei
  fehlendem Text;
- keine DRM-Entfernung oder -Umgehung; Konvertierungsfehler bleiben
  fehlgeschlagene `ToolExecution`-Records und werden nicht zu `NO_TEXT`;
- keine Ausgabe des extrahierten Rohtexts über die CLI.

### Poppler-PDF

- `PopplerPdfAnalyzer` und CLI `foliotone pdf-analyze`;
- ausschließlich PDF sowie feste `pdfinfo`-/`pdftotext`-Argumentformen;
- separate `ToolExecution`-Records für technische Metadaten und Text;
- Sicherheitsuntergrenze Poppler 26.07.0 vor dem Öffnen der Eingabe;
- maximal 1 MiB allowlist-geparste `pdfinfo`-Ausgabe und validierte Dateigröße;
- maximal 64 MiB großes privates, integritätsgeprüftes `POPPLER_TEXT`-Artefakt;
- gemeinsamer versionierter `NFKC`-/Whitespace-Normalisierer und
  `EBOOK_NORMALIZED_TEXT`-Fingerprint;
- explizites `NO_TEXT` nur nach erfolgreicher leerer Extraktion;
- kein Rohtext, OCR, Passwortargument, frei übergebbares Poppler-Argument oder
  PDF-Schreibpfad über die CLI;
- qpdf bis zu einem konkreten Bedarf an zusätzlicher Struktur-Evidence
  zurückgestellt.

### Synthetischer E-Book-Vergleichskorpus

- Manifestversion `foliotone-ebook-comparison-fixture/v1` mit ausschließlich
  sicheren relativen Fixture-Pfaden;
- reproduzierbare SHA-256-Werte für Container-Surrogate und extrahierte
  Text-Artefakte;
- byte-stabile Git-Attribute für binäre Container-Surrogate und LF-normalisierte
  Text-Artefakte;
- produktiver `EBOOK_NORMALIZED_TEXT`-Fingerprint für Inhaltsvergleich;
- getrennte Ground Truth für `File`, normalisierten Inhalt, `Edition` und
  `Work`;
- gelabelte `RelationType`-Erwartungen für spätere W6-Kalibrierung;
- versionsgebundene synthetische Tool-Beobachtungen, die bei Widerspruch
  erhalten bleiben und keinen kanonischen Wert erzeugen;
- keine Matching Engine, kein Scoring, keine automatische Review-Entscheidung
  und keine zusätzliche Produktoberfläche.

### EPUBCheck-Strukturvalidierung

- `EpubCheckAnalyzer` und CLI `foliotone epub-validate`;
- ausschließlich unveränderte EPUB-`FileObservation`-Eingaben;
- `ToolCapability.STRUCTURAL_VALIDATION` und Adapterversion
  `epubcheck-json/1`;
- feste headless Java/JAR-Befehlsform ohne caller-kontrollierte
  EPUBCheck-Optionen;
- EPUBCheck 5.3.0 als Mindestversion;
- JVM-Tempdaten und Report ausschließlich im ephemeren Tool-Workspace;
- maximal 8 MiB großes privates, integritätsgeprüftes
  `EPUBCHECK_JSON`-Artefakt und höchstens 10.000 Meldungen;
- `CONFORMANT`/`NONCONFORMANT`, fünf Severity-Counts und aggregierte
  Diagnosecode-Counts mit exaktem Execution-/Observation-Link;
- keine Meldungstexte, Publication-Metadaten oder lokalen Pfade in
  `ToolResult` und CLI-Ausgabe;
- `{0, 1}` als feste akzeptierte Exitcodes, wobei ein Konformitätsfehler
  Evidence und kein technischer Prozessfehler ist;
- kein calibre-GUI-Diff-Adapter und kein qpdf-Adapter ohne zusätzlichen
  maschinenlesbaren Vergleichs- oder PDF-Strukturbedarf.

### calibre-Embedded-Cover und FolioTone-dHash

- `CalibreCoverAnalyzer` und CLI `foliotone ebook-cover`;
- feste EPUB/MOBI/AZW/AZW3-Allowlist unter `ToolCapability.FINGERPRINT`;
- paketierter `calibre-debug -e`-Helper mit privater Source-Kopie, ohne
  `ebook-meta`-Setter oder caller-kontrollierte Python-/calibre-Argumente;
- deaktivierte gerenderte EPUB-Ersatzcover und explizites
  `NO_EMBEDDED_COVER` ohne Fingerprint;
- erforderliches, maximal 1 KiB großes JSON-Ergebnis mit Source-SHA-256 sowie
  erneuter Digest-Prüfung nach dem Lauf;
- optionales, maximal 32 MiB großes privates
  `CALIBRE_EMBEDDED_COVER`-Artefakt;
- Pillow-12.3-Rasterdekodierung für JPEG/PNG/WebP/GIF mit
  Decompression-Bomb- und 40-Megapixel-Grenze;
- EXIF-orientierter 9-x-8-Graustufen-Lanczos-Normalisierer und versionierter
  horizontaler 64-Bit-`EBOOK_COVER_DHASH`;
- Coverähnlichkeit ausschließlich als unterstützende Evidence, ohne
  automatische Datei-/`Edition`-/`Work`-Identität.

### Einheitliche E-Book-Analyse

- `EbookAnalysisOrchestrator` und CLI `foliotone ebook-analyze`;
- aktuelles Profil `ebook-analysis-workflow/v3` und feste Allowlist EPUB/MOBI/AZW/AZW3/PDF;
- ausschließlich Komposition der bestehenden calibre-, EPUBCheck- und
  Poppler-Adapter, ohne neue Toolargumente oder Parser;
- Format-Routing: EPUB vier Schritte, MOBI/AZW/AZW3 drei Schritte, PDF ein
  Adapterergebnis mit zwei getrennten ToolExecutions;
- Fortsetzung unabhängiger Schritte nach erwarteten Adapter-/Toolfehlern;
- explizite Schritt- und Gesamtzustände sowie Exitcode 0 nur bei vollständig
  technisch erfolgreicher Analyse;
- begrenzte CLI-Zusammenfassung ohne rohe Artefakte, Diagnosetexte oder
  absolute Source-Pfade;
- nicht persistierender read-only Versionsprobe vor Wiederverwendung;
- exakter Vergleich von Provider, Tool-Version, Adapter, Capability,
  FileObservation-Input und Konfigurationsidentität;
- ausschließlich neuester exakt passender erfolgreicher Lauf; ein neuerer
  fehlgeschlagener exakter Versuch erzwingt Retry;
- adapter-spezifische Größen-/SHA-256-Prüfung jedes Pflichtartefakts und
  deterministische Rekonstruktion der persistierten Ergebnisse/Fingerprints;
- `REUSED`/`EXECUTED` je Schritt und `--fresh` zum vollständigen Bypass;
- atomarer PDF-Workflow-Schritt: Beide getrennten Poppler-Ausführungen werden
  gemeinsam wiederverwendet oder gemeinsam neu ausgeführt.
- separate, deterministische Projektion `ebook-quality/v1` ohne zusätzlichen
  Toollauf oder Persistenzmigration;
- `EbookQualityAssessment` mit stabil geordneten Dimensionen `METADATA`,
  `TEXT`, `COVER`, `STRUCTURE` und `FORMAT_RISK`;
- feste Befundcodes mit exakten verfügbaren ToolExecution-IDs sowie getrennte
  Zustände `INCOMPLETE`, `REVIEW` und `ACTION_REQUIRED`;
- kein skalarer Quality Score, keine Identitätsableitung und keine Änderung der
  technischen `ebook-analyze`-Exitcodes durch Qualitätsbefunde.

**Empirisch für W3-012:** Der echte CLI-Smoke mit der synthetischen EPUB unter
`C:\rep\tmp\FolioTone\w3-011-smoke-01` verwendete alle vier vorhandenen
ToolExecutions wieder und erzeugte keinen neuen Lauf. `ebook-quality/v1`
meldete `TEXT_VERY_SHORT` und `EPUB_VALIDATION_ERRORS` als
`ACTION_REQUIRED`; der technische Workflow blieb `SUCCEEDED`. Die Source-
SHA-256 blieb
`41070cdea56904647215b069f15af3f6e46d6d94b81795974e247a337464b6ea`, der
Work-Ordner blieb leer und der ToolExecution-Zähler blieb bei neun.

Der vollständige W3-012-Stand bestand mit Python 3.12.10 lokal
`ruff check .`, Mypy für 74 Source-Dateien und alle 222 Pytest-Tests in
9 Minuten 23 Sekunden. Das Wheel unter
`C:\rep\artifacts\FolioTone\w3-012-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`a02e033db35e6e2acfe0d374961597e257e3070198bb3f503854425a17a95457` und
enthält `foliotone/workflows/quality.py`.

### Provider-neutraler E-Book-Evidence-Vergleich

- `EbookComparisonService`, Profil `ebook-comparison/v1` und CLI
  `foliotone ebook-compare`;
- ausschließlich persistierte Evidence zweier expliziter FileObservation-IDs,
  ohne Source Root, Medienzugriff oder neuen Toollauf;
- stabil geordnete Dimensionen `FILE_BYTES`, `NORMALIZED_TEXT`, `METADATA`,
  `STRUCTURE` und `COVER`;
- getrennte Dimension States und Evidence-Coverage statt Matchscore oder
  Identitätsentscheidung;
- vollständige Datei-SHA-256 und kompatible versionierte Text-/Cover-
  Fingerprints; `QUICK_FILE` genügt nicht für Bytegleichheit;
- Metadatenvergleich über provider-neutrale Feldkandidaten, mit Feldpfaden und
  Counts statt rohen Werten;
- Ausschluss des empirisch volatilen internen `identifier.calibre` aus dem
  bibliografischen Vergleich bei unveränderter Raw-Evidence;
- EPUB-Strukturvergleich über Konformität, Severity-Counts und Diagnostic-
  Codes; Cover-dHash-Distanz ohne Ähnlichkeitsschwelle;
- neueste Ausführung je Provider/Capability; ein neuerer fehlgeschlagener Lauf
  verhindert die Verwendung älterer Evidence desselben Providers;
- keine persistierte `Relation`, Confidence, Review-Entscheidung oder
  kanonische Metadaten.

**Empirisch für W3-013:** Die fünf gezielten Korpus-, CLI- und Bootstrap-Tests
waren erfolgreich; Ruff und Mypy für 75 Source-Dateien waren ebenfalls
erfolgreich. Der vollständige Stand bestand alle 225 Pytest-Tests in
13 Minuten 27 Sekunden. Der echte CLI-Smoke unter
`C:\rep\tmp\FolioTone\w3-013-smoke-01` analysierte zwei bytegleiche
synthetische EPUB-Kopien in insgesamt acht erfolgreichen ToolExecutions.
`ebook-compare` meldete `COMPLETE` und fünfmal `SAME`. Beide Source-SHA-256
blieben
`41070cdea56904647215b069f15af3f6e46d6d94b81795974e247a337464b6ea`, der
Work-Ordner blieb leer und es wurde keine Relation persistiert. Das Wheel unter
`C:\rep\artifacts\FolioTone\w3-013-wheel-01\foliotone-0.1.0-py3-none-any.whl`
hat SHA-256
`985e84dbf06e8bcad2e23468af3cd096a6ef9c0469300ae357a016854da669fe` und
enthält `foliotone/workflows/comparison.py`.

### Persistence

- Alembic `0002_incremental_index` ergänzt Scan-Events, Tool-Artefakte und W2-Indizes;
- Alembic `0003_deletion_confirmation` ergänzt die persistente Abwesenheitsserie;
- Alembic `0004_relocation_candidates` ergänzt persistente Relocation-Kandidaten;
- Alembic `0005_scan_resume_lineage` ergänzt `scan_runs.resumed_from_run_id` und den zugehörigen Index.
- Alembic `0006_ebook_evidence_lookup_indexes` ergänzt drei additive Indizes für begrenzte Observation-Evidence-Abfragen.
- Alembic `0007_ebook_collection_batches` ergänzt fortsetzbare Collection-
  Runs und Items mit Root-/Status- und Run-/Status-/Ordinal-Indizes, ohne
  Pfade oder Metadatenwerte in den Batch-Tabellen zu speichern.
- Alembic `0008_ebook_collection_reports` ergänzt geordnete Item-Ausführungen,
  Quality-Befunde, deren exakte `ToolExecution`-Quellen und den belegten
  Fingerprint-Gruppierungsindex, weiterhin ohne Source-Pfade oder Inhalte in
  den Collection-Tabellen.
- Alembic `0009_scan_run_leases` ergänzt nullable Lease-Felder und einen
  Root-/Status-/Lease-Index für sichere Heartbeats und explizite Recovery
  verwaister Scans.

### Begrenzter Evidence-Lesepfad und synthetischer v2-Korpus

- `load_observation_evidence()` lädt ausschließlich Records expliziter
  `FileObservation`-IDs und führt keinen collection-weiten `list_all()`-Read
  aus;
- Paarvergleich und exakte Collection-Evidence-Wiederverwendung teilen diesen
  indexgestützten Lesepfad; Reuse fordert genau eine Observation sowie
  höchstens 64 Artefakte der ausgewählten Ausführung an;
- feste `LIMIT maximum + 1`-Grenzen schützen `ToolExecution`, `ToolResult`
  und `Fingerprint` vor unbeschränkter Historienladung;
- eine Überschreitung erzeugt einen technischen Fehler ohne Full-Table-
  Fallback;
- der v2-Korpus ergänzt AZW, AZW3, PDF, Sparse-/Malformed-Evidence und
  Cover-dHash-Distanzen 0/1/8/32/64;
- der Skalierungstest verwendet 10.000 synthetische Fremdrecords je Evidence-
  Tabelle und bestätigt genau drei gefilterte, indexgestützte Reads;
- 12 gezielte Tests bestanden in 2 Minuten 39 Sekunden; Ruff, Mypy für 77
  Source-Dateien und alle 229 Pytest-Tests in 15 Minuten 46 Sekunden waren
  erfolgreich.
- das gebaute Wheel unter
  `C:\rep\artifacts\FolioTone\w3-014-wheel-01` hat SHA-256
  `8c39c43917d55fbd7e241cc6b4610afc64642a0f5b92b3032f8f92fc8605a3a3`
  und enthält Query-Modul, Migration und Vergleichsworkflow.

### Fortsetzbare E-Book-Collection-Analyse

- `EbookCollectionService`, Profil `ebook-collection-analysis/v1` und CLI
  `foliotone ebook-collection-analyze`;
- unveränderlicher Plan aus dem neuesten `COMPLETED`-`ScanRun` eines
  aktivierten EBOOK-`ScanRoot`;
- ausschließlich aktuelle `PRESENT`-Beobachtungen mit exakt gleichem relativem
  Pfad, Größe und Änderungszeitpunkt für EPUB/MOBI/AZW/AZW3/PDF;
- im Default genau ein gestreamter Plan-Read mit höchstens 500 Items je
  Insert-Batch und optionalem `--plan-limit` für globale deterministische
  Piloten;
- alternativ `--plan-per-format N` für höchstens N stabil sortierte Items je
  vorhandenem unterstütztem Format; gegenseitig exklusiv zu `--plan-limit`;
- persistente Lease, 1 bis 8 Worker, höchstens zwei beanspruchte Workerwellen
  und 30-Sekunden-SQLite-`busy_timeout`;
- kontrollierte Teil-Invocation über `--max-items` sowie Resume desselben Plans
  über `--resume-run`, ohne abgeschlossene Items zu wiederholen;
- exakte Evidence-Wiederverwendung oder `--fresh` für den gesamten neuen Lauf;
- per-File-Fehlerfortsetzung mit pfadfreien Fehlercodes und begrenzten
  Analyse-/Quality-Zählern;
- prozesslokaler thread-sicherer Versionsprobe-Cache ausschließlich im
  Batch-Modus;
- keine Source-Media-Mutation, keine `Relation`, keine Confidence und keine
  kanonischen Metadaten.

Sieben Batch-Integrationstests bestanden in 1 Minute 20 Sekunden. Der
Skalierungsfall bestätigt einen Plan-SELECT und Insert-Batches von 500, 500
und 201 für 1.201 synthetische Beobachtungen. Fünf CLI-/Bootstrap-Tests
bestanden in 28 Sekunden und prüfen Teil-Invocation, Resume, path-freie
Ausgabe, unveränderte Source-Dateien und getrennte beschreibbare Runtime-Pfade.
Der verfeinerte Tool-Versionsprobe-Cache bestand seinen gezielten
Parallelitätstest. ADR-0021 dokumentiert den Vertrag.

Der vollständige W3-015-Stand bestand mit Python 3.12.10 lokal
`ruff check .`, Mypy für 82 Source-Dateien und alle 239 Pytest-Tests in
18 Minuten 43 Sekunden. Der JUnit-Bericht liegt unter
`C:\rep\artifacts\FolioTone\w3-015-test-results\pytest-full.xml`. Das Wheel
`C:\rep\artifacts\FolioTone\w3-015-wheel-01\foliotone-0.1.0-py3-none-any.whl`
ist 134.583 Byte groß, hat SHA-256
`3a4d98aa852769c83dc2019f1e986cbacd41931ec38558f38b02ef6b3fd99a2e`
und enthält Collection-Domainmodell, Persistenz, Workflow und Migration
`0007_ebook_collection_batches`.

Commit `9a6b2d1ace10b1ef57c4402439ba782ede233b04` bestand in PR #25 den
vollständigen Remote-Gate mit Ruff, Mypy, 239 Pytest-Tests und allen Docker-
Smokes. Merge-Commit `fe3672a7002137859607dacb12072eeae35e268a` und GitHub
Actions Run `31900550819` auf `main` waren erfolgreich. Der anschließend
versionierte CI-Vertrag führt die Vollsuite nur am PR oder manuell aus; ein
`main`-Push erhält nur den kurzen Merge-/Whitespace-Vertrag.

### Deterministischer privater Collection-Bericht

- `EbookCollectionReportService`, Profil `ebook-collection-report/v1` und CLI
  `foliotone ebook-collection-report`;
- konsistenter read-only Snapshot eines persistierten, nicht mehr `RUNNING`
  befindlichen Collection-Laufs ohne Source-Media- oder Toolzugriff;
- vollständige Format-, Analyse-, Quality- und Befundzähler sowie begrenzte,
  priorisierte Review-Items mit exakten verfügbaren `ToolExecution`-Quellen;
- Exact-Duplicate-Kandidaten für gleiche vollständige `FILE_SHA256`-Werte und
  Content-Variant-Kandidaten für gleichen normalisierten Text bei
  unterschiedlichen vollständigen Datei-Hashes;
- sortierte Streaming-Abfragen mit `fetchmany(500)`, begrenzte Top-Gruppen und
  explizite Gesamt-/Truncation-Angaben;
- byte-stabile private JSON-/CSV-/Checksum-Artefakte in einem
  inhaltsadressierten Verzeichnis außerhalb des Source Root;
- keine rohen Fingerprints, keine `Relation`, keine Confidence und keine
  Identitätsentscheidung.

Der einzelne umfassende Berichtstest bestand nach der finalen
Projektionsprüfung in 21,33 Sekunden; der direkt
betroffene Head-Migrationstest bestand in 19,38 Sekunden. Ruff war für die
geänderten Source-/Testdateien erfolgreich, Mypy für 85 Source-Dateien. Ein
erneuter vollständiger lokaler Pytest-Lauf wurde bewusst nicht dupliziert. Der
CI-Vertrag verlangt genau einen vollständigen `quality`-Lauf am Pull Request
und nach dem Merge nur den kurzen `post-merge-contract`. Commit
`0237861bb1a02455fa65d2a5f754e46bb4530d92` wurde über PR #26 als
`111267f8a3c66e629cfd4b61d006c1731a9d9b12` gemergt; der Main-Lauf
`31900986647` benötigte für den Post-Merge-Job drei Sekunden.

Das Wheel
`C:\rep\artifacts\FolioTone\w3-016-wheel-01\foliotone-0.1.0-py3-none-any.whl`
ist 147.477 Byte groß, hat SHA-256
`7b69ea169d1f07adfe1780a4acc91ee19ef6298b51237c45dc85142a164a0482`
und enthält Report-Query, Workflow, CLI-Anbindung und Migration `0008`.

Bereits gemergte Migrationen werden nicht rückwirkend verändert.

### Reale Collection-Härtung und selektive Duplikatbestätigung

- unveränderte Scan-Observationen übernehmen vollständige jüngste
  Hash-Evidence ohne erneuten Source-Read; fehlende Evidence wird selektiv
  ergänzt;
- 1 bis 8 begrenzte Hash-Worker, set-orientierte Indexwrites und atomare
  Fingerprint-Batches beseitigen die gemessenen Persistenzengpässe;
- per-File-Hash-I/O-Fehler bleiben isoliert und werden durch den nächsten
  normalen Scan ausschließlich für die fehlenden Objekte erneut versucht;
- `--plan-per-format N` ergänzt einen gegenseitig exklusiven,
  formatabdeckenden Pilotmodus neben dem globalen `--plan-limit`;
- `ebook-duplicate-hash/v1` und `foliotone ebook-hash-candidates` berechnen
  vollständiges SHA-256 nur für aktuelle Mitglieder mehrfach belegter
  `QUICK_FILE`-Gruppen ohne vorhandenen Vollhash;
- der reale Vollhashlauf belegte eine wiederholte historische
  Fingerprint-Aggregation als mehrstündigen SQL-Engpass; die Auswahl schränkt
  nun zuerst auf den aktuellen Scan ein und materialisiert genau einen
  verbindungslokalen Temp-Snapshot pro Invocation;
- der gemessene Index `ix_fingerprints_target_profile_id_value`, stabile
  Temp-Keyset-Batches, `--max-items`, 1 bis 8 Worker und atomare Writes machen
  die Duplikatbestätigung begrenzt und durch denselben Aufruf fortsetzbar;
- pfadfreie, sofort geleerte Phasen- und Batch-Ausgaben machen auch die
  Kandidatenauswahl und den Migrationsschritt beobachtbar;
- `ebook_candidate_hash_runs`, eine rootweite partielle Active-Run-
  Eindeutigkeit und ein separater Lease-Keeper verhindern konkurrierende
  Kandidaten-Hashläufe und halten auch lange Einzelhashes lebendig;
- Fingerprint-Insert und Fortschrittszähler werden pro Batch in derselben
  gefenceten Transaktion persistiert; ein stale übernommener Vorgänger kann
  keine nachträgliche Evidence schreiben;
- `foliotone ebook-hash-status` liest Run-ID, Phase, Heartbeat, Lease-Ablauf
  und Zähler pfadfrei über SQLite `mode=ro`, erzeugt keine Verzeichnisse und
  migriert die Datenbank ausdrücklich nicht; der optionale JSON-Vertrag gibt
  nur freigegebene IDs, Zeitpunkte, Lease-Zustand und Zähler aus;
- Observation-Prüfung vor und nach dem Hash verhindert, dass inzwischen
  veränderte Source-Dateien falsche Evidence erhalten;
- ein privater read-only Vierformat-Pilot bestätigte reale EPUB-, PDF-, AZW3-
  und MOBI-Verarbeitung sowie exakte Evidence-Wiederverwendung, ohne private
  Pfade, Inhalte oder Sammlungskennzahlen in Git zu übernehmen.
- `ebook-inventory-report/v1` und `foliotone ebook-inventory-report` erzeugen
  aus dem neuesten abgeschlossenen Scan ohne Source-Zugriff vollständige
  Format-/Byte-Summen, Hash-Abdeckung, offene Quick-Kandidaten und exakte
  Duplikatsummen;
- Gruppen-/Mitgliederlimits begrenzen private Pfaddetails, während vollständige
  Summen und Kürzungsmarker erhalten bleiben; rohe Hashwerte, Relation,
  Keep-Präferenz und Identitätsurteil werden nicht ausgegeben.
- `foliotone ebook-postscan-verify` prüft den paketierten Alembic-Head,
  Source-Scan- und Kandidaten-Hash-Lineage, bytegenaue Inventarartefakte sowie
  die begrenzte Formatabdeckung eines expliziten `EbookCollectionRun` über
  dieselbe echte Read-only-Verbindung und öffnet keine Source Media;
- 25 gezielte CLI-, Resume-, Lease-, Migrations-, Persistenz- und
  Dokumentationsvertrags-Tests bestanden; Ruff und der gezielte Mypy-Lauf waren
  ohne Befund. Der vollständige Gate bleibt dem Pull Request vorbehalten.
- 26 gezielte Kandidaten-Hash-Lease-, Status-, Migrations-, Persistenz- und
  Dokumentationsvertrags-Tests bestanden in 3 Minuten 56 Sekunden. Sie decken
  konkurrierende Besitzer, root-parallele Läufe, stale Takeover, atomaren
  Batch-Rollback und die read-only Statusabfrage ab; Ruff und der gezielte
  Mypy-Lauf waren ohne Befund.
- 30 gezielte Persistenz-, Lease-, Kandidaten-Hash-, Collection- und
  Postscan-Verifikationstests bestanden in 7 Minuten 2 Sekunden. Sie decken
  echte Read-only-Verbindungen, lange Einzelhashes, Keeper-Ausfall,
  `KeyboardInterrupt`, harten synthetischen Prozessabbruch und die
  Abschlusszustände `COMPLETE`, `PENDING`, `DEGRADED` und `INVALID` ab. Nach
  der dynamischen Bindung an den paketierten Alembic-Head bestanden die fünf
  direkt betroffenen Tests erneut in 43,48 Sekunden; Ruff und Mypy waren ohne
  Befund.

ADR-0015, ADR-0021, ADR-0023, ADR-0024 und ADR-0025 dokumentieren die
verbindlichen Resume-, Lease-, Plan-, Hash- und Inventarverträge. Die
vollständige lokale Testsuite wird nicht während jeder Iteration wiederholt;
gezielte Source-/
Integrationstests laufen während der Entwicklung, der vollständige Gate genau
einmal am Pull Request.

Die gezielte Performance-Verifikation bestand 13 Kandidaten-, Migrations-,
Query-Plan- und Dokumentationsvertrags-Tests in 1 Minute 28 Sekunden. Ruff und
der gezielte Mypy-Lauf waren ohne Befund. Ein zusätzlicher synthetischer Lauf
mit 100.000 historischen Quick-Fingerprint-Zeilen materialisierte genau eine
aktuelle Gruppe und verarbeitete zwei Batchgrößen-1-Kandidaten in 0,395
Sekunden. Private Collection-Pfade oder Laufzeitkennzahlen wurden nicht in Git
übernommen.

## Kanonische Fortsetzung

Die einzige kanonische Ausführungsfront steht am Anfang von `BACKLOG.md`.
`CS-01` ist abgeschlossen. `collection-state/v1` materialisiert die
persistierte Evidence genau eines abgeschlossenen book-only `ScanRun` als
immutable, rebuildbaren und content-addressed Snapshot. Migration `0023`
persistiert Snapshot, Komponenten, vollständige Zähler und itembezogene
Zustände insert-only. `collection-state-build` liest ausschließlich
persistierte Evidence in deterministischen Keyset-Pässen;
`collection-state-report` verwendet eine echte SQLite-Read-only-Verbindung und
bleibt pfad- sowie metadatenwertfrei. Kein Pfad öffnet Source Media, startet
Tools oder Provider oder erhält Mutation Authority.

`CS-02` ist ebenfalls abgeschlossen. `collection-state-diff/v1` trennt sieben
direkt belegte Änderungskategorien, zählt den vollständigen Vergleich und
begrenzt nur die nach opaque `File`-ID paginierten Details.
`collection-query/v1` akzeptiert ausschließlich einen begrenzten `AND`-/`OR`-
AST mit festen Feldern, Operatoren und `FILE_ID_ASC`. Migration `0024` bindet
Statuswerte, Finding-Codes und ausgewählte Metadaten-Candidates insert-only an
den exakten Snapshot und projiziert nur diese Werte in FTS5. Query-History,
Content, OCR, Netzwerk, API und UI bleiben ausgeschlossen. Maschinenreports
bleiben metadatenwertfrei; private Werte sind nur mit `--private-details` in
interaktiver Textausgabe sichtbar und absolute Pfade werden ausgefiltert.

`CS-03` ist ebenfalls abgeschlossen. ADR-0060 und Migration `0025` ergänzen
`library-health/v1` als immutable, content-addressed Projektion über den
exakten `CollectionState` und Query-Index. Sie besitzt sieben unabhängige
Dimensionen mit eigener Coverage und eigenem Status, vollständige Finding-
Counts, höchstens 64 opaque Samples je Finding und keinen Gesamtscore.
`library-health-report` liest SQLite tatsächlich read-only und kann einen
älteren kompatiblen Snapshot ohne Kausalitätsbehauptung vergleichen.

Für CS-01 bestanden 16 dedizierte Tests und ein betroffener 60-Test-Verbund.
Nach dem vollständigen lokalen Lauf bestanden die 32 direkt relevanten
CollectionState-, Bootstrap- und Dokumentationsfälle erneut. Repository-Ruff
und Mypy für 194 Source-Dateien waren grün. Nach Integration des parallelen
S-W10-05A-Commits bestand der exakte rebased Head zusätzlich 73 betroffene
Tests; ein hostprivilegabhängiger Symlink-Fall wurde übersprungen. Der
vollständige Pytest-Lauf vor diesem schemafreien Rebase bestand 1.751 Tests,
übersprang neun und zeigte nach Korrektur des einzigen CS-01-eigenen
Bootstrap-Vertrags ausschließlich die 47 bereits auf unverändertem Windows-
`main` reproduzierten CRLF-/Long-Path-Baselinefehler. Der vollständige PR-CI-
Gate bleibt der kanonische Nachweis für den exakten stabilen Head.

Für CS-02 bestanden 28 dedizierte Fälle. Der synthetische 600-Dokumente-Lauf
blieb für die FTS-Suche unter drei Sekunden und bestätigte den FTS5-Virtual-
Table-Index. Der betroffene Persistenz-, Bootstrap- und
Dokumentationsverbund bestand am finalen lokalen Stand 98 Tests. Eine zunächst
fehlende FTS-Tabelleninventarisierung sowie nicht als Migration benannte
Migrationsszenarien wurden korrigiert und darin grün nachgewiesen.
Repository-Ruff, die statischen Vertragstests und Mypy für 201 Source-Dateien
waren ohne Befund. Der vollständige lokale Lauf bestand 1.788 Tests,
übersprang zehn und zeigte ausschließlich die 47 bekannten Windows-CRLF-/
Long-Path-Baselinefehler; keine CS-02-Datei und keine neue Fehlersignatur war
betroffen. Der vollständige PR-CI-Gate ist vor dem Git-Abschluss für den
stabilen Head zu vervollständigen.

Für CS-03 wurden elf neue synthetische Contract-, Migrations-, Persistenz-,
Rollback-, Vergleichs-, Privacy-, Read-only- und Sicherheitsfälle sowie sechs
direkt betroffene Regressionen grün nachgewiesen. Der fokussierte Ruff-Lauf
war ohne Befund; Mypy prüfte die vier neuen Source-Module erfolgreich. Nach
Aufnahme des kanonischen Schreibplans bestanden zusätzlich 15 betroffene
Planungs-/Dokumentationsverträge. Gemäß Test Policy und ausdrücklicher
Ressourcenanforderung wurde keine weitere vollständige lokale Suite gestartet.
Der vollständige PR-CI-Gate läuft genau einmal auf dem stabilen Head und ist
Merge-Voraussetzung.

`W10-005` ist als getrennte `FRONTIER`-Wave abgeschlossen. Capability-Auflösung,
`quarantine-authorize`, `quarantine-execute` mit zweiter
Bestätigung und One-use-Fencing sowie no-move `quarantine-recover` sind
vorhanden. Kein Slice erweitert die Ein-Datei-/Same-Filesystem-Grenze oder
behauptet atomare No-Replace-Semantik. Die zweite Bestätigung bleibt auf nicht
geloggtes `stdin` beschränkt. In `W9-007` sind `S-W9-007A` bis `S-W9-007C`
umgesetzt. ADR-0066 hat `FG-W10-RENAME` danach nur für Same-Parent-
`FILE_RENAME` entschieden; `S-W10-RN01` bis `S-W10-RN04` sind umgesetzt.
FUT-011 ist durch ADR-0067 entschieden; `S-FUT11-01` ist der nächste
freigegebene Slice. Die verbleibenden operation-spezifischen W10-Gates bleiben
Entscheidungen und sind keine freigegebenen Implementierungswaves.

`OPS-001` ist ein getrenntes lokales Betriebsverfahren für den vollständigen
privaten Inventory-/Hash-/Collection-/Verifier-Lauf. Es verwendet den
read-only Bestand, erzeugt keine CI-Evidence und schreibt keine privaten
Artefakte nach Git.

EB-07 und EB-08 sind abgeschlossen. ADR-0034 ist vollständig umgesetzt;
S-EB08-01 bis S-EB08-09 sowie W9 sind `DONE`. `foliotone.consolidation`
liefert immutable DTOs, `canonical-json/v1`, reine Preconditions und Blocker,
die reviewpflichtige Keep Preference, Migration `0016`, insert-only Persistenz,
den read-only Report `ebook-consolidation-report` und den statischen
Non-Execution-Gate gegen Filesystem-Mutationen und mutierende
Calibre-Command-Shapes. W9-Pläne bleiben dauerhaft `NOT_EXECUTABLE`; nur ein
separater, kurzlebiger ADR-0056-Authorization-Snapshot darf den vorhandenen
Interim-Quarantäneexecutor öffnen.

FG-03A ist durch ADR-0035 akzeptiert. Das Gate legt den
`provider-cache-entry/v1`-Vertrag mit Result-Status, Payload-Kind,
Freshness-Triade, getrenntem vierteiligen Source- und fünfteiligen
Mapping-Input-Key, Negative-Cache-Regeln, Mapping-Reanalyse ohne Refetch,
generation-gefencetem CAS und bounded Retention fest. EB-03A und der
Open-Library-Slice EB-03B sind abgeschlossen.

EB-00, EB-01/E4, EB-02, EB-05, EB-06, EB-07 und EB-08 sind abgeschlossen. Die
Reihenfolge, Stop-Gates und atomaren Pakete stehen in
`EBOOK_ENDGAME_IMPLEMENTATION_PLAN.md` und der historisch benannten Datei
`EBOOK_SPARK_WORK_PACKAGES.md`. Modell- und Agentenauswahl folgen
repositoryweit `MODEL_ROUTING_POLICY.md`: Status und deterministische
Prüfungen beginnen mit `LOCAL`, vollständig festgelegte Pakete verwenden
`ECONOMICAL`, gewöhnliche Integration `BALANCED` und kritische Architektur-,
Security-, Privacy-, Nebenläufigkeits- oder W10-Verträge `FRONTIER`.
`AI_WORKFLOW.md` und `TEST_POLICY.md` regeln die Wave und ihren Local-first-
Nachweis. Private Pfade, Runtime-Daten, Kennzahlen und Berichte bleiben
außerhalb von Git; Source Media bleibt unverändert.

`EBOOK_WRITE_PIPELINE_PLAN.md` ist die kanonische End-to-End-Leserichtung für
die spätere book-only Schreibstrecke. Sie verbindet den implementierten
read-only Pfad mit `W9-006`/`W9-007`, den getrennten Metadata-, Sidecar-,
externen Library-, Rename- und Archive-Write-Gates sowie Rescan,
Verifikation, Recovery, Rollback/Purge und FUT-011. ADR-0061 autorisiert die
getrennte Writer-Entwicklung mit synthetischen Fixtures, aber keine pauschale
reale Mutation. Das Dokument setzt keine zweite Statusachse; die aktuelle
Front bleibt ausschließlich im Backlog.

Die langfristige Produktvision und Medienfolge stehen als nicht statussetzende
Entwürfe in `docs/vision/EVIDENCE_DRIVEN_COLLECTION_INTELLIGENCE.md` und
`docs/planning/FUTURE_CAPABILITY_MAP.md`. Sie ersetzen weder Backlog noch
ADRs. Die unveränderte Roh-Ideensammlung liegt im ausdrücklich
nichtkanonischen öffentlichen Bereich
`docs/ideas/owner-notes/raw/Gedanken_für_die_Zukunft.md`.

ADR-0042 und FUT-010 integrieren als vorgeschlagene Querschnittsfortsetzung die
portable Objekt-Lineage sowie bounded, idempotenten Austausch und
konfliktbewusste Fusion mehrerer FolioTone-Systeme. Vor Code sind getrennte
Gates für Knoten-/Objektreferenzen, Clone-/Restore-Semantik,
Austauschpaket, Merge/Trust/Decision Compatibility und read-only
Kennzeichnungsträger erforderlich. Ein Tag, Pfad oder Hash ist dabei keine
alleinige Identitätsautorität. ADR-0042 ist `Proposed`; es existiert weder ein
Export-/Import-/Sync-Workflow noch ein Kennzeichnungs- oder External-Library-
Write. ADR-0042 bleibt `Proposed` und blockiert die lokale book-only
`CollectionState`-Projektion nicht.

Music W4 bleibt die nächste geplante vollständige Mediendomäne, wird nach
Abschluss von `CS-03` aber nicht automatisch aktiviert. Book-only Leistungen
und offene Music-Anteile besitzen im Backlog getrennte IDs und Statuswerte.
Bilder und weitere Linien bleiben ebenfalls getrennt geplant.

Die aktuell implementierte Produktoberfläche bleibt bis zur Umsetzung der
neuen Waves ausschließlich die CLI. ADR-0067 entscheidet FUT-011 mit stabilen
Application-Verträgen, getrennten Einstiegen je Medienlinie, lokaler
Authentisierung, Autorisierung, Privacy, Audit, Jobs und Workertrennung.
UI- oder API-Bedarf öffnet keine W10-Capability. Externe Tool-Ergebnisse werden
weiterhin als Evidence behandelt und nicht direkt zu kanonischen Metadaten.

## Verbindliche Sicherheitsgrenzen

- `/data` ist persistent read-write.
- Source Media unter `/media` bleibt read-only.
- Keine Source-Media-Delete-/Move-/Rename-/Retag-Operation durch W0 bis W9.
- `DELETED` ist ein Indexzustand und keine Delete-Operation.
- `FileRelocationCandidate` ist Evidence und keine Move-/Rename-Ausführung oder Identitätszusammenführung.
- Scan-Resume ist Orchestrierung und verändert Source Media nicht.
- `EbookOperationRecipePlan` bleibt dauerhaft `NOT_EXECUTABLE`; private
  relative Locator in seinem Candidate sind keine Dateisystem-Capability.
- Keine automatische Calibre-Modifikation.
- Keine write-capable externe Tooloperation.
- Externe Tool-/Provider-Ergebnisse sind Evidence, nicht kanonische Wahrheit.
- Absolute private Pfade werden nicht als persistierte Tool-Input-Identität gespeichert.
- ADR-0056 erlaubt ausschließlich die enge Interim-Ein-Datei-Quarantäne;
  atomarer Move und weitere Mutationstypen bleiben operativ getrennt.
- ADR-0061 erlaubt ihre kontrollierte Entwicklung, ist aber weder technische
  Operations-ADR noch konkrete Runtime-Authorization für reale Source Media.

## Dokumentations- und Lizenzregeln

- Die kanonische erklärende Dokumentation ist grundsätzlich deutsch; etablierte technische Begriffe bleiben in kanonischer Form.
- `docs/reference/GLOSSARY.md` ist für fachliche Kernbegriffe maßgeblich.
- Der zweisprachige Lizenzblock am Anfang der Root-README ist geschützt und darf nur auf ausdrücklichen Benutzerauftrag geändert werden.
- `LICENSE.md` bestimmt, dass die englische Lizenzfassung rechtlich maßgeblich ist.

## Handover-Qualitätsregel

Am Ende einer substanziellen Arbeit müssen `PROJECT_STATUS.md` und `BACKLOG.md` den realen Repositoryzustand wiedergeben. Tests dürfen nur als bestanden dokumentiert werden, wenn sie tatsächlich ausgeführt wurden. Ein zukünftiges KI-System darf zur Fortsetzung nicht auf den bisherigen Chat angewiesen sein.
