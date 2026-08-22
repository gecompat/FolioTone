from __future__ import annotations

import hashlib
import os
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from foliotone.core import EntityId
from foliotone.metadata_write import (
    EpubTitleWritePreparationSnapshot,
    ResolvedMetadataWriteCapability,
    build_metadata_write_authorization,
    build_metadata_write_run,
)
from foliotone.metadata_write.authorization import (
    _preparation_hash_from_material,
    _preparation_id,
)
from foliotone.metadata_write.linux_backend import (
    LinuxMetadataWriteBackend,
    LinuxMetadataWriteBackendError,
    LinuxMetadataWriteBackendErrorCode,
    LinuxMetadataWritePhysicalState,
    _require_glibc,
    _source_locator,
)
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteOwnerKind,
)

NOW = datetime(2026, 8, 22, 19, 0, tzinfo=UTC)
ROOT_ID = EntityId.parse("a1000000-0000-0000-0000-000000000001")
FILE_ID = EntityId.parse("a1000000-0000-0000-0000-000000000002")
OBSERVATION_ID = EntityId.parse("a1000000-0000-0000-0000-000000000003")
PLAN_ID = EntityId.parse("a1000000-0000-0000-0000-000000000004")
PREPARATION_OWNER_ID = EntityId.parse("a1000000-0000-0000-0000-000000000005")
CAPABILITY_ID = EntityId.parse("a1000000-0000-0000-0000-000000000006")
RUN_ID = EntityId.parse("a1000000-0000-0000-0000-000000000007")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _operation(
    source: bytes,
    output: bytes,
    source_root: Path,
    recovery: Path,
):
    capability = ResolvedMetadataWriteCapability(
        CAPABILITY_ID,
        ROOT_ID,
        source_root,
        recovery,
    )
    authorized_at = NOW
    prepared_at = NOW + timedelta(seconds=1)
    material = {
        "preparation_owner_id": PREPARATION_OWNER_ID,
        "preparation_fence_epoch": 1,
        "plan_id": PLAN_ID,
        "plan_content_hash": "1" * 64,
        "scan_root_id": ROOT_ID,
        "file_id": FILE_ID,
        "observation_id": OBSERVATION_ID,
        "source_sha256": _sha(source),
        "source_size_bytes": len(source),
        "expected_output_sha256": _sha(output),
        "expected_output_size_bytes": len(output),
        "metadata_write_capability_id": CAPABILITY_ID,
        "dcterms_modified": "2026-08-22T19:00:01Z",
        "authorized_at": authorized_at,
        "prepared_at": prepared_at,
        "metadata_tool_version": "ebook-meta calibre 9.13.0",
        "epubcheck_tool_version": "EPUBCheck v5.3.0",
        "text_tool_version": "ebook-convert calibre 9.13.0",
        "cover_tool_version": "calibre-debug calibre 9.13.0",
        "validator_set_fingerprint": "2" * 64,
    }
    preparation_hash = _preparation_hash_from_material(material)
    preparation = EpubTitleWritePreparationSnapshot(
        id=_preparation_id(preparation_hash),
        content_hash=preparation_hash,
        **material,
    )
    authorization = build_metadata_write_authorization(
        preparation,
        expires_at=NOW + timedelta(minutes=10),
    )
    lease = OwnedScanRootWriteLease(
        scan_root_id=ROOT_ID,
        owner_kind=ScanRootWriteOwnerKind.METADATA_WRITE_RUN,
        owner_run_id=RUN_ID,
        lease_token="synthetic-linux-backend",
        fence_epoch=2,
        acquired_at=NOW,
        heartbeat_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=15),
    )
    run = build_metadata_write_run(
        authorization,
        capability,
        lease,
        run_id=RUN_ID,
        created_at=NOW + timedelta(seconds=2),
    )
    return capability, authorization, run


@pytest.fixture
def linux_tmpfs() -> Path:
    root = Path("/dev/shm")
    if sys.platform != "linux" or not root.is_dir() or not os.access(root, os.W_OK):
        pytest.skip("Linux tmpfs is required for the renameat2 conformance gate")
    sandbox = root / f"foliotone-mw04-{uuid4()}"
    sandbox.mkdir(mode=0o700)
    try:
        yield sandbox
    finally:
        shutil.rmtree(sandbox)


def _filesystem(linux_tmpfs: Path):
    source_root = linux_tmpfs / "source"
    source_parent = source_root / "books"
    recovery = linux_tmpfs / "recovery"
    stage = linux_tmpfs / "stage"
    for directory in (source_root, source_parent, recovery, stage):
        directory.mkdir(mode=0o700)
    source = b"synthetic-original-epub-bytes\n"
    output = b"synthetic-updated-epub-bytes\n"
    source_path = source_parent / "book.epub"
    stage_path = stage / "output.epub"
    source_path.write_bytes(source)
    source_path.chmod(0o640)
    stage_path.write_bytes(output)
    details = source_path.stat()
    modified_at = datetime.fromtimestamp(details.st_mtime, tz=UTC)
    capability, authorization, run = _operation(
        source,
        output,
        source_root,
        recovery,
    )
    return (
        source,
        output,
        source_path,
        stage_path,
        recovery,
        modified_at,
        capability,
        authorization,
        run,
    )


def test_backend_fails_closed_outside_native_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = b"source"
    output = b"output"
    source_root = Path("C:/synthetic/source") if os.name == "nt" else Path("/synthetic/source")
    recovery = (
        Path("C:/synthetic/recovery")
        if os.name == "nt"
        else Path("/synthetic/recovery")
    )
    capability, authorization, run = _operation(
        source,
        output,
        source_root,
        recovery,
    )
    monkeypatch.setattr("foliotone.metadata_write.linux_backend.sys.platform", "win32")

    with pytest.raises(LinuxMetadataWriteBackendError) as raised:
        LinuxMetadataWriteBackend().open_session(
            capability=capability,
            source_relative_path="book.epub",
            authorization=authorization,
            run=run,
            expected_modified_at=NOW,
        )

    assert raised.value.code is LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE
    assert str(raised.value) == "TOOL_UNAVAILABLE"


def test_backend_rejects_non_glibc_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "confstr", lambda _name: "musl 1.2", raising=False)

    with pytest.raises(LinuxMetadataWriteBackendError) as raised:
        _require_glibc()

    assert raised.value.code is LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE


@pytest.mark.parametrize(
    "value",
    (
        "../book.epub",
        "/absolute/book.epub",
        "books//book.epub",
        "books/book.pdf",
        "books/./book.epub",
    ),
)
def test_backend_rejects_untrusted_source_locators(value: str) -> None:
    with pytest.raises(LinuxMetadataWriteBackendError) as raised:
        _source_locator(value)

    assert raised.value.code is LinuxMetadataWriteBackendErrorCode.SOURCE_STALE


def test_linux_tmpfs_exchange_preserve_and_restore_are_exact(
    linux_tmpfs: Path,
) -> None:
    (
        source,
        output,
        source_path,
        stage_path,
        recovery,
        modified_at,
        capability,
        authorization,
        run,
    ) = _filesystem(linux_tmpfs)

    with LinuxMetadataWriteBackend().open_session(
        capability=capability,
        source_relative_path="books/book.epub",
        authorization=authorization,
        run=run,
        expected_modified_at=modified_at,
    ) as session:
        assert session.read_source_bytes() == source
        assert session.classify().state is LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_ONLY
        assert (
            session.prepare_output(stage_path).state
            is LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT
        )
        assert (
            session.exchange().state
            is LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_ORIGINAL_DRAFT
        )
        assert source_path.read_bytes() == output
        assert source_path.stat().st_mode & 0o777 == 0o640
        assert (
            session.preserve_original().state
            is LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_PRESERVED_ORIGINAL
        )
        preserved_files = tuple(path for path in recovery.iterdir() if path.is_file())
        assert len(preserved_files) == 1
        assert preserved_files[0].read_bytes() == source
        assert preserved_files[0].stat().st_mode & 0o777 == 0o640
        restored = session.restore_original()
        assert (
            restored.state
            is LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT
        )
        assert session.restore_original() == restored

    assert source_path.read_bytes() == source
    assert source_path.stat().st_mode & 0o777 == 0o640
    draft = source_path.parent / f".foliotone-metadata-write-{run.id}.draft.epub"
    assert draft.read_bytes() == output
    assert draft.stat().st_mode & 0o777 == 0o640


def test_linux_tmpfs_recovery_collision_never_overwrites(
    linux_tmpfs: Path,
) -> None:
    (
        source,
        output,
        source_path,
        stage_path,
        recovery,
        modified_at,
        capability,
        authorization,
        run,
    ) = _filesystem(linux_tmpfs)
    collision = recovery / f"original-{authorization.source_sha256}-{run.id}.epub"

    with LinuxMetadataWriteBackend().open_session(
        capability=capability,
        source_relative_path="books/book.epub",
        authorization=authorization,
        run=run,
        expected_modified_at=modified_at,
    ) as session:
        session.prepare_output(stage_path)
        session.exchange()
        collision.write_bytes(b"synthetic-collision")
        with pytest.raises(LinuxMetadataWriteBackendError):
            session.preserve_original()
        assert collision.read_bytes() == b"synthetic-collision"
        assert (
            session.classify().state
            is LinuxMetadataWritePhysicalState.AMBIGUOUS
        )
        with pytest.raises(LinuxMetadataWriteBackendError) as restore_error:
            session.restore_original()

    assert restore_error.value.code is (
        LinuxMetadataWriteBackendErrorCode.STATE_AMBIGUOUS
    )
    assert source_path.read_bytes() == output
    draft = source_path.parent / f".foliotone-metadata-write-{run.id}.draft.epub"
    assert draft.read_bytes() == source
    assert collision.read_bytes() == b"synthetic-collision"
    assert output != source


def test_linux_tmpfs_source_change_before_exchange_is_never_replaced(
    linux_tmpfs: Path,
) -> None:
    (
        _source,
        _output,
        source_path,
        stage_path,
        _recovery,
        modified_at,
        capability,
        authorization,
        run,
    ) = _filesystem(linux_tmpfs)
    changed = b"synthetic-concurrent-change\n"

    with LinuxMetadataWriteBackend().open_session(
        capability=capability,
        source_relative_path="books/book.epub",
        authorization=authorization,
        run=run,
        expected_modified_at=modified_at,
    ) as session:
        session.prepare_output(stage_path)
        source_path.write_bytes(changed)
        with pytest.raises(LinuxMetadataWriteBackendError) as raised:
            session.exchange()

    assert raised.value.code is LinuxMetadataWriteBackendErrorCode.SOURCE_STALE
    assert source_path.read_bytes() == changed


def test_linux_tmpfs_hardlink_source_is_stale(
    linux_tmpfs: Path,
) -> None:
    (
        _source,
        _output,
        source_path,
        _stage_path,
        _recovery,
        modified_at,
        capability,
        authorization,
        run,
    ) = _filesystem(linux_tmpfs)
    os.link(source_path, source_path.parent / "second-name.epub")

    with LinuxMetadataWriteBackend().open_session(
        capability=capability,
        source_relative_path="books/book.epub",
        authorization=authorization,
        run=run,
        expected_modified_at=modified_at,
    ) as session:
        with pytest.raises(LinuxMetadataWriteBackendError) as raised:
            session.read_source_bytes()

    assert raised.value.code is LinuxMetadataWriteBackendErrorCode.SOURCE_STALE


def test_linux_tmpfs_symlink_source_is_stale(
    linux_tmpfs: Path,
) -> None:
    (
        _source,
        _output,
        source_path,
        _stage_path,
        _recovery,
        modified_at,
        capability,
        authorization,
        run,
    ) = _filesystem(linux_tmpfs)
    link = source_path.parent / "linked.epub"
    link.symlink_to(source_path.name)

    with LinuxMetadataWriteBackend().open_session(
        capability=capability,
        source_relative_path="books/linked.epub",
        authorization=authorization,
        run=run,
        expected_modified_at=modified_at,
    ) as session:
        with pytest.raises(LinuxMetadataWriteBackendError) as raised:
            session.read_source_bytes()

    assert raised.value.code is LinuxMetadataWriteBackendErrorCode.SOURCE_STALE


def test_linux_tmpfs_extended_attribute_is_stale(
    linux_tmpfs: Path,
) -> None:
    (
        _source,
        _output,
        source_path,
        _stage_path,
        _recovery,
        modified_at,
        capability,
        authorization,
        run,
    ) = _filesystem(linux_tmpfs)
    try:
        os.setxattr(source_path, b"user.foliotone-test", b"synthetic")
    except (AttributeError, OSError):
        pytest.skip("tmpfs xattrs are unavailable")

    with LinuxMetadataWriteBackend().open_session(
        capability=capability,
        source_relative_path="books/book.epub",
        authorization=authorization,
        run=run,
        expected_modified_at=modified_at,
    ) as session:
        with pytest.raises(LinuxMetadataWriteBackendError) as raised:
            session.read_source_bytes()

    assert raised.value.code is LinuxMetadataWriteBackendErrorCode.SOURCE_STALE
