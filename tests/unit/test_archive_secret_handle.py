"""Synthetic redaction and persistence-boundary tests for SecretHandle."""

import ast
from dataclasses import fields, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from foliotone.archive import (
    ARCHIVE_PASSWORD_ATTEMPT_PROFILE,
    ArchivePasswordAttemptMetadata,
    ArchivePasswordAttemptStatus,
    ArchiveSecretCandidateSource,
    SecretHandle,
)


def _metadata(handle: SecretHandle | None = None) -> ArchivePasswordAttemptMetadata:
    return ArchivePasswordAttemptMetadata(
        archive_identity="archive-identity-1",
        observation_profile="archive-observation/v1",
        tool_provider_id="archive-7zip",
        tool_version="26.02",
        adapter_version="archive-7zip-cli/1",
        status=ArchivePasswordAttemptStatus.REJECTED,
        attempt_count=1,
        observed_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        secret_handle=handle,
        candidate_source=ArchiveSecretCandidateSource.DIRECTORY_SIDECAR,
        candidate_rank=0,
    )


def test_handle_exposes_only_opaque_identity_and_version() -> None:
    handle = SecretHandle("local-provider", "handle-123", "v7")
    assert handle.cache_key() == ("local-provider", "handle-123", "v7")
    assert handle.to_persistable_payload() == {
        "provider_id": "local-provider",
        "handle_id": "handle-123",
        "secret_version": "v7",
    }


def test_attempt_payload_and_cache_key_are_secret_free() -> None:
    handle = SecretHandle("local-provider", "opaque-handle", "v1")
    metadata = _metadata(handle)
    payload = metadata.to_persistable_payload()
    assert payload["profile"] == ARCHIVE_PASSWORD_ATTEMPT_PROFILE
    assert payload["status"] == "REJECTED"
    assert payload["secret_handle"] == handle.to_persistable_payload()
    assert "commandline" not in payload and "argv" not in payload and "env" not in payload
    assert metadata.cache_key()[-1] == handle.cache_key()


def test_plaintext_is_not_an_accepted_constructor_field_or_error_payload() -> None:
    with pytest.raises(TypeError):
        ArchivePasswordAttemptMetadata(  # type: ignore[call-arg]
            archive_identity="a",
            observation_profile="p",
            tool_provider_id="t",
            tool_version="v",
            adapter_version="a",
            status=ArchivePasswordAttemptStatus.REJECTED,
            attempt_count=0,
            observed_at=datetime.now(UTC),
            plaintext="sentinel-secret",  # type: ignore[call-arg]
        )

    with pytest.raises(ValueError) as error:
        SecretHandle("provider", "bad/name", "v1")
    assert "bad/name" not in str(error.value)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: SecretHandle("", "handle", "v1"),
        lambda: SecretHandle("provider", "handle", ""),
        lambda: SecretHandle("provider", "handle", "v1\n"),
        lambda: SecretHandle("provider", "x" * 257, "v1"),
    ],
)
def test_opaque_identifiers_are_bounded_and_path_free(factory: object) -> None:
    with pytest.raises(ValueError):
        factory()  # type: ignore[operator]


def test_attempt_count_timestamp_and_rank_bounds() -> None:
    with pytest.raises(ValueError):
        replace(_metadata(), attempt_count=17)

    with pytest.raises(ValueError):
        replace(_metadata(), observed_at=datetime(2026, 8, 20, 12, 0))

    with pytest.raises(ValueError):
        replace(_metadata(), candidate_rank=64)

    with pytest.raises(ValueError):
        replace(_metadata(), attempt_count="1")  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        replace(_metadata(), candidate_source=None)

    with pytest.raises(ValueError):
        replace(_metadata(), candidate_rank=None)

    with pytest.raises(ValueError):
        replace(_metadata(), observation_profile="../private")


def test_static_contract_has_no_io_or_secret_material_fields() -> None:
    source = Path(__file__).parents[2] / "src" / "foliotone" / "archive" / "secret_handle.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imports & {"os", "pathlib", "socket", "subprocess", "requests"}
    forbidden = {"password", "plaintext", "material", "commandline", "argv", "env", "stdin"}
    for model in (SecretHandle, ArchivePasswordAttemptMetadata):
        assert not {field.name.casefold() for field in fields(model)} & forbidden
