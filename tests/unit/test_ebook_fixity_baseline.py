from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from foliotone.core import EntityId
from foliotone.fixity import (
    EBOOK_FIXITY_BASELINE_PROFILE,
    EBOOK_FIXITY_BASELINE_SERIALIZER,
    EbookFixityBaselineEntriesHasher,
    EbookFixityBaselineEntry,
    EbookFixityBaselineManifest,
    EbookFixityBaselineSourceEntry,
    expected_fixity_baseline_confirmation,
    verify_fixity_baseline_confirmation,
)

NOW = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
SHA_A = "a" * 64


def _entry(ordinal: int = 0) -> EbookFixityBaselineEntry:
    return EbookFixityBaselineEntry(
        ordinal=ordinal,
        file_id=EntityId.new(),
        observation_id=EntityId.new(),
        expected_size_bytes=7,
        relative_locator="books/example.epub",
        expected_sha256=SHA_A,
    )


def test_entry_is_immutable_private_and_content_bound() -> None:
    entry = _entry()

    assert "books/example.epub" not in repr(entry)
    assert SHA_A not in repr(entry)
    assert len(entry.entry_digest) == 64
    with pytest.raises(FrozenInstanceError):
        entry.ordinal = 1  # type: ignore[misc]
    with pytest.raises(ValueError, match="entry_digest"):
        EbookFixityBaselineEntry(
            ordinal=entry.ordinal,
            file_id=entry.file_id,
            observation_id=entry.observation_id,
            expected_size_bytes=entry.expected_size_bytes,
            relative_locator=entry.relative_locator,
            expected_sha256=entry.expected_sha256,
            entry_digest="b" * 64,
        )


@pytest.mark.parametrize(
    "locator",
    (
        "/private/book.epub",
        "../book.epub",
        "folder/../book.epub",
        "folder\\book.epub",
        "folder//book.epub",
        "folder/./book.epub",
    ),
)
def test_private_locator_rejects_absolute_escaping_or_noncanonical_values(
    locator: str,
) -> None:
    with pytest.raises(ValueError, match="relative_locator"):
        EbookFixityBaselineSourceEntry(
            file_id=EntityId.new(),
            observation_id=EntityId.new(),
            relative_locator=locator,
            expected_size_bytes=1,
            expected_modified_at=NOW,
        )


def test_entries_hasher_requires_gapless_order() -> None:
    hasher = EbookFixityBaselineEntriesHasher()
    first = _entry(0)
    hasher.update(first)

    assert hasher.count == 1
    assert len(hasher.hexdigest()) == 64
    with pytest.raises(ValueError, match="contiguous"):
        hasher.update(_entry(2))


def test_manifest_uses_exact_profiles_and_at_most_fifteen_minutes() -> None:
    manifest = EbookFixityBaselineManifest(
        manifest_id=EntityId.new(),
        scan_root_id=EntityId.new(),
        source_scan_run_id=EntityId.new(),
        prepared_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        item_count=1,
        total_size_bytes=7,
        entries_digest=SHA_A,
    )

    assert manifest.profile == EBOOK_FIXITY_BASELINE_PROFILE
    assert manifest.serializer == EBOOK_FIXITY_BASELINE_SERIALIZER
    assert len(manifest.content_digest) == 64
    with pytest.raises(ValueError, match="15 minutes"):
        EbookFixityBaselineManifest(
            manifest_id=EntityId.new(),
            scan_root_id=EntityId.new(),
            source_scan_run_id=EntityId.new(),
            prepared_at=NOW,
            expires_at=NOW + timedelta(minutes=15, microseconds=1),
            item_count=0,
            total_size_bytes=0,
            entries_digest=SHA_A,
        )


def test_confirmation_is_exact_and_only_digest_is_returned() -> None:
    manifest_id = EntityId.new()
    expected = expected_fixity_baseline_confirmation(manifest_id)

    digest = verify_fixity_baseline_confirmation(manifest_id, expected)

    assert len(digest) == 64
    assert expected not in digest
    for invalid in (expected.lower(), f" {expected}", f"{expected}\n"):
        with pytest.raises(ValueError, match="does not match"):
            verify_fixity_baseline_confirmation(manifest_id, invalid)
