"""Synthetic integration tests for the non-executing archive workflow."""

import ast
import inspect
from dataclasses import replace
from pathlib import Path

import pytest

from foliotone.archive import (
    ARCHIVE_EXTRACTION_PROFILE,
    ARCHIVE_LISTING_PROFILE,
    ARCHIVE_MEMBER_PROFILE,
    ARCHIVE_MEMBER_REUSE_PROFILE,
    ARCHIVE_SAFETY_POLICY_PROFILE,
    ArchiveEncryptionStatus,
    ArchiveExtractionExecution,
    ArchiveExtractionStatus,
    ArchiveIntegrityExecution,
    ArchiveIntegrityStatus,
    ArchiveListingExecution,
    ArchiveListingResult,
    ArchiveListingStatus,
    ArchiveMemberCrcStatus,
    ArchiveMemberKind,
    ArchiveMemberObservation,
    ArchivePasswordAttemptStatus,
    ArchiveReuseKey,
    ArchiveSafetyStatus,
    FakeArchiveListingProvider,
    FakeArchiveListingReuseStore,
    build_archive_member_identity,
)
from foliotone.core import FileRecord

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _key() -> ArchiveReuseKey:
    return ArchiveReuseKey(
        archive_full_sha256=SHA_A,
        volume_group_fingerprint=SHA_B,
        tool_provider_id="fake-archive",
        tool_version="1",
        adapter_version="fake-adapter-1",
        parser_version="fake-parser-1",
        listing_profile=ARCHIVE_LISTING_PROFILE,
        extraction_profile=ARCHIVE_EXTRACTION_PROFILE,
        safety_profile=ARCHIVE_SAFETY_POLICY_PROFILE,
    )


def _member(**changes: object) -> ArchiveMemberObservation:
    values: dict[str, object] = {
        "profile": ARCHIVE_MEMBER_PROFILE,
        "archive_observation_id": "observation-1",
        "volume_group_fingerprint": SHA_B,
        "member_ordinal": 0,
        "member_path_safe": "private/book.epub",
        "declared_compressed_bytes": 10,
        "declared_uncompressed_bytes": 20,
        "crc_status": ArchiveMemberCrcStatus.NOT_TESTED,
        "encryption_status": ArchiveEncryptionStatus.NONE,
        "listing_execution_id": "execution-1",
    }
    values.update(changes)
    values.setdefault(
        "member_identity",
        build_archive_member_identity(
            archive_full_sha256=SHA_A,
            volume_group_fingerprint=values["volume_group_fingerprint"],  # type: ignore[arg-type]
            member_path_safe=values["member_path_safe"],  # type: ignore[arg-type]
            member_ordinal=values["member_ordinal"],  # type: ignore[arg-type]
        ),
    )
    return ArchiveMemberObservation(**values)  # type: ignore[arg-type]


def _listed(*members: ArchiveMemberObservation) -> ArchiveListingResult:
    return ArchiveListingResult(
        listing_execution=ArchiveListingExecution(
            ArchiveListingStatus.LISTED, "execution-1"
        ),
        encryption_status=ArchiveEncryptionStatus.NONE,
        reuse_key=_key(),
        members=members,
    )


def test_fake_provider_is_non_executing_and_member_is_not_file_record() -> None:
    member = _member()
    result = _listed(member)
    provider = FakeArchiveListingProvider(result)

    assert provider.list() is result
    assert not isinstance(member, FileRecord)
    assert "private/book.epub" not in repr(member)
    assert tuple(inspect.signature(provider.list).parameters) == ()
    with pytest.raises(TypeError):
        provider.list(secret="sentinel")  # type: ignore[call-arg]


def test_secure_channel_and_encrypted_header_contracts_fail_closed() -> None:
    data_encrypted = replace(_member(), encryption_status=ArchiveEncryptionStatus.DATA_ENCRYPTED)
    listed = ArchiveListingResult(
        ArchiveListingExecution(ArchiveListingStatus.LISTED, "execution-1"),
        ArchiveEncryptionStatus.DATA_ENCRYPTED,
        _key(),
        password_attempt_status=ArchivePasswordAttemptStatus.SECURE_CHANNEL_UNAVAILABLE,
        extraction_policy_status=ArchiveSafetyStatus.POLICY_REJECTED,
        members=(data_encrypted,),
    )
    assert listed.members == (data_encrypted,)
    assert listed.password_attempt_status is ArchivePasswordAttemptStatus.SECURE_CHANNEL_UNAVAILABLE

    headers = ArchiveListingResult(
        ArchiveListingExecution(ArchiveListingStatus.PASSWORD_REQUIRED, "execution-2"),
        ArchiveEncryptionStatus.HEADERS_ENCRYPTED,
        _key(),
        password_attempt_status=ArchivePasswordAttemptStatus.SECURE_CHANNEL_UNAVAILABLE,
        extraction_policy_status=ArchiveSafetyStatus.POLICY_REJECTED,
    )
    assert headers.members == ()
    with pytest.raises(ValueError, match="encrypted headers"):
        replace(
            headers,
            listing_execution=ArchiveListingExecution(
                ArchiveListingStatus.LISTED, "execution-3"
            ),
        )
    with pytest.raises(ValueError, match="secure"):
        replace(listed, password_attempt_status=ArchivePasswordAttemptStatus.ACCEPTED)


def test_unknown_declared_size_is_preserved_but_blocks_extraction() -> None:
    unknown = _member(declared_compressed_bytes=None)
    with pytest.raises(ValueError, match="blocked"):
        _listed(unknown)
    blocked = ArchiveListingResult(
        ArchiveListingExecution(ArchiveListingStatus.LISTED, "execution-1"),
        ArchiveEncryptionStatus.NONE,
        _key(),
        extraction_policy_status=ArchiveSafetyStatus.POLICY_REJECTED,
        members=(unknown,),
    )
    assert blocked.members[0].declared_compressed_bytes is None


def test_extraction_fields_are_jointly_nullable_and_hash_bounded() -> None:
    with pytest.raises(ValueError, match="jointly nullable"):
        replace(_member(), extraction_execution_id="extract-1")

    extracted = replace(
        _member(),
        extraction_execution_id="extract-1",
        observed_uncompressed_bytes=20,
        member_sha256=SHA_D,
        crc_status=ArchiveMemberCrcStatus.MATCHED,
    )
    assert extracted.member_sha256 == SHA_D
    with pytest.raises(ValueError, match="SHA-256"):
        replace(extracted, member_sha256="not-a-hash")

    with pytest.raises(ValueError, match="failed extraction"):
        _listed(extracted)
    successful = ArchiveListingResult(
        ArchiveListingExecution(ArchiveListingStatus.LISTED, "execution-1"),
        ArchiveEncryptionStatus.NONE,
        _key(),
        integrity_execution=ArchiveIntegrityExecution(
            ArchiveIntegrityStatus.PASSED, "integrity-1"
        ),
        extraction_execution=ArchiveExtractionExecution(
            ArchiveExtractionStatus.EXTRACTED, "extract-1"
        ),
        members=(extracted,),
    )
    assert successful.members == (extracted,)
    assert successful.execution_id == "execution-1"
    assert successful.listing_status is ArchiveListingStatus.LISTED
    assert successful.integrity_status is ArchiveIntegrityStatus.PASSED

    second = _member(
        member_ordinal=1,
        member_path_safe="private/second.epub",
    )
    with pytest.raises(ValueError, match="partial extraction"):
        ArchiveListingResult(
            ArchiveListingExecution(ArchiveListingStatus.LISTED, "execution-1"),
            ArchiveEncryptionStatus.NONE,
            _key(),
            integrity_execution=ArchiveIntegrityExecution(
                ArchiveIntegrityStatus.PASSED, "integrity-1"
            ),
            extraction_execution=ArchiveExtractionExecution(
                ArchiveExtractionStatus.EXTRACTED, "extract-1"
            ),
            members=(extracted, second),
        )


def test_member_lineage_and_canonical_ordinals_are_required() -> None:
    with pytest.raises(ValueError, match="contiguous"):
        _listed(replace(_member(), member_ordinal=1))
    with pytest.raises(ValueError, match="listing execution"):
        _listed(replace(_member(), listing_execution_id="foreign"))
    with pytest.raises(ValueError, match="reuse lineage"):
        _listed(replace(_member(), volume_group_fingerprint=SHA_D))
    with pytest.raises(ValueError, match="safety"):
        replace(_member(), member_path_safe="../private")


@pytest.mark.parametrize(
    ("snapshot_type", "idle_status", "active_status"),
    [
        (
            ArchiveListingExecution,
            ArchiveListingStatus.NOT_ATTEMPTED,
            ArchiveListingStatus.LISTED,
        ),
        (
            ArchiveIntegrityExecution,
            ArchiveIntegrityStatus.NOT_TESTED,
            ArchiveIntegrityStatus.PASSED,
        ),
        (
            ArchiveExtractionExecution,
            ArchiveExtractionStatus.NOT_ATTEMPTED,
            ArchiveExtractionStatus.EXTRACTED,
        ),
    ],
)
def test_execution_snapshots_are_exact_status_id_sum_types(
    snapshot_type: type[object], idle_status: object, active_status: object
) -> None:
    idle = snapshot_type(idle_status)  # type: ignore[operator]
    active = snapshot_type(active_status, "step-1")  # type: ignore[operator]
    assert idle.execution_id is None  # type: ignore[attr-defined]
    assert active.execution_id == "step-1"  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="idle"):
        snapshot_type(idle_status, "step-1")  # type: ignore[operator]
    with pytest.raises(ValueError, match="requires"):
        snapshot_type(active_status)  # type: ignore[operator]
    with pytest.raises(ValueError, match="path-free"):
        snapshot_type(active_status, "private/path")  # type: ignore[operator]


def test_every_execution_status_requires_the_contractual_id_shape() -> None:
    for snapshot_type, idle_status, statuses in (
        (
            ArchiveListingExecution,
            ArchiveListingStatus.NOT_ATTEMPTED,
            ArchiveListingStatus,
        ),
        (
            ArchiveIntegrityExecution,
            ArchiveIntegrityStatus.NOT_TESTED,
            ArchiveIntegrityStatus,
        ),
        (
            ArchiveExtractionExecution,
            ArchiveExtractionStatus.NOT_ATTEMPTED,
            ArchiveExtractionStatus,
        ),
    ):
        for status in statuses:
            if status is idle_status:
                assert snapshot_type(status).execution_id is None
                with pytest.raises(ValueError, match="idle"):
                    snapshot_type(status, "step-1")
            else:
                assert snapshot_type(status, "step-1").execution_id == "step-1"
                with pytest.raises(ValueError, match="requires"):
                    snapshot_type(status)


def test_execution_snapshot_matrix_fails_closed_and_preserves_provenance() -> None:
    listing = ArchiveListingExecution(ArchiveListingStatus.LISTED, "execution-1")
    integrity = ArchiveIntegrityExecution(ArchiveIntegrityStatus.PASSED, "integrity-1")
    extraction = ArchiveExtractionExecution(ArchiveExtractionStatus.EXTRACTED, "extract-1")
    extracted = replace(
        _member(),
        extraction_execution_id="extract-1",
        observed_uncompressed_bytes=20,
        member_sha256=SHA_D,
        crc_status=ArchiveMemberCrcStatus.MATCHED,
    )
    result = ArchiveListingResult(
        listing,
        ArchiveEncryptionStatus.NONE,
        _key(),
        integrity_execution=integrity,
        extraction_execution=extraction,
        members=(extracted,),
    )
    assert result.listing_execution is listing
    assert result.integrity_execution is integrity
    assert result.extraction_execution is extraction
    assert "private/book.epub" not in repr(result)
    assert "private/book.epub" not in repr(listing)

    with pytest.raises(ValueError, match="distinct"):
        replace(result, integrity_execution=ArchiveIntegrityExecution(
            ArchiveIntegrityStatus.PASSED, "execution-1"
        ))
    with pytest.raises(ValueError, match="integrity execution requires"):
        ArchiveListingResult(
            ArchiveListingExecution(ArchiveListingStatus.TOOL_FAILED, "listing-2"),
            ArchiveEncryptionStatus.NONE,
            _key(),
            integrity_execution=integrity,
            extraction_policy_status=ArchiveSafetyStatus.POLICY_REJECTED,
        )
    with pytest.raises(ValueError, match="safe successful preconditions"):
        ArchiveListingResult(
            listing,
            ArchiveEncryptionStatus.DATA_ENCRYPTED,
            _key(),
            integrity_execution=integrity,
            extraction_execution=extraction,
            password_attempt_status=ArchivePasswordAttemptStatus.SECURE_CHANNEL_UNAVAILABLE,
            extraction_policy_status=ArchiveSafetyStatus.POLICY_REJECTED,
            members=(replace(extracted, encryption_status=ArchiveEncryptionStatus.DATA_ENCRYPTED),),
        )
    with pytest.raises(ValueError, match="failed extraction"):
        replace(
            result,
            extraction_execution=ArchiveExtractionExecution(
                ArchiveExtractionStatus.VALIDATION_FAILED, "extract-2"
            ),
        )


@pytest.mark.parametrize(
    ("status", "policy_status"),
    [
        (ArchiveExtractionStatus.POLICY_REJECTED, ArchiveSafetyStatus.POLICY_REJECTED),
        (ArchiveExtractionStatus.LIMIT_EXCEEDED, ArchiveSafetyStatus.ACCEPTED),
        (ArchiveExtractionStatus.LIMIT_EXCEEDED, ArchiveSafetyStatus.LIMIT_EXCEEDED),
        (ArchiveExtractionStatus.TIMED_OUT, ArchiveSafetyStatus.ACCEPTED),
        (ArchiveExtractionStatus.TOOL_UNAVAILABLE, ArchiveSafetyStatus.ACCEPTED),
        (ArchiveExtractionStatus.TOOL_FAILED, ArchiveSafetyStatus.ACCEPTED),
        (ArchiveExtractionStatus.VALIDATION_FAILED, ArchiveSafetyStatus.ACCEPTED),
    ],
)
def test_terminal_extraction_statuses_obey_the_policy_matrix(
    status: ArchiveExtractionStatus, policy_status: ArchiveSafetyStatus
) -> None:
    result = ArchiveListingResult(
        ArchiveListingExecution(ArchiveListingStatus.LISTED, "execution-1"),
        ArchiveEncryptionStatus.NONE,
        _key(),
        integrity_execution=ArchiveIntegrityExecution(
            ArchiveIntegrityStatus.PASSED, "integrity-1"
        ),
        extraction_execution=ArchiveExtractionExecution(status, "extract-1"),
        extraction_policy_status=policy_status,
        members=(_member(),),
    )
    assert result.extraction_execution.status is status


@pytest.mark.parametrize(
    ("status", "policy_status"),
    [
        (ArchiveExtractionStatus.POLICY_REJECTED, ArchiveSafetyStatus.ACCEPTED),
        (ArchiveExtractionStatus.POLICY_REJECTED, ArchiveSafetyStatus.LIMIT_EXCEEDED),
        (ArchiveExtractionStatus.LIMIT_EXCEEDED, ArchiveSafetyStatus.POLICY_REJECTED),
        (ArchiveExtractionStatus.EXTRACTED, ArchiveSafetyStatus.POLICY_REJECTED),
        (ArchiveExtractionStatus.EXTRACTED, ArchiveSafetyStatus.LIMIT_EXCEEDED),
        (ArchiveExtractionStatus.TIMED_OUT, ArchiveSafetyStatus.POLICY_REJECTED),
        (ArchiveExtractionStatus.TOOL_FAILED, ArchiveSafetyStatus.LIMIT_EXCEEDED),
    ],
)
def test_terminal_extraction_statuses_reject_invalid_policy_combinations(
    status: ArchiveExtractionStatus, policy_status: ArchiveSafetyStatus
) -> None:
    with pytest.raises(ValueError, match="policy"):
        ArchiveListingResult(
            ArchiveListingExecution(ArchiveListingStatus.LISTED, "execution-1"),
            ArchiveEncryptionStatus.NONE,
            _key(),
            integrity_execution=ArchiveIntegrityExecution(
                ArchiveIntegrityStatus.PASSED, "integrity-1"
            ),
            extraction_execution=ArchiveExtractionExecution(status, "extract-1"),
            extraction_policy_status=policy_status,
            members=(_member(),),
        )


@pytest.mark.parametrize("member_kind", [ArchiveMemberKind.DIRECTORY, ArchiveMemberKind.SYMLINK])
def test_non_file_members_reject_extraction_evidence(member_kind: ArchiveMemberKind) -> None:
    with pytest.raises(ValueError, match="non-file"):
        replace(
            _member(member_kind=member_kind),
            extraction_execution_id="extract-1",
            observed_uncompressed_bytes=20,
            member_sha256=SHA_D,
        )


def test_extraction_status_literals_are_exact_and_legacy_constructor_fields_are_absent() -> None:
    assert tuple(ArchiveExtractionStatus) == (
        ArchiveExtractionStatus.NOT_ATTEMPTED,
        ArchiveExtractionStatus.EXTRACTED,
        ArchiveExtractionStatus.LIMIT_EXCEEDED,
        ArchiveExtractionStatus.TIMED_OUT,
        ArchiveExtractionStatus.TOOL_UNAVAILABLE,
        ArchiveExtractionStatus.TOOL_FAILED,
        ArchiveExtractionStatus.POLICY_REJECTED,
        ArchiveExtractionStatus.VALIDATION_FAILED,
    )
    assert {"execution_id", "integrity_status", "listing_status"}.isdisjoint(
        ArchiveListingResult.__dataclass_fields__
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("archive_full_sha256", SHA_C),
        ("volume_group_fingerprint", SHA_C),
        ("tool_provider_id", "other-provider"),
        ("tool_version", "2"),
        ("adapter_version", "adapter-2"),
        ("parser_version", "parser-2"),
        ("secret_version", "secret-2"),
    ],
)
def test_reuse_key_materiality(field_name: str, value: str) -> None:
    original = _key()
    changed = replace(original, **{field_name: value})
    assert changed.member_key() != original.member_key()
    assert changed.listing_key() != original.listing_key()
    assert original.member_key()[0] == ARCHIVE_MEMBER_REUSE_PROFILE


def test_profile_materiality_is_validated_fail_closed() -> None:
    with pytest.raises(ValueError, match="listing profile"):
        replace(_key(), listing_profile="archive-listing/v2")
    with pytest.raises(ValueError, match="extraction profile"):
        replace(_key(), extraction_profile="archive-extraction/v2")
    with pytest.raises(ValueError, match="safety profile"):
        replace(_key(), safety_profile="archive-safety-policy/v2")


def test_failed_or_limited_snapshot_never_replaces_reusable_success() -> None:
    key = _key()
    success = _listed(_member())
    store = FakeArchiveListingReuseStore()
    assert store.remember(key, success) is success
    assert store.remember(key, success) is success

    for status in (
        ArchiveListingStatus.TOOL_FAILED,
        ArchiveListingStatus.LIMIT_EXCEEDED,
        ArchiveListingStatus.POLICY_REJECTED,
    ):
        failed = ArchiveListingResult(
            ArchiveListingExecution(status, "failed-execution"),
            ArchiveEncryptionStatus.NONE,
            key,
            extraction_policy_status=ArchiveSafetyStatus.POLICY_REJECTED,
        )
        assert store.remember(key, failed) is success
        assert store.get(key) is success

    with pytest.raises(ValueError, match="divergent"):
        store.remember(key, _listed(_member(member_path_safe="private/other.epub")))
    with pytest.raises(ValueError, match="reuse key"):
        store.remember(replace(key, tool_version="2"), success)


def test_member_identity_is_domain_separated_and_nfc_stable() -> None:
    composed = build_archive_member_identity(
        archive_full_sha256=SHA_A,
        volume_group_fingerprint=SHA_B,
        member_path_safe="private/é.epub",
        member_ordinal=0,
    )
    decomposed = build_archive_member_identity(
        archive_full_sha256=SHA_A,
        volume_group_fingerprint=SHA_B,
        member_path_safe="private/e\u0301.epub",
        member_ordinal=0,
    )
    assert composed == decomposed
    assert composed != SHA_A


def test_workflow_source_has_no_process_io_network_or_raw_stream_contract() -> None:
    source = Path(__file__).parents[2] / "src" / "foliotone" / "archive" / "workflow.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imports & {"os", "pathlib", "socket", "subprocess", "requests"}
    forbidden_fields = {"argv", "commandline", "stdout", "stderr", "raw_comment"}
    assert not forbidden_fields & ArchiveListingResult.__dataclass_fields__.keys()
