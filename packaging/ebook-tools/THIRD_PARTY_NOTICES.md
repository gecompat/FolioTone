# Third-party notices for the optional E-book Toolchain image

This file documents the separately acquired tools in
`ebook-toolchain-linux-amd64/v1`. The exact upstream URLs, versions, archive
sizes and SHA-256 values are recorded in `toolchain.lock.json`.

The image recipe downloads the upstream distributions during the explicit
local build. No third-party binary is stored in the FolioTone Git repository.

| Component | Version | License | Upstream source and license information |
|---|---:|---|---|
| calibre | 9.13.0 | GPL-3.0 | https://github.com/kovidgoyal/calibre/tree/v9.13.0 and https://github.com/kovidgoyal/calibre/blob/v9.13.0/LICENSE |
| Poppler | 26.07.0 | GPL-2.0-or-later for the selected utilities and core | https://gitlab.freedesktop.org/poppler/poppler/-/tree/poppler-26.07.0 |
| Eclipse Temurin JRE | 21.0.12+8 | GPL-2.0 with Classpath Exception and bundled notices | https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.12%2B8 |
| EPUBCheck | 5.3.0 | BSD-3-Clause plus bundled dependency notices | https://github.com/w3c/epubcheck/releases/tag/v5.3.0 |

The extracted Temurin and EPUBCheck distributions retain their upstream legal
and license directories. The Poppler source archive contains `COPYING` and
`COPYING3`; the image installs those files under `/usr/share/licenses/poppler`.
The local image must not be published or redistributed without a separate
component-level license and source-offer review.
