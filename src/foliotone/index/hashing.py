"""Bounded-memory generic file fingerprints for incremental indexing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from sqlalchemy import Engine

from foliotone.core import EntityId, EntityKind, FileObservation, Fingerprint
from foliotone.persistence import repository

DEFAULT_CHUNK_BYTES = 4 * 1024 * 1024
QUICK_SAMPLE_BYTES = 64 * 1024


class HashMode(StrEnum):
    NONE = "NONE"
    QUICK = "QUICK"
    FULL = "FULL"


@dataclass(frozen=True, slots=True)
class HashValues:
    """Generic fingerprints calculated for one exact FileObservation."""

    quick: str | None = None
    sha256: str | None = None


def quick_file_fingerprint(path: Path, sample_bytes: int = QUICK_SAMPLE_BYTES) -> str:
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
                digest.update(chunk)
        else:
            digest.update(stream.read(sample_bytes))
            stream.seek(size - sample_bytes)
            digest.update(stream.read(sample_bytes))
    return digest.hexdigest()


def stream_sha256(path: Path, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> str:
    """Calculate full SHA-256 without loading the file into memory."""
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be positive")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def calculate_hashes(path: Path, mode: HashMode) -> HashValues:
    """Apply the configured staged hashing policy."""
    if mode is HashMode.NONE:
        return HashValues()
    quick = quick_file_fingerprint(path)
    if mode is HashMode.QUICK:
        return HashValues(quick=quick)
    return HashValues(quick=quick, sha256=stream_sha256(path))


class FingerprintWriter:
    """Persist generic file fingerprints against an exact observation identity."""

    def __init__(self, engine: Engine) -> None:
        self._repository = repository(engine, Fingerprint)

    def calculate_and_save(
        self,
        observation: FileObservation,
        physical_path: Path,
        mode: HashMode,
        created_at: datetime,
    ) -> tuple[Fingerprint, ...]:
        values = calculate_hashes(physical_path, mode)
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
        for fingerprint in fingerprints:
            self._repository.save(fingerprint)
        return tuple(fingerprints)
