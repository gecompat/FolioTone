"""FolioTone-owned normalization and fingerprinting of extracted e-book text."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass

from foliotone.core import EntityId, EntityKind, FileObservation, Fingerprint
from foliotone.tooling import ToolExecution

DEFAULT_MAX_EBOOK_TEXT_BYTES = 64 * 1024 * 1024
TEXT_FINGERPRINT_KIND = "EBOOK_NORMALIZED_TEXT"
TEXT_NORMALIZATION_PROFILE = (
    f"unicode-nfkc-whitespace-v1+ucd-{unicodedata.unidata_version}"
)


class EbookTextError(ValueError):
    """Extracted e-book text cannot satisfy the shared normalization contract."""


@dataclass(frozen=True, slots=True)
class NormalizedEbookText:
    """Bounded normalized text plus its deterministic SHA-256."""

    text: str
    sha256: str

    @property
    def character_count(self) -> int:
        """Return the number of Unicode code points after normalization."""
        return len(self.text)


def normalize_ebook_text(
    data: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_EBOOK_TEXT_BYTES,
) -> NormalizedEbookText:
    """Decode bounded UTF-8, apply NFKC, and collapse Unicode whitespace."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if len(data) > max_bytes:
        raise EbookTextError("e-book text exceeds the configured size limit")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise EbookTextError("e-book text is not valid UTF-8") from error
    normalized = " ".join(unicodedata.normalize("NFKC", text).split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return NormalizedEbookText(text=normalized, sha256=digest)


def build_normalized_text_fingerprint(
    normalized: NormalizedEbookText,
    observation: FileObservation,
    execution: ToolExecution,
) -> Fingerprint | None:
    """Build shared text Evidence against the exact observation and execution."""
    if not normalized.text:
        return None
    if execution.finished_at is None:
        raise EbookTextError("successful text extraction has no completion time")
    return Fingerprint(
        id=EntityId.new(),
        target_kind=EntityKind.FILE_OBSERVATION,
        target_id=observation.id,
        kind=TEXT_FINGERPRINT_KIND,
        algorithm="sha256",
        algorithm_version=TEXT_NORMALIZATION_PROFILE,
        value=normalized.sha256,
        created_at=execution.finished_at,
        tool_execution_id=execution.id,
    )
