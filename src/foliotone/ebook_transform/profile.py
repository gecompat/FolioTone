"""Bounded EPUB inspection, OPF normalization, and canonical packaging."""

from __future__ import annotations

import copy
import hashlib
import io
import re
import stat
import struct
import unicodedata
import xml.etree.ElementTree as ElementTree
import zipfile
import zlib
from dataclasses import dataclass
from typing import Final

from .contracts import (
    MAX_ARCHIVE_BYTES,
    MAX_COMPRESSION_RATIO,
    MAX_CONTAINER_BYTES,
    MAX_ENTRIES,
    MAX_MEMBER_BYTES,
    MAX_MEMBER_COMPONENT_BYTES,
    MAX_MEMBER_NAME_BYTES,
    MAX_PACKAGE_BYTES,
    MAX_TOTAL_UNCOMPRESSED_BYTES,
    MAX_XML_DEPTH,
    MAX_XML_ELEMENTS,
    CanonicalEpubProfile,
    CanonicalEpubResult,
    EbookTransformError,
    EbookTransformErrorCode,
    EpubInspection,
    EpubMemberInspection,
    TransformMetadataSnapshot,
    fail,
)

_OCF_NAMESPACE: Final = "urn:oasis:names:tc:opendocument:xmlns:container"
_OPF_NAMESPACE: Final = "http://www.idpf.org/2007/opf"
_DC_NAMESPACE: Final = "http://purl.org/dc/elements/1.1/"
_CONTAINER_PATH: Final = "META-INF/container.xml"
_PACKAGE_MEDIA_TYPE: Final = "application/oebps-package+xml"
_EPUB_MIMETYPE: Final = b"application/epub+zip"
_SIGNATURE_PATH: Final = "META-INF/signatures.xml"
_ENCRYPTION_PATH: Final = "META-INF/encryption.xml"
_READ_CHUNK_BYTES: Final = 1024 * 1024

_EOCD = struct.Struct("<4s4H2LH")
_CENTRAL_HEADER = struct.Struct("<4s6H3L5H2L")
_LOCAL_HEADER = struct.Struct("<4s5H3L2H")
_EOCD_SIGNATURE = b"PK\x05\x06"
_CENTRAL_SIGNATURE = b"PK\x01\x02"
_LOCAL_SIGNATURE = b"PK\x03\x04"
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_FORBIDDEN_XML = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_EPUB3_VERSION = re.compile(r"3(?:\.[0-9]+)*\Z")
_FORBIDDEN_MEMBER_NAME_CHARACTERS = frozenset('"*:<>?\\|')

_ALLOWED_DC_FIELDS = frozenset(
    {
        "title",
        "identifier",
        "creator",
        "contributor",
        "language",
        "publisher",
        "date",
        "subject",
        "description",
        "rights",
        "type",
    }
)
_ALLOWED_REFINEMENTS = frozenset(
    {
        "collection-type",
        "file-as",
        "group-position",
        "identifier-type",
        "role",
        "title-type",
    }
)
_ALLOWED_LEGACY_META = frozenset(
    {
        "calibre:rating",
        "calibre:series",
        "calibre:series_index",
        "calibre:title_sort",
    }
)
_REFINEMENTS_BY_TARGET = {
    "title": frozenset({"file-as", "title-type"}),
    "identifier": frozenset({"identifier-type"}),
    "creator": frozenset({"file-as", "role"}),
    "contributor": frozenset({"file-as", "role"}),
    "collection": frozenset({"collection-type", "group-position"}),
}


@dataclass(frozen=True, slots=True)
class _LoadedArchive:
    inspection: EpubInspection
    member_order: tuple[str, ...]
    member_content: dict[str, bytes]
    package_document: bytes


def inspect_epub3(data: bytes, profile: CanonicalEpubProfile) -> EpubInspection:
    """Validate an EPUB without paths, extraction, external tools, or mutation."""
    _ = profile.identity_sha256
    return _load_archive(data).inspection


def canonicalize_epub3(
    calibre_output: bytes,
    snapshot: TransformMetadataSnapshot,
    profile: CanonicalEpubProfile,
) -> CanonicalEpubResult:
    """Normalize one untrusted calibre output into the fixed GATE-0002 profile."""
    source = _load_archive(calibre_output)
    if source.inspection.metadata_by_key != snapshot.values_by_key:
        fail(EbookTransformErrorCode.METADATA_SNAPSHOT_MISMATCH)

    package_document = _normalize_package_document(
        source.package_document,
        snapshot.technical_modified_utc,
    )
    normalized_values = _project_metadata(_parse_package(package_document))
    if normalized_values != snapshot.values_by_key:
        fail(EbookTransformErrorCode.METADATA_SNAPSHOT_MISMATCH)

    members = dict(source.member_content)
    members[source.inspection.package_member_name] = package_document
    output = _pack_canonical(members, profile)
    verified = _load_archive(output)
    if verified.inspection.metadata_by_key != snapshot.values_by_key:
        fail(EbookTransformErrorCode.METADATA_SNAPSHOT_MISMATCH)
    if verified.inspection.package_member_name != source.inspection.package_member_name:
        fail(EbookTransformErrorCode.PAYLOAD_PRESERVATION_FAILED)
    if (
        verified.inspection.package_structure_sha256
        != source.inspection.package_structure_sha256
    ):
        fail(EbookTransformErrorCode.PAYLOAD_PRESERVATION_FAILED)
    _verify_preserved_payloads(source, verified)

    return CanonicalEpubResult(
        epub_bytes=output,
        sha256=_sha256(output),
        size_bytes=len(output),
        package_document_sha256=verified.inspection.package_document_sha256,
        snapshot_sha256=snapshot.snapshot_sha256,
        profile_sha256=profile.identity_sha256,
        members=verified.inspection.members,
    )


def verify_canonical_epub3(
    data: bytes,
    snapshot: TransformMetadataSnapshot,
    profile: CanonicalEpubProfile,
) -> CanonicalEpubResult:
    """Require replay through the complete profile to be exactly byte-identical."""
    result = canonicalize_epub3(data, snapshot, profile)
    if result.epub_bytes != data:
        fail(EbookTransformErrorCode.OUTPUT_NOT_CANONICAL)
    return result


def _load_archive(data: bytes) -> _LoadedArchive:
    if not data or len(data) > MAX_ARCHIVE_BYTES:
        fail(EbookTransformErrorCode.ARCHIVE_SIZE_UNSUPPORTED)
    expected_entries, central_offset, central_size = _validate_eocd(data)
    _validate_raw_headers(data, expected_entries, central_offset, central_size)
    try:
        with zipfile.ZipFile(io.BytesIO(data), mode="r") as archive:
            infos = archive.infolist()
            if len(infos) != expected_entries or not infos:
                fail(EbookTransformErrorCode.ARCHIVE_INVALID)
            if archive.comment:
                fail(EbookTransformErrorCode.ARCHIVE_FEATURE_UNSUPPORTED)
            if infos[0].header_offset != 0 or infos[0].filename != "mimetype":
                fail(EbookTransformErrorCode.MIMETYPE_INVALID)
            if infos[0].compress_type != zipfile.ZIP_STORED or infos[0].extra:
                fail(EbookTransformErrorCode.MIMETYPE_INVALID)

            seen_names: set[str] = set()
            seen_folded: set[str] = set()
            member_content: dict[str, bytes] = {}
            member_inspections: list[EpubMemberInspection] = []
            total_uncompressed = 0
            for info in infos:
                _validate_member(info, seen_names, seen_folded)
                total_uncompressed += info.file_size
                if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
                    fail(EbookTransformErrorCode.ENTRY_SIZE_UNSUPPORTED)
                content = _read_member(archive, info)
                if info.filename == "mimetype" and content != _EPUB_MIMETYPE:
                    fail(EbookTransformErrorCode.MIMETYPE_INVALID)
                member_content[info.filename] = content
                member_inspections.append(
                    EpubMemberInspection(
                        name=info.filename,
                        content_sha256=_sha256(content),
                        uncompressed_size=len(content),
                        compression=info.compress_type,
                    )
                )
    except EbookTransformError:
        raise
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        RuntimeError,
        NotImplementedError,
        EOFError,
        OSError,
        struct.error,
        zlib.error,
    ) as error:
        raise EbookTransformError(EbookTransformErrorCode.ENTRY_UNREADABLE) from error

    names = tuple(item.name for item in member_inspections)
    if _SIGNATURE_PATH in member_content or _ENCRYPTION_PATH in member_content:
        fail(EbookTransformErrorCode.ARCHIVE_FEATURE_UNSUPPORTED)
    container = member_content.get(_CONTAINER_PATH)
    if container is None or len(container) > MAX_CONTAINER_BYTES:
        fail(EbookTransformErrorCode.CONTAINER_INVALID)
    package_name = _package_name_from_container(container, names)
    package_document = member_content[package_name]
    if len(package_document) > MAX_PACKAGE_BYTES:
        fail(EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID)
    package_root = _parse_package(package_document)
    metadata = _project_metadata(package_root)
    _validate_publication_structure(package_root, package_name, set(names))
    inspection = EpubInspection(
        source_sha256=_sha256(data),
        size_bytes=len(data),
        package_member_name=package_name,
        package_document_sha256=_sha256(package_document),
        package_structure_sha256=_package_structure_sha256(package_root),
        members=tuple(member_inspections),
        metadata_values=tuple((key, metadata[key]) for key in metadata),
    )
    return _LoadedArchive(
        inspection=inspection,
        member_order=names,
        member_content=member_content,
        package_document=package_document,
    )


def _validate_eocd(data: bytes) -> tuple[int, int, int]:
    lower = max(0, len(data) - _EOCD.size - 65_535)
    for offset in range(len(data) - _EOCD.size, lower - 1, -1):
        if data[offset : offset + 4] != _EOCD_SIGNATURE:
            continue
        values = _EOCD.unpack_from(data, offset)
        entries = int(values[4])
        central_size = int(values[5])
        central_offset = int(values[6])
        comment_length = int(values[7])
        if offset + _EOCD.size + comment_length != len(data):
            continue
        if (
            int(values[1]) != 0
            or int(values[2]) != 0
            or int(values[3]) != entries
            or entries == 0xFFFF
            or central_size == 0xFFFFFFFF
            or central_offset == 0xFFFFFFFF
            or central_offset + central_size != offset
            or comment_length != 0
            or (offset >= 20 and data[offset - 20 : offset - 16] == _ZIP64_LOCATOR_SIGNATURE)
        ):
            fail(EbookTransformErrorCode.ARCHIVE_FEATURE_UNSUPPORTED)
        if not 1 <= entries <= MAX_ENTRIES:
            fail(EbookTransformErrorCode.ENTRY_LIMIT_EXCEEDED)
        return entries, central_offset, central_size
    fail(EbookTransformErrorCode.ARCHIVE_INVALID)


def _validate_raw_headers(
    data: bytes,
    entries: int,
    central_offset: int,
    central_size: int,
) -> None:
    pointer = central_offset
    end = central_offset + central_size
    raw_names: set[bytes] = set()
    decoded_names: set[str] = set()
    folded_names: set[str] = set()
    for _ in range(entries):
        if pointer + _CENTRAL_HEADER.size > end:
            fail(EbookTransformErrorCode.ARCHIVE_INVALID)
        values = _CENTRAL_HEADER.unpack_from(data, pointer)
        if values[0] != _CENTRAL_SIGNATURE:
            fail(EbookTransformErrorCode.ARCHIVE_INVALID)
        flags = int(values[3])
        name_length = int(values[10])
        extra_length = int(values[11])
        comment_length = int(values[12])
        local_offset = int(values[16])
        variable_start = pointer + _CENTRAL_HEADER.size
        variable_end = variable_start + name_length + extra_length + comment_length
        if name_length == 0 or variable_end > end or extra_length or comment_length:
            fail(EbookTransformErrorCode.ARCHIVE_FEATURE_UNSUPPORTED)
        raw_name = data[variable_start : variable_start + name_length]
        decoded_name = _decode_raw_name(raw_name, flags)
        _validate_member_name(decoded_name)
        normalized = unicodedata.normalize("NFC", decoded_name)
        folded = normalized.casefold()
        if (
            raw_name in raw_names
            or decoded_name in decoded_names
            or folded in folded_names
        ):
            fail(EbookTransformErrorCode.ENTRY_DUPLICATE)
        raw_names.add(raw_name)
        decoded_names.add(decoded_name)
        folded_names.add(folded)
        if local_offset + _LOCAL_HEADER.size > central_offset:
            fail(EbookTransformErrorCode.ARCHIVE_INVALID)
        local = _LOCAL_HEADER.unpack_from(data, local_offset)
        if local[0] != _LOCAL_SIGNATURE:
            fail(EbookTransformErrorCode.ARCHIVE_INVALID)
        local_name_length = int(local[9])
        local_extra_length = int(local[10])
        local_name_start = local_offset + _LOCAL_HEADER.size
        local_name_end = local_name_start + local_name_length
        if (
            local_name_end + local_extra_length > central_offset
            or local_extra_length
            or data[local_name_start:local_name_end] != raw_name
            or int(local[2]) != flags
            or int(local[3]) != int(values[4])
        ):
            fail(EbookTransformErrorCode.ARCHIVE_FEATURE_UNSUPPORTED)
        pointer = variable_end
    if pointer != end:
        fail(EbookTransformErrorCode.ARCHIVE_INVALID)


def _decode_raw_name(raw_name: bytes, flags: int) -> str:
    if b"\x00" in raw_name or b"\\" in raw_name:
        fail(EbookTransformErrorCode.ENTRY_NAME_INVALID)
    try:
        if flags & 0x0800:
            return raw_name.decode("utf-8")
        if any(value >= 0x80 for value in raw_name):
            fail(EbookTransformErrorCode.ENTRY_NAME_INVALID)
        return raw_name.decode("ascii")
    except UnicodeDecodeError as error:
        raise EbookTransformError(EbookTransformErrorCode.ENTRY_NAME_INVALID) from error


def _validate_member(
    info: zipfile.ZipInfo,
    seen_names: set[str],
    seen_folded: set[str],
) -> None:
    _validate_member_name(info.filename)
    normalized = unicodedata.normalize("NFC", info.filename)
    folded = normalized.casefold()
    if info.filename in seen_names or folded in seen_folded:
        fail(EbookTransformErrorCode.ENTRY_DUPLICATE)
    seen_names.add(info.filename)
    seen_folded.add(folded)
    if normalized != info.filename:
        fail(EbookTransformErrorCode.ENTRY_NAME_INVALID)
    if info.flag_bits & (0x0001 | 0x0040 | 0x2000):
        fail(EbookTransformErrorCode.ENTRY_ENCRYPTED)
    if info.flag_bits & ~(0x0800):
        fail(EbookTransformErrorCode.ARCHIVE_FEATURE_UNSUPPORTED)
    if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
        fail(EbookTransformErrorCode.ENTRY_COMPRESSION_UNSUPPORTED)
    if info.extra or info.comment or info.volume != 0:
        fail(EbookTransformErrorCode.ARCHIVE_FEATURE_UNSUPPORTED)
    if info.file_size > MAX_MEMBER_BYTES or info.compress_size > MAX_ARCHIVE_BYTES:
        fail(EbookTransformErrorCode.ENTRY_SIZE_UNSUPPORTED)
    if info.file_size and (
        info.compress_size == 0
        or info.file_size > info.compress_size * MAX_COMPRESSION_RATIO
    ):
        fail(EbookTransformErrorCode.ENTRY_RATIO_UNSUPPORTED)
    unix_mode = info.external_attr >> 16
    if info.is_dir() or (unix_mode and stat.S_IFMT(unix_mode) != stat.S_IFREG):
        fail(EbookTransformErrorCode.ENTRY_LINK_UNSUPPORTED)
    if info.external_attr & 0x0400:
        fail(EbookTransformErrorCode.ENTRY_LINK_UNSUPPORTED)


def _validate_member_name(name: str) -> None:
    try:
        raw_name = name.encode("utf-8")
    except UnicodeEncodeError as error:
        raise EbookTransformError(EbookTransformErrorCode.ENTRY_NAME_INVALID) from error
    if (
        not name
        or len(raw_name) > MAX_MEMBER_NAME_BYTES
        or name.startswith("/")
        or name.endswith("/")
        or "\\" in name
        or any(character in _FORBIDDEN_MEMBER_NAME_CHARACTERS for character in name)
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in name)
    ):
        fail(EbookTransformErrorCode.ENTRY_NAME_INVALID)
    parts = name.split("/")
    if any(
        part in {"", ".", ".."}
        or part.endswith(".")
        or len(part.encode("utf-8")) > MAX_MEMBER_COMPONENT_BYTES
        for part in parts
    ):
        fail(EbookTransformErrorCode.ENTRY_NAME_INVALID)


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    content = bytearray()
    try:
        with archive.open(info, mode="r") as member:
            while chunk := member.read(_READ_CHUNK_BYTES):
                if len(content) + len(chunk) > MAX_MEMBER_BYTES:
                    fail(EbookTransformErrorCode.ENTRY_SIZE_UNSUPPORTED)
                content.extend(chunk)
    except EbookTransformError:
        raise
    except (
        zipfile.BadZipFile,
        RuntimeError,
        NotImplementedError,
        EOFError,
        OSError,
        zlib.error,
    ) as error:
        raise EbookTransformError(EbookTransformErrorCode.ENTRY_UNREADABLE) from error
    if len(content) != info.file_size:
        fail(EbookTransformErrorCode.ENTRY_UNREADABLE)
    return bytes(content)


def _parse_xml(data: bytes, max_bytes: int, code: EbookTransformErrorCode) -> ElementTree.Element:
    if not data or len(data) > max_bytes or _FORBIDDEN_XML.search(data):
        fail(code)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EbookTransformError(code) from error
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise EbookTransformError(code) from error
    count = 0
    stack = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        count += 1
        if count > MAX_XML_ELEMENTS or depth > MAX_XML_DEPTH:
            fail(code)
        stack.extend((child, depth + 1) for child in element)
    return root


def _package_name_from_container(container: bytes, names: tuple[str, ...]) -> str:
    root = _parse_xml(container, MAX_CONTAINER_BYTES, EbookTransformErrorCode.CONTAINER_INVALID)
    if root.tag != f"{{{_OCF_NAMESPACE}}}container":
        fail(EbookTransformErrorCode.CONTAINER_INVALID)
    rootfiles = tuple(
        child
        for parent in root
        if parent.tag == f"{{{_OCF_NAMESPACE}}}rootfiles"
        for child in parent
        if child.tag == f"{{{_OCF_NAMESPACE}}}rootfile"
    )
    if len(rootfiles) != 1:
        fail(EbookTransformErrorCode.CONTAINER_INVALID)
    package_name = rootfiles[0].attrib.get("full-path", "")
    if rootfiles[0].attrib.get("media-type") != _PACKAGE_MEDIA_TYPE:
        fail(EbookTransformErrorCode.CONTAINER_INVALID)
    _validate_member_name(package_name)
    if package_name not in names:
        fail(EbookTransformErrorCode.CONTAINER_INVALID)
    return package_name


def _parse_package(package_document: bytes) -> ElementTree.Element:
    root = _parse_xml(
        package_document,
        MAX_PACKAGE_BYTES,
        EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID,
    )
    if root.tag != f"{{{_OPF_NAMESPACE}}}package" or _EPUB3_VERSION.fullmatch(
        root.attrib.get("version", "")
    ) is None:
        fail(EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID)
    metadata = tuple(child for child in root if child.tag == f"{{{_OPF_NAMESPACE}}}metadata")
    if len(metadata) != 1:
        fail(EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID)
    _validate_metadata_container(metadata[0])
    _reject_unsafe_calibre_metadata(metadata[0])
    return root


def _validate_metadata_container(metadata: ElementTree.Element) -> None:
    if metadata.attrib or (metadata.text is not None and metadata.text.strip()):
        fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)
    if any(child.tail is not None and child.tail.strip() for child in metadata):
        fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)


def _reject_unsafe_calibre_metadata(metadata: ElementTree.Element) -> None:
    for element in metadata:
        if _local_name(element.tag) != "meta":
            continue
        name = (_attribute(element, "name") or _attribute(element, "property")).casefold()
        if name.startswith("calibre:user_metadata"):
            fail(EbookTransformErrorCode.UNSAFE_CALIBRE_METADATA)


def _project_metadata(root: ElementTree.Element) -> dict[str, tuple[str, ...]]:
    metadata = next(child for child in root if child.tag == f"{{{_OPF_NAMESPACE}}}metadata")
    refinements: dict[str, dict[str, list[str]]] = {}
    legacy: dict[str, list[str]] = {key: [] for key in _ALLOWED_LEGACY_META}
    collections: list[ElementTree.Element] = []
    modified_count = 0
    refinement_targets: dict[str, str] = {}

    for element in metadata:
        namespace, local = _expanded_name(element.tag)
        if namespace == _DC_NAMESPACE:
            if local not in _ALLOWED_DC_FIELDS or len(element):
                fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)
            allowed_attributes = {"id"} if local in {
                "title",
                "identifier",
                "creator",
                "contributor",
            } else set()
            if local == "identifier":
                allowed_attributes.add("scheme")
            _require_metadata_attributes(element, allowed_attributes)
            _register_refinement_target(refinement_targets, element, local)
            _required_text(element)
            continue
        if namespace != _OPF_NAMESPACE or local != "meta" or len(element):
            fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)
        property_name = _attribute(element, "property")
        legacy_name = (
            _attribute(element, "name") or _attribute(element, "property")
        ).casefold()
        if property_name == "dcterms:modified":
            _require_metadata_attributes(element, {"property"})
            if _attribute(element, "refines") or not _required_text(element):
                fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)
            modified_count += 1
        elif property_name == "belongs-to-collection":
            _require_metadata_attributes(element, {"id", "property"})
            _required_text(element)
            if not _attribute(element, "id"):
                fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)
            _register_refinement_target(refinement_targets, element, "collection")
            collections.append(element)
        elif property_name in _ALLOWED_REFINEMENTS:
            allowed_attributes = {"property", "refines"}
            if property_name in {"identifier-type", "role"}:
                allowed_attributes.add("scheme")
            _require_metadata_attributes(element, allowed_attributes)
            target = _attribute(element, "refines")
            if not target.startswith("#"):
                fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)
            refinements.setdefault(target[1:], {}).setdefault(property_name, []).append(
                _required_text(element)
            )
        elif legacy_name in _ALLOWED_LEGACY_META:
            _require_metadata_attributes(element, {"content", "name", "property"})
            value = _attribute(element, "content") or _required_text(element)
            if not value:
                fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)
            legacy[legacy_name].append(value)
        else:
            fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)
    if modified_count != 1:
        fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)
    for target, properties in refinements.items():
        target_type = refinement_targets.get(target)
        if target_type is None or any(
            property_name not in _REFINEMENTS_BY_TARGET[target_type]
            or len(values) != 1
            for property_name, values in properties.items()
        ):
            fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)

    def dc_values(name: str) -> tuple[str, ...]:
        return tuple(
            _required_text(element)
            for element in metadata
            if element.tag == f"{{{_DC_NAMESPACE}}}{name}"
        )

    titles = tuple(
        element for element in metadata if element.tag == f"{{{_DC_NAMESPACE}}}title"
    )
    title_values: list[str] = []
    for element in titles:
        title_types = refinements.get(_attribute(element, "id"), {}).get(
            "title-type", []
        )
        if len(title_types) != 1:
            fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)
        title_values.append(f"{title_types[0]}|{_required_text(element)}")
    title_sort = [
        value
        for element in titles
        for value in refinements.get(_attribute(element, "id"), {}).get("file-as", [])
    ]
    title_sort.extend(legacy["calibre:title_sort"])

    identifiers: list[str] = []
    for element in metadata:
        if element.tag != f"{{{_DC_NAMESPACE}}}identifier":
            continue
        identifier_type = refinements.get(_attribute(element, "id"), {}).get(
            "identifier-type", []
        )
        scheme = _attribute(element, "scheme")
        namespace = identifier_type[0] if identifier_type else scheme
        value = _required_text(element)
        if not namespace:
            if value.casefold().startswith("urn:uuid:"):
                namespace = "urn:uuid"
            elif ":" in value:
                namespace = value.split(":", 1)[0]
        if not namespace:
            fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)
        identifiers.append(f"{namespace.casefold()}|{value}")

    contributors: list[str] = []
    for element in metadata:
        namespace, local = _expanded_name(element.tag)
        if namespace != _DC_NAMESPACE or local not in {"creator", "contributor"}:
            continue
        element_refinements = refinements.get(_attribute(element, "id"), {})
        roles = ",".join(element_refinements.get("role", ()))
        sort_names = ",".join(element_refinements.get("file-as", ()))
        contributors.append(f"{local}|{_required_text(element)}|{roles}|{sort_names}")

    series_names = [_required_text(element) for element in collections]
    series_types = [
        value
        for element in collections
        for value in refinements.get(_attribute(element, "id"), {}).get(
            "collection-type", []
        )
    ]
    series_positions = [
        value
        for element in collections
        for value in refinements.get(_attribute(element, "id"), {}).get(
            "group-position", []
        )
    ]
    series_names.extend(legacy["calibre:series"])
    series_positions.extend(legacy["calibre:series_index"])

    return {
        "title": tuple(sorted(title_values)),
        "title_sort": tuple(sorted(title_sort)),
        "identifiers": tuple(sorted(identifiers)),
        "contributors": tuple(sorted(contributors)),
        "language": tuple(sorted(dc_values("language"))),
        "publisher": tuple(sorted(dc_values("publisher"))),
        "publication_date": tuple(sorted(dc_values("date"))),
        "subjects": tuple(sorted(dc_values("subject"))),
        "description": tuple(sorted(dc_values("description"))),
        "rights": tuple(sorted(dc_values("rights"))),
        "type": tuple(sorted(dc_values("type"))),
        "rating": tuple(sorted(legacy["calibre:rating"])),
        "series_name": tuple(sorted(series_names)),
        "series_type": tuple(sorted(series_types)),
        "series_position": tuple(sorted(series_positions)),
    }


def _validate_publication_structure(
    root: ElementTree.Element,
    package_name: str,
    names: set[str],
) -> None:
    manifests = tuple(child for child in root if child.tag == f"{{{_OPF_NAMESPACE}}}manifest")
    spines = tuple(child for child in root if child.tag == f"{{{_OPF_NAMESPACE}}}spine")
    if len(manifests) != 1 or len(spines) != 1:
        fail(EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID)
    items = tuple(
        child for child in manifests[0] if child.tag == f"{{{_OPF_NAMESPACE}}}item"
    )
    if len(items) != len(manifests[0]):
        fail(EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID)
    item_ids = {_attribute(item, "id") for item in items}
    if "" in item_ids or len(item_ids) != len(items):
        fail(EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID)
    nav_count = 0
    cover_count = 0
    for item in items:
        properties = frozenset(_attribute(item, "properties").split())
        nav_count += int("nav" in properties)
        cover_count += int("cover-image" in properties)
        target = _resolve_member_name(package_name, _attribute(item, "href"))
        if target not in names:
            fail(EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID)
    if nav_count != 1 or cover_count != 1:
        fail(EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID)
    itemrefs = tuple(
        child for child in spines[0] if child.tag == f"{{{_OPF_NAMESPACE}}}itemref"
    )
    if (
        not itemrefs
        or len(itemrefs) != len(spines[0])
        or any(_attribute(itemref, "idref") not in item_ids for itemref in itemrefs)
    ):
        fail(EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID)


def _resolve_member_name(package_name: str, href: str) -> str:
    if not href or any(character in href for character in "?#%"):
        fail(EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID)
    prefix = package_name.rsplit("/", 1)[0] if "/" in package_name else ""
    target = f"{prefix}/{href}" if prefix else href
    _validate_member_name(target)
    return target


def _normalize_package_document(package_document: bytes, modified_utc: str) -> bytes:
    root = _parse_package(package_document)
    metadata = next(child for child in root if child.tag == f"{{{_OPF_NAMESPACE}}}metadata")
    modified = tuple(
        child
        for child in metadata
        if child.tag == f"{{{_OPF_NAMESPACE}}}meta"
        and _attribute(child, "property") == "dcterms:modified"
    )
    if len(modified) != 1:
        fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)
    modified[0].text = modified_utc
    metadata[:] = sorted(metadata, key=_metadata_sort_key)
    _sort_manifest_items(root)
    for element in root.iter():
        sorted_attributes = sorted(element.attrib.items(), key=lambda item: item[0])
        element.attrib.clear()
        element.attrib.update(sorted_attributes)
        if element.text is not None and not element.text.strip():
            element.text = None
        if element.tail is not None and not element.tail.strip():
            element.tail = None
    ElementTree.indent(root, space="  ")
    ElementTree.register_namespace("opf", _OPF_NAMESPACE)
    ElementTree.register_namespace("dc", _DC_NAMESPACE)
    output = ElementTree.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True,
        short_empty_elements=True,
    )
    if not isinstance(output, bytes):
        fail(EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID)
    return output.replace(b"\r\n", b"\n") + b"\n"


def _package_structure_sha256(root: ElementTree.Element) -> str:
    structure = copy.deepcopy(root)
    structure[:] = [
        child
        for child in structure
        if child.tag != f"{{{_OPF_NAMESPACE}}}metadata"
    ]
    _sort_manifest_items(structure)
    for element in structure.iter():
        sorted_attributes = sorted(element.attrib.items(), key=lambda item: item[0])
        element.attrib.clear()
        element.attrib.update(sorted_attributes)
        if element.text is not None and not element.text.strip():
            element.text = None
        if element.tail is not None and not element.tail.strip():
            element.tail = None
    ElementTree.indent(structure, space="  ")
    ElementTree.register_namespace("opf", _OPF_NAMESPACE)
    encoded = ElementTree.tostring(
        structure,
        encoding="utf-8",
        short_empty_elements=True,
    )
    if not isinstance(encoded, bytes):
        fail(EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID)
    return _sha256(encoded.replace(b"\r\n", b"\n") + b"\n")


def _sort_manifest_items(root: ElementTree.Element) -> None:
    manifests = tuple(
        child for child in root if child.tag == f"{{{_OPF_NAMESPACE}}}manifest"
    )
    if len(manifests) != 1:
        fail(EbookTransformErrorCode.PACKAGE_DOCUMENT_INVALID)
    manifests[0][:] = sorted(
        manifests[0],
        key=lambda item: (
            _attribute(item, "id"),
            _attribute(item, "href"),
            tuple(sorted(item.attrib.items())),
        ),
    )


def _metadata_sort_key(element: ElementTree.Element) -> tuple[object, ...]:
    return (
        element.tag,
        _attribute(element, "refines"),
        _attribute(element, "property"),
        _attribute(element, "name"),
        _attribute(element, "id"),
        tuple(sorted(element.attrib.items())),
        element.text or "",
    )


def _pack_canonical(members: dict[str, bytes], profile: CanonicalEpubProfile) -> bytes:
    if members.get("mimetype") != _EPUB_MIMETYPE:
        fail(EbookTransformErrorCode.MIMETYPE_INVALID)
    order = ("mimetype",) + tuple(
        sorted(
            (name for name in members if name != "mimetype"),
            key=lambda value: value.encode("utf-8"),
        )
    )
    output = bytearray()
    central: list[bytes] = []
    for name in order:
        _validate_member_name(name)
        content = members[name]
        raw_name = name.encode("utf-8")
        compression = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
        payload = content if compression == zipfile.ZIP_STORED else _raw_deflate(content, profile)
        crc32 = zlib.crc32(content) & 0xFFFFFFFF
        local_offset = len(output)
        modified_time, modified_date = profile.zip_datetime
        output.extend(
            _LOCAL_HEADER.pack(
                _LOCAL_SIGNATURE,
                profile.zip_version_needed,
                profile.zip_utf8_flag,
                compression,
                modified_time,
                modified_date,
                crc32,
                len(payload),
                len(content),
                len(raw_name),
                0,
            )
        )
        output.extend(raw_name)
        output.extend(payload)
        central.append(
            _CENTRAL_HEADER.pack(
                _CENTRAL_SIGNATURE,
                profile.zip_version_made_by,
                profile.zip_version_needed,
                profile.zip_utf8_flag,
                compression,
                modified_time,
                modified_date,
                crc32,
                len(payload),
                len(content),
                len(raw_name),
                0,
                0,
                0,
                0,
                profile.zip_external_attributes,
                local_offset,
            )
            + raw_name
        )
    central_offset = len(output)
    for record in central:
        output.extend(record)
    central_size = len(output) - central_offset
    output.extend(
        _EOCD.pack(
            _EOCD_SIGNATURE,
            0,
            0,
            len(order),
            len(order),
            central_size,
            central_offset,
            0,
        )
    )
    if len(output) > MAX_ARCHIVE_BYTES:
        fail(EbookTransformErrorCode.ARCHIVE_SIZE_UNSUPPORTED)
    return bytes(output)


def _raw_deflate(content: bytes, profile: CanonicalEpubProfile) -> bytes:
    compressor = zlib.compressobj(
        profile.compression_level,
        zlib.DEFLATED,
        profile.compression_wbits,
        profile.compression_mem_level,
        profile.compression_strategy,
    )
    payload = bytearray()
    for offset in range(0, len(content), profile.compression_chunk_bytes):
        payload.extend(
            compressor.compress(content[offset : offset + profile.compression_chunk_bytes])
        )
    payload.extend(compressor.flush(profile.compression_flush_mode))
    return bytes(payload)


def _verify_preserved_payloads(source: _LoadedArchive, output: _LoadedArchive) -> None:
    if set(source.member_content) != set(output.member_content):
        fail(EbookTransformErrorCode.PAYLOAD_PRESERVATION_FAILED)
    package_name = source.inspection.package_member_name
    for name, content in source.member_content.items():
        if name != package_name and output.member_content[name] != content:
            fail(EbookTransformErrorCode.PAYLOAD_PRESERVATION_FAILED)


def _required_text(element: ElementTree.Element) -> str:
    value = element.text or ""
    if not value.strip():
        fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)
    return value


def _require_metadata_attributes(
    element: ElementTree.Element,
    allowed: set[str],
) -> None:
    attribute_names = tuple(element.attrib)
    if len(attribute_names) != len(set(attribute_names)) or any(
        name not in allowed for name in attribute_names
    ):
        fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)


def _register_refinement_target(
    targets: dict[str, str],
    element: ElementTree.Element,
    target_type: str,
) -> None:
    identifier = _attribute(element, "id")
    if not identifier:
        return
    if identifier in targets:
        fail(EbookTransformErrorCode.METADATA_UNREPRESENTABLE)
    targets[identifier] = target_type


def _attribute(element: ElementTree.Element, local_name: str) -> str:
    return element.attrib.get(local_name, "")


def _expanded_name(tag: str) -> tuple[str, str]:
    if tag.startswith("{") and "}" in tag:
        namespace, local = tag[1:].split("}", 1)
        return namespace, local
    return "", tag


def _local_name(tag: str) -> str:
    return _expanded_name(tag)[1]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


__all__ = ["canonicalize_epub3", "inspect_epub3", "verify_canonical_epub3"]
