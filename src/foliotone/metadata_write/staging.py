"""Private streaming staging for the bounded EPUB 3 title writer."""

from __future__ import annotations

import hashlib
import struct
import zipfile
import zlib
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO, NoReturn

from foliotone.core import EntityId
from foliotone.metadata_write.contracts import (
    EPUB_TITLE_PATCHER_VERSION,
    EPUB_TITLE_WRITE_PROFILE,
    MAX_EPUB_ARCHIVE_BYTES,
    MAX_EPUB_ENTRIES,
    MAX_EPUB_PACKAGE_DOCUMENT_BYTES,
    EpubTitleArchiveDiff,
    EpubTitlePackagePatch,
    EpubTitleWritePreflight,
)
from foliotone.metadata_write.epub_title import validate_epub3_title_package_patch

EPUB_TITLE_STAGING_PROFILE = "epub3-title-private-staging/v1"
PRIVATE_STAGE_INPUT_NAME = "input.epub"
PRIVATE_STAGE_OUTPUT_NAME = "output.epub"

_CHUNK_BYTES = 1024 * 1024
_EOCD = struct.Struct("<4s4H2LH")
_CENTRAL_HEADER = struct.Struct("<4s6H3L5H2L")
_LOCAL_HEADER = struct.Struct("<4s5H3L2H")
_EOCD_SIGNATURE = b"PK\x05\x06"
_CENTRAL_SIGNATURE = b"PK\x01\x02"
_LOCAL_SIGNATURE = b"PK\x03\x04"
_DATA_DESCRIPTOR_SIGNATURE = b"PK\x07\x08"
_WINDOWS_REPARSE_POINT = 0x0400


class EpubTitleStagingErrorCode(StrEnum):
    """Path- and metadata-free failures for private staging and verification."""

    STAGE_DIRECTORY_INVALID = "STAGE_DIRECTORY_INVALID"
    STAGE_TARGET_EXISTS = "STAGE_TARGET_EXISTS"
    STAGE_IO_FAILED = "STAGE_IO_FAILED"
    SOURCE_IDENTITY_MISMATCH = "SOURCE_IDENTITY_MISMATCH"
    ARCHIVE_REBUILD_FAILED = "ARCHIVE_REBUILD_FAILED"
    ARCHIVE_DIFF_INVALID = "ARCHIVE_DIFF_INVALID"
    VALIDATION_TOOL_UNAVAILABLE = "VALIDATION_TOOL_UNAVAILABLE"
    VALIDATION_TOOL_FAILED = "VALIDATION_TOOL_FAILED"
    VALIDATION_EVIDENCE_INVALID = "VALIDATION_EVIDENCE_INVALID"
    METADATA_READBACK_MISMATCH = "METADATA_READBACK_MISMATCH"
    PRESERVED_FIELDS_MISMATCH = "PRESERVED_FIELDS_MISMATCH"
    EPUBCHECK_MISMATCH = "EPUBCHECK_MISMATCH"
    TEXT_READBACK_MISMATCH = "TEXT_READBACK_MISMATCH"
    COVER_READBACK_MISMATCH = "COVER_READBACK_MISMATCH"


class EpubTitleStagingError(RuntimeError):
    """One fixed-code failure without private paths, hashes, or metadata values."""

    def __init__(self, code: EpubTitleStagingErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


def _fail(code: EpubTitleStagingErrorCode) -> NoReturn:
    raise EpubTitleStagingError(code)


@dataclass(frozen=True, slots=True)
class EpubTitleStagedFiles:
    """Private input copy and rebuilt output; neither path is reportable evidence."""

    plan_id: EntityId
    plan_content_hash: str = field(repr=False)
    private_directory: Path = field(repr=False)
    input_path: Path = field(repr=False)
    output_path: Path = field(repr=False)
    input_sha256: str = field(repr=False)
    input_size_bytes: int
    output_sha256: str = field(repr=False)
    output_size_bytes: int
    archive_diff: EpubTitleArchiveDiff
    writer_profile: str = EPUB_TITLE_WRITE_PROFILE
    patcher_version: str = EPUB_TITLE_PATCHER_VERSION
    profile: str = EPUB_TITLE_STAGING_PROFILE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.plan_id, EntityId)
            or not isinstance(self.archive_diff, EpubTitleArchiveDiff)
            or not all(
                isinstance(value, Path)
                for value in (
                    self.private_directory,
                    self.input_path,
                    self.output_path,
                )
            )
        ):
            _fail(EpubTitleStagingErrorCode.ARCHIVE_DIFF_INVALID)
        if (
            self.profile != EPUB_TITLE_STAGING_PROFILE
            or self.writer_profile != EPUB_TITLE_WRITE_PROFILE
            or self.patcher_version != EPUB_TITLE_PATCHER_VERSION
            or self.input_size_bytes <= 0
            or self.output_size_bytes <= 0
            or self.input_size_bytes > MAX_EPUB_ARCHIVE_BYTES
            or self.output_size_bytes > MAX_EPUB_ARCHIVE_BYTES
            or not _is_sha256(self.plan_content_hash)
            or not _is_sha256(self.input_sha256)
            or not _is_sha256(self.output_sha256)
            or self.archive_diff.plan_id != self.plan_id
            or self.archive_diff.input_sha256 != self.input_sha256
            or self.archive_diff.output_sha256 != self.output_sha256
        ):
            _fail(EpubTitleStagingErrorCode.ARCHIVE_DIFF_INVALID)
        if (
            not self.private_directory.is_absolute()
            or self.input_path.parent != self.private_directory
            or self.output_path.parent != self.private_directory
            or self.input_path.name != PRIVATE_STAGE_INPUT_NAME
            or self.output_path.name != PRIVATE_STAGE_OUTPUT_NAME
        ):
            _fail(EpubTitleStagingErrorCode.STAGE_DIRECTORY_INVALID)


@dataclass(frozen=True, slots=True)
class _Eocd:
    entries: int
    central_size: int
    central_offset: int
    comment: bytes


@dataclass(frozen=True, slots=True)
class _Member:
    ordinal: int
    raw_name: bytes
    name: str
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
    descriptor: bytes


class _BoundedDigestWriter:
    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._digest = hashlib.sha256()
        self.size = 0

    def write(self, data: bytes) -> None:
        if self.size + len(data) > MAX_EPUB_ARCHIVE_BYTES:
            _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)
        written = self._stream.write(data)
        if written != len(data):
            _fail(EpubTitleStagingErrorCode.STAGE_IO_FAILED)
        self._digest.update(data)
        self.size += len(data)

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()


def build_private_epub3_title_stage(
    private_stage_directory: Path,
    source_stream: BinaryIO,
    preflight: EpubTitleWritePreflight,
    patch: EpubTitlePackagePatch,
) -> EpubTitleStagedFiles:
    """Copy an exact source and rebuild one private output without a source path."""
    validate_epub3_title_package_patch(preflight, patch)
    stage_directory = _create_private_stage_directory(private_stage_directory)
    input_path = stage_directory / PRIVATE_STAGE_INPUT_NAME
    output_path = stage_directory / PRIVATE_STAGE_OUTPUT_NAME

    input_sha256, input_size = _copy_exact_source(source_stream, input_path)
    if (
        input_sha256 != preflight.source_sha256
        or input_size != preflight.source_size_bytes
    ):
        _fail(EpubTitleStagingErrorCode.SOURCE_IDENTITY_MISMATCH)

    try:
        with input_path.open("rb") as input_file, output_path.open("xb") as output_file:
            output_sha256, output_size = _rebuild_archive(
                input_file,
                output_file,
                preflight,
                patch,
            )
    except EpubTitleStagingError:
        raise
    except (OSError, EOFError, struct.error, zlib.error) as error:
        raise EpubTitleStagingError(
            EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED
        ) from error

    if _stream_file_identity(input_path) != (input_sha256, input_size):
        _fail(EpubTitleStagingErrorCode.SOURCE_IDENTITY_MISMATCH)
    if _stream_file_identity(output_path) != (output_sha256, output_size):
        _fail(EpubTitleStagingErrorCode.ARCHIVE_DIFF_INVALID)
    archive_diff = verify_private_epub3_title_stage(preflight, patch, output_path)
    return EpubTitleStagedFiles(
        plan_id=preflight.plan_id,
        plan_content_hash=preflight.plan_content_hash,
        private_directory=stage_directory,
        input_path=input_path,
        output_path=output_path,
        input_sha256=input_sha256,
        input_size_bytes=input_size,
        output_sha256=output_sha256,
        output_size_bytes=output_size,
        archive_diff=archive_diff,
    )


def verify_private_epub3_title_stage(
    preflight: EpubTitleWritePreflight,
    patch: EpubTitlePackagePatch,
    output_path: Path,
) -> EpubTitleArchiveDiff:
    """Stream-verify the staged archive against the pure preflight and patch."""
    validate_epub3_title_package_patch(preflight, patch)
    try:
        output_sha256, output_size = _stream_file_identity(output_path)
        if (
            output_size <= 0
            or output_size > MAX_EPUB_ARCHIVE_BYTES
            or output_sha256 == preflight.source_sha256
        ):
            _fail(EpubTitleStagingErrorCode.ARCHIVE_DIFF_INVALID)
        with output_path.open("rb") as stream:
            records, eocd = _read_members(stream, output_size)
        if (
            len(records) != len(preflight.members)
            or hashlib.sha256(eocd.comment).hexdigest()
            != preflight.archive_comment_sha256
        ):
            _fail(EpubTitleStagingErrorCode.ARCHIVE_DIFF_INVALID)

        preserved = 0
        package_document: bytes | None = None
        with zipfile.ZipFile(output_path, mode="r") as archive:
            infos = archive.infolist()
            if len(infos) != len(records):
                _fail(EpubTitleStagingErrorCode.ARCHIVE_DIFF_INVALID)
            for ordinal, (record, info, before) in enumerate(
                zip(records, infos, preflight.members, strict=True)
            ):
                if (
                    ordinal != before.ordinal
                    or record.name != before.name
                    or record.raw_name != before.raw_name
                    or _metadata_fingerprint(record) != before.metadata_fingerprint
                    or info.filename != record.name
                ):
                    _fail(EpubTitleStagingErrorCode.ARCHIVE_DIFF_INVALID)
                capture = ordinal == preflight.package_member_ordinal
                digest, size, data = _read_member(archive, info, capture=capture)
                if capture:
                    if (
                        record.name != preflight.package_member_name
                        or digest != patch.patched_package_sha256
                        or size != len(patch.patched_package_document)
                        or data != patch.patched_package_document
                        or digest == before.content_sha256
                    ):
                        _fail(EpubTitleStagingErrorCode.ARCHIVE_DIFF_INVALID)
                    package_document = data
                else:
                    if digest != before.content_sha256 or size != before.uncompressed_size:
                        _fail(EpubTitleStagingErrorCode.ARCHIVE_DIFF_INVALID)
                    preserved += 1
        if package_document is None or preserved != len(preflight.members) - 1:
            _fail(EpubTitleStagingErrorCode.ARCHIVE_DIFF_INVALID)
    except EpubTitleStagingError:
        raise
    except (
        OSError,
        EOFError,
        struct.error,
        zipfile.BadZipFile,
        RuntimeError,
        NotImplementedError,
        zlib.error,
    ) as error:
        raise EpubTitleStagingError(EpubTitleStagingErrorCode.ARCHIVE_DIFF_INVALID) from error

    return EpubTitleArchiveDiff(
        plan_id=preflight.plan_id,
        input_sha256=preflight.source_sha256,
        output_sha256=output_sha256,
        original_package_sha256=preflight.package_document_sha256,
        patched_package_sha256=patch.patched_package_sha256,
        member_count=len(preflight.members),
        preserved_member_count=preserved,
    )


def _create_private_stage_directory(value: Path) -> Path:
    if not isinstance(value, Path) or not value.is_absolute() or value.name in {"", ".", ".."}:
        _fail(EpubTitleStagingErrorCode.STAGE_DIRECTORY_INVALID)
    if value.exists():
        _fail(EpubTitleStagingErrorCode.STAGE_TARGET_EXISTS)
    parent = value.parent
    try:
        resolved_parent = parent.resolve(strict=True)
        if (
            resolved_parent != parent
            or not resolved_parent.is_dir()
            or _is_link_or_reparse(resolved_parent)
        ):
            _fail(EpubTitleStagingErrorCode.STAGE_DIRECTORY_INVALID)
        value.mkdir(mode=0o700)
        resolved = value.resolve(strict=True)
    except EpubTitleStagingError:
        raise
    except FileExistsError as error:
        raise EpubTitleStagingError(EpubTitleStagingErrorCode.STAGE_TARGET_EXISTS) from error
    except OSError as error:
        raise EpubTitleStagingError(
            EpubTitleStagingErrorCode.STAGE_DIRECTORY_INVALID
        ) from error
    if resolved.parent != resolved_parent or _is_link_or_reparse(resolved):
        _fail(EpubTitleStagingErrorCode.STAGE_DIRECTORY_INVALID)
    return resolved


def _is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    return path.is_symlink() or bool(attributes & _WINDOWS_REPARSE_POINT)


def _copy_exact_source(source: BinaryIO, target: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("xb") as output:
            while chunk := source.read(_CHUNK_BYTES):
                if not isinstance(chunk, bytes):
                    _fail(EpubTitleStagingErrorCode.STAGE_IO_FAILED)
                size += len(chunk)
                if size > MAX_EPUB_ARCHIVE_BYTES:
                    _fail(EpubTitleStagingErrorCode.SOURCE_IDENTITY_MISMATCH)
                digest.update(chunk)
                if output.write(chunk) != len(chunk):
                    _fail(EpubTitleStagingErrorCode.STAGE_IO_FAILED)
    except EpubTitleStagingError:
        raise
    except (OSError, ValueError) as error:
        raise EpubTitleStagingError(EpubTitleStagingErrorCode.STAGE_IO_FAILED) from error
    return digest.hexdigest(), size


def _rebuild_archive(
    source: BinaryIO,
    target: BinaryIO,
    preflight: EpubTitleWritePreflight,
    patch: EpubTitlePackagePatch,
) -> tuple[str, int]:
    records, eocd = _read_members(source, preflight.source_size_bytes)
    if (
        len(records) != len(preflight.members)
        or len(records) > MAX_EPUB_ENTRIES
        or hashlib.sha256(eocd.comment).hexdigest() != preflight.archive_comment_sha256
    ):
        _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)
    for record, snapshot in zip(records, preflight.members, strict=True):
        if (
            record.ordinal != snapshot.ordinal
            or record.name != snapshot.name
            or record.raw_name != snapshot.raw_name
            or record.uncompressed_size != snapshot.uncompressed_size
            or _metadata_fingerprint(record) != snapshot.metadata_fingerprint
        ):
            _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)

    writer = _BoundedDigestWriter(target)
    output_records: list[_Member] = []
    for record in records:
        local_offset = writer.size
        if record.ordinal == preflight.package_member_ordinal:
            payload, crc32 = _compress_package(patch.patched_package_document, record)
            output_record = replace(
                record,
                crc32=crc32,
                compressed_size=len(payload),
                uncompressed_size=len(patch.patched_package_document),
                local_header_offset=local_offset,
                local_crc32=0 if record.flags & 0x0008 else crc32,
                local_compressed_size=0 if record.flags & 0x0008 else len(payload),
                local_uncompressed_size=(
                    0 if record.flags & 0x0008 else len(patch.patched_package_document)
                ),
                descriptor=(
                    _DATA_DESCRIPTOR_SIGNATURE
                    + struct.pack(
                        "<LLL",
                        crc32,
                        len(payload),
                        len(patch.patched_package_document),
                    )
                    if record.flags & 0x0008
                    else b""
                ),
            )
            _write_local_header(writer, output_record)
            writer.write(payload)
            writer.write(output_record.descriptor)
        else:
            output_record = replace(record, local_header_offset=local_offset)
            _write_local_header(writer, output_record)
            _copy_range(source, writer, record.local_data_offset, record.compressed_size)
            writer.write(record.descriptor)
        output_records.append(output_record)

    central_offset = writer.size
    for record in output_records:
        writer.write(
            _CENTRAL_HEADER.pack(
                _CENTRAL_SIGNATURE,
                record.version_made_by,
                record.version_needed,
                record.flags,
                record.compression,
                record.modified_time,
                record.modified_date,
                record.crc32,
                record.compressed_size,
                record.uncompressed_size,
                len(record.raw_name),
                len(record.central_extra),
                len(record.comment),
                record.disk_start,
                record.internal_attributes,
                record.external_attributes,
                record.local_header_offset,
            )
        )
        writer.write(record.raw_name)
        writer.write(record.central_extra)
        writer.write(record.comment)
    central_size = writer.size - central_offset
    writer.write(
        _EOCD.pack(
            _EOCD_SIGNATURE,
            0,
            0,
            len(output_records),
            len(output_records),
            central_size,
            central_offset,
            len(eocd.comment),
        )
    )
    writer.write(eocd.comment)
    target.flush()
    return writer.sha256, writer.size


def _write_local_header(writer: _BoundedDigestWriter, record: _Member) -> None:
    writer.write(
        _LOCAL_HEADER.pack(
            _LOCAL_SIGNATURE,
            record.version_needed,
            record.flags,
            record.compression,
            record.modified_time,
            record.modified_date,
            record.local_crc32,
            record.local_compressed_size,
            record.local_uncompressed_size,
            len(record.raw_name),
            len(record.local_extra),
        )
    )
    writer.write(record.raw_name)
    writer.write(record.local_extra)


def _compress_package(data: bytes, record: _Member) -> tuple[bytes, int]:
    if len(data) > MAX_EPUB_PACKAGE_DOCUMENT_BYTES:
        _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)
    crc32 = zlib.crc32(data) & 0xFFFFFFFF
    if record.compression == zipfile.ZIP_STORED:
        return data, crc32
    if record.compression != zipfile.ZIP_DEFLATED:
        _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)
    level = 9 if record.flags & 0x0002 else (1 if record.flags & 0x0004 else 6)
    compressor = zlib.compressobj(level, zlib.DEFLATED, -15)
    payload = bytearray()
    for offset in range(0, len(data), _CHUNK_BYTES):
        payload.extend(compressor.compress(data[offset : offset + _CHUNK_BYTES]))
    payload.extend(compressor.flush())
    return bytes(payload), crc32


def _read_members(stream: BinaryIO, file_size: int) -> tuple[tuple[_Member, ...], _Eocd]:
    eocd = _read_eocd(stream, file_size)
    stream.seek(eocd.central_offset)
    partial: list[_Member] = []
    for ordinal in range(eocd.entries):
        header = _read_exact(stream, _CENTRAL_HEADER.size)
        values = _CENTRAL_HEADER.unpack(header)
        if values[0] != _CENTRAL_SIGNATURE:
            _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)
        name_length = int(values[10])
        extra_length = int(values[11])
        comment_length = int(values[12])
        raw_name = _read_exact(stream, name_length)
        central_extra = _read_exact(stream, extra_length)
        comment = _read_exact(stream, comment_length)
        flags = int(values[3])
        partial.append(
            _Member(
                ordinal=ordinal,
                raw_name=raw_name,
                name=_decode_name(raw_name, flags),
                version_made_by=int(values[1]),
                version_needed=int(values[2]),
                flags=flags,
                compression=int(values[4]),
                modified_time=int(values[5]),
                modified_date=int(values[6]),
                crc32=int(values[7]),
                compressed_size=int(values[8]),
                uncompressed_size=int(values[9]),
                central_extra=central_extra,
                comment=comment,
                disk_start=int(values[13]),
                internal_attributes=int(values[14]),
                external_attributes=int(values[15]),
                local_header_offset=int(values[16]),
                local_extra=b"",
                local_crc32=0,
                local_compressed_size=0,
                local_uncompressed_size=0,
                local_data_offset=0,
                descriptor=b"",
            )
        )
    if stream.tell() != eocd.central_offset + eocd.central_size:
        _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)

    completed: list[_Member] = []
    for ordinal, record in enumerate(partial):
        stream.seek(record.local_header_offset)
        values = _LOCAL_HEADER.unpack(_read_exact(stream, _LOCAL_HEADER.size))
        if values[0] != _LOCAL_SIGNATURE:
            _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)
        raw_name = _read_exact(stream, int(values[9]))
        local_extra = _read_exact(stream, int(values[10]))
        if (
            int(values[1]) != record.version_needed
            or int(values[2]) != record.flags
            or int(values[3]) != record.compression
            or int(values[4]) != record.modified_time
            or int(values[5]) != record.modified_date
            or raw_name != record.raw_name
        ):
            _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)
        data_offset = stream.tell()
        data_end = data_offset + record.compressed_size
        boundary = (
            partial[ordinal + 1].local_header_offset
            if ordinal + 1 < len(partial)
            else eocd.central_offset
        )
        if data_end > boundary:
            _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)
        stream.seek(data_end)
        descriptor = _read_exact(stream, boundary - data_end)
        completed.append(
            replace(
                record,
                local_extra=local_extra,
                local_crc32=int(values[6]),
                local_compressed_size=int(values[7]),
                local_uncompressed_size=int(values[8]),
                local_data_offset=data_offset,
                descriptor=descriptor,
            )
        )
    return tuple(completed), eocd


def _read_eocd(stream: BinaryIO, file_size: int) -> _Eocd:
    if file_size < _EOCD.size or file_size > MAX_EPUB_ARCHIVE_BYTES:
        _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)
    tail_size = min(file_size, _EOCD.size + 65_535)
    stream.seek(file_size - tail_size)
    tail = _read_exact(stream, tail_size)
    for offset in range(tail_size - _EOCD.size, -1, -1):
        if tail[offset : offset + 4] != _EOCD_SIGNATURE:
            continue
        values = _EOCD.unpack_from(tail, offset)
        comment_length = int(values[7])
        if offset + _EOCD.size + comment_length != tail_size:
            continue
        entries = int(values[4])
        central_size = int(values[5])
        central_offset = int(values[6])
        if (
            int(values[1]) != 0
            or int(values[2]) != 0
            or int(values[3]) != entries
            or not 1 <= entries <= MAX_EPUB_ENTRIES
            or central_offset + central_size != file_size - tail_size + offset
        ):
            _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)
        return _Eocd(
            entries=entries,
            central_size=central_size,
            central_offset=central_offset,
            comment=tail[offset + _EOCD.size :],
        )
    _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)


def _copy_range(
    source: BinaryIO,
    target: _BoundedDigestWriter,
    offset: int,
    length: int,
) -> None:
    source.seek(offset)
    remaining = length
    while remaining:
        chunk = source.read(min(_CHUNK_BYTES, remaining))
        if not isinstance(chunk, bytes) or not chunk:
            _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)
        target.write(chunk)
        remaining -= len(chunk)


def _read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    capture: bool,
) -> tuple[str, int, bytes | None]:
    digest = hashlib.sha256()
    size = 0
    data = bytearray() if capture else None
    with archive.open(info, mode="r") as member:
        while chunk := member.read(_CHUNK_BYTES):
            size += len(chunk)
            if size > info.file_size:
                _fail(EpubTitleStagingErrorCode.ARCHIVE_DIFF_INVALID)
            digest.update(chunk)
            if data is not None:
                if len(data) + len(chunk) > MAX_EPUB_PACKAGE_DOCUMENT_BYTES:
                    _fail(EpubTitleStagingErrorCode.ARCHIVE_DIFF_INVALID)
                data.extend(chunk)
    if size != info.file_size:
        _fail(EpubTitleStagingErrorCode.ARCHIVE_DIFF_INVALID)
    return digest.hexdigest(), size, None if data is None else bytes(data)


def _stream_file_identity(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    if _is_link_or_reparse(path) or not path.is_file():
        _fail(EpubTitleStagingErrorCode.STAGE_IO_FAILED)
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            size += len(chunk)
            if size > MAX_EPUB_ARCHIVE_BYTES:
                _fail(EpubTitleStagingErrorCode.ARCHIVE_DIFF_INVALID)
            digest.update(chunk)
    return digest.hexdigest(), size


def _metadata_fingerprint(record: _Member) -> str:
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
        digest.update(integer_value.to_bytes(8, "little", signed=False))
    for byte_value in (
        record.raw_name,
        record.central_extra,
        record.local_extra,
        record.comment,
    ):
        digest.update(len(byte_value).to_bytes(8, "little", signed=False))
        digest.update(byte_value)
    return digest.hexdigest()


def _decode_name(raw_name: bytes, flags: int) -> str:
    try:
        return raw_name.decode("utf-8" if flags & 0x0800 else "ascii")
    except UnicodeDecodeError as error:
        raise EpubTitleStagingError(
            EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED
        ) from error


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    if size < 0:
        _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)
    data = stream.read(size)
    if not isinstance(data, bytes) or len(data) != size:
        _fail(EpubTitleStagingErrorCode.ARCHIVE_REBUILD_FAILED)
    return data


def _is_sha256(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "EPUB_TITLE_STAGING_PROFILE",
    "PRIVATE_STAGE_INPUT_NAME",
    "PRIVATE_STAGE_OUTPUT_NAME",
    "EpubTitleStagedFiles",
    "EpubTitleStagingError",
    "EpubTitleStagingErrorCode",
    "build_private_epub3_title_stage",
    "verify_private_epub3_title_stage",
]
