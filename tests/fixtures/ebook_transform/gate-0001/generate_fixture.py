# ruff: noqa: E501
"""Generate the deterministic synthetic input for GATE-0001."""

from __future__ import annotations

import base64
import zipfile
from hashlib import sha256
from pathlib import Path

PROFILE = "ebook-transform-gate-input/v1"
ZIP_TIME = (2026, 8, 25, 10, 0, 0)

CONTAINER = b'''<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
'''

PACKAGE = b'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0" unique-identifier="book-id" xml:lang="de">
  <metadata>
    <dc:identifier id="book-id">urn:uuid:11111111-2222-4333-8444-555555555555</dc:identifier>
    <dc:title id="title">Synthetischer Ausgangstitel</dc:title>
    <dc:creator id="creator">Ada Beispiel</dc:creator>
    <meta refines="#creator" property="role" scheme="marc:relators">aut</meta>
    <dc:language>de</dc:language>
    <dc:publisher>FolioTone Testverlag</dc:publisher>
    <meta property="dcterms:modified">2026-08-25T10:00:00Z</meta>
    <meta property="belongs-to-collection" id="series">Synthetische Reihe</meta>
    <meta refines="#series" property="collection-type">series</meta>
    <meta refines="#series" property="group-position">1</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
    <item id="cover" href="cover.png" media-type="image/png" properties="cover-image"/>
  </manifest>
  <spine><itemref idref="chapter"/></spine>
</package>
'''

NAVIGATION = b'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="de">
  <head><title>Inhalt</title></head><body><nav epub:type="toc"><ol><li><a href="chapter.xhtml">Kapitel</a></li></ol></nav></body>
</html>
'''

CHAPTER = b'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="de">
  <head><title>Kapitel</title></head><body><h1>Kapitel</h1><p>Unveraenderlicher synthetischer Text.</p></body>
</html>
'''

COVER = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

REVIEWED_METADATA = b'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0" unique-identifier="book-id">
  <metadata>
    <dc:identifier id="book-id">urn:uuid:11111111-2222-4333-8444-555555555555</dc:identifier>
    <dc:title>Synthetischer Zieltitel</dc:title>
    <dc:creator id="creator">Ada Beispiel</dc:creator>
    <meta refines="#creator" property="role" scheme="marc:relators">aut</meta>
    <dc:language>de</dc:language>
    <dc:publisher>FolioTone Testverlag</dc:publisher>
    <meta property="belongs-to-collection" id="series">Synthetische Reihe</meta>
    <meta refines="#series" property="collection-type">series</meta>
    <meta refines="#series" property="group-position">1</meta>
  </metadata>
</package>
'''

ENTRIES = (
    ("mimetype", b"application/epub+zip"),
    ("META-INF/container.xml", CONTAINER),
    ("EPUB/package.opf", PACKAGE),
    ("EPUB/nav.xhtml", NAVIGATION),
    ("EPUB/chapter.xhtml", CHAPTER),
    ("EPUB/cover.png", COVER),
)


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def generate_fixture(output_dir: Path) -> dict[str, object]:
    """Generate a byte-stable EPUB and reviewed-metadata OPF."""
    output_dir.mkdir(parents=True, exist_ok=True)
    source = output_dir / "source.epub"
    reviewed_metadata = output_dir / "reviewed-metadata.opf"
    with zipfile.ZipFile(source, mode="w") as archive:
        for name, content in ENTRIES:
            archive.writestr(_zip_info(name), content)
    reviewed_metadata.write_bytes(REVIEWED_METADATA)
    return {
        "profile": PROFILE,
        "source_sha256": sha256(source.read_bytes()).hexdigest(),
        "source_size_bytes": source.stat().st_size,
        "reviewed_metadata_sha256": sha256(reviewed_metadata.read_bytes()).hexdigest(),
        "reviewed_metadata_size_bytes": reviewed_metadata.stat().st_size,
    }
