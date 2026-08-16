"""Authority data and entity-resolution package."""

from foliotone.authority.resolution import (
    DEFAULT_AUTHOR_RESOLUTION_VERSION,
    DEFAULT_TITLE_RESOLUTION_VERSION,
    AuthorityNameProfile,
    TitleProfile,
    disambiguate,
    generate_agent_name_candidates,
    generate_edition_candidates,
    generate_series_candidates,
    generate_work_candidates,
    is_homonym_free_merge,
    normalize_agent_name,
    normalize_identifier,
    normalize_identifier_for_profile,
    canonicalize_title,
)

__all__ = [
    "AuthorityNameProfile",
    "TitleProfile",
    "DEFAULT_AUTHOR_RESOLUTION_VERSION",
    "DEFAULT_TITLE_RESOLUTION_VERSION",
    "canonicalize_title",
    "disambiguate",
    "generate_agent_name_candidates",
    "generate_edition_candidates",
    "generate_series_candidates",
    "generate_work_candidates",
    "is_homonym_free_merge",
    "normalize_agent_name",
    "normalize_identifier",
    "normalize_identifier_for_profile",
]
