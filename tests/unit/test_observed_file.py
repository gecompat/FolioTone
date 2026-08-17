from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from foliotone.analyzers.ebook.observations import (
    _windows_extended_path_text,
    resolve_observed_file,
)
from foliotone.core import EntityId, FileObservation


def test_windows_extended_path_text_handles_drive_unc_and_existing_prefix() -> None:
    assert _windows_extended_path_text(r"C:\collection\book.epub") == (
        r"\\?\C:\collection\book.epub"
    )
    assert _windows_extended_path_text(r"\\server\share\book.epub") == (
        r"\\?\UNC\server\share\book.epub"
    )
    assert _windows_extended_path_text(r"\\?\C:\collection\book.epub") == (
        r"\\?\C:\collection\book.epub"
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length path behavior")
def test_resolve_observed_file_reads_a_windows_path_beyond_max_path(tmp_path: Path) -> None:
    root = tmp_path.resolve(strict=True)
    extended_root = Path(_windows_extended_path_text(str(root)))
    relative = Path(*(f"segment-{index}-" + "x" * 48 for index in range(5))) / "book.epub"
    source = extended_root / relative
    assert len(str(root / relative)) >= 260
    try:
        source.parent.mkdir(parents=True)
        source.write_bytes(b"long-path-ebook")
        source_stat = source.stat()
        modified_at = datetime.fromtimestamp(source_stat.st_mtime, tz=UTC)
        observation = FileObservation(
            id=EntityId.new(),
            file_id=EntityId.new(),
            scan_run_id=EntityId.new(),
            relative_path=relative.as_posix(),
            size_bytes=source_stat.st_size,
            modified_at=modified_at,
            observed_at=modified_at,
        )

        resolved = resolve_observed_file(root, observation)

        assert str(resolved).startswith("\\\\?\\")
        assert resolved.read_bytes() == b"long-path-ebook"
    finally:
        shutil.rmtree(extended_root, ignore_errors=True)
