from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from foliotone.archive.safety_policy import (
    MAX_MEMBER_COUNT,
    MAX_SINGLE_MEMBER_BYTES,
    MAX_TOTAL_UNCOMPRESSED_BYTES,
)

ARCHIVE_TAR_STREAM_FRAME_PROFILE: Final = "archive-tar-stream-frame/v1"
TAR_BLOCK_BYTES: Final = 512
MAX_TAR_STREAM_CHUNK_BYTES: Final = 262_144
MAX_TAR_STREAM_CHUNKS: Final = 65_536
MAX_TAR_HEADER_COUNT: Final = MAX_MEMBER_COUNT * 2
MAX_TAR_STREAM_BYTES: Final = (
    MAX_TOTAL_UNCOMPRESSED_BYTES + MAX_TAR_HEADER_COUNT * 1_024 + 1_024
)

_OCTAL_FIELD = re.compile(rb" *[0-7]+[\x00 ]*").fullmatch
_SHA256 = re.compile(r"[0-9a-f]{64}").fullmatch
_ZERO_BLOCK: Final = bytes(TAR_BLOCK_BYTES)


class ArchiveTarStreamFrameStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"


@dataclass(frozen=True, slots=True)
class ArchiveTarStreamFrameResult:
    status: ArchiveTarStreamFrameStatus
    stream_size_bytes: int = 0
    stream_sha256: str | None = None
    header_count: int = 0
    profile: str = ARCHIVE_TAR_STREAM_FRAME_PROFILE

    def __post_init__(self) -> None:
        if not isinstance(self.status, ArchiveTarStreamFrameStatus):
            raise ValueError("invalid tar stream frame status")
        if self.profile != ARCHIVE_TAR_STREAM_FRAME_PROFILE:
            raise ValueError("invalid tar stream frame profile")
        if self.status is ArchiveTarStreamFrameStatus.VALID:
            if (
                isinstance(self.stream_size_bytes, bool)
                or not 1_024 <= self.stream_size_bytes <= MAX_TAR_STREAM_BYTES
                or self.stream_size_bytes % TAR_BLOCK_BYTES
                or not isinstance(self.stream_sha256, str)
                or _SHA256(self.stream_sha256) is None
                or isinstance(self.header_count, bool)
                or not 0 <= self.header_count <= MAX_TAR_HEADER_COUNT
            ):
                raise ValueError("invalid valid tar stream frame result")
        elif (
            self.stream_size_bytes != 0
            or self.stream_sha256 is not None
            or self.header_count != 0
        ):
            raise ValueError("failed tar stream frame result contains partial values")


class ArchiveTarStreamFrameConsumer:
    """Incrementally validate a bounded TAR byte stream without retaining it."""

    __slots__ = (
        "_buffer",
        "_chunk_count",
        "_finished",
        "_hash",
        "_header_count",
        "_payload_bytes",
        "_payload_padding_remaining",
        "_payload_size_remaining",
        "_result",
        "_stream_size_bytes",
        "_zero_blocks",
    )

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._chunk_count = 0
        self._finished = False
        self._hash = hashlib.sha256()
        self._header_count = 0
        self._payload_bytes = 0
        self._payload_padding_remaining = 0
        self._payload_size_remaining = 0
        self._result: ArchiveTarStreamFrameResult | None = None
        self._stream_size_bytes = 0
        self._zero_blocks = 0

    @property
    def terminal_status(self) -> ArchiveTarStreamFrameStatus | None:
        return self._result.status if self._result is not None else None

    def feed(self, chunk: bytes) -> bool:
        if self._finished or self._result is not None:
            return False
        self._chunk_count += 1
        if not isinstance(chunk, bytes):
            self._fail(ArchiveTarStreamFrameStatus.INVALID)
            return False
        if (
            self._chunk_count > MAX_TAR_STREAM_CHUNKS
            or len(chunk) > MAX_TAR_STREAM_CHUNK_BYTES
            or self._stream_size_bytes + len(chunk) > MAX_TAR_STREAM_BYTES
        ):
            self._fail(ArchiveTarStreamFrameStatus.LIMIT_EXCEEDED)
            return False
        self._stream_size_bytes += len(chunk)
        self._hash.update(chunk)
        self._buffer.extend(chunk)
        while len(self._buffer) >= TAR_BLOCK_BYTES:
            block = bytes(self._buffer[:TAR_BLOCK_BYTES])
            del self._buffer[:TAR_BLOCK_BYTES]
            if not self._accept_block(block):
                return False
        return True

    def finish(self) -> ArchiveTarStreamFrameResult:
        if self._result is not None:
            return self._result
        self._finished = True
        if (
            self._buffer
            or self._payload_padding_remaining
            or self._payload_size_remaining
            or self._zero_blocks < 2
        ):
            return self._fail(ArchiveTarStreamFrameStatus.INVALID)
        self._result = ArchiveTarStreamFrameResult(
            ArchiveTarStreamFrameStatus.VALID,
            self._stream_size_bytes,
            self._hash.hexdigest(),
            self._header_count,
        )
        return self._result

    def _accept_block(self, block: bytes) -> bool:
        if self._payload_padding_remaining:
            payload_bytes = min(self._payload_size_remaining, TAR_BLOCK_BYTES)
            if payload_bytes < TAR_BLOCK_BYTES and any(block[payload_bytes:]):
                self._fail(ArchiveTarStreamFrameStatus.INVALID)
                return False
            self._payload_size_remaining -= payload_bytes
            self._payload_padding_remaining -= TAR_BLOCK_BYTES
            return True
        if block == _ZERO_BLOCK:
            self._zero_blocks += 1
            return True
        if self._zero_blocks:
            self._fail(ArchiveTarStreamFrameStatus.INVALID)
            return False
        if not _checksum_is_valid(block):
            self._fail(ArchiveTarStreamFrameStatus.INVALID)
            return False
        size = _parse_octal(block[124:136])
        if size is None:
            self._fail(ArchiveTarStreamFrameStatus.INVALID)
            return False
        self._header_count += 1
        if (
            self._header_count > MAX_TAR_HEADER_COUNT
            or size > MAX_SINGLE_MEMBER_BYTES
            or self._payload_bytes + size > MAX_TOTAL_UNCOMPRESSED_BYTES
        ):
            self._fail(ArchiveTarStreamFrameStatus.LIMIT_EXCEEDED)
            return False
        self._payload_bytes += size
        self._payload_size_remaining = size
        self._payload_padding_remaining = (
            (size + TAR_BLOCK_BYTES - 1) // TAR_BLOCK_BYTES
        ) * TAR_BLOCK_BYTES
        return True

    def _fail(
        self, status: ArchiveTarStreamFrameStatus
    ) -> ArchiveTarStreamFrameResult:
        self._buffer.clear()
        self._result = ArchiveTarStreamFrameResult(status)
        return self._result


def validate_archive_tar_stream(chunks: Iterable[bytes]) -> ArchiveTarStreamFrameResult:
    consumer = ArchiveTarStreamFrameConsumer()
    try:
        for chunk in chunks:
            if not consumer.feed(chunk):
                break
    except Exception:
        return ArchiveTarStreamFrameResult(ArchiveTarStreamFrameStatus.INVALID)
    return consumer.finish()


def _parse_octal(field: bytes) -> int | None:
    if _OCTAL_FIELD(field) is None:
        return None
    digits = field.strip(b"\x00 ")
    if not digits:
        return None
    try:
        return int(digits, 8)
    except ValueError:
        return None


def _checksum_is_valid(block: bytes) -> bool:
    if len(block) != TAR_BLOCK_BYTES:
        return False
    stored = _parse_octal(block[148:156])
    if stored is None:
        return False
    return stored == sum(block[:148]) + (8 * 32) + sum(block[156:])
