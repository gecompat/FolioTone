"""Versioned, non-destructive authority normalization helpers."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from foliotone.core._validation import require_non_empty

NAME_NORMALIZATION_PROFILE = (
    f"unicode-nfkc+diacritic-removal+punct-space+casefold+comma-order-v1+"
    f"ucd-{unicodedata.unidata_version}"
)
IDENTIFIER_NORMALIZATION_PROFILE = (
    f"unicode-nfkc+casefold+whitespace-stripped+punct-collapse-v1+"
    f"ucd-{unicodedata.unidata_version}"
)


@dataclass(frozen=True, slots=True)
class NormalizedName:
    """Raw + normalized name together so normalization never overwrites source text."""

    original: str
    normalized: str
    profile: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "original", require_non_empty(self.original, "original"))
        object.__setattr__(self, "normalized", require_non_empty(self.normalized, "normalized"))
        object.__setattr__(self, "profile", require_non_empty(self.profile, "profile"))

    @property
    def changed(self) -> bool:
        """Whether normalization changed any visible aspect."""
        return self.original != self.normalized


@dataclass(frozen=True, slots=True)
class NormalizedIdentifier:
    """Raw + normalized identifier together so normalization never overwrites source text."""

    original: str
    normalized: str
    profile: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "original", require_non_empty(self.original, "original"))
        object.__setattr__(self, "normalized", require_non_empty(self.normalized, "normalized"))
        object.__setattr__(self, "profile", require_non_empty(self.profile, "profile"))

    @property
    def changed(self) -> bool:
        """Whether normalization changed any visible aspect."""
        return self.original != self.normalized


def normalize_agent_name(name: str, *, profile: str = NAME_NORMALIZATION_PROFILE) -> NormalizedName:
    """
    Return a canonical, non-destructive name form.

    The result preserves the original name and exposes the normalized version for
    comparison, matching and evidence generation.
    """
    return _normalize_name_or_identity(name, profile=profile)


def normalize_identifier(identifier: str, *, profile: str = IDENTIFIER_NORMALIZATION_PROFILE) -> NormalizedIdentifier:
    """
    Return a canonical, non-destructive identifier form.

    The result preserves the original identifier and exposes the normalized value
    for candidate matching and cache keys.
    """
    original = require_non_empty(identifier, "identifier")
    normalized = unicodedata.normalize("NFKC", original).strip().casefold()
    normalized = "".join(char for char in normalized if not unicodedata.category(char).startswith("M"))
    normalized = "".join(_collapse_identifier_char(char) for char in normalized)
    normalized = " ".join(normalized.split())

    if not normalized:
        raise ValueError("normalized identifier must not be empty")

    return NormalizedIdentifier(original=original, normalized=normalized, profile=profile)


def _normalize_name_or_identity(raw_name: str, *, profile: str) -> NormalizedName:
    original = require_non_empty(raw_name, "name")
    normalized = unicodedata.normalize("NFKC", original)
    normalized = _strip_diacritics(normalized)
    normalized = normalized.casefold()
    normalized = _reorder_family_given_name(normalized)
    normalized = "".join(_collapse_name_char(char) for char in normalized)
    normalized = " ".join(normalized.split())

    if not normalized:
        raise ValueError("normalized name must not be empty")

    return NormalizedName(original=original, normalized=normalized, profile=profile)


def _strip_diacritics(value: str) -> str:
    """Drop combining marks after canonical normalization."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(
        char for char in decomposed
        if unicodedata.category(char) != "Mn"
    )


def _collapse_name_char(char: str) -> str:
    category = unicodedata.category(char)
    if category.startswith("P") or category.startswith("S"):
        return " "
    return char


def _collapse_identifier_char(char: str) -> str:
    category = unicodedata.category(char)
    if char.isspace():
        return ""
    if category.startswith("M"):
        return ""
    if char in {"-", "_", "(", ")", "[", "]", "{", "}", "\"", "'", "`"}:
        return ""
    return char


def _reorder_family_given_name(value: str) -> str:
    """
    Convert `Family, Given` forms into `given family` when there is one comma.

    This is intentionally conservative and only handles the common two-part format.
    """
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2:
        return value
    first, second = parts
    if not first or not second:
        return value
    return f"{second} {first}"
