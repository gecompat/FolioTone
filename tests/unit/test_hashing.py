import hashlib
from pathlib import Path

import pytest

from foliotone.index.hashing import (
    HashMode,
    calculate_hashes,
    quick_file_fingerprint,
    stream_sha256,
)


def test_stream_sha256_matches_hashlib_with_small_chunks(tmp_path: Path) -> None:
    path = tmp_path / "sample.bin"
    payload = b"abcdefghijklmnopqrstuvwxyz" * 100
    path.write_bytes(payload)
    assert stream_sha256(path, chunk_bytes=7) == hashlib.sha256(payload).hexdigest()


def test_quick_fingerprint_changes_when_head_or_tail_changes(tmp_path: Path) -> None:
    path = tmp_path / "sample.bin"
    payload = bytearray(b"x" * 200_000)
    path.write_bytes(payload)
    baseline = quick_file_fingerprint(path)

    payload[0] = ord("a")
    path.write_bytes(payload)
    head_changed = quick_file_fingerprint(path)
    assert head_changed != baseline

    payload[-1] = ord("b")
    path.write_bytes(payload)
    assert quick_file_fingerprint(path) != head_changed


def test_hash_modes_are_staged(tmp_path: Path) -> None:
    path = tmp_path / "sample.bin"
    path.write_bytes(b"synthetic")

    assert calculate_hashes(path, HashMode.NONE).quick is None
    quick = calculate_hashes(path, HashMode.QUICK)
    assert quick.quick is not None
    assert quick.sha256 is None

    full = calculate_hashes(path, HashMode.FULL)
    assert full.quick == quick.quick
    assert full.sha256 == hashlib.sha256(b"synthetic").hexdigest()


def test_stream_hash_stops_on_cooperative_cancellation(tmp_path: Path) -> None:
    path = tmp_path / "sample.bin"
    path.write_bytes(b"synthetic")

    with pytest.raises(RuntimeError, match="hashing was cancelled"):
        stream_sha256(path, chunk_bytes=2, cancelled=lambda: True)
