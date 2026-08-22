from __future__ import annotations

import hashlib
import io
import json
import struct
import warnings
import zipfile
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from foliotone.core import EntityId, PresenceState, ScanRunStatus, ValueState
from foliotone.metadata_correction import (
    METADATA_TARGET_REFERENCE_KIND,
    MetadataCorrectionCandidateInputs,
    MetadataCorrectionOperation,
    MetadataCorrectionPlanInputs,
    MetadataCorrectionReviewSnapshot,
    MetadataCorrectionReviewState,
    MetadataDependencyKind,
    MetadataDependencySnapshot,
    MetadataDependencyState,
    MetadataEvidenceReference,
    MetadataTargetCarrier,
    MetadataTargetSnapshot,
    MetadataValueSnapshot,
    build_metadata_correction_candidate,
    build_metadata_correction_plan,
    build_metadata_field_correction,
    build_metadata_writer_requirement,
)
from foliotone.metadata_write import (
    EPUB_TITLE_DIFF_PROFILE,
    EPUB_TITLE_PATCH_PROFILE,
    EPUB_TITLE_PREFLIGHT_PROFILE,
    EPUB_TITLE_STAGING_PROFILE,
    EPUB_TITLE_VALIDATION_PROFILE,
    EPUB_TITLE_WRITE_PROFILE,
    EpubConformanceStatus,
    EpubInputConformance,
    EpubPublicationKind,
    EpubTitleStagingError,
    EpubTitleStagingErrorCode,
    EpubTitleValidationArtifact,
    EpubTitleValidationCommand,
    EpubTitleValidationToolOutcome,
    EpubTitleWriteContractError,
    EpubTitleWriteErrorCode,
    FixedEpubTitleStagingValidator,
    MetadataWriteAuthorizationError,
    MetadataWriteAuthorizationErrorCode,
    ResolvedMetadataWriteCapability,
    build_and_verify_private_epub3_title_stage,
    build_epub3_title_package_patch,
    build_epub3_title_write_preparation,
    build_metadata_write_authorization,
    build_metadata_write_run,
    build_private_epub3_title_stage,
    preflight_epub3_title_write,
    verify_epub3_title_archive_diff,
    verify_private_epub3_title_stage,
)
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteOwnerKind,
)

NOW = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
PACKAGE_NAME = "OEBPS/package.opf"
PRIVATE_SELECTED_TITLE = "Café & <Nord>\rBand 2"


def _id(value: int) -> EntityId:
    return EntityId(UUID(int=value))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(character: str) -> str:
    return character * 64


def _ref(kind: str, identifier: int, digest: str) -> MetadataEvidenceReference:
    return MetadataEvidenceReference(
        kind=kind,
        ref_id=_id(identifier),
        material_fingerprint=_digest(digest),
    )


def _value(
    *,
    ordinal: int,
    state: ValueState,
    value: str,
    identifier: int,
    digest: str,
) -> MetadataValueSnapshot:
    return MetadataValueSnapshot(
        ordinal=ordinal,
        state=state,
        source_ref=_ref("VALUE_ASSERTION", identifier, digest),
        value=value,
    )


def _dependencies(
    *,
    calibre: MetadataDependencyState = MetadataDependencyState.KNOWN_NONE,
    sidecar: MetadataDependencyState = MetadataDependencyState.KNOWN_NONE,
    archive: MetadataDependencyState = MetadataDependencyState.NOT_APPLICABLE,
) -> tuple[MetadataDependencySnapshot, ...]:
    return (
        MetadataDependencySnapshot(
            kind=MetadataDependencyKind.CALIBRE,
            state=calibre,
            snapshot_kind="calibre-dependency/v1",
            snapshot_id=_id(31),
            material_fingerprint=_digest("3"),
        ),
        MetadataDependencySnapshot(
            kind=MetadataDependencyKind.SIDECAR,
            state=sidecar,
            snapshot_kind="sidecar-dependency/v1",
            snapshot_id=_id(32),
            material_fingerprint=_digest("4"),
        ),
        MetadataDependencySnapshot(
            kind=MetadataDependencyKind.ARCHIVE,
            state=archive,
            snapshot_kind="archive-dependency/v1",
            snapshot_id=_id(33),
            material_fingerprint=_digest("5"),
        ),
    )


def _approved_plan(
    epub: bytes,
    *,
    selected_title: str = PRIVATE_SELECTED_TITLE,
    format_label: str = "EPUB",
    target_carrier: MetadataTargetCarrier = MetadataTargetCarrier.SOURCE_METADATA,
    field_path: str = "title",
    operation: MetadataCorrectionOperation = MetadataCorrectionOperation.REPLACE,
    selected_count: int = 1,
    dependencies: tuple[MetadataDependencySnapshot, ...] | None = None,
    review_state: MetadataCorrectionReviewState = MetadataCorrectionReviewState.ACCEPTED,
):
    file_id = _id(3)
    target = MetadataTargetSnapshot(
        carrier=target_carrier,
        reference_kind=METADATA_TARGET_REFERENCE_KIND[target_carrier],
        reference_id=(
            file_id if target_carrier is MetadataTargetCarrier.SOURCE_METADATA else _id(9)
        ),
        carrier_state_fingerprint=_digest("6"),
    )
    observed = (
        _value(
            ordinal=0,
            state=ValueState.OBSERVED,
            value="Synthetic old title",
            identifier=21,
            digest="7",
        ),
    )
    selected = tuple(
        _value(
            ordinal=ordinal,
            state=ValueState.USER_CONFIRMED,
            value=f"{selected_title}{ordinal if selected_count > 1 else ''}",
            identifier=22 + ordinal,
            digest="8",
        )
        for ordinal in range(selected_count)
    )
    if operation is MetadataCorrectionOperation.REMOVE:
        selected = ()
    correction = build_metadata_field_correction(
        field_path=field_path,
        operation=operation,
        observed_values=observed,
        selected_values=selected,
        evidence_refs=(_ref("TOOL_RESULT", 25, "9"),),
    )
    candidate = build_metadata_correction_candidate(
        MetadataCorrectionCandidateInputs(
            scan_root_id=_id(1),
            source_scan_run_id=_id(2),
            source_scan_run_status=ScanRunStatus.COMPLETED,
            file_id=file_id,
            observation_id=_id(4),
            format_label=format_label,
            expected_presence_state=PresenceState.PRESENT,
            expected_full_sha256=_sha(epub),
            expected_size_bytes=len(epub),
            expected_modified_at=NOW - timedelta(days=1),
            expected_observed_at=NOW - timedelta(hours=1),
            metadata_evidence_fingerprint=_digest("a"),
            target=target,
            field_corrections=(correction,),
            dependencies=_dependencies() if dependencies is None else dependencies,
            writer_requirement=build_metadata_writer_requirement(
                format_label=format_label,
                target_carrier=target_carrier,
            ),
            evidence_refs=(
                _ref("FILE_OBSERVATION", 4, "b"),
                _ref("VALUE_ASSERTION", 21, "7"),
            ),
        ),
        clock=lambda: NOW,
    )
    decided = review_state in {
        MetadataCorrectionReviewState.ACCEPTED,
        MetadataCorrectionReviewState.REJECTED,
    }
    review = MetadataCorrectionReviewSnapshot(
        candidate_id=candidate.id,
        state=review_state,
        evidence_fingerprint=candidate.evidence_fingerprint,
        candidate_set_fingerprint=candidate.content_hash,
        review_item_id=_id(51),
        decision_id=_id(52) if decided else None,
        decision_sequence_no=1 if decided else None,
    )
    return build_metadata_correction_plan(
        MetadataCorrectionPlanInputs(
            candidate=candidate,
            review=review,
            preserved_fields_fingerprint=_digest("c"),
            analysis_profile="ebook-analysis-workflow/v3",
            lineage_matches=True,
            source_evidence_complete=True,
            field_selection_valid=True,
            target_carrier_valid=True,
            writer_requirement_valid=True,
            preconditions_complete=True,
            verification_contract_complete=True,
        ),
        clock=lambda: NOW,
    )


def _package_document(
    *,
    version: str = "3.0",
    title_markup: str = '<dc:title id="main-title">Old &amp; title</dc:title>',
    modified_markup: str = (
        '<meta property="dcterms:modified">2026-08-22T10:00:00Z</meta>'
    ),
    extra_metadata: str = "",
    doctype: str = "",
    dc_prefix: str = "dc",
) -> bytes:
    if dc_prefix != "dc":
        title_markup = title_markup.replace("dc:title", f"{dc_prefix}:title")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"{doctype}"
        f'<package xmlns="http://www.idpf.org/2007/opf" '
        f'xmlns:{dc_prefix}="http://purl.org/dc/elements/1.1/" '
        f'version="{version}" unique-identifier="book-id">\n'
        "  <metadata>\n"
        f'    <{dc_prefix}:identifier id="book-id">urn:uuid:synthetic</{dc_prefix}:identifier>\n'
        f"    {title_markup}\n"
        f"    {modified_markup}\n"
        f"    {extra_metadata}\n"
        "  </metadata>\n"
        '  <manifest><item id="chapter" href="chapter.xhtml" '
        'media-type="application/xhtml+xml"/></manifest>\n'
        '  <spine><itemref idref="chapter"/></spine>\n'
        "</package>\n"
    ).encode()


def _container_document(*, rootfiles: tuple[str, ...] = (PACKAGE_NAME,)) -> bytes:
    entries = "".join(
        f'<rootfile full-path="{name}" media-type="application/oebps-package+xml"/>'
        for name in rootfiles
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
        f'version="1.0"><rootfiles>{entries}</rootfiles></container>'
    ).encode()


def _zip_info(
    name: str,
    *,
    compression: int,
    extra: bytes = b"",
    comment: bytes = b"",
) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 8, 22, 10, 0, 0))
    info.compress_type = compression
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.internal_attr = 0
    info.extra = extra
    info.comment = comment
    return info


class _UnseekableBuffer:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def write(self, data: bytes) -> int:
        self._buffer.extend(data)
        return len(data)

    def tell(self) -> int:
        return len(self._buffer)

    def seek(self, *_args: object) -> int:
        raise OSError("synthetic unseekable buffer")

    def flush(self) -> None:
        return None

    def getvalue(self) -> bytes:
        return bytes(self._buffer)


def _epub(
    *,
    package_document: bytes | None = None,
    container_document: bytes | None = None,
    mimetype_data: bytes = b"application/epub+zip",
    mimetype_compression: int = zipfile.ZIP_STORED,
    mimetype_extra: bytes = b"",
    package_compression: int = zipfile.ZIP_DEFLATED,
    additional_entries: tuple[tuple[str, bytes, int], ...] = (),
    duplicate_package: bool = False,
    mimetype_first: bool = True,
    archive_comment: bytes = b"synthetic-archive-comment",
    data_descriptors: bool = False,
) -> bytes:
    package_document = _package_document() if package_document is None else package_document
    container_document = (
        _container_document() if container_document is None else container_document
    )
    entries = [
        (
            _zip_info(
                "mimetype",
                compression=mimetype_compression,
                extra=mimetype_extra,
            ),
            mimetype_data,
        ),
        (
            _zip_info(_CONTAINER_NAME, compression=zipfile.ZIP_DEFLATED),
            container_document,
        ),
        (_zip_info(PACKAGE_NAME, compression=package_compression), package_document),
        (
            _zip_info("OEBPS/chapter.xhtml", compression=zipfile.ZIP_DEFLATED),
            b'<html xmlns="http://www.w3.org/1999/xhtml"><body>synthetic</body></html>',
        ),
    ]
    entries.extend(
        (_zip_info(name, compression=compression), data)
        for name, data, compression in additional_entries
    )
    if duplicate_package:
        entries.append((_zip_info(PACKAGE_NAME, compression=package_compression), package_document))
    if not mimetype_first:
        entries[0], entries[1] = entries[1], entries[0]
    output = _UnseekableBuffer() if data_descriptors else io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(output, mode="w") as archive:
            archive.comment = archive_comment
            for info, data in entries:
                archive.writestr(info, data)
    return output.getvalue()


_CONTAINER_NAME = "META-INF/container.xml"


def _conformance(
    epub: bytes,
    *,
    status: EpubConformanceStatus = EpubConformanceStatus.CONFORMANT,
    kind: EpubPublicationKind = EpubPublicationKind.EPUB3,
    digest: str | None = None,
) -> EpubInputConformance:
    return EpubInputConformance(
        input_sha256=_sha(epub) if digest is None else digest,
        publication_kind=kind,
        status=status,
    )


def _preflight(epub: bytes, *, selected_title: str = PRIVATE_SELECTED_TITLE):
    return preflight_epub3_title_write(
        _approved_plan(epub, selected_title=selected_title),
        epub,
        _conformance(epub),
    )


def _copy_info(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    copied = zipfile.ZipInfo(info.filename, date_time=info.date_time)
    for attribute in (
        "compress_type",
        "comment",
        "extra",
        "create_system",
        "create_version",
        "extract_version",
        "internal_attr",
        "external_attr",
        "flag_bits",
    ):
        setattr(copied, attribute, getattr(info, attribute))
    return copied


def _rebuild_epub(
    source: bytes,
    *,
    replacement_package: bytes,
    mutate_entry: Callable[[zipfile.ZipInfo, bytes], tuple[zipfile.ZipInfo, bytes]] | None = None,
    archive_comment: bytes | None = None,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source), mode="r") as before:
        with zipfile.ZipFile(output, mode="w") as after:
            after.comment = before.comment if archive_comment is None else archive_comment
            for original_info in before.infolist():
                info = _copy_info(original_info)
                data = before.read(original_info)
                if info.filename == PACKAGE_NAME:
                    data = replacement_package
                if mutate_entry is not None:
                    info, data = mutate_entry(info, data)
                after.writestr(info, data)
    return output.getvalue()


def _error_code(call: Callable[[], object]) -> EpubTitleWriteErrorCode:
    with pytest.raises(EpubTitleWriteContractError) as caught:
        call()
    assert str(caught.value) == caught.value.code.value
    return caught.value.code


def test_preflight_patch_and_archive_diff_preserve_every_non_target_member() -> None:
    source = _epub()
    preflight = _preflight(source)

    patch = build_epub3_title_package_patch(
        preflight,
        authorized_at=NOW + timedelta(microseconds=987_654),
    )
    output = _rebuild_epub(source, replacement_package=patch.patched_package_document)
    diff = verify_epub3_title_archive_diff(preflight, patch, output)

    assert preflight.profile == EPUB_TITLE_PREFLIGHT_PROFILE
    assert patch.profile == EPUB_TITLE_PATCH_PROFILE
    assert diff.profile == EPUB_TITLE_DIFF_PROFILE
    assert {preflight.writer_profile, patch.writer_profile, diff.writer_profile} == {
        EPUB_TITLE_WRITE_PROFILE
    }
    assert patch.dcterms_modified == "2026-08-22T10:00:01Z"
    assert b"Caf\xc3\xa9 &amp; &lt;Nord&gt;&#13;Band 2" in patch.patched_package_document
    assert diff.member_count == 4
    assert diff.preserved_member_count == 3
    assert diff.changed_member_count == 1
    assert diff.input_sha256 != diff.output_sha256


def test_patch_is_exactly_two_lexical_replacements_and_accepts_an_alias_prefix() -> None:
    package = _package_document(dc_prefix="d")
    source = _epub(package_document=package)
    preflight = _preflight(source, selected_title="Synthetic replacement")

    patch = build_epub3_title_package_patch(preflight, authorized_at=NOW)

    expected = preflight.package_document
    replacements = (
        (preflight.title_span.start, preflight.title_span.end, b"Synthetic replacement"),
        (preflight.modified_span.start, preflight.modified_span.end, b"2026-08-22T10:00:01Z"),
    )
    for start, end, replacement in sorted(replacements, reverse=True):
        expected = expected[:start] + replacement + expected[end:]
    assert patch.patched_package_document == expected
    assert b"xmlns:d=" in patch.patched_package_document
    assert b"<d:identifier" in patch.patched_package_document


def test_authorization_timestamp_is_utc_second_bounded_and_retry_deterministic() -> None:
    source = _epub()
    preflight = _preflight(source)
    authorized_at = datetime(
        2026,
        8,
        22,
        12,
        0,
        7,
        999_999,
        tzinfo=timezone(timedelta(hours=2)),
    )

    first = build_epub3_title_package_patch(preflight, authorized_at=authorized_at)
    second = build_epub3_title_package_patch(preflight, authorized_at=authorized_at)

    assert first == second
    assert first.dcterms_modified == "2026-08-22T10:00:07Z"


def test_modified_timestamp_more_than_300_seconds_in_future_blocks() -> None:
    package = _package_document(
        modified_markup='<meta property="dcterms:modified">2026-08-22T10:05:01Z</meta>'
    )
    source = _epub(package_document=package)
    preflight = _preflight(source)

    assert _error_code(
        lambda: build_epub3_title_package_patch(preflight, authorized_at=NOW)
    ) is EpubTitleWriteErrorCode.MODIFIED_TIME_FUTURE


@pytest.mark.parametrize(
    "make_plan",
    (
        lambda epub: _approved_plan(epub, format_label="PDF"),
        lambda epub: _approved_plan(epub, target_carrier=MetadataTargetCarrier.SIDECAR),
        lambda epub: _approved_plan(epub, field_path="publisher"),
        lambda epub: _approved_plan(
            epub,
            operation=MetadataCorrectionOperation.REMOVE,
            selected_count=0,
        ),
        lambda epub: _approved_plan(epub, selected_count=2),
        lambda epub: _approved_plan(
            epub,
            dependencies=_dependencies(calibre=MetadataDependencyState.KNOWN_PRESENT),
        ),
        lambda epub: _approved_plan(
            epub,
            dependencies=_dependencies(sidecar=MetadataDependencyState.UNKNOWN),
        ),
        lambda epub: _approved_plan(
            epub,
            dependencies=_dependencies(archive=MetadataDependencyState.KNOWN_NONE),
        ),
        lambda epub: _approved_plan(
            epub,
            review_state=MetadataCorrectionReviewState.PENDING,
        ),
    ),
    ids=(
        "format",
        "carrier",
        "field",
        "remove",
        "multiple-values",
        "calibre",
        "sidecar",
        "archive",
        "review",
    ),
)
def test_writer_rejects_every_valid_but_incompatible_plan(make_plan) -> None:
    source = _epub()

    assert _error_code(
        lambda: preflight_epub3_title_write(make_plan(source), source, _conformance(source))
    ) is EpubTitleWriteErrorCode.PLAN_INCOMPATIBLE


def test_source_hash_and_size_are_revalidated_before_archive_parsing() -> None:
    source = _epub()
    plan = _approved_plan(source)
    changed = source + b"not-the-reviewed-source"

    assert _error_code(
        lambda: preflight_epub3_title_write(plan, changed, _conformance(changed))
    ) is EpubTitleWriteErrorCode.SOURCE_IDENTITY_MISMATCH


@pytest.mark.parametrize(
    ("conformance", "expected"),
    (
        (
            lambda epub: _conformance(epub, status=EpubConformanceStatus.NONCONFORMANT),
            EpubTitleWriteErrorCode.CONFORMANCE_EVIDENCE_INVALID,
        ),
        (
            lambda epub: _conformance(epub, status=EpubConformanceStatus.UNKNOWN),
            EpubTitleWriteErrorCode.CONFORMANCE_EVIDENCE_INVALID,
        ),
        (
            lambda epub: _conformance(epub, kind=EpubPublicationKind.KEPUB),
            EpubTitleWriteErrorCode.CONFORMANCE_EVIDENCE_INVALID,
        ),
        (
            lambda epub: _conformance(epub, digest="f" * 64),
            EpubTitleWriteErrorCode.CONFORMANCE_EVIDENCE_INVALID,
        ),
    ),
    ids=("nonconformant", "unknown", "kepub", "wrong-input"),
)
def test_input_conformance_must_be_positive_and_bound_to_the_same_bytes(
    conformance,
    expected: EpubTitleWriteErrorCode,
) -> None:
    source = _epub()

    assert _error_code(
        lambda: preflight_epub3_title_write(
            _approved_plan(source), source, conformance(source)
        )
    ) is expected


@pytest.mark.parametrize(
    ("epub_factory", "expected"),
    (
        (
            lambda: _epub(mimetype_data=b"application/zip"),
            EpubTitleWriteErrorCode.MIMETYPE_INVALID,
        ),
        (
            lambda: _epub(mimetype_compression=zipfile.ZIP_DEFLATED),
            EpubTitleWriteErrorCode.MIMETYPE_INVALID,
        ),
        (
            lambda: _epub(mimetype_extra=struct.pack("<HH", 0xCAFE, 0)),
            EpubTitleWriteErrorCode.MIMETYPE_INVALID,
        ),
        (
            lambda: _epub(mimetype_first=False),
            EpubTitleWriteErrorCode.MIMETYPE_INVALID,
        ),
        (
            lambda: _epub(duplicate_package=True),
            EpubTitleWriteErrorCode.ENTRY_DUPLICATE,
        ),
        (
            lambda: _epub(package_compression=zipfile.ZIP_BZIP2),
            EpubTitleWriteErrorCode.ENTRY_COMPRESSION_UNSUPPORTED,
        ),
        (
            lambda: _epub(additional_entries=(("META-INF/signatures.xml", b"x", 0),)),
            EpubTitleWriteErrorCode.ARCHIVE_FEATURE_UNSUPPORTED,
        ),
        (
            lambda: _epub(additional_entries=(("META-INF/encryption.xml", b"x", 0),)),
            EpubTitleWriteErrorCode.ARCHIVE_FEATURE_UNSUPPORTED,
        ),
    ),
    ids=(
        "mimetype-content",
        "mimetype-compression",
        "mimetype-extra",
        "mimetype-order",
        "duplicate",
        "compression",
        "signature",
        "encryption",
    ),
)
def test_archive_preflight_rejects_unsupported_ocf_features(
    epub_factory,
    expected: EpubTitleWriteErrorCode,
) -> None:
    source = epub_factory()

    assert _error_code(
        lambda: preflight_epub3_title_write(
            _approved_plan(source), source, _conformance(source)
        )
    ) is expected


def test_archive_preflight_rejects_encryption_flag_without_trying_to_read() -> None:
    source = bytearray(_epub())
    local_offset = source.find(b"PK\x03\x04")
    central_offset = source.find(b"PK\x01\x02")
    assert local_offset >= 0 and central_offset >= 0
    for offset in (local_offset + 6, central_offset + 8):
        flags = struct.unpack_from("<H", source, offset)[0]
        struct.pack_into("<H", source, offset, flags | 0x0001)
    encrypted = bytes(source)

    assert _error_code(
        lambda: preflight_epub3_title_write(
            _approved_plan(encrypted), encrypted, _conformance(encrypted)
        )
    ) is EpubTitleWriteErrorCode.ENTRY_ENCRYPTED


def test_archive_preflight_accepts_bounded_standard_data_descriptors() -> None:
    source = _epub(data_descriptors=True)

    preflight = _preflight(source)

    assert preflight.source_size_bytes == len(source)
    assert len(preflight.members) == 4


@pytest.mark.parametrize(
    ("package", "expected"),
    (
        (
            _package_document(version="2.0"),
            EpubTitleWriteErrorCode.EPUB_VERSION_UNSUPPORTED,
        ),
        (
            _package_document(
                title_markup=(
                    "<dc:title>One</dc:title><dc:title>Two</dc:title>"
                )
            ),
            EpubTitleWriteErrorCode.TITLE_STRUCTURE_UNSUPPORTED,
        ),
        (
            _package_document(title_markup="<dc:title><![CDATA[Old title]]></dc:title>"),
            EpubTitleWriteErrorCode.TITLE_STRUCTURE_UNSUPPORTED,
        ),
        (
            _package_document(
                extra_metadata='<meta refines="#main-title" property="file-as">Old</meta>'
            ),
            EpubTitleWriteErrorCode.TITLE_STRUCTURE_UNSUPPORTED,
        ),
        (
            _package_document(
                modified_markup=(
                    '<meta property="dcterms:modified" refines="#main-title">'
                    "2026-08-22T10:00:00Z</meta>"
                )
            ),
            EpubTitleWriteErrorCode.MODIFIED_STRUCTURE_UNSUPPORTED,
        ),
        (
            _package_document(
                modified_markup=(
                    '<meta property="dcterms:modified">2026-08-22 10:00:00Z</meta>'
                )
            ),
            EpubTitleWriteErrorCode.MODIFIED_TIME_INVALID,
        ),
        (
            _package_document(doctype='<!DOCTYPE package [<!ENTITY x "private">]>'),
            EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID,
        ),
    ),
    ids=(
        "epub2",
        "multiple-title",
        "cdata",
        "title-refinement",
        "modified-refinement",
        "modified-format",
        "doctype",
    ),
)
def test_package_preflight_rejects_ambiguous_or_non_epub3_targets(
    package: bytes,
    expected: EpubTitleWriteErrorCode,
) -> None:
    source = _epub(package_document=package)

    assert _error_code(
        lambda: preflight_epub3_title_write(
            _approved_plan(source), source, _conformance(source)
        )
    ) is expected


def test_container_rejects_multiple_renditions() -> None:
    container = _container_document(rootfiles=(PACKAGE_NAME, "OEBPS/other.opf"))
    source = _epub(
        container_document=container,
        additional_entries=(("OEBPS/other.opf", _package_document(), zipfile.ZIP_DEFLATED),),
    )

    assert _error_code(
        lambda: preflight_epub3_title_write(
            _approved_plan(source), source, _conformance(source)
        )
    ) is EpubTitleWriteErrorCode.CONTAINER_INVALID


def test_archive_diff_rejects_a_changed_non_package_member() -> None:
    source = _epub()
    preflight = _preflight(source)
    patch = build_epub3_title_package_patch(preflight, authorized_at=NOW)

    def mutate(info: zipfile.ZipInfo, data: bytes) -> tuple[zipfile.ZipInfo, bytes]:
        if info.filename == "OEBPS/chapter.xhtml":
            return info, data + b"changed"
        return info, data

    output = _rebuild_epub(
        source,
        replacement_package=patch.patched_package_document,
        mutate_entry=mutate,
    )

    assert _error_code(
        lambda: verify_epub3_title_archive_diff(preflight, patch, output)
    ) is EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID


def test_archive_diff_rejects_changed_member_metadata_or_archive_comment() -> None:
    source = _epub()
    preflight = _preflight(source)
    patch = build_epub3_title_package_patch(preflight, authorized_at=NOW)

    def mutate(info: zipfile.ZipInfo, data: bytes) -> tuple[zipfile.ZipInfo, bytes]:
        if info.filename == "OEBPS/chapter.xhtml":
            info.comment = b"changed-comment"
        return info, data

    metadata_changed = _rebuild_epub(
        source,
        replacement_package=patch.patched_package_document,
        mutate_entry=mutate,
    )
    comment_changed = _rebuild_epub(
        source,
        replacement_package=patch.patched_package_document,
        archive_comment=b"changed-archive-comment",
    )

    for output in (metadata_changed, comment_changed):
        assert _error_code(
            lambda output=output: verify_epub3_title_archive_diff(preflight, patch, output)
        ) is EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID


def test_archive_diff_rejects_a_patch_object_with_extra_package_changes() -> None:
    source = _epub()
    preflight = _preflight(source)
    patch = build_epub3_title_package_patch(preflight, authorized_at=NOW)
    tampered_bytes = patch.patched_package_document.replace(b"urn:uuid:synthetic", b"urn:x")
    tampered = replace(
        patch,
        patched_package_document=tampered_bytes,
        patched_package_sha256=_sha(tampered_bytes),
    )
    output = _rebuild_epub(source, replacement_package=tampered_bytes)

    assert _error_code(
        lambda: verify_epub3_title_archive_diff(preflight, tampered, output)
    ) is EpubTitleWriteErrorCode.PATCH_DIFF_INVALID


def test_public_repr_and_failures_do_not_expose_private_title_or_hash() -> None:
    source = _epub()
    plan = _approved_plan(source)
    preflight = preflight_epub3_title_write(plan, source, _conformance(source))
    patch = build_epub3_title_package_patch(preflight, authorized_at=NOW)
    output = _rebuild_epub(source, replacement_package=patch.patched_package_document)
    diff = verify_epub3_title_archive_diff(preflight, patch, output)

    rendered = " ".join((repr(preflight), repr(patch), repr(diff)))
    assert PRIVATE_SELECTED_TITLE not in rendered
    assert plan.content_hash not in rendered
    assert _sha(source) not in rendered
    assert PACKAGE_NAME not in rendered

    incompatible = _approved_plan(source, target_carrier=MetadataTargetCarrier.SIDECAR)
    with pytest.raises(EpubTitleWriteContractError) as caught:
        preflight_epub3_title_write(incompatible, source, _conformance(source))
    assert str(caught.value) == "PLAN_INCOMPATIBLE"
    assert PRIVATE_SELECTED_TITLE not in repr(caught.value)
    assert _sha(source) not in repr(caught.value)


class _RecordingSource(io.BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)


def test_private_stage_streams_source_and_preserves_descriptor_members(
    tmp_path: Path,
) -> None:
    source = _epub(data_descriptors=True)
    preflight = _preflight(source)
    patch = build_epub3_title_package_patch(preflight, authorized_at=NOW)
    stream = _RecordingSource(source)

    stage = build_private_epub3_title_stage(
        tmp_path / "stage",
        stream,
        preflight,
        patch,
    )

    assert stage.profile == EPUB_TITLE_STAGING_PROFILE
    assert stage.input_path.read_bytes() == source
    assert stage.input_sha256 == _sha(source)
    assert stage.output_sha256 == _sha(stage.output_path.read_bytes())
    assert stage.output_sha256 != stage.input_sha256
    assert max(stream.read_sizes) == 1024 * 1024
    assert verify_private_epub3_title_stage(
        preflight,
        patch,
        stage.output_path,
    ) == stage.archive_diff


def test_private_stage_preserves_stored_package_and_entry_metadata(tmp_path: Path) -> None:
    base = _epub(package_compression=zipfile.ZIP_STORED)

    def annotate(info: zipfile.ZipInfo, data: bytes) -> tuple[zipfile.ZipInfo, bytes]:
        if info.filename == "OEBPS/chapter.xhtml":
            info.comment = b"synthetic-entry-comment"
            info.extra = struct.pack("<HH", 0xCAFE, 3) + b"abc"
            info.internal_attr = 1
        return info, data

    source = _rebuild_epub(
        base,
        replacement_package=_package_document(),
        mutate_entry=annotate,
    )
    preflight = _preflight(source)
    patch = build_epub3_title_package_patch(preflight, authorized_at=NOW)

    stage = build_private_epub3_title_stage(
        tmp_path / "stored",
        io.BytesIO(source),
        preflight,
        patch,
    )

    with zipfile.ZipFile(stage.output_path, mode="r") as archive:
        package = archive.getinfo(PACKAGE_NAME)
        chapter = archive.getinfo("OEBPS/chapter.xhtml")
    assert package.compress_type == zipfile.ZIP_STORED
    assert chapter.comment == b"synthetic-entry-comment"
    assert chapter.extra == struct.pack("<HH", 0xCAFE, 3) + b"abc"
    assert chapter.internal_attr == 1
    assert verify_epub3_title_archive_diff(
        preflight,
        patch,
        stage.output_path.read_bytes(),
    ) == stage.archive_diff


def test_private_stage_rejects_changed_source_and_existing_target(tmp_path: Path) -> None:
    source = _epub()
    preflight = _preflight(source)
    patch = build_epub3_title_package_patch(preflight, authorized_at=NOW)

    with pytest.raises(EpubTitleStagingError) as changed:
        build_private_epub3_title_stage(
            tmp_path / "changed",
            io.BytesIO(source + b"changed"),
            preflight,
            patch,
        )
    assert changed.value.code is EpubTitleStagingErrorCode.SOURCE_IDENTITY_MISMATCH

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(EpubTitleStagingError) as collision:
        build_private_epub3_title_stage(
            existing,
            io.BytesIO(source),
            preflight,
            patch,
        )
    assert collision.value.code is EpubTitleStagingErrorCode.STAGE_TARGET_EXISTS


def _readback_opf(
    title: str,
    *,
    publisher: str = "Synthetic Publisher",
    stable_identifier: str = "urn:uuid:synthetic",
    calibre_identifier: str = "volatile-calibre-id",
) -> bytes:
    escaped_title = (
        title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf" version="3.0">'
        "<metadata>"
        f"<dc:title>{escaped_title}</dc:title>"
        "<dc:creator>Ada Author</dc:creator>"
        f"<dc:identifier>{stable_identifier}</dc:identifier>"
        f'<dc:identifier opf:scheme="calibre">{calibre_identifier}</dc:identifier>'
        "<dc:language>de</dc:language>"
        f"<dc:publisher>{publisher}</dc:publisher>"
        "</metadata></package>"
    ).encode()


class _SyntheticValidationRunner:
    def __init__(
        self,
        original_title: str,
        selected_title: str,
        *,
        failure: str | None = None,
    ) -> None:
        self.original_title = " ".join(original_title.split())
        self.selected_title = " ".join(selected_title.split())
        self.failure = failure
        self.commands: list[EpubTitleValidationCommand] = []

    def run(
        self,
        command: EpubTitleValidationCommand,
        _workspace: Path,
    ) -> EpubTitleValidationToolOutcome:
        self.commands.append(command)
        artifacts: tuple[EpubTitleValidationArtifact, ...]
        version = "calibre 9.13.0"
        if command.step.startswith("metadata-"):
            is_output = command.step == "metadata-output"
            title = self.selected_title if is_output else self.original_title
            if is_output and self.failure == "title":
                title = "Wrong title"
            publisher = (
                "Changed Publisher"
                if is_output and self.failure == "metadata"
                else "Synthetic Publisher"
            )
            artifacts = (
                EpubTitleValidationArtifact(
                    "CALIBRE_OPF",
                    _readback_opf(
                        title,
                        publisher=publisher,
                        stable_identifier=(
                            "urn:uuid:changed"
                            if is_output and self.failure == "identifier"
                            else "urn:uuid:synthetic"
                        ),
                        calibre_identifier=(
                            "volatile-output-id" if is_output else "volatile-input-id"
                        ),
                    ),
                ),
            )
        elif command.step == "epubcheck-output":
            version = "EPUBCheck v5.3.0"
            failed = self.failure == "epubcheck"
            report = {
                "checker": {
                    "checkerVersion": "5.3.0",
                    "filename": "output.epub",
                    "nError": int(failed),
                    "nFatal": 0,
                    "nUsage": 0,
                    "nWarning": 0,
                },
                "messages": (
                    [{"ID": "OPF-001", "severity": "ERROR", "message": "private"}]
                    if failed
                    else []
                ),
            }
            artifacts = (
                EpubTitleValidationArtifact(
                    "EPUBCHECK_JSON",
                    json.dumps(report).encode(),
                ),
            )
        elif command.step.startswith("text-"):
            data = (
                b"Changed text"
                if command.step == "text-output" and self.failure == "text"
                else b"Synthetic readable text"
            )
            artifacts = (EpubTitleValidationArtifact("CALIBRE_TEXT", data),)
        else:
            assert command.step.startswith("cover-")
            source = Path(command.args[3])
            result = {
                "cover_bytes": 0,
                "source_sha256": _sha(source.read_bytes()),
                "status": "NO_EMBEDDED_COVER",
            }
            if command.step == "cover-output" and self.failure == "cover":
                version = "calibre 9.14.0"
            artifacts = (
                EpubTitleValidationArtifact(
                    "CALIBRE_COVER_RESULT",
                    json.dumps(result).encode(),
                ),
            )
        return EpubTitleValidationToolOutcome(command.step, version, artifacts)


def test_fixed_staging_validation_runs_exact_independent_sequence(tmp_path: Path) -> None:
    source = _epub()
    preflight = _preflight(source)
    patch = build_epub3_title_package_patch(preflight, authorized_at=NOW)
    runner = _SyntheticValidationRunner(preflight.original_title, patch.selected_title)
    validator = FixedEpubTitleStagingValidator(runner=runner)

    verified = build_and_verify_private_epub3_title_stage(
        tmp_path / "verified",
        io.BytesIO(source),
        preflight,
        patch,
        validator=validator,
    )

    assert verified.validation.profile == EPUB_TITLE_VALIDATION_PROFILE
    assert verified.validation.conformance_status == "CONFORMANT"
    assert verified.validation.cover_status == "NO_EMBEDDED_COVER"
    assert [command.step for command in runner.commands] == [
        "metadata-input",
        "metadata-output",
        "epubcheck-output",
        "text-input",
        "text-output",
        "cover-input",
        "cover-output",
    ]
    joined_args = " ".join(arg for command in runner.commands for arg in command.args)
    assert "--title" not in joined_args
    assert str(verified.staged_files.input_path) in joined_args
    assert str(verified.staged_files.output_path) in joined_args


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        ("title", EpubTitleStagingErrorCode.METADATA_READBACK_MISMATCH),
        ("metadata", EpubTitleStagingErrorCode.PRESERVED_FIELDS_MISMATCH),
        ("identifier", EpubTitleStagingErrorCode.PRESERVED_FIELDS_MISMATCH),
        ("epubcheck", EpubTitleStagingErrorCode.EPUBCHECK_MISMATCH),
        ("text", EpubTitleStagingErrorCode.TEXT_READBACK_MISMATCH),
        ("cover", EpubTitleStagingErrorCode.COVER_READBACK_MISMATCH),
    ),
)
def test_fixed_staging_validation_fails_closed_on_independent_mismatch(
    tmp_path: Path,
    failure: str,
    expected: EpubTitleStagingErrorCode,
) -> None:
    source = _epub()
    preflight = _preflight(source)
    patch = build_epub3_title_package_patch(preflight, authorized_at=NOW)
    validator = FixedEpubTitleStagingValidator(
        runner=_SyntheticValidationRunner(
            preflight.original_title,
            patch.selected_title,
            failure=failure,
        )
    )
    stage = build_private_epub3_title_stage(
        tmp_path / failure,
        io.BytesIO(source),
        preflight,
        patch,
    )

    with pytest.raises(EpubTitleStagingError) as caught:
        validator.validate(stage, preflight, patch)

    assert caught.value.code is expected
    assert str(caught.value) == expected.value
    assert PRIVATE_SELECTED_TITLE not in repr(caught.value)
    assert str(stage.private_directory) not in repr(caught.value)


def _prepare_authorization_material(tmp_path: Path):
    source = _epub()
    plan = _approved_plan(source)
    preflight = preflight_epub3_title_write(plan, source, _conformance(source))
    patch = build_epub3_title_package_patch(preflight, authorized_at=NOW)
    validator = FixedEpubTitleStagingValidator(
        runner=_SyntheticValidationRunner(preflight.original_title, patch.selected_title)
    )
    verified = build_and_verify_private_epub3_title_stage(
        tmp_path / "private-stage",
        io.BytesIO(source),
        preflight,
        patch,
        validator=validator,
    )
    scan_root = tmp_path / "source-root"
    recovery = tmp_path / "recovery"
    scan_root.mkdir()
    recovery.mkdir()
    capability = ResolvedMetadataWriteCapability(
        metadata_write_capability_id=_id(61),
        scan_root_id=plan.candidate.scan_root_id,
        scan_root_directory=scan_root,
        recovery_directory=recovery,
    )
    lease = OwnedScanRootWriteLease(
        scan_root_id=plan.candidate.scan_root_id,
        owner_kind=ScanRootWriteOwnerKind.METADATA_WRITE_PREPARATION,
        owner_run_id=_id(62),
        lease_token="synthetic-preparation-lease",
        fence_epoch=7,
        acquired_at=NOW - timedelta(seconds=1),
        heartbeat_at=NOW - timedelta(seconds=1),
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    preparation = build_epub3_title_write_preparation(
        plan=plan,
        preflight=preflight,
        patch=patch,
        verified_stage=verified,
        capability=capability,
        preparation_lease=lease,
        authorized_at=NOW,
        prepared_at=NOW + timedelta(seconds=1),
    )
    return plan, preflight, patch, verified, capability, lease, preparation


def test_preparation_authorization_and_run_bind_exact_verified_material(
    tmp_path: Path,
) -> None:
    plan, preflight, patch, verified, capability, lease, preparation = (
        _prepare_authorization_material(tmp_path)
    )

    repeated = build_epub3_title_write_preparation(
        plan=plan,
        preflight=preflight,
        patch=patch,
        verified_stage=verified,
        capability=capability,
        preparation_lease=lease,
        authorized_at=NOW,
        prepared_at=NOW + timedelta(seconds=1),
    )
    authorization = build_metadata_write_authorization(
        preparation,
        expires_at=NOW + timedelta(minutes=10),
    )
    run_id = _id(63)
    run_lease = replace(
        lease,
        owner_kind=ScanRootWriteOwnerKind.METADATA_WRITE_RUN,
        owner_run_id=run_id,
        lease_token="synthetic-run-lease",
        fence_epoch=8,
        acquired_at=NOW + timedelta(seconds=2),
        heartbeat_at=NOW + timedelta(seconds=2),
        lease_expires_at=NOW + timedelta(minutes=6),
    )
    run = build_metadata_write_run(
        authorization,
        capability,
        run_lease,
        run_id=run_id,
        created_at=NOW + timedelta(seconds=2),
    )

    assert preparation == repeated
    assert preparation.plan_id == plan.id
    assert preparation.source_sha256 == verified.staged_files.input_sha256
    assert preparation.expected_output_sha256 == verified.staged_files.output_sha256
    assert preparation.dcterms_modified == patch.dcterms_modified
    assert authorization.preparation_id == preparation.id
    assert authorization.expected_output_sha256 == preparation.expected_output_sha256
    assert run.authorization_id == authorization.id
    assert run.initial_fence_epoch == run_lease.fence_epoch
    for private_value in (
        PRIVATE_SELECTED_TITLE,
        str(verified.staged_files.private_directory),
        preparation.source_sha256,
        preparation.expected_output_sha256,
    ):
        assert private_value not in repr(preparation)
        assert private_value not in repr(authorization)


def test_preparation_rejects_wrong_capability_and_fence_without_private_output(
    tmp_path: Path,
) -> None:
    plan, preflight, patch, verified, capability, lease, _preparation = (
        _prepare_authorization_material(tmp_path)
    )
    wrong_capability = replace(capability, scan_root_id=_id(99))
    with pytest.raises(MetadataWriteAuthorizationError) as capability_error:
        build_epub3_title_write_preparation(
            plan=plan,
            preflight=preflight,
            patch=patch,
            verified_stage=verified,
            capability=wrong_capability,
            preparation_lease=lease,
            authorized_at=NOW,
            prepared_at=NOW + timedelta(seconds=1),
        )
    assert capability_error.value.code is MetadataWriteAuthorizationErrorCode.CAPABILITY_INVALID

    wrong_lease = replace(
        lease,
        owner_kind=ScanRootWriteOwnerKind.METADATA_WRITE_RUN,
    )
    with pytest.raises(MetadataWriteAuthorizationError) as lease_error:
        build_epub3_title_write_preparation(
            plan=plan,
            preflight=preflight,
            patch=patch,
            verified_stage=verified,
            capability=capability,
            preparation_lease=wrong_lease,
            authorized_at=NOW,
            prepared_at=NOW + timedelta(seconds=1),
        )
    assert lease_error.value.code is MetadataWriteAuthorizationErrorCode.LEASE_INVALID
    assert PRIVATE_SELECTED_TITLE not in str(capability_error.value)
    assert str(verified.staged_files.private_directory) not in str(lease_error.value)


def test_authorization_and_run_fail_closed_on_window_or_material_change(
    tmp_path: Path,
) -> None:
    _plan, _preflight_value, _patch, _verified, capability, lease, preparation = (
        _prepare_authorization_material(tmp_path)
    )
    with pytest.raises(MetadataWriteAuthorizationError) as expired:
        build_metadata_write_authorization(
            preparation,
            expires_at=preparation.prepared_at,
        )
    assert expired.value.code is MetadataWriteAuthorizationErrorCode.AUTHORIZATION_WINDOW_INVALID

    authorization = build_metadata_write_authorization(
        preparation,
        expires_at=NOW + timedelta(minutes=10),
    )
    with pytest.raises(MetadataWriteAuthorizationError) as tampered:
        replace(authorization, expected_output_sha256="f" * 64)
    assert tampered.value.code is MetadataWriteAuthorizationErrorCode.AUTHORIZATION_INVALID

    run_id = _id(64)
    wrong_lease = replace(
        lease,
        owner_kind=ScanRootWriteOwnerKind.METADATA_WRITE_RUN,
        owner_run_id=_id(65),
        lease_token="wrong-run-lease",
        fence_epoch=9,
        acquired_at=NOW + timedelta(seconds=2),
        heartbeat_at=NOW + timedelta(seconds=2),
        lease_expires_at=NOW + timedelta(minutes=6),
    )
    with pytest.raises(MetadataWriteAuthorizationError) as fenced:
        build_metadata_write_run(
            authorization,
            capability,
            wrong_lease,
            run_id=run_id,
            created_at=NOW + timedelta(seconds=2),
        )
    assert fenced.value.code is MetadataWriteAuthorizationErrorCode.LEASE_INVALID
