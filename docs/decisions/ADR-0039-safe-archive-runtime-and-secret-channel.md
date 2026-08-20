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
  `LISTED`, Integritystatus `PASSED` und Encryptionstatus `NONE`;
- `POLICY_REJECTED` verlangt den Policy-Status `POLICY_REJECTED`;
  `LIMIT_EXCEEDED` darf entweder einen bereits im Preflight festgestellten
  Policy-Status `LIMIT_EXCEEDED` oder eine erst während der Ausführung
  überschrittene Grenze bei zuvor akzeptierter Policy abbilden; alle anderen
  ausgeführten Extraction-Statuswerte verlangen eine akzeptierte Policy;
- `EXTRACTED` verlangt für jedes reguläre Member vollständige Größen-, CRC-,
  Hash- und Extraction-Provenance mit genau der `execution_id` des
  Extraction-Snapshots;
- Nicht-Datei-Member dürfen niemals Extraction-ID, beobachtete Dateigröße oder
  Member-Hash tragen;
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
- gibt einen begrenzten Containerkommentar ausschließlich als redigiertes
  ephemeres Objekt an den aufrufenden In-Memory-Workflow zurück; eine spätere
  separat getestete Brücke darf ihn an den lokalen Secret-Candidate-Parser
  übergeben;
- verwirft Rohbytes nach der Verarbeitung;
- gibt private Memberlocator nur an die interne Path- und Safety-Prüfung
  weiter.

stderr wird gleichzeitig bis zur 1-MiB-Grenze verarbeitet und ausschließlich
in feste technische Status- beziehungsweise Fehlerliterale klassifiziert.
Rohtext und unbekannte Fehlermeldungen werden nicht persistiert. Exceptions,
`repr`, CLI-Ausgabe und Telemetrie dürfen weder Raw-Ausgabe noch Membernamen,
Containerkommentare, Source-Pfade oder Secretmaterial enthalten.

### Exakter `archive-7zip-slt-parser/v1`-Vertrag

S-EBAR-02 implementiert ausschließlich einen inkrementellen Parser für den
stdout-Bytestream des fest gepinnten `7zzs` 26.02. Der Parser startet kein Tool,
öffnet keine Datei und besitzt keine Persistenz-, Logging-, Preview- oder
Artefaktschnittstelle. Seine öffentlichen Ergebnisse sind ein Sum-Type mit
exakt `PARSED`, `LIMIT_EXCEEDED`, `ENCODING_REJECTED` und
`GRAMMAR_REJECTED`. Nur `PARSED` darf Header, Members oder einen ephemeren
Kommentar tragen; jeder andere Status verwirft alle bis dahin gelesenen
Teilwerte.

Der Streamvertrag ist exakt:

```text
max_stdout_bytes             = 8_388_608
max_chunk_bytes              = 262_144
max_chunks                   = 65_536
max_line_utf8_bytes          = 8_192
max_line_codepoints          = 4_096
max_fields_per_record        = 32
max_member_records           = 10_000
max_member_path_utf8_bytes   = 4_096
max_member_path_codepoints   = 1_024
max_comment_utf8_bytes       = 4_096
max_comment_codepoints       = 4_086
```

Chunks müssen `bytes` sein und dürfen die Chunkgrenze nicht überschreiten;
auch leere Chunks zählen gegen die Chunkgrenze. Dekodiert wird mit einem
zustandsbehafteten, strikt fehlschlagenden UTF-8-Decoder. Genau ein UTF-8-BOM
ist ausschließlich am Streamanfang zulässig. `LF` und `CRLF` sind zulässige
Zeilenenden; einzelnes `CR`, NUL und andere C0-/C1-Steuerzeichen außer dem
jeweiligen Zeilenende werden abgewiesen. Ein Stream muss mit einem
Zeilenende abschließen. Die Bytegrenze wird vor dem Dekodieren, die
Codepointgrenze vor jeder Feldübernahme geprüft.

Die Kommentar-Codepointgrenze berücksichtigt den zehn Zeichen langen festen
Feldpräfix `Comment = `; ein maximaler Kommentar bleibt dadurch innerhalb der
allgemeinen Zeilengrenze von 4.096 Codepoints.

Die v1-Grammatik besteht aus einem Archive-Header, der exakten Trennzeile
`----------` und null bis 10.000 Member-Records. Records werden durch genau
eine Leerzeile getrennt. Jede Feldzeile hat exakt die Form
`ASCII_FIELD_NAME = VALUE`; führende oder nachlaufende Leerzeichen,
Fortsetzungszeilen, doppelte Felder, Material vor dem Header, eine zweite
Trennzeile und Material nach dem letzten abgeschlossenen Record sind
ungültig. Feldreihenfolge ist nicht materiell; Member-Reihenfolge bleibt die
vom Tool gelieferte Reihenfolge und erzeugt die spätere kanonische Ordinalzahl.

Der Archive-Header akzeptiert ausschließlich:

```text
Path
Type
Physical Size
Headers Size
Method
Solid
Blocks
Volumes
Total Physical Size
Tail Size
Embedded Stub Size
Characteristics
Comment
```

Ein Member-Record akzeptiert ausschließlich:

```text
Path
Folder
Size
Packed Size
Modified
Created
Accessed
Attributes
Encrypted
CRC
Method
Block
Characteristics
Host OS
Version
Volume Index
Offset
Symbolic Link
Hard Link
User
Group
Alternate Stream
Anti
```

`Path` ist in beiden Recordarten Pflicht. Im Header sind zusätzlich `Type`
und `Physical Size`, im Member zusätzlich `Folder`, `Size`, `Packed Size` und
`Encrypted` Pflicht. `Folder`, `Encrypted`, `Solid`, `Alternate Stream` und
`Anti` akzeptieren ausschließlich `+` oder `-`. Größen, Counts, Block- und
Offsetwerte sind kanonische nichtnegative ASCII-Dezimalzahlen ohne Vorzeichen
oder führende Null außer dem Einzelwert `0`; sie dürfen `2^63 - 1` nicht
überschreiten. `CRC` ist, wenn vorhanden, exakt acht uppercase
Hexadezimalzeichen. Unbekannte Felder, unbekannte boolesche Werte oder
abweichende numerische Formen ergeben `GRAMMAR_REJECTED`; sie werden niemals
ignoriert. Die spätere EBAR-05-Fixturematrix muss für jedes freigegebene
Archivformat belegen, dass `7zzs` 26.02 innerhalb dieser v1-Allowlist bleibt.
Eine notwendige Erweiterung verlangt ein neues Parserprofil oder eine
explizite ADR-Änderung und darf nicht still in v1 aufgenommen werden.

Der Parser übernimmt nur die für Safety und technische Evidence nötigen
Werte. Archive- und Member-`Path` bleiben private, `repr=False` markierte
Locator und durchlaufen danach unverändert die vorhandene Path-/Safety-
Prüfung; sie erscheinen nie in öffentlichen DTOs oder Fehlermeldungen.
`Symbolic Link`, `Hard Link`, `User`, `Group` und `Characteristics` werden
ausschließlich durch ihre Feldpräsenz auf je ein boolesches Unsafe-Flag
projiziert; ihr potentiell privater Wert wird unmittelbar verworfen.
`Alternate Stream` und `Anti` werden aus ihrem festen `+`-/`-`-Wert auf
boolesche Unsafe-Flags projiziert. Kein Wert dieser Felder darf in ein DTO,
einen Fingerprint, `repr`/`str` oder eine Fehlermeldung gelangen. Jedes gesetzte
Unsafe-Flag wird von der nachfolgenden Safety-Prüfung fail-closed bewertet,
nicht als vertrauenswürdige Metadaten. Leere Werte der präsenzbasierten Felder
sind weiterhin Feldpräsenz und damit unsafe; ein doppeltes Feld bleibt ein
Grammatikfehler.

`Comment` ist eine Sondergrenze. Höchstens der einzelne Header-Kommentar wird
bis zu den oben festgelegten Grenzen in einem
`EphemeralArchiveComment`-Objekt mit vollständig redigiertem `repr`/`str`
zurückgegeben. Memberkommentare machen v1 `GRAMMAR_REJECTED`; sie werden nicht
als Secretquelle interpretiert. Das ephemere Objekt bietet keine
Serialisierung und darf nur innerhalb desselben In-Memory-Workflows an eine
spätere, separat getestete Comment-Candidate-Brücke übergeben werden. S-EBAR-02
erzeugt noch keinen `ArchiveSecretCandidate`: Die bestehende Sidecar-API ist
absichtlich auf `DIRECTORY_SIDECAR` beschränkt und darf nicht falsch als
`ARCHIVE_COMMENT` verwendet werden. Bis eine Folgeänderung diese Brücke exakt
definiert, wird der Kommentar nach dem Parseraufruf verworfen und es findet
kein Passwortversuch statt.

Der Parser kopiert Raw-Zeilen oder unbekannte Feldwerte niemals in Status,
Exception oder Textdarstellung. Seine Fehler geben ausschließlich Profil und
festen Status zurück. Unit-Tests müssen Chunk-Splits an jedem UTF-8- und
CRLF-Grenzpunkt, zu viele leere Chunks, BOM-/Encodingfehler, jede einzelne
Boundkante, unbekannte/doppelte Felder, Steuerzeichen, unvollständige Records,
Kommentarredaktion sowie pathfreie `repr`/`str`-Ausgaben abdecken.

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
ausschließlich read-write gemountet. Vor der Containererzeugung löst der
Backend-Preflight beide Roots und jeden Parent no-follow innerhalb des
konfigurierten FolioTone-Temp-Roots auf. Symlinks, Hardlinks, Junctions,
Reparse Points, Devices und andere nicht reguläre Einträge sind in Roots,
Parents und Staging-Membern verboten. Das container-sichtbare Staging gehört
numerisch `65532:65532`; Verzeichnisse haben Modus `0500`, reguläre Dateien
`0400`. Der neu erzeugte leere Output-Root gehört numerisch `65532:65532` und
hat Modus `0700`. Zusätzliche ACL-Rechte für andere Principals sind verboten.
Der Preflight muss Ownership, Modi, read-only/read-write-Mountflags und
no-follow-Auflösung sowohl vor dem Start als auch nach Erzeugung der Bind-
Mount-Konfiguration belegen. Kann eine Host-/Docker-Bind-Projektion diese
Eigenschaften nicht beweisen, endet der Auftrag vor Toolstart fail-closed mit
`TOOL_UNAVAILABLE`. Nach dem Lauf werden Output und Staging erneut no-follow
auf Links und Reparse Points geprüft. Beide privaten Verzeichnisse liegen
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

FG-A-IMAGE ist durch
[ADR-0040](ADR-0040-reproducible-archive-runtime-image.md) akzeptiert. Das
projekt-eigene `linux/amd64`-Image verwendet `FROM scratch`, das unveränderte
offizielle statische `7zzs`-26.02-Tar-Member mit festem Upstream-SHA-256,
vollständige Lizenzhinweise und den numerischen User `65532:65532`. Der
Upstream veröffentlicht keinen unabhängigen Signaturnachweis; dieser Umstand
bleibt als `UNSIGNED_UPSTREAM_RELEASE` sichtbar.

Der noch nicht gebaute Result-Digest wird nicht erfunden. S-EBAR-03 baut das
reine Offline-Rezept zweimal, verlangt identische `linux/amd64`-Manifest-
Plattform-Manifest-Digests und übernimmt erst den beobachteten Wert in
`archive-image-lock/v1`. Ein geschützter Post-Merge-Build muss denselben Digest
ohne Inline-Attestations nach GHCR publizieren und SBOM sowie das in ADR-0040
definierte SLSA-v1-Custom-Predicate danach an diesen Digest anhängen. Das
Package muss durch geschützten Owner-Setup öffentlich und mit
`gecompat/FolioTone` source-associated sein; ein Abruf der Digestreferenz aus
einem vollständig anonymen Prozess muss denselben Digest liefern. Dieser
Prozess hat keine Benutzer- oder Registry-Credentials, darf aber ausschließlich
den in ADR-0040 festgelegten fail-closed Registry-v2-Bearer-Flow verwenden.
Bis Lock, öffentliche Publikation, Source-Association, anonyme
Digestverifikation und Attestations vollständig und konsistent sind, bleibt
der Runtime-Status `TOOL_UNAVAILABLE`. S-EBAR-03 darf keine Quelle, Lizenz,
Build-, Plattform- oder Redistributionsregel selbst auswählen.

Jeder Containerstart erzwingt mindestens:

- einen festen numerischen non-root User, read-only Root-Filesystem und eine
  feste `7zzs`-Entrypoint-/argv-Allowlist ohne Shell;
- `network=none`, keine Devices, keinen Docker-Socket, keine privilegierte
  Ausführung, `cap-drop=ALL` und `no-new-privileges`;
- das Docker-Default-Seccomp-Profil oder ein nachweislich strengeres Profil,
  niemals `unconfined`;
- `--pids-limit=16`, `--memory=1g`, `--memory-swap=1g`, `--cpus=1.0` und
  `7zzs` Single-Threading sowie die ADR-0038-Laufzeit-, Ausgabe- und
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
| S-EBAR-02 | Reiner bounded `archive-7zip-slt-parser/v1` mit der exakten v1-Feld-/Record-Allowlist, Chunk-, Encoding-, Limit- und Redaktionsfällen sowie ausschließlich ephemerem Header-Kommentar ohne Sidecar-Umetikettierung | 5.3 Codex Spark `high`; Fallback 5.4 Mini, danach 5.6 Terra |
| FG-A-IMAGE | Durch ADR-0040 akzeptiert: projekt-eigenes `scratch`-Rezept, feste Upstream-/Lizenzidentitäten, gepinntes Buildx-/BuildKit-Profil, zweistufiger Plattform-Manifest-Digest-Lock, nachträgliche SBOM/Provenance, UID/GID, öffentliche/source-associated GHCR-Freigabe, Updates und CI-Grenzen | 5.6 Sol `high`; kein Spark-Fallback |
| S-EBAR-03 | Die durch ADR-0040 exakt festgelegten Image-/`7zzs`-/Builderidentitäten und Packagingdateien mechanisch umsetzen, zweimal als einzelnes OCI-Layout ohne Inline-Attestations reproduzierbar bauen, Plattform-Manifest-Digest locken und danach Toolmanifest, Startprüfung sowie feste Command Builder ohne freie Argumente liefern; Publish erst geschützt, öffentlich/source-associated und anonym per Digest verifiziert | 5.3 Codex Spark `high`; Fallback 5.4 Mini, danach 5.6 Terra; bei Builder-, Digest-, ELF-, Lizenz-, Public-/Source-Association-, anonymer Verifikations- oder Attestationsabweichung blockiert |
| EBAR-04 | Docker-Backend `archive-linux-container-runner/v1` mit opaque Input-Staging `65532:65532` (`0500`/`0400`), leerem Output `65532:65532`/`0700`, no-follow Link-/Junction-/Reparse-Preflight, festen Mount-/Netzwerk-/Capability-/Seccomp-/Ressourcengrenzen und vollständigem Kill/Remove | 5.6 Sol `high`; Fallback 5.5 nur, wenn keine Secret- oder neue Sandboxentscheidung offen ist |
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
