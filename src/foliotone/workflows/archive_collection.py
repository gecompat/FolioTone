"""Bounded, restartable execution of one sealed archive collection plan."""

from __future__ import annotations

import hashlib
import os
import stat
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Protocol

from foliotone.archive.container_sandbox import (
    ARCHIVE_WRAPPER_CONTAINER_RUNNER_PROFILE,
    ArchiveContainerRequest,
    ArchiveVolumeSource,
)
from foliotone.archive.process_runner import CancellationProbe
from foliotone.archive.provider import (
    ARCHIVE_PROVIDER_PROFILE,
    ARCHIVE_WRAPPER_PROVIDER_PROFILE,
    ArchiveProviderOutcome,
    ArchiveSevenZipProvider,
    _command_identity,
    build_archive_volume_group_fingerprint,
)
from foliotone.archive.safety_policy import ARCHIVE_SAFETY_POLICY_PROFILE
from foliotone.archive.sevenzip import (
    ARCHIVE_7ZIP_ADAPTER_VERSION,
    ARCHIVE_7ZIP_PROVIDER_ID,
    ARCHIVE_7ZIP_TOOL_VERSION,
    ARCHIVE_IMAGE_REFERENCE,
    ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
    build_7zzs_listing_command,
    build_7zzs_tar_stdin_integrity_command,
    build_7zzs_tar_stdin_listing_command,
    build_7zzs_wrapper_decode_command,
)
from foliotone.archive.sevenzip_slt import (
    ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE,
    ArchiveSevenZipFormatCase,
    ArchiveSevenZipSltParseStatus,
)
from foliotone.archive.signatures import (
    MAX_ARCHIVE_HEADER_BYTES,
    ArchiveListingStatus,
    ArchiveOuterCompressionKind,
    ArchiveSignatureObservationV2,
    observe_archive_signature_v2,
)
from foliotone.archive.workflow import (
    ARCHIVE_EXTRACTION_PROFILE,
    ARCHIVE_LISTING_PROFILE,
    NONE_SECRET_VERSION,
    ArchiveReuseKey,
)
from foliotone.core import (
    ArchiveCollectionDisposition,
    ArchiveCollectionItemStatus,
    ArchiveCollectionRun,
    ArchiveCollectionRunStatus,
    EntityId,
)
from foliotone.persistence.archive import (
    ArchiveEvidenceCompatibility,
    ArchiveEvidenceSnapshot,
    ArchiveEvidenceSource,
    PersistedArchiveEvidence,
    SQLiteArchiveEvidenceStore,
)
from foliotone.persistence.archive_collection import (
    ArchiveCollectionStoreError,
    ArchiveCollectionWorkItem,
    SQLiteArchiveCollectionStore,
    _ArchiveCollectionResolvedSource,
)

_READ_CHUNK_BYTES = 1024 * 1024
_DEFAULT_LEASE_DURATION = timedelta(minutes=30)
_DEFAULT_HEARTBEAT_INTERVAL = timedelta(seconds=30)
_WRAPPER_IMAGE_REFERENCE = (
    f"{ARCHIVE_IMAGE_REFERENCE}@"
    "sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287"
)


class ArchiveCollectionExecutionError(RuntimeError):
    """The invocation lost authority or could not be completed safely."""


class _Provider(Protocol):
    def inspect(
        self,
        request: ArchiveContainerRequest,
        *,
        signature: ArchiveSignatureObservationV2,
        archive_observation_id: str,
        archive_full_sha256: str,
        volume_group_fingerprint: str,
        cancellation: CancellationProbe | None = None,
    ) -> ArchiveProviderOutcome: ...


@dataclass(frozen=True, slots=True)
class _ValidatedItemMaterial:
    request: ArchiveContainerRequest
    signature: ArchiveSignatureObservationV2
    reuse_key: ArchiveReuseKey
    sources: tuple[ArchiveEvidenceSource, ...]


@dataclass(frozen=True, slots=True)
class _PreparedItemResult:
    observation_id: EntityId | None = None
    reused: PersistedArchiveEvidence | None = None
    snapshot: ArchiveEvidenceSnapshot | None = None
    cancelled: bool = False

    def __post_init__(self) -> None:
        variants = sum(
            value is not None for value in (self.reused, self.snapshot)
        ) + self.cancelled
        if variants != 1:
            raise ValueError("archive collection prepared result is invalid")
        expected = (
            self.reused.id
            if self.reused is not None
            else self.snapshot.id
            if self.snapshot is not None
            else None
        )
        if self.observation_id != expected:
            raise ValueError("archive collection prepared result identity is invalid")


class _CombinedCancellation:
    def __init__(self, external: CancellationProbe | None) -> None:
        self._external = external
        self._internal = threading.Event()

    def is_set(self) -> bool:
        return self._internal.is_set() or (
            self._external is not None and self._external.is_set()
        )

    def stop(self) -> None:
        self._internal.set()


class _Cancelled(RuntimeError):
    pass


def execute_archive_collection_invocation(
    collection_store: SQLiteArchiveCollectionStore,
    evidence_store: SQLiteArchiveEvidenceStore,
    provider: ArchiveSevenZipProvider,
    run_id: EntityId,
    lease_token: str,
    source_root: Path,
    *,
    max_items: int,
    now: Callable[[], datetime],
    cancellation: CancellationProbe | None = None,
    lease_duration: timedelta = _DEFAULT_LEASE_DURATION,
    heartbeat_interval: timedelta = _DEFAULT_HEARTBEAT_INTERVAL,
) -> ArchiveCollectionRun:
    """Execute at most ``max_items`` through the fixed production provider."""

    if type(collection_store) is not SQLiteArchiveCollectionStore:
        raise ValueError("archive collection store is invalid")
    if type(evidence_store) is not SQLiteArchiveEvidenceStore:
        raise ValueError("archive evidence store is invalid")
    if type(provider) is not ArchiveSevenZipProvider:
        raise ValueError("archive provider must use the fixed production adapter")
    return _execute_archive_collection_invocation(
        collection_store,
        evidence_store,
        provider,
        run_id,
        lease_token,
        source_root,
        max_items=max_items,
        now=now,
        cancellation=cancellation,
        lease_duration=lease_duration,
        heartbeat_interval=heartbeat_interval,
    )


def _execute_archive_collection_invocation(
    collection_store: SQLiteArchiveCollectionStore,
    evidence_store: SQLiteArchiveEvidenceStore,
    provider: _Provider,
    run_id: EntityId,
    lease_token: str,
    source_root: Path,
    *,
    max_items: int,
    now: Callable[[], datetime],
    cancellation: CancellationProbe | None,
    lease_duration: timedelta,
    heartbeat_interval: timedelta,
) -> ArchiveCollectionRun:
    if not isinstance(run_id, EntityId) or not isinstance(lease_token, str) or not lease_token:
        raise ValueError("archive collection invocation identity is invalid")
    if not isinstance(source_root, Path) or not source_root.is_absolute():
        raise ValueError("archive collection source root is invalid")
    if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 1:
        raise ValueError("archive collection max-items bound is invalid")
    if lease_duration <= timedelta(0) or not timedelta(0) < heartbeat_interval <= timedelta(
        seconds=60
    ):
        raise ValueError("archive collection timing bounds are invalid")
    run = collection_store.get_run(run_id)
    if run is None or run.status is not ArchiveCollectionRunStatus.RUNNING:
        raise ArchiveCollectionExecutionError("archive collection run is not executable")
    combined = _CombinedCancellation(cancellation)
    processed = 0
    fence_lost = False
    try:
        while processed < max_items and not combined.is_set():
            heartbeat_at = now()
            run = collection_store.heartbeat(
                run_id,
                lease_token,
                heartbeat_at=heartbeat_at,
                lease_expires_at=heartbeat_at + lease_duration,
            )
            claim_limit = min(max_items - processed, 2 * run.worker_count, 4)
            claimed = collection_store.claim_pending(
                run_id, lease_token, limit=claim_limit, started_at=now()
            )
            if not claimed:
                break
            for work_item in claimed:
                if combined.is_set():
                    break
                try:
                    prepared = _prepare_with_heartbeat(
                        collection_store,
                        evidence_store,
                        provider,
                        run,
                        work_item,
                        source_root,
                        lease_token,
                        combined,
                        now,
                        lease_duration,
                        heartbeat_interval,
                    )
                except ArchiveCollectionStoreError:
                    fence_lost = True
                    combined.stop()
                    raise
                except Exception:
                    collection_store.complete_item(
                        work_item.item,
                        lease_token,
                        status=ArchiveCollectionItemStatus.ERROR,
                        completed_at=now(),
                        archive_observation_id=None,
                        disposition=None,
                        error_code="ORCHESTRATION_ERROR",
                    )
                    processed += 1
                    _heartbeat(collection_store, run_id, lease_token, now, lease_duration)
                    continue
                if prepared.cancelled:
                    combined.stop()
                    break
                if prepared.reused is not None:
                    persisted = prepared.reused
                    disposition = ArchiveCollectionDisposition.REUSED
                else:
                    assert prepared.snapshot is not None
                    write_lease = collection_store.owned_write_lease(
                        run_id, lease_token
                    )
                    try:
                        persisted = evidence_store.create_or_get(
                            prepared.snapshot,
                            write_lease,
                            now(),
                        )
                    except Exception:
                        collection_store.complete_item(
                            work_item.item,
                            lease_token,
                            status=ArchiveCollectionItemStatus.ERROR,
                            completed_at=now(),
                            archive_observation_id=None,
                            disposition=None,
                            error_code="PERSISTENCE_ERROR",
                        )
                        processed += 1
                        _heartbeat(
                            collection_store,
                            run_id,
                            lease_token,
                            now,
                            lease_duration,
                        )
                        continue
                    disposition = ArchiveCollectionDisposition.EXECUTED
                status = (
                    ArchiveCollectionItemStatus.SUCCEEDED
                    if persisted.listing_status == ArchiveListingStatus.LISTED.value
                    else ArchiveCollectionItemStatus.FAILED
                )
                collection_store.complete_item(
                    work_item.item,
                    lease_token,
                    status=status,
                    completed_at=now(),
                    archive_observation_id=persisted.id,
                    disposition=disposition,
                    error_code=(
                        None
                        if status is ArchiveCollectionItemStatus.SUCCEEDED
                        else f"ARCHIVE_{persisted.listing_status}"
                    ),
                )
                processed += 1
                _heartbeat(collection_store, run_id, lease_token, now, lease_duration)
        _heartbeat(collection_store, run_id, lease_token, now, lease_duration)
        return collection_store.finish_invocation(
            run_id, lease_token, finished_at=now()
        )
    except ArchiveCollectionStoreError:
        fence_lost = True
        combined.stop()
        raise ArchiveCollectionExecutionError(
            "archive collection invocation lost its write authority"
        ) from None
    finally:
        if fence_lost:
            combined.stop()


def _prepare_with_heartbeat(
    collection_store: SQLiteArchiveCollectionStore,
    evidence_store: SQLiteArchiveEvidenceStore,
    provider: _Provider,
    run: ArchiveCollectionRun,
    work_item: ArchiveCollectionWorkItem,
    source_root: Path,
    lease_token: str,
    cancellation: _CombinedCancellation,
    now: Callable[[], datetime],
    lease_duration: timedelta,
    heartbeat_interval: timedelta,
) -> _PreparedItemResult:
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="archive-collection") as pool:
        future: Future[_PreparedItemResult] = pool.submit(
            _prepare_item,
            collection_store,
            evidence_store,
            provider,
            run,
            work_item,
            source_root,
            cancellation,
            now,
        )
        while True:
            try:
                return future.result(timeout=heartbeat_interval.total_seconds())
            except TimeoutError:
                try:
                    _heartbeat(
                        collection_store, run.id, lease_token, now, lease_duration
                    )
                except Exception:
                    cancellation.stop()
                    raise ArchiveCollectionStoreError(
                        "archive collection heartbeat failed"
                    ) from None


def _prepare_item(
    collection_store: SQLiteArchiveCollectionStore,
    evidence_store: SQLiteArchiveEvidenceStore,
    provider: _Provider,
    run: ArchiveCollectionRun,
    work_item: ArchiveCollectionWorkItem,
    source_root: Path,
    cancellation: _CombinedCancellation,
    now: Callable[[], datetime],
) -> _PreparedItemResult:
    if cancellation.is_set():
        return _PreparedItemResult(cancelled=True)
    try:
        try:
            resolved = collection_store._resolve_work_item_sources(work_item)
        except ArchiveCollectionStoreError:
            raise ArchiveCollectionExecutionError(
                "archive collection source lineage is invalid"
            ) from None
        material = _revalidate_material(
            resolved, work_item, source_root, cancellation
        )
    except _Cancelled:
        return _PreparedItemResult(cancelled=True)
    reused = _find_reuse(evidence_store, material, run)
    if reused is not None:
        return _PreparedItemResult(reused.id, reused=reused)
    observation_id = EntityId.new()
    outcome = provider.inspect(
        material.request,
        signature=material.signature,
        archive_observation_id=str(observation_id),
        archive_full_sha256=material.reuse_key.archive_full_sha256,
        volume_group_fingerprint=material.reuse_key.volume_group_fingerprint,
        cancellation=cancellation,
    )
    if outcome.result is None:
        return _PreparedItemResult(cancelled=True)
    snapshot = ArchiveEvidenceSnapshot(
        observation_id,
        run.scan_root_id,
        run.source_scan_run_id,
        now(),
        material.signature,
        outcome,
        material.sources,
    )
    return _PreparedItemResult(observation_id, snapshot=snapshot)


def _revalidate_material(
    resolved: tuple[_ArchiveCollectionResolvedSource, ...],
    work_item: ArchiveCollectionWorkItem,
    source_root: Path,
    cancellation: CancellationProbe,
) -> _ValidatedItemMaterial:
    root = source_root.resolve(strict=True)
    volumes: list[ArchiveVolumeSource] = []
    evidence: list[ArchiveEvidenceSource] = []
    primary_prefix = b""
    primary_name = ""
    for value in resolved:
        path = root.joinpath(*PurePosixPath(value.relative_path).parts)
        resolved_path = path.resolve(strict=True)
        try:
            resolved_path.relative_to(root)
        except ValueError:
            raise ArchiveCollectionExecutionError(
                "archive collection source revalidation failed"
            ) from None
        digest, prefix = _hash_source(
            resolved_path, value.source.size_bytes, cancellation
        )
        if digest != value.source.full_sha256:
            raise ArchiveCollectionExecutionError(
                "archive collection source revalidation failed"
            )
        volumes.append(
            ArchiveVolumeSource(
                resolved_path,
                value.source.size_bytes,
                digest,
                value.source.staging_name,
            )
        )
        evidence.append(
            ArchiveEvidenceSource(
                value.source.file_observation_id,
                digest,
                value.source.size_bytes,
                value.source.staging_name,
            )
        )
        if value.source.staging_name == "archive":
            primary_prefix = prefix
            primary_name = PurePosixPath(value.relative_path).name
    request = ArchiveContainerRequest(
        tuple(volumes), build_7zzs_listing_command(), (root,)
    )
    signature = observe_archive_signature_v2(primary_name, primary_prefix)
    if signature != work_item.item.signature:
        raise ArchiveCollectionExecutionError(
            "archive collection signature revalidation failed"
        )
    fingerprint = build_archive_volume_group_fingerprint(request)
    primary = next(item for item in volumes if item.staging_name == "archive")
    return _ValidatedItemMaterial(
        request,
        signature,
        ArchiveReuseKey(
            primary.full_sha256,
            fingerprint,
            ARCHIVE_7ZIP_PROVIDER_ID,
            ARCHIVE_7ZIP_TOOL_VERSION,
            ARCHIVE_7ZIP_ADAPTER_VERSION,
            ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE,
            ARCHIVE_LISTING_PROFILE,
            ARCHIVE_EXTRACTION_PROFILE,
            ARCHIVE_SAFETY_POLICY_PROFILE,
            NONE_SECRET_VERSION,
        ),
        tuple(evidence),
    )


def _hash_source(
    path: Path, expected_size: int, cancellation: CancellationProbe
) -> tuple[str, bytes]:
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_size != expected_size:
        raise ArchiveCollectionExecutionError(
            "archive collection source revalidation failed"
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    digest = hashlib.sha256()
    prefix = bytearray()
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size != expected_size:
            raise ArchiveCollectionExecutionError(
                "archive collection source revalidation failed"
            )
        while True:
            if cancellation.is_set():
                raise _Cancelled
            chunk = os.read(descriptor, _READ_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            if len(prefix) < MAX_ARCHIVE_HEADER_BYTES:
                prefix.extend(chunk[: MAX_ARCHIVE_HEADER_BYTES - len(prefix)])
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final = path.stat(follow_symlinks=False)
    if (
        _stat_identity(before) != _stat_identity(opened)
        or _stat_identity(opened) != _stat_identity(after)
        or _stat_identity(after) != _stat_identity(final)
    ):
        raise ArchiveCollectionExecutionError(
            "archive collection source changed during revalidation"
        )
    return digest.hexdigest(), bytes(prefix)


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _find_reuse(
    store: SQLiteArchiveEvidenceStore,
    material: _ValidatedItemMaterial,
    run: ArchiveCollectionRun,
) -> PersistedArchiveEvidence | None:
    matches: dict[EntityId, PersistedArchiveEvidence] = {}
    for case in ArchiveSevenZipFormatCase:
        compatibility = _compatibility(material.signature, case)
        value = store.find_listing_reuse(
            material.reuse_key,
            compatibility,
            scan_root_id=run.scan_root_id,
            source_scan_run_id=run.source_scan_run_id,
            sources=material.sources,
        )
        if value is not None:
            matches[value.id] = value
    if len(matches) > 1:
        raise ArchiveCollectionExecutionError(
            "archive collection reuse evidence is ambiguous"
        )
    return next(iter(matches.values()), None)


def _compatibility(
    signature: ArchiveSignatureObservationV2, case: ArchiveSevenZipFormatCase
) -> ArchiveEvidenceCompatibility:
    if signature.outer_compression_kind is ArchiveOuterCompressionKind.NONE:
        return ArchiveEvidenceCompatibility(
            signature,
            ARCHIVE_PROVIDER_PROFILE,
            ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
            ArchiveSevenZipSltParseStatus.PARSED,
            case.value,
        )
    return ArchiveEvidenceCompatibility(
        signature,
        ARCHIVE_WRAPPER_PROVIDER_PROFILE,
        ARCHIVE_WRAPPER_CONTAINER_RUNNER_PROFILE,
        ArchiveSevenZipSltParseStatus.PARSED,
        case.value,
        _WRAPPER_IMAGE_REFERENCE,
        _command_identity(build_7zzs_wrapper_decode_command()),
        _command_identity(build_7zzs_tar_stdin_listing_command()),
        _command_identity(build_7zzs_tar_stdin_integrity_command()),
    )


def _heartbeat(
    store: SQLiteArchiveCollectionStore,
    run_id: EntityId,
    lease_token: str,
    now: Callable[[], datetime],
    lease_duration: timedelta,
) -> None:
    heartbeat_at = now()
    store.heartbeat(
        run_id,
        lease_token,
        heartbeat_at=heartbeat_at,
        lease_expires_at=heartbeat_at + lease_duration,
    )
