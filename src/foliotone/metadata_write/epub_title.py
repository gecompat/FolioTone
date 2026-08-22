"""Pure bounded EPUB 3 title preflight, lexical patch, and archive diff."""

from __future__ import annotations

import hashlib
import io
import re
import struct
import xml.etree.ElementTree as ElementTree
import zipfile
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, NoReturn

from foliotone.core import ValueState
from foliotone.metadata_correction import (
    MetadataCorrectionExecutionState,
    MetadataCorrectionOperation,
    MetadataCorrectionPlan,
    MetadataCorrectionPlanStatus,
    MetadataCorrectionPreconditionCode,
    MetadataDependencyKind,
    MetadataDependencyState,
    MetadataTargetCarrier,
    MetadataTargetReferenceKind,
    metadata_correction_candidate_content_hash,
    metadata_correction_candidate_evidence_fingerprint,
    metadata_correction_candidate_id,
    metadata_correction_plan_content_hash,
    metadata_correction_plan_id,
    metadata_correction_selected_fields_fingerprint,
    metadata_field_selection_fingerprint,
    metadata_writer_requirement_fingerprint,
)
from foliotone.metadata_write.contracts import (
    MAX_EPUB_ARCHIVE_BYTES,
    MAX_EPUB_CONTAINER_XML_BYTES,
    MAX_EPUB_ENTRIES,
    MAX_EPUB_MEMBER_UNCOMPRESSED_BYTES,
    MAX_EPUB_PACKAGE_DOCUMENT_BYTES,
    MAX_EPUB_TOTAL_UNCOMPRESSED_BYTES,
    MAX_EPUB_XML_DEPTH,
    MAX_EPUB_XML_ELEMENTS,
    EpubConformanceStatus,
    EpubInputConformance,
    EpubMemberSnapshot,
    EpubPublicationKind,
    EpubTextSpan,
    EpubTitleArchiveDiff,
    EpubTitlePackagePatch,
    EpubTitleWriteContractError,
    EpubTitleWriteErrorCode,
    EpubTitleWritePreflight,
)

_OCF_CONTAINER_NAMESPACE: Final = "urn:oasis:names:tc:opendocument:xmlns:container"
_OPF_NAMESPACE: Final = "http://www.idpf.org/2007/opf"
_DC_NAMESPACE: Final = "http://purl.org/dc/elements/1.1/"
_CONTAINER_PATH: Final = "META-INF/container.xml"
_PACKAGE_MEDIA_TYPE: Final = "application/oebps-package+xml"
_EPUB_MIMETYPE: Final = b"application/epub+zip"
_SIGNATURE_PATH: Final = "META-INF/signatures.xml"
_ENCRYPTION_PATH: Final = "META-INF/encryption.xml"
_READ_CHUNK_BYTES: Final = 1024 * 1024
_MAX_MODIFIED_FUTURE_SECONDS: Final = 300

_EOCD = struct.Struct("<4s4H2LH")
_CENTRAL_HEADER = struct.Struct("<4s6H3L5H2L")
_LOCAL_HEADER = struct.Struct("<4s5H3L2H")
_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_CENTRAL_SIGNATURE = b"PK\x01\x02"
_LOCAL_SIGNATURE = b"PK\x03\x04"
_DATA_DESCRIPTOR_SIGNATURE = b"PK\x07\x08"
_ZIP64_EXTRA_ID = 0x0001
_UNICODE_PATH_EXTRA_ID = 0x7075
_ALLOWED_GENERAL_FLAGS = 0x000E | 0x0800
_ENCRYPTION_FLAGS = 0x0001 | 0x0040 | 0x2000
_SUPPORTED_COMPRESSION = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}

_EPUB_VERSION = re.compile(r"3(?:\.[0-9]+)+\Z")
_MODIFIED_TIMESTAMP = re.compile(
    r"(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})Z\Z"
)
_XML_DECLARATION = re.compile(
    br"\A(?:\xef\xbb\xbf)?<\?xml\s+(?P<body>.*?)\?>",
    re.DOTALL,
)
_XML_ENCODING = re.compile(br"\bencoding\s*=\s*(['\"])(?P<value>.*?)\1", re.DOTALL)
_XML_FORBIDDEN_DECLARATION = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _EocdRecord:
    entries: int
    central_size: int
    central_offset: int
    offset: int
    comment: bytes


@dataclass(frozen=True, slots=True)
class _CentralRecord:
    raw_name: bytes
    decoded_name: str
    version_made_by: int
    version_needed: int
    flags: int
    compression: int
    modified_time: int
    modified_date: int
    crc32: int
    compressed_size: int
    uncompressed_size: int
    central_extra: bytes
    comment: bytes
    disk_start: int
    internal_attributes: int
    external_attributes: int
    local_header_offset: int
    local_extra: bytes
    local_crc32: int
    local_compressed_size: int
    local_uncompressed_size: int
    local_data_offset: int


@dataclass(frozen=True, slots=True)
class _LocalRecord:
    version_needed: int
    flags: int
    compression: int
    modified_time: int
    modified_date: int
    crc32: int
    compressed_size: int
    uncompressed_size: int
    raw_name: bytes
    extra: bytes
    data_offset: int


@dataclass(frozen=True, slots=True)
class _ArchiveInspection:
    source_sha256: str
    members: tuple[EpubMemberSnapshot, ...]
    archive_comment: bytes
    package_member_ordinal: int
    package_member_name: str
    package_document: bytes


@dataclass(frozen=True, slots=True)
class _PackageInspection:
    title: str
    modified: str
    title_span: EpubTextSpan
    modified_span: EpubTextSpan


@dataclass(frozen=True, slots=True)
class _OpenElement:
    qname: str
    namespaces: dict[str, str]
    content_start: int
    target: str | None


def _fail(code: EpubTitleWriteErrorCode) -> NoReturn:
    raise EpubTitleWriteContractError(code)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_plan(plan: MetadataCorrectionPlan) -> str:
    if not isinstance(plan, MetadataCorrectionPlan):
        _fail(EpubTitleWriteErrorCode.PLAN_INCOMPATIBLE)
    candidate = plan.candidate
    try:
        candidate_hash = metadata_correction_candidate_content_hash(candidate)
        candidate_evidence = metadata_correction_candidate_evidence_fingerprint(candidate)
        plan_hash = metadata_correction_plan_content_hash(plan)
    except (TypeError, ValueError):
        _fail(EpubTitleWriteErrorCode.PLAN_INCOMPATIBLE)
    if (
        candidate.content_hash != candidate_hash
        or candidate.evidence_fingerprint != candidate_evidence
        or candidate.id != metadata_correction_candidate_id(candidate_hash)
        or plan.content_hash != plan_hash
        or plan.id != metadata_correction_plan_id(plan_hash)
        or plan.status is not MetadataCorrectionPlanStatus.APPROVED_NON_EXECUTABLE
        or plan.execution_state is not MetadataCorrectionExecutionState.NOT_EXECUTABLE
        or plan.blockers
        or candidate.format_label != "EPUB"
        or candidate.target.carrier is not MetadataTargetCarrier.SOURCE_METADATA
        or candidate.target.reference_kind is not MetadataTargetReferenceKind.SOURCE_FILE
        or candidate.target.reference_id != candidate.file_id
        or candidate.writer_requirement.format_label != "EPUB"
        or candidate.writer_requirement.target_carrier
        is not MetadataTargetCarrier.SOURCE_METADATA
        or candidate.writer_requirement.material_fingerprint
        != metadata_writer_requirement_fingerprint(
            format_label=candidate.writer_requirement.format_label,
            target_carrier=candidate.writer_requirement.target_carrier,
        )
        or tuple(value.code for value in plan.preconditions)
        != tuple(MetadataCorrectionPreconditionCode)
        or len(candidate.field_corrections) != 1
    ):
        _fail(EpubTitleWriteErrorCode.PLAN_INCOMPATIBLE)

    correction = candidate.field_corrections[0]
    if (
        correction.field_path != "title"
        or correction.operation is not MetadataCorrectionOperation.REPLACE
        or len(correction.selected_values) != 1
        or correction.selected_values[0].state
        not in {ValueState.CANONICAL, ValueState.USER_CONFIRMED}
        or correction.selection_fingerprint
        != metadata_field_selection_fingerprint(
            field_path=correction.field_path,
            operation=correction.operation,
            observed_values=correction.observed_values,
            selected_values=correction.selected_values,
        )
        or plan.verification.changed_field_paths != ("title",)
        or plan.verification.target_carrier is not MetadataTargetCarrier.SOURCE_METADATA
        or plan.verification.format_label != "EPUB"
        or plan.verification.expected_selected_fields_fingerprint
        != metadata_correction_selected_fields_fingerprint(candidate)
    ):
        _fail(EpubTitleWriteErrorCode.PLAN_INCOMPATIBLE)

    dependency_states = {value.kind: value.state for value in candidate.dependencies}
    if dependency_states != {
        MetadataDependencyKind.CALIBRE: MetadataDependencyState.KNOWN_NONE,
        MetadataDependencyKind.SIDECAR: MetadataDependencyState.KNOWN_NONE,
        MetadataDependencyKind.ARCHIVE: MetadataDependencyState.NOT_APPLICABLE,
    }:
        _fail(EpubTitleWriteErrorCode.PLAN_INCOMPATIBLE)
    return correction.selected_values[0].value


def preflight_epub3_title_write(
    plan: MetadataCorrectionPlan,
    epub_bytes: bytes,
    input_conformance: EpubInputConformance,
) -> EpubTitleWritePreflight:
    """Validate one exact plan and EPUB byte sequence without filesystem access."""
    selected_title = _validate_plan(plan)
    if not isinstance(epub_bytes, bytes):
        _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
    if not epub_bytes or len(epub_bytes) > MAX_EPUB_ARCHIVE_BYTES:
        _fail(EpubTitleWriteErrorCode.ARCHIVE_SIZE_UNSUPPORTED)
    source_sha256 = _sha256(epub_bytes)
    candidate = plan.candidate
    if (
        candidate.expected_size_bytes != len(epub_bytes)
        or candidate.expected_full_sha256 != source_sha256
    ):
        _fail(EpubTitleWriteErrorCode.SOURCE_IDENTITY_MISMATCH)
    if (
        not isinstance(input_conformance, EpubInputConformance)
        or input_conformance.input_sha256 != source_sha256
        or input_conformance.publication_kind is not EpubPublicationKind.EPUB3
        or input_conformance.status is not EpubConformanceStatus.CONFORMANT
    ):
        _fail(EpubTitleWriteErrorCode.CONFORMANCE_EVIDENCE_INVALID)

    archive = _inspect_archive(epub_bytes)
    package = _inspect_package_document(archive.package_document)
    package_sha256 = _sha256(archive.package_document)
    if archive.members[archive.package_member_ordinal].content_sha256 != package_sha256:
        _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
    _escape_xml_text(selected_title)

    return EpubTitleWritePreflight(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        source_sha256=source_sha256,
        source_size_bytes=len(epub_bytes),
        package_member_ordinal=archive.package_member_ordinal,
        package_member_name=archive.package_member_name,
        package_document=archive.package_document,
        package_document_sha256=package_sha256,
        title_span=package.title_span,
        modified_span=package.modified_span,
        original_title=package.title,
        selected_title=selected_title,
        original_modified=package.modified,
        members=archive.members,
        archive_comment_sha256=_sha256(archive.archive_comment),
    )


def build_epub3_title_package_patch(
    preflight: EpubTitleWritePreflight,
    *,
    authorized_at: datetime,
) -> EpubTitlePackagePatch:
    """Replace only title text and dcterms:modified in the package document bytes."""
    if not isinstance(preflight, EpubTitleWritePreflight):
        _fail(EpubTitleWriteErrorCode.PATCH_DIFF_INVALID)
    _validate_preflight_snapshot(preflight)
    modified = _next_modified_timestamp(preflight.original_modified, authorized_at)
    patched = _apply_text_replacements(
        preflight.package_document,
        (
            (preflight.title_span, _escape_xml_text(preflight.selected_title)),
            (preflight.modified_span, modified.encode("ascii")),
        ),
    )
    if patched == preflight.package_document:
        _fail(EpubTitleWriteErrorCode.PATCH_DIFF_INVALID)
    inspected = _inspect_package_document(patched)
    if inspected.title != preflight.selected_title or inspected.modified != modified:
        _fail(EpubTitleWriteErrorCode.PATCH_DIFF_INVALID)

    return EpubTitlePackagePatch(
        plan_id=preflight.plan_id,
        plan_content_hash=preflight.plan_content_hash,
        source_sha256=preflight.source_sha256,
        original_package_sha256=preflight.package_document_sha256,
        patched_package_document=patched,
        patched_package_sha256=_sha256(patched),
        selected_title=preflight.selected_title,
        dcterms_modified=modified,
        title_span=preflight.title_span,
        modified_span=preflight.modified_span,
    )


def verify_epub3_title_archive_diff(
    preflight: EpubTitleWritePreflight,
    patch: EpubTitlePackagePatch,
    output_epub_bytes: bytes,
) -> EpubTitleArchiveDiff:
    """Require exactly one package member change and the exact two-span patch."""
    validate_epub3_title_package_patch(preflight, patch)
    if not isinstance(output_epub_bytes, bytes):
        _fail(EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID)

    output = _inspect_archive(output_epub_bytes)
    output_sha256 = output.source_sha256
    if output_sha256 == preflight.source_sha256:
        _fail(EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID)
    if (
        len(output.members) != len(preflight.members)
        or output.package_member_ordinal != preflight.package_member_ordinal
        or output.package_member_name != preflight.package_member_name
        or _sha256(output.archive_comment) != preflight.archive_comment_sha256
        or output.package_document != patch.patched_package_document
    ):
        _fail(EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID)

    changed_members = 0
    for before, after in zip(preflight.members, output.members, strict=True):
        if (
            before.ordinal != after.ordinal
            or before.name != after.name
            or before.raw_name != after.raw_name
            or before.metadata_fingerprint != after.metadata_fingerprint
        ):
            _fail(EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID)
        if before.ordinal == preflight.package_member_ordinal:
            if (
                after.content_sha256 != patch.patched_package_sha256
                or after.uncompressed_size != len(patch.patched_package_document)
                or before.content_sha256 == after.content_sha256
            ):
                _fail(EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID)
            changed_members += 1
        elif (
            before.content_sha256 != after.content_sha256
            or before.uncompressed_size != after.uncompressed_size
        ):
            _fail(EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID)
    if changed_members != 1:
        _fail(EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID)

    inspected = _inspect_package_document(output.package_document)
    if inspected.title != patch.selected_title or inspected.modified != patch.dcterms_modified:
        _fail(EpubTitleWriteErrorCode.PATCH_DIFF_INVALID)

    return EpubTitleArchiveDiff(
        plan_id=preflight.plan_id,
        input_sha256=preflight.source_sha256,
        output_sha256=output_sha256,
        original_package_sha256=preflight.package_document_sha256,
        patched_package_sha256=patch.patched_package_sha256,
        member_count=len(preflight.members),
        preserved_member_count=len(preflight.members) - 1,
    )


def validate_epub3_title_package_patch(
    preflight: EpubTitleWritePreflight,
    patch: EpubTitlePackagePatch,
) -> None:
    """Validate the exact pure patch linkage without requiring archive bytes."""
    if (
        not isinstance(preflight, EpubTitleWritePreflight)
        or not isinstance(patch, EpubTitlePackagePatch)
        or patch.plan_id != preflight.plan_id
        or patch.plan_content_hash != preflight.plan_content_hash
        or patch.source_sha256 != preflight.source_sha256
        or patch.original_package_sha256 != preflight.package_document_sha256
        or patch.selected_title != preflight.selected_title
        or patch.title_span != preflight.title_span
        or patch.modified_span != preflight.modified_span
        or patch.patched_package_sha256 != _sha256(patch.patched_package_document)
    ):
        _fail(EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID)
    _validate_preflight_snapshot(preflight)
    try:
        _parse_modified_timestamp(patch.dcterms_modified)
        modified_bytes = patch.dcterms_modified.encode("ascii")
    except (EpubTitleWriteContractError, UnicodeEncodeError) as error:
        raise EpubTitleWriteContractError(EpubTitleWriteErrorCode.PATCH_DIFF_INVALID) from error

    expected_package = _apply_text_replacements(
        preflight.package_document,
        (
            (preflight.title_span, _escape_xml_text(patch.selected_title)),
            (preflight.modified_span, modified_bytes),
        ),
    )
    if patch.patched_package_document != expected_package:
        _fail(EpubTitleWriteErrorCode.PATCH_DIFF_INVALID)


def _validate_preflight_snapshot(preflight: EpubTitleWritePreflight) -> None:
    if (
        preflight.package_document_sha256 != _sha256(preflight.package_document)
        or preflight.members[preflight.package_member_ordinal].content_sha256
        != preflight.package_document_sha256
    ):
        _fail(EpubTitleWriteErrorCode.PATCH_DIFF_INVALID)
    package = _inspect_package_document(preflight.package_document)
    if (
        package.title != preflight.original_title
        or package.modified != preflight.original_modified
        or package.title_span != preflight.title_span
        or package.modified_span != preflight.modified_span
    ):
        _fail(EpubTitleWriteErrorCode.PATCH_DIFF_INVALID)


def _inspect_archive(epub_bytes: bytes) -> _ArchiveInspection:
    if not epub_bytes or len(epub_bytes) > MAX_EPUB_ARCHIVE_BYTES:
        _fail(EpubTitleWriteErrorCode.ARCHIVE_SIZE_UNSUPPORTED)
    eocd = _parse_eocd(epub_bytes)
    records = _parse_central_records(epub_bytes, eocd)
    if not records or records[0].local_header_offset != 0:
        _fail(EpubTitleWriteErrorCode.MIMETYPE_INVALID)

    try:
        with zipfile.ZipFile(io.BytesIO(epub_bytes), mode="r") as archive:
            infos = archive.infolist()
            if len(infos) != len(records):
                _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
            if archive.comment != eocd.comment:
                _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
            _validate_zipinfo(records, infos)
            names = tuple(record.decoded_name for record in records)
            if _SIGNATURE_PATH in names or _ENCRYPTION_PATH in names:
                _fail(EpubTitleWriteErrorCode.ARCHIVE_FEATURE_UNSUPPORTED)
            if names[0] != "mimetype":
                _fail(EpubTitleWriteErrorCode.MIMETYPE_INVALID)
            mimetype_record = records[0]
            if (
                mimetype_record.compression != zipfile.ZIP_STORED
                or mimetype_record.central_extra
                or mimetype_record.local_extra
            ):
                _fail(EpubTitleWriteErrorCode.MIMETYPE_INVALID)

            members: list[EpubMemberSnapshot] = []
            container_document: bytes | None = None
            for ordinal, (record, info) in enumerate(zip(records, infos, strict=True)):
                if record.decoded_name == "mimetype" and info.file_size != len(_EPUB_MIMETYPE):
                    _fail(EpubTitleWriteErrorCode.MIMETYPE_INVALID)
                if (
                    record.decoded_name == _CONTAINER_PATH
                    and info.file_size > MAX_EPUB_CONTAINER_XML_BYTES
                ):
                    _fail(EpubTitleWriteErrorCode.CONTAINER_INVALID)
                content_sha256, actual_size, captured = _read_member(
                    archive,
                    info,
                    capture=record.decoded_name in {"mimetype", _CONTAINER_PATH},
                )
                if record.decoded_name == "mimetype" and captured != _EPUB_MIMETYPE:
                    _fail(EpubTitleWriteErrorCode.MIMETYPE_INVALID)
                if record.decoded_name == _CONTAINER_PATH:
                    container_document = captured
                members.append(
                    EpubMemberSnapshot(
                        ordinal=ordinal,
                        name=record.decoded_name,
                        raw_name=record.raw_name,
                        content_sha256=content_sha256,
                        uncompressed_size=actual_size,
                        metadata_fingerprint=_member_metadata_fingerprint(record),
                    )
                )
            if container_document is None:
                _fail(EpubTitleWriteErrorCode.CONTAINER_INVALID)
            package_name = _package_name_from_container(container_document, names)
            package_ordinal = names.index(package_name)
            package_info = infos[package_ordinal]
            if package_info.file_size > MAX_EPUB_PACKAGE_DOCUMENT_BYTES:
                _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
            _, _, package_document = _read_member(archive, package_info, capture=True)
            if package_document is None:
                _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
    except EpubTitleWriteContractError:
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
        raise EpubTitleWriteContractError(EpubTitleWriteErrorCode.ENTRY_UNREADABLE) from error

    return _ArchiveInspection(
        source_sha256=_sha256(epub_bytes),
        members=tuple(members),
        archive_comment=eocd.comment,
        package_member_ordinal=package_ordinal,
        package_member_name=package_name,
        package_document=package_document,
    )


def _parse_eocd(data: bytes) -> _EocdRecord:
    minimum = _EOCD.size
    if len(data) < minimum:
        _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
    lower = max(0, len(data) - minimum - 65_535)
    for offset in range(len(data) - minimum, lower - 1, -1):
        if data[offset : offset + 4] != _EOCD_SIGNATURE:
            continue
        try:
            values = _EOCD.unpack_from(data, offset)
        except struct.error:
            continue
        disk_number = int(values[1])
        central_disk = int(values[2])
        entries_on_disk = int(values[3])
        entries = int(values[4])
        central_size = int(values[5])
        central_offset = int(values[6])
        comment_length = int(values[7])
        end = offset + minimum + comment_length
        if end != len(data):
            continue
        if (
            disk_number != 0
            or central_disk != 0
            or entries_on_disk != entries
            or entries in {0xFFFF}
            or central_size == 0xFFFFFFFF
            or central_offset == 0xFFFFFFFF
            or central_offset + central_size != offset
            or (offset >= 20 and data[offset - 20 : offset - 16] == _ZIP64_LOCATOR_SIGNATURE)
        ):
            _fail(EpubTitleWriteErrorCode.ARCHIVE_FEATURE_UNSUPPORTED)
        if not 1 <= entries <= MAX_EPUB_ENTRIES:
            _fail(EpubTitleWriteErrorCode.ENTRY_LIMIT_EXCEEDED)
        return _EocdRecord(
            entries=entries,
            central_size=central_size,
            central_offset=central_offset,
            offset=offset,
            comment=data[offset + minimum : end],
        )
    _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)


def _parse_central_records(data: bytes, eocd: _EocdRecord) -> tuple[_CentralRecord, ...]:
    if eocd.central_offset < 0 or eocd.central_offset + eocd.central_size > len(data):
        _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
    pointer = eocd.central_offset
    records: list[_CentralRecord] = []
    names: set[str] = set()
    raw_names: set[bytes] = set()
    previous_local_offset = -1
    total_uncompressed = 0
    for _ in range(eocd.entries):
        if pointer + _CENTRAL_HEADER.size > eocd.offset:
            _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
        try:
            values = _CENTRAL_HEADER.unpack_from(data, pointer)
        except struct.error as error:
            raise EpubTitleWriteContractError(EpubTitleWriteErrorCode.ARCHIVE_INVALID) from error
        if values[0] != _CENTRAL_SIGNATURE:
            _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
        version_made_by = int(values[1])
        version_needed = int(values[2])
        flags = int(values[3])
        compression = int(values[4])
        modified_time = int(values[5])
        modified_date = int(values[6])
        crc32 = int(values[7])
        compressed_size = int(values[8])
        uncompressed_size = int(values[9])
        name_length = int(values[10])
        extra_length = int(values[11])
        comment_length = int(values[12])
        disk_start = int(values[13])
        internal_attributes = int(values[14])
        external_attributes = int(values[15])
        local_offset = int(values[16])
        variable_start = pointer + _CENTRAL_HEADER.size
        variable_end = variable_start + name_length + extra_length + comment_length
        if name_length == 0 or variable_end > eocd.offset:
            _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
        raw_name = data[variable_start : variable_start + name_length]
        central_extra = data[
            variable_start + name_length : variable_start + name_length + extra_length
        ]
        comment = data[variable_start + name_length + extra_length : variable_end]
        decoded_name = _decode_member_name(raw_name, flags)
        _validate_member_name(decoded_name)
        if raw_name in raw_names or decoded_name in names:
            _fail(EpubTitleWriteErrorCode.ENTRY_DUPLICATE)
        raw_names.add(raw_name)
        names.add(decoded_name)
        if flags & _ENCRYPTION_FLAGS:
            _fail(EpubTitleWriteErrorCode.ENTRY_ENCRYPTED)
        if flags & ~_ALLOWED_GENERAL_FLAGS or (flags & 0x0006) == 0x0006:
            _fail(EpubTitleWriteErrorCode.ARCHIVE_FEATURE_UNSUPPORTED)
        if compression not in _SUPPORTED_COMPRESSION:
            _fail(EpubTitleWriteErrorCode.ENTRY_COMPRESSION_UNSUPPORTED)
        if compression == zipfile.ZIP_STORED and flags & 0x0006:
            _fail(EpubTitleWriteErrorCode.ARCHIVE_FEATURE_UNSUPPORTED)
        if disk_start != 0 or any(
            value == 0xFFFFFFFF
            for value in (compressed_size, uncompressed_size, local_offset)
        ):
            _fail(EpubTitleWriteErrorCode.ARCHIVE_FEATURE_UNSUPPORTED)
        if uncompressed_size > MAX_EPUB_MEMBER_UNCOMPRESSED_BYTES:
            _fail(EpubTitleWriteErrorCode.ENTRY_SIZE_UNSUPPORTED)
        total_uncompressed += uncompressed_size
        if total_uncompressed > MAX_EPUB_TOTAL_UNCOMPRESSED_BYTES:
            _fail(EpubTitleWriteErrorCode.ENTRY_SIZE_UNSUPPORTED)
        if local_offset <= previous_local_offset or local_offset >= eocd.central_offset:
            _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
        previous_local_offset = local_offset
        _validate_extra_fields(central_extra)
        local = _parse_local_header(data, local_offset, eocd.central_offset)
        if (
            local.version_needed != version_needed
            or local.flags != flags
            or local.compression != compression
            or local.modified_time != modified_time
            or local.modified_date != modified_date
            or local.raw_name != raw_name
        ):
            _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
        records.append(
            _CentralRecord(
                raw_name=raw_name,
                decoded_name=decoded_name,
                version_made_by=version_made_by,
                version_needed=version_needed,
                flags=flags,
                compression=compression,
                modified_time=modified_time,
                modified_date=modified_date,
                crc32=crc32,
                compressed_size=compressed_size,
                uncompressed_size=uncompressed_size,
                central_extra=central_extra,
                comment=comment,
                disk_start=disk_start,
                internal_attributes=internal_attributes,
                external_attributes=external_attributes,
                local_header_offset=local_offset,
                local_extra=local.extra,
                local_crc32=local.crc32,
                local_compressed_size=local.compressed_size,
                local_uncompressed_size=local.uncompressed_size,
                local_data_offset=local.data_offset,
            )
        )
        pointer = variable_end
    if pointer != eocd.central_offset + eocd.central_size:
        _fail(EpubTitleWriteErrorCode.ARCHIVE_FEATURE_UNSUPPORTED)
    _validate_local_layout(data, tuple(records), eocd.central_offset)
    return tuple(records)


def _parse_local_header(
    data: bytes,
    offset: int,
    central_offset: int,
) -> _LocalRecord:
    if offset < 0 or offset + _LOCAL_HEADER.size > central_offset:
        _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
    try:
        values = _LOCAL_HEADER.unpack_from(data, offset)
    except struct.error as error:
        raise EpubTitleWriteContractError(EpubTitleWriteErrorCode.ARCHIVE_INVALID) from error
    if values[0] != _LOCAL_SIGNATURE:
        _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
    name_length = int(values[9])
    extra_length = int(values[10])
    variable_start = offset + _LOCAL_HEADER.size
    variable_end = variable_start + name_length + extra_length
    if name_length == 0 or variable_end > central_offset:
        _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
    raw_name = data[variable_start : variable_start + name_length]
    extra = data[variable_start + name_length : variable_end]
    _validate_extra_fields(extra)
    return _LocalRecord(
        version_needed=int(values[1]),
        flags=int(values[2]),
        compression=int(values[3]),
        modified_time=int(values[4]),
        modified_date=int(values[5]),
        crc32=int(values[6]),
        compressed_size=int(values[7]),
        uncompressed_size=int(values[8]),
        raw_name=raw_name,
        extra=extra,
        data_offset=variable_end,
    )


def _validate_local_layout(
    data: bytes,
    records: tuple[_CentralRecord, ...],
    central_offset: int,
) -> None:
    for ordinal, record in enumerate(records):
        boundary = (
            records[ordinal + 1].local_header_offset
            if ordinal + 1 < len(records)
            else central_offset
        )
        data_end = record.local_data_offset + record.compressed_size
        if data_end > boundary:
            _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
        if record.flags & 0x0008:
            descriptor = data[data_end:boundary]
            if descriptor.startswith(_DATA_DESCRIPTOR_SIGNATURE):
                descriptor = descriptor[4:]
            if len(descriptor) != 12:
                _fail(EpubTitleWriteErrorCode.ARCHIVE_FEATURE_UNSUPPORTED)
            crc32, compressed_size, uncompressed_size = struct.unpack("<LLL", descriptor)
            if (
                int(crc32) != record.crc32
                or int(compressed_size) != record.compressed_size
                or int(uncompressed_size) != record.uncompressed_size
                or record.local_crc32 not in {0, record.crc32}
                or record.local_compressed_size not in {0, record.compressed_size}
                or record.local_uncompressed_size not in {0, record.uncompressed_size}
            ):
                _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
        elif (
            data_end != boundary
            or record.local_crc32 != record.crc32
            or record.local_compressed_size != record.compressed_size
            or record.local_uncompressed_size != record.uncompressed_size
        ):
            _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)


def _validate_extra_fields(extra: bytes) -> None:
    pointer = 0
    while pointer < len(extra):
        if pointer + 4 > len(extra):
            _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
        header_id, payload_size = struct.unpack_from("<HH", extra, pointer)
        pointer += 4
        if header_id in {_ZIP64_EXTRA_ID, _UNICODE_PATH_EXTRA_ID}:
            _fail(EpubTitleWriteErrorCode.ARCHIVE_FEATURE_UNSUPPORTED)
        pointer += int(payload_size)
        if pointer > len(extra):
            _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)


def _decode_member_name(raw_name: bytes, flags: int) -> str:
    if b"\x00" in raw_name:
        _fail(EpubTitleWriteErrorCode.ENTRY_NAME_INVALID)
    try:
        if flags & 0x0800:
            return raw_name.decode("utf-8")
        if any(value >= 0x80 for value in raw_name):
            _fail(EpubTitleWriteErrorCode.ENTRY_NAME_INVALID)
        return raw_name.decode("ascii")
    except UnicodeDecodeError as error:
        raise EpubTitleWriteContractError(EpubTitleWriteErrorCode.ENTRY_NAME_INVALID) from error


def _validate_member_name(name: str) -> None:
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or any(ord(character) < 0x20 for character in name)
    ):
        _fail(EpubTitleWriteErrorCode.ENTRY_NAME_INVALID)
    parts = name.split("/")
    if name.endswith("/"):
        parts = parts[:-1]
    if not parts or any(part in {"", ".", ".."} for part in parts):
        _fail(EpubTitleWriteErrorCode.ENTRY_NAME_INVALID)


def _validate_zipinfo(
    records: tuple[_CentralRecord, ...],
    infos: list[zipfile.ZipInfo],
) -> None:
    for record, info in zip(records, infos, strict=True):
        if (
            info.filename != record.decoded_name
            or info.flag_bits != record.flags
            or info.compress_type != record.compression
            or info.CRC != record.crc32
            or info.compress_size != record.compressed_size
            or info.file_size != record.uncompressed_size
            or info.extra != record.central_extra
            or info.comment != record.comment
            or info.internal_attr != record.internal_attributes
            or info.external_attr != record.external_attributes
            or info.header_offset != record.local_header_offset
            or info.volume != record.disk_start
            or info.create_system != record.version_made_by >> 8
            or info.create_version != record.version_made_by & 0xFF
            or info.extract_version != record.version_needed
        ):
            _fail(EpubTitleWriteErrorCode.ARCHIVE_INVALID)


def _read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    capture: bool,
) -> tuple[str, int, bytes | None]:
    digest = hashlib.sha256()
    size = 0
    captured = bytearray() if capture else None
    try:
        with archive.open(info, mode="r") as member:
            while chunk := member.read(_READ_CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_EPUB_MEMBER_UNCOMPRESSED_BYTES:
                    _fail(EpubTitleWriteErrorCode.ENTRY_SIZE_UNSUPPORTED)
                digest.update(chunk)
                if captured is not None:
                    captured.extend(chunk)
    except EpubTitleWriteContractError:
        raise
    except (
        zipfile.BadZipFile,
        RuntimeError,
        NotImplementedError,
        EOFError,
        OSError,
        zlib.error,
    ) as error:
        raise EpubTitleWriteContractError(EpubTitleWriteErrorCode.ENTRY_UNREADABLE) from error
    if size != info.file_size:
        _fail(EpubTitleWriteErrorCode.ENTRY_UNREADABLE)
    return digest.hexdigest(), size, None if captured is None else bytes(captured)


def _member_metadata_fingerprint(record: _CentralRecord) -> str:
    digest = hashlib.sha256()
    for integer_value in (
        record.version_made_by,
        record.version_needed,
        record.flags,
        record.compression,
        record.modified_time,
        record.modified_date,
        record.disk_start,
        record.internal_attributes,
        record.external_attributes,
    ):
        digest.update(int(integer_value).to_bytes(8, "little", signed=False))
    for byte_value in (
        record.raw_name,
        record.central_extra,
        record.local_extra,
        record.comment,
    ):
        digest.update(len(byte_value).to_bytes(8, "little", signed=False))
        digest.update(byte_value)
    return digest.hexdigest()


def _package_name_from_container(container: bytes, names: tuple[str, ...]) -> str:
    root = _parse_xml(
        container,
        max_bytes=MAX_EPUB_CONTAINER_XML_BYTES,
        error_code=EpubTitleWriteErrorCode.CONTAINER_INVALID,
    )
    if root.tag != f"{{{_OCF_CONTAINER_NAMESPACE}}}container":
        _fail(EpubTitleWriteErrorCode.CONTAINER_INVALID)
    rootfiles_nodes = tuple(
        child
        for child in root
        if child.tag == f"{{{_OCF_CONTAINER_NAMESPACE}}}rootfiles"
    )
    if len(rootfiles_nodes) != 1:
        _fail(EpubTitleWriteErrorCode.CONTAINER_INVALID)
    rootfiles = tuple(
        child
        for child in rootfiles_nodes[0]
        if child.tag == f"{{{_OCF_CONTAINER_NAMESPACE}}}rootfile"
    )
    if len(rootfiles) != 1:
        _fail(EpubTitleWriteErrorCode.CONTAINER_INVALID)
    rootfile = rootfiles[0]
    package_name = rootfile.attrib.get("full-path", "")
    if rootfile.attrib.get("media-type") != _PACKAGE_MEDIA_TYPE:
        _fail(EpubTitleWriteErrorCode.CONTAINER_INVALID)
    _validate_member_name(package_name)
    if package_name not in names or package_name.endswith("/"):
        _fail(EpubTitleWriteErrorCode.CONTAINER_INVALID)
    return package_name


def _inspect_package_document(package_document: bytes) -> _PackageInspection:
    root = _parse_xml(
        package_document,
        max_bytes=MAX_EPUB_PACKAGE_DOCUMENT_BYTES,
        error_code=EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID,
    )
    if root.tag != f"{{{_OPF_NAMESPACE}}}package":
        _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
    version = root.attrib.get("version", "")
    if _EPUB_VERSION.fullmatch(version) is None:
        _fail(EpubTitleWriteErrorCode.EPUB_VERSION_UNSUPPORTED)
    metadata_nodes = tuple(
        child for child in root if child.tag == f"{{{_OPF_NAMESPACE}}}metadata"
    )
    if len(metadata_nodes) != 1:
        _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
    metadata = metadata_nodes[0]
    all_titles = tuple(
        element for element in root.iter() if element.tag == f"{{{_DC_NAMESPACE}}}title"
    )
    if (
        len(all_titles) != 1
        or all_titles[0] not in tuple(metadata)
        or len(all_titles[0]) != 0
    ):
        _fail(EpubTitleWriteErrorCode.TITLE_STRUCTURE_UNSUPPORTED)
    title = all_titles[0]
    title_text = title.text
    if title_text is None or not title_text.strip():
        _fail(EpubTitleWriteErrorCode.TITLE_STRUCTURE_UNSUPPORTED)
    title_id = title.attrib.get("id")
    meta_elements = tuple(
        element for element in root.iter() if element.tag == f"{{{_OPF_NAMESPACE}}}meta"
    )
    modified_elements = tuple(
        element
        for element in meta_elements
        if element.attrib.get("property") == "dcterms:modified"
    )
    if (
        len(modified_elements) != 1
        or modified_elements[0] not in tuple(metadata)
        or "refines" in modified_elements[0].attrib
        or len(modified_elements[0]) != 0
        or modified_elements[0].text is None
    ):
        _fail(EpubTitleWriteErrorCode.MODIFIED_STRUCTURE_UNSUPPORTED)
    if any(
        element.attrib.get("property") == "title-type"
        or (title_id is not None and element.attrib.get("refines") == f"#{title_id}")
        for element in meta_elements
    ):
        _fail(EpubTitleWriteErrorCode.TITLE_STRUCTURE_UNSUPPORTED)
    modified = modified_elements[0].text
    _parse_modified_timestamp(modified)
    title_span, modified_span = _lexical_target_spans(package_document)
    return _PackageInspection(
        title=title_text,
        modified=modified,
        title_span=title_span,
        modified_span=modified_span,
    )


def _parse_xml(
    document: bytes,
    *,
    max_bytes: int,
    error_code: EpubTitleWriteErrorCode,
) -> ElementTree.Element:
    if not document or len(document) > max_bytes or _XML_FORBIDDEN_DECLARATION.search(document):
        _fail(error_code)
    try:
        document.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EpubTitleWriteContractError(error_code) from error
    declaration = _XML_DECLARATION.match(document)
    if declaration is not None:
        encoding = _XML_ENCODING.search(declaration.group("body"))
        if encoding is not None:
            normalized = encoding.group("value").decode("ascii", errors="ignore").lower()
            if normalized not in {"utf-8", "utf8"}:
                _fail(error_code)
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as error:
        raise EpubTitleWriteContractError(error_code) from error
    count = 0
    stack = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        count += 1
        if count > MAX_EPUB_XML_ELEMENTS or depth > MAX_EPUB_XML_DEPTH:
            _fail(error_code)
        stack.extend((child, depth + 1) for child in element)
    return root


def _lexical_target_spans(document: bytes) -> tuple[EpubTextSpan, EpubTextSpan]:
    stack: list[_OpenElement] = []
    targets: dict[str, list[EpubTextSpan]] = {"title": [], "modified": []}
    pointer = 0
    while True:
        start = document.find(b"<", pointer)
        if start < 0:
            break
        if document.startswith(b"<!--", start):
            _reject_markup_in_target(stack)
            end = document.find(b"-->", start + 4)
            if end < 0:
                _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
            pointer = end + 3
            continue
        if document.startswith(b"<![CDATA[", start):
            _reject_markup_in_target(stack)
            end = document.find(b"]]>", start + 9)
            if end < 0:
                _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
            pointer = end + 3
            continue
        if document.startswith(b"<?", start):
            _reject_markup_in_target(stack)
            end = document.find(b"?>", start + 2)
            if end < 0:
                _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
            pointer = end + 2
            continue
        if document.startswith(b"</", start):
            end = document.find(b">", start + 2)
            if end < 0 or not stack:
                _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
            qname = _decode_qname(document[start + 2 : end].strip())
            opened = stack.pop()
            if qname != opened.qname:
                _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
            if opened.target is not None:
                targets[opened.target].append(EpubTextSpan(opened.content_start, start))
            pointer = end + 1
            continue
        if document.startswith(b"<!", start):
            _reject_markup_in_target(stack)
            _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)

        _reject_markup_in_target(stack)
        end = _find_tag_end(document, start + 1)
        qname, attributes, self_closing = _parse_start_tag(document[start + 1 : end])
        namespaces = dict(stack[-1].namespaces) if stack else {"xml": "http://www.w3.org/XML/1998/namespace"}
        for name, value in attributes.items():
            if name == "xmlns":
                namespaces[""] = value
            elif name.startswith("xmlns:"):
                namespaces[name.split(":", 1)[1]] = value
        namespace, local_name = _expanded_name(qname, namespaces)
        target: str | None = None
        if namespace == _DC_NAMESPACE and local_name == "title":
            target = "title"
        elif (
            namespace == _OPF_NAMESPACE
            and local_name == "meta"
            and attributes.get("property") == "dcterms:modified"
            and "refines" not in attributes
        ):
            target = "modified"
        if target is not None and self_closing:
            code = (
                EpubTitleWriteErrorCode.TITLE_STRUCTURE_UNSUPPORTED
                if target == "title"
                else EpubTitleWriteErrorCode.MODIFIED_STRUCTURE_UNSUPPORTED
            )
            _fail(code)
        if not self_closing:
            stack.append(
                _OpenElement(
                    qname=qname,
                    namespaces=namespaces,
                    content_start=end + 1,
                    target=target,
                )
            )
        pointer = end + 1
    if stack:
        _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
    if len(targets["title"]) != 1:
        _fail(EpubTitleWriteErrorCode.TITLE_STRUCTURE_UNSUPPORTED)
    if len(targets["modified"]) != 1:
        _fail(EpubTitleWriteErrorCode.MODIFIED_STRUCTURE_UNSUPPORTED)
    return targets["title"][0], targets["modified"][0]


def _reject_markup_in_target(stack: list[_OpenElement]) -> None:
    if not stack or stack[-1].target is None:
        return
    code = (
        EpubTitleWriteErrorCode.TITLE_STRUCTURE_UNSUPPORTED
        if stack[-1].target == "title"
        else EpubTitleWriteErrorCode.MODIFIED_STRUCTURE_UNSUPPORTED
    )
    _fail(code)


def _find_tag_end(document: bytes, pointer: int) -> int:
    quote: int | None = None
    while pointer < len(document):
        value = document[pointer]
        if quote is not None:
            if value == quote:
                quote = None
        elif value in {ord("'"), ord('"')}:
            quote = value
        elif value == ord(">"):
            return pointer
        pointer += 1
    _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)


def _parse_start_tag(tag: bytes) -> tuple[str, dict[str, str], bool]:
    stripped = tag.rstrip()
    self_closing = stripped.endswith(b"/")
    if self_closing:
        stripped = stripped[:-1].rstrip()
    pointer = 0
    while pointer < len(stripped) and stripped[pointer] not in b" \t\r\n":
        pointer += 1
    qname = _decode_qname(stripped[:pointer])
    attributes: dict[str, str] = {}
    while pointer < len(stripped):
        while pointer < len(stripped) and stripped[pointer] in b" \t\r\n":
            pointer += 1
        if pointer == len(stripped):
            break
        name_start = pointer
        while pointer < len(stripped) and stripped[pointer] not in b" \t\r\n=<>/'\"":
            pointer += 1
        name = _decode_qname(stripped[name_start:pointer])
        while pointer < len(stripped) and stripped[pointer] in b" \t\r\n":
            pointer += 1
        if pointer >= len(stripped) or stripped[pointer] != ord("="):
            _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
        pointer += 1
        while pointer < len(stripped) and stripped[pointer] in b" \t\r\n":
            pointer += 1
        if pointer >= len(stripped) or stripped[pointer] not in {ord("'"), ord('"')}:
            _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
        quote = stripped[pointer]
        pointer += 1
        value_start = pointer
        while pointer < len(stripped) and stripped[pointer] != quote:
            if stripped[pointer] == ord("<"):
                _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
            pointer += 1
        if pointer >= len(stripped):
            _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
        value = _decode_xml_value(stripped[value_start:pointer])
        pointer += 1
        if name in attributes:
            _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
        attributes[name] = value
    return qname, attributes, self_closing


def _decode_qname(value: bytes) -> str:
    if not value:
        _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
    try:
        decoded = value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EpubTitleWriteContractError(
            EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID
        ) from error
    if decoded.count(":") > 1 or decoded.startswith(":") or decoded.endswith(":"):
        _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
    return decoded


def _decode_xml_value(value: bytes) -> str:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EpubTitleWriteContractError(
            EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID
        ) from error
    result: list[str] = []
    pointer = 0
    replacements = {"amp": "&", "lt": "<", "gt": ">", "apos": "'", "quot": '"'}
    while pointer < len(text):
        ampersand = text.find("&", pointer)
        if ampersand < 0:
            result.append(text[pointer:])
            break
        result.append(text[pointer:ampersand])
        semicolon = text.find(";", ampersand + 1)
        if semicolon < 0:
            _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
        reference = text[ampersand + 1 : semicolon]
        try:
            if reference.startswith("#x"):
                replacement = chr(int(reference[2:], 16))
            elif reference.startswith("#"):
                replacement = chr(int(reference[1:], 10))
            else:
                replacement = replacements[reference]
        except (KeyError, ValueError, OverflowError) as error:
            raise EpubTitleWriteContractError(
                EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID
            ) from error
        if not _is_xml_character(ord(replacement)):
            _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
        result.append(replacement)
        pointer = semicolon + 1
    return "".join(result)


def _expanded_name(qname: str, namespaces: dict[str, str]) -> tuple[str, str]:
    if ":" in qname:
        prefix, local_name = qname.split(":", 1)
        namespace = namespaces.get(prefix)
        if namespace is None:
            _fail(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
        return namespace, local_name
    return namespaces.get("", ""), qname


def _parse_modified_timestamp(value: str) -> datetime:
    match = _MODIFIED_TIMESTAMP.fullmatch(value)
    if match is None:
        _fail(EpubTitleWriteErrorCode.MODIFIED_TIME_INVALID)
    try:
        return datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
            int(match.group("second")),
            tzinfo=UTC,
        )
    except ValueError as error:
        raise EpubTitleWriteContractError(EpubTitleWriteErrorCode.MODIFIED_TIME_INVALID) from error


def _next_modified_timestamp(previous: str, authorized_at: datetime) -> str:
    previous_time = _parse_modified_timestamp(previous)
    if not isinstance(authorized_at, datetime) or authorized_at.tzinfo is None:
        _fail(EpubTitleWriteErrorCode.AUTHORIZATION_TIME_INVALID)
    try:
        offset = authorized_at.utcoffset()
        if offset is None:
            _fail(EpubTitleWriteErrorCode.AUTHORIZATION_TIME_INVALID)
        authorized_utc = authorized_at.astimezone(UTC).replace(microsecond=0)
        if previous_time > authorized_utc + timedelta(seconds=_MAX_MODIFIED_FUTURE_SECONDS):
            _fail(EpubTitleWriteErrorCode.MODIFIED_TIME_FUTURE)
        next_time = max(authorized_utc, previous_time + timedelta(seconds=1))
    except EpubTitleWriteContractError:
        raise
    except (OverflowError, ValueError) as error:
        raise EpubTitleWriteContractError(
            EpubTitleWriteErrorCode.AUTHORIZATION_TIME_INVALID
        ) from error
    return (
        f"{next_time.year:04d}-{next_time.month:02d}-{next_time.day:02d}"
        f"T{next_time.hour:02d}:{next_time.minute:02d}:{next_time.second:02d}Z"
    )


def _escape_xml_text(value: str) -> bytes:
    if not isinstance(value, str) or not value or any(
        not _is_xml_character(ord(character)) for character in value
    ):
        _fail(EpubTitleWriteErrorCode.PLAN_INCOMPATIBLE)
    escaped = (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\r", "&#13;")
    )
    return escaped.encode("utf-8")


def _is_xml_character(value: int) -> bool:
    return (
        value in {0x09, 0x0A, 0x0D}
        or 0x20 <= value <= 0xD7FF
        or 0xE000 <= value <= 0xFFFD
        or 0x10000 <= value <= 0x10FFFF
    )


def _apply_text_replacements(
    document: bytes,
    replacements: tuple[tuple[EpubTextSpan, bytes], ...],
) -> bytes:
    ordered = tuple(sorted(replacements, key=lambda item: item[0].start))
    previous_end = 0
    for span, _ in ordered:
        if span.start < previous_end or span.end > len(document):
            _fail(EpubTitleWriteErrorCode.PATCH_DIFF_INVALID)
        previous_end = span.end
    output = document
    for span, replacement in reversed(ordered):
        output = output[: span.start] + replacement + output[span.end :]
    return output


__all__ = [
    "build_epub3_title_package_patch",
    "preflight_epub3_title_write",
    "validate_epub3_title_package_patch",
    "verify_epub3_title_archive_diff",
]
