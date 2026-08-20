# External Analysis Tools Registry

This registry records mature software that FolioTone may orchestrate rather than reimplement.

A listed tool is a **candidate ToolProvider**, not a mandatory dependency. Before implementation, re-check the current official documentation, maintenance state, license, automation interface, output formats, container availability and security implications.

## General policy

Preferred order for a capability:

1. use a stable existing FolioTone/core capability when it is genuinely domain-specific;
2. reuse a mature external tool through a documented interface when it already solves the specialist problem well;
3. normalize the tool output into FolioTone observations/evidence;
4. implement FolioTone-native specialist logic only where existing tools are unsuitable, insufficient, non-automatable or strategically undesirable.

External tools provide **evidence and specialist processing**. FolioTone owns provenance, reconciliation, canonical identity decisions, cross-tool matching, review and consolidation planning.

Through W9, source media remains read-only. Tool write/delete/move/retag capabilities are not authorized.

## Integration modes

- `CLI` — execute a documented command and capture structured output, exit status and tool version.
- `SERVICE` — call a documented HTTP/API/service interface.
- `CONTAINER_JOB` — run a pinned external image for a bounded analysis job.
- `LOCAL_LIBRARY` — integrate a library only behind an adapter when process isolation is not preferable.
- `INTERACTIVE_VALIDATOR` — optional human-facing specialist tool; not required for the automated pipeline.

Für `ebook-collection-analysis/v1` kann die Runtime identische lokale
Versionsprobes innerhalb genau einer Prozess-Invocation thread-sicher
wiederverwenden. Der Cache persistiert nichts, öffnet keine Source Media und
ersetzt weder ToolExecution-Provenance noch die exakte Evidence-
Wiederverwendungsprüfung. Verschiedene Toolbefehle und Version Policies bleiben
getrennte Cache-Identitäten; Einzeldatei-Kommandos aktivieren diese Optimierung
nicht standardmäßig.

## E-book tools

### calibre

Priority: **very high**

Evaluated snapshot: **9.13.0 on 2026-08-15; metadata, EPUB/MOBI/AZW/AZW3 text and embedded-cover adapters implemented**

Candidate roles:

- e-book metadata extraction through calibre CLI tools;
- deterministic plain-text extraction from EPUB, MOBI, AZW and AZW3 for
  FolioTone-owned fingerprints;
- embedded-cover extraction from EPUB, MOBI, AZW and AZW3 for bounded
  FolioTone-owned visual Evidence;
- calibre library inventory/query through `calibredb`;
- optional remote library access through a calibre Content Server used by `calibredb`;
- format inspection/conversion support for analysis workflows;
- validation/comparison/polishing capabilities where a safe read-only analysis path exists.

Preferred integration:

- `CLI`: the implemented immutable `ebook-meta FILE --to-opf metadata.opf` shape;
- `CLI`: the implemented immutable `ebook-convert FILE content.txt` shape with
  fixed UTF-8, Unix-newline, plain-text and no-line-wrap options;
- `CLI`: the implemented fixed `calibre-debug -e` helper, which stages source
  privately and disables rendered EPUB fallback covers;
- `CLI`: die durch ADR-0033 festgelegten lokalen read-only Shapes für
  `list --for-machine`, Exact-ID-`search`, `show_metadata --as-opf` und
  `list_categories --csv`; keine beliebigen Subcommands, Optionen,
  Suchausdrücke oder Remote-Content-Server;
- `SERVICE`: calibre Content Server where useful, using documented interfaces rather than reverse-engineered web UI calls;
- `CONTAINER_JOB`: optional external calibre container.

Important boundary:

`calibredb` can modify a calibre library. ADR-0033 erlaubt deshalb nur vier
vollständig erzeugte read-only Command Shapes. Der lokale Bibliothekspfad
bleibt Runtime-Konfiguration; absolute Pfade werden bereits in der
maschinenlesbaren Ausgabe durch eine feste Pseudowurzel ersetzt. Calibre bleibt
Evidence Source und wird nicht zur kanonischen FolioTone-Datenbank.

`ebook-meta` is also a read/write executable. The implemented adapter exposes no
setter arguments, isolates `CALIBRE_CONFIG_DIRECTORY`, persists a bounded OPF
artifact and rejects unknown versions or calibre versions below 9.10.0 before
opening Source Media. This minimum follows `GHSA-2j4m-2q7x-2c47` /
`CVE-2026-53511`; versions through 9.9.0 are affected.

Metadata adapter version `ebook-meta-opf/2` retains provider-shaped raw OPF
observations and additionally projects OPF 2 attributes plus OPF 3 refinements
under `ebook-metadata-candidate/v1`. Grouped candidates cover identifier
namespace/value pairs including explicit ISBN schemes, contributor names,
MARC relator roles and sort names, language, publisher, publication date,
subject, description, rights, type, title sort, rating and series
name/position. Every result links to the exact `ToolExecution` and
`FileObservation`. Unknown role vocabularies are retained without a guessed
normalized role, and the adapter creates no canonical entities.

The text adapter applies the same version floor and isolated configuration to
`ebook-convert`. Adapter version `ebook-convert-text/2` accepts exactly EPUB,
MOBI, AZW and AZW3, writes exclusively into the private tool workspace,
captures at most 64 MiB as `CALIBRE_TEXT`, and exposes no caller-controlled
conversion options. FolioTone then computes the versioned
`EBOOK_NORMALIZED_TEXT` SHA-256; calibre remains the replaceable extractor, not
the fingerprint or domain model. DRM removal or bypass is not implemented.
Protected, damaged or otherwise failed conversions remain failures and are not
mislabeled as successful `NO_TEXT` results.

Adapter version `calibre-debug-cover/1` accepts exactly EPUB, MOBI, AZW and
AZW3. The fixed packaged helper copies the observed file into the private
workspace before calibre sees it, returns a bounded JSON result plus optional
32 MiB private cover artifact, and verifies the staged Source SHA-256 after the
run. Rendered first-page EPUB covers are disabled; absent embedded artwork is
explicit `NO_EMBEDDED_COVER`. Direct `ebook-meta --get-cover` is not used
because its rendered-cover fallback violates that semantic contract and the
9.13 `--disallow-rendered-cover` path can rewrite the input.

The binding evaluation, license notes and reuse/defer decisions are documented
in [E-Book-Toolchain-Bewertung](EBOOK_TOOL_EVALUATION.md).

Official references:

- https://manual.calibre-ebook.com/en/generated/en/cli-index.html
- https://manual.calibre-ebook.com/generated/en/ebook-meta.html
- https://manual.calibre-ebook.com/generated/en/ebook-convert.html
- https://manual.calibre-ebook.com/generated/en/calibre-debug.html
- https://manual.calibre-ebook.com/drm.html
- https://manual.calibre-ebook.com/en/generated/en/calibredb.html
- https://manual.calibre-ebook.com/server.html
- https://www.w3.org/TR/epub-33/
- https://www.loc.gov/marc/relators/relacode.html
- https://github.com/kovidgoyal/calibre/blob/master/src/calibre/ebooks/metadata/opf3.py
- https://github.com/kovidgoyal/calibre/security/advisories/GHSA-2j4m-2q7x-2c47

Container candidate:

- LinuxServer.io calibre: `lscr.io/linuxserver/calibre:latest`
- https://docs.linuxserver.io/images/docker-calibre/

Security note:

The LinuxServer calibre image exposes a full GUI/terminal environment and its own documentation warns about privileged access implications. It should not automatically become part of FolioTone's default minimal runtime. Prefer a purpose-built CLI integration or an isolated optional profile where practical.

### Pillow

Priority: **high**

Evaluated snapshot: **12.3.0 on 2026-08-15; bounded e-book cover normalization implemented**

Implemented role:

- decode JPEG, PNG, WebP or GIF embedded covers;
- apply EXIF orientation, grayscale conversion and 9 x 8 Lanczos resampling;
- provide pixels for FolioTone's versioned horizontal 64-bit dHash.

Important boundary:

Pillow is the image decoder/resampler, not the owner of the fingerprint or an
identity decision. FolioTone limits the encoded artifact to 32 MiB and decoded
image to 40 megapixels, treats Decompression-Bomb warnings as failures, uses
only the first frame and records the exact Pillow version in
`algorithm_version`. The resulting `EBOOK_COVER_DHASH` is supporting Evidence
only. Pillow is licensed MIT-CMU.

ImageHash 4.3.2 was evaluated but not added. Its package brings NumPy, SciPy and
PyWavelets in addition to Pillow, while the current contract needs only a
small fixed dHash. Additional visual algorithms require a new evaluation and
new versioned profile.

Official references:

- https://pypi.org/project/pillow/
- https://pillow.readthedocs.io/en/stable/reference/Image.html
- https://github.com/python-pillow/Pillow/blob/main/LICENSE
- https://pypi.org/project/ImageHash/
- https://github.com/JohannesBuchner/imagehash/blob/master/setup.py

### EPUBCheck

Priority: **very high**

Evaluated snapshot: **5.3.0 on 2026-08-15; EPUB 2/3 JSON validation adapter implemented**

Implemented role:

- EPUB conformance and structural diagnostics as bounded external Evidence.

Preferred integration:

- `CLI`: Java runs the separately installed official `epubcheck.jar` with one
  source EPUB, `--json report.json` and fixed English locale output.

Important boundary:

Adapter version `epubcheck-json/1` accepts only an unchanged persisted EPUB
`FileObservation`. It exposes no caller-controlled EPUBCheck options, fixes the
JVM to headless mode, and redirects the JVM temporary directory into the
ephemeral private tool workspace. Version 5.3.0 is the minimum accepted report
contract. The JSON artifact is limited to 8 MiB, integrity-checked and parsed
with bounded message counts.

EPUBCheck uses exit code `1` for a completed validation with errors. The
adapter therefore accepts only `{0, 1}` for this operation, preserves the
observed code, and requires a valid report before treating the invocation as
successful. `ToolResult` records contain `CONFORMANT` or `NONCONFORMANT`,
fatal/error/warning/usage/info counts and aggregated severity/code counts.
They omit report message text and local paths. The raw private report remains a
`ToolArtifact`; it is not committed or printed by the CLI.

EPUBCheck is BSD-3-Clause. FolioTone does not bundle its JAR or a Java runtime
in this repository. A later distributable package must decide and document how
those dependencies and their license notices are supplied.

Official references:

- https://github.com/w3c/epubcheck
- https://github.com/w3c/epubcheck/releases/tag/v5.3.0
- https://github.com/w3c/epubcheck/blob/v5.3.0/src/main/java/com/adobe/epubcheck/tool/EpubChecker.java
- https://github.com/w3c/epubcheck/blob/v5.3.0/LICENSE.md

### Poppler

Priority: **very high**

Evaluated snapshot: **26.07.0 on 2026-08-14; PDF metadata/page/text adapters implemented**

Implemented roles:

- technical PDF metadata and page count through `pdfinfo`;
- bounded plain-text extraction through `pdftotext`;
- explicit distinction between successful `TEXT_EXTRACTED` and successful
  `NO_TEXT` results.

Preferred integration:

- `CLI`: `pdfinfo -enc UTF-8 -isodates FILE`;
- `CLI`: `pdftotext -enc UTF-8 -eol unix -nopgbrk -remove-hyphens all FILE
  content.txt`.

Important boundary:

The adapter accepts PDF only and exposes no caller-controlled Poppler options,
password handling, OCR or write operations. `pdfinfo` and `pdftotext` are
recorded as separate `ToolExecution` instances. Unknown versions and versions
below 26.07.0 are rejected before Source Media is opened. Imported `pdfinfo`
stdout is bounded to 1 MiB and parsed through a field allowlist; extracted text
is bounded to 64 MiB and remains a private `POPPLER_TEXT` artifact. The CLI
prints metadata, status, count and fingerprint, never raw extracted text.

FolioTone applies its own shared, versioned Unicode `NFKC` and whitespace
normalization after artifact verification. A successful empty extraction is
`NO_TEXT` and creates no `EBOOK_NORMALIZED_TEXT` fingerprint. Non-zero Poppler
exit codes, encrypted or damaged inputs remain failures and are not mislabeled
as no-text PDFs.

qpdf 12.4.0 remains deferred as optional structural/integrity evidence because
the implemented W3-004 contract has no unresolved structural gap. Poppler is
not bundled in this repository; redistribution requires a separate review of
the GPL-2.0-or-later components and dependencies actually shipped.

Official references:

- https://poppler.freedesktop.org/
- https://gitlab.freedesktop.org/poppler/poppler/-/blob/poppler-26.07.0/NEWS
- https://packages.msys2.org/packages/mingw-w64-x86_64-poppler

### Archiv-Listing und sichere Testextraktion

Priority: **high / FG-A-RUNTIME accepted, implementation pending**

Evaluated snapshot: **7-Zip 26.02 and libarchive 3.8.9 on 2026-08-20;
tool contract accepted by ADR-0038 and unencrypted runtime contract accepted by
ADR-0039, no real adapter implemented**

Candidate roles:

- signature-first Listing und Integritätstest für ZIP, RAR, 7z, TAR, CBR und
  CBZ;
- Verschlüsselungs-, Volume-, CRC- und Methodenerkennung;
- begrenzte private Testextraktion ohne Source-Media-Mutation;
- maschinenlesbare Mitglieder- und Fehlerausgabe für versionierte Evidence.

ADR-0038 wählt 7-Zip 26.02 als optionalen Baseline-`ToolProvider` für exakt
erzeugte read-only `i`-, `l -slt`-, `t`- und später `x`-Shapes. Die
FolioTone-Allowlist umfasst ZIP, RAR 4/5, 7z, TAR sowie gzip-, bzip2-, xz- und
zstd-komprimierte TAR-Unterformen; EPUB, CBZ und CBR bleiben
Publikationscontainer. Andere von 7-Zip technisch lesbare Formate sind nicht
dadurch freigegeben. Toolausgaben bleiben bounded und verlassen keine private
Runtime-Grenze; Source und vollständige Volumegruppen werden read-only
geöffnet.

Die allgemeine Formulierung zu Runtime-Artefakten gilt nicht für rohe
7-Zip-Archive-Ausgabe: `l -slt` kann Containerkommentare mit Passwortmaterial
und private Membernamen enthalten. Die bestehende `ToolRuntime` persistiert
stdout/stderr unverändert und ist deshalb für den realen Adapter ungeeignet.
ADR-0039 akzeptiert dafür eine spezialisierte `ArchiveProcessRunner`-Grenze,
nicht eine Erweiterung der generischen `ToolRuntime`. stdout wird bis zur
ADR-0038-Grenze direkt mit `archive-7zip-slt-parser/v1` verarbeitet; stderr
wird nur in feste Fehlerliterale klassifiziert. Rohbytes, Previews und Raw-
Artefakte werden nicht persistiert. Die Runtime verwendet ein minimales
allowlist-basiertes Environment und muss bei Timeout oder Grenzverletzung den
vollständigen Prozessbaum beenden.

Der erste freigegebene Backendvertrag heißt
`archive-linux-container-runner/v1` für die primäre Docker/Linux-Runtime. Er
verwendet nur ein lokal vorhandenes, per Digest gepinntes Image. FG-A-IMAGE
ist durch [ADR-0040](../decisions/ADR-0040-reproducible-archive-runtime-image.md)
akzeptiert: FolioTone pflegt für genau `linux/amd64` ein projekt-eigenes
`FROM scratch`-Rezept mit dem unveränderten offiziellen statischen
`7zzs`-Tar-Member aus dem
`7z2602-linux-x64.tar.xz`, dessen SHA-256
`41aaba7b1235304ab5aa0624530c67ae829496cd29e875925271efdccc28c03e`
beträgt, vollständigen Lizenzhinweisen und `USER 65532:65532`. Das offizielle
Release besitzt keinen separaten Signaturnachweis; dieser Sachverhalt bleibt
als `UNSIGNED_UPSTREAM_RELEASE` Teil der Supply-Chain-Evidence.

S-EBAR-03 setzt die festen Werte mechanisch um, prüft den statischen Tar-Member
`7zzs` als Linux-x86-64-ELF und baut das Offline-Rezept zweimal. Der identische,
in `archive-image-lock/v1` gespeicherte `linux/amd64`-Plattform-Manifest-
Digest lautet
`sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287`.
Der Build
verwendet das in ADR-0040 vollständig gepinnte Buildx-/BuildKit-Profil und
erzeugt das Runtime-Manifest ohne Inline-Attestations; SBOM und Provenance
werden anschließend an den gelockten Digest angehängt. Das GHCR-Package muss
durch geschützten Owner-Setup öffentlich und mit `gecompat/FolioTone` source-
associated sein. Ein neuer Prozess ohne Benutzer- oder Registry-Credentials,
Cookies oder Docker-Config muss die Digestreferenz anonym über den in ADR-0040
begrenzt erlaubten credentialfreien Registry-v2-Bearer-Flow abrufen und exakt
bestätigen; jede Abweichung bleibt `TOOL_UNAVAILABLE`. Ein Tag ist niemals eine
Runtime-Identität. Der
Container läuft non-root mit
`network=none`, read-only
Root-Filesystem, `cap-drop=ALL`, no-new-privileges, Default-oder-strengerem
Seccomp, ohne Devices, mit festen PID-/RAM-/CPU-Grenzen, fester Entrypoint/argv
und minimalem Environment. Timeout und Cancellation erzwingen Kill und
Entfernung des Containers.

[ADR-0041](../decisions/ADR-0041-offline-archive-runtime-availability.md)
entscheidet die verbleibende Availability-Grenze. Der Bootstrap-Lock und ein
lokales Image Inspect beweisen keine akzeptierte Release-Lineage. S-EBAR-03A
muss deshalb vor EBAR-04 einen reviewten `archive-runtime-release/v1`-Record,
die exakt gehashten Custom-SLSA-/SPDX-Bundles und GitHub-Workflowclaims, eine
kontrollierte Erstprovisionierung sowie einen monotonen lokalen State
implementieren. Ein ungepinntes System-`gh` ist nicht die Runtime-Authority;
die reviewte FolioTone-Source autorisiert die gebundenen Evidence-Bytes.

Public Visibility und Source-Association werden beim Provisioning und
spätestens alle 90 Tage beim Refresh geprüft. Jeder Archive-Lauf bleibt danach
vollständig offline und revalidiert Release-Record, Evidence, Revocation,
lokales OCI-Manifest, Config, komprimierte Layer, geordnete RootFS-`diff_id`-
Werte und den tatsächlich auswählbaren Docker-Store-Eintrag. Fehlender oder
beschädigter State, rückläufige Generation oder Clock, Ablauf, Revocation und
jede Identity-Abweichung liefern `TOOL_UNAVAILABLE`; es gibt keinen Pull- oder
Registry-Fallback. Ein Offline-Host kann eine seit dem letzten Refresh extern
veröffentlichte Revocation nicht erkennen, und v1 behauptet keinen TPM-
Antirollback-Schutz gegen den lokalen Administrator.

Die tatsächliche Source und jeder ScanRoot werden niemals gemountet. FolioTone
kopiert genau die validierte Volumegruppe in ein opaque privates Input-Staging
unter dem konfigurierten Temp-Root, bewahrt nur die nötige Suffix-/Volumeform
und prüft Source-Observation, Bytes und vollständige Hashes vor und nach der
Kopie. No-follow-Preflight und Bind-Projektion müssen für das Staging
container-sichtbar Owner `65532:65532`, Verzeichnisse `0500`, reguläre Dateien
`0400` und Link-/Junction-/Reparse-Freiheit beweisen. Nur dieses Staging wird
read-only gemountet; ein neu erzeugtes leeres privates Output-Verzeichnis mit
Owner `65532:65532` und Modus `0700` ist der einzige read-write Mount.
Zusätzliche ACL-Rechte oder nicht beweisbare Mountsemantik schließen das
Backend fail-closed. Beide Workspaces werden nach dem Lauf erneut no-follow
geprüft und bereinigt. Native Windows-Ausführung bleibt `TOOL_UNAVAILABLE`, bis
`FG-A-WINDOWS-SANDBOX` Netzwerk- und Filesystemisolation nachweist. Job
Objects und Handle-Allowlisten allein sind dafür unzureichend.

Die Freigabe umfasst nur unverschlüsseltes Listing, Integrity und die nach
vollständiger Policy-Prüfung zulässige private Testextraktion. Listing,
Integrity und Extraction erhalten getrennte `ToolExecution`-Provenance. Die
Extraction wird erst nach einer erneuten Workspace-Prüfung und vollständigem
Member-/Größen-/CRC-Abgleich als erfolgreich behandelt.

libarchive/bsdtar 3.8.9 bleibt zurückgestellt. libarchive besitzt einen
Passphrase-Callback und breite Leseunterstützung, deckt verschlüsselte RAR-/7z-
Payloads jedoch nicht als gemeinsame Baseline ab. `bsdtar --passphrase`
dokumentiert seinen eigenen CLI-Weg ausdrücklich als unsicher. Eine parallele
Fallback-Ausführung würde außerdem eine zweite Parser-/Ergebnissemantik
einführen.

Die 7-Zip-CLI dokumentiert nur `-p{password}` und besitzt keinen für FolioTone
freigegebenen Secret-Kanal über separaten File Descriptor. Deshalb ist
Password Handling im realen v1-Adapter blockiert und liefert
`SECURE_CHANNEL_UNAVAILABLE`, bevor ein Secret den Prozess erreicht. Eine
spätere verschlüsselte Runtime benötigt ein eigenes Frontier-Gate und einen
isolierten Helper-/anonymen-Pipe-Vertrag; stdin-, PTY-, argv- und
Environment-Workarounds sind nicht akzeptiert.

Dieses Gate heißt FG-A-SECRET und bleibt blockiert. Es muss einen konkreten
Helper, die tatsächlich unterstützte verschlüsselte Formatmatrix, explizite
Handle-Vererbung, Speicherbereinigung und adversarial Leakage-Tests festlegen.
Ohne diesen Nachweis bleibt der Status `SECURE_CHANNEL_UNAVAILABLE`; die
unverschlüsselte Runtime darf daraus keine implizite Passwortfreigabe ableiten.

Eine erfolgreiche Extraktion ist keine Löschfreigabe. CBR, CBZ und EPUB sind
Publikationscontainer und werden nicht als automatisch entbehrliche Archive
behandelt. Der detaillierte Stufenvertrag steht in
[`EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md`](../planning/EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md);
die bindenden Literale, Budgets, Command Shapes, Secret- und Sandbox-Grenzen
stehen in [ADR-0038](../decisions/ADR-0038-safe-archive-container-analysis.md)
und [ADR-0039](../decisions/ADR-0039-safe-archive-runtime-and-secret-channel.md).

Official references:

- https://www.7-zip.org/download.html
- https://www.7-zip.org/
- https://github.com/ip7z/7zip/blob/main/DOC/src-history.txt
- https://github.com/ip7z/7zip/blob/main/DOC/7zip.hhp
- https://github.com/ip7z/7zip/issues/184
- https://github.com/libarchive/libarchive/releases/tag/v3.8.9
- https://github.com/libarchive/libarchive/wiki/LibarchiveFormats
- https://github.com/libarchive/libarchive/blob/master/libarchive/archive.h
- https://github.com/libarchive/libarchive/blob/master/libarchive/test/test_read_format_7zip_encryption_data.c
- https://github.com/libarchive/libarchive/issues/2516
- https://github.com/libarchive/libarchive/blob/master/tar/bsdtar.1
- https://docs.docker.com/reference/cli/docker/container/run/
- https://docs.docker.com/engine/storage/bind-mounts/
- https://docs.docker.com/engine/network/drivers/none/
- https://docs.docker.com/engine/containers/resource_constraints/
- https://docs.docker.com/engine/security/seccomp/
- https://docs.docker.com/build/building/best-practices/
- https://docs.docker.com/build/building/base-images/
- https://docs.docker.com/build/ci/github-actions/reproducible-builds/
- https://docs.docker.com/build/metadata/attestations/sbom/
- https://github.com/docker/buildx/releases/tag/v0.36.1
- https://github.com/moby/buildkit/releases/tag/v0.32.2
- https://docs.docker.com/reference/cli/docker/buildx/build/
- https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility
- https://docs.github.com/en/packages/learn-github-packages/connecting-a-repository-to-a-package
- https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
- https://docs.docker.com/build/metadata/attestations/slsa-provenance/
- https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations
- https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline
- https://cli.github.com/manual/gh_attestation_verify
- https://cli.github.com/manual/gh_attestation_trusted-root
- https://www.7-zip.org/license.txt

## Music tools

### FFmpeg / ffprobe

Priority: **very high**

Candidate roles:

- codec/container/stream inspection;
- duration, sample rate, channels, bitrate and other technical observations;
- format/probe failure as integrity evidence;
- decoding support required by other fingerprinting tools.

Preferred integration:

- `CLI` using `ffprobe` with machine-readable output, preferably JSON.

Official references:

- https://ffmpeg.org/ffprobe.html
- https://ffmpeg.org/documentation.html

### Chromaprint / fpcalc

Priority: **very high**

Candidate roles:

- compact acoustic fingerprints;
- near-identical audio identification support;
- duplicate candidate generation;
- input to AcoustID lookups.

Preferred integration:

- `CLI` through `fpcalc` with machine-readable output;
- optionally `LOCAL_LIBRARY` later if process overhead becomes material.

Important boundary:

Chromaprint is optimized for near-identical audio identification and is not a universal semantic music-similarity engine. FolioTone must not treat one fingerprint as sufficient evidence for every distinction such as remix, remaster, alternate performance or work identity.

Official reference:

- https://github.com/acoustid/chromaprint

### beets

Priority: **very high**

Candidate roles:

- MusicBrainz-based music metadata matching;
- duplicate analysis;
- missing-track/album completeness analysis;
- Chromaprint/AcoustID integration;
- query/library capabilities;
- source of specialist evidence for music reconciliation.

Preferred integration:

- `CLI` first;
- possible Python integration only if a stable public programmatic boundary provides clear value.

Safety note:

beets has commands/plugins capable of moving, deleting, tagging and otherwise modifying files. FolioTone must use analysis/query modes only through W9.

Official references:

- https://beets.readthedocs.io/
- https://beets.readthedocs.io/en/stable/plugins/duplicates.html
- https://beets.readthedocs.io/en/stable/plugins/missing.html

### SongKong

Priority: **high**

Candidate roles:

- automated music identification and metadata analysis;
- status/report generation;
- classical metadata evidence;
- MusicBrainz/Discogs/AcoustID-based matching evidence;
- preview-mode comparison of proposed changes.

Preferred integration:

- `CONTAINER_JOB` and documented `CLI`;
- consume generated reports/artifacts as evidence.

Current official image family includes `songkong/songkong`; the application can run in Docker and command-line modes. Commercial licensing/edition capabilities must be evaluated before making any feature dependent on it.

Safety note:

SongKong exposes commands for fixing metadata, deleting duplicates, moving/renaming and other writes. FolioTone must initially restrict integration to status/report/preview or other verified non-mutating modes.

Official references:

- https://www.jthink.net/songkong/help/help.html
- https://www.jthink.net/songkong/en/install_docker_synology.jsp
- https://community.jthink.net/t/tutorial-songkong-command-line/11892
- https://www.jthink.net/songkong/download.jsp

### MusicBrainz Picard

Priority: **medium / optional specialist**

Candidate roles:

- MusicBrainz-oriented validation;
- clustering/lookup/fingerprinting workflows;
- optional specialist comparison against FolioTone/beets/SongKong results;
- interactive expert review.

Picard supports command-line executable commands through its documented `-e` mechanism, including processing workflows.

Preferred integration:

- `CLI` / executable commands for bounded validation jobs;
- `INTERACTIVE_VALIDATOR` for human specialist review.

Architectural note:

Picard is not currently planned as FolioTone's primary automated backend. Its value is strongest as an additional independent evidence source or specialist validator where its workflow is suitable.

Official references:

- https://picard-docs.musicbrainz.org/en/latest/appendices/command_line.html
- https://picard-docs.musicbrainz.org/en/latest/usage/exec_commands.html

### Jaikoz

Priority: **low for automation / useful external expert tool**

Candidate role:

- manual expert metadata inspection/editing outside FolioTone's automated core.

FolioTone should not depend on Jaikoz unless a future review identifies a stable automation interface that provides unique value.

Official reference:

- https://jthink.net/jaikoz/

## Local metadata infrastructure

### MusicBrainz local mirror

Priority: **later / scale-dependent**

Candidate role:

- reduce repeated public-service queries for very large collections;
- provide local MusicBrainz web-service/search infrastructure when operational cost is justified.

The MusicBrainz Server documentation points to the MetaBrainz Docker Compose project as an installation path for local mirror/testing/development environments.

This is intentionally not an MVP dependency; it introduces substantial operational/storage complexity.

Official references:

- https://github.com/metabrainz/musicbrainz-docker
- https://github.com/metabrainz/musicbrainz-server/blob/master/INSTALL.md

## Candidates to evaluate later

These may provide useful specialist functions but need a dedicated current review:

- MediaInfo — technical media metadata;
- ExifTool — broad metadata extraction;
- ebook-polish sub-workflows within calibre;
- qpdf 12.4.0 — optional later PDF structural/integrity evidence; it does not extract text;
- MuPDF — deferred until a concrete gap remains after Poppler/qpdf evaluation;
- additional audio integrity/checksum tools;
- Cover Art Archive or image-processing tools for cover evidence;
- additional Dockerized specialist tools when they provide a documented, reproducible, non-destructive interface.

## ToolProvider evaluation checklist

Before implementing an adapter, document:

- exact capability FolioTone intends to reuse;
- why reuse is preferable to native implementation;
- official automation interface (CLI/API/service/container);
- machine-readable output availability;
- current version and maintenance state;
- license and redistribution constraints;
- whether the tool is open-source, free, commercial or edition-limited;
- Docker image ownership/source and supported architectures where relevant;
- required CPU/RAM/storage for expected collection scale;
- read/write behavior and safe analysis mode;
- failure/timeout/partial-output semantics;
- reproducibility/version recording strategy;
- privacy implications;
- how output maps into FolioTone observations/evidence;
- fallback behavior when the tool is unavailable.

## Operational principle

FolioTone should become the system that **connects the right specialists**, not a collection of unnecessary reimplementations.

The durable FolioTone assets are the common domain model, provenance, evidence graph, cross-tool reconciliation, review knowledge, library-health interpretation and safety model. Individual specialist tools remain replaceable.
