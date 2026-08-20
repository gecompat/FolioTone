"""Synthetic ADR-0038 tests for pure archive safety validation."""

import pytest

from foliotone.archive import (
    ARCHIVE_SAFETY_POLICY_PROFILE,
    MAX_COMPRESSION_RATIO,
    MAX_CONCURRENT_ARCHIVE_JOBS,
    MAX_CONCURRENT_JOBS_PER_ARCHIVE,
    MAX_EXTRACTION_SECONDS,
    MAX_INTEGRITY_SECONDS,
    MAX_LISTING_SECONDS,
    MAX_MEMBER_COUNT,
    MAX_SINGLE_MEMBER_BYTES,
    MAX_STDERR_BYTES,
    MAX_STDOUT_BYTES,
    MAX_TOOL_MEMORY_BYTES,
    MAX_TOOL_PROCESSES,
    MAX_TOTAL_UNCOMPRESSED_BYTES,
    MAX_VOLUME_COUNT,
    MAX_WORKSPACE_BYTES,
    MIN_WORKSPACE_FREE_RESERVE_BYTES,
    ArchiveMemberDescriptor,
    ArchiveMemberKind,
    ArchiveSafetyStatus,
    ArchiveSafetyViolation,
    validate_archive_safety,
)


def _member(locator: str = "safe/book.txt", **changes: object) -> ArchiveMemberDescriptor:
    values: dict[str, object] = {
        "locator": locator,
        "declared_compressed_bytes": 1,
        "declared_uncompressed_bytes": 1,
    }
    values.update(changes)
    return ArchiveMemberDescriptor(**values)  # type: ignore[arg-type]


def test_exact_budget_edges_are_accepted() -> None:
    result = validate_archive_safety(
        [
            _member(
                declared_compressed_bytes=(MAX_SINGLE_MEMBER_BYTES + MAX_COMPRESSION_RATIO - 1)
                // MAX_COMPRESSION_RATIO,
                declared_uncompressed_bytes=MAX_SINGLE_MEMBER_BYTES,
            )
        ],
        volume_count=MAX_VOLUME_COUNT,
        workspace_capacity_bytes=MAX_WORKSPACE_BYTES,
        workspace_free_bytes=MAX_SINGLE_MEMBER_BYTES + MIN_WORKSPACE_FREE_RESERVE_BYTES,
    )
    assert result.profile == ARCHIVE_SAFETY_POLICY_PROFILE
    assert result.status is ArchiveSafetyStatus.ACCEPTED


def test_exact_member_and_total_edges_are_accepted() -> None:
    member_bound = validate_archive_safety(
        _member(f"{index}.txt") for index in range(MAX_MEMBER_COUNT)
    )
    assert member_bound.status is ArchiveSafetyStatus.ACCEPTED

    compressed = (MAX_SINGLE_MEMBER_BYTES + MAX_COMPRESSION_RATIO - 1) // MAX_COMPRESSION_RATIO
    total_bound = validate_archive_safety(
        [
            _member(
                f"{index}.bin",
                declared_compressed_bytes=compressed,
                declared_uncompressed_bytes=MAX_SINGLE_MEMBER_BYTES,
            )
            for index in range(4)
        ]
    )
    assert total_bound.status is ArchiveSafetyStatus.ACCEPTED


def test_fixed_execution_budget_constants_match_adr_0038() -> None:
    assert (
        MAX_LISTING_SECONDS,
        MAX_INTEGRITY_SECONDS,
        MAX_EXTRACTION_SECONDS,
    ) == (60, 300, 600)
    assert (MAX_STDOUT_BYTES, MAX_STDERR_BYTES) == (8_388_608, 1_048_576)
    assert MAX_TOOL_MEMORY_BYTES == 1_073_741_824
    assert (MAX_TOOL_PROCESSES, MAX_CONCURRENT_ARCHIVE_JOBS) == (1, 2)
    assert MAX_CONCURRENT_JOBS_PER_ARCHIVE == 1


@pytest.mark.parametrize(
    ("members", "kwargs", "violation"),
    [
        ([_member()] * (MAX_MEMBER_COUNT + 1), {}, ArchiveSafetyViolation.MEMBER_COUNT_LIMIT),
        (
            [_member()],
            {"volume_count": MAX_VOLUME_COUNT + 1},
            ArchiveSafetyViolation.VOLUME_COUNT_LIMIT,
        ),
        ([_member()], {"volume_count": 0}, ArchiveSafetyViolation.VOLUME_COUNT_LIMIT),
        (
            [_member(declared_uncompressed_bytes=MAX_SINGLE_MEMBER_BYTES + 1)],
            {},
            ArchiveSafetyViolation.MEMBER_SIZE_LIMIT,
        ),
        (
            [
                _member(
                    declared_compressed_bytes=1,
                    declared_uncompressed_bytes=MAX_COMPRESSION_RATIO + 1,
                )
            ],
            {},
            ArchiveSafetyViolation.COMPRESSION_RATIO_LIMIT,
        ),
        ([_member(declared_compressed_bytes=None)], {}, ArchiveSafetyViolation.UNKNOWN_SIZE),
        ([_member(declared_uncompressed_bytes=-1)], {}, ArchiveSafetyViolation.NEGATIVE_SIZE),
        (
            [_member()],
            {"workspace_capacity_bytes": MAX_WORKSPACE_BYTES + 1},
            ArchiveSafetyViolation.WORKSPACE_LIMIT,
        ),
        (
            [_member()],
            {"workspace_free_bytes": MIN_WORKSPACE_FREE_RESERVE_BYTES},
            ArchiveSafetyViolation.WORKSPACE_RESERVE,
        ),
        (
            [_member()],
            {"source_overlaps_workspace": True},
            ArchiveSafetyViolation.WORKSPACE_OVERLAP,
        ),
    ],
)
def test_budget_boundaries_fail_closed(
    members: list[ArchiveMemberDescriptor],
    kwargs: dict[str, object],
    violation: ArchiveSafetyViolation,
) -> None:
    result = validate_archive_safety(members, **kwargs)  # type: ignore[arg-type]
    assert result.status is not ArchiveSafetyStatus.ACCEPTED
    assert result.violations == (violation,)


@pytest.mark.parametrize(
    "locator",
    [
        "",
        "/absolute",
        r"\absolute",
        r"\\server\share",
        r"\\?\C:\x",
        "C:drive-relative",
        "../escape",
        "a/./b",
        "a//b",
        "a\\b",
        "stream:ads",
        "NUL",
        "COM1.txt",
        "CONOUT$.txt",
        "a. ",
        "a\x00b",
        "a\n",
        "x" * 1_025,
        "a/" * 128 + "b",
    ],
)
def test_adversarial_posix_and_windows_paths_are_rejected(locator: str) -> None:
    result = validate_archive_safety([_member(locator)])
    assert result.violations == (ArchiveSafetyViolation.PATH_INVALID,)


@pytest.mark.parametrize(
    "kind",
    [
        ArchiveMemberKind.SYMLINK,
        ArchiveMemberKind.HARDLINK,
        ArchiveMemberKind.REPARSE_POINT,
        ArchiveMemberKind.FIFO,
        ArchiveMemberKind.SOCKET,
        ArchiveMemberKind.BLOCK_DEVICE,
        ArchiveMemberKind.CHARACTER_DEVICE,
        ArchiveMemberKind.UNKNOWN,
    ],
)
def test_non_regular_member_types_are_rejected(kind: ArchiveMemberKind) -> None:
    assert validate_archive_safety([_member(kind=kind)]).violations == (
        ArchiveSafetyViolation.MEMBER_KIND_REJECTED,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"nested_archive": True},
        {"sparse": True},
        {"alternate_stream": True},
        {"has_acl": True},
        {"has_xattrs": True},
        {"has_owner": True},
        {"has_group": True},
        {"has_setuid": True},
        {"has_setgid": True},
        {"has_special_flags": True},
    ],
)
def test_nested_and_unsafe_metadata_are_rejected(changes: dict[str, bool]) -> None:
    result = validate_archive_safety([_member(**changes)])
    expected = (
        ArchiveSafetyViolation.NESTED_ARCHIVE_REJECTED
        if "nested_archive" in changes
        else ArchiveSafetyViolation.METADATA_REJECTED
    )
    assert result.violations == (expected,)


def test_non_boolean_member_flags_are_invalid_input() -> None:
    result = validate_archive_safety([_member(sparse=1)])
    assert result.violations == (ArchiveSafetyViolation.INVALID_INPUT,)


def test_normalized_collisions_and_file_directory_conflicts_are_rejected() -> None:
    assert validate_archive_safety([_member("A.txt"), _member("a.TXT")]).violations == (
        ArchiveSafetyViolation.PATH_COLLISION,
    )
    assert validate_archive_safety([_member("e\u0301.txt"), _member("é.txt")]).violations == (
        ArchiveSafetyViolation.PATH_COLLISION,
    )
    assert validate_archive_safety([_member("a"), _member("a/child")]).violations == (
        ArchiveSafetyViolation.PARENT_CHILD_CONFLICT,
    )


def test_total_bound_and_member_locator_are_redacted() -> None:
    members = [
        _member(
            f"{index}.bin",
            declared_compressed_bytes=(MAX_SINGLE_MEMBER_BYTES + MAX_COMPRESSION_RATIO - 1)
            // MAX_COMPRESSION_RATIO,
            declared_uncompressed_bytes=MAX_SINGLE_MEMBER_BYTES,
        )
        for index in range(5)
    ]
    result = validate_archive_safety(members)
    assert result.violations == (ArchiveSafetyViolation.TOTAL_UNCOMPRESSED_LIMIT,)
    assert "safe/book.txt" not in repr(_member())
    assert MAX_TOTAL_UNCOMPRESSED_BYTES == 8_589_934_592
