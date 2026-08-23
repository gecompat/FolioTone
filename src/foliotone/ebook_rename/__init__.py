"""Bounded contracts for the e-book same-parent rename line."""

from foliotone.ebook_rename.dependency_scopes import (
    EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE,
    EBOOK_RENAME_DEPENDENCY_SCOPES_FILE_ENV,
    EbookRenameDependencyScopeAxis,
    EbookRenameDependencyScopeMode,
    EbookRenameDependencyScopeResolver,
    EbookRenameDependencyScopeUnavailable,
    EbookRenameDependencySnapshotKind,
    ResolvedEbookRenameDependencyScope,
)
from foliotone.ebook_rename.target import (
    EBOOK_RENAME_PROCESSOR_PROFILE,
    EbookRenameTargetError,
    build_ebook_rename_target_locator,
)

__all__ = [
    "EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE",
    "EBOOK_RENAME_DEPENDENCY_SCOPES_FILE_ENV",
    "EBOOK_RENAME_PROCESSOR_PROFILE",
    "EbookRenameDependencyScopeAxis",
    "EbookRenameDependencyScopeMode",
    "EbookRenameDependencyScopeResolver",
    "EbookRenameDependencyScopeUnavailable",
    "EbookRenameDependencySnapshotKind",
    "EbookRenameTargetError",
    "ResolvedEbookRenameDependencyScope",
    "build_ebook_rename_target_locator",
]
