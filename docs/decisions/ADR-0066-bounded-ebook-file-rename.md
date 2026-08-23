# ADR-0066: Begrenzter E-Book-Datei-Rename

- Status: Accepted
- Datum: 2026-08-23

## Kontext

ADR-0065 definiert dauerhaft nicht ausführbare, reviewte
`EbookOperationRecipePlan`-Snapshots für sechs Operationsfamilien. Der erste
noch fehlende Pfad zu einem nutzbaren Rezept beginnt nicht beim
Dateisystemaufruf: Für `FILE_RENAME` existieren bisher weder eine begrenzte
Proposal-/Review-/Plan-Oberfläche noch eine operation-spezifische W10-
Capability, Authorization, Ausführung oder Reconciliation.

Ein Rename verändert keine Nutzbytes, aber mehrere sicherheitsrelevante
Zustände gleichzeitig. Der geplante Name kann zwischen Review und Ausführung
belegt werden, ein Locator kann durch Unicode-Normalisierung oder
Groß-/Kleinschreibung aliasieren, ein Parent kann durch einen Symlink oder
Mountwechsel ersetzt werden und ein Crash kann zwischen Kerneloperation,
Directory-`fsync`, Journal und Folgescan eintreten. Der SQLite-Commit kann den
Dateisystem-Rename nicht atomar einschließen.

`FILE_REORGANIZE` ist trotz gleicher Byteidentität ein anderer
Sicherheitsvertrag: Die Operation betrifft zwei Elternverzeichnisse, benötigt
deren getrennte Haltbarkeitsnachweise und wirft zusätzliche Fragen zu
Zielverzeichnissen und Verzeichnis-Dependencies auf. Ein gemeinsames Gate
würde den ersten Writer unnötig verbreitern.

ADR-0061 erlaubt die kontrollierte Entwicklung mit synthetischen Fixtures.
Sie autorisiert weder reale Dateien noch eine allgemeine Rename-Funktion. Die
normale Analyse-Runtime behält ihre read-only `/media`-Mounts.

## Entscheidung

`FG-W10-RENAME` akzeptiert ausschließlich einen byte-identischen Rename genau
einer regulären E-Book-Datei auf einen anderen Basename im selben bereits
vorhandenen Parent und `ScanRoot`. Das feste Writerprofil lautet:

```text
ebook-file-rename-linux-renameat2-noreplace/v1
```

Die W10-Verträge verwenden zusätzlich diese festen Profile:

```text
ebook-file-rename-proposal/v1
ebook-file-rename-preparation/v1
ebook-file-rename-authorization/v1
ebook-file-rename-run/v1
ebook-file-rename-execution-confirmation/v1
ebook-file-rename-capability/v1
ebook-file-rename-capability-probe/v1
ebook-file-rename-dependency-scope/v1
ebook-file-rename-reconciliation/v1
ebook-file-rename-status-report/v1
```

Der bestehende W9-Plan bleibt permanent `NOT_EXECUTABLE`. Nur ein neuer,
höchstens 15 Minuten gültiger und genau einmal verbrauchbarer
`EbookRenameAuthorizationSnapshot` darf einen einzelnen Run öffnen. Es gibt
keinen globalen Rename-Schalter und keine gemeinsame `write-all`-Capability.

`FILE_REORGANIZE` wird in `FG-W10-REORGANIZE` separat entschieden. Import,
Export, Transformation und Archive-Rewrite bleiben ebenfalls hinter ihren
eigenen Gates. Der vorhandene Quarantäne-Interim-Executor und der EPUB-
Metadatenwriter werden nicht als generischer Move- oder Rename-Executor
umgedeutet.

## Feste Planungs- und Reviewoberfläche

Der erste Implementierungsslice ergänzt vor jeder W10-Authority ausschließlich
folgende nicht mutierende Application-/CLI-Fläche:

```text
ebook-rename-propose --observation-id UUID --dependency-scope-id UUID
ebook-rename-preview --candidate-id UUID --private-details
ebook-rename-review --candidate-id UUID --decision ACCEPT|REJECT|DEFER
ebook-rename-plan --candidate-id UUID
```

`ebook-rename-propose` liest genau einen Ziel-Basename als begrenzte, nicht
geloggte `stdin`-Zeile. Der Wert ist weder argv noch Environment-Variable und
wird nicht in Standardausgabe oder Fehler gespiegelt. Der Service erzeugt
einen `FILE_RENAME`-Candidate über den bestehenden ADR-0065-Builder,
persistiert ihn insert-only und eröffnet genau ein
`ReviewType.EBOOK_OPERATION_RECIPE`-Item. Er erzeugt keine Reviewentscheidung,
keinen Plan und keine Authorization.

`ebook-rename-preview` ist die einzige neue lokale Planungsansicht, die mit
dem ausdrücklichen Opt-in `--private-details` Source- und Ziel-Locator relativ
zum ScanRoot zeigen darf. Absolute Pfade, Hashes und Capability-Inhalte
bleiben auch dort ausgeschlossen. Ohne dieses Flag gibt der Befehl nur opaque
IDs, Profile, Operationstyp, Counts, Reviewstatus und feste Blockercodes aus.

`ebook-rename-review` schreibt genau eine append-only Entscheidung für den
exakten Candidate. `ebook-rename-plan` reduziert ausschließlich die neueste
kompatible Entscheidung über den bestehenden reinen Planner und persistiert
den resultierenden Plan insert-only. Zielwahl während Authorize oder Execute,
freie Pfade, Glob, Rekursion, Batch und implizites „nächstes Element“ sind
ausgeschlossen.

Die opaque Dependency-Scope-ID wird über die owner-only geschützte lokale
`FOLIOTONE_EBOOK_RENAME_DEPENDENCY_SCOPES_FILE` auf genau einen ScanRoot und
alle fünf Achsen abgebildet. Für als verwaltet deklarierte Achsen leitet der
Proposal-Service den Zustand nur aus einem vollständigen aktuellen
persistierten Snapshot ab. Für ausdrücklich nicht verwendete Achsen darf die
versions- und konfigurationsgebundene Erklärung `NOT_APPLICABLE` liefern.
Vorhandene `KNOWN_PRESENT`-Evidence hat stets Vorrang. Fehlende Tabellenzeilen,
fehlende Konfiguration oder unvollständige Coverage ergeben `UNKNOWN`, niemals
stillschweigend `KNOWN_NONE` oder `NOT_APPLICABLE`.

Die Scope-Datei enthält keine Collection-Pfade oder freien Befehle. Ihr
Material-Fingerprint bindet Scope-ID, ScanRoot-ID, Profil, Version, die fünf
Achsen und die jeweils herangezogene Snapshot-Lineage. Dieselbe Scope-ID mit
geändertem Material macht Candidate und Plan stale. Die spätere Authorization
löst anhand der fünf gebundenen Dependency-Material-Fingerprints genau einen
passenden Scope erneut auf; kein oder mehr als ein Treffer blockiert. Eine
bloße frühere Reviewentscheidung konserviert keine veraltete Dependency-
Erklärung. RN01 verwendet dafür die bestehenden Recipe-Dependency-Zeilen und
benötigt keine neue Persistenztabelle.

RN01 konkretisiert die private Datei als JSON-Objekt mit genau dem Rootfeld
`dependency_scopes`. Jeder Eintrag enthält `dependency_scope_id`,
`scan_root_id`, das feste Profil, eine positive `version` und unter `axes`
genau die fünf kanonischen Dependency-Namen. Pro Datei sind Scope-ID und
ScanRoot-ID eindeutig. Eine Achse besitzt genau eine der beiden Formen:

```json
{"mode":"NOT_APPLICABLE"}
{"mode":"MANAGED","snapshot_kind":"TOOL_RESULT","snapshot_id":"UUID"}
```

Neben `TOOL_RESULT` sind `CALIBRE_SNAPSHOT` für Calibre-, Sidecar- und
External-Library-Coverage sowie `ARCHIVE_COLLECTION_RUN` für Archive- und
Volume-Group-Coverage zulässig. Nur ein vollständiger aktueller
`COMPLETED`-Snapshot ohne begrenzten oder fehlerhaften Archive-Plan kann
`KNOWN_NONE` liefern. Der FolioTone-eigene `TOOL_RESULT` muss das feste Profil
`ebook-rename-dependency-coverage/v1`, den exakten Observation- und
Achsenbezug, `COMPLETENESS_ANALYSIS`, erfolgreichen Abschluss und Confidence
eins besitzen. Ein fehlender, fremder, unvollständiger oder nicht aktueller
Snapshot wird als `UNKNOWN` materialisiert.

Aktuelle persistierte Calibre-Format-/Sidecar-, Archive-/Volume- und
Archive-Sidecar-Beziehungen sowie ein gültiges `KNOWN_PRESENT`-Coverage-
Resultat werden vor der Scope-Erklärung ausgewertet und überstimmen
`NOT_APPLICABLE`. Der Scope-Resolver liest höchstens 64 KiB, akzeptiert weder
Symlink noch Hardlink und verlangt unter Linux eine reguläre owner-only Datei
mit Modus `0600`. RN01 erzeugt solche Coverage nicht stillschweigend und
startet dafür weder Tool noch Scan.

## Zulässiger W9-Plan

Eine W10-Vorbereitung akzeptiert nur einen Plan, der alle folgenden
Bedingungen gleichzeitig erfüllt:

- `operation_kind = FILE_RENAME`;
- `status = APPROVED_NON_EXECUTABLE`, `execution_state = NOT_EXECUTABLE` und
  keine Blocker;
- genau eine `PRIMARY`-Source, keine Companion-Source;
- Source, Target und Plan gehören demselben `ScanRoot` und Parent an;
- Outputidentität ist `BYTE_IDENTICAL_TO_PRIMARY` mit exakt demselben Format,
  derselben Größe und demselben vollständigen SHA-256;
- Processor ist FolioTone-nativ und exakt
  `ebook-file-rename-linux-renameat2-noreplace/v1`;
- Collision ist `REQUIRE_TARGET_ABSENT`, Workspace ist `NOT_REQUIRED` und
  Recovery ist `REVERSE_RELOCATION`;
- alle fünf Dependency-Achsen `CALIBRE`, `SIDECAR`, `ARCHIVE`,
  `VOLUME_GROUP` und `EXTERNAL_LIBRARY` sind entweder durch vollständige
  aktuelle Evidence `KNOWN_NONE` oder durch den exakten aktuellen Dependency-
  Scope nachweislich `NOT_APPLICABLE`;
- Review-, Source-, Target-, Dependency-, Processor-, Recovery- und
  Verification-Lineage sind gegenüber dem content-addressed Plan unverändert;
- die Source ist die aktuelle Observation des neuesten abgeschlossenen
  book-only `ScanRun` und besitzt aktuelles `PRESENT` sowie einen
  vollständigen `FILE_SHA256`;
- die Target-Position ist physisch abwesend und es existiert für ihren
  relativen Locator noch kein historischer `FileRecord` desselben ScanRoots.

`KNOWN_PRESENT` und `UNKNOWN` blockieren v1 auf jeder Dependency-Achse.
`NOT_APPLICABLE` ist ausschließlich mit dem beschriebenen aktuellen
Dependency-Scope zulässig und darf keine vorhandene Beziehung überstimmen.
Damit verschiebt der Writer weder calibre-verwaltete Formate noch Sidecar-/
Archiv-/Volume-/externe-Library-Beziehungen, deren Folgewirkung dieser Slice
nicht beherrscht.

Das Verbot eines historischen Target-`FileRecord` ist absichtlich
konservativ. Der Folgescan kann dadurch den Source-Record eindeutig als
`MISSING` und einen neuen Target-Record als `NEW` abbilden. Die Wiederbelegung
eines historischen Slots und deren `REAPPEARED`-Semantik bleiben einem
späteren Profil vorbehalten.

## Basename- und Locatorvertrag

Der Source-Locator und der daraus erzeugte Target-Locator müssen bereits
exakt Unicode-NFC sein. Das ist für v1 verpflichtend, weil die bestehende
W9-Serialisierung Text für den Hash normalisiert, während SQLite den privaten
Locator roh erhält. Nicht normalisierte Bestandslocator werden nicht
stillschweigend umgeschrieben, sondern mit `LOCATOR_NOT_NFC` blockiert.

Der Target-Basename:

- ist genau eine UTF-8-/NFC-Komponente innerhalb der bestehenden Grenzen von
  255 Komponentenbytes und 1024 Locatorbytes;
- ist weder leer noch `.` oder `..` und enthält keinen Slash, Backslash,
  NUL- oder Steuerwert;
- besitzt weder führende oder abschließende Leerzeichen beziehungsweise
  Punkte noch das reservierte Präfix `.foliotone-`;
- verwendet nicht die portabilitätskritischen DOS-Namen `CON`, `PRN`, `AUX`,
  `NUL`, `COM1` bis `COM9` oder `LPT1` bis `LPT9` als case-insensitiven Stem;
- behält die letzte Dateiendung der Source exakt bei und gehört damit weiter
  zu `EPUB`, `MOBI`, `AZW`, `AZW3` oder `PDF`;
- unterscheidet sich vom Source-Basename sowohl bytegenau als auch nach
  Unicode-`casefold()`.

Case-only Rename, Suffixwechsel, Parentwechsel, Verzeichniserzeugung und
Normalisierung vorhandener Namen sind keine versteckten Unterfälle dieses
Profils.

## Private Capability und Runtime-Grenze

`FOLIOTONE_EBOOK_RENAME_CAPABILITIES_FILE` verweist auf eine owner-only
geschützte lokale Konfiguration. Eine opaque Capability-ID löst genau auf:

- eine exakte `ScanRoot`-ID und deren privates absolutes Rootverzeichnis;
- ein privates, nicht überlappendes Probeverzeichnis auf derselben lokalen
  Filesysteminstanz;
- `ebook-file-rename-capability/v1` und genau das feste Writerprofil;
- die unveränderliche Capability-Konfigurationsidentität.

Absolute Pfade und rohe Dateisystemkennungen werden weder in SQLite noch in
Reports persistiert. SQLite bindet sie ausschließlich über domänengetrennte
Einweg-Fingerprints. Root und Probe dürfen weder Datenbank-, Cache-, Tool-
Workspace- noch Repositoryverzeichnisse überdecken. Konfiguration und
Probeverzeichnis müssen dem ausführenden Benutzer gehören und dürfen nicht
gruppen- oder weltbeschreibbar sein. Das Root muss zum konfigurierten
ScanRoot passen; ein
fehlender, read-only, überlappender oder umgebogener Pfad ergibt
`TOOL_UNAVAILABLE`.

Die normale Scan-/Analyse-Runtime erhält aus dieser Konfiguration keine
Schreibrechte. Nur der konkrete Rename-Operator darf das Root für die Dauer
seiner einen Capability beschreibbar sehen. Die Capability autorisiert weder
Quarantäne, Metadatenwrite, Reorganisation, Delete noch externe Tools.

## Linux-Backend und Conformance

Der Backend-Slice ist Linux/Docker-only und verwendet eine fest geprüfte
x86_64-glibc-Systemcallgrenze. Caller können weder Syscallnummern, Flags noch
argv liefern. Der Capability-Probe muss auf Root und Probe dieselbe
Filesysteminstanz, einen unterstützten lokalen Typ aus `ext4`, `btrfs`, `xfs`
oder `tmpfs`, `openat2` und `renameat2(RENAME_NOREPLACE)` nachweisen. NFS,
CIFS/SMB, FUSE, Overlay-Dateisysteme, Remote-/Netzwerkdateisysteme,
Cross-Device-Ziele, unbekannte Typen und fehlende Directory-`fsync`-Semantik
werden abgewiesen. Es gibt keinen Fallback.

Der Probe verwendet ausschließlich neu erzeugte, zufällige und exklusiv
geöffnete Fixtures im privaten Probeverzeichnis. Er darf nur genau seine
eigenen gebundenen Probe-Fixtures umbenennen und entfernen; Source-Root,
Benutzerdaten und fremde Probeeinträge bleiben unberührt. Das Ergebnis bindet
Kernel-, Filesystem-, Backend- und Probeprofil sowie den Prüfzeitpunkt.

Die Root wird als Directory-FD geöffnet. Der Parent wird relativ dazu mit
`openat2` und exakt diesen Resolution-Flags aufgelöst:

```text
RESOLVE_BENEATH
RESOLVE_NO_SYMLINKS
RESOLVE_NO_MAGICLINKS
RESOLVE_NO_XDEV
```

Source und Target werden ausschließlich relativ zu demselben gehaltenen
Parent-FD adressiert. Die Source wird no-follow geöffnet und muss unmittelbar
vor der Mutation eine reguläre Datei mit Linkanzahl eins sein. Der Executor
bindet `st_dev`, `st_ino`, Größe, `mtime_ns`, Mode, Owner, Group, einen bounded
Xattr-Digest, Format und vollständigen SHA-256. Er prüft die Source-Namens-
Identität erneut über den Parent-FD und Target-Abwesenheit ohne Follow.

Nach `fsync` der Source führt genau ein Kernelaufruf aus:

```text
renameat2(parent_fd, source_basename, parent_fd, target_basename,
          RENAME_NOREPLACE)
```

Nach erfolgreichem Rename folgt `fsync(parent_fd)`; erst danach darf
`RELOCATED` persistiert werden. `EEXIST`, `EXDEV`, nicht unterstützte Flags,
Identity-Abweichung oder eine stale Fence brechen ohne alternativen Move ab.
Insbesondere sind `os.rename`, `os.replace`, Copy+Delete, Overwrite,
Shellbefehle, Calibre und ToolProvider kein Ersatzpfad.

Der bestehende Metadata-Write-Executor oder Quarantäne-Executor wird nicht
aufgerufen. Ein späterer Refactor darf nur die bereits geprüften internen
Low-level-`openat2`-/`renameat2`-Primitiven teilen; Capability, Planprüfung,
Journal, Recovery und Reconciliation bleiben operation-spezifisch.

## Threat Model und verbleibende Grenze

Der Vertrag schützt gegen stale Datenbankzustände, FolioTone-interne
Parallelwriter, Target-Collision, Symlink-/Magiclink-/Mount-Ausbruch,
Cross-Device-Fallback, Hardlink-Aliase, Authorization-Replay, Prozesscrash und
unvollständige Journalfortschreibung. Rootweite `ScanRootWriteLease`-Fences
serialisieren alle FolioTone-Writer.

Ein Prozess mit unabhängiger Schreibauthority auf demselben Verzeichnis kann
Linux-Namenseinträge zwischen Revalidierung und `renameat2` austauschen; Linux
bietet für `renameat2` keine „rename this already-open inode“-Variante. v1
setzt deshalb einen betrieblich exklusiven Writerzeitraum ohne fremde
Mutatoren voraus und verifiziert die tatsächlich verschobene Inode und Bytes
unmittelbar. Eine Abweichung wird niemals als Erfolg klassifiziert, kann aber
eine bereits erfolgte fremde Race nicht rückwirkend verhindern. Ein Root mit
nicht vertrauenswürdigen Mitautoren ist für diese Capability ungeeignet.

## Preparation, Authorization und Fencing

`ebook-rename-authorize` nimmt ausschließlich:

```text
--plan-id UUID
--plan-content-hash SHA256
--capability-id UUID
```

Unter einer neuen `EBOOK_RENAME_PREPARATION`-Lease revalidiert der Operator
den vollständigen W9-Plan, die neueste abgeschlossene Scan-/Observation-
Lineage, alle fünf Dependencies samt exakt gebundenem Dependency-Scope,
Capability/Probe, Sourceattribute und Sourcebytes sowie physische und
historische Target-Abwesenheit. Ein inzwischen geänderter oder nicht mehr
eindeutig auflösbarer Dependency-Scope blockiert. Unmittelbar vor dem Insert
werden Plan und Fence erneut atomar geprüft.

`EbookRenamePreparationSnapshot` bindet content-addressed Plan, Candidate,
Source/Target, private domänengetrennte Digests ihrer exakten UTF-8-Locators,
Source-Inode-/Attribut-/Hashzustand, Target-Abwesenheit, Dependency-Scope-/
Review-Lineage, Capability-/Backend-/Probeidentität und Fence. Die Raw-Locators
bleiben privat. Daraus entsteht eine höchstens 15 Minuten gültige
`EbookRenameAuthorizationSnapshot`; eine fehlgeschlagene Vorbereitung erzeugt
keine Authorization.

`ebook-rename-execute` verlangt dieselben drei Binder und zusätzlich:

```text
--authorization-id UUID
```

Unmittelbar vor Runerzeugung zeigt die CLI nur:

```text
CONFIRM EBOOK RENAME <Authorization-ID>
```

Sie akzeptiert genau eine begrenzte Zeile über nicht geloggtes `stdin`.
Persistiert wird nur ein domänengetrennter Digest, der Authorization, Plan-ID,
Plan-Content-Hash und Capability bindet. Fehlende oder abweichende Bestätigung
erzeugt keinen Run.

Der bestätigte `PREPARED`-Insert verbraucht die Authorization atomar und
bindet eine frische `EBOOK_RENAME_RUN`-Fence. Ein Retry einer verbrauchten
Authorization darf nur denselben Run fortsetzen oder auf Recovery verweisen;
er erzeugt nie eine zweite Rename-Operation.

## Journal und unmittelbare Verifikation

Ein `EbookRenameExecutionRun` besitzt ein gapless append-only Eventjournal mit
höchstens 16 Einträgen und ausschließlich diesen Zuständen:

```text
PREPARED
RELOCATED
IMMEDIATE_VERIFIED
RECOVERY_RELOCATED
RECOVERY_VERIFIED
SCAN_HANDOFF
VERIFIED
CANCELLED
RECOVERED
MANUAL_RECOVERY_REQUIRED
```

Nach dem einzigen `renameat2`-Aufruf wird `RELOCATED` nur unter der weiterhin
gehaltenen Fence ergänzt. Der Executor verlangt anschließend:

- Source-Name fehlt und Target-Name bezeichnet exakt dieselbe `st_dev`-/
  `st_ino`-Inode wie der vorab geöffnete Source-FD;
- Target ist regulär, Linkanzahl bleibt eins und die erlaubten Attribute
  einschließlich Größe und `mtime_ns` entsprechen dem Prepare-Snapshot;
- vollständiger SHA-256, Format und Größe entsprechen exakt der Source und
  dem erwarteten W9-Output;
- Parent-`fsync` war erfolgreich und Capability/Probe/Fence sind weiterhin
  gültig.

Nur dann entsteht `IMMEDIATE_VERIFIED`. Ein Dateiname oder eine gelungene
Kernelrückgabe allein ist kein Erfolgsnachweis.

## Feste Recovery-Matrix

`ebook-rename-recover --run-id UUID` löst ausschließlich die historisch
gebundene Capability und Source-/Target-Digests auf. Recovery nimmt keine
Pfade, Zielnamen oder neue fachliche Entscheidung entgegen.

| Letzter Zustand | Exakte physische Verteilung | Aktion |
|---|---|---|
| `PREPARED` | Source exakt, Target fehlt | `CANCELLED`; keine Mutation |
| `PREPARED` oder `RELOCATED` | Source fehlt, Target exakt | atomarer Reverse-Rename Target nach Source mit `RENAME_NOREPLACE`, Parent-`fsync`, danach `RECOVERY_RELOCATED` und vollständige Verifikation |
| `RELOCATED`, `RECOVERY_RELOCATED`, `RECOVERY_VERIFIED` oder `SCAN_HANDOFF` | Source exakt, Target fehlt | wiederhergestellte Source vollständig verifizieren, danach `RECOVERY_VERIFIED` beziehungsweise Scan-/Reconciliation fortsetzen |
| `IMMEDIATE_VERIFIED` oder `SCAN_HANDOFF` | Source fehlt, Target exakt | keine Umkehr; Folgescan und Forward-Reconciliation fortsetzen |
| beliebig vor terminal | beide vorhanden, beide fehlen, falscher Typ/Linkcount, unbekannte oder abweichende Inode/Bytes/Attribute, Source-Slot wiederbelegt oder Capability/Probe nicht sicher | keine Mutation; `MANUAL_RECOVERY_REQUIRED` |
| `VERIFIED`, `CANCELLED` oder `RECOVERED` | beliebig | idempotent terminal; keine weitere Mutation |

Der Reverse-Rename ist Teil derselben noch nicht erfolgreich abgeschlossenen
Operation und nur vor `IMMEDIATE_VERIFIED` erlaubt. Ist der Source-Slot in der
Zwischenzeit belegt, verhindert `RENAME_NOREPLACE` jedes Überschreiben. Nach
`VERIFIED` ist diese Authorization irreversibel; ein später gewünschter
Rename zurück benötigt einen neuen Candidate, Review, Plan und eine neue
Authorization.

`RECOVERY_VERIFIED` ist noch nicht terminal. Danach folgt derselbe explizite
Lease-Handoff zu einem neuen Scan. Nur eine passende immutable Recovery-
Reconciliation darf atomar das terminale `RECOVERED` erzeugen.

## Scan, FileRecord-Identität und Reconciliation

Nach `IMMEDIATE_VERIFIED` persistiert der Operator `SCAN_HANDOFF`, gibt die
`EBOOK_RENAME_RUN`-Lease ausdrücklich frei und startet einen neuen
vollständigen, inkrementell wiederverwendenden Scan mit einem Hash-Worker. Für
den Forward-Erfolg muss der Scan `COMPLETED` sein und belegt:

- der alte Source-`FileRecord` besitzt eine neue `MISSING`-Observation;
- für den historisch unbenutzten Target-Locator entstand ein eigener neuer
  `FileRecord` mit `NEW` und aktuellem `PRESENT`;
- Target-Observation, Größe und vollständiger SHA-256 entsprechen dem
  autorisierten Output.

Der Rename schreibt oder vereinigt keine `FileRecord`-Identität. Ein optional
entstehender `FileRelocationCandidate` bleibt heuristische Evidence und ist
weder Voraussetzung noch Ersatz für die ausgeführte Run-Lineage.

Nach `RECOVERY_VERIFIED` muss der Folgescan stattdessen denselben alten
Source-`FileRecord` wieder als aktuelles `PRESENT` mit exakter Original-
Byteidentität und einen weiterhin physisch sowie historisch abwesenden
Target-Slot belegen. Er erzeugt keinen erfundenen Target-`FileRecord`.

Aus dem neuen Scan entsteht ein `collection-state/v1`. Pfadabhängige
Analysis-, Resolution-, Classification-, Matching-, Review-, Calibre-,
Archive- und Plan-Evidence wird gemäß ihren bestehenden Profilen als
`CURRENT`, `STALE`, `UNSCOPED` oder `MISSING` projiziert. Dieser Slice startet
keine unbeschränkte automatische Vollanalyse.

Anschließend erwirbt derselbe Run eine frische `EBOOK_RENAME_RUN`-Fence,
revalidiert Target und Plan erneut und persistiert atomar einen immutable
`EbookRenameReconciliationSnapshot` plus das zum Outcome passende terminale
Event. Für `VERIFIED` bindet der Snapshot Run, alten Source-FileRecord und
dessen letzte `PRESENT`-/neue `MISSING`-Observation sowie den neuen Target-
FileRecord und dessen `NEW`-Observation. Für `RECOVERED` bindet er den alten
Source-FileRecord, seine neue aktuelle `PRESENT`-Observation und den
historisch weiterhin freien Target-Slot. Beide Outcomes binden neuen
`ScanRun`, `CollectionState`, erwartete Bytes, privaten Physical-Digest und
content-addressed Reconciliation-Digest. Ein passender bereits abgeschlossener
Folgescan darf nach Crash wiederverwendet werden; ein älterer oder abweichender
Scan nicht.

## Privacy und Produktoberflächen

Standard-Text, JSON, Status, Logs und Fehler enthalten ausschließlich opaque
IDs, Profile, Zustände, Zeitpunkte, Counts und feste Fehler-/Blockercodes.
Ausgeschlossen bleiben absolute und relative Locator, Basenames, Hashes,
Inodes, Attribute, Capability-Inhalte, Fences, Confirmation- und private
Physical-Digests. Nur die ausdrücklich lokale Planungsansicht
`ebook-rename-preview --private-details` darf relative Source-/Ziel-Locators
zeigen.

REST-API und grafische Oberfläche bleiben bis FUT-011 geschlossen. Spätere
Adapter dürfen ausschließlich dieselben Application-Commands und -Queries
aufrufen und erhalten keine zusätzliche Mutation Authority. Andere
Medienlinien besitzen später eigene Menü- und Capability-Einstiege.

## Lieferpakete

Die Implementierung folgt in genau vier kleinen Waves:

1. `S-W10-RN01` ergänzt Proposal, private Preview, append-only Review und
   Planreduktion auf dem bestehenden W9-Store. Keine Capability und keine
   Source-Mutation.
2. `S-W10-RN02` implementiert reine Preparation-/Authorization-/Run-/Event-
   Verträge, private Capability/Probe-Auflösung, additive insert-only
   Persistenz über `0031_ebook_rename_operations`, neue Lease-Owner und
   read-only Status. Kein Executor.
3. `S-W10-RN03` implementiert das feste Linux-Backend, genau einen gefenceten
   Rename, unmittelbare Verifikation und die Exact-State-Recovery. Keine CLI.
4. `S-W10-RN04` ergänzt Authorize/Execute/Recover/Status, zweite Bestätigung,
   Lease-Handoff, Scan, `CollectionState` und immutable Reconciliation über
   `0032_ebook_rename_reconciliation`.

Nach jeder Wave bleiben andere Operationsarten unerreichbar. RN01 und RN02
sind umgesetzt; RN03 ist die nächste kanonische Produkt-Wave. RN02 öffnet
weder einen Executor noch eine öffentliche Mutationsoberfläche.

## Synthetische Verifikation

Kein Test benötigt reale E-Books. Minimal generierte EPUB-, MOBI-, AZW-,
AZW3- und PDF-Bytes sowie temporäre SQLite-Datenbanken prüfen gezielt:

- Plan-/Dependency-/Review-/Locator-/Target-History-Blocker;
- Unicode-, Case-, Suffix-, Komponenten-, Reserved-Name- und Parent-Grenzen;
- Capability-Schema, Berechtigungen, Root-/Probe-Nonoverlap und Privacy;
- fehlendes `openat2`/`renameat2`, ungeeignete Filesysteme, `EEXIST`, `EXDEV`,
  Symlink-, Mount-, Hardlink-, Inode- und Attributwechsel;
- Crash vor und nach `renameat2`, `fsync`, jedem Journalereignis, Lease-
  Handoff, Scan und Reconciliation;
- Authorization-Replay, stale Fence, Recovery-Matrix und idempotente Retries;
- getrennte alte/neue `FileRecord`-Identität, `MISSING`/`NEW`,
  `CollectionState`-Staleness und Standardausgabe-Redaction.

Lokale Prüfungen bleiben pro Wave auf den betroffenen Scope begrenzt. Nur der
stabile PR-Head erhält genau einen vollständigen CI-Gate. Reale private Daten,
private Collection-Roots, Docker und externe Tools sind kein Entwicklungs-Gate.

## Geprüfte Primärquellen

Die Entscheidung wurde am 2026-08-23 gegen folgende Primärquellen geprüft:

- Linux man-pages, `rename(2)` / `renameat2(2)`:
  https://man7.org/linux/man-pages/man2/renameat2.2.html
- Linux man-pages, `openat2(2)`:
  https://man7.org/linux/man-pages/man2/openat2.2.html
- Linux man-pages, `fsync(2)`:
  https://man7.org/linux/man-pages/man2/fsync.2.html
- Python-3.14-`os`-Dokumentation:
  https://docs.python.org/3/library/os.html
- SQLite, Atomic Commit:
  https://www.sqlite.org/atomiccommit.html

`os.rename` wurde nicht gewählt, weil es auf Unix ein bestehendes Ziel still
ersetzen kann. `RENAME_NOREPLACE` liefert die benötigte atomare
Target-Abwesenheitsbedingung, bleibt aber von Kernel und Filesystem abhängig.
Directory-`fsync` ist notwendig, weil File-`fsync` allein den geänderten
Verzeichniseintrag nicht dauerhaft macht. SQLite-Atomizität ersetzt kein
Dateisystemjournal.

## Folgen

- RN01 liefert den nutzbaren, vollständig nicht mutierenden Rename-
  Planungsweg; RN02 ergänzt dessen nicht ausführende Authority- und
  Persistenzschicht.
- Der spätere Writer verändert genau einen Namen und keine Bytes, Metadaten,
  Parentstruktur oder externe Library.
- Reorganisation bleibt sichtbar geplant, wird aber nicht über eine zu breite
  Rename-Capability eingeschleust.
- Der Scan bewahrt das bestehende pfadgebundene `FileRecord`-Modell; die
  operationseigene Reconciliation erklärt den Übergang ohne Identity-Merge.
- Linux/Docker und ein explizit geeignetes lokales Filesystem sind bewusste
  Runtime-Voraussetzungen. Native Windows-, Netzwerk- und ungeprüfte
  Filesystempfade bleiben `TOOL_UNAVAILABLE`.
- Ein feindlicher externer Parallelwriter ist eine dokumentierte Restgrenze
  und kein durch Fencing vorgetäuschtes gelöstes Problem.
