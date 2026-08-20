# ADR-0038: Sichere read-only Archiv- und Containeranalyse

- Status: Accepted
- Datum: 2026-08-20

## Kontext

Die Archive-Strecke muss ZIP-, RAR-, 7z- und TAR-Familien technisch
inventarisieren können, ohne einen Container mit einer Dublette
gleichzusetzen. EPUB, CBZ und CBR sind Publikationscontainer. Ein generisches
Archiv kann mehrere Werke, Sidecars, Volumes, Backups oder bisher einzigartige
Dateien enthalten. Weder gleiche Memberbytes noch eine erfolgreiche
Extraktion machen den Source-Container deshalb entbehrlich.

Archivparser verarbeiten adversarial Input. Neben Traversal und Linktypen sind
unbegrenzte Mitgliederzahlen, deklarierte Größen, Kompressionsverhältnisse,
verschachtelte Archive, Laufzeiten und Ausgaben sicherheitsrelevant.
Verschlüsselte Archive ergänzen eine zweite Grenze: Geheimes Material darf
weder in Prozessargumenten noch in Environment Variables, Persistenz, Logs,
Fehlern oder Artefakten erscheinen.

Die aktuelle `ToolRuntime` startet lokale Prozesse mit `stdin=DEVNULL` und
besitzt keinen Secret-Kanal. 7-Zip 26.02 dokumentiert für seine CLI nur
`-p{password}`. Das würde das Passwort im Prozessargument offenlegen. `bsdtar`
dokumentiert `--passphrase passphrase` ausdrücklich als unsicher; libarchive
bietet zwar einen C-Passphrase-Callback, unterstützt verschlüsselte 7z- und
RAR-Payloads aber nicht als vollständige gemeinsame Baseline. Diese Lücke wird
nicht durch eine undokumentierte stdin-, PTY- oder Environment-Lösung
überbrückt.

## Entscheidung

FolioTone führt Archive bis zu einer späteren W10-Entscheidung ausschließlich
als read-only Container-Evidence. Normale Scans extrahieren nichts. Listing,
Integritätstest und eine spätere Extraktion sind getrennte, explizite Schritte.
Jeder Schritt prüft seine eigenen Preconditions und Budgets erneut.

Für die erste reale unverschlüsselte Runtime wird **7-Zip 26.02** als optionaler
lokaler `ToolProvider` gewählt. Die Wahl gilt nur für die unten festgelegten
read-only Command Shapes und die freigegebene Formatmatrix. FolioTone bündelt
7-Zip nicht; Packaging und Redistribution benötigen eine eigene aktuelle
Lizenzprüfung. Andere 7-Zip-Versionen werden nicht still als kompatibel
behandelt, sondern benötigen einen erneuten Fixture- und Parservertrag.

libarchive 3.8.9 bleibt ein geprüfter, aber nicht gewählter Baseline-Kandidat.
`bsdtar` wird in v1 nicht parallel als Fallback ausgeführt. Seine breitere
Library-API rechtfertigt keine zweite Ergebnissemantik, und sein CLI-
Passwortparameter erfüllt die Secret-Grenze nicht.

## Containerklassen und Identitätsgrenze

```text
ArchiveContainerClass
---------------------
PUBLICATION_CONTAINER
GENERIC_ARCHIVE
UNSUPPORTED_CONTAINER
UNKNOWN_CONTAINER

ArchiveFormatKind
-----------------
EPUB
CBZ
CBR
ZIP
RAR4
RAR5
SEVEN_Z
TAR
TAR_GZIP
TAR_BZIP2
TAR_XZ
TAR_ZSTD
UNKNOWN

ArchiveRecognitionStatus
------------------------
MATCHED
SIGNATURE_SUFFIX_MISMATCH
OUTER_COMPRESSION_ONLY
UNSUPPORTED_FORMAT
UNKNOWN_SIGNATURE
```

Die Klasse ist technische Evidence. Sie ist weder File-Identity noch eine
`Relation`, Keep Preference oder Löschentscheidung.

- `EPUB` ist ein ZIP-basierter `PUBLICATION_CONTAINER`. Die ZIP-Signatur allein
  genügt nicht; die EPUB-Strukturprüfung bleibt ein eigener Vertrag.
- `CBZ` ist ein ZIP-basierter `PUBLICATION_CONTAINER`-Kandidat. Suffix und
  ZIP-Signatur müssen zusammenpassen; eine spätere Comic-Strukturprüfung kann
  die fachliche Rolle präzisieren.
- `CBR` ist ein RAR-basierter `PUBLICATION_CONTAINER`-Kandidat unter derselben
  Regel.
- ZIP, RAR, 7z und TAR-Unterformen sind `GENERIC_ARCHIVE`, sofern sie nicht
  durch den Publikationscontainervertrag beansprucht werden.
- Ein Suffix-/Signaturwiderspruch wird erhalten und nie durch Umbenennen oder
  stilles Uminterpretieren korrigiert.

Ein `ArchiveMemberObservation` ist kein `FileRecord`, keine
`FileObservation` und keine Behauptung, dass das Member physisch neben dem
Archiv existiert. Gleiches Member- und File-SHA-256 ist später höchstens
Evidence für eine File-/Member-Beziehung. Der Container bleibt ein eigenes
Source-Objekt.

## Format- und Signatur-Allowlist

`archive-signature-observer/v1` liest höchstens 512 Byte am Anfang sowie bei
ZIP und TAR die für den Strukturtest ausdrücklich benötigten begrenzten
Bereiche. Es führt keine Dekompression aus.

| Familie | Freigegebene Suffixe | Signatur-/Strukturvertrag | v1-Status |
|---|---|---|---|
| ZIP | `.zip`, `.cbz` | `PK\x03\x04`, `PK\x05\x06` oder `PK\x07\x08`; CBZ bleibt Publication Candidate | unterstützt |
| EPUB | `.epub` | ZIP-Signatur plus eigener EPUB-Strukturvertrag | Publication Container |
| RAR 4 | `.rar`, `.cbr`, `.partNN.rar`, alte `.rar`+`.rNN`-Sets | `52 61 72 21 1A 07 00` | unterstützt, read-only |
| RAR 5 | dieselben RAR-Suffixformen | `52 61 72 21 1A 07 01 00` | unterstützt, read-only |
| 7z | `.7z`, `.7z.NNN` | `37 7A BC AF 27 1C` | unterstützt |
| TAR | `.tar` | gültiger TAR-Header einschließlich Checksumme; `ustar` an Offset 257 ist starke, aber nicht alleinige Evidence | unterstützt |
| gzip-TAR | `.tar.gz`, `.tgz` | gzip `1F 8B`; erst ein begrenztes Tool-Listing bestätigt den inneren TAR | unterstützt |
| bzip2-TAR | `.tar.bz2`, `.tbz2` | `42 5A 68`; erst Listing bestätigt TAR | unterstützt |
| xz-TAR | `.tar.xz`, `.txz` | `FD 37 7A 58 5A 00`; erst Listing bestätigt TAR | unterstützt |
| zstd-TAR | `.tar.zst`, `.tzst` | zstd `28 B5 2F FD`; erst Listing bestätigt TAR | unterstützt |
| Split ZIP | `.zip` mit `.zNN` | ZIP-Signatur/Volumegruppe | nur inventarisieren; Runtime v1 `UNSUPPORTED_FORMAT` |

Selbstextrahierende Executables, ARJ, CAB, ISO, WIM, disk images und alle
anderen von 7-Zip technisch lesbaren Formate sind nicht freigegeben. Ein Tool
darf die FolioTone-Allowlist nicht durch automatische Formatbreite erweitern.
Ein einzelner gzip-, bzip2-, xz- oder zstd-Stream ohne bestätigten inneren TAR
ist kein freigegebenes Generic Archive dieser E-Book-Welle.

RAR- und 7z-Volumegruppen werden nur als vollständig beobachtete, kanonisch
sortierte Gruppe gelistet. Fehlende, doppelte oder uneindeutige Volumes ergeben
`MISSING_VOLUME` beziehungsweise `POLICY_REJECTED`; FolioTone versucht keine
Reparatur. Alte RAR- und neue `partNN.rar`-Benennung werden nicht miteinander
vermischt.

Die v1-Gruppierung ist absichtlich enger als die Toolerkennung und verwendet
folgende case-insensitiven Formen:

- neues RAR: `stem.partN.rar` mit `N` aus 1 bis 6 Dezimalstellen, innerhalb
  einer Gruppe mit identischer Stellenbreite, beginnend bei dem numerischen
  Wert 1 und lückenlos aufsteigend; Einstieg ist dieses erste Volume;
- altes RAR: genau `stem.rar` gefolgt von `stem.r00` bis höchstens
  `stem.r99`, lückenlos und ohne `.sNN`-Fortsetzung; Einstieg ist `stem.rar`;
- 7z: `stem.7z.NNN` mit 3 bis 6 Dezimalstellen, innerhalb einer Gruppe mit
  identischer Stellenbreite, beginnend bei dem numerischen Wert 1 und
  lückenlos aufsteigend; Einstieg ist das erste Volume;
- Split ZIP: `stem.z01` bis höchstens `stem.z99`, lückenlos, zusammen mit
  genau `stem.zip`; die Gruppe wird nur inventarisiert und nicht an die v1-
  Runtime übergeben.

`stem` muss in allen Volumes bytegleich sein. Casefold- oder normalisierte
Namenskollisionen, weitere passende Dateien nach einer Lücke, gemischte
Stellenbreiten oder mehr als `max_volume_count` Einträge sind
`POLICY_REJECTED`; eine lückenhafte ansonsten eindeutige Folge ist
`MISSING_VOLUME`. Suffixzahlen werden numerisch und nicht lexikografisch
sortiert.

## Zustände

```text
ArchiveListingStatus
--------------------
NOT_ATTEMPTED
LISTED
PASSWORD_REQUIRED
UNSUPPORTED_FORMAT
UNSUPPORTED_METHOD
MISSING_VOLUME
CORRUPT
LIMIT_EXCEEDED
TIMED_OUT
TOOL_UNAVAILABLE
TOOL_FAILED
POLICY_REJECTED

ArchiveEncryptionStatus
-----------------------
NONE
DATA_ENCRYPTED
HEADERS_ENCRYPTED
MIXED
UNKNOWN

ArchiveIntegrityStatus
----------------------
NOT_TESTED
PASSED
PASSWORD_REQUIRED
UNSUPPORTED_METHOD
CORRUPT
LIMIT_EXCEEDED
TIMED_OUT
TOOL_UNAVAILABLE
TOOL_FAILED
POLICY_REJECTED

ArchivePasswordAttemptStatus
----------------------------
NOT_ATTEMPTED
ACCEPTED
REJECTED
SECURE_CHANNEL_UNAVAILABLE
LIMIT_EXCEEDED
TOOL_ERROR

ArchiveMemberKind
-----------------
REGULAR_FILE
DIRECTORY
SYMLINK
HARDLINK
REPARSE_POINT
FIFO
SOCKET
BLOCK_DEVICE
CHARACTER_DEVICE
UNKNOWN

ArchiveMemberCrcStatus
----------------------
NOT_AVAILABLE
NOT_TESTED
MATCHED
MISMATCHED

ArchiveSecretCandidateSource
----------------------------
USER_HANDLE
CONFIRMED_LOCAL_HANDLE
ARCHIVE_COMMENT
SAME_BASENAME_SIDECAR
DIRECTORY_SIDECAR
LOCAL_PASSWORD_LIST

ArchiveSidecarKind
------------------
NFO
TEXT
DIZ
INFO
URL
HTML
SFV
README
PASSWORD
```

`CORRUPT` bezeichnet einen reproduzierbaren Header-, CRC- oder
Integritätsfehler. `PASSWORD_REQUIRED` ist kein Korruptionsbefund.
`UNSUPPORTED_METHOD` bedeutet, dass die Containerfamilie erkannt wurde, aber
der festgelegte Tool-/Adaptervertrag mindestens eine Methode nicht verarbeiten
kann. Ein verschlüsseltes Archiv erhält in der realen v1-CLI immer
`SECURE_CHANNEL_UNAVAILABLE`, bevor ein Kandidat an 7-Zip übergeben würde.

## Read-only Toolmanifest und feste Command Shapes

```text
provider_id       = archive-7zip
adapter_version   = archive-7zip-cli/1
tool_version      = exakt 26.02
listing_profile   = archive-listing/v1
integrity_profile = archive-integrity/v1
extraction_profile = archive-extraction/v1
accepted_exit_codes = {0}
network           = disabled
```

Die öffentliche Adaptergrenze nimmt keine Argumentliste, kein Kennwort und
keine beliebige 7-Zip-Option entgegen. `A` ist genau ein intern validierter,
read-only Source-Pfad. Bei einer Volumegruppe ist `A` ausschließlich der nach
dem Volumevertrag bestimmte Einstiegspfad; die Vollständigkeit aller Volumes
wird vorher separat geprüft. `W` ist ein neu erzeugter leerer privater
Workspace außerhalb jedes `ScanRoot`.

```text
7zzs i

7zzs l -slt -ba -bd -bb0 -bso1 -bse2 -bsp0 -sccUTF-8 -- A

7zzs t -bd -bb0 -bso1 -bse2 -bsp0 -sccUTF-8 -mmt=1 -- A

7zzs x -y -bd -bb0 -bso1 -bse2 -bsp0 -sccUTF-8 -mmt=1 -oW -- A
```

Das Extraction Shape ist erst für die spätere Frontier-Runtime reserviert.
Es wird nur nach erfolgreichem Listing, Pfad-/Memberprüfung und Integritätstest
in einem Prozess-/Filesystem-Sandboxprofil freigegeben. `a`, `d`, `u`, `rn`,
`e`, `-sdel`, frei wählbare `-o`, Include-/Exclude-Listen, Wildcards,
Listfiles, `-p`, SFX, stdin/stdout-Archive und alle zusätzlichen Optionen sind
verboten.

Die Source wird read-only gemountet oder über einen read-only Handle geöffnet.
Das Arbeitsverzeichnis liegt auf einem privaten Dateisystem mit `umask 077`,
ohne Netzwerk, ohne zusätzliche Capabilities und mit begrenztem CPU-, RAM-,
Prozess-, Datei- und Plattenbudget. Source und Workspace dürfen sich nicht
überlappen.

7-Zip-Listing kann Containerkommentare und private Membernamen auf stdout
ausgeben. Ein Kommentar kann selbst Passwortmaterial enthalten. Die aktuelle
`ToolRuntime` persistiert stdout/stderr unverändert und darf deshalb auch für
unverschlüsseltes reales Archive-Listing nicht wiederverwendet werden. Der
spätere Frontier-Task benötigt einen bounded Streaming-Runner, der stdout
direkt verarbeitet und die Rohbytes danach verwirft. Der reale feste
`-ba -slt`-Befehl unterdrückt Archive-Header und Containerkommentar; er wird
deshalb nach [ADR-0043](ADR-0043-archive-machine-output-and-status-classification.md)
mit `archive-7zip-slt-parser/v2` als Member-only-Stream verarbeitet. Parser v1
bleibt ein synthetischer Legacy-Vertrag und darf diesen realen Stream nicht
auswerten. Die spätere Umwandlung eines Kommentars in einen lokalen
Passwortkandidaten benötigt weiterhin die in ADR-0039 getrennt benannte
Brücke. stderr wird bounded konsumiert und vollständig verworfen; Prosa und
grobe Exitcodes sind keine Ursachen-Authority. Persistierbar ist ausschließlich
ein normalisiertes, secretfreies DTO. Diese Outputlücke ist neben dem
Secret-Kanal ein harter Runtime-Blocker.

## Sicherheitsprofil und Budgets

`archive-safety-policy/v1` besitzt folgende feste Defaults:

```text
max_member_count                 = 10_000
max_volume_count                 = 256
max_total_uncompressed_bytes     = 8_589_934_592       # 8 GiB
max_single_member_bytes          = 2_147_483_648       # 2 GiB
max_compression_ratio            = 1_000
max_member_path_codepoints       = 1_024
max_member_path_utf8_bytes       = 4_096
max_member_path_segments         = 128
max_nested_depth                 = 0
max_listing_seconds              = 60
max_integrity_seconds            = 300
max_extraction_seconds           = 600
max_stdout_bytes                 = 8_388_608           # 8 MiB
max_stderr_bytes                 = 1_048_576           # 1 MiB
max_workspace_bytes              = 8_589_934_592       # 8 GiB
min_workspace_free_reserve_bytes = 1_073_741_824       # 1 GiB
max_tool_memory_bytes            = 1_073_741_824       # 1 GiB
max_tool_processes               = 1
max_concurrent_archive_jobs      = 2
max_concurrent_jobs_per_archive  = 1
```

Das Verhältnis wird je Member und für den Container kumulativ geprüft.
Positive unkomprimierte Größe bei null deklarierter komprimierter Größe ist
ein Limitfehler. Unbekannte Größen werden nicht als null angenommen; sie
blockieren die Extraktion. Die reale Bytezahl und Workspacebelegung werden
während der Extraktion zusätzlich gezählt. Der erste überschrittene Grenzwert
bricht den Prozess ab und verwirft die gesamte Ableitung.

`max_nested_depth=0` bedeutet, dass v1 ein erkanntes nested Archive nur als
Member-Evidence meldet. Es wird weder automatisch geöffnet noch rekursiv
extrahiert. Ein späteres Profil darf die Grenze höchstens nach einem eigenen
Security Review erhöhen.

## Member- und Workspace-Regeln

Vor jeder Extraktion wird die vollständige begrenzte Memberliste validiert.
Zulässig sind ausschließlich reguläre Dateien und Verzeichnisse. Abgewiesen
werden:

- leere Namen, NUL-/Steuerzeichen und nicht eindeutig decodierbare Namen;
- POSIX-absolute, Windows-absolute, UNC-, Extended-, Device- und Drive-relative
  Pfade;
- `.`-, `..`-Segmente, Root Escape, Backslash-/Slash-Tricks und Windows ADS;
- reservierte Windows-Gerätenamen, nachgestellte Punkte/Leerzeichen sowie
  NFC-, Casefold- oder Separator-normalisierte Zielkollisionen;
- Symlinks, Junctions, Reparse Points, Hardlinks, FIFOs, Sockets, Block- und
  Character Devices;
- Sparse-/Alternate-Stream-Ausgaben und Metadaten, die ACLs, xattrs, Owner,
  Gruppen, setuid/setgid oder besondere Dateiflags wiederherstellen würden;
- doppelte kanonische Memberziele und Eltern-/Kind-Konflikte zwischen Datei
  und Verzeichnis.

Der spätere Runtime-Wrapper setzt nach der Extraktion ausschließlich private
0600-/0700-Berechtigungen und validiert den Workspace ohne Links erneut. Erst
danach werden reguläre Dateien gestreamt gehasht. `listed members == extracted
regular members` und die deklarierte/gezählte Größenmatrix müssen gelten.
Teilresultate werden nicht als erfolgreiche Member-Evidence persistiert.

## Sidecars und lokale Passwortkandidaten

`archive-sidecar-classifier/v1` betrachtet nur bereits indexierte Dateien im
direkten Verzeichnis des Archivs. Es startet keine Rekursion. Zulässig sind:

- `.nfo`;
- `.txt`;
- `.diz`;
- `.info`;
- `.url`;
- `.html` und `.htm`;
- `.sfv`;
- extensionless Basenames `README`, `READ.ME`, `PASSWORD`, `PASSWORT`,
  `PASS` und `PW`, case-insensitiv.

HTML wird ohne Skript-/Style-Inhalte, externe Ressourcen oder aktive
Auswertung in bounded Text überführt; Entity-Decodierung zählt gegen
`max_decoded_codepoints`. URL-Dateien liefern nur lokale Textkandidaten; keine
URL wird geöffnet. SFV-Prüfsummen sind Evidence, nicht Passwortmaterial, außer
eine ausdrücklich erlaubte Textzeile enthält eine Markierung.

Die feste Quellenreihenfolge lautet:

1. ausdrücklich vom Benutzer bereitgestellter `SecretHandle`;
2. bestätigter Handle für exakt dieselbe versionierte Archive-/Release-
   Identity;
3. bounded Containerkommentar aus dem nicht persistierten Listing-Stream;
4. gleichnamige Sidecars der obigen Klassen;
5. übrige bereits indexierte Sidecars derselben Klassen im direkten
   Verzeichnis;
6. ausdrücklich konfigurierte lokale Passwortliste hinter einem
   `SecretProvider`.

Innerhalb einer Klasse wird nach privatem normalisiertem Locator und danach
Regelordinal deterministisch geordnet. Locator und Kandidatenmaterial werden
nicht in öffentliche DTOs oder Logs übernommen.

`archive-secret-candidate/v1` setzt folgende Grenzen:

```text
max_sidecar_files             = 32
max_bytes_per_sidecar         = 262_144             # 256 KiB
max_total_sidecar_bytes       = 1_048_576           # 1 MiB
max_decoded_codepoints        = 1_048_576
max_lines_per_sidecar         = 4_096
max_line_codepoints           = 4_096
max_html_nodes                = 10_000
max_uri_codepoints            = 4_096
max_candidates                = 64
max_attempts_per_archive      = 16
max_candidate_codepoints      = 256
max_candidate_utf8_bytes      = 1_024
```

Es werden nur UTF-8 mit oder ohne BOM und nach eigener Fixture-Bewertung
explizit freigegebene Legacy-Decodierungen verarbeitet. Die v1-Reihenfolge ist
exakt: BOM bestimmt UTF-8, UTF-16LE oder UTF-16BE; ohne BOM wird zuerst strikt
UTF-8 versucht. Nur nach dessen Fehlschlag verwenden `.nfo`, `.diz` und `.sfv`
CP437, während `.txt`, `.info`, `.url`, `.html`, `.htm` und extensionless
Sidecars Windows-1252 verwenden. Andere Encodings ergeben einen technischen
Parserbefund und keine Kandidaten.

Kandidaten entstehen nur aus case-insensitiven Markern `password`,
`passwort`, `kennwort`, `pass`, `pwd`, `pw`, aus deren `:`-/`=`-Wert oder aus
einer einzigen folgenden nichtleeren Zeile sowie aus entsprechend benannten
URI-Query-/Fragmentwerten. Ein eindeutiges PASSWORD-Sidecar darf zusätzlich
seine erste nichtleere Nicht-Kommentarzeile liefern. Sie werden nach Quelle
und Regel priorisiert, exakt dedupliziert und ausschließlich ephemer gehalten.
Verboten sind Brute Force, Wörterbucherweiterung, Kombinatorik, Ableitung aus
privaten Dateinamen und jede Netzwerkanfrage.

## `SecretHandle` und Prozessgrenze

Ein `SecretHandle` ist ein opaker, versionierter Verweis. Seine öffentliche
Repräsentation enthält ausschließlich Provider-ID, Handle-ID und
`secret_version`; niemals Secretbytes, Länge, Prefix, Hash oder eine
rückrechenbare Ableitung. Equality und Cache Keys verwenden die opake Version,
nicht das Material.

Persistierbar sind höchstens:

- opaker Handle und Secret-Version;
- Kandidatenquellklasse und Rang;
- Versuchszähler und `ArchivePasswordAttemptStatus`;
- Zeitpunkt, Archive-Identity und Profile;
- Tool-/Adapter-Version ohne Commandline.

Plaintext darf nicht in SQLite, JSON/CSV, `ToolResult`, `ToolArtifact`, Cache,
Exception, `repr`, `str`, LogRecord, Telemetrie, stdout/stderr, argv oder env
gelangen. Fehler werden vor der Persistenz auf feste Literale reduziert.

Für 7-Zip 26.02 existiert kein freigegebener sicherer CLI-Secret-Kanal.
Deshalb führt `archive-7zip-cli/1` keine Passwortversuche aus. Ein späterer
Frontier-Task darf erst dann verschlüsselte ZIP-, 7z- oder RAR-Payloads
freigeben, wenn ein isolierter Helper den Secret Handle in seinem Prozess
auflöst oder Secretbytes über einen einmaligen anonymen Pipe-/Handle-Kanal
empfängt, stdin/argv/env und jegliche Aufzeichnung technisch ausschließt,
Speicher nach dem Versuch bestmöglich löscht und das Format in adversarial
Tests tatsächlich unterstützt. Eine PTY-Automation des interaktiven 7-Zip-
Prompts ist kein akzeptierter Vertrag.

libarchive kann über `archive_read_set_passphrase_callback` einen Secretwert
ohne CLI-Argument annehmen und ist daher ein möglicher ZIP-spezifischer Helper-
Baustein. Wegen fehlender vollständiger verschlüsselter RAR-/7z-Unterstützung
und In-Process-Parserrisiko ist dies noch keine Runtime-Freigabe.

## Immutable Evidence, Profile und Reuse

```text
observation_profile = archive-observation/v1
member_profile      = archive-member-observation/v1
serializer_profile  = canonical-json/v1
parser_profile      = archive-7zip-slt-parser/v1
```

`canonical-json/v1` verwendet UTF-8, NFC-normalisierte Strings,
lexikografisch sortierte Objektschlüssel, feste DTO-Feldnamen und keine
Whitespace-Bytes. Listen mit fachlicher Reihenfolge behalten diese; Mengen
werden vor der Serialisierung nach ihrem vertraglichen Schlüssel sortiert.
IDs, Zeitpunkte und Enumwerte verwenden dieselben kanonischen Formen wie
ADR-0034. Floats und nicht endliche Zahlen sind verboten.

```text
ArchiveObservation
------------------
id
profile
source_observation_ids
source_full_sha256_values
archive_content_fingerprint
volume_group_fingerprint
container_class
format_kind
recognition_status
signature_profile
listing_status
encryption_status
integrity_status
listing_execution_id
integrity_execution_id
listing_profile
integrity_profile
safety_profile
observed_at
```

`source_observation_ids` enthält eine bis höchstens 256 kanonisch geordnete
aktuelle `FileObservation`-IDs derselben `ScanRoot`-/`ScanRun`-Lineage. Das
gleich lange `source_full_sha256_values` bindet deren jeweilige vollständige
Datei-SHA-256-Werte. `archive_content_fingerprint` ist der domain-separierte
Digest über diese geordnete Folge und kein Hash einer fiktiven
zusammengefügten Datei.

```text
ArchiveMemberObservation
------------------------
profile
archive_observation_id
volume_group_fingerprint
member_ordinal
member_identity
member_path_safe
member_kind
declared_compressed_bytes
declared_uncompressed_bytes
observed_uncompressed_bytes
member_sha256
crc_status
encryption_status
listing_execution_id
extraction_execution_id
listing_profile
extraction_profile
safety_profile
secret_version
```

`member_path_safe` ist ein validierter privater relativer Locator. Öffentliche
Status-/Report-DTOs geben ihn nicht aus. `member_identity` ist ein
domain-separierter SHA-256 über Archive-Identity, Volumegruppe, kanonischen
Memberlocator, Memberordinal und Listingprofil; es ist keine File-ID.

`listing_execution_id` ist für jedes Member erforderlich.
`extraction_execution_id`, `observed_uncompressed_bytes` und `member_sha256`
sind gemeinsam nullable und erst nach vollständig erfolgreicher Extraktion
gesetzt. Deklarierte Größen dürfen bei einem Format fehlen; dann blockiert
`POLICY_REJECTED` die Extraktion. `secret_version` ist `NONE`, solange kein
sicherer erfolgreicher Passwortversuch existiert. Bei
`HEADERS_ENCRYPTED` entsteht ohne sicheren Kanal keine Memberliste und damit
keine scheinbar leere Membermenge.

Eine erfolgreiche Member-Ableitung ist nur wiederverwendbar, wenn exakt gleich
sind:

```text
archive full SHA-256
vollständiger volume_group_fingerprint
tool provider und tool version
adapter/parser version
listing_profile
extraction_profile
safety_profile
secret_version oder NONE
```

Der Reuse Key lautet `archive-member-reuse/v1`. Listing ohne Extraktion darf
separat mit `archive-listing-reuse/v1` wiederverwendet werden. Ein neueres
fehlgeschlagenes, abgebrochenes oder limitüberschreitendes Ergebnis darf eine
ältere erfolgreiche Ableitung nicht still als aktuell erscheinen lassen.
Alle Persistenzmodelle sind insert-only Snapshots. Diese ADR legt keine
Migration oder konkrete Tabellennamen fest.

## Grenze der Folgepakete

S-EBA-01 bis S-EBA-07 dürfen ausschließlich synthetische Fixtures, reine
Observer/Parser/Validatoren, `SecretHandle`-Redaction und einen Fake-
`ToolProvider` implementieren. Sie dürfen insbesondere nicht:

- `7zzs`, `bsdtar`, libarchive oder ein anderes reales Archivtool starten;
- Archive real extrahieren oder ein Secret an einen Prozess übergeben;
- eine Persistenzmigration hinzufügen;
- einen Online-Passwortprovider anbinden;
- Archive-aware Matching, Keep Preference oder Deduplizierungsplanung
  implementieren.

Erst nach grünem S-EBA-01..07-Abschluss folgt ein separates Frontier-Gate für
Prozessisolation, echte 7-Zip-Version/Packaging, Outputparser, private
Extraction Fixtures und gegebenenfalls einen sicheren Secret Helper. Die
Secret-Kanallücke ist bis dahin ein harter Runtime-Blocker, kein optionaler
Finding.

## W10- und Privacy-Grenze

Source-Archive und Sidecars bleiben unverändert. FolioTone extrahiert nie
neben das Source-Archiv und löscht weder Archiv noch Sidecar oder leeres
Verzeichnis. `QUARANTINE`, `PURGE` und `EMPTY_DIRECTORY_REVIEW` bleiben
nicht ausführbare Intents aus ADR-0034. Archive-Evidence kann einen
`ConsolidationPlan` blockieren oder stützen, aber niemals allein eine
Mutation autorisieren.

Online-Passwortsuche, Newzcrabber und andere Usenet-/Webquellen sind nicht
Teil dieses Gates. Es gibt keinen automatischen Internet-Fallback. Eine
spätere Providerintegration benötigt eine bestätigte Produktidentität,
dokumentierte API, Terms-/Privacy-/Cache-Prüfung, explizites Opt-in und ein
separates Provider-Gate.

## Konsequenzen

- Die mechanischen S-EBA-Pakete besitzen exakte Literale, Limits, Profile und
  Stopbedingungen.
- Unverschlüsselte Archive können später über einen einzigen optionalen
  ToolProvider analysiert werden, ohne Toolbreite in den Core zu übernehmen.
- Verschlüsselte Archive bleiben sichtbar und reviewbar, werden aber nicht
  durch einen unsicheren Passwortparameter verarbeitet.
- Publication Container, Generic Archive, Member-Evidence und physische Datei
  bleiben getrennte Ebenen.
- Eine reale Extraction Runtime, Persistenz und jede W10-Operation bleiben
  außerhalb dieses Gates.

## Verifikation

Das Gate selbst ändert keinen Produktionscode und führt keine Toolausführung
aus. Folgepakete prüfen mit synthetischen Fixtures mindestens alle Signaturen,
Suffixkonflikte, Volumeformen, Statuswerte, Sidecarklassen, Parserlimits,
Secret-Redaction, Windows-/POSIX-Traversal, Link-/Device-/Hardlinktypen,
Budgetgrenzen, nested Archive und den Fake-Tool-Reuse-Key.

## Primärquellen

- 7-Zip 26.02 Download und Plattformpakete:
  https://www.7-zip.org/download.html
- 7-Zip Formatabdeckung und Lizenz:
  https://www.7-zip.org/
- 7-Zip 26.02 History und Symlink-Sicherheitsänderungen:
  https://github.com/ip7z/7zip/blob/main/DOC/src-history.txt
- 7-Zip Command-Line-Hilfeindex einschließlich `l`, `t`, `x`, `-slt`, `-p`
  und Exitcodes:
  https://github.com/ip7z/7zip/blob/main/DOC/7zip.hhp
- Offene 7-Zip-Anforderung für einen Passwortkanal über separaten File
  Descriptor:
  https://github.com/ip7z/7zip/issues/184
- libarchive 3.8.9 Releases:
  https://github.com/libarchive/libarchive/releases/tag/v3.8.9
- libarchive Formatabdeckung:
  https://github.com/libarchive/libarchive/wiki/LibarchiveFormats
- libarchive Passphrase-Callback:
  https://github.com/libarchive/libarchive/blob/master/libarchive/archive.h
- libarchive-Testvertrag: verschlüsseltes 7z-Member ist erkennbar, der
  Payload-Read schlägt jedoch fehl:
  https://github.com/libarchive/libarchive/blob/master/libarchive/test/test_read_format_7zip_encryption_data.c
- libarchive-Issue zur fehlenden verschlüsselten RAR-/7z-Payloadverarbeitung:
  https://github.com/libarchive/libarchive/issues/2516
- `bsdtar`-Manual mit der ausdrücklichen Warnung zu `--passphrase`:
  https://github.com/libarchive/libarchive/blob/master/tar/bsdtar.1
