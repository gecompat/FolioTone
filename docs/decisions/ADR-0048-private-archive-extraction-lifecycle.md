# ADR-0048: Privater Archive-Extraction-Lifecycle

**Status:** Akzeptiert

**Datum:** 2026-08-20

**Geltungsbereich:** FG-A-EXTRACTION-LIFECYCLE, S-EBAR-05A, S-EBAR-06A,
FG-A-EXTRACTION-QUOTA, S-EBAR-04Q, S-EBAR-04A und EBAR-06

## Kontext

[ADR-0039](ADR-0039-safe-archive-runtime-and-secret-channel.md) verlangt für
eine erfolgreiche private Testextraktion Live-Budgets, eine erneute
no-follow-Workspaceprüfung, vollständige Member-/Größen-/CRC-Konsistenz,
Streaming-Hashes und Cleanup ohne Partial-Evidence. EBAR-04 stellt den
isolierten Runner bereit, EBAR-05 das formatgelockte Listing und den getrennten
Integritätstest.

Der aktuelle Runner kann diese Schritte nicht sicher verbinden. Seine
öffentliche `run`-Methode bereinigt den privaten Sandbox-Root vor der Rückgabe.
`LocalSandboxFilesystem.verify_after_run` verwendet außerdem die
Preflight-Prüfung erneut und verlangt deshalb einen leeren Output-Root. Eine
erfolgreiche `7zzs x`-Ausgabe wird damit vor einer Memberprüfung verworfen und
als Fehler behandelt. Der Runner besitzt weder einen privaten
Workspace-Consumer noch einen unterscheidbaren Live-Workspace-Abbruchgrund.

Auch die EBAR-05-Grenze reicht für EBAR-06 noch nicht aus. Der gelockte Parser
kennt private Memberlocator und CRC32-Werte, die öffentliche Projektion gibt
jedoch absichtlich nur Status, Profile, opaque IDs und `member_count` aus.
Eine erneute Listingausführung in EBAR-06 würde Execution-Provenance und
Inputidentität duplizieren und ist nicht zulässig.

gzip, bzip2, xz und zstd sind weiterhin nur
`OUTER_COMPRESSION_ONLY`. Ihre sichere zweistufige Dekompression, erneute
Signaturprüfung und TAR-Verarbeitung besitzt noch keinen akzeptierten
Lifecycle- oder Lineage-Vertrag. Die frühere Formulierung „bis EBAR-06“ ist
deshalb keine Implementierungsfreigabe.

## Entscheidung

FG-A-EXTRACTION-LIFECYCLE ist als Boundary- und Paketreihenfolge akzeptiert.
Vor EBAR-06 werden vier mechanische Pakete und ein separates Quota-Gate
eingefügt:

```text
EBAR-05
    -> S-EBAR-05A privater Listing-/CRC-Handoff
    -> S-EBAR-06A reiner versiegelter Extraction-Consumer
    -> FG-A-EXTRACTION-QUOTA harter Workspace-Cap-Vertrag
    -> S-EBAR-04Q mechanische Quota-Capability
    -> S-EBAR-04A privater Workspace-Consumer-Lifecycle
    -> EBAR-06 direkte unverschlüsselte Extraction
```

Die Pakete ändern keine öffentliche Archive-API, keine Persistenz und keine
Secret-Grenze. EBAR-06 verarbeitet ausschließlich direkte Storage-Familien.
Alle vier äußeren Kompressionsformen bleiben bis zu einem separaten
FG-A-WRAPPER-PIPELINE ohne Provider- oder Extraction-Lauf.

## S-EBAR-05A: privater Listing-/CRC-Handoff

S-EBAR-05A ergänzt in `provider.py` einen underscore-internen immutable
Handoff. Er enthält nur die für EBAR-06 notwendigen privaten normalisierten
Memberwerte:

```text
archive_full_sha256
volume_group_fingerprint
signature_profile
storage_family
case_kind
parser_profile
format_lock_profile
format_lock_sha256
compatibility_profile
member_ordinal
member_locator
member_kind
declared_compressed_bytes
declared_uncompressed_bytes
listed_crc32 oder NONE
member_identity
```

Der Handoff referenziert dasselbe konkrete `ArchiveProviderOutcome`-Objekt und
exakt dieselben Listing-/Integrity-`ToolExecution`-Objekte wie der einmalige
EBAR-05-Lauf. Zusätzlich bindet ausschließlich der private Envelope die
Signatur-/Storage-/Fall- und Lockidentity sowie das private
`ArchiveListingResult`. Diese zusätzlichen Achsen werden nicht als bereits in
der öffentlichen Projektion vorhanden behauptet. Der Handoff darf Listing oder
Integrity weder wiederholen noch aus der öffentlichen Projektion
rekonstruieren.

## S-EBAR-06A: reiner versiegelter Extraction-Consumer

Vor jeder Runner-Erweiterung entsteht in `extraction.py` ein underscore-
interner, reiner Consumervertrag. Er akzeptiert ausschließlich den privaten
S-EBAR-05A-Handoff und eine geliehene Workspace-Capability-Schnittstelle; er
startet weder Tool noch Container und besitzt keinen absoluten Pfad. Seine
reine Reduktion implementiert Membergleichheit, Größen-, CRC-, SHA-256-,
Deadline-, Budget- und Keine-Partial-Evidence-Regeln. Damit existiert der echte
Consumer bereits, wenn S-EBAR-04A den Linux-Lifecycle integriert; ein frei
erfundener Testcallback ist keine Runtime-Authority.

S-EBAR-06A allein autorisiert keine Extraction. Ohne akzeptiertes
FG-A-EXTRACTION-QUOTA, abgeschlossenes S-EBAR-04Q und S-EBAR-04A bleibt jeder
reale Extraction-Aufruf `TOOL_UNAVAILABLE`.

Ein Extraction-Handoff entsteht nur, wenn alle folgenden Bedingungen gelten:

- Signatur- und Formatlock autorisieren einen direkten `MEASURED`-Fall;
- Listing ist `LISTED`;
- Encryption ist `NONE`;
- Integrity ist `PASSED`;
- die Safety Policy ist `ACCEPTED`;
- alle Memberlocator, Größen, CRC-Werte und Identitäten stammen aus demselben
  vollständig finalisierten gelockten Parserresultat.

Bei Cancellation entsteht wie bisher kein terminaler Archive-Snapshot. Bei
Wrappern, Verschlüsselung, nicht akzeptierter Policy, Listing-/Integrity-
Fehlern oder einer Lineageabweichung bleibt der private Handoff leer.

Der Handoff wird nicht aus `foliotone.archive.__init__` exportiert. Seine
`repr`-/`str`-Darstellung, Exceptions, öffentliche DTO-Projektion und
`ToolExecution` enthalten weder Locator noch CRC-Wert. Er besitzt keine
Serialisierungs-, Persistenz-, Log-, Artefakt- oder Cache-Schnittstelle. Ein
öffentlicher Aufrufer kann weder einen Handoff einspeisen noch Memberwerte
überschreiben.

## S-EBAR-04A: privater Workspace-Consumer-Lifecycle

Die öffentliche Runner-Methode bleibt die Authority für Listing und
Integrity und akzeptiert keinen frei injizierbaren Callback. Das
Extraction-Command-Shape `x` wird über diese öffentliche Grenze fail-closed
abgewiesen. Nur eine underscore-interne Runner-Grenze darf das feste
Extraction-Command zusammen mit dem exakten privaten Workspace-Consumer aus
S-EBAR-06A ausführen.

Der Runner bleibt alleiniger Besitzer von Input-Staging, Output-Workspace,
Container-ID, Cleanup und den zugehörigen Hostlocators. Der Consumer erhält
keinen `Path`, keinen frei verwendbaren File Descriptor und keine
Cleanup-Funktion. Während des synchronen Callbacks leiht der Runner eine
opaque, pathfreie Workspace-Capability mit ausschließlich bounded no-follow-
Operationen aus. Die Capability wird im `finally` des Callbacks invalidiert;
jeder spätere Zugriff schlägt mit einem festen pathfreien Fehler fehl.

Die Lifecycle-Reihenfolge ist exakt:

```text
Preconditions und Safety erneut prüfen
    -> opaque Quota-Slot leasen und per-run Authority attestieren
    -> private Input-/Output-Jobroots ausschließlich im Slot erzeugen
       und verifizieren
    -> Live-Workspace-Monitor scharf schalten
    -> festen Extraction-Container starten
    -> bei Cancellation oder Live-Befund Prozessbaum beenden
    -> Container stoppen/entfernen und Abwesenheit beweisen
    -> Monitor finalisieren
    -> nur bei erfolgreichem Toollauf Workspace-Capability an Consumer leihen
    -> Consumer revalidiert und erzeugt nur vorläufige In-Memory-Evidence
    -> Capability invalidieren
    -> Runner bereinigt Output- und Input-Jobroots vollständig
    -> leeren Slot no-follow revalidieren
    -> Slot-Capability invalidieren und Slot an S-EBAR-04Q zurückgeben
    -> erst nach erfolgreichem Return vorläufige Evidence freigeben
```

Kann die Container-Abwesenheit nicht bewiesen werden, wird der Consumer nicht
aufgerufen und der Runner löscht keinen möglicherweise noch gemounteten
Host-Workspace. Kill, Remove und Abwesenheitsprüfung werden auf jedem Pfad
bounded versucht. Nach bewiesener Abwesenheit versucht der Runner auf jedem
Pfad das Filesystem-Cleanup; nach einem Consumeraufruf liegt dieses Cleanup
ausnahmslos im anschließenden `finally`. Der Consumer besitzt keine
Möglichkeit, Cleanup zu überspringen, zu ersetzen oder selbst auszuführen.
Ein Cleanup- oder Absencefehler verwirft jede vorläufige Evidence und bleibt
ein pathfreier administrativer Recovery-Befund.

Lease, per-run Authority-Attestation, Empty-Revalidation und Return sind Teil
desselben `finally`-geschützten Lifecycles. Bei unbewiesener
Container-Abwesenheit, Cleanup-, Empty-Revalidation-, Attestations- oder
Returnfehler wird der Slot niemals in den leasebaren Pool zurückgestellt,
sondern durch S-EBAR-04Q für die administrative Recovery quarantänisiert. Der
Gesamtstatus ist `TOOL_FAILED`, alle vorläufige Evidence wird verworfen und
eine spätere Wiederverwendung erfordert den im Quota-Gate akzeptierten
Recoverynachweis.

### Harte Workspace-Caps, Live-Beobachtung und Abbruch

Polling ist ausschließlich eine Early-Abort-Optimierung und niemals der
Beweis eines kumulativen Byte-, Member- oder Reserve-Limits. Vor S-EBAR-04A
muss FG-A-EXTRACTION-QUOTA einen konkreten, atomar beweisbaren Host-
Workspace-Cap akzeptieren. Bis dahin bleibt der reale Extraction-Backendpfad
`TOOL_UNAVAILABLE`.

Das Quota-Gate entscheidet mindestens:

- den exakten Byte- und Inode-Cap einschließlich notwendiger Parent-
  Verzeichnisse;
- die Host-Privilege- und Ownershipgrenze;
- Reservierung und Beweis von `min_workspace_free_reserve_bytes`;
- Mount-, Quota- oder Loopback-Lifecycle, Racefreiheit und Crash-Recovery;
- Supply Chain und feste argv/Exitcode-Verträge aller dafür benötigten Host-
  Werkzeuge oder alternativ der verwendeten Kernel-APIs;
- noexec/nosuid/nodev/no-follow sowie Unmount-/Detach-/Delete-Reihenfolge;
- fokussierte echte Linux-Nachweise für Cap, Überlauf, Cleanup und Recovery.

Ein bloßer periodischer Verzeichnisscan, `RLIMIT_FSIZE`, ein unquotierter
RW-Bind-Mount oder ein Testdouble genügt nicht. Insbesondere autorisiert diese
ADR weder ungepinnte Aufrufe von `fallocate`, `mkfs`, `losetup` oder `mount`
noch stillschweigend neue Host-Privileges.

Die bevorzugte kleinste Authority ist ein administrativ vorprovisionierter,
`noexec`/`nosuid`/`nodev` gemounteter Pool harter Quota-Slots. Die Runtime darf
nur eine unprivilegierte, opaque Slot-Capability leasen und zurückgeben. Das
Gate muss Slot-Byte- und Inode-Cap, Reserve, Ownership, Parallelität,
Authority-Attestation, Crash-Recovery und sichere Wiederverwendung exakt
festlegen. Es autorisiert keine spontane Runtime-Ausführung der oben genannten
Hostwerkzeuge und keine Ausweitung auf `root` oder `CAP_SYS_ADMIN`. Falls ein
harter Cap ausschließlich damit oder ohne atomaren Reservebeweis erreichbar
ist, bleibt die Runtime `TOOL_UNAVAILABLE`.

[ADR-0049](ADR-0049-bounded-archive-workspace-capability.md) entscheidet diese
offene Authority als dateisystemneutrale, atomar begrenzte
Workspace-Capability. S-EBAR-04Q implementiert ausschließlich den neutralen
Provider-, Lease-, Capability-, Return- und Quarantänevertrag. Reale
Extraction bleibt bis zu einem separat akzeptierten Plattformadapter
`TOOL_UNAVAILABLE`.

Nach einem akzeptierten Quota-Gate beobachtet der Live-Monitor während des
Toollaufs mindestens:

- reguläre Dateien und Verzeichnisse gegen `max_member_count` sowie die
  zulässigen impliziten Parent-Verzeichnisse;
- logische Bytegrößen je regulärem Member;
- die kumulative logische Workspacegröße gegen
  `max_workspace_bytes` und `max_total_uncompressed_bytes`;
- den freien Platz gegen `min_workspace_free_reserve_bytes`;
- Link-, Reparse-, Hardlink-, Device- und sonstige nicht reguläre Nodes;
- Sparse-/Alternate-Stream- und besondere Metadatenbefunde, soweit sie auf
  dem freigegebenen Linux-Dateisystem beweisbar sind.

S-EBAR-04A verwendet dafür keine neue öffentliche Statusachse. Ein privat
gelatchter Workspace-Abbruch wird über die bestehende Cancellation-/Kill-
Grenze an den Prozessrunner übergeben. Der Latchgrund ist immutable. Sind in
derselben Prüfung sowohl ein Sicherheits-/Limitbefund als auch eine
Benutzer-Cancellation sichtbar, hat der Sicherheits-/Limitbefund Vorrang;
ein zuvor gelatchter Grund wird nicht nachträglich umgedeutet. Nach der
Prozessbeendigung reduziert der Container-Runner den privaten Grund auf
`LIMIT_EXCEEDED` beziehungsweise den späteren
`VALIDATION_FAILED`-Extraction-Befund. Eine echte Benutzer-Cancellation bleibt
nur bei erfolgreichem Remove und Cleanup snapshotlos mit
`ToolExecutionStatus.CANCELLED`.

`max_single_member_bytes` wird zusätzlich als fester
`RLIMIT_FSIZE`-Soft-/Hard-Wert des Containers gesetzt. Der kumulative
Workspace-Cap bleibt trotzdem erforderlich. Kann das Backend Cap,
Reserveprüfung oder vollständige Prozessbeendigung bei einem Live-Befund nicht
beweisen, bleibt Extraction `TOOL_UNAVAILABLE`.

Die 600 Sekunden aus `max_extraction_seconds` umfassen Toollauf,
post-run-Revalidierung und Streaming-Hashing. Der Consumer prüft die monotone
Deadline mindestens vor jedem Member und jedem begrenzten Lesechunk. Ein
Timeout während Revalidierung oder Hashing verwirft alle vorläufigen
Memberwerte.

### Post-run-Revalidierung und TOCTOU

Der Consumer läuft erst, nachdem kein Containerprozess den Output-Workspace
mehr verändern kann. Er traversiert ausschließlich relativ zu der geliehenen
Workspace-Capability. Jeder Pfadabschnitt wird no-follow geöffnet; offene
Directory- und File-Handles werden während ihrer Prüfung gehalten. Für jedes
Objekt werden Typ, Device, Inode, Linkzahl, Modus, Größe und relevante
Metadaten vor und nach dem Lesen verglichen. Symlinks, Hardlinks,
Mount-/Devicewechsel, Reparse Points, FIFOs, Sockets, Block-/Character-
Devices, Sparse-Ausgaben, ACLs, xattrs, Owner-/Gruppenwiederherstellung,
setuid/setgid, besondere Flags oder eine Änderung während des Lesens ergeben
`VALIDATION_FAILED`.

Nach dieser Prüfung setzt der Consumer über die gehaltenen no-follow-Handles
ausschließlich Modus `0700` für Verzeichnisse und `0600` für reguläre Dateien
und revalidiert Typ, Identity und Modus erneut. Andere Metadaten werden weder
übernommen noch wiederhergestellt.

Die kanonische Locatorprüfung aus `archive-safety-policy/v1` wird erneut auf
jedes gefundene Ziel angewendet. NFC-, Casefold-, Separator- und
Parent-/Child-Kollisionen bleiben abgewiesen. Reguläre Dateien müssen exakt
der gelisteten regulären Membermenge entsprechen. Verzeichnisse dürfen nur
explizit gelistete Verzeichnisse oder notwendige kanonische Parents eines
gelisteten Ziels sein; weitere oder fehlende reguläre Ziele sind unzulässig.

Jede reguläre Datei wird einmal bounded gestreamt. Derselbe Bytestream zählt
`observed_uncompressed_bytes`, SHA-256 und, falls im privaten Listing
vorhanden, CRC32. Beobachtete und deklarierte Größe müssen gleich sein. Eine
vorhandene Listing-CRC muss exakt passen und ergibt `MATCHED`; ohne Listing-
CRC entsteht `NOT_AVAILABLE`. Eine CRC-Abweichung macht die gesamte
Extraktion `VALIDATION_FAILED`. Es gibt keine erfolgreiche Teilmenge.

## Status-, Exception- und Cleanup-Priorität

Öffentliche Statusliterale bleiben unverändert. Für einen Extraction-Versuch
gilt folgende terminale Priorität:

1. Nicht beweisbare Container-Abwesenheit, Cleanup-, Slot-Revalidierungs-,
   Attestations- oder Returnfehler sowie unbekannte Lifecycle-/Consumerfehler
   ergeben `TOOL_FAILED`, quarantänisieren den Slot und verwerfen alles.
2. Eine echte Benutzer-Cancellation erzeugt nach erfolgreichem Cleanup keinen
   terminalen Archive-Snapshot; die `ToolExecution` endet `CANCELLED`.
3. Fehlende Runtime-Authority oder eine nicht beweisbare Sandbox ergibt
   `TOOL_UNAVAILABLE`.
4. Ein Preflight-, Hard-Cap- oder zusätzlicher Polling-Budgetbefund ergibt
   `LIMIT_EXCEEDED`.
5. Das Überschreiten der Extraction-Deadline ergibt `TIMED_OUT`.
6. Ein nicht akzeptierter Exitcode oder anderer Toolfehler ergibt
   `TOOL_FAILED`.
7. Workspace-, Member-, Größen-, CRC-, Hash- oder TOCTOU-Abweichungen ergeben
   `VALIDATION_FAILED`.
8. Nur ein vollständig validierter Consumerbefund mit anschließend
   erfolgreichem Cleanup ergibt `EXTRACTED`.

Ein bereits vor dem Toolstart abgewiesener Member-/Pfadvertrag ergibt
`POLICY_REJECTED`; ein dabei überschrittenes festes Budget ergibt
`LIMIT_EXCEEDED`. Der Runner persistiert keine privaten Detailgründe.
Exceptions werden an der privaten Grenze auf eine feste path- und secretfreie
Allowlist reduziert. Raw-Exceptiontexte, Workspacepfade, Memberlocator und
CRC-Werte verlassen den In-Memory-Lifecycle nicht.

Schlägt Cleanup nach einer Cancellation fehl, dominiert der Cleanupfehler:
die `ToolExecution` endet `FAILED`, der terminale Extraction-Status ist
`TOOL_FAILED`, und es entsteht keine Member-Evidence. Diese Regel folgt der
Cleanup-Semantik aus ADR-0039.

## Folgepakete und Dateigrenzen

### S-EBAR-05A

Erlaubt sind ausschließlich:

```text
src/foliotone/archive/provider.py
tests/unit/test_ebar05_archive_provider.py
tests/integration/test_ebar05_archive_provider_integration.py
```

Das Paket prüft Einmallauf, Handoff-/Public-Projektionsgleichheit,
Execution-, Material-, Signature-, Storage-, Case- und Lockbindung,
Locator-/CRC-Redaktion, fehlenden Handoff für alle nicht extrahierbaren Fälle
sowie unveränderte Sourcebytes. Es ändert weder Runner, Parser, Workflow,
Persistenz noch öffentliche Exporte.

### S-EBAR-06A

Erlaubt sind ausschließlich:

```text
src/foliotone/archive/extraction.py
eine neue fokussierte Unit-Testdatei
```

Das Paket implementiert nur den underscore-internen reinen Consumer und seine
geschlossenen DTO-/Statusinvarianten. Tests verwenden eine bounded
Capability-Simulation für Membergleichheit, Directory-Parents, Größe, CRC,
SHA-256, Deadline, Kollisionen und Keine-Partial-Evidence. Es ändert weder
Runner noch Provider, führt kein Tool aus und erklärt keinen Backendpfad für
verfügbar.

### FG-A-EXTRACTION-QUOTA

Das Docs-only Sol-`high`-Gate folgt auf S-EBAR-06A und muss vor S-EBAR-04Q
angenommen werden. Es legt den konkreten harten Host-Workspace-Cap sowie die
exakten Code-/Testdateien eines nötigen mechanischen Vorpakets fest. Ohne diese
Entscheidung bleiben S-EBAR-04Q, S-EBAR-04A und EBAR-06 blockiert; Polling darf
nicht als Ersatz implementiert werden.

### S-EBAR-04Q

Das mechanische Paket folgt erst nach Annahme von FG-A-EXTRACTION-QUOTA und
implementiert exakt dessen Capability-, Provisionierungs-, Attestations- und
Recoveryvertrag. Das Gate legt die kleinste notwendige Datei- und Testgrenze
fest; ADR-0048 erfindet dafür keinen vorzeitigen Produktionsscope. S-EBAR-04Q
darf weder Container- noch Extraction-Lifecycle vorwegnehmen. Ohne positiven
realen Linux-Nachweis bleibt es nicht abgeschlossen.

### S-EBAR-04A

Erlaubt sind ausschließlich:

```text
src/foliotone/archive/container_sandbox.py
tests/unit/test_archive_container_sandbox.py
tests/integration/test_archive_container_sandbox_runtime.py
```

Das Paket prüft die gesperrte öffentliche Extraction, die exakte private
S-EBAR-06A-Consumergrenze, Lifecycle-Reihenfolge, harten Workspace-Cap,
Polling-Limit-/Cancellation-Latch, `RLIMIT_FSIZE`, Kill/Remove,
Container-Abwesenheit, Capability-Invalidierung, Consumer-Exception, Timeout
sowie Cleanup, Slot-Empty-Revalidation, Return und Quarantäne auf jedem Pfad.
Der reale Linux-Integrationstest muss beweisen,
dass der Consumer nur zwischen Container-Abwesenheit und Cleanup Zugriff
besitzt. Fehlt dieser Nachweis, stoppt das Paket; eine private
Testdouble-Simulation genügt nicht zur Runtime-Freigabe.

S-EBAR-04A beginnt erst nach Annahme von FG-A-EXTRACTION-QUOTA und Abschluss
von S-EBAR-04Q. Es konsumiert ausschließlich dessen exakte unprivilegierte
Workspace-Slot-Capability; Provisionierungs-, Mount- und Quota-Authority liegen
nicht im Runner.

### EBAR-06

Erlaubt bleiben ausschließlich:

```text
src/foliotone/archive/extraction.py
src/foliotone/archive/safety_policy.py
eine neue fokussierte Unit-Testdatei
eine neue fokussierte Integrationstestdatei
```

EBAR-06 verbindet nur den privaten S-EBAR-05A-Handoff, den reinen
S-EBAR-06A-Consumer und den privaten S-EBAR-04A-Lifecycle. Autorisiert sind
ausschließlich direkte
ZIP-/RAR4-/RAR5-/7z-/TAR-Fälle mit finaler `MEASURED`-Disposition,
`LISTED`, Encryption `NONE`, Integrity `PASSED` und Safety `ACCEPTED`.
Wrappers, Secretverarbeitung, Persistenz, W10 und Source-Mutation bleiben
ausgeschlossen.

## Separates FG-A-WRAPPER-PIPELINE

gzip, bzip2, xz und zstd bleiben `OUTER_COMPRESSION_ONLY`, Storage Family
`UNKNOWN`, `runtime_authorized=false` und ohne Provider-/Extraction-Lauf.
Ein späteres FG-A-WRAPPER-PIPELINE muss mindestens entscheiden:

- bounded äußere Dekompression und deren Tool-/Command-Authority;
- vollständige Byte-/Hash-Lineage des erzeugten inneren Streams;
- erneute Signature-v2-Prüfung und ausschließlich bestätigtes inneres TAR;
- eigene Listing-/Integrity-/Extraction-Execution-Provenance;
- Live-Budgets und Cleanup für beide Workspacephasen;
- Schutz gegen rekursive oder mehrschichtige Wrapper; `max_nested_depth=0`
  bleibt unverändert.

Ohne dieses Gate darf weder EBAR-06 noch ein späterer Orchestrator die vier
Wrapper still als TAR behandeln.

## Abnahme und Stopbedingungen

Jedes Folgepaket verwendet nur fokussierte Tests sowie Ruff, Mypy und
`git diff --check`; der vollständige Gate läuft genau einmal auf dem stabilen
PR-Stand. Die Pakete stoppen fail-closed bei:

- einem erforderlichen öffentlichen Callback oder frei injizierbaren
  Workspacepfad;
- einem Workspaceobjekt, das den synchronen Callback überlebt;
- nicht unterscheidbarer User-Cancellation und Workspacegrenze;
- einem nur per Polling statt durch einen akzeptierten harten Cap begrenzten
  Workspace;
- nicht beweisbarer Prozessbaumbeendigung, Container-Abwesenheit oder
  Cleanup-Reihenfolge;
- einer notwendigen Persistenz-, Secret-, Wrapper- oder W10-Entscheidung;
- einem Linux-Backend, das den akzeptierten harten Cap, no-follow-
  Revalidierung oder `RLIMIT_FSIZE` nicht belegen kann.

## Supersession

Diese ADR ersetzt ausdrücklich ausschließlich folgende frühere Klauseln:

- ADR-0046s Aussage, äußere Kompression werde erstmals in EBAR-06 privat
  dekomprimiert. Diese ADR trennte Wrapper zunächst in
  FG-A-WRAPPER-PIPELINE ab; ADR-0051 entscheidet inzwischen ausschließlich
  deren read-only Listing-/Integrity-Strecke. EBAR-06 bleibt wrapperfrei.
- ADR-0039s Reihenfolge, nach der Cleanup erst nach Evidence-Übernahme erfolgt.
  Für diesen Lifecycle bleibt Evidence bis nach erfolgreichem Cleanup nur
  vorläufig und wird erst danach freigegeben.

Alle übrigen Anforderungen aus ADR-0038, ADR-0039, ADR-0043, ADR-0046 und
ADR-0047 bleiben unverändert bindend.

## Folgen

- EBAR-06 beginnt erst nach S-EBAR-05A, S-EBAR-06A,
  FG-A-EXTRACTION-QUOTA, S-EBAR-04Q und S-EBAR-04A.
- Der bestehende öffentliche Listing-/Integrity-Vertrag bleibt unverändert.
- Private Locator und CRC-Werte bleiben innerhalb eines einzigen
  nicht persistierbaren In-Memory-Lifecycles.
- Cleanup ist Voraussetzung erfolgreicher Member-Evidence und keine spätere
  Best-Effort-Aktion.
- Wrapperunterstützung wird nicht aus dem direkten Extraction-Vertrag
  interpoliert.

## Primärquellen und bindende Entscheidungen

- [ADR-0038](ADR-0038-safe-archive-container-analysis.md)
- [ADR-0039](ADR-0039-safe-archive-runtime-and-secret-channel.md)
- [ADR-0043](ADR-0043-archive-machine-output-and-status-classification.md)
- [ADR-0047](ADR-0047-final-archive-7zip-format-lock.md)
- Docker `run` mit `--ulimit` und `RLIMIT_FSIZE`:
  https://docs.docker.com/reference/cli/docker/container/run/#set-ulimits-in-container---ulimit
