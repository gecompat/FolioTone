"""Synthetic tests for the pure archive-sidecar classifier."""

from foliotone.archive import (
    ARCHIVE_SIDECAR_PROFILE,
    ArchiveListingStatus,
    ArchiveSidecarKind,
    classify_archive_sidecars,
)


def test_all_allowlisted_extensions_and_extensionless_basenames() -> None:
    result = classify_archive_sidecars(
        [
            "release.NFO",
            "notes.txt",
            "file.diz",
            "details.INFO",
            "links.URL",
            "page.HTML",
            "page.htm",
            "checksums.SFV",
            "README",
            "read.me",
            "PASSWORD",
            "passwort",
            "PASS",
            "pw",
            "book.zip",
        ]
    )

    assert result.profile == ARCHIVE_SIDECAR_PROFILE
    assert result.status is ArchiveListingStatus.LISTED
    assert [(item.basename, item.kind) for item in result.sidecars] == [
        ("checksums.SFV", ArchiveSidecarKind.SFV),
        ("details.INFO", ArchiveSidecarKind.INFO),
        ("file.diz", ArchiveSidecarKind.DIZ),
        ("links.URL", ArchiveSidecarKind.URL),
        ("notes.txt", ArchiveSidecarKind.TEXT),
        ("page.htm", ArchiveSidecarKind.HTML),
        ("page.HTML", ArchiveSidecarKind.HTML),
        ("PASS", ArchiveSidecarKind.PASSWORD),
        ("PASSWORD", ArchiveSidecarKind.PASSWORD),
        ("passwort", ArchiveSidecarKind.PASSWORD),
        ("pw", ArchiveSidecarKind.PASSWORD),
        ("read.me", ArchiveSidecarKind.README),
        ("README", ArchiveSidecarKind.README),
        ("release.NFO", ArchiveSidecarKind.NFO),
    ]


def test_limit_is_bounded_and_does_not_classify_partial_input() -> None:
    result = classify_archive_sidecars([f"{index}.txt" for index in range(33)])
    assert result.status is ArchiveListingStatus.LIMIT_EXCEEDED
    assert result.sidecars == ()


def test_nested_names_and_non_sidecars_are_ignored_without_io_or_execution() -> None:
    result = classify_archive_sidecars(
        ["nested/secret.txt", r"nested\README", "payload.py", "run.exe", "archive.zip"]
    )
    assert result.status is ArchiveListingStatus.LISTED
    assert result.sidecars == ()


def test_private_basename_is_redacted_from_repr() -> None:
    result = classify_archive_sidecars(["private-release.nfo"])
    assert "private-release" not in repr(result)
