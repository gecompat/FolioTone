from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

import foliotone.archive.wrapper_stream as wrapper_stream
from foliotone.archive.safety_policy import MAX_SINGLE_MEMBER_BYTES
from foliotone.archive.sevenzip import (
    build_7zzs_tar_stdin_integrity_command,
    build_7zzs_tar_stdin_listing_command,
    build_7zzs_wrapper_decode_command,
)
from foliotone.archive.wrapper_stream import (
    ARCHIVE_TAR_STREAM_FRAME_PROFILE,
    MAX_TAR_STREAM_CHUNK_BYTES,
    ArchiveTarStreamFrameConsumer,
    ArchiveTarStreamFrameResult,
    ArchiveTarStreamFrameStatus,
    validate_archive_tar_stream,
)


def _tar_header(size: int, *, name: bytes = b"synthetic.bin") -> bytes:
    block = bytearray(512)
    block[: len(name)] = name
    block[100:108] = b"0000644\x00"
    block[108:116] = b"0000000\x00"
    block[116:124] = b"0000000\x00"
    block[124:136] = f"{size:011o}\0".encode("ascii")
    block[136:148] = b"00000000000\x00"
    block[148:156] = b"        "
    block[156:157] = b"0"
    block[257:263] = b"ustar\x00"
    block[263:265] = b"00"
    checksum = sum(block)
    block[148:156] = f"{checksum:06o}\0 ".encode("ascii")
    return bytes(block)


def _tar(payload: bytes = b"synthetic") -> bytes:
    padding = bytes((-len(payload)) % 512)
    return _tar_header(len(payload)) + payload + padding + bytes(1_024)


def test_fixed_wrapper_commands_are_exact_and_have_no_write_shape() -> None:
    assert build_7zzs_wrapper_decode_command() == (
        "/usr/local/bin/7zzs",
        "x",
        "-so",
        "-bd",
        "-bb0",
        "-bso0",
        "-bse0",
        "-bsp0",
        "-mmt=1",
        "--",
        "/workspace/input/archive",
    )
    assert build_7zzs_tar_stdin_listing_command() == (
        "/usr/local/bin/7zzs",
        "l",
        "-si",
        "-ttar",
        "-slt",
        "-ba",
        "-bd",
        "-bb0",
        "-bso1",
        "-bse0",
        "-bsp0",
        "-sccUTF-8",
    )
    assert build_7zzs_tar_stdin_integrity_command() == (
        "/usr/local/bin/7zzs",
        "t",
        "-si",
        "-ttar",
        "-bd",
        "-bb0",
        "-bso0",
        "-bse0",
        "-bsp0",
        "-sccUTF-8",
        "-mmt=1",
    )
    for command in (
        build_7zzs_wrapper_decode_command(),
        build_7zzs_tar_stdin_listing_command(),
        build_7zzs_tar_stdin_integrity_command(),
    ):
        assert not any(item.startswith(("-o", "-p")) for item in command)


@pytest.mark.parametrize("chunk_size", [1, 7, 511, 512, 513, 2_048])
def test_valid_stream_is_incremental_and_chunk_independent(chunk_size: int) -> None:
    payload = _tar()
    chunks = tuple(
        payload[index : index + chunk_size]
        for index in range(0, len(payload), chunk_size)
    )
    result = validate_archive_tar_stream(chunks)
    assert result.status is ArchiveTarStreamFrameStatus.VALID
    assert result.stream_size_bytes == len(payload)
    assert result.stream_sha256 == hashlib.sha256(payload).hexdigest()
    assert result.header_count == 1
    assert repr(result).find("synthetic.bin") == -1


def test_empty_tar_and_additional_zero_blocks_are_valid() -> None:
    empty = bytes(1_024)
    result = validate_archive_tar_stream((b"", empty[:13], empty[13:]))
    assert result.status is ArchiveTarStreamFrameStatus.VALID
    assert result.header_count == 0
    extended = validate_archive_tar_stream((empty + bytes(1_024),))
    assert extended.status is ArchiveTarStreamFrameStatus.VALID


@pytest.mark.parametrize(
    "payload",
    [
        _tar()[:-1],
        _tar()[:-512],
        _tar() + (b"x" * 512),
        _tar() + _tar(),
        _tar_header(0) + bytes(512),
        _tar()[: 512 + len(b"synthetic")] + b"x" + _tar()[512 + len(b"synthetic") + 1 :],
    ],
    ids=[
        "partial-block",
        "one-zero-block",
        "nonzero-tail",
        "concatenated",
        "one-end-block",
        "nonzero-padding",
    ],
)
def test_invalid_framing_discards_all_partial_values(payload: bytes) -> None:
    result = validate_archive_tar_stream((payload,))
    assert result == ArchiveTarStreamFrameResult(ArchiveTarStreamFrameStatus.INVALID)


def test_checksum_and_octal_grammar_fail_closed() -> None:
    bad_checksum = bytearray(_tar())
    bad_checksum[0] ^= 1
    assert (
        validate_archive_tar_stream((bytes(bad_checksum),)).status
        is ArchiveTarStreamFrameStatus.INVALID
    )

    bad_octal = bytearray(_tar())
    bad_octal[124:136] = b"0000000008\x00\x00"
    bad_octal[148:156] = b"        "
    bad_octal[148:156] = f"{sum(bad_octal[:512]):06o}\0 ".encode("ascii")
    assert (
        validate_archive_tar_stream((bytes(bad_octal),)).status
        is ArchiveTarStreamFrameStatus.INVALID
    )


def test_limits_and_iterable_errors_have_fixed_statuses(monkeypatch: pytest.MonkeyPatch) -> None:
    too_large = validate_archive_tar_stream((b"x" * (MAX_TAR_STREAM_CHUNK_BYTES + 1),))
    assert too_large.status is ArchiveTarStreamFrameStatus.LIMIT_EXCEEDED

    declared_too_large = _tar_header(MAX_SINGLE_MEMBER_BYTES + 1) + bytes(1_024)
    assert (
        validate_archive_tar_stream((declared_too_large,)).status
        is ArchiveTarStreamFrameStatus.LIMIT_EXCEEDED
    )

    monkeypatch.setattr(wrapper_stream, "MAX_TAR_STREAM_CHUNKS", 2)
    assert (
        validate_archive_tar_stream((b"", b"", b"")).status
        is ArchiveTarStreamFrameStatus.LIMIT_EXCEEDED
    )

    def broken() -> object:
        yield bytes(512)
        raise RuntimeError("private details")

    result = validate_archive_tar_stream(broken())  # type: ignore[arg-type]
    assert result.status is ArchiveTarStreamFrameStatus.INVALID
    assert "private details" not in repr(result)


def test_consumer_is_terminal_after_failure_or_finish() -> None:
    consumer = ArchiveTarStreamFrameConsumer()
    assert consumer.feed(_tar())
    valid = consumer.finish()
    assert valid.status is ArchiveTarStreamFrameStatus.VALID
    assert not consumer.feed(bytes(512))
    assert consumer.finish() is valid

    failed = ArchiveTarStreamFrameConsumer()
    assert not failed.feed("not-bytes")  # type: ignore[arg-type]
    assert failed.terminal_status is ArchiveTarStreamFrameStatus.INVALID
    assert failed.finish() == ArchiveTarStreamFrameResult(ArchiveTarStreamFrameStatus.INVALID)


def test_result_direct_construction_is_closed() -> None:
    valid = validate_archive_tar_stream((_tar(),))
    assert valid.profile == ARCHIVE_TAR_STREAM_FRAME_PROFILE
    for mutation in (
        {"profile": "foreign/v1"},
        {"stream_sha256": None},
        {"stream_size_bytes": 513},
        {"header_count": -1},
        {"status": "VALID"},
    ):
        with pytest.raises(ValueError):
            replace(valid, **mutation)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ArchiveTarStreamFrameResult(
            ArchiveTarStreamFrameStatus.INVALID,
            stream_size_bytes=1_024,
        )
