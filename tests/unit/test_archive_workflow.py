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
    ArchiveIntegrityStatus,
    ArchiveListingResult,
    ArchiveListingStatus,
    ArchiveMemberCrcStatus,
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
        listing_status=ArchiveListingStatus.LISTED,
        execution_id="execution-1",
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
        ArchiveListingStatus.LISTED,
        "execution-1",
        ArchiveEncryptionStatus.DATA_ENCRYPTED,
        _key(),
        password_attempt_status=ArchivePasswordAttemptStatus.SECURE_CHANNEL_UNAVAILABLE,
        extraction_policy_status=ArchiveSafetyStatus.POLICY_REJECTED,
        members=(data_encrypted,),
    )
    assert listed.members == (data_encrypted,)
    assert listed.password_attempt_status is ArchivePasswordAttemptStatus.SECURE_CHANNEL_UNAVAILABLE

    headers = ArchiveListingResult(
        ArchiveListingStatus.PASSWORD_REQUIRED,
        "execution-2",
        ArchiveEncryptionStatus.HEADERS_ENCRYPTED,
        _key(),
        password_attempt_status=ArchivePasswordAttemptStatus.SECURE_CHANNEL_UNAVAILABLE,
        extraction_policy_status=ArchiveSafetyStatus.POLICY_REJECTED,
    )
    assert headers.members == ()
    with pytest.raises(ValueError, match="encrypted headers"):
        replace(headers, listing_status=ArchiveListingStatus.LISTED)
    with pytest.raises(ValueError, match="secure"):
        replace(listed, password_attempt_status=ArchivePasswordAttemptStatus.ACCEPTED)


def test_unknown_declared_size_is_preserved_but_blocks_extraction() -> None:
    unknown = _member(declared_compressed_bytes=None)
    with pytest.raises(ValueError, match="blocked"):
        _listed(unknown)
    blocked = ArchiveListingResult(
        ArchiveListingStatus.LISTED,
        "execution-1",
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

    with pytest.raises(ValueError, match="safe successful"):
        _listed(extracted)
    successful = ArchiveListingResult(
        ArchiveListingStatus.LISTED,
        "execution-1",
        ArchiveEncryptionStatus.NONE,
        _key(),
        integrity_status=ArchiveIntegrityStatus.PASSED,
        members=(extracted,),
    )
    assert successful.members == (extracted,)

    second = _member(
        member_ordinal=1,
        member_path_safe="private/second.epub",
    )
    with pytest.raises(ValueError, match="partial extraction"):
        ArchiveListingResult(
            ArchiveListingStatus.LISTED,
            "execution-1",
            ArchiveEncryptionStatus.NONE,
            _key(),
            integrity_status=ArchiveIntegrityStatus.PASSED,
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
            status,
            "failed-execution",
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
