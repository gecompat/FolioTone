"""Standalone calibre-runtime helper for embedded-cover extraction.

This module is executed by ``calibre-debug -e`` and intentionally has no
FolioTone imports. It stages the observed source inside the private working
directory before calibre sees it, so format readers cannot mutate source media.
"""

from __future__ import annotations

import hashlib
import json
import sys
from contextlib import nullcontext
from pathlib import Path

CHUNK_BYTES = 1024 * 1024
SUPPORTED_SUFFIXES = frozenset({".azw", ".azw3", ".epub", ".mobi"})


def _workspace_path(workspace: Path, value: str) -> Path:
    candidate = (workspace / value).resolve()
    if Path(value).is_absolute() or not candidate.is_relative_to(workspace):
        raise ValueError("output path escapes the private workspace")
    return candidate


def _stage_source(source: Path, target: Path, expected_bytes: int) -> str:
    if source.is_symlink() or not source.is_file():
        raise ValueError("source is not a regular file")
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    copied = 0
    with source.open("rb") as source_stream, target.open("xb") as target_stream:
        while chunk := source_stream.read(CHUNK_BYTES):
            copied += len(chunk)
            if copied > expected_bytes:
                raise ValueError("source changed while being staged")
            digest.update(chunk)
            target_stream.write(chunk)
    if copied != expected_bytes:
        raise ValueError("source changed while being staged")
    return digest.hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) != 6:
        print("cover extraction received invalid arguments", file=sys.stderr)
        return 2

    source = Path(argv[1])
    cover_name, result_name = argv[2], argv[3]
    try:
        expected_bytes = int(argv[4])
        max_cover_bytes = int(argv[5])
        if expected_bytes < 0 or max_cover_bytes <= 0:
            raise ValueError("invalid size limit")
        suffix = source.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError("unsupported e-book format")

        workspace = Path.cwd().resolve()
        cover_path = _workspace_path(workspace, cover_name)
        result_path = _workspace_path(workspace, result_name)
        staged_path = workspace / "input" / f"source{suffix}"
        source_sha256 = _stage_source(source, staged_path, expected_bytes)

        from calibre.ebooks.metadata.epub import (  # type: ignore[import-not-found]
            epub_metadata_settings,
        )
        from calibre.ebooks.metadata.meta import get_metadata  # type: ignore[import-not-found]

        metadata_scope = (
            epub_metadata_settings(allow_rendered_cover=False)
            if suffix == ".epub"
            else nullcontext()
        )
        with staged_path.open("rb") as stream, metadata_scope:
            metadata = get_metadata(
                stream,
                suffix[1:],
                force_read_metadata=True,
            )

        cover_data = getattr(metadata, "cover_data", None)
        data = cover_data[1] if cover_data and len(cover_data) > 1 else None
        status = "NO_EMBEDDED_COVER"
        cover_bytes = 0
        if data:
            if not isinstance(data, bytes):
                data = bytes(data)
            cover_bytes = len(data)
            if cover_bytes > max_cover_bytes:
                raise ValueError("cover exceeds the configured size limit")
            cover_path.write_bytes(data)
            status = "COVER_EXTRACTED"

        result_path.write_text(
            json.dumps(
                {
                    "cover_bytes": cover_bytes,
                    "source_sha256": source_sha256,
                    "status": status,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    except Exception as error:
        print(
            f"cover extraction failed ({type(error).__name__})",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
