from __future__ import annotations

import json
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from foliotone.archive.container_sandbox import (
    ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
    ARCHIVE_WRAPPER_CONTAINER_RUNNER_PROFILE,
    ArchiveContainerRequest,
    ArchiveContainerRunResult,
    ArchiveContainerRunStatus,
    ArchiveVolumeSource,
    ArchiveWrapperContainerRequest,
    ArchiveWrapperContainerRunResult,
    ArchiveWrapperOperation,
)
from foliotone.archive.provider import (
    ARCHIVE_PROVIDER_PROFILE,
    ArchiveProviderOutcome,
    ArchiveSevenZipProvider,
    _ArchiveExtractionHandoff,
    _ArchiveExtractionMemberHandoff,
    _ArchiveWrapperReuseEvidence,
    _attach_extraction_handoff,
    _inspect,
    _listing_status,
    build_archive_provider_input_identity,
    build_archive_volume_group_fingerprint,
)
from foliotone.archive.safety_policy import ArchiveSafetyStatus
from foliotone.archive.sevenzip import build_7zzs_listing_command
from foliotone.archive.sevenzip_slt import (
    ArchiveSevenZipFormatCase,
    ArchiveSevenZipSltParseStatus,
)
from foliotone.archive.signatures import ArchiveStorageFamily, observe_archive_signature_v2
from foliotone.archive.workflow import (
    ArchiveEncryptionStatus,
    ArchiveIntegrityStatus,
)
from foliotone.core import ToolExecutionStatus

FORMAT_LOCK = (
    Path(__file__).parents[2] / "packaging" / "archive" / "7zip-26.02" / "archive-format.lock.json"
)
INSTANT = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _run(status: ArchiveContainerRunStatus) -> ArchiveContainerRunResult:
    return ArchiveContainerRunResult(
        ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
        status,
        0 if status is ArchiveContainerRunStatus.COMPLETED else 2,
    )


class _FakeRunner:
    def __init__(
        self,
        steps: list[tuple[ArchiveContainerRunStatus, tuple[bytes, ...]]],
    ) -> None:
        self.steps = steps
        self.requests: list[ArchiveContainerRequest] = []

    def run(self, request: ArchiveContainerRequest, **kwargs: Any) -> ArchiveContainerRunResult:
        self.requests.append(request)
        status, chunks = self.steps.pop(0)
        consumer = kwargs["stdout_consumer"]
        stderr = kwargs["stderr_classifier"]
        assert stderr(b"private foreign-language prose") is True
        for chunk in chunks:
            if not consumer(chunk):
                return _run(ArchiveContainerRunStatus.POLICY_REJECTED)
        return _run(status)


class _FakeWrapperRunner:
    def __init__(
        self,
        steps: list[
            tuple[
                ArchiveContainerRunStatus,
                tuple[bytes, ...],
                int,
                str | None,
            ]
        ],
    ) -> None:
        self.steps = steps
        self.requests: list[ArchiveWrapperContainerRequest] = []
        self.direct_requests: list[ArchiveContainerRequest] = []

    def run(self, request: ArchiveContainerRequest, **_kwargs: Any) -> ArchiveContainerRunResult:
        self.direct_requests.append(request)
        raise AssertionError("wrapper provider must not use the direct runner")

    def run_wrapper_pipeline(
        self, request: ArchiveWrapperContainerRequest, **kwargs: Any
    ) -> ArchiveWrapperContainerRunResult:
        self.requests.append(request)
        status, chunks, stream_size, stream_sha256 = self.steps.pop(0)
        consumer = kwargs["stdout_consumer"]
        for chunk in chunks:
            if not consumer(chunk):
                return ArchiveWrapperContainerRunResult(
                    ARCHIVE_WRAPPER_CONTAINER_RUNNER_PROFILE,
                    ArchiveContainerRunStatus.POLICY_REJECTED,
                )
        return ArchiveWrapperContainerRunResult(
            ARCHIVE_WRAPPER_CONTAINER_RUNNER_PROFILE,
            status,
            0 if status is ArchiveContainerRunStatus.COMPLETED else 2,
            0 if status is ArchiveContainerRunStatus.COMPLETED else None,
            sum(len(chunk) for chunk in chunks),
            0,
            stream_size if status is ArchiveContainerRunStatus.COMPLETED else 0,
            stream_sha256 if status is ArchiveContainerRunStatus.COMPLETED else None,
        )


def _request() -> ArchiveContainerRequest:
    synthetic_root = Path.cwd().resolve()
    source = ArchiveVolumeSource(
        synthetic_root / ".synthetic-ebar05-source.bin",
        1,
        "a" * 64,
        "archive",
    )
    return ArchiveContainerRequest(
        (source,),
        build_7zzs_listing_command(),
        (synthetic_root,),
    )


def _tar_header() -> bytes:
    header = bytearray(512)
    header[:8] = b"file.txt"
    header[148:156] = b"        "
    header[148:156] = f"{sum(header):06o}\0 ".encode()
    return bytes(header)


def _signature(storage: str) -> object:
    names = {
        "ZIP": ("book.zip", b"PK\x03\x04"),
        "RAR4": ("book.rar", b"Rar!\x1a\x07\x00"),
        "RAR5": ("book.rar", b"Rar!\x1a\x07\x01\x00"),
        "SEVEN_Z": ("book.7z", b"7z\xbc\xaf'\x1c"),
        "TAR": ("book.tar", _tar_header()),
    }
    name, header = names[storage]
    return observe_archive_signature_v2(name, header)


def _value(value_class: str, ordinal: int) -> str:
    return {
        "EMPTY": "",
        "BOOL_PLUS": "+",
        "BOOL_MINUS": "-",
        "CANONICAL_UINT": "1",
        "CRC32": "ABCDEF12",
        "TIMESTAMP": "2026-08-20 00:00:00",
        "PRIVATE_LOCATOR_DISCARDED": f"member-{ordinal}.bin",
        "PRIVATE_NONEMPTY_DISCARDED": "private-target",
        "TECHNICAL_NONEMPTY_DISCARDED": "technical",
    }[value_class]


def _stream(capability: dict[str, Any]) -> bytes:
    records = []
    for ordinal, profile in enumerate(capability["record_profiles"], start=1):
        records.append(
            "".join(
                f"{field['name']} = {_value(field['value_class'], ordinal)}\n"
                for field in profile["fields"]
            )
            + "\n"
        )
    return "".join(records).encode()


def _tar_plaintext_capability() -> dict[str, Any]:
    lock = json.loads(FORMAT_LOCK.read_text(encoding="utf-8"))
    return next(
        item
        for item in lock["capabilities"]
        if item["storage_family"] == "TAR"
        and item["case_kind"] == "PLAINTEXT_REGULAR"
        and item["disposition"] == "MEASURED"
    )


def _wrapper_signature(kind: str) -> object:
    names = {
        "GZIP": ("book.tar.gz", b"\x1f\x8b"),
        "BZIP2": ("book.tar.bz2", b"BZh"),
        "XZ": ("book.tar.xz", b"\xfd7zXZ\x00"),
        "ZSTD": ("book.tar.zst", b"(\xb5/\xfd"),
    }
    name, header = names[kind]
    return observe_archive_signature_v2(name, header)


def _wrapper_steps(
    *, integrity_hash: str = "e" * 64
) -> list[tuple[ArchiveContainerRunStatus, tuple[bytes, ...], int, str | None]]:
    listing = _stream(_tar_plaintext_capability())
    return [
        (ArchiveContainerRunStatus.COMPLETED, (listing,), 2_048, "e" * 64),
        (ArchiveContainerRunStatus.COMPLETED, (), 2_048, integrity_hash),
    ]


def _clock() -> Any:
    values = iter(INSTANT + timedelta(seconds=index) for index in range(8))
    return lambda: next(values)


def _inspect_capability(capability: dict[str, Any]) -> tuple[ArchiveProviderOutcome, _FakeRunner]:
    encrypted = capability["case_kind"] in {"ALL_ENCRYPTED", "MIXED"}
    steps = [(ArchiveContainerRunStatus.COMPLETED, (_stream(capability),))]
    if not encrypted:
        steps.append((ArchiveContainerRunStatus.COMPLETED, (b"discarded integrity",)))
    runner = _FakeRunner(steps)
    outcome = _inspect(
        runner,
        _request(),
        signature=_signature(capability["storage_family"]),  # type: ignore[arg-type]
        archive_observation_id="archive-observation-1",
        archive_full_sha256="a" * 64,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(_request()),
        cancellation=None,
        now=_clock(),
    )
    return outcome, runner


def test_every_measured_cell_uses_locked_parser_and_exact_provenance() -> None:
    lock = json.loads(FORMAT_LOCK.read_text(encoding="utf-8"))
    measured = [item for item in lock["capabilities"] if item["disposition"] == "MEASURED"]
    assert len(measured) == 14
    for capability in measured:
        outcome, runner = _inspect_capability(capability)
        assert outcome.profile == ARCHIVE_PROVIDER_PROFILE
        assert outcome.result is not None
        assert outcome.result.listing_status.value == "LISTED"
        assert outcome.executions[0].status is ToolExecutionStatus.SUCCEEDED
        assert outcome.result.member_count == len(capability["record_profiles"])
        persistence = outcome._persistence_handoff
        assert persistence is not None
        assert persistence.outcome is outcome
        assert persistence.parser_result.public.case_kind.value == capability["case_kind"]
        assert len(persistence.listing_result.members) == outcome.result.member_count
        assert not hasattr(outcome.result, "members")
        assert len(runner.requests) == (
            1 if capability["case_kind"] in {"ALL_ENCRYPTED", "MIXED"} else 2
        )
        assert "member-" not in repr(outcome)


def test_private_handoff_binds_the_single_accepted_run_without_rendering_members() -> None:
    lock = json.loads(FORMAT_LOCK.read_text(encoding="utf-8"))
    capability = next(
        item
        for item in lock["capabilities"]
        if item["storage_family"] == "RAR4" and item["case_kind"] == "PLAINTEXT_REGULAR"
    )
    outcome, runner = _inspect_capability(capability)

    handoff = outcome._extraction_handoff
    assert isinstance(handoff, _ArchiveExtractionHandoff)
    assert handoff.outcome is outcome
    assert handoff.parser_result is outcome._private_parser_result
    assert outcome.result is not None
    assert handoff.listing_result.listing_execution is outcome.result.listing_execution
    assert handoff.listing_execution is outcome.executions[0]
    assert handoff.integrity_execution is outcome.executions[1]
    assert handoff.archive_full_sha256 == outcome.result.reuse_key.archive_full_sha256
    assert handoff.volume_group_fingerprint == outcome.result.reuse_key.volume_group_fingerprint
    assert handoff.signature_profile == "archive-signature-observer/v2"
    assert handoff.storage_family.value == "RAR4"
    assert handoff.case_kind.value == "PLAINTEXT_REGULAR"
    assert handoff.parser_profile == "archive-7zip-slt-parser/v3"
    assert handoff.format_lock_profile == "archive-7zip-format-lock/v1"
    assert len(handoff.format_lock_sha256) == 64
    assert handoff.compatibility_profile == "archive-publication-storage-compatibility/v1"
    assert len(handoff.members) == outcome.result.member_count
    assert tuple(item.member_ordinal for item in handoff.members) == tuple(
        item.member_ordinal for item in handoff.listing_result.members
    )
    assert tuple(item.member_identity for item in handoff.members) == tuple(
        item.member_identity for item in handoff.listing_result.members
    )
    assert len(runner.requests) == 2
    for rendered in (repr(handoff), str(handoff), repr(outcome), str(outcome)):
        assert "member-" not in rendered
        assert "ABCDEF12" not in rendered


def test_private_handoff_rejects_equal_id_result_and_member_lineage_tampering() -> None:
    lock = json.loads(FORMAT_LOCK.read_text(encoding="utf-8"))
    capability = next(
        item
        for item in lock["capabilities"]
        if item["storage_family"] == "RAR4" and item["case_kind"] == "PLAINTEXT_REGULAR"
    )
    outcome, _runner = _inspect_capability(capability)
    handoff = outcome._extraction_handoff
    assert isinstance(handoff, _ArchiveExtractionHandoff)

    def fresh_outcome() -> ArchiveProviderOutcome:
        fresh = ArchiveProviderOutcome(outcome.profile, outcome.result, outcome.executions)
        object.__setattr__(fresh, "_private_listing_result", handoff.listing_result)
        object.__setattr__(fresh, "_private_parser_result", handoff.parser_result)
        return fresh

    other_valid_result = replace(handoff.listing_result)
    assert other_valid_result is not handoff.listing_result
    assert (
        other_valid_result.listing_execution.execution_id
        == handoff.listing_result.listing_execution.execution_id
    )
    with pytest.raises(ValueError, match="lineage"):
        _attach_extraction_handoff(
            fresh_outcome(),
            other_valid_result,
            outcome.executions,
            _signature("RAR4"),  # type: ignore[arg-type]
            handoff.parser_result,
        )

    foreign_parser_result = replace(handoff.parser_result)
    assert foreign_parser_result is not handoff.parser_result
    with pytest.raises(ValueError, match="lineage"):
        _attach_extraction_handoff(
            fresh_outcome(),
            handoff.listing_result,
            outcome.executions,
            _signature("RAR4"),  # type: ignore[arg-type]
            foreign_parser_result,
        )

    changed_locator = replace(handoff.members[0], member_locator="different-member.bin")
    changed_identity = replace(handoff.members[0], member_identity="f" * 64)
    changed_crc = replace(handoff.members[0], listed_crc32="12345678")
    with pytest.raises(ValueError, match="member lineage"):
        replace(
            handoff,
            outcome=fresh_outcome(),
            members=(changed_locator, *handoff.members[1:]),
        )
    with pytest.raises(ValueError, match="member lineage"):
        replace(
            handoff,
            outcome=fresh_outcome(),
            members=(changed_identity, *handoff.members[1:]),
        )
    with pytest.raises(ValueError, match="member lineage"):
        replace(
            handoff,
            outcome=fresh_outcome(),
            members=(changed_crc, *handoff.members[1:]),
        )


def test_private_handoff_dtos_fail_closed_on_direct_mutation() -> None:
    lock = json.loads(FORMAT_LOCK.read_text(encoding="utf-8"))
    capability = next(
        item
        for item in lock["capabilities"]
        if item["storage_family"] == "RAR4" and item["case_kind"] == "PLAINTEXT_REGULAR"
    )
    outcome, _runner = _inspect_capability(capability)
    handoff = outcome._extraction_handoff
    assert isinstance(handoff, _ArchiveExtractionHandoff)
    member = handoff.members[0]
    assert isinstance(member, _ArchiveExtractionMemberHandoff)

    with pytest.raises(ValueError, match="ordinal"):
        replace(member, member_ordinal=True)
    with pytest.raises(ValueError, match="kind"):
        replace(member, member_kind="REGULAR_FILE")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="size"):
        replace(member, declared_uncompressed_bytes=-1)
    with pytest.raises(ValueError, match="CRC"):
        replace(member, listed_crc32="private-crc")
    with pytest.raises(ValueError, match="identity"):
        replace(member, member_identity="A" * 64)
    with pytest.raises(ValueError, match="flags"):
        replace(member, encrypted=True)

    def fresh_outcome() -> ArchiveProviderOutcome:
        fresh = ArchiveProviderOutcome(outcome.profile, outcome.result, outcome.executions)
        object.__setattr__(fresh, "_private_listing_result", handoff.listing_result)
        object.__setattr__(fresh, "_private_parser_result", handoff.parser_result)
        return fresh

    for mutation in (
        {"format_lock_sha256": "f" * 64},
        {"signature_profile": "archive-signature-observer/v1"},
        {"compatibility_profile": "archive-publication-storage-compatibility/v0"},
        {"storage_family": ArchiveStorageFamily.UNKNOWN},
        {"case_kind": ArchiveSevenZipFormatCase.ALL_ENCRYPTED},
        {"case_kind": ArchiveSevenZipFormatCase.DIRECTORY},
        {"members": list(handoff.members)},
    ):
        with pytest.raises(ValueError):
            replace(handoff, outcome=fresh_outcome(), **mutation)  # type: ignore[arg-type]


def test_private_handoff_is_absent_for_every_non_extractable_terminal_state() -> None:
    lock = json.loads(FORMAT_LOCK.read_text(encoding="utf-8"))
    regular = next(
        item
        for item in lock["capabilities"]
        if item["storage_family"] == "RAR4" and item["case_kind"] == "PLAINTEXT_REGULAR"
    )
    encrypted = next(
        item
        for item in lock["capabilities"]
        if item["storage_family"] == "ZIP" and item["case_kind"] == "ALL_ENCRYPTED"
    )
    rejected = next(
        item
        for item in lock["capabilities"]
        if item["storage_family"] == "TAR" and item["case_kind"] == "SYMBOLIC_LINK"
    )
    outcomes = [
        _inspect_capability(encrypted)[0],
        _inspect_capability(rejected)[0],
        _inspect(
            _FakeRunner([(ArchiveContainerRunStatus.COMPLETED, (b"Unknown = private\n\n",))]),
            _request(),
            signature=_signature("RAR4"),  # type: ignore[arg-type]
            archive_observation_id="archive-observation-1",
            archive_full_sha256="a" * 64,
            volume_group_fingerprint=build_archive_volume_group_fingerprint(_request()),
            cancellation=None,
            now=_clock(),
        ),
        _inspect(
            _FakeRunner(
                [
                    (ArchiveContainerRunStatus.COMPLETED, (_stream(regular),)),
                    (ArchiveContainerRunStatus.TOOL_FAILED, ()),
                ]
            ),
            _request(),
            signature=_signature("RAR4"),  # type: ignore[arg-type]
            archive_observation_id="archive-observation-1",
            archive_full_sha256="a" * 64,
            volume_group_fingerprint=build_archive_volume_group_fingerprint(_request()),
            cancellation=None,
            now=_clock(),
        ),
        _inspect(
            _FakeRunner([(ArchiveContainerRunStatus.CANCELLED, ())]),
            _request(),
            signature=_signature("ZIP"),  # type: ignore[arg-type]
            archive_observation_id="archive-observation-1",
            archive_full_sha256="a" * 64,
            volume_group_fingerprint=build_archive_volume_group_fingerprint(_request()),
            cancellation=None,
            now=_clock(),
        ),
        _inspect(
            _FakeRunner([]),
            _request(),
            signature=observe_archive_signature_v2("book.tar.gz", b"\x1f\x8b"),
            archive_observation_id="archive-observation-1",
            archive_full_sha256="a" * 64,
            volume_group_fingerprint=build_archive_volume_group_fingerprint(_request()),
            cancellation=None,
            now=_clock(),
        ),
    ]
    assert all(outcome._extraction_handoff is None for outcome in outcomes)


@pytest.mark.parametrize("kind", ["GZIP", "BZIP2", "XZ", "ZSTD"])
def test_wrapper_runs_two_composites_with_matching_inner_evidence_and_no_handoff(
    kind: str,
) -> None:
    runner = _FakeWrapperRunner(_wrapper_steps())
    outcome = _inspect(
        runner,
        _request(),
        signature=_wrapper_signature(kind),  # type: ignore[arg-type]
        archive_observation_id="archive-observation-1",
        archive_full_sha256="a" * 64,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(_request()),
        cancellation=None,
        now=_clock(),
    )
    assert outcome.result is not None
    assert outcome.result.listing_status.value == "LISTED"
    assert outcome.result.integrity_status is ArchiveIntegrityStatus.PASSED
    assert outcome.result.extraction_policy_status is ArchiveSafetyStatus.POLICY_REJECTED
    assert len(outcome.executions) == 2
    assert [request.operation for request in runner.requests] == [
        ArchiveWrapperOperation.LISTING,
        ArchiveWrapperOperation.INTEGRITY,
    ]
    assert runner.direct_requests == []
    assert outcome._extraction_handoff is None
    evidence = outcome._wrapper_reuse_evidence
    assert isinstance(evidence, _ArchiveWrapperReuseEvidence)
    assert outcome._persistence_handoff is not None
    assert outcome._persistence_handoff.wrapper_listing_run is evidence.listing_run
    assert outcome._persistence_handoff.wrapper_integrity_run is evidence.integrity_run
    assert evidence.inner_stream_size_bytes == 2_048
    assert evidence.inner_stream_sha256 == "e" * 64
    assert kind not in repr(outcome)


def test_wrapper_inner_hash_mismatch_fails_integrity_and_discards_reuse_evidence() -> None:
    runner = _FakeWrapperRunner(_wrapper_steps(integrity_hash="f" * 64))
    outcome = _inspect(
        runner,
        _request(),
        signature=_wrapper_signature("GZIP"),  # type: ignore[arg-type]
        archive_observation_id="archive-observation-1",
        archive_full_sha256="a" * 64,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(_request()),
        cancellation=None,
        now=_clock(),
    )
    assert outcome.result is not None
    assert outcome.result.integrity_status is ArchiveIntegrityStatus.TOOL_FAILED
    assert outcome.executions[1].status is ToolExecutionStatus.FAILED
    assert outcome._wrapper_reuse_evidence is None
    assert outcome._persistence_handoff is not None
    assert outcome._persistence_handoff.wrapper_listing_run is not None
    assert outcome._extraction_handoff is None


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ArchiveContainerRunStatus.TOOL_UNAVAILABLE, "TOOL_UNAVAILABLE"),
        (ArchiveContainerRunStatus.TIMED_OUT, "TIMED_OUT"),
        (ArchiveContainerRunStatus.LIMIT_EXCEEDED, "LIMIT_EXCEEDED"),
        (ArchiveContainerRunStatus.POLICY_REJECTED, "POLICY_REJECTED"),
        (ArchiveContainerRunStatus.TOOL_FAILED, "TOOL_FAILED"),
    ],
)
def test_wrapper_listing_runner_status_is_preserved(
    status: ArchiveContainerRunStatus,
    expected: str,
) -> None:
    runner = _FakeWrapperRunner([(status, (), 0, None)])
    outcome = _inspect(
        runner,
        _request(),
        signature=_wrapper_signature("GZIP"),  # type: ignore[arg-type]
        archive_observation_id="archive-observation-1",
        archive_full_sha256="a" * 64,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(_request()),
        cancellation=None,
        now=_clock(),
    )
    assert outcome.result is not None
    assert outcome.result.listing_status.value == expected
    assert len(outcome.executions) == 1
    assert outcome._wrapper_reuse_evidence is None
    assert outcome._persistence_handoff is not None


def test_wrapper_cancellation_is_snapshotless_and_signature_mismatch_never_runs() -> None:
    cancelled_runner = _FakeWrapperRunner(
        [(ArchiveContainerRunStatus.CANCELLED, (), 0, None)]
    )
    cancelled = _inspect(
        cancelled_runner,
        _request(),
        signature=_wrapper_signature("GZIP"),  # type: ignore[arg-type]
        archive_observation_id="archive-observation-1",
        archive_full_sha256="a" * 64,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(_request()),
        cancellation=None,
        now=_clock(),
    )
    assert cancelled.result is None
    assert cancelled.executions[0].status is ToolExecutionStatus.CANCELLED

    mismatched_runner = _FakeWrapperRunner([])
    mismatched = _inspect(
        mismatched_runner,
        _request(),
        signature=observe_archive_signature_v2("book.gz", b"\x1f\x8b"),
        archive_observation_id="archive-observation-1",
        archive_full_sha256="a" * 64,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(_request()),
        cancellation=None,
        now=_clock(),
    )
    assert mismatched.result is not None
    assert mismatched.result.listing_status.value == "NOT_ATTEMPTED"
    assert mismatched_runner.requests == []


def test_wrapper_reuse_evidence_is_sealed_to_both_concrete_runs() -> None:
    outcome = _inspect(
        _FakeWrapperRunner(_wrapper_steps()),
        _request(),
        signature=_wrapper_signature("GZIP"),  # type: ignore[arg-type]
        archive_observation_id="archive-observation-1",
        archive_full_sha256="a" * 64,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(_request()),
        cancellation=None,
        now=_clock(),
    )
    evidence = outcome._wrapper_reuse_evidence
    assert isinstance(evidence, _ArchiveWrapperReuseEvidence)
    with pytest.raises(ValueError, match="lineage"):
        replace(evidence, inner_stream_sha256="f" * 64)
    with pytest.raises(ValueError, match="lineage"):
        replace(
            evidence,
            outer_compression_kind=evidence.outer_compression_kind.__class__.XZ,
        )
    with pytest.raises(ValueError, match="lineage"):
        replace(
            evidence,
            integrity_run=replace(
                evidence.integrity_run,
                inner_stream_sha256="f" * 64,
            ),
        )


def test_parser_failure_is_failed_execution_not_false_success() -> None:
    runner = _FakeRunner([(ArchiveContainerRunStatus.COMPLETED, (b"Unknown = private\n\n",))])
    outcome = _inspect(
        runner,
        _request(),
        signature=_signature("ZIP"),  # type: ignore[arg-type]
        archive_observation_id="archive-observation-1",
        archive_full_sha256="a" * 64,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(_request()),
        cancellation=None,
        now=_clock(),
    )
    assert outcome.result is not None
    assert outcome.result.listing_status.value == "TOOL_FAILED"
    assert outcome.executions[0].status is ToolExecutionStatus.FAILED
    assert outcome._persistence_handoff is not None
    assert not any(thread.name == "archive-locked-parser" for thread in threading.enumerate())
    with pytest.raises(ValueError, match="statuses"):
        ArchiveProviderOutcome(
            ARCHIVE_PROVIDER_PROFILE,
            outcome.result,
            (replace(outcome.executions[0], status=ToolExecutionStatus.SUCCEEDED),),
        )
    with pytest.raises(ValueError, match="material identity"):
        ArchiveProviderOutcome(
            ARCHIVE_PROVIDER_PROFILE,
            outcome.result,
            (
                replace(
                    outcome.executions[0],
                    input_identity="archive-7zip-provider-input/v1:" + "f" * 64,
                ),
            ),
        )


def test_runner_exception_is_path_free_failed_provenance() -> None:
    class _ExplodingRunner:
        def run(self, request: ArchiveContainerRequest, **kwargs: Any) -> ArchiveContainerRunResult:
            del request, kwargs
            raise RuntimeError("C:/private/never-render-this")

    outcome = _inspect(
        _ExplodingRunner(),
        _request(),
        signature=_signature("ZIP"),  # type: ignore[arg-type]
        archive_observation_id="archive-observation-1",
        archive_full_sha256="a" * 64,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(_request()),
        cancellation=None,
        now=_clock(),
    )
    assert outcome.result is not None
    assert outcome.result.listing_status.value == "TOOL_FAILED"
    assert outcome.executions[0].status is ToolExecutionStatus.FAILED
    assert "private" not in repr(outcome)


@pytest.mark.parametrize("cancel_step", [0, 1])
def test_cancellation_has_provenance_but_no_terminal_snapshot(cancel_step: int) -> None:
    lock = json.loads(FORMAT_LOCK.read_text(encoding="utf-8"))
    capability = next(
        item
        for item in lock["capabilities"]
        if item["storage_family"] == "ZIP" and item["case_kind"] == "PLAINTEXT_REGULAR"
    )
    steps = [(ArchiveContainerRunStatus.COMPLETED, (_stream(capability),))]
    if cancel_step == 0:
        steps[0] = (ArchiveContainerRunStatus.CANCELLED, ())
    else:
        steps.append((ArchiveContainerRunStatus.CANCELLED, ()))
    runner = _FakeRunner(steps)
    outcome = _inspect(
        runner,
        _request(),
        signature=_signature("ZIP"),  # type: ignore[arg-type]
        archive_observation_id="archive-observation-1",
        archive_full_sha256="a" * 64,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(_request()),
        cancellation=None,
        now=_clock(),
    )
    assert outcome.result is None
    assert outcome.executions[-1].status is ToolExecutionStatus.CANCELLED
    assert len(outcome.executions) == cancel_step + 1
    with pytest.raises(ValueError, match="provider identity"):
        ArchiveProviderOutcome(
            ARCHIVE_PROVIDER_PROFILE,
            executions=tuple(
                replace(item, input_identity="C:/private/archive") for item in outcome.executions
            ),
        )


def test_encryption_skips_integrity_and_mixed_is_valid() -> None:
    lock = json.loads(FORMAT_LOCK.read_text(encoding="utf-8"))
    for case_kind, expected in (
        ("ALL_ENCRYPTED", ArchiveEncryptionStatus.DATA_ENCRYPTED),
        ("MIXED", ArchiveEncryptionStatus.MIXED),
    ):
        capability = next(
            item
            for item in lock["capabilities"]
            if item["storage_family"] == "ZIP" and item["case_kind"] == case_kind
        )
        outcome, runner = _inspect_capability(capability)
        assert outcome.result is not None
        assert outcome.result.encryption_status is expected
        assert outcome.result.integrity_status is ArchiveIntegrityStatus.NOT_TESTED
        assert len(runner.requests) == 1
        with pytest.raises(ValueError, match="encrypted"):
            replace(
                outcome.result,
                member_count=0 if case_kind == "ALL_ENCRYPTED" else 1,
            )


def test_public_result_rejects_unstructured_integrity_cause() -> None:
    lock = json.loads(FORMAT_LOCK.read_text(encoding="utf-8"))
    capability = next(
        item
        for item in lock["capabilities"]
        if item["storage_family"] == "ZIP" and item["case_kind"] == "PLAINTEXT_REGULAR"
    )
    outcome, _runner = _inspect_capability(capability)
    assert outcome.result is not None
    with pytest.raises(ValueError, match="not authorized"):
        replace(
            outcome.result,
            integrity_execution=replace(
                outcome.result.integrity_execution,
                status=ArchiveIntegrityStatus.CORRUPT,
            ),
        )


def test_public_authority_and_input_identity_are_closed() -> None:
    with pytest.raises(ValueError):
        ArchiveSevenZipProvider(object())  # type: ignore[arg-type]
    identity = build_archive_provider_input_identity(
        archive_full_sha256="a" * 64,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(_request()),
    )
    assert identity.startswith("archive-7zip-provider-input/v1:")
    assert "a" * 64 not in identity


@pytest.mark.parametrize(
    ("runner_status", "parser_status", "expected"),
    [
        (
            ArchiveContainerRunStatus.TIMED_OUT,
            ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED,
            "TIMED_OUT",
        ),
        (
            ArchiveContainerRunStatus.LIMIT_EXCEEDED,
            ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED,
            "LIMIT_EXCEEDED",
        ),
        (
            ArchiveContainerRunStatus.TIMED_OUT,
            ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED,
            "TIMED_OUT",
        ),
        (
            ArchiveContainerRunStatus.POLICY_REJECTED,
            ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED,
            "LIMIT_EXCEEDED",
        ),
        (
            ArchiveContainerRunStatus.POLICY_REJECTED,
            ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED,
            "TOOL_FAILED",
        ),
    ],
)
def test_runner_status_precedes_parser_except_consumer_rejection(
    runner_status: ArchiveContainerRunStatus,
    parser_status: ArchiveSevenZipSltParseStatus,
    expected: str,
) -> None:
    assert _listing_status(_run(runner_status), parser_status, True).value == expected


@pytest.mark.parametrize(
    ("observation_id", "archive_sha256", "group_fingerprint"),
    [
        ("C:/private/observation", "a" * 64, None),
        ("archive-observation-1", "c" * 64, None),
        ("archive-observation-1", "a" * 64, "d" * 64),
    ],
)
def test_material_and_observation_preflight_fail_before_runner(
    observation_id: str,
    archive_sha256: str,
    group_fingerprint: str | None,
) -> None:
    runner = _FakeRunner([])
    request = _request()
    with pytest.raises(ValueError):
        _inspect(
            runner,
            request,
            signature=_signature("ZIP"),  # type: ignore[arg-type]
            archive_observation_id=observation_id,
            archive_full_sha256=archive_sha256,
            volume_group_fingerprint=(
                group_fingerprint or build_archive_volume_group_fingerprint(request)
            ),
            cancellation=None,
            now=_clock(),
        )
    assert runner.requests == []
