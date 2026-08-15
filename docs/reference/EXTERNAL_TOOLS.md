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
- `CLI`: a future explicit read-command allowlist for `calibredb`, not arbitrary subcommands;
- `SERVICE`: calibre Content Server where useful, using documented interfaces rather than reverse-engineered web UI calls;
- `CONTAINER_JOB`: optional external calibre container.

Important boundary:

`calibredb` can modify a calibre library. FolioTone must initially use only read-oriented operations and must not make Calibre the canonical FolioTone database.

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
