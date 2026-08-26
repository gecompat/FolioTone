from __future__ import annotations

import importlib.util
import io
import json
import platform
import stat
import struct
import sys
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from xml.sax.saxutils import quoteattr

import pytest

import foliotone.ebook_transform.profile as profile_module
from foliotone.ebook_transform import (
    METADATA_INVENTORY_KEYS,
    CanonicalEpubProfile,
    EbookTransformError,
    EbookTransformErrorCode,
    MetadataDisposition,
    MetadataProvenance,
    TransformMetadataField,
    TransformMetadataSnapshot,
    canonicalize_epub3,
    inspect_epub3,
    verify_canonical_epub3,
)

FIXTURE_ROOT = Path("tests/fixtures/ebook_transform/gate-0002")
GENERATOR = FIXTURE_ROOT / "generate_fixture.py"
SNAPSHOT = FIXTURE_ROOT / "metadata-snapshot.json"
MANIFEST = FIXTURE_ROOT / "fixture-manifest.json"
GATE_RUNNER = Path("tests/gates/run_gate_0002.py")
IMAGE_ID = "sha256:392fe0e6f3316b1dbc988fef55cb6a6c34137436ae62275e43f5d0a9e29270c7"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gate_0002_fixture", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_gate_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gate_0002_runner", GATE_RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot() -> TransformMetadataSnapshot:
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    fields = tuple(
        TransformMetadataField(
            key=item["key"],
            values=tuple(item["values"]),
            provenance=MetadataProvenance(item["provenance"]),
            disposition=MetadataDisposition(item["disposition"]),
            review_reference=item["review_reference"],
        )
        for item in payload["fields"]
    )
    return TransformMetadataSnapshot(
        fields=fields,
        technical_modified_utc=payload["technical_modified_utc"],
        technical_delta_allowlist=tuple(payload["technical_delta_allowlist"]),
        profile=payload["profile"],
    )


def _profile() -> CanonicalEpubProfile:
    return CanonicalEpubProfile(
        calibre_version="9.13.0",
        calibre_adapter_version="ebook-polish-opf/1",
        parser_version="epub3-bounded-ocf/1",
        serializer_version="epub3-opf-canonical/1",
        packer_version="epub3-zip-canonical/1",
        python_implementation=sys.implementation.name,
        python_version=platform.python_version(),
        python_build=" ".join(platform.python_build()),
        zlib_build_version=zlib.ZLIB_VERSION,
        zlib_runtime_version=zlib.ZLIB_RUNTIME_VERSION,
        image_id=IMAGE_ID,
        image_platform="linux/amd64",
        base_image_digest="1" * 64,
        toolchain_sbom_sha256="2" * 64,
        calibre_artifact_sha256="3" * 64,
        epubcheck_version="5.3.0",
        epubcheck_jar_sha256="4" * 64,
        java_runtime="OpenJDK synthetic-test",
        config_sha256="5" * 64,
        environment_sha256="6" * 64,
    )


def _zip_bytes(
    entries: list[tuple[str, bytes]],
    *,
    zip_time: tuple[int, int, int, int, int, int] = (2026, 8, 26, 9, 0, 0),
    compression: int = zipfile.ZIP_STORED,
    attributes: dict[str, tuple[int, int]] | None = None,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        for name, content in entries:
            info = zipfile.ZipInfo(name, date_time=zip_time)
            info.compress_type = zipfile.ZIP_STORED if name == "mimetype" else compression
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            if attributes and name in attributes:
                info.create_system, info.external_attr = attributes[name]
            archive.writestr(info, content)
    return output.getvalue()


def _calibre_like_output(
    generator: ModuleType,
    *,
    modified: str,
    zip_time: tuple[int, int, int, int, int, int],
    reverse: bool = False,
) -> bytes:
    package = generator.PACKAGE.replace(
        b"Synthetischer Ausgangstitel", b"Synthetischer Zieltitel"
    ).replace(
        b"Ausgangstitel, Synthetischer", b"Zieltitel, Synthetischer"
    ).replace(
        b"2026-08-26T09:00:00Z", modified.encode("ascii")
    )
    entries = [
        (name, package if name == "EPUB/package.opf" else content)
        for name, content in generator.ENTRIES
    ]
    if reverse:
        entries = entries[:1] + list(reversed(entries[1:]))
    return _zip_bytes(entries, zip_time=zip_time)


def _replace_package(generator: ModuleType, package: bytes) -> bytes:
    return _zip_bytes(
        [
            (name, package if name == "EPUB/package.opf" else content)
            for name, content in generator.ENTRIES
        ]
    )


def _preflight_then_run(data: bytes, runner: Callable[[], None]) -> None:
    inspect_epub3(data, _profile())
    runner()


def test_gate_0002_fixture_and_snapshot_are_complete_and_byte_stable(
    tmp_path: Path,
) -> None:
    generator = _load_generator()
    first = generator.generate_fixture(tmp_path / "first")
    second = generator.generate_fixture(tmp_path / "second")

    assert first == second
    assert (tmp_path / "first/source.epub").read_bytes() == (
        tmp_path / "second/source.epub"
    ).read_bytes()
    snapshot = _snapshot()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert first == {
        key: manifest[key]
        for key in (
            "profile",
            "reviewed_metadata_sha256",
            "reviewed_metadata_size_bytes",
            "source_sha256",
            "source_size_bytes",
        )
    }
    assert tuple(item.key for item in snapshot.fields) == METADATA_INVENTORY_KEYS
    assert snapshot.technical_delta_allowlist == ("dcterms:modified",)
    assert len(snapshot.snapshot_sha256) == 64
    assert snapshot.snapshot_sha256 == manifest["metadata_snapshot_sha256"]
    source = inspect_epub3((tmp_path / "first/source.epub").read_bytes(), _profile())
    assert source.package_member_name == "EPUB/package.opf"
    assert source.metadata_by_key["series_name"] == ("Synthetische Reihe",)
    assert source.metadata_by_key["contributors"] == (
        "contributor|Berta Muster|trl|Muster, Berta",
        "creator|Ada Beispiel|aut|Beispiel, Ada",
    )


def test_gate_0002_two_fresh_runs_are_exact_and_replay_is_idempotent() -> None:
    generator = _load_generator()
    first_raw = _calibre_like_output(
        generator,
        modified="2026-08-26T09:01:02Z",
        zip_time=(2026, 8, 26, 9, 1, 2),
    )
    second_raw = _calibre_like_output(
        generator,
        modified="2026-08-26T09:01:08Z",
        zip_time=(2026, 8, 26, 9, 1, 8),
        reverse=True,
    )
    assert first_raw != second_raw

    first = canonicalize_epub3(first_raw, _snapshot(), _profile())
    second = canonicalize_epub3(second_raw, _snapshot(), _profile())

    assert first.epub_bytes == second.epub_bytes
    assert first.sha256 == second.sha256
    assert first.size_bytes == second.size_bytes
    replay = verify_canonical_epub3(first.epub_bytes, _snapshot(), _profile())
    assert replay.epub_bytes == first.epub_bytes
    assert replay.sha256 == first.sha256


def test_gate_0002_profile_binds_runtime_and_canonical_zip_headers() -> None:
    generator = _load_generator()
    result = canonicalize_epub3(
        _calibre_like_output(
            generator,
            modified="2026-08-26T09:01:02Z",
            zip_time=(2026, 8, 26, 9, 1, 2),
        ),
        _snapshot(),
        _profile(),
    )
    assert len(result.profile_sha256) == 64
    with zipfile.ZipFile(io.BytesIO(result.epub_bytes)) as archive:
        infos = archive.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert [info.filename for info in infos[1:]] == sorted(
            info.filename for info in infos[1:]
        )
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in infos)
        assert all(info.flag_bits == 0x0800 for info in infos)
        assert all(info.extra == b"" and info.comment == b"" for info in infos)
        assert all(info.create_system == 3 and info.create_version == 20 for info in infos)
        assert all(info.extract_version == 20 for info in infos)
        assert all(info.external_attr == 0o100644 << 16 for info in infos)
        assert archive.comment == b""


def test_gate_0002_preserves_navigation_spine_text_cover_and_payload_hashes() -> None:
    generator = _load_generator()
    source_bytes = _zip_bytes(list(generator.ENTRIES))
    raw = _calibre_like_output(
        generator,
        modified="2026-08-26T09:01:02Z",
        zip_time=(2026, 8, 26, 9, 1, 2),
    )
    source = inspect_epub3(source_bytes, _profile())
    before = inspect_epub3(raw, _profile())
    result = canonicalize_epub3(raw, _snapshot(), _profile())
    after = inspect_epub3(result.epub_bytes, _profile())
    source_hashes = {item.name: item.content_sha256 for item in source.members}
    before_hashes = {item.name: item.content_sha256 for item in before.members}
    after_hashes = {item.name: item.content_sha256 for item in after.members}

    assert after.metadata_by_key == _snapshot().values_by_key
    for field in _snapshot().fields:
        if field.disposition is MetadataDisposition.PRESERVE:
            assert source.metadata_by_key[field.key] == field.values
    for name in (
        "META-INF/container.xml",
        "EPUB/nav.xhtml",
        "EPUB/chapter.xhtml",
        "EPUB/cover.png",
        "mimetype",
    ):
        assert source_hashes[name] == before_hashes[name] == after_hashes[name]
    with zipfile.ZipFile(io.BytesIO(result.epub_bytes)) as archive:
        package = archive.read("EPUB/package.opf")
        assert b"Synthetischer Zieltitel" in package
        assert b"2026-08-26T09:00:00Z" in package
        assert archive.read("EPUB/chapter.xhtml") == generator.CHAPTER
        assert archive.read("EPUB/cover.png") == generator.COVER


def test_gate_0002_runner_rejects_source_payload_drift() -> None:
    generator = _load_generator()
    runner = _load_gate_runner()
    source = _zip_bytes(list(generator.ENTRIES))
    raw = _calibre_like_output(
        generator,
        modified="2026-08-26T09:01:02Z",
        zip_time=(2026, 8, 26, 9, 1, 2),
    )
    runner._verify_source_preservation(source, raw, _snapshot(), _profile())
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        changed = _zip_bytes(
            [
                (
                    info.filename,
                    b"changed synthetic text"
                    if info.filename == "EPUB/chapter.xhtml"
                    else archive.read(info.filename),
                )
                for info in archive.infolist()
            ]
        )
    with pytest.raises(ValueError, match="preserved source payload changed"):
        runner._verify_source_preservation(source, changed, _snapshot(), _profile())

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        changed_structure = _zip_bytes(
            [
                (
                    info.filename,
                    archive.read(info.filename).replace(
                        b'media-type="application/xhtml+xml"',
                        b'media-type="text/plain"',
                        1,
                    )
                    if info.filename == "EPUB/package.opf"
                    else archive.read(info.filename),
                )
                for info in archive.infolist()
            ]
        )
    with pytest.raises(ValueError, match="package structure changed"):
        runner._verify_source_preservation(
            source,
            changed_structure,
            _snapshot(),
            _profile(),
        )


def test_gate_0002_snapshot_rejects_omission_and_invalid_lineage() -> None:
    snapshot = _snapshot()
    with pytest.raises(EbookTransformError) as omitted:
        TransformMetadataSnapshot(
            fields=snapshot.fields[:-1],
            technical_modified_utc=snapshot.technical_modified_utc,
        )
    assert omitted.value.code is EbookTransformErrorCode.SNAPSHOT_INVALID

    with pytest.raises(EbookTransformError) as unreviewed:
        TransformMetadataField(
            key="title",
            values=("Synthetic",),
            provenance=MetadataProvenance.USER_CONFIRMED,
            disposition=MetadataDisposition.REVIEWED,
        )
    assert unreviewed.value.code is EbookTransformErrorCode.SNAPSHOT_INVALID


@pytest.mark.parametrize(
    "payload",
    [
        "python:def evaluate(book, context): return 'x'",
        'program: template("python:def evaluate(book, context): return \'x\'")',
    ],
)
def test_gate_0002_rejects_calibre_python_metadata_before_tool_invocation(
    payload: str,
) -> None:
    generator = _load_generator()
    injected = (
        '<meta name="calibre:user_metadata:#attack" content='
        + quoteattr(json.dumps({"display": {"composite_template": payload}}))
        + "/>"
    ).encode()
    package = generator.PACKAGE.replace(b"  </metadata>", b"    " + injected + b"\n  </metadata>")
    data = _replace_package(generator, package)
    invocations = 0

    def runner() -> None:
        nonlocal invocations
        invocations += 1

    with pytest.raises(EbookTransformError) as rejected:
        _preflight_then_run(data, runner)
    assert rejected.value.code is EbookTransformErrorCode.UNSAFE_CALIBRE_METADATA
    assert invocations == 0


@pytest.mark.parametrize(
    "name",
    [
        "/absolute.xhtml",
        "C:drive.xhtml",
        "EPUB\\backslash.xhtml",
        "EPUB/./dot.xhtml",
        "EPUB/../parent.xhtml",
        "EPUB//empty.xhtml",
        "EPUB/bad:name.xhtml",
        'EPUB/bad"name.xhtml',
        "EPUB/bad*name.xhtml",
        "EPUB/bad<name.xhtml",
        "EPUB/bad>name.xhtml",
        "EPUB/bad?name.xhtml",
        "EPUB/bad|name.xhtml",
        "EPUB/trailing.",
    ],
)
def test_gate_0002_rejects_unsafe_member_names(name: str) -> None:
    generator = _load_generator()
    zip_name = name.replace("\\", "/")
    entries = list(generator.ENTRIES) + [(zip_name, b"x")]
    data = _zip_bytes(entries)
    if "\\" in name:
        data = data.replace(zip_name.encode(), name.encode())
    with pytest.raises(EbookTransformError) as rejected:
        inspect_epub3(data, _profile())
    assert rejected.value.code is EbookTransformErrorCode.ENTRY_NAME_INVALID


@pytest.mark.parametrize(
    "names",
    [
        ("EPUB/duplicate.xhtml", "EPUB/duplicate.xhtml"),
        ("EPUB/Case.xhtml", "epub/case.xhtml"),
        ("EPUB/caf\u00e9.xhtml", "EPUB/cafe\u0301.xhtml"),
    ],
)
def test_gate_0002_rejects_duplicate_nfc_and_casefold_collisions(
    names: tuple[str, str],
) -> None:
    generator = _load_generator()
    entries = list(generator.ENTRIES) + [(names[0], b"a"), (names[1], b"b")]
    with pytest.warns(UserWarning) if names[0] == names[1] else _no_warning():
        data = _zip_bytes(entries)
    with pytest.raises(EbookTransformError) as rejected:
        inspect_epub3(data, _profile())
    assert rejected.value.code in {
        EbookTransformErrorCode.ENTRY_DUPLICATE,
        EbookTransformErrorCode.ENTRY_NAME_INVALID,
    }


@pytest.mark.parametrize(
    ("create_system", "external_attr"),
    [
        (3, (stat.S_IFLNK | 0o777) << 16),
        (3, (stat.S_IFIFO | 0o600) << 16),
        (0, 0x0400),
    ],
)
def test_gate_0002_rejects_link_reparse_and_hardlink_like_entries(
    create_system: int,
    external_attr: int,
) -> None:
    generator = _load_generator()
    entries = list(generator.ENTRIES) + [("EPUB/link", b"target")]
    data = _zip_bytes(
        entries,
        attributes={"EPUB/link": (create_system, external_attr)},
    )
    with pytest.raises(EbookTransformError) as rejected:
        inspect_epub3(data, _profile())
    assert rejected.value.code is EbookTransformErrorCode.ENTRY_LINK_UNSUPPORTED


def test_gate_0002_rejects_zip64_encryption_and_unsupported_compression() -> None:
    generator = _load_generator()
    baseline = bytearray(_zip_bytes(list(generator.ENTRIES)))
    eocd = baseline.rfind(b"PK\x05\x06")
    struct.pack_into("<H", baseline, eocd + 10, 0xFFFF)
    with pytest.raises(EbookTransformError) as zip64:
        inspect_epub3(bytes(baseline), _profile())
    assert zip64.value.code is EbookTransformErrorCode.ARCHIVE_FEATURE_UNSUPPORTED

    encrypted = bytearray(_zip_bytes(list(generator.ENTRIES)))
    first_local = encrypted.find(b"PK\x03\x04")
    first_central = encrypted.find(b"PK\x01\x02")
    struct.pack_into("<H", encrypted, first_local + 6, 1)
    struct.pack_into("<H", encrypted, first_central + 8, 1)
    with pytest.raises(EbookTransformError) as encryption:
        inspect_epub3(bytes(encrypted), _profile())
    assert encryption.value.code is EbookTransformErrorCode.ENTRY_ENCRYPTED

    unsupported = bytearray(_zip_bytes(list(generator.ENTRIES)))
    second_local = unsupported.find(b"PK\x03\x04", unsupported.find(b"PK\x03\x04") + 4)
    second_central = unsupported.find(b"PK\x01\x02", unsupported.find(b"PK\x01\x02") + 4)
    struct.pack_into("<H", unsupported, second_local + 8, 12)
    struct.pack_into("<H", unsupported, second_central + 10, 12)
    with pytest.raises(EbookTransformError) as compression:
        inspect_epub3(bytes(unsupported), _profile())
    assert compression.value.code is EbookTransformErrorCode.ENTRY_COMPRESSION_UNSUPPORTED


def test_gate_0002_rejects_ratio_member_aggregate_and_entry_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _load_generator()
    bomb = _zip_bytes(
        list(generator.ENTRIES) + [("EPUB/bomb.bin", b"a" * 100_000)],
        compression=zipfile.ZIP_DEFLATED,
    )
    with pytest.raises(EbookTransformError) as ratio:
        inspect_epub3(bomb, _profile())
    assert ratio.value.code is EbookTransformErrorCode.ENTRY_RATIO_UNSUPPORTED

    monkeypatch.setattr(profile_module, "MAX_MEMBER_BYTES", 8)
    with pytest.raises(EbookTransformError) as member:
        inspect_epub3(_zip_bytes(list(generator.ENTRIES)), _profile())
    assert member.value.code is EbookTransformErrorCode.ENTRY_SIZE_UNSUPPORTED
    monkeypatch.setattr(profile_module, "MAX_MEMBER_BYTES", 64 * 1024 * 1024)
    monkeypatch.setattr(profile_module, "MAX_TOTAL_UNCOMPRESSED_BYTES", 32)
    with pytest.raises(EbookTransformError) as aggregate:
        inspect_epub3(_zip_bytes(list(generator.ENTRIES)), _profile())
    assert aggregate.value.code is EbookTransformErrorCode.ENTRY_SIZE_UNSUPPORTED
    monkeypatch.setattr(profile_module, "MAX_TOTAL_UNCOMPRESSED_BYTES", 256 * 1024 * 1024)
    monkeypatch.setattr(profile_module, "MAX_ENTRIES", 2)
    with pytest.raises(EbookTransformError) as count:
        inspect_epub3(_zip_bytes(list(generator.ENTRIES)), _profile())
    assert count.value.code is EbookTransformErrorCode.ENTRY_LIMIT_EXCEEDED


def test_gate_0002_rejects_multiple_rootfiles_malformed_xml_and_unknown_metadata() -> None:
    generator = _load_generator()
    multiple = generator.CONTAINER.replace(
        b"</rootfiles>",
        b'<rootfile full-path="EPUB/second.opf" '
        b'media-type="application/oebps-package+xml"/></rootfiles>',
    )
    entries = [
        (name, multiple if name == "META-INF/container.xml" else content)
        for name, content in generator.ENTRIES
    ] + [("EPUB/second.opf", generator.PACKAGE)]
    with pytest.raises(EbookTransformError) as rootfiles:
        inspect_epub3(_zip_bytes(entries), _profile())
    assert rootfiles.value.code is EbookTransformErrorCode.CONTAINER_INVALID

    malformed = generator.PACKAGE.replace(b"</metadata>", b"</broken>")
    with pytest.raises(EbookTransformError) as xml:
        inspect_epub3(_replace_package(generator, malformed), _profile())
    assert xml.value.code is EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID

    unknown = generator.PACKAGE.replace(
        b"  </metadata>", b'    <meta property="unknown:value">x</meta>\n  </metadata>'
    )
    with pytest.raises(EbookTransformError) as metadata:
        inspect_epub3(_replace_package(generator, unknown), _profile())
    assert metadata.value.code is EbookTransformErrorCode.METADATA_UNREPRESENTABLE

    orphan = generator.PACKAGE.replace(
        b"  </metadata>",
        b'    <meta refines="#missing" property="role">evil</meta>\n  </metadata>',
    )
    with pytest.raises(EbookTransformError) as refinement:
        inspect_epub3(_replace_package(generator, orphan), _profile())
    assert refinement.value.code is EbookTransformErrorCode.METADATA_UNREPRESENTABLE

    unknown_attribute = generator.PACKAGE.replace(
        b'<dc:publisher>FolioTone Testverlag</dc:publisher>',
        b'<dc:publisher unknown="evil">FolioTone Testverlag</dc:publisher>',
    )
    with pytest.raises(EbookTransformError) as attribute:
        inspect_epub3(_replace_package(generator, unknown_attribute), _profile())
    assert attribute.value.code is EbookTransformErrorCode.METADATA_UNREPRESENTABLE

    namespaced_attribute = generator.PACKAGE.replace(
        b'<dc:title id="title">',
        b'<dc:title xmlns:x="urn:evil" x:id="title">',
    )
    with pytest.raises(EbookTransformError) as namespaced:
        inspect_epub3(_replace_package(generator, namespaced_attribute), _profile())
    assert namespaced.value.code is EbookTransformErrorCode.METADATA_UNREPRESENTABLE


@pytest.mark.parametrize(
    ("needle", "replacement"),
    (
        (
            b"<metadata>",
            b'<metadata xmlns:x="urn:evil" x:id="evil">',
        ),
        (b"<metadata>", b"<metadata>evil"),
        (b"</dc:publisher>", b"</dc:publisher>evil"),
    ),
)
def test_gate_0002_rejects_metadata_container_attributes_or_mixed_content(
    needle: bytes,
    replacement: bytes,
) -> None:
    generator = _load_generator()
    package = generator.PACKAGE.replace(needle, replacement, 1)

    with pytest.raises(EbookTransformError) as rejected:
        inspect_epub3(_replace_package(generator, package), _profile())
    assert rejected.value.code is EbookTransformErrorCode.METADATA_UNREPRESENTABLE


@pytest.mark.parametrize(
    "package",
    [
        b'<!DOCTYPE package [<!ENTITY attack "x">]><package/>',
        b"\xff\xfe<package/>",
    ],
)
def test_gate_0002_rejects_doctype_entity_and_invalid_utf8(package: bytes) -> None:
    generator = _load_generator()
    with pytest.raises(EbookTransformError) as rejected:
        inspect_epub3(_replace_package(generator, package), _profile())
    assert rejected.value.code is EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID


def test_gate_0002_rejects_corrupt_zip() -> None:
    generator = _load_generator()
    data = bytearray(_zip_bytes(list(generator.ENTRIES)))
    data[0:4] = b"FAIL"
    with pytest.raises(EbookTransformError) as rejected:
        inspect_epub3(bytes(data), _profile())
    assert rejected.value.code in {
        EbookTransformErrorCode.ENTRY_UNREADABLE,
        EbookTransformErrorCode.ARCHIVE_INVALID,
    }


class _no_warning:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_args: object) -> None:
        return None


def test_gate_0002_readme_forbids_committed_outputs_and_authority() -> None:
    readme = (FIXTURE_ROOT / "README.md").read_text(encoding="utf-8")
    assert "nicht eingecheckt" in readme
    assert "keine Writer-,\nPublish- oder W10-Autorisierung" in readme
    assert "den externen Prozess nicht" in readme


def test_gate_0002_profile_rejects_unbound_runtime() -> None:
    with pytest.raises(EbookTransformError) as rejected:
        replace(_profile(), zlib_runtime_version="")
    assert rejected.value.code is EbookTransformErrorCode.PROFILE_INVALID
