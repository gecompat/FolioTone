# ADR-0039: Sichere Archive-Runtime und weiterhin blockierter Secret-Kanal

- Status: Accepted
- Datum: 2026-08-20

## Kontext

ADR-0038 legt Format-Allowlist, 7-Zip-26.02-Toolmanifest, feste read-only
Command Shapes, Sicherheitsbudgets, Memberpfade, Secret-Grenze und
Evidence-Reuse fest. S-EBA-01 bis S-EBA-07 implementieren die zugehörigen
synthetischen beziehungsweise Fake-only Verträge. Eine reale Toolausführung
war in diesen Paketen ausdrücklich ausgeschlossen.

Die generische `ToolRuntime` ist für reale Archive ungeeignet. Sie persistiert
stdout und stderr unverändert als `ToolArtifact`, erzeugt Text-Previews,
begrenzt die Ausgabedateien nicht während der Prozessausführung und übernimmt
standardmäßig die Prozessumgebung des Hosts. Ein 7-Zip-Listing kann private
Membernamen und Containerkommentare mit Passwortmaterial ausgeben. Die
bestehende Runtime würde diese Daten deshalb vor einer Normalisierung in
Persistenz und Artefakte übernehmen.

7-Zip 26.02 dokumentiert für seine CLI weiterhin nur `-p{password}`. Ein
Passwort würde damit im Prozessargument erscheinen. Das offene 7-Zip-Issue
für einen separaten File-Descriptor-Kanal belegt keine verfügbare
Produktschnittstelle. Eine undokumentierte Übergabe über stdin, PTY oder
Environment Variables bleibt ausgeschlossen.

Die mechanischen Vorarbeiten erlauben damit zwei getrennte Entscheidungen:

1. unverschlüsselte Archive dürfen über eine spezialisierte, streaming-
   basierte und isolierte Runtime read-only gelistet, auf Integrität geprüft
   und nach erneuter Policy-Prüfung privat testextrahiert werden;
2. reale Passwortversuche bleiben gesperrt, bis ein weiterer nachweisbarer
   Secret-Helper-Vertrag akzeptiert ist.

## Entscheidung

FG-A-RUNTIME ist akzeptiert. FolioTone darf eine spezialisierte
`ArchiveProcessRunner`-Grenze für unverschlüsselte Archive implementieren.
Diese Grenze ist kein allgemeiner Ersatz und keine Erweiterung der
`ToolRuntime`. Sie verwendet ausschließlich die in ADR-0038 festgelegten
7-Zip-26.02-Command-Shapes und erzeugt nur normalisierte, secretfreie Archive-
DTOs und `ToolExecution`-Provenance.

Reale Passwortversuche sind durch dieses Gate nicht freigegeben. Solange kein
separates FG-A-SECRET einen konkreten Helper, eine unterstützte Formatmatrix
und einen technisch belegten Secret-Kanal akzeptiert, endet jede
Passwortanforderung vor dem Toolstart mit
`ArchivePasswordAttemptStatus.SECURE_CHANNEL_UNAVAILABLE`.

## Zulässige Runtime-Schritte

Die Schritte bleiben getrennt und werden in dieser Reihenfolge ausgeführt:

```text
Version Probe
    -> Listing Stream
    -> vollständige Member- und Budgetprüfung
    -> Integritätstest
    -> erneute Preconditions- und Budgetprüfung
    -> private vollständige Testextraktion
    -> Workspace-Revalidierung
    -> Streaming-Hashes und Member-Evidence
```

Ein späterer Schritt darf keinen Befund eines früheren Schritts still
ersetzen. Jeder Schritt besitzt eine eigene `ToolExecution`-ID. Ein
`ArchiveObservation` mit ausgeführtem Integritätstest enthält deshalb neben
`listing_execution_id` auch `integrity_execution_id`. Eine erfolgreiche
Extraktion bindet jedes reguläre Member an `extraction_execution_id`.

Die öffentliche Adaptergrenze akzeptiert weder eine freie Argumentliste noch
beliebige 7-Zip-Optionen. Sie nimmt nur intern validierte Source-
beziehungsweise Volumegruppen-Identität, feste Profile und einen bereits
geprüften privaten Workspacevertrag entgegen. `ToolCapability` erhält
getrennte read-only Capabilities für Archive Listing, Archive Integrity und
Archive Extraction; keine davon autorisiert Source-Media-Mutation.

## Execution-Snapshots und Status-Sum-Types

Listing, Integrity und Extraction verwenden drei getrennte immutable
Execution-Snapshots. Ein Snapshot enthält ausschließlich den fachlichen
Schrittstatus und eine optionale opaque `execution_id`; er enthält weder
Command Line, Pfad, Membernamen, Raw-Ausgabe noch Fehlerfreitext. Die drei
Execution-IDs bezeichnen verschiedene `ToolExecution`-Datensätze und dürfen
innerhalb eines Resultats nicht gleich sein.

```text
ArchiveListingExecution
    status: ArchiveListingStatus
    execution_id: opaque ID | NONE

ArchiveIntegrityExecution
    status: ArchiveIntegrityStatus
    execution_id: opaque ID | NONE

ArchiveExtractionExecution
    status: ArchiveExtractionStatus
    execution_id: opaque ID | NONE
```

Die bisherigen `ArchiveListingStatus`- und `ArchiveIntegrityStatus`-Literale
aus ADR-0038 bleiben unverändert. Für Extraction gelten exakt:

```text
ArchiveExtractionStatus
-----------------------
NOT_ATTEMPTED
EXTRACTED
LIMIT_EXCEEDED
TIMED_OUT
TOOL_UNAVAILABLE
TOOL_FAILED
POLICY_REJECTED
VALIDATION_FAILED
```

`NOT_ATTEMPTED` beziehungsweise `NOT_TESTED` verlangt `execution_id = NONE`.
Jeder andere Schrittstatus verlangt genau eine opaque `execution_id`. Eine
solche ID dokumentiert den auditierten Schrittversuch; sie behauptet nicht,
dass ein Betriebssystemprozess gestartet wurde. Preflight-Ergebnisse wie
`POLICY_REJECTED` oder `TOOL_UNAVAILABLE` bleiben dadurch nachvollziehbar,
ohne einen Prozessstart zu erfinden.

Die Reihenfolge ist fail-closed:

- ein Integrity-Snapshot ungleich `NOT_TESTED` verlangt Listingstatus
  `LISTED`;
- ein Extraction-Snapshot ungleich `NOT_ATTEMPTED` verlangt Listingstatus
  `LISTED`, Integritystatus `PASSED`, Encryptionstatus `NONE` und eine
  akzeptierte Extraction Policy;
- `EXTRACTED` verlangt für jedes reguläre Member vollständige Größen-, CRC-,
  Hash- und Extraction-Provenance mit genau der `execution_id` des
  Extraction-Snapshots;
- jeder andere Extraction-Status verbietet erfolgreiche Extraction-Felder an
  Members; teilweise Ergebnisse bilden keine erfolgreiche Evidence;
- `VALIDATION_FAILED` umfasst Abweichungen bei Workspace-, Member-, Größen-,
  CRC- oder Hash-Revalidierung;
- ein fehlgeschlagenes Cleanup wird als `TOOL_FAILED` behandelt und verhindert
  erfolgreiche Member-Evidence. Ein detaillierter interner Fehlercode darf
  nur aus einer festen secretfreien Allowlist stammen.

Cancellation erzeugt keinen terminalen Archive-Snapshot. Die zugehörige
`ToolExecution` endet `CANCELLED`; ein Wiederanlauf erzeugt neue
Execution-Snapshots. So müssen ADR-0038-Literale nicht um einen unklaren
teilweisen Archivezustand erweitert werden.

S-EBAR-01 ersetzt im Fake-Vertrag die einzelnen Felder `execution_id` und
`integrity_status` durch diese drei Snapshots. Die bisherigen Informationen
bleiben vollständig ableitbar, aber neue Konstruktoren und DTO-Ausgaben
verwenden ausschließlich die getrennten Snapshots. Eine temporäre
read-only-Kompatibilitätseigenschaft darf den bisherigen Listing-Identifier
liefern; neue Signaturen akzeptieren den alten Feldnamen nicht. Der
`archive-listing-reuse/v1`- und `archive-member-reuse/v1`-Schlüssel bleibt
unverändert.

## Streaming- und Redaktionsvertrag

`ArchiveProcessRunner` schreibt stdout und stderr nicht in `ToolArtifact`,
Preview, Log oder temporäre Raw-Ausgabedateien. stdout wird während der
Ausführung als begrenzter Bytestream unmittelbar an
`archive-7zip-slt-parser/v1` übergeben. Der Parser:

- erzwingt die in ADR-0038 festgelegte 8-MiB-Gesamtgrenze;
- dekodiert ausschließlich den festgelegten UTF-8-Vertrag;
- begrenzt Zeilenlänge, Feldzahl und Memberzahl;
- normalisiert nur allowlist-basierte Felder;
- leitet einen begrenzten Containerkommentar ausschließlich ephemer an den
  lokalen Secret-Candidate-Parser weiter;
- verwirft Rohbytes nach der Verarbeitung;
- gibt private Memberlocator nur an die interne Path- und Safety-Prüfung
  weiter.

stderr wird gleichzeitig bis zur 1-MiB-Grenze verarbeitet und ausschließlich
in feste technische Status- beziehungsweise Fehlerliterale klassifiziert.
Rohtext und unbekannte Fehlermeldungen werden nicht persistiert. Exceptions,
`repr`, CLI-Ausgabe und Telemetrie dürfen weder Raw-Ausgabe noch Membernamen,
Containerkommentare, Source-Pfade oder Secretmaterial enthalten.

Ein Überschreiten der stdout-/stderr-, Zeit-, Prozess-, Speicher- oder
Workspace-Grenze beendet den vollständigen Prozessbaum. Bereits geparste
Teilwerte bilden keine erfolgreiche Archive-Evidence.

## Prozess- und Filesystemisolation

Die tatsächliche Source und jeder `ScanRoot` werden niemals in die
Tool-Sandbox gemountet. Vor jedem Toolstart kopiert FolioTone genau die bereits
vollständig validierte Volumegruppe in ein neu erzeugtes, opaque benanntes und
privates Input-Staging-Verzeichnis unter dem konfigurierten FolioTone-Temp-
Root. Dabei bleiben nur die für die Volumeauflösung notwendigen Suffix- und
Gruppenformen erhalten; Source-Verzeichnis und Source-Basename werden nicht in
Containerargumente oder -Metadaten übernommen. Ein getrenntes, ebenfalls
opaque und privates Output-Verzeichnis beginnt leer.

Vor und nach der Kopie werden Source-Observation, Volumezuordnung, Größen und
vollständige SHA-256-Werte gegen den validierten Auftrag geprüft. Anschließend
werden Größe und vollständiger SHA-256-Wert jedes Staging-Objekts gegen die
Source-Evidence verifiziert. Jede Änderung, fehlende Volume, zusätzliche Datei
oder Hashabweichung endet vor dem Containerstart fail-closed. Das Input-
Staging wird ausschließlich read-only, das getrennte Output-Verzeichnis
ausschließlich read-write gemountet. Beide privaten Verzeichnisse liegen
außerhalb jedes `ScanRoot` und werden nach Evidence-Übernahme, Fehler,
Cancellation oder Timeout vollständig bereinigt.

Die erste Runtime muss mindestens folgende Grenzen technisch durchsetzen:

- alle Werte aus `archive-safety-policy/v1` einschließlich maximal eines
  Toolprozesses und höchstens zweier paralleler Archive Jobs;
- CPU-, RAM-, Laufzeit-, Prozess-, Datei- und Workspace-Byte-Limits;
- vollständige Prozessbaumbeendigung bei Cancellation oder Grenzverletzung;
- ein neu erzeugtes minimales Environment ohne Credentials, Hostpfade oder
  projektexterne Secrets;
- keine Shell, keine Wildcards, keine Listfiles und keine vom Aufrufer
  ergänzbaren Optionen;
- keine Ausführung eines extrahierten Members.

Der erste freigegebene Backendvertrag ist
`archive-linux-container-runner/v1` für die primäre Docker/Linux-Runtime. Er
startet ausschließlich ein lokal vorhandenes Image über seine unveränderliche
Digest-Referenz `repository@sha256:<digest>` mit `--pull=never`.

Der konkrete Imagevertrag ist noch nicht freigegeben. Das separate
`FG-A-IMAGE` muss vor S-EBAR-03 entscheiden, ob FolioTone ein projekt-eigenes,
reproduzierbares Image-Build-Rezept pflegt oder ein operator-provided Image
mit gleichwertiger Attestation akzeptiert. Das Gate fixiert Base- und
Result-Image-Digests, offizielle Quelle, veröffentlichte Checksumme und den
dokumentierten Status eines Signaturnachweises für das eingebettete
7zz-26.02-Artefakt, Lizenz und
Redistribution, SBOM und Build-Provenance, numerische non-root UID/GID,
Reproduzierbarkeits- und Update-Regel sowie private und öffentliche CI-Grenzen.
Bis `FG-A-IMAGE` akzeptiert ist, bleibt S-EBAR-03 blockiert und der Runtime-
Status `TOOL_UNAVAILABLE`.

Nach dem Gate übernimmt S-EBAR-03 die festgelegten Werte mechanisch in das
Toolmanifest und verifiziert Result-Image-Digest, 7zz-Version und Artefakt-
SHA-256 beim Start. Es darf keine Quelle, Lizenz, Build- oder
Redistributionsregel selbst auswählen.

Jeder Containerstart erzwingt mindestens:

- einen festen numerischen non-root User, read-only Root-Filesystem und eine
  feste 7zz-Entrypoint-/argv-Allowlist ohne Shell;
- `network=none`, keine Devices, keinen Docker-Socket, keine privilegierte
  Ausführung, `cap-drop=ALL` und `no-new-privileges`;
- das Docker-Default-Seccomp-Profil oder ein nachweislich strengeres Profil,
  niemals `unconfined`;
- `--pids-limit=16`, `--memory=1g`, `--memory-swap=1g`, `--cpus=1.0` und
  7zz Single-Threading sowie die ADR-0038-Laufzeit-, Ausgabe- und
  Parallelitätsgrenzen;
- ausschließlich das read-only Input-Staging und den getrennten read-write
  Output-Workspace; keine weiteren Bind Mounts, Volumes oder Tmpfs-Mounts;
- ein im Image und im Startprofil festes minimales Environment ohne vom Host
  geerbte Variablen.

Bei Timeout, Cancellation oder Grenzverletzung werden Container und
vollständiger Prozessbaum beendet, der Container zwangsweise entfernt und
seine Abwesenheit verifiziert, bevor Staging und Output bereinigt werden. Ein
teilweise beendeter oder noch vorhandener Container ist kein terminal
erfolgreicher Lauf.

Native Windows-Ausführung bleibt `TOOL_UNAVAILABLE`, bis das separate
`FG-A-WINDOWS-SANDBOX` die tatsächliche Netzwerk- und Filesystemisolation
belegt. Job Objects und explizite Handle-Allowlisten können Prozesslebenszeit
und Handlevererbung begrenzen, isolieren aber weder Netzwerk noch Filesystem
und sind allein keine zulässige Sandbox.

## Extraktionsvertrag

Extraktion ist nur für ein unverschlüsseltes, vollständig gelistetes Archiv
mit erfolgreichem Integritätstest und akzeptierter Safety Policy zulässig.
Unbekannte deklarierte Größen, fehlende Volumes, unbekannte Methoden,
Verschlüsselung und jeder Limit- oder Policy-Befund blockieren den Schritt.

Vor dem Toolstart wird die vollständige Memberliste gegen Traversal,
absolute/Device-/ADS-Pfade, normalisierte Kollisionen, Links, Reparse Points,
Devices, Sparse-Ausgaben, besondere Metadaten und Parent-/Child-Konflikte
geprüft. Nach dem Toolende wird der Workspace ohne Verlassen des privaten
Roots erneut auf dieselben Eigenschaften geprüft. Erst danach werden reguläre
Dateien gestreamt gehasht.

Eine erfolgreiche Ableitung verlangt:

```text
listed regular members == extracted regular members
declared sizes == observed sizes
CRC-/Integritätsvertrag erfüllt
Workspacebudget eingehalten
keine zusätzlichen oder fehlenden Ziele
```

Die gesamte Ableitung schlägt fehl, wenn eine Bedingung nicht erfüllt ist.
Teilweise extrahierte Member werden weder wiederverwendet noch als
erfolgreiche `ArchiveMemberObservation` persistiert. Der Workspace wird nach
dem notwendigen secretfreien Evidence-Import vollständig entfernt.

## Weiterhin blockierter Secret-Kanal

FG-A-SECRET ist ein separates Frontier-Gate. Es darf erst akzeptiert werden,
wenn ein konkreter isolierter Helper nachweist, dass Secretmaterial:

- entweder innerhalb des Helperprozesses aus einem `SecretHandle` aufgelöst
  oder über genau einen einmaligen anonymen Pipe-/Handle-Kanal empfangen wird;
- nicht in argv, Environment Variables, stdin, PTY, stdout, stderr,
  Persistenz, Artefakte, Dumps, Exceptions, Logs oder Telemetrie gelangt;
- nur über explizit vererbte Handles erreichbar ist;
- nach dem Versuch bestmöglich aus veränderbarem Speicher entfernt wird;
- höchstens für die in einem neuen adversarial Fixturevertrag belegten
  ZIP-/RAR-/7z-Formate freigegeben wird.

Der Helper muss Prozessisolation, Tool-/Library-Version, Packaging,
Fehlermatrix und Speichergrenzen separat dokumentieren. Der vorhandene
7-Zip-CLI-Adapter darf auch nach FG-A-RUNTIME niemals `-p` verwenden. Eine
fehlende sichere gemeinsame Lösung darf zu einer begründeten Nichtfreigabe
einzelner oder aller verschlüsselten Formate führen.

## Evidence, Reuse und Persistenzgrenze

`archive-listing-reuse/v1` behält den durch S-EBA-07 implementierten
konservativen Schlüssel unverändert bei:

```text
archive full SHA-256
volume_group_fingerprint
tool provider und tool version
adapter- und parser version
listing_profile
extraction_profile
safety_profile
secret_version oder NONE
```

`extraction_profile` invalidiert damit auch ein Listing, obwohl es erst den
späteren Schritt beschreibt. Diese konservative Überinvalidierung vermeidet
eine stille Umdeutung des bestehenden v1-Profils. Eine spätere Trennung
benötigt `archive-listing-reuse/v2`. Für die durch dieses Gate zulässige
unverschlüsselte Runtime ist `secret_version = NONE`.

`archive-member-reuse/v1` verwendet denselben vollständigen materiellen
Schlüssel. Eine erfolgreiche Member-Ableitung verlangt zusätzlich die
vollständige Extraction-Provenance, Größen-/CRC-Konsistenz und Member-Hashes.
Ein neueres terminales Fehler-, Timeout- oder Limitresultat ersetzt keine
ältere erfolgreiche Ableitung. Die Persistenz bleibt insert-only und speichert
keine Raw-Ausgaben, öffentlichen Memberpfade oder Secretwerte.

Die konkrete additive Migration folgt erst nach den Runtime- und DTO-
Folgepaketen. Dieses Gate benennt keine Tabellen und führt keine Migration
aus.

## Fixture- und Verifikationsgrenze

Repositorytests verwenden ausschließlich kleine synthetisch erzeugte Archive
ohne reale Sammlungspfade, Titel, Personen, Passwörter oder kopierte
Drittanbieterarchive. Toolabhängige private Extraction Fixtures liegen unter
den vorgesehenen Pfaden in `C:\rep\tmp\FolioTone` beziehungsweise
`C:\rep\artifacts\FolioTone` und gelangen nicht in Git oder öffentliche CI-
Artefakte. Ein privater Fixturelauf ersetzt keine deterministischen Unit- und
Integrationstests.

Die Gate-Welle selbst führt kein Archivtool aus. Folgepakete benötigen
gezielte Parser-, Prozess-, Timeout-, Prozessbaum-, Budget-, Traversal-,
Kollisions-, Integritäts-, Cleanup- und Privacy-Tests. Pro konsistenter Welle
läuft genau ein vollständiger PR-CI-Gate.

## Folgepakete und Modellrouting

| Paket | Inhalt | Modell und Thinking |
|---|---|---|
| S-EBAR-01 | Characterization-Tests, getrennte Archive-Execution-DTOs und vollständige Listing-/Integrity-/Extraction-Provenance | 5.3 Codex Spark `high`; Fallback 5.4 Mini, danach 5.6 Terra |
| S-EBAR-02 | Reiner bounded `archive-7zip-slt-parser/v1` mit Chunk-, Encoding-, Limit- und Redaktionsfällen | 5.3 Codex Spark `high`; Fallback 5.4 Mini, danach 5.6 Terra |
| FG-A-IMAGE | Projekt-eigenes Build-Rezept oder operator-provided Image, Digests, offizielle 7zz-Artefaktidentität, Lizenz/Redistribution, SBOM/Provenance, numerische UID/GID, Reproduzierbarkeit, Updates und CI-Grenzen entscheiden | 5.6 Sol `high`; kein Spark-Fallback |
| S-EBAR-03 | Die durch FG-A-IMAGE exakt festgelegten Image-/7zz-Identitäten, Packagingdateien und UID/GID mechanisch umsetzen und verifizieren; Toolmanifest, Startprüfung und feste Command Builder ohne freie Argumente | 5.3 Codex Spark `high`; Fallback 5.4 Mini, danach 5.6 Terra; ohne akzeptiertes FG-A-IMAGE blockiert |
| EBAR-04 | Docker-Backend `archive-linux-container-runner/v1` mit opaque Input-Staging, getrenntem Output, festen Mount-/Netzwerk-/Capability-/Seccomp-/Ressourcengrenzen und vollständigem Kill/Remove | 5.6 Sol `high`; Fallback 5.5 nur, wenn keine Secret- oder neue Sandboxentscheidung offen ist |
| EBAR-05 | Reales unverschlüsseltes Listing und Integrity über den akzeptierten Runner | 5.6 Terra `medium`, `high` nur bei schichtübergreifender Diagnose; Fallback 5.4 |
| EBAR-06 | Private Extraction-Sandbox, Live-Budgets, Workspace-Revalidierung und Member-Hashing | 5.6 Sol `high`; keine Delegation an Spark oder Terra |
| FG-A-SECRET | Separater Helper-, Kanal-, Format- und adversarial Sicherheitsvertrag | 5.6 Sol `xhigh`; kein niedriger eingestuftes Fallback |
| FG-A-PERSISTENCE | Separates Gate für immutable Archive-/Member-Lineage, Reuse, Tabellen, Indizes, Migration und Lease/Fencing | 5.6 Sol `high`; kein Spark-Fallback |
| S-EBAR-07 | Durch FG-A-PERSISTENCE exakt spezifizierte additive Archive-Persistenz und insert-only Store | 5.3 Codex Spark `high`; Fallback 5.4 Mini, danach 5.6 Terra |
| EBAR-08 | Restartbare Collection-Orchestrierung, Lease/Fencing, Heartbeat und pfadfreie Reports | 5.6 Sol `high`; keine Delegation an Spark |
| EBAR-09 | Abschlussabgleich von EA2 bis EA6 und Freigabe des separaten EB-A3-Gates | 5.6 Luna `medium` für Status/CI; semantische Integration mit 5.6 Terra `medium` |

Die Pakete laufen strikt in Reihenfolge. Nach S-EBAR-02 wird zuerst FG-A-IMAGE
entschieden. Danach folgen S-EBAR-03 und EBAR-04 bis EBAR-06; anschließend legt
FG-A-PERSISTENCE den exakten Schema-, Reuse- und Writer-Vertrag fest. Erst
danach beginnt S-EBAR-07. FG-A-SECRET darf unabhängig später erfolgen und
blockiert die unverschlüsselte Strecke nicht. Archive-aware Matching, Keep
Preference und Planung bleiben ein separates EB-A3-Gate.

## Nicht autorisiert

Dieses Gate autorisiert nicht:

- Source-Media-Mutation oder Extraction neben das Source-Archiv;
- Passwortübergabe an 7-Zip oder einen anderen Prozess;
- Online-Passwortprovider, Newzcrabber oder Web-/Usenet-Recherche;
- Persistenz von Raw-Ausgaben, Memberpfaden oder Secretmaterial;
- automatische Nested-Archive-Verarbeitung;
- Archive-aware Matching oder eine Lösch-/Keep-Entscheidung;
- W10, Quarantäne, Purge oder Empty-Directory-Cleanup.

## Konsequenzen

- Die unverschlüsselte EB-A2-Runtime besitzt einen implementierbaren,
  containergebundenen Sicherheitsvertrag für die primäre Docker/Linux-
  Runtime.
- Die generische `ToolRuntime` behält ihren bisherigen Vertrag und wird nicht
  für private Archive-Raw-Ausgabe wiederverwendet.
- Passwortverarbeitung bleibt sichtbar, aber fail-closed blockiert.
- Ein erfolgreicher Listing-, Integrity- oder Extraction-Schritt bleibt
  technische Evidence und macht einen Container nicht entbehrlich.
- Persistenz, Collection-Orchestrierung und EB-A3 folgen als getrennte Wellen.

## Primärquellen

- 7-Zip 26.02 Download und Plattformpakete:
  https://www.7-zip.org/download.html
- 7-Zip Formatabdeckung und Lizenz:
  https://www.7-zip.org/
- 7-Zip Command-Line-Hilfeindex:
  https://github.com/ip7z/7zip/blob/main/DOC/7zip.hhp
- Offene 7-Zip-Anforderung für einen Passwortkanal über separaten File
  Descriptor:
  https://github.com/ip7z/7zip/issues/184
- Docker, `docker container run` einschließlich read-only Root-Filesystem,
  Mounts, Capability-, Security- und Ressourcenoptionen:
  https://docs.docker.com/reference/cli/docker/container/run/
- Docker, read-only Bind Mounts:
  https://docs.docker.com/engine/storage/bind-mounts/
- Docker, `none` Network Driver:
  https://docs.docker.com/engine/network/drivers/none/
- Docker, CPU- und Speichergrenzen:
  https://docs.docker.com/engine/containers/resource_constraints/
- Docker, Default-Seccomp-Profil:
  https://docs.docker.com/engine/security/seccomp/
- Docker, pinning von Base Images und reproduzierbare Build-Eingaben:
  https://docs.docker.com/build/building/best-practices/
- Docker, SBOM-Attestations:
  https://docs.docker.com/build/metadata/attestations/sbom/
- Docker, Provenance-Attestations:
  https://docs.docker.com/build/metadata/attestations/slsa-provenance/
- 7-Zip Lizenz:
  https://www.7-zip.org/license.txt
