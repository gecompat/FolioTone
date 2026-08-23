"""Pure target-locator policy for the bounded same-parent rename."""

from __future__ import annotations

import unicodedata
from pathlib import PurePosixPath
from typing import Final

from foliotone.ebook_operation_recipes.contracts import (
    MAX_EBOOK_OPERATION_LOCATOR_BYTES,
    MAX_EBOOK_OPERATION_LOCATOR_COMPONENT_BYTES,
)

EBOOK_RENAME_PROCESSOR_PROFILE: Final = (
    "ebook-file-rename-linux-renameat2-noreplace/v1"
)

_SUPPORTED_SUFFIXES: Final = frozenset({"EPUB", "MOBI", "AZW", "AZW3", "PDF"})
_DOS_STEMS: Final = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{value}" for value in range(1, 10)}
    | {f"lpt{value}" for value in range(1, 10)}
)


class EbookRenameTargetError(ValueError):
    """A private locator failed one fixed, path-free policy check."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def build_ebook_rename_target_locator(
    source_locator: str,
    target_basename: str,
) -> tuple[str, str]:
    """Return ``(target locator, format label)`` without normalizing input."""

    if not isinstance(source_locator, str) or not isinstance(target_basename, str):
        raise EbookRenameTargetError("TARGET_BASENAME_INVALID")
    if source_locator != unicodedata.normalize("NFC", source_locator):
        raise EbookRenameTargetError("LOCATOR_NOT_NFC")
    if target_basename != unicodedata.normalize("NFC", target_basename):
        raise EbookRenameTargetError("LOCATOR_NOT_NFC")
    if (
        not source_locator
        or source_locator.startswith("/")
        or source_locator.endswith("/")
        or "\\" in source_locator
        or any(part in {"", ".", ".."} for part in source_locator.split("/"))
    ):
        raise EbookRenameTargetError("SOURCE_LOCATOR_INVALID")
    if (
        not target_basename
        or target_basename in {".", ".."}
        or "/" in target_basename
        or "\\" in target_basename
        or "\x00" in target_basename
        or any(unicodedata.category(character) == "Cc" for character in target_basename)
        or target_basename[0] in {" ", "."}
        or target_basename[-1] in {" ", "."}
        or target_basename.casefold().startswith(".foliotone-")
        or len(target_basename.encode("utf-8"))
        > MAX_EBOOK_OPERATION_LOCATOR_COMPONENT_BYTES
    ):
        raise EbookRenameTargetError("TARGET_BASENAME_INVALID")

    source_basename = PurePosixPath(source_locator).name
    source_stem, source_separator, source_suffix = source_basename.rpartition(".")
    target_stem, target_separator, target_suffix = target_basename.rpartition(".")
    if (
        not source_separator
        or not source_stem
        or source_suffix.upper() not in _SUPPORTED_SUFFIXES
    ):
        raise EbookRenameTargetError("SOURCE_FORMAT_UNSUPPORTED")
    if (
        not target_separator
        or not target_stem
        or target_suffix != source_suffix
    ):
        raise EbookRenameTargetError("TARGET_SUFFIX_MISMATCH")
    if target_basename.split(".", 1)[0].casefold() in _DOS_STEMS:
        raise EbookRenameTargetError("TARGET_BASENAME_INVALID")
    if target_basename == source_basename:
        raise EbookRenameTargetError("TARGET_UNCHANGED")
    if target_basename.casefold() == source_basename.casefold():
        raise EbookRenameTargetError("TARGET_CASE_ONLY")

    parent, separator, _basename = source_locator.rpartition("/")
    target_locator = f"{parent}/{target_basename}" if separator else target_basename
    if (
        target_locator != unicodedata.normalize("NFC", target_locator)
        or len(target_locator.encode("utf-8")) > MAX_EBOOK_OPERATION_LOCATOR_BYTES
    ):
        raise EbookRenameTargetError("TARGET_LOCATOR_TOO_LONG")
    return target_locator, source_suffix.upper()


__all__ = [
    "EBOOK_RENAME_PROCESSOR_PROFILE",
    "EbookRenameTargetError",
    "build_ebook_rename_target_locator",
]
