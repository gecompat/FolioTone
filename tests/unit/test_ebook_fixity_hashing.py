from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from foliotone.core import EntityId
from foliotone.fixity import (
    EbookFixityBaselineSourceEntry,
    EbookFixityHashError,
    EbookFixityHashErrorCode,
    EbookFixityRootReader,
)


def _secure_open_supported() -> bool:
    return (
        int(getattr(os, "O_NOFOLLOW", 0)) != 0
        and int(getattr(os, "O_DIRECTORY", 0)) != 0
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
    )


def _source(path: Path, root: Path) -> EbookFixityBaselineSourceEntry:
    details = path.stat()
    return EbookFixityBaselineSourceEntry(
        file_id=EntityId.new(),
        observation_id=EntityId.new(),
        relative_locator=path.relative_to(root).as_posix(),
        expected_size_bytes=details.st_size,
        expected_modified_at=datetime.fromtimestamp(details.st_mtime, tz=UTC),
    )


def test_secure_reader_fails_closed_when_descriptor_relative_open_is_unsupported(
    tmp_path: Path,
) -> None:
    if _secure_open_supported():
        pytest.skip("host supports the primary Linux secure-open contract")

    with pytest.raises(EbookFixityHashError) as caught:
        with EbookFixityRootReader(tmp_path.resolve()):
            pass

    assert caught.value.code is EbookFixityHashErrorCode.SECURE_OPEN_UNAVAILABLE


@pytest.mark.skipif(not _secure_open_supported(), reason="requires Linux dir_fd no-follow")
def test_secure_reader_streams_in_bounded_chunks(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    path = root / "nested" / "book.epub"
    path.parent.mkdir()
    path.write_bytes(b"abcdefghijk")
    observed: list[int] = []

    with EbookFixityRootReader(root) as reader:
        digest = reader.hash(_source(path, root), chunk_bytes=4, on_bytes_read=observed.append)

    assert digest == "ca2f2069ea0c6e4658222e06f8dd639659cbb5e67cbbba6734bc334a3799bc68"
    assert observed == [4, 4, 3]


@pytest.mark.skipif(not _secure_open_supported(), reason="requires Linux dir_fd no-follow")
def test_secure_reader_rejects_parent_symlink(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    real = root / "real"
    real.mkdir()
    path = real / "book.epub"
    path.write_bytes(b"book")
    link = root / "linked"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    source = EbookFixityBaselineSourceEntry(
        file_id=EntityId.new(),
        observation_id=EntityId.new(),
        relative_locator="linked/book.epub",
        expected_size_bytes=4,
        expected_modified_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
    )

    with EbookFixityRootReader(root) as reader, pytest.raises(EbookFixityHashError) as caught:
        reader.hash(source)

    assert caught.value.code is EbookFixityHashErrorCode.UNSAFE_LOCATOR


@pytest.mark.skipif(not _secure_open_supported(), reason="requires Linux dir_fd no-follow")
def test_secure_reader_distinguishes_missing_source_drift(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    path = root / "book.epub"
    path.write_bytes(b"book")
    source = _source(path, root)
    path.unlink()

    with EbookFixityRootReader(root) as reader, pytest.raises(EbookFixityHashError) as caught:
        reader.hash(source)

    assert caught.value.code is EbookFixityHashErrorCode.SOURCE_CHANGED


@pytest.mark.skipif(not _secure_open_supported(), reason="requires Linux dir_fd no-follow")
def test_secure_reader_distinguishes_unreadable_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path.resolve()
    path = root / "book.epub"
    path.write_bytes(b"book")
    source = _source(path, root)

    def unreadable(_descriptor: int, _size: int) -> bytes:
        raise PermissionError

    monkeypatch.setattr(os, "read", unreadable)
    with EbookFixityRootReader(root) as reader, pytest.raises(EbookFixityHashError) as caught:
        reader.hash(source)

    assert caught.value.code is EbookFixityHashErrorCode.SOURCE_UNREADABLE


@pytest.mark.skipif(not _secure_open_supported(), reason="requires Linux dir_fd no-follow")
def test_secure_reader_rejects_unresolved_final_locator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path.resolve()
    path = root / "book.epub"
    path.write_bytes(b"book")
    source = _source(path, root)
    real_stat = os.stat

    def unresolved(path: object, *args: object, **kwargs: object) -> os.stat_result:
        if path == "book.epub" and kwargs.get("dir_fd") is not None:
            raise PermissionError
        return real_stat(path, *args, **kwargs)

    with EbookFixityRootReader(root) as reader:
        monkeypatch.setattr(os, "stat", unresolved)
        with pytest.raises(EbookFixityHashError) as caught:
            reader.hash(source)

    assert caught.value.code is EbookFixityHashErrorCode.UNSAFE_LOCATOR


@pytest.mark.skipif(not _secure_open_supported(), reason="requires Linux dir_fd no-follow")
def test_secure_reader_ignores_new_file_outside_bound_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path.resolve()
    path = root / "book.epub"
    path.write_bytes(b"abcdefgh")
    source = _source(path, root)
    real_read = os.read
    created = False

    def creating_read(descriptor: int, size: int) -> bytes:
        nonlocal created
        block = real_read(descriptor, size)
        if block and not created:
            created = True
            (root / "after-scan.epub").write_bytes(b"later")
        return block

    monkeypatch.setattr(os, "read", creating_read)
    with EbookFixityRootReader(root) as reader:
        digest = reader.hash(source, chunk_bytes=4)

    assert digest == "9c56cc51b374c3ba189210d5b6d4bf57790d351c96c47c02190ecf1e430635ab"


@pytest.mark.skipif(not _secure_open_supported(), reason="requires Linux dir_fd no-follow")
def test_secure_reader_rejects_root_path_replacement(tmp_path: Path) -> None:
    root = tmp_path / "ebooks"
    root.mkdir()
    path = root / "book.epub"
    path.write_bytes(b"book")

    with EbookFixityRootReader(root) as reader:
        root.rename(tmp_path / "old-ebooks")
        root.mkdir()
        with pytest.raises(EbookFixityHashError) as caught:
            reader.check_root()

    assert caught.value.code is EbookFixityHashErrorCode.ROOT_UNAVAILABLE


@pytest.mark.skipif(not _secure_open_supported(), reason="requires Linux dir_fd no-follow")
def test_secure_reader_detects_change_during_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path.resolve()
    path = root / "book.epub"
    path.write_bytes(b"abcdefgh")
    source = _source(path, root)
    real_read = os.read
    changed = False

    def changing_read(descriptor: int, size: int) -> bytes:
        nonlocal changed
        block = real_read(descriptor, size)
        if block and not changed:
            changed = True
            path.write_bytes(b"abcdWXYZ")
        return block

    monkeypatch.setattr(os, "read", changing_read)
    with EbookFixityRootReader(root) as reader, pytest.raises(EbookFixityHashError) as caught:
        reader.hash(source, chunk_bytes=4)

    assert caught.value.code is EbookFixityHashErrorCode.SOURCE_CHANGED


@pytest.mark.skipif(not _secure_open_supported(), reason="requires Linux dir_fd no-follow")
def test_secure_reader_detects_intermediate_directory_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path.resolve()
    nested = root / "outer" / "nested"
    nested.mkdir(parents=True)
    path = nested / "book.epub"
    path.write_bytes(b"abcdefgh")
    source = _source(path, root)
    source_times = (path.stat().st_atime, path.stat().st_mtime)
    real_read = os.read
    changed = False

    def moving_read(descriptor: int, size: int) -> bytes:
        nonlocal changed
        block = real_read(descriptor, size)
        if block and not changed:
            changed = True
            nested.rename(root / "outer" / "moved")
            nested.mkdir()
            replacement = nested / "book.epub"
            replacement.write_bytes(b"abcdefgh")
            os.utime(replacement, source_times)
        return block

    monkeypatch.setattr(os, "read", moving_read)
    with EbookFixityRootReader(root) as reader, pytest.raises(EbookFixityHashError) as caught:
        reader.hash(source, chunk_bytes=4)

    assert caught.value.code is EbookFixityHashErrorCode.SOURCE_CHANGED
