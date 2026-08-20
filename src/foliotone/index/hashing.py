"""Bounded-memory generic file fingerprints for incremental indexing."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from threading import Event

from sqlalchemy import Engine, and_, func, insert, literal_column, select

from foliotone.core import EntityId, EntityKind, FileObservation, Fingerprint
from foliotone.persistence import schema
from foliotone.persistence.codecs import codec_for
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    SQLiteScanRootWriteLeaseStore,
)

DEFAULT_CHUNK_BYTES = 4 * 1024 * 1024
QUICK_SAMPLE_BYTES = 64 * 1024


class _HashingCancelled(RuntimeError):
    """Stop an in-process scan hash worker without exposing partial evidence."""


class HashMode(StrEnum):
    NONE = "NONE"
    QUICK = "QUICK"
    FULL = "FULL"


QUICK_FILE_PROFILE = ("QUICK_FILE", "sha256-head-tail", "1")
FULL_FILE_PROFILE = ("FILE_SHA256", "sha256", "1")
_FILE_HASH_PROFILES = (QUICK_FILE_PROFILE, FULL_FILE_PROFILE)


@dataclass(frozen=True, slots=True)
class HashValues:
    """Generic fingerprints calculated for one exact FileObservation."""

    quick: str | None = None
    sha256: str | None = None


def quick_file_fingerprint(
    path: Path,
    sample_bytes: int = QUICK_SAMPLE_BYTES,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> str:
    """Hash size plus bounded head/tail samples; small files are hashed completely."""
    if sample_bytes <= 0:
        raise ValueError("sample_bytes must be positive")
    size = path.stat().st_size
    digest = hashlib.sha256()
    digest.update(b"foliotone-quick-v1\0")
    digest.update(size.to_bytes(16, byteorder="big", signed=False))

    with path.open("rb") as stream:
        if size <= sample_bytes * 2:
            while chunk := stream.read(sample_bytes):
                _raise_if_cancelled(cancelled)
                digest.update(chunk)
        else:
            _raise_if_cancelled(cancelled)
            digest.update(stream.read(sample_bytes))
            stream.seek(size - sample_bytes)
            _raise_if_cancelled(cancelled)
            digest.update(stream.read(sample_bytes))
    return digest.hexdigest()


def stream_sha256(
    path: Path,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> str:
    """Calculate full SHA-256 without loading the file into memory."""
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be positive")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            _raise_if_cancelled(cancelled)
            digest.update(chunk)
    return digest.hexdigest()


def calculate_hashes(
    path: Path,
    mode: HashMode,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> HashValues:
    """Apply the configured staged hashing policy."""
    if mode is HashMode.NONE:
        return HashValues()
    quick = quick_file_fingerprint(path, cancelled=cancelled)
    if mode is HashMode.QUICK:
        return HashValues(quick=quick)
    return HashValues(quick=quick, sha256=stream_sha256(path, cancelled=cancelled))


def _raise_if_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise _HashingCancelled("file hashing was cancelled")


class FingerprintWriter:
    """Persist generic file fingerprints against an exact observation identity."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._codec = codec_for(Fingerprint)
        self._write_leases = SQLiteScanRootWriteLeaseStore(engine)
        self._cancelled = Event()

    def cancel_pending(self) -> None:
        """Request cooperative termination of active in-process hash reads."""

        self._cancelled.set()

    def reset_cancellation(self) -> None:
        """Prepare this writer for a new scan after all prior workers stopped."""

        self._cancelled.clear()

    def calculate(
        self,
        observation: FileObservation,
        physical_path: Path,
        mode: HashMode,
        created_at: datetime,
    ) -> tuple[Fingerprint, ...]:
        """Calculate generic fingerprints without opening a persistence transaction."""

        values = calculate_hashes(
            physical_path,
            mode,
            cancelled=self._cancelled.is_set,
        )
        fingerprints: list[Fingerprint] = []
        if values.quick is not None:
            fingerprints.append(
                Fingerprint(
                    id=EntityId.new(),
                    target_kind=EntityKind.FILE_OBSERVATION,
                    target_id=observation.id,
                    kind="QUICK_FILE",
                    algorithm="sha256-head-tail",
                    algorithm_version="1",
                    value=values.quick,
                    created_at=created_at,
                )
            )
        if values.sha256 is not None:
            fingerprints.append(
                Fingerprint(
                    id=EntityId.new(),
                    target_kind=EntityKind.FILE_OBSERVATION,
                    target_id=observation.id,
                    kind="FILE_SHA256",
                    algorithm="sha256",
                    algorithm_version="1",
                    value=values.sha256,
                    created_at=created_at,
                )
            )
        return tuple(fingerprints)

    def save_many(
        self,
        fingerprints: Sequence[Fingerprint],
        *,
        write_lease: OwnedScanRootWriteLease,
        committed_at: datetime,
    ) -> None:
        """Persist one bounded fingerprint batch in a single transaction."""

        if not fingerprints:
            return
        rows = [dict(self._codec.encode(fingerprint)) for fingerprint in fingerprints]
        with self._engine.begin() as connection:
            self._write_leases.fence(connection, write_lease, committed_at)
            connection.execute(insert(self._codec.table), rows)

    def calculate_full(
        self,
        observation: FileObservation,
        physical_path: Path,
        created_at: datetime,
    ) -> Fingerprint:
        """Calculate only the full-file profile for a prefiltered observation."""

        return Fingerprint(
            id=EntityId.new(),
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=observation.id,
            kind=FULL_FILE_PROFILE[0],
            algorithm=FULL_FILE_PROFILE[1],
            algorithm_version=FULL_FILE_PROFILE[2],
            value=stream_sha256(physical_path),
            created_at=created_at,
        )

    def reuse_latest(
        self,
        observations: Sequence[FileObservation],
        mode: HashMode,
        created_at: datetime,
    ) -> dict[EntityId, tuple[Fingerprint, ...]]:
        """Project complete latest file hashes onto unchanged observations."""

        if not observations or mode is HashMode.NONE:
            return {}
        required_profiles = (
            (QUICK_FILE_PROFILE,)
            if mode is HashMode.QUICK
            else (QUICK_FILE_PROFILE, FULL_FILE_PROFILE)
        )
        observation_table = schema.file_observations
        fingerprint_table = schema.fingerprints
        current_ids = tuple(str(observation.id) for observation in observations)
        file_ids = tuple(str(observation.file_id) for observation in observations)
        ranked_observations = (
            select(
                observation_table.c.id,
                observation_table.c.file_id,
                func.row_number()
                .over(
                    partition_by=observation_table.c.file_id,
                    order_by=(
                        observation_table.c.observed_at.desc(),
                        literal_column("file_observations.rowid").desc(),
                    ),
                )
                .label("observation_rank"),
            )
            .where(
                observation_table.c.file_id.in_(file_ids),
                ~observation_table.c.id.in_(current_ids),
            )
            .subquery()
        )
        statement = (
            select(
                ranked_observations.c.file_id,
                fingerprint_table.c.kind,
                fingerprint_table.c.algorithm,
                fingerprint_table.c.algorithm_version,
                fingerprint_table.c.value,
            )
            .join(
                fingerprint_table,
                and_(
                    fingerprint_table.c.target_kind
                    == EntityKind.FILE_OBSERVATION.value,
                    fingerprint_table.c.target_id == ranked_observations.c.id,
                ),
            )
            .where(
                ranked_observations.c.observation_rank == 1,
                fingerprint_table.c.kind.in_(
                    tuple(profile[0] for profile in _FILE_HASH_PROFILES)
                ),
            )
            .order_by(ranked_observations.c.file_id, fingerprint_table.c.id)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()

        available: dict[str, dict[tuple[str, str, str], str]] = {}
        for row in rows:
            profile = (
                str(row["kind"]),
                str(row["algorithm"]),
                str(row["algorithm_version"]),
            )
            if profile not in _FILE_HASH_PROFILES:
                continue
            available.setdefault(str(row["file_id"]), {}).setdefault(
                profile,
                str(row["value"]),
            )

        reused: dict[EntityId, tuple[Fingerprint, ...]] = {}
        for observation in observations:
            profiles = available.get(str(observation.file_id), {})
            if not all(profile in profiles for profile in required_profiles):
                continue
            reused[observation.id] = tuple(
                Fingerprint(
                    id=EntityId.new(),
                    target_kind=EntityKind.FILE_OBSERVATION,
                    target_id=observation.id,
                    kind=profile[0],
                    algorithm=profile[1],
                    algorithm_version=profile[2],
                    value=profiles[profile],
                    created_at=created_at,
                )
                for profile in _FILE_HASH_PROFILES
                if profile in profiles
            )
        return reused

    def calculate_and_save(
        self,
        observation: FileObservation,
        physical_path: Path,
        mode: HashMode,
        created_at: datetime,
        *,
        write_lease: OwnedScanRootWriteLease,
    ) -> tuple[Fingerprint, ...]:
        fingerprints = self.calculate(observation, physical_path, mode, created_at)
        self.save_many(
            fingerprints,
            write_lease=write_lease,
            committed_at=created_at,
        )
        return fingerprints
