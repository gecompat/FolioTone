# Safety and Non-Destructive Operation

## Baseline

W0 bis W9 behandeln Source Collections als Evidence und nicht als
beschreibbaren Workspace. ADR-0061 erlaubt die kontrollierte Entwicklung der
E-Book-Schreibstrecke mit synthetischen Fixtures. Eine reale W10-Mutation
bleibt trotzdem an einen eigenen technischen Operationsvertrag, eine lokale
Capability und eine kurzlebige Authorization gebunden.

## Enforced W0–W9 invariants

- source media mounts are read-only in the standard container configuration;
- no source-media delete command exists;
- no source-media move or rename command exists;
- no general metadata-write command exists; the sole source-metadata exception
  is the ADR-0063/ADR-0064 EPUB-3 `title`-`REPLACE` operator;
- no Calibre write adapter exists;
- external enrichment does not write back to source media;
- external ToolProviders may use only analysis-safe operations against source media;
- W9 consolidation and metadata-correction plans are data records only and
  remain permanently `NOT_EXECUTABLE`.

## External tool safety

A third-party tool can expose dangerous operations even when FolioTone itself contains no write command. Tool integration therefore inherits the same W0-W9 safety gate.

Rules:

- prefer read-only media mounts for external tool containers/jobs;
- prefer status/report/scan/probe/preview operations;
- do not invoke delete, move, rename, retag, metadata-write or other source-mutating commands;
- do not assume a tool is safe merely because it is popular or trusted;
- record the tool version and operation used for material evidence;
- treat external tool output as evidence, not automatic destructive authority;
- isolate temporary work/output from source media where conversion or extraction requires writable storage;
- validate paths/mounts before launching a ToolProvider job;
- never pass credentials through command arguments when a safer secret/config mechanism exists;
- do not expose tool web interfaces to untrusted networks by default.

Examples: beets, SongKong, calibre and Picard all have workflows capable of changing media/library state; these write-capable functions remain unauthorized through W9.

## Archive- und Secret-Sicherheit

ADR-0038 ist der bindende Vertrag für Archive. Archive sind Container-
Evidence und nicht automatisch Duplikate. Listing geht jedem Integritätstest
und jeder späteren Extraktion voraus. Source-Archive bleiben read-only;
Extraktion darf ausschließlich in einem neuen privaten, begrenzten Workspace
außerhalb jedes `ScanRoot` erfolgen.

Die gewählte 7-Zip-26.02-CLI wird nur über feste read-only Command Shapes
verwendet. Ihre dokumentierte Passwortoption würde das Secret in argv
offenlegen und ist daher verboten. Bis ein separates Frontier-Gate einen
isolierten Helper-/Pipe-Kanal technisch belegt, endet jede reale
Passwortanforderung mit `SECURE_CHANNEL_UNAVAILABLE`. Secretmaterial darf
weder Persistenz, `ToolArtifact`, `ToolResult`, Cache, Exception, `repr`, Log,
stdout/stderr, argv noch Environment erreichen.

Da 7-Zip-Listing Containerkommentare mit Secretmaterial ausgeben kann, darf
die bestehende Raw-stdout/stderr-Persistenz der `ToolRuntime` nicht verwendet
werden. ADR-0039 akzeptiert für unverschlüsselte Archive eine separate
`ArchiveProcessRunner`-Grenze. Sie verarbeitet stdout unmittelbar mit einem
begrenzten Streaming-Parser. stderr wird begrenzt und unverändert verworfen;
weder Prosa noch grobe 7-Zip-Exitcodes sind Ursachen-Authority. Ein nicht
strukturierter Fehler wird ausschließlich `TOOL_FAILED`. Preview, Raw
Artifact, Raw Log und eine frei übernommene Host-Environment sind verboten.

ADR-0045 verlangte vor einem Produktionslock die vollständige Fallmatrix.
S-EBAR-02B2 bindet Directory-, Encryption- und positive Linkfälle geschlossen
als `MEASURED`, `FORMAT_UNSUPPORTED` oder `EVIDENCE_UNAVAILABLE`. ADR-0046
trennt Publication Kind, direkte Storage Family und äußere Kompression
orthogonal. ADR-0047 akzeptiert ausschließlich darauf den kanonischen
`archive-7zip-format-lock/v1`; jede Identitäts-, Feldordnungs-, Value-Class-
oder Capabilityabweichung ist stale und fail-closed. Suffixe dürfen keine
Storage-Familie setzen; 7-Zip-Ausgabe darf sie nicht umklassifizieren. Private
Linkziele dürfen nie DTO, Manifest, Digest, Log oder Artefakt erreichen.
ADR-0051 und S-EBAR-W01 bis S-EBAR-W04 schließen für gzip, bzip2, xz und zstd
ausschließlich eine bounded read-only Streamingstrecke ab. Die
Source-Beobachtung bleibt `OUTER_COMPRESSION_ONLY` und Storage `UNKNOWN`;
private innere TAR-Evidence darf sie nicht umschreiben. Ein inkrementeller
512-Byte-Rahmenprüfer muss Headerchecksumme, Größen, Padding, mindestens zwei
Nullblöcke und ausschließlich nullhaltigen Nachlauf beweisen. Listing und
Integrity dekomprimieren getrennt und müssen identische innere Bytelänge und
SHA-256 liefern. Rawstreams werden nie gespeichert. Extraction,
Extraction-Handoff, Persistenz und Schreiboperationen bleiben gesperrt.

Die unverschlüsselte Runtime setzt die ADR-0038-Limits während der Ausführung
durch und beendet bei Timeout oder Grenzverletzung den vollständigen
Prozessbaum. `archive-linux-container-runner/v1` ist der erste freigegebene
Backendvertrag. Er startet in der primären Docker/Linux-Runtime ausschließlich
ein digest-gepinntes Image mit verifizierter eingebetteter `7zzs`-26.02-Identität:
non-root, `network=none`, read-only Root-Filesystem, alle Capabilities entfernt,
no-new-privileges, Default-oder-strengeres Seccomp, ohne Devices und mit festen
PID-, RAM-, CPU- und Laufzeitgrenzen. Timeout und Cancellation erzwingen Kill
und Entfernung des gesamten Containers.

FG-A-IMAGE ist durch ADR-0040 akzeptiert. Das projekt-eigene Runtime-Image
verwendet für genau `linux/amd64` den leeren, nicht pullbaren
`FROM scratch`-Ausgangspunkt, den unveränderten offiziellen statischen `7zzs`-26.02-Tar-Member
mit festem SHA-256, vollständige Lizenzhinweise und den numerischen User
`65532:65532`. Der Upstream-Release ist nicht unabhängig signiert; die
FolioTone-Attestation ersetzt diesen fehlenden Nachweis nicht.

S-EBAR-03 baut das Image zweimal offline mit identischen Inputs und fixiert den
beobachteten identischen `linux/amd64`-Plattform-Manifest-Digest mit dem fest
gepinnten Buildx-/BuildKit-Profil in `archive-image-lock/v1`. Die
Runtime-Builds enthalten keine Inline-Attestations; erst nach dem geschützten
Post-Merge-Publish werden SBOM und das in ADR-0040 festgelegte SLSA-v1-
Custom-Predicate an den gelockten Digest angehängt. Das GHCR-Package muss
explizit öffentlich und mit `gecompat/FolioTone` source-associated sein, und
ein vollständig anonymer Manifest-by-Digest-Abruf muss den gelockten Digest
bestätigen. Der Abruf hat keine Benutzer- oder Registry-Credentials und
verwendet ausschließlich den in ADR-0040 begrenzten, credentialfreien
Registry-v2-Bearer-Flow; ein Bearer ist weder Credential-Fallback noch
persistier- oder logbar. Ein fehlender oder abweichender Digest, ein dynamisch
abhängiges ELF, unvollständige Lizenzhinweise, eine fehlende Attestation oder
eine fehlgeschlagene anonyme Verifikation ergeben fail-closed
`TOOL_UNAVAILABLE`.

ADR-0041 akzeptiert FG-A-RUNTIME-AVAILABILITY; S-EBAR-03A hat diese Grenze vor
EBAR-04 umgesetzt. `BOOTSTRAP_LOCKED`, lokales Docker Image Inspect
oder eine erfolgreiche `7zzs i`-Probe sind einzeln und gemeinsam keine
Runtime-Authority. Erst ein reviewter `archive-runtime-release/v1`-Record in
der vertrauenswürdigen FolioTone-Source bindet den exakten Manifestdigest,
Custom-SLSA-/SPDX-Bundles, GitHub-Workflowidentity, Trust-Root-Snapshot und
Revocation-Generation. Ein ungepinntes `gh` ist keine Runtime-Trust-Root.

Die explizite Erstprovisionierung prüft Public Visibility und Source-
Association, übernimmt die exakt gehashten Evidence-Bytes, validiert das
lokale OCI-Layout vollständig und erzeugt erst danach atomar einen privaten
lokalen State. Jeder Containerstart prüft ohne Netzwerk erneut Release-
Record, Evidence-Hashes, State, Revocation, höchstens 90 Tage Offline-
Gültigkeit, den vollständigen OCI-Vertrag sowie Docker Config und geordnete
RootFS-`diff_id`-Werte. Missing oder beschädigter State, eine rückläufige
Release-/Revocation-Generation, Clock Rollback, Ablauf, Denylist-Treffer oder
eine Identity-Abweichung ergeben vor Toolstart `TOOL_UNAVAILABLE`. Public
Visibility und Source-Association sind Provisioning-/Refresh-Gates und werden
nicht bei jedem Lauf über das Netzwerk abgefragt.

Offline kann eine nach dem letzten Refresh extern veröffentlichte Revocation
nicht erkannt werden. Das 90-Tage-Fenster begrenzt dieses Restrisiko; nach
Ablauf ist ein Refresh erforderlich. Die Regeln behaupten keinen TPM- oder
Hardware-Antirollback-Schutz. Ein lokaler Administrator, der Programm,
Image-Store, Clock und Trust-State gemeinsam manipuliert, bleibt außerhalb der
v1-Sicherheitsgrenze.

Die tatsächliche Source und jeder ScanRoot werden niemals gemountet. Eine
bereits vollständig validierte Volumegruppe wird in ein opaque privates
Temp-Staging kopiert, vor und nach der Kopie gegen Source-Observation, Bytes
und vollständige Hashes geprüft und ausschließlich read-only gemountet. Der
Preflight weist no-follow nach, verbietet Links/Junctions/Reparse Points sowie
Devices und verlangt container-sichtbar `65532:65532`, Modus `0500` für Input-
Verzeichnisse und `0400` für Input-Dateien. Ein neu erzeugter leerer Output-
Workspace mit Owner `65532:65532` und Modus `0700` ist der einzige read-write
Mount. Zusätzliche ACL-Rechte oder eine nicht beweisbare Bind-Projektion
beenden den Auftrag vor Toolstart mit `TOOL_UNAVAILABLE`. Listing,
Integritätstest und private Extraktion besitzen getrennte `ToolExecution`-
Provenance.

ADR-0048 ergänzt vor EBAR-06 fünf verpflichtende Schritte. S-EBAR-05A erhält
private Memberlocator und CRC-Werte ausschließlich als redigierten
In-Memory-Handoff desselben Listing-/Integrity-Laufs. S-EBAR-06A implementiert
den exakten underscore-internen, reinen Extraction-Validator ohne Tool- oder
Filesystemzugriff. FG-A-EXTRACTION-QUOTA muss danach einen harten, atomar
durchgesetzten, plattformneutral beschriebenen Workspace-Cap für Gesamtbytes,
Member und Reserve
akzeptieren; Polling allein ist dafür kein Sicherheitsbeweis. S-EBAR-04Q
implementiert danach den exakt entschiedenen neutralen Provider- und
Capability-Vertrag. Erst ein reales Adaptergate und danach S-EBAR-04A
erweitern den Runner um einen nicht öffentlichen
Workspace-Consumer-Lifecycle.
Der Runner
beweist zuerst die Container-Abwesenheit, leiht danach eine opaque no-follow-
Workspace-Capability synchron an den exakten internen Consumer und invalidiert
sie unmittelbar nach dem Callback. Der Consumer revalidiert Member, Pfade,
Typen, Größen, CRC und TOCTOU und hasht reguläre Dateien bounded. Nur der
Runner bereinigt Input und Output. Danach muss S-EBAR-04Q den leeren Slot
erneut beweisen und erfolgreich zurücknehmen; erst dann wird die vorläufige
Evidence freigegeben. Cleanup-, Container-Absence-, Slot-Revalidation- oder
Returnfehler werden `TOOL_FAILED`, verwerfen alle Teilwerte und
quarantänisieren den Slot statt ihn wiederzuverwenden.

Während Extraction darf Polling Memberzahl, Einzel- und Gesamtgröße,
Workspacegröße und freien Reserveplatz nur als zusätzlichen Frühabbruch
überwachen. Ein gelatchter Limitbefund beendet den Prozessbaum über die
bestehende Cancellation-/Kill-Grenze und wird danach `LIMIT_EXCEEDED`;
`RLIMIT_FSIZE` begrenzt zusätzlich jedes einzelne Output-Member. Der harte
Gesamtbudgetnachweis muss aus dem akzeptierten FG-A-EXTRACTION-QUOTA-Vertrag
stammen und Überschreitungen zwischen zwei Scans verhindern. ADR-0049
akzeptiert dafür eine dateisystemneutrale, atomar begrenzte
Workspace-Capability. Nutzbare Bytes, Objektzahl und Reserve müssen durch den
jeweiligen Plattformadapter unabhängig von Polling erzwungen werden.
S-EBAR-04Q implementiert nur den neutralen Provider-, Lease-, Capability-,
Return- und Quarantänevertrag. Ein konkretes Dateisystem, Volume- oder
Quota-Backend wird ausschließlich in einem separaten Adaptergate akzeptiert.
FolioTone erhält keine Host-Capability. Kann ein Adapter harten Cap,
Live-Abbruch, no-follow-Revalidierung oder Cleanup nicht belegen, bleibt
Extraction `TOOL_UNAVAILABLE`.

[ADR-0050](../decisions/ADR-0050-linux-docker-workspace-backend-unavailable.md)
belegt für die aktuelle Linux-/Docker-Grenze keinen vollständigen Adapter:
Bind-Mount, Docker-Layer, `tmpfs` und nicht konkret live attestierte Linux-
Quota erfüllen Byte-, Objekt-, Reserve- und Consumer-Lifecycle nicht gemeinsam.
Die Adapter-Allowlist bleibt daher leer. ext4, NTFS, Btrfs, XFS und FIEMAP
sind keine allgemeine Projektvoraussetzung. Ein späterer Adapter darf lokale
Backend-Eigenschaften nur hinter einem eigenen Capability-/Conformance-Gate
verwenden und muss jede fehlende Live-Attestation fail-closed behandeln.

Native Windows-Ausführung bleibt `TOOL_UNAVAILABLE`, bis
`FG-A-WINDOWS-SANDBOX` Netzwerk- und Filesystemisolation belegt. Job Objects
und explizite Handle-Allowlists begrenzen diese Zugriffe nicht und sind allein
keine Sandbox.

Diese Runtime-Freigabe umfasst keinen Secret-Kanal. Reale Passwortversuche
bleiben bis FG-A-SECRET `SECURE_CHANNEL_UNAVAILABLE`. Der vorhandene
7-Zip-CLI-Adapter darf niemals `-p` verwenden. stdin-, PTY-, argv- und
Environment-Workarounds bleiben ausgeschlossen.

`archive-safety-policy/v1` begrenzt Member, Bytes, Ratio, Pfade, Laufzeiten,
Ausgaben und Parallelität. Traversal, absolute/Device-/ADS-Pfade, normalisierte
Zielkollisionen, Symlinks, Reparse Points, Hardlinks, FIFOs, Sockets und
Devices werden vor einer Extraktion abgewiesen. Nested Archive Processing ist
im v1-Profil deaktiviert. W10, Quarantäne, Purge und Empty-Directory-Cleanup
bleiben davon unberührt gesperrt.

## External lookup privacy

External knowledge can improve identification, but network use must not silently disclose unnecessary collection context.

Rules:

- never send absolute local paths to external providers;
- prefer structured identifiers/candidate fields over raw filenames;
- transmit only the minimum fields required for a lookup;
- use provider cache/local datasets to avoid unnecessary repeated disclosure;
- keep API keys and credentials outside Git;
- generic web/AI research creates candidates/evidence, not automatic destructive authority;
- ordinary local scanning/analysis must remain useful with external providers disabled.

## W10 requirements

ADR-0061 entfernt die fehlende Owner-Freigabe für die Entwicklung weiterer
E-Book-Writer. Sie ist kein globaler Runtime-Schalter und keine konkrete
Ausführungs-Authorization. Solange die eigene technische ADR und die
vollständige Bedien-/Recoverykette eines Operationstyps fehlen, bleibt dieser
Writer operativ nicht verfügbar.

ADR-0056 öffnet die Vertragsschicht für eine gefencete Ein-Datei-Quarantäne.
S-W10-01 und S-W10-02 bleiben mutationsfrei. Der eng begrenzte S-W10-03-
Interim-Executor darf ausschließlich `os.rename` im selben vom Betriebssystem
gemeldeten Filesystem nach Ziel-Abwesenheitsprüfung und vollständiger SHA-256-
Revalidierung verwenden. Er behauptet keine atomare No-Replace-Semantik.
`FG-W10-MOVE-BACKEND` bleibt verpflichtend für den späteren atomaren
No-Replace-Move, no-follow sowie Race-/Crash-Nachweise ohne Copy+Delete-
Fallback. Purge, Calibrewrite und Verzeichnisbereinigung bleiben blockiert.

`S-W10-05A` bis `S-W10-05C` öffnen ausschließlich die feste Bedienkette bis
zum Interim-Execute. Die private Capability bleibt außerhalb von argv,
SQLite und Reports. Authorize revalidiert beide Dateien read-only. Execute
fordert Authorization- und Plan-ID exakt über begrenztes, nicht geloggtes
`stdin`, löst Capability und aktuelle Lineage erneut auf und verbraucht die
Authorization genau einmal beim gefenceten `PREPARED`-Insert. Nur danach darf
der vorhandene Interim-Executor aufgerufen werden. Ein Retry verwendet keine
verbrauchte Authorization; bis `S-W10-05D` muss jeder nicht abgeschlossene Run
ohne weitere Mutation bei read-only Status und manueller Untersuchung stoppen.

ADR-0063 entscheidet die technische Grenze des ersten Source-Metadata-Writers
ausschließlich für EPUB 3, `SOURCE_METADATA` und genau einen reviewten
`title`-`REPLACE`. Der Writer patcht im privaten Staging nur `dc:title` und
das formatbedingt aktualisierte `dcterms:modified`; alle übrigen Package-
Document-Bytes und alle Nicht-Package-Entry-Inhalte müssen erhalten bleiben.
Der Linux-Commit tauscht vorbereiteten Output und Source nur über
`renameat2(RENAME_EXCHANGE)` und bewahrt das herausgetauschte Original per
`RENAME_NOREPLACE` im capability-gebundenen Same-Filesystem-Recoverybereich.
Es gibt keinen Copy+Delete-, Overwrite- oder Cross-Volume-Fallback. ADR-0064
öffnet ausschließlich die vollständige Bedien- und Reconciliation-Kette
dieses Profils; andere Felder, Formate, Zielträger und Writer bleiben gesperrt.

`S-W10-MW01` schwächt diese Grenze nicht. Das Paket
`foliotone.metadata_write` nimmt ausschließlich einen immutable Plan,
gebundene Conformance-Evidence und EPUB-Bytes entgegen. Es prüft und erzeugt
immutable DTOs und Bytes, besitzt aber keine Pfad-, Dateischreib-,
Persistenz-, Tool-, Netzwerk-, CLI-, Capability-, Authorization- oder
Execute-Schnittstelle. Ein erfolgreicher `EpubTitleArchiveDiff` ist deshalb
nur Staging-Evidence und keine Mutationsfreigabe.

`S-W10-MW02` ergänzt ausschließlich private Staging-Dateien und unabhängige
Validatoren. `S-W10-MW03` ergänzt die content-addressed Preparation/
Authorization, private Capability-Auflösung, gefencete insert-only Run-/
Eventpersistenz und einen read-only Status. Die Capability-Pfade bleiben
außerhalb von SQLite und Standardreports. `S-W10-MW04` implementiert den eng
begrenzten internen Linux-Commit und dessen Recovery auf synthetischen
Filesystemen. Das Backend verlangt Linux x86_64 mit glibc, feste no-follow
Directory-FDs, eine erlaubte lokale Same-Filesystem-Instanz, einen erfolgreichen
persistenten `RENAME_EXCHANGE`-/`RENAME_NOREPLACE`-Probevertrag sowie reguläre
owner-eigene Source-Dateien ohne weitere Links, Special Bits oder xattrs.
Unmittelbar vor dem Exchange werden gültige Authorization, aktuelle Plan-/
Review-/File-Lineage, Backend-Binding, Full-SHA-256 und Root-Fence erneut
geprüft. Recovery ignoriert Ablauf oder spätere fachliche Änderungen nur, um
unter einer neuen Fence die exakten Originalbytes derselben bereits begonnenen
Operation wiederherzustellen. Uneindeutige Zustände werden nicht weiter
mutiert. Delete, Copy+Delete, Overwrite, Cross-Volume, Cleanup und ein
caller-gesteuerter Rename bleiben ausgeschlossen.

MW04 endet intern bei `ORIGINAL_PRESERVED`. `S-W10-MW05` ergänzt die einzige
feste Authorize-/Execute-/Recover-/Status-CLI, eine exakte zweite Bestätigung
über nicht geloggtes `stdin`, unmittelbare physische und semantische
Verifikation sowie einen expliziten Lease-Handoff. Erst ein neuer
`COMPLETED`-Scan, die neue Observation, ein passender `CollectionState`, eine
frische physische Revalidierung und der atomare Reconciliation-Insert dürfen
`VERIFIED` erzeugen. Recovery durchläuft dieselbe Reconciliation und endet
ohne `VERIFIED` bei `RECOVERED`.

ADR-0066 entscheidet davon getrennt ausschließlich einen byte-identischen
`FILE_RENAME` auf einen historisch unbenutzten Basename im selben vorhandenen
Parent. Fünf Dependency-Achsen müssen durch aktuelle Coverage `KNOWN_NONE`
oder über einen expliziten aktuellen Scope nachweislich `NOT_APPLICABLE` sein;
`KNOWN_PRESENT`, `UNKNOWN` und bloß fehlende Daten blockieren. Source und Target
müssen bereits NFC-kanonisch, casefold-verschieden und unter der festen
Basename-/Suffixgrenze liegen. Eine private Capability autorisiert genau
diesen ScanRoot und Writer. Das Linux-Backend löst den Parent mit `openat2`
beneath/no-follow/no-xdev auf und verwendet genau ein
`renameat2(RENAME_NOREPLACE)` relativ zu demselben Directory-FD. `os.rename`,
Copy+Delete, Overwrite, Cross-Device, Shell und ToolProvider sind keine
Fallbacks. Ein externer Prozess mit eigener Schreibauthority bleibt eine
explizite betriebliche Restgrenze und darf während der Operation nicht
parallel mutieren.

`S-W10-RN01` ist vollständig nicht mutierend umgesetzt. Der Ziel-Basename
kommt ausschließlich als eine begrenzte, nicht zurückgespiegelte `stdin`-
Zeile herein; Proposal, append-only Review und Plan schreiben nur in die
bestehende SQLite-Persistenz. Standardausgaben bleiben Locator-, Pfad- und
Hash-frei; relative Source-/Target-Locators zeigt ausschließlich
`ebook-rename-preview --private-details --output text`. RN02 ergänzt
Authority, Capability, erfolgreichen persistenten Probe, Fencing, One-use-
Run, insert-only Journal und read-only Status. RN03 ergänzt den internen
Raw-`openat2`-/`renameat2(RENAME_NOREPLACE)`-Executor, bounded Xattr-Bindung,
unmittelbare Verifikation und feste Exact-State-Recovery. RN04 stellt jetzt
ausschließlich `ebook-rename-authorize`, `ebook-rename-execute`,
`ebook-rename-recover` und den SQLite-read-only
`ebook-rename-status` bereit. Vor `IMMEDIATE_VERIFIED` darf Recovery
ausschließlich den atomaren Reverse-Rename versuchen. Danach wird nur vorwärts
reconciled. Vor dem Folgescan wird die Run-Lease explizit freigegeben; der
Scan verwendet Full-SHA-256 und genau einen Worker. Eine frische Run-Fence
bindet anschließend physischen Zustand, Scan-Evidence, `CollectionState`,
immutable Reconciliation und Terminalstatus atomar. Uneindeutigkeit endet
bei `MANUAL_RECOVERY_REQUIRED`; der Folgescan vereinigt keine `FileRecord`-
Identitäten. Parentwechsel bleiben hinter `FG-W10-REORGANIZE`, REST/API/UI
hinter FUT-011.

Ein ausführbarer Consolidation-Teil darf nicht lediglich durch einen CLI-
Schalter aktiviert werden. Er benötigt weiterhin mindestens:

1. dry-run/plan representation;
2. explicit operation approval;
3. source precondition validation immediately before mutation;
4. changed-since-analysis protection;
5. collision handling;
6. audit logging;
7. clear partial-failure semantics;
8. tests on temporary synthetic filesystems;
9. a design for recovery/rollback where feasible;
10. no implicit deletion based on one signal, one tool/provider result, one AI/web inference or one score;
11. separate authorization rules for FolioTone-native operations and write-capable ToolProvider operations.

## Persistence und operation-spezifische Media Writes

`/data` is intentionally writable so scans, hashes, normalized metadata, tool execution records, authority/provider cache, decisions, and future plans can be persisted. `/media/...` is read-only in the default compose file.

Ein W10-Writer erhält keine allgemeine Schreibfreigabe für
`/media`. Er verwendet ausschließlich die engste lokal aufgelöste Capability
seines Operationstyps. Fehlt sie oder ist ihre Revalidierung nicht eindeutig,
endet die Operation fail-closed vor der Mutation.

## Private data

Runtime state may itself contain sensitive metadata about a private collection. `/data` is therefore excluded from Git. Logs should avoid dumping full extracted text, unnecessary absolute paths, raw external queries, tool command lines containing sensitive values, or credentials.

Extracted e-book text is private runtime data. The W3 calibre and Poppler text
adapters store it only as bounded `ToolArtifact` data under the configured
artifact root; the CLI emits status, character count and fingerprint, but not
the raw text. Their fixed command allowlists expose no caller-controlled
conversion options, PDF passwords, OCR or Source-Media write operations.
The calibre text allowlist is limited to EPUB, MOBI, AZW and AZW3. FolioTone
does not remove or bypass DRM; protected, damaged or otherwise failed
conversions remain failed `ToolExecution` records and are not mislabeled as
successful `NO_TEXT` observations.

EPUBCheck validation uses a fixed Java/JAR command and writes its bounded JSON
report only into the private tool workspace before artifact capture. The raw
report may contain the runtime source path and therefore remains private
runtime data. Normalized `ToolResult` Evidence contains only the conformance
verdict, bounded severity counts and diagnostic-code counts; message text and
local paths are not emitted by the CLI.

Embedded e-book covers are also private runtime data. The fixed calibre helper
copies an exact EPUB/MOBI/AZW/AZW3 observation into the ephemeral workspace
before calibre opens it, disables rendered EPUB fallback covers and verifies
the staged Source SHA-256 after execution. The optional raster is limited to
32 MiB and decoded only through a JPEG/PNG/WebP/GIF allowlist with a
40-megapixel and Decompression-Bomb boundary. The CLI emits only status, format,
dimensions and the versioned dHash, never the raw cover or an absolute path.

The unified `ebook-analyze` workflow does not add a generic command surface.
It can only select the existing fixed calibre, EPUBCheck and Poppler adapters
for the explicit EPUB/MOBI/AZW/AZW3/PDF allowlist. Adapter configuration is
preflighted before source analysis. Expected failure in one independent step
does not hide or relabel later Evidence, while the aggregate CLI result remains
non-zero unless every applicable technical step succeeds. Its bounded summary
excludes raw metadata, text, cover bytes, validation messages, artifact paths
and absolute source paths.

`ebook-analysis-workflow/v2` treats reuse as a read-only optimization, never as
an assumption. Before lookup, the exact FileObservation path is checked again
for root containment, symlinks, size and modification time. Current tool
versions are probed without opening source media and without persisting a run.
Reuse requires an explicit configuration identity, the latest exact matching
execution to be successful, every required private artifact to pass its
adapter-specific size and SHA-256 checks, and all normalized results and
fingerprints to be reproducible from those artifacts. Failure of any guard
falls back to a normal read-only execution. `--fresh` performs no reuse lookup.
Neither mode changes source media, and neither prints private artifact paths or
raw artifact content.

`ebook-quality/v1` is a read-only projection over the bounded workflow facts.
It does not execute another tool, open source media or persist raw metadata,
text, cover bytes or validation messages. `INCOMPLETE` means that the required
technical Evidence is unavailable or inconsistent; it must not be counted as
bad media. Conversely, `REVIEW` and `ACTION_REQUIRED` do not make an otherwise
successful ToolExecution fail and do not change the `ebook-analyze` exit code.
Quality dimensions, metadata completeness, text availability, cover presence
and structural findings are not identity Evidence by themselves and never
confirm a file-, `Edition`- or `Work`-level duplicate.

`ebook-comparison/v1` reads only persisted Evidence for two explicit
FileObservation IDs. It receives no Source Root, does not open media, invokes
no ToolProvider and writes no Relation or other matching state. The CLI emits
only formats, dimension states, coverage, bounded field/diagnostic keys,
Evidence counts and internal provenance IDs; raw metadata values, text,
covers, artifact paths and source paths remain private. A newer failed or
cancelled provider execution prevents older Evidence from silently appearing
current. `SAME`, a dHash distance or equal metadata fields are comparison facts
and never an automatic file-, `Edition`- or `Work`-identity decision.

`ebook-collection-analysis/v1` persistiert nur Run-/Observation-IDs,
Lifecycle, Lease, technische Zustände und begrenzte Zähler. Die CLI gibt keine
Observation-ID, keinen relativen oder absoluten Medienpfad und keine
Metadatenwerte aus. Datenbank, Tool-Artefakte und ephemeres Work-Verzeichnis
müssen außerhalb des Source Root liegen. Jedes geplante Item durchläuft vor
einer tatsächlichen Toolausführung erneut die vorhandene Root-, Symlink-,
Größen- und Änderungszeitprüfung. Ein Fehler bleibt lokal zum Item und
berechtigt weder eine Source-Media-Operation noch eine Identitätsentscheidung.

`ebook-collection-report/v1` liest ausschließlich den persistierten
Collection-Snapshot und öffnet keine Source-Media-Datei. Datenbank und Report
Root müssen außerhalb des Source Root liegen. Die CLI gibt nur Run-ID,
Profile, Summen, Bericht-Hash und privaten Ausgabeort aus; relative
Medienpfade erscheinen ausschließlich in den lokalen Review-Artefakten. Rohe
Datei- und Textfingerprints werden weder im JSON noch in CSV ausgegeben.
CSV-Zellen mit Formelpräfixen werden neutralisiert. Exact-Duplicate- und
Content-Variant-Gruppen sind technische Review-Kandidaten und berechtigen
weder eine Source-Media-Operation noch eine `Relation` oder
Identitätsentscheidung.

`archive-collection-orchestration/v1` persistiert einen pfadfreien,
immutable Multi-Volume-Plan für genau einen abgeschlossenen Scan. Der
Orchestrator revalidiert jede Source vor dem Providerlauf und schreibt nur
unter einer gefenceten `ARCHIVE_COLLECTION_RUN`-Lease. Stale Worker verlieren
nach Takeover jede Write-Authority. Der read-only Status gibt ausschließlich
Run-ID, Profile, feste Statusliterale und Summenzähler aus. Extraction,
Secretübergabe, Quarantäne und Source-Mutation bleiben dadurch gesperrt.

Imported/local provider datasets and external tool reports derived from a private collection must also stay out of Git unless a future explicit decision establishes that a specific redistributable artifact belongs in the repository.
