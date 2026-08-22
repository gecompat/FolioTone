# ADR-0063: Begrenzter EPUB-Titelwriter mit atomarem Austausch

- Status: Accepted
- Datum: 2026-08-22

## Kontext

ADR-0061 erlaubt die kontrollierte Entwicklung von E-Book-Writer-Pfaden mit
synthetischen Fixtures. ADR-0062 liefert dafür einen immutable, reviewten und
dauerhaft `NOT_EXECUTABLE` bleibenden `MetadataCorrectionPlan`. Vor einem
Source-Metadata-Writer fehlen noch die operation-spezifische Formatgrenze, der
Rohwerterhalt, der Byte-/Semantik-Diff sowie ein belegbarer Backup-, Crash- und
Recovery-Vertrag.

Ein allgemeiner Metadata-Writer über EPUB, MOBI, AZW, AZW3 und PDF würde diese
Entscheidungen vermischen. EPUB ist außerdem ein OCF-ZIP-Container: Selbst eine
einzelne Titelkorrektur erzeugt neue Containerbytes und einen neuen vollständigen
Datei-Hash. Das Ziel dieser ADR ist deshalb genau ein kleiner, überprüfbarer
Einstieg und keine formatübergreifende Write-Abstraktion.

## Entscheidung

`FG-W10-METADATA-WRITE` akzeptiert ausschließlich den Writer:

```text
ebook-source-metadata-write/epub3-title-replace/v1
```

Der Writer darf genau einen `MetadataCorrectionPlan` mit diesen Eigenschaften
auflösen:

- `format_label = EPUB`;
- `target_carrier = SOURCE_METADATA` und Zielreferenz auf dieselbe `FileRecord`;
- Planstatus `APPROVED_NON_EXECUTABLE` bei weiterhin unverändertem
  `execution_state = NOT_EXECUTABLE`;
- genau eine Feldkorrektur `title` mit `operation = REPLACE`;
- genau ein ausgewählter Wert im Zustand `CANONICAL` oder `USER_CONFIRMED`;
- `CALIBRE = KNOWN_NONE`, `SIDECAR = KNOWN_NONE` und
  `ARCHIVE = NOT_APPLICABLE`.

Alle anderen Feldpfade, `REMOVE`, mehrere Werte, EPUB 2, KEPUB, mehrere
Renditions sowie MOBI, AZW, AZW3 und PDF sind inkompatibel mit diesem Profil.
Ein inkompatibler Plan wird vor Source-I/O abgewiesen. Sidecar-, Calibre-,
externe Library-, Rename-, Reorganisations- und allgemeine Archivewrites
bleiben hinter ihren eigenen Gates geschlossen.

Die W10-Schicht deutet den W9-Plan nicht um. Eine spätere kurzlebige
`metadata-write-authorization/v1` bindet Plan-ID, Plan-Content-Hash,
Writerprofil, Writer-/Parserversion, erwarteten Input- und Output-Hash, den
technischen `dcterms:modified`-Wert, ScanRoot, Capability-ID und Ablaufzeit.
Sie ist einmal verwendbar und erzeugt keine `write-all`-Capability. Der
spätere Run und jedes Event binden zusätzlich die tatsächlich gehaltene
frische Lease-Fence; eine Authorization ersetzt oder reserviert keine Lease.

Die Authorization darf erst nach einer nicht mutierenden Vorbereitung
entstehen. Dieser Prepare-Schritt friert einen vorgeschlagenen
`authorized_at`-Zeitpunkt ein, hält kurz eine Root-Lease, revalidiert den
Input, baut und verifiziert damit den deterministischen Staging-Output und
berechnet dessen vollständigen Hash. Nur eine unmittelbar danach bestätigte
Authorization übernimmt genau diesen Zeitpunkt und Output-Hash. Execute
erwirbt später eine neue Root-Lease, revalidiert den Input erneut und
akzeptiert nur denselben gebundenen Output-Hash. Ein Prepare-Ergebnis allein
ist weder Authorization noch Mutation.

## Zulässiges EPUB-Profil

Der erste Writer akzeptiert nur eine bereits konforme, unverschlüsselte und
unsignierte EPUB-3-Publikation. Vor dem Patch müssen mindestens folgende
Eigenschaften feststehen:

1. Die Source ist genau eine reguläre Datei ohne Symlink, Reparse Point oder
   weitere Hardlinks.
2. Der OCF-Container besitzt eindeutige UTF-8-Entry-Namen, keine ZIP-
   Verschlüsselung, keine Split-/Spanned-Struktur und ausschließlich die
   Kompressionsmethoden `stored` oder `deflate`.
3. `mimetype` ist der erste, unkomprimierte Entry ohne Extra Field und enthält
   exakt `application/epub+zip`.
4. `META-INF/container.xml` verweist auf genau ein vorhandenes Package
   Document vom Typ `application/oebps-package+xml`.
5. Das Package Document ist UTF-8-kodiert, verwendet EPUB 3 und enthält weder
   `DOCTYPE` noch Entity-Deklarationen.
6. Es existiert genau ein einfaches `dc:title` ohne Kindknoten, `CDATA`,
   Subtitle- oder Refinement-Semantik.
7. Es existiert genau ein nicht verfeinertes `dcterms:modified` im durch EPUB 3
   vorgeschriebenen UTC-Format.
8. `META-INF/signatures.xml` und `META-INF/encryption.xml` fehlen.
9. EPUBCheck 5.3.0 bewertet den unveränderten Input als `CONFORMANT`.

Unbekannte Archivefeatures, ein nicht vollständig lesbarer Entry, zusätzliche
Renditions, Signaturen, Verschlüsselung oder nicht eindeutig lokalisierbare
Zieltexte ergeben keinen Reparaturversuch. Der Writer endet fail-closed.

Diese Einschränkungen sind eine v1-Kompatibilitätsmatrix und kein Urteil über
die Qualität abgewiesener EPUBs. Spätere Profile dürfen einzelne Fälle nur
nach eigener Primärquellenprüfung und synthetischem Konformitätsnachweis
öffnen.

## Rohwerterhalt und Patchvertrag

Der Patch wird durch FolioTone erzeugt. Ein no-network XML-Parser validiert
zuerst die Semantik; ein getrennter begrenzter lexikalischer Scanner bestimmt
danach die beiden eindeutigen Textspannen. Der Writer ersetzt ausschließlich:

1. den Textinhalt des einzigen `dc:title` durch den ausgewählten Planwert in
   gültiger XML-Escapingform;
2. den Textinhalt des einzigen `dcterms:modified` durch den in der
Authorization gebundenen UTC-Sekundenwert.

Der technische Änderungszeitpunkt ist der spätere Wert aus dem auf volle
Sekunden normalisierten Authorization-Zeitpunkt und dem bisherigen
`dcterms:modified` plus einer Sekunde. Liegt der Ausgangswert mehr als 300
Sekunden nach dem Authorization-Zeitpunkt, blockiert er die Authorization.
Dadurch ist der Output bei Retry und Recovery deterministisch.
`dcterms:modified` ist eine formatbedingte technische Änderung und keine
zweite kanonische Metadatenkorrektur.

Alle Bytes des Package Documents außerhalb dieser beiden Textspannen müssen
identisch bleiben. Insbesondere bleiben Identifier, Contributors, Sprachen,
Titel-Refinements, Sortierwerte, Publisher, Subjects, Serienwerte, Rechte,
Custom Metadata, Manifest, Spine, Links, Prefixe, Kommentare und Whitespace
unverändert. Der Patch fügt weder ein FolioTone-Tag noch calibre-spezifische
Metadaten hinzu.

Der Writer baut den OCF-Container streaming-basiert neu auf. Entry-Menge,
Reihenfolge, Namen, Archiv- und Entry-Kommentare, Zeitstempel,
Kompressionsmethoden, Extra Fields, interne/externe Attribute sowie
unkomprimierte Inhalte bleiben erhalten; nur der Package-Document-Entry darf
andere Inhaltsbytes besitzen. OCF-vorgeschriebene UTF-8- und `mimetype`-Flags
bleiben gesetzt. Containerheader und komprimierte Bytes dürfen sich durch den
Neuaufbau ändern. Deshalb gelten der vollständige Datei-Hash und ein
pauschaler Binärvergleich nicht als Semantik-Diff.

Der feste Diffvertrag verlangt stattdessen:

- alter und neuer vollständiger SHA-256 sind verschieden und gebunden;
- alle Nicht-Package-Entries besitzen vor und nach dem Lauf denselben
  streaming-berechneten SHA-256 und dieselbe unkomprimierte Länge;
- Entry-Menge und Reihenfolge sind gleich;
- das Package Document unterscheidet sich bytegenau nur in den zwei erlaubten
  Textspannen;
- der neue Titel und `dcterms:modified` stimmen semantisch exakt mit der
  Authorization überein;
- Dateityp, Owner, Group, Mode und erlaubte Dateiattribute bleiben gleich;
  nicht vollständig inventarisierbare ACLs oder Extended Attributes blockieren
  v1.

Observed- und sonstige Rohwerte bleiben zusätzlich unverändert in FolioTones
Evidence- und Planpersistenz erhalten. Ein erfolgreicher Source-Write
überschreibt keine historische `ValueAssertion`.

## Bewertung externer Spezialwerkzeuge

calibre 9.13.0 und EPUBCheck 5.3.0 bleiben gepinnte Spezialwerkzeuge. Sie
erhalten in diesem Profil jedoch unterschiedliche Rollen.

`ebook-meta` ist laut offizieller CLI sowohl Reader als auch Writer. Die
versionierte Sourceprüfung zeigt für einen Setter-Aufruf eine breite
Mutation: Das Tool liest das vollständige Metadatenobjekt, setzt alle
nichtleeren unterstützten Felder erneut, erzeugt bei `--title` zusätzlich
`title_sort`, serialisiert das OPF neu und öffnet die Datei anschließend
`r+b`. Die offizielle Dokumentation warnt außerdem, dass nicht unterstützte
Metadaten je Format still ignoriert werden können. Dieser Vertrag ist für den
bytegenau begrenzten v1-Patch zu breit.

`ebook-polish --opf` kann einen getrennten Output erzeugen und versucht
Änderungen zu minimieren, übernimmt aber einen vollständigen OPF-
Metadatensatz statt genau einer gebundenen Textspanne. Es wird deshalb für v1
ebenfalls nicht als Writer verwendet.

FolioTone implementiert den kleinen Container-/XML-Patch nativ, weil die
dokumentierten CLI-Grenzen den benötigten Rohwerterhalt nicht ausdrücken.
calibre bleibt über den vorhandenen read-only Adapter
`ebook-meta-opf/2` eine unabhängige semantische Read-back-Evidence. EPUBCheck
5.3.0 bleibt die unabhängige Formatprüfung. Toolabwesenheit, falsche Version
oder ein fehlgeschlagener Read-back blockieren die Mutation beziehungsweise
deren Verifikation; sie öffnen keinen nativen Fallback mit schwächerer
Prüfung.

## Staging und unmittelbare Revalidierung

Der Writer führt keinen externen Prozess gegen die Source aus. Die
Ausführungsfolge lautet:

1. Capability, Authorization, Plan-/Review-Lineage, Dependencies und
   `ScanRootWriteLease` mit frischer Fence-Epoch prüfen.
2. Die Source über no-follow Directory-FDs öffnen und Full-SHA-256, Größe,
   Zeitstempel, Dateityp, Linkzahl und Attribute gegen Plan und Authorization
   revalidieren.
3. Die Bytes streaming-basiert in einen privaten Workspace kopieren und Source
   sowie Kopie erneut vollständig hashen.
4. Patch und Containerneuaufbau ausschließlich im privaten Workspace
   durchführen.
5. Den Staging-Output durch den Byte-/Semantik-Diff, den vorhandenen
   Metadatenadapter, EPUBCheck, Text-/Lesbarkeitsanalyse und Coverfingerprint
   prüfen.
6. Den fertig verifizierten Output in einen exklusiv erzeugten temporären
   Eintrag im Source-Elternverzeichnis kopieren, Datei und Verzeichnis per
   `fsync` persistieren und dessen Hash nochmals prüfen.
7. Unmittelbar vor dem Austausch alle Source-Preconditions, Authorization und
   Lease-Fence erneut prüfen und `PREPARED` append-only persistieren.
8. Genau einen atomaren Austausch durchführen und danach beide Seiten anhand
   der gebundenen Hashes klassifizieren.

Ein Tool-Exitcode, ein erfolgreicher XML-Parse oder ein einzelner Hash genügt
nicht. Jeder Fehler vor Schritt 8 lässt den Source-Eintrag unverändert.

## Linux-Austausch-, Backup- und Recoverygrenze

Das erste ausführbare Backend heißt:

```text
epub-source-replace-linux-renameat2/v1
```

Es ist ausschließlich für die primäre Linux/Docker-Runtime vorgesehen. Ein
kleiner Python-Adapter bindet die glibc-Funktion `renameat2` über feste
Directory-FDs und feste Flags. Beliebige Pfade, Syscallnummern, Shellbefehle
oder caller-kontrollierte Flags sind nicht Teil der öffentlichen Schnittstelle.

Die Capability löst eine opaque ID auf genau einen `ScanRoot`, einen privaten
gleichartigen Recovery-Bereich und das Writerprofil auf. Source-Eltern- und
Recovery-Verzeichnis müssen auf demselben lokalen Filesystem liegen. Vor der
ersten Ausführung prüft der Adapter `RENAME_EXCHANGE` und
`RENAME_NOREPLACE` in einem capability-eigenen synthetischen Probe-Slot.
Fehlende Flag- oder Filesystemunterstützung, `EXDEV`, NFS, Overlay-/Remote-
Semantik ohne akzeptierten Konformitätsnachweis, native Windows-Ausführung
oder ein read-only Mount ergeben `TOOL_UNAVAILABLE`. FolioTone remountet oder
installiert nichts still.

Der Commit verwendet `renameat2(RENAME_EXCHANGE)`, um den vorbereiteten
Output und den bestehenden Source-Eintrag atomar zu tauschen. Der temporäre
Eintrag enthält danach das bisherige Original. Erst nachdem beide Einträge
erneut als erwarteter Output beziehungsweise erwartetes Original bestätigt
sind, wird das Original mit `RENAME_NOREPLACE` unter einer content-addressed,
nicht kollidierenden Recovery-Referenz im Capability-Bereich abgelegt.
Datei- und beide Verzeichnis-FDs werden an den vorgeschriebenen Grenzen per
`fsync` persistiert.

Damit gibt es keinen Copy+Delete-, Cross-Volume- oder Overwrite-Fallback. Ein
konkurrierend ausgetauschter Source-Eintrag wird durch den nach dem atomaren
Exchange herausgetauschten Hash erkannt. Solange die Einträge noch exakt den
beiden journalisierten Hashes entsprechen, darf die Recovery den Exchange
umkehren. Bei abweichendem oder nicht eindeutigem Zustand führt sie keine
weitere Mutation aus und markiert den Run für manuelle Recovery.

Die append-only Run-/Eventpersistenz muss mindestens diese stabilen Phasen
rekonstruierbar machen:

```text
CREATED
PREPARED
EXCHANGED
ORIGINAL_PRESERVED
VERIFIED
RECOVERED
MANUAL_RECOVERY_REQUIRED
```

Ein Crash darf zwischen jeder Dateisystem- und Journalgrenze auftreten. Die
Recovery klassifiziert Source, temporären Eintrag und Recovery-Artefakt nur
über gebundene Typen, Metadaten und vollständige Hashes. Sie ist idempotent
und fence-gebunden. Nicht mehr benötigte Draft-, Original- oder
Incident-Artefakte werden durch diesen Writer nicht gelöscht. Eine spätere
Retention-/Purge-Entscheidung bleibt W10-003 vorbehalten.

Vor `VERIFIED` darf Recovery den ursprünglichen Zustand nur als Abschluss
derselben einmal autorisierten Operation wiederherstellen. Nach `VERIFIED`
ist eine fachlich gewünschte Rücknahme ein separater Rollback mit neuer
Authorization und nicht mehr Teil dieses Writers.

## Post-write-Verifikation und Reconciliation

Nach dem Austausch muss der Executor bei weiterhin gehaltener Root-Lease
mindestens bestätigen:

- den erwarteten neuen Full-SHA-256 und den erwarteten regulären Dateizustand;
- den vollständigen Byte-/Semantik-Diffvertrag;
- den ausgewählten Titel über den FolioTone-Patcher und unabhängig über
  `ebook-meta-opf/2`;
- `CONFORMANT` durch EPUBCheck 5.3.0;
- unveränderte normalisierte Text-, Cover- und Nicht-Zielfeld-Fingerprints;
- die Abwesenheit unerwarteter Calibre-, Sidecar- und Archive-Dependencies.

Danach erzeugt ein neuer Scan eine neue `FileObservation`; alle vom alten
Full-SHA-256 oder Package-Document-Fingerprint abhängigen Results werden
stale. `CollectionState`, Quality, Matching und Review werden aus persistierter
Evidence neu aufgebaut. Der Writer übernimmt weder stillschweigend die alte
Edition-Identity noch setzt er einen neuen kanonischen Wert ohne die bereits
gebundene Reviewentscheidung.

Erst wenn unmittelbare Verifikation und Reconciliation erfolgreich sind,
erhält der Run `VERIFIED`. Ein fachlich korrekt geschriebener Titel bei
fehlgeschlagener Struktur-, Lesbarkeits- oder Erhaltungsprüfung ist kein
Erfolg und bleibt recoverable beziehungsweise reviewpflichtig.

## Privacy- und Bediengrenze

Standard-CLI, JSON, Logs und Fehler enthalten ausschließlich opaque IDs,
Profile, Zustände, Counts, Zeitpunkte und feste Fehlercodes. Titelwerte,
Pfade, Dateinamen, Source-/Output-Hashes, temporäre Namen, Recovery-Namen und
Capability-Inhalte bleiben privat. Eine spätere CLI nimmt nur Plan-ID,
Plan-Content-Hash, Capability-ID und opaque Authorization-ID an; die zweite
Bestätigung erfolgt über nicht geloggtes `stdin`.

Der normale Analysebetrieb behält read-only `/media`-Mounts. Ein Write-Lauf
benötigt einen separat gestarteten, explizit read-write bereitgestellten Mount
für genau die lokale Capability. Die Runtime darf weder Mounts ändern noch
Tools installieren. REST-API und grafische Oberfläche bleiben bis FUT-011
geschlossen und können später nur dieselben Application-Verträge aufrufen.

## Lieferpakete

Die Umsetzung folgt in getrennten kleinen Waves:

1. `S-W10-MW01`: reine bounded EPUB-3-Preflight-, lexikalische Patch- und
   Byte-/Semantik-Diff-Verträge mit synthetischen Fixtures; keine Source-
   Mutation, Persistenz, CLI oder Capability.
2. `S-W10-MW02`: privater Staging-Builder und feste Read-back-/EPUBCheck-/
   Text-/Cover-Verifikation, weiterhin ohne Source-Commit.
3. `S-W10-MW03`: immutable Authorization-/Run-/Eventpersistenz,
   Capability-Auflösung, Root-Lease-/Fence-Vertrag und read-only Status.
4. `S-W10-MW04`: Linux-`renameat2`-Backend, Executor und idempotente
   Crash-Recovery auf synthetischen Filesystemen.
5. `S-W10-MW05`: feste Authorize-/Execute-/Recover-CLI, zweiter
   Bestätigungsschritt, neuer Scan und Collection-Reconciliation.

Bis alle fünf Pakete einschließlich des exakten Runtime-Konformitätsgates
abgeschlossen sind, bleibt die reale Source-Metadata-Mutation operativ nicht
verfügbar. `S-W10-MW01` implementiert den reinen Preflight-, Patch- und Diff-
Vertrag; `S-W10-MW02` implementiert privates Streaming-Staging und die festen
unabhängigen Validatoren. `S-W10-MW03` implementiert die immutable
Authorization-/Run-/Eventpersistenz, private Capability-Auflösung,
Root-Lease/Fencing und read-only Status. `S-W10-MW04` implementiert das feste
Linux-x86_64-glibc-Backend, die persistente Backend-/Probe-Bindung, den
gefenceten Ein-Datei-Executor und idempotente Recovery für exakte bekannte
Hashverteilungen. Der Erfolgszustand bleibt `ORIGINAL_PRESERVED`; eine
operative Source-Mutation besteht bis CLI, zweiter Bestätigung, Post-write-
Verifikation, neuem Scan und Reconciliation aus `S-W10-MW05` weiterhin nicht.

## Synthetische Konformitätsmatrix

Jedes Paket testet nur seine betroffene Grenze. Die Gesamtmatrix umfasst
mindestens:

- einen minimalen gültigen EPUB-3-Titelwechsel mit Sonderzeichen;
- falschen Zielträger, Format, Feldpfad, Operation, Value-State und
  Mehrfachwert;
- `UNKNOWN` oder `KNOWN_PRESENT` für Calibre, Sidecar und Archive;
- EPUB 2, KEPUB, mehrere Rootfiles/Titel/Renditions, Refined Title, Subtitle,
  `DOCTYPE`, `CDATA`, Signatur, Verschlüsselung und initiale
  Nichtkonformität;
- Duplicate Entry-Namen, unzulässige Kompressionsmethode und verletzten
  `mimetype`-Vertrag;
- bytegenauen OPF-Erhalt außerhalb der zwei erlaubten Spannen sowie identische
  Nicht-Package-Entry-Hashes;
- Source-Änderung vor Staging, vor `PREPARED`, unmittelbar beim Exchange und
  nach dem Exchange;
- Symlink, Reparse Point, Hardlink, fremden Owner, ACL-/Xattr-Unklarheit,
  `EXDEV`, unsupported Flags, NFS und Recovery-Kollision;
- Fenceverlust, abgelaufene oder wiederverwendete Authorization und Retry;
- Crash nach jeder persistierten Phase und idempotente Recovery für jede
  beobachtbare Hashverteilung;
- pfad- und metadatenwertfreie Reports, Logs und Fehler.

Reale private E-Books und produktive Runtime-Datenbanken sind weder
Entwicklungs- noch CI-Fixtures. Pro Implementierungswave laufen
lokal nur fokussierte synthetische Tests; der stabile Pull-Request-Head erhält
genau einen vollständigen CI-Gate.

## Folgen

- `FG-W10-METADATA-WRITE` ist für genau EPUB 3, `SOURCE_METADATA` und einen
  einzelnen `title`-`REPLACE` entschieden.
- calibre wird nicht zur Write-Authority; seine bestehende read-only
  Metadatenprojektion und EPUBCheck bleiben unabhängige Validatoren.
- Der neue Full-SHA-256 ist erwartete Revisions-Evidence und kein Verlust der
  bestehenden `FileRecord`-Lineage.
- Die Linux/Docker-Implementierung kann ohne Windows- oder
  formatübergreifende Abstraktion beginnen und bleibt auf nicht unterstützten
  Filesystemen fail-closed.
- Sidecar, Calibre Library, externe Tools, andere Felder/Formate, Rollback,
  Purge, Rename und allgemeine Containeränderungen werden nicht freigegeben.
- Operative Source-Mutation bleibt geschlossen, bis Capability, Authorization,
  Staging, Commit, Journal, Recovery, CLI und Reconciliation vollständig
  implementiert und synthetisch belegt sind.

## Geprüfte Primärquellen

Bewertet am 2026-08-22 gegen die im Projekt gepinnten Toolversionen:

- calibre 9.13.0 `ebook-meta`:
  https://manual.calibre-ebook.com/generated/en/ebook-meta.html
- calibre 9.13.0 `ebook-polish`:
  https://manual.calibre-ebook.com/generated/en/ebook-polish.html
- calibre 9.13.0 `ebook-meta`-Implementierung:
  https://github.com/kovidgoyal/calibre/blob/v9.13.0/src/calibre/ebooks/metadata/cli.py
- calibre 9.13.0 EPUB-Metadatenwriter:
  https://github.com/kovidgoyal/calibre/blob/v9.13.0/src/calibre/ebooks/metadata/epub.py
- calibre 9.13.0 OPF-3-Metadatenwriter:
  https://github.com/kovidgoyal/calibre/blob/v9.13.0/src/calibre/ebooks/metadata/opf3.py
- calibre 9.13.0 ZIP-Replace-Implementierung:
  https://github.com/kovidgoyal/calibre/blob/v9.13.0/src/calibre/utils/zipfile.py
- W3C EPUB 3.3:
  https://www.w3.org/TR/epub-33/
- Linux `renameat2(2)`:
  https://man7.org/linux/man-pages/man2/rename.2.html
- Python `os.fsync` und Directory-FD-Schnittstellen:
  https://docs.python.org/3/library/os.html
- SQLite Atomic Commit:
  https://www.sqlite.org/atomiccommit.html
