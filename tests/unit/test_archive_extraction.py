from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from typing import Any

import pytest

import tests.unit.test_ebar05_archive_provider as provider_fixture
from foliotone.archive.extraction import (
    _MAX_STREAM_CHUNK_BYTES,
    _ArchiveExtractionValidationError,
    _ExtractionValidationLimits,
    _ObservedWorkspaceMember,
    _ProvisionalExtractionEvidence,
    _ProvisionalMemberEvidence,
    _validate_private_extraction_workspace,
    _validate_workspace_shape,
)
from foliotone.archive.provider import _ArchiveExtractionHandoff
from foliotone.archive.safety_policy import (
    MAX_EXTRACTION_SECONDS,
    MAX_MEMBER_COUNT,
    MAX_SINGLE_MEMBER_BYTES,
    MAX_TOTAL_UNCOMPRESSED_BYTES,
    MAX_WORKSPACE_BYTES,
    ArchiveMemberKind,
)
from foliotone.archive.workflow import ArchiveMemberCrcStatus


class _FakeCapability:
    def __init__(
        self,
        members: tuple[_ObservedWorkspaceMember, ...],
        content: dict[str, tuple[bytes, ...]],
        *,
        unchanged: bool = True,
        now: tuple[float, ...] = (1.0,),
        stream_error: Exception | None = None,
    ) -> None:
        self._members = members
        self._content = content
        self._unchanged = unchanged
        self._now = iter(now)
        self._last_now = now[-1]
        self._stream_error = stream_error

    def snapshot(self) -> tuple[_ObservedWorkspaceMember, ...]:
        return self._members

    def stream(self, member: _ObservedWorkspaceMember) -> tuple[bytes, ...]:
        if self._stream_error is not None:
            raise self._stream_error
        return self._content[member.observation_token]

    def unchanged(self, member: _ObservedWorkspaceMember) -> bool:
        return self._unchanged

    def now_monotonic(self) -> float:
        try:
            self._last_now = next(self._now)
        except StopIteration:
            pass
        return self._last_now


def _genuine_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> _ArchiveExtractionHandoff:
    lock = json.loads(provider_fixture.FORMAT_LOCK.read_text(encoding="utf-8"))
    capability = next(
        item
        for item in lock["capabilities"]
        if item["storage_family"] == "RAR4"
        and item["case_kind"] == "PLAINTEXT_REGULAR"
    )
    original_value = provider_fixture._value

    def fixed_value(value_class: str, ordinal: int) -> str:
        if value_class == "CRC32":
            return "8CDC1683"  # CRC32 of synthetic b"x".
        if value_class == "PRIVATE_LOCATOR_DISCARDED":
            return "nested/mémber.bin"
        return original_value(value_class, ordinal)

    monkeypatch.setattr(provider_fixture, "_value", fixed_value)
    outcome, _runner = provider_fixture._inspect_capability(capability)
    handoff = outcome._extraction_handoff
    assert isinstance(handoff, _ArchiveExtractionHandoff)
    assert handoff.outcome._extraction_handoff is handoff
    return handoff


def _observed(locator: str, content: bytes | None, token: str) -> _ObservedWorkspaceMember:
    return _ObservedWorkspaceMember(
        locator,
        ArchiveMemberKind.DIRECTORY if content is None else ArchiveMemberKind.REGULAR_FILE,
        0 if content is None else len(content),
        token,
    )


def _limits(**changes: Any) -> _ExtractionValidationLimits:
    return _ExtractionValidationLimits(0.0, 10.0, **changes)


def _regular_workspace(
    handoff: _ArchiveExtractionHandoff,
    *,
    content: tuple[bytes, ...] = (b"x",),
    now: tuple[float, ...] = (1.0,),
    unchanged: bool = True,
) -> _FakeCapability:
    locator = handoff.members[0].member_locator
    parent = locator.rsplit("/", 1)[0]
    return _FakeCapability(
        (_observed(parent, None, "dir"), _observed(locator, b"x", "file")),
        {"file": content},
        now=now,
        unchanged=unchanged,
    )


def test_genuine_sealed_handoff_validates_bounded_multi_member_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = _genuine_handoff(monkeypatch)
    result = _validate_private_extraction_workspace(
        handoff, _regular_workspace(handoff), _limits()
    )
    assert isinstance(result, _ProvisionalExtractionEvidence)
    assert tuple(item.member_ordinal for item in result.members) == (0,)
    assert result.members[0].crc_status is ArchiveMemberCrcStatus.MATCHED
    assert result.members[0].member_sha256 == (
        "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"
    )
    assert "nested/mémber.bin" not in repr(result)


def test_genuine_sealed_empty_handoff_yields_empty_provisional_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = _genuine_handoff(monkeypatch)
    # Preserve the exact provider-created sealed graph while projecting its valid empty form.
    object.__setattr__(handoff, "members", ())
    object.__setattr__(handoff.listing_result, "members", ())
    object.__setattr__(handoff.parser_result, "members", ())
    object.__setattr__(handoff.parser_result.public, "members", ())
    assert handoff.outcome.result is not None
    object.__setattr__(handoff.outcome.result, "member_count", 0)

    result = _validate_private_extraction_workspace(
        handoff, _FakeCapability((), {}), _limits()
    )

    assert result.members == ()


def test_rejects_forged_orphaned_and_mutated_handoff_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = _genuine_handoff(monkeypatch)
    workspace = _regular_workspace(handoff)
    forged = copy.copy(handoff)
    with pytest.raises(_ArchiveExtractionValidationError):
        _validate_private_extraction_workspace(forged, workspace, _limits())
    original_hash = handoff.archive_full_sha256
    object.__setattr__(handoff, "archive_full_sha256", "f" * 64)
    try:
        with pytest.raises(_ArchiveExtractionValidationError):
            _validate_private_extraction_workspace(handoff, workspace, _limits())
    finally:
        object.__setattr__(handoff, "archive_full_sha256", original_hash)
    object.__setattr__(handoff.outcome, "_extraction_handoff", None)
    try:
        with pytest.raises(_ArchiveExtractionValidationError):
            _validate_private_extraction_workspace(handoff, workspace, _limits())
    finally:
        object.__setattr__(handoff.outcome, "_extraction_handoff", handoff)


@pytest.mark.parametrize(
    "changes",
    [
        {"max_member_count": True},
        {"max_member_count": -1},
        {"max_member_count": MAX_MEMBER_COUNT + 1},
        {"max_single_member_bytes": MAX_SINGLE_MEMBER_BYTES + 1},
        {"max_total_uncompressed_bytes": MAX_TOTAL_UNCOMPRESSED_BYTES + 1},
        {"max_workspace_bytes": MAX_WORKSPACE_BYTES + 1},
    ],
)
def test_limits_cannot_exceed_project_contract(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="limits"):
        _limits(**changes)


@pytest.mark.parametrize(
    ("start", "deadline"),
    [
        (float("nan"), 1.0),
        (0.0, float("inf")),
        (2.0, 1.0),
        (0.0, MAX_EXTRACTION_SECONDS + 0.001),
    ],
)
def test_deadline_is_finite_monotonic_and_bounded(start: float, deadline: float) -> None:
    with pytest.raises(ValueError, match="limits"):
        _ExtractionValidationLimits(start, deadline)


@pytest.mark.parametrize("now", [(float("nan"),), (float("inf"),), (2.0, 1.0)])
def test_runtime_clock_rejects_nonfinite_and_rollback(
    monkeypatch: pytest.MonkeyPatch, now: tuple[float, ...]
) -> None:
    handoff = _genuine_handoff(monkeypatch)
    with pytest.raises(_ArchiveExtractionValidationError):
        _validate_private_extraction_workspace(
            handoff, _regular_workspace(handoff, now=now), _limits()
        )


@pytest.mark.parametrize(
    "content",
    [
        (b"",),
        (b"x" * (_MAX_STREAM_CHUNK_BYTES + 1),),
        tuple(b"x" for _ in range((MAX_SINGLE_MEMBER_BYTES // _MAX_STREAM_CHUNK_BYTES) + 1)),
    ],
)
def test_stream_rejects_empty_oversized_and_excessive_chunks(
    monkeypatch: pytest.MonkeyPatch, content: tuple[bytes, ...]
) -> None:
    handoff = _genuine_handoff(monkeypatch)
    with pytest.raises(_ArchiveExtractionValidationError):
        _validate_private_extraction_workspace(
            handoff, _regular_workspace(handoff, content=content), _limits()
        )


def test_zero_byte_file_requires_zero_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    handoff = _genuine_handoff(monkeypatch)
    member = handoff.members[0]
    parser_member = handoff.parser_result.members[0]
    listed = handoff.listing_result.members[0]
    for target in (member, parser_member, listed):
        object.__setattr__(target, "declared_uncompressed_bytes", 0)
    object.__setattr__(member, "listed_crc32", "00000000")
    object.__setattr__(parser_member, "crc32", "00000000")
    locator = member.member_locator
    parent = locator.rsplit("/", 1)[0]
    observations = (_observed(parent, None, "dir"), _observed(locator, b"", "file"))
    result = _validate_private_extraction_workspace(
        handoff, _FakeCapability(observations, {"file": ()}), _limits()
    )
    assert result.members[0].observed_uncompressed_bytes == 0
    with pytest.raises(_ArchiveExtractionValidationError):
        _validate_private_extraction_workspace(
            handoff, _FakeCapability(observations, {"file": (b"",)}), _limits()
        )


@pytest.mark.parametrize("variant", ["missing", "extra", "case", "nfc"])
def test_requires_exact_implicit_directories_and_raw_locators(
    monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    handoff = _genuine_handoff(monkeypatch)
    locator = handoff.members[0].member_locator
    parent = locator.rsplit("/", 1)[0]
    members = {
        "missing": (_observed(locator, b"x", "file"),),
        "extra": (
            _observed(parent, None, "dir"),
            _observed(locator, b"x", "file"),
            _observed("extra", None, "extra"),
        ),
        "case": (
            _observed(parent.upper(), None, "dir"),
            _observed(locator, b"x", "file"),
        ),
        "nfc": (
            _observed(parent, None, "dir"),
            _observed("nested/me\u0301mber.bin", b"x", "file"),
        ),
    }[variant]
    with pytest.raises(_ArchiveExtractionValidationError):
        _validate_private_extraction_workspace(
            handoff, _FakeCapability(members, {"file": (b"x",)}), _limits()
        )


def test_reordered_regular_observations_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    handoff = _genuine_handoff(monkeypatch)
    first = handoff.members[0]
    second = replace(
        first,
        member_ordinal=1,
        member_locator="nested/second.bin",
        member_identity="2" * 64,
    )
    source = SimpleNamespace(members=(first, second))
    observed = (
        _observed("nested", None, "dir"),
        _observed(second.member_locator, b"x", "second"),
        _observed(first.member_locator, b"x", "first"),
    )
    with pytest.raises(_ArchiveExtractionValidationError):
        _validate_workspace_shape(source, observed, _limits())  # type: ignore[arg-type]


def test_capability_failure_toctou_and_private_dtos_are_redacted_and_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = _genuine_handoff(monkeypatch)
    base = _regular_workspace(handoff)
    for capability in (
        _regular_workspace(handoff, unchanged=False),
        _FakeCapability(
            base._members,
            {"file": (b"x",)},
            stream_error=RuntimeError("C:/private/secret.bin"),
        ),
    ):
        with pytest.raises(_ArchiveExtractionValidationError) as raised:
            _validate_private_extraction_workspace(handoff, capability, _limits())
        assert "private" not in str(raised.value)
        assert "secret" not in repr(raised.value)
    observed = base._members[1]
    with pytest.raises(FrozenInstanceError):
        observed.locator = "other"  # type: ignore[misc]
    assert handoff.members[0].member_locator not in repr(observed)
    arbitrary = _ProvisionalMemberEvidence(
        2, "1" * 64, 1, 1, "2" * 64, ArchiveMemberCrcStatus.MATCHED
    )
    with pytest.raises(ValueError, match="provisional"):
        _ProvisionalExtractionEvidence(
            "archive-extraction-validator/v1", (arbitrary,), (2,), object()
        )
