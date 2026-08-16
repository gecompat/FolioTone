"""Authority data and entity-resolution package."""

from foliotone.authority.normalization import (
    IDENTIFIER_NORMALIZATION_PROFILE,
    NAME_NORMALIZATION_PROFILE,
    NormalizedIdentifier,
    NormalizedName,
    normalize_agent_name as _normalize_agent_name,
    normalize_identifier as _normalize_identifier,
)

from foliotone.authority.resolution import (
    DEFAULT_AUTHOR_RESOLUTION_VERSION,
    DEFAULT_AGENT_NAME_CONFIDENCE,
    DEFAULT_IDENTIFIER_CONFIDENCE,
    DEFAULT_IDENTIFIER_RESOLUTION_VERSION,
    DEFAULT_METADATA_RESOLUTION_VERSION,
    DEFAULT_TITLE_RESOLUTION_VERSION,
    DEFAULT_TITLE_CONFIDENCE,
    AuthorityNameProfile,
    BibliographicEntityProfile,
    TitleProfile,
    canonicalize_title,
    disambiguate,
    generate_agent_name_candidates,
    generate_bibliographic_entity_candidates,
    generate_edition_candidates,
    generate_metadata_entity_candidates,
    generate_series_candidates,
    generate_work_candidates,
    is_homonym_free_merge,
    normalize_agent_name_key,
    normalize_identifier_for_profile,
    normalize_identifier_key,
)


def normalize_agent_name(name: str) -> NormalizedName:
    """Return the versioned normalized agent name record."""

    return _normalize_agent_name(name)


def normalize_agent_name_text(name: str) -> str:
    """Return only the normalized agent-name text used by local matching."""

    return normalize_agent_name(name).normalized


def normalize_identifier(identifier: str) -> NormalizedIdentifier:
    """Return the versioned normalized identifier record."""

    return _normalize_identifier(identifier)


def normalize_identifier_text(identifier: str) -> str:
    """Return only the normalized identifier value used by local matching."""

    return normalize_identifier(identifier).normalized


__all__ = [
    "AuthorityNameProfile",
    "BibliographicEntityProfile",
    "DEFAULT_AUTHOR_RESOLUTION_VERSION",
    "DEFAULT_AGENT_NAME_CONFIDENCE",
    "DEFAULT_IDENTIFIER_CONFIDENCE",
    "DEFAULT_IDENTIFIER_RESOLUTION_VERSION",
    "DEFAULT_METADATA_RESOLUTION_VERSION",
    "DEFAULT_TITLE_CONFIDENCE",
    "DEFAULT_TITLE_RESOLUTION_VERSION",
    "IDENTIFIER_NORMALIZATION_PROFILE",
    "NAME_NORMALIZATION_PROFILE",
    "NormalizedIdentifier",
    "NormalizedName",
    "TitleProfile",
    "canonicalize_title",
    "disambiguate",
    "generate_agent_name_candidates",
    "generate_bibliographic_entity_candidates",
    "generate_edition_candidates",
    "generate_metadata_entity_candidates",
    "generate_series_candidates",
    "generate_work_candidates",
    "is_homonym_free_merge",
    "normalize_agent_name",
    "normalize_agent_name_key",
    "normalize_agent_name_text",
    "normalize_identifier",
    "normalize_identifier_for_profile",
    "normalize_identifier_key",
    "normalize_identifier_text",
]
