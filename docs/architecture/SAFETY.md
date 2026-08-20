# Safety and Non-Destructive Operation

## Baseline

FolioTone starts as an analysis system. Source collections are treated as evidence, not as writable workspace.

## Enforced W0–W9 invariants

- source media mounts are read-only in the standard container configuration;
- no source-media delete command exists;
- no source-media move or rename command exists;
- no metadata writer exists for source media;
- no Calibre write adapter exists;
- external enrichment does not write back to source media;
- external ToolProviders may use only analysis-safe operations against source media;
- W9 consolidation plans are data records only and cannot execute.

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
begrenzten Streaming-Parser, klassifiziert stderr ausschließlich in feste
Fehlerliterale und verwirft Rohbytes nach secretfreier Normalisierung. Preview,
Raw Artifact, Raw Log und eine frei übernommene Host-Environment sind
verboten.

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

S-EBAR-03 muss das Image zweimal offline mit identischen Inputs bauen und den
beobachteten identischen `linux/amd64`-Plattform-Manifest-Digest mit dem fest
gepinnten Buildx-/BuildKit-Profil in `archive-image-lock/v1` fixieren. Die
Runtime-Builds enthalten keine Inline-Attestations; erst nach dem geschützten
Post-Merge-Publish werden SBOM und Provenance an den gelockten Digest
angehängt. Das GHCR-Package muss explizit öffentlich und mit
`gecompat/FolioTone` source-associated sein, und ein vollständig anonymer
Manifest-by-Digest-Abruf muss den gelockten Digest bestätigen. Ein fehlender
oder abweichender Digest, ein dynamisch abhängiges ELF, unvollständige
Lizenzhinweise, eine fehlende Attestation oder eine fehlgeschlagene anonyme
Verifikation ergeben fail-closed `TOOL_UNAVAILABLE`.

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
Provenance. Nach der Extraktion wird der private Workspace erneut no-follow auf
Pfade, Links, Reparse Points, Devices, Kollisionen, Größen und Vollständigkeit
geprüft, bevor Member gehasht und beide privaten Workspaces bereinigt werden.

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

## Future W10 requirements

A future executable consolidation engine must not be enabled merely by adding a CLI flag. It requires an explicit accepted ADR and must include at least:

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

## Persistence is writable; media is not

`/data` is intentionally writable so scans, hashes, normalized metadata, tool execution records, authority/provider cache, decisions, and future plans can be persisted. `/media/...` is read-only in the default compose file.

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

Imported/local provider datasets and external tool reports derived from a private collection must also stay out of Git unless a future explicit decision establishes that a specific redistributable artifact belongs in the repository.
