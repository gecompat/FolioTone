"""Integrity checks for the inert synthetic ADR-0038 archive fixtures."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE = Path(__file__).parents[1] / "fixtures" / "archive" / "v1" / "archive_cases.json"


def test_archive_fixture_manifest_is_small_inert_and_contract_complete() -> None:
    raw = FIXTURE.read_bytes()
    manifest = json.loads(raw)

    assert len(raw) < 16_384
    assert manifest["schema_version"] == 1
    assert manifest["synthetic_only"] is True
    assert not any(marker in raw.lower() for marker in (b"password", b"passwort", b"secret"))

    signatures = {case["name"]: case for case in manifest["signatures"]}
    assert set(signatures) == {
        "zip-local",
        "zip-empty",
        "zip-spanned",
        "epub-basis",
        "cbz-basis",
        "rar4",
        "cbr-basis",
        "rar5",
        "seven-z",
        "gzip-outer",
        "bzip2-outer",
        "xz-outer",
        "zstd-outer",
        "suffix-mismatch",
        "unknown",
        "tar-header-only",
    }
    assert bytes.fromhex(signatures["zip-local"]["header_hex"]) == b"PK\x03\x04"
    assert bytes.fromhex(signatures["rar4"]["header_hex"]) == b"Rar!\x1a\x07\x00"
    assert bytes.fromhex(signatures["rar5"]["header_hex"]) == b"Rar!\x1a\x07\x01\x00"
    assert bytes.fromhex(signatures["seven-z"]["header_hex"]) == b"7z\xbc\xaf'\x1c"

    tar_case = signatures["tar-header-only"]
    tar_header = bytearray.fromhex(tar_case["header_hex"] + tar_case["tail_padding_hex"])
    assert len(tar_header) == 512
    assert tar_header[257:263] == b"ustar\x00"
    stored_checksum = int(tar_header[148:154], 8)
    tar_header[148:156] = b"        "
    assert stored_checksum == tar_case["expected_checksum"]
    assert sum(tar_header) == stored_checksum

    groups = {case["name"]: case for case in manifest["volume_groups"]}
    assert groups == {
        "rar-new-valid": {
            "name": "rar-new-valid",
            "members": ["book.part01.rar", "book.part02.rar"],
            "expected_status": "LISTED",
        },
        "rar-new-gap": {
            "name": "rar-new-gap",
            "members": ["book.part01.rar", "book.part03.rar"],
            "expected_status": "MISSING_VOLUME",
        },
        "rar-new-mixed-width": {
            "name": "rar-new-mixed-width",
            "members": ["book.part1.rar", "book.part02.rar"],
            "expected_status": "POLICY_REJECTED",
        },
        "rar-old-valid": {
            "name": "rar-old-valid",
            "members": ["book.rar", "book.r00", "book.r01"],
            "expected_status": "LISTED",
        },
        "seven-z-valid": {
            "name": "seven-z-valid",
            "members": ["book.7z.001", "book.7z.002"],
            "expected_status": "LISTED",
        },
        "seven-z-gap": {
            "name": "seven-z-gap",
            "members": ["book.7z.001", "book.7z.003"],
            "expected_status": "MISSING_VOLUME",
        },
        "split-zip-inventory": {
            "name": "split-zip-inventory",
            "members": ["book.z01", "book.z02", "book.zip"],
            "expected_status": "UNSUPPORTED_FORMAT",
        },
    }

    # The manifest contains signatures only.  It is not an extractable archive corpus.
    archive_suffixes = {".zip", ".rar", ".7z", ".tar"}
    assert not any(path.suffix.lower() in archive_suffixes for path in FIXTURE.parent.iterdir())
