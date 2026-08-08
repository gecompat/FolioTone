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

## E-book tools

### calibre

Priority: **very high**

Candidate roles:

- e-book metadata extraction through calibre CLI tools;
- calibre library inventory/query through `calibredb`;
- optional remote library access through a calibre Content Server used by `calibredb`;
- format inspection/conversion support for analysis workflows;
- validation/comparison/polishing capabilities where a safe read-only analysis path exists.

Preferred integration:

- `CLI`: `ebook-meta`, `calibredb`, and other documented calibre CLI tools;
- `SERVICE`: calibre Content Server where useful, using documented interfaces rather than reverse-engineered web UI calls;
- `CONTAINER_JOB`: optional external calibre container.

Important boundary:

`calibredb` can modify a calibre library. FolioTone must initially use only read-oriented operations and must not make Calibre the canonical FolioTone database.

Official references:

- https://manual.calibre-ebook.com/en/generated/en/cli-index.html
- https://manual.calibre-ebook.com/en/generated/en/calibredb.html
- https://manual.calibre-ebook.com/server.html

Container candidate:

- LinuxServer.io calibre: `lscr.io/linuxserver/calibre:latest`
- https://docs.linuxserver.io/images/docker-calibre/

Security note:

The LinuxServer calibre image exposes a full GUI/terminal environment and its own documentation warns about privileged access implications. It should not automatically become part of FolioTone's default minimal runtime. Prefer a purpose-built CLI integration or an isolated optional profile where practical.

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
- ebook-convert / ebook-polish sub-workflows within calibre;
- EPUBCheck — EPUB conformance/structural validation;
- qpdf / MuPDF / Poppler tools — PDF structural/text analysis;
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
