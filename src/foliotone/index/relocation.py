"""Fingerprint-blocked move/rename candidate detection."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import Engine, and_, select

from foliotone.core import (
    EntityId,
    EntityKind,
    FileChangeState,
    FileRelocationCandidate,
    RelocationCandidateKind,
    ScanRun,
)
from foliotone.persistence import repository, schema, w2_schema

_SUPPORTED_FINGERPRINTS = frozenset({"QUICK_FILE", "FILE_SHA256"})
_FINGERPRINT_PRIORITY = {"QUICK_FILE": 1, "FILE_SHA256": 2}


@dataclass(frozen=True, slots=True)
class _FingerprintMatch:
    source_file_id: str
    target_file_id: str
    source_relative_path: str
    target_relative_path: str
    source_fingerprint_id: str
    target_fingerprint_id: str
    fingerprint_kind: str
    fingerprint_algorithm: str
    fingerprint_algorithm_version: str
    fingerprint_value: str

    @property
    def evidence_key(self) -> tuple[str, str, str, str]:
        return (
            self.fingerprint_kind,
            self.fingerprint_algorithm,
            self.fingerprint_algorithm_version,
            self.fingerprint_value,
        )

    @property
    def pair_key(self) -> tuple[str, str]:
        return (self.source_file_id, self.target_file_id)


class RelocationCandidateDetector:
    """Create candidates without changing FileRecord identity or scan change states."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._repository = repository(engine, FileRelocationCandidate)

    def detect(
        self,
        run: ScanRun,
        created_at: datetime,
    ) -> tuple[FileRelocationCandidate, ...]:
        """Persist unambiguous fingerprint-blocked candidates for one completed scan body."""
        matches = self._load_matches(run)
        unambiguous = self._unambiguous_matches(matches)
        best_by_pair: dict[tuple[str, str], _FingerprintMatch] = {}
        for match in unambiguous:
            current = best_by_pair.get(match.pair_key)
            if current is None or _priority(match) > _priority(current):
                best_by_pair[match.pair_key] = match

        candidates = tuple(
            self._to_candidate(match, run, created_at)
            for match in sorted(
                best_by_pair.values(),
                key=lambda item: (
                    item.source_relative_path,
                    item.target_relative_path,
                    item.fingerprint_kind,
                ),
            )
        )
        for candidate in candidates:
            self._repository.save(candidate)
        return candidates

    def _load_matches(self, run: ScanRun) -> tuple[_FingerprintMatch, ...]:
        new_event = w2_schema.file_scan_events.alias("new_event")
        absent_event = w2_schema.file_scan_events.alias("absent_event")
        source_record = schema.file_records.alias("source_record")
        target_record = schema.file_records.alias("target_record")
        source_observation = schema.file_observations.alias("source_observation")
        target_observation = schema.file_observations.alias("target_observation")
        source_fingerprint = schema.fingerprints.alias("source_fingerprint")
        target_fingerprint = schema.fingerprints.alias("target_fingerprint")

        latest_source_observation_id = (
            select(schema.file_observations.c.id)
            .where(schema.file_observations.c.file_id == absent_event.c.file_id)
            .order_by(
                schema.file_observations.c.observed_at.desc(),
                schema.file_observations.c.id.desc(),
            )
            .limit(1)
            .correlate(absent_event)
            .scalar_subquery()
        )

        statement = (
            select(
                source_record.c.id.label("source_file_id"),
                target_record.c.id.label("target_file_id"),
                source_record.c.relative_path.label("source_relative_path"),
                target_record.c.relative_path.label("target_relative_path"),
                source_fingerprint.c.id.label("source_fingerprint_id"),
                target_fingerprint.c.id.label("target_fingerprint_id"),
                source_fingerprint.c.kind.label("fingerprint_kind"),
                source_fingerprint.c.algorithm.label("fingerprint_algorithm"),
                source_fingerprint.c.algorithm_version.label(
                    "fingerprint_algorithm_version"
                ),
                source_fingerprint.c.value.label("fingerprint_value"),
            )
            .select_from(
                absent_event.join(
                    source_record,
                    source_record.c.id == absent_event.c.file_id,
                )
                .join(
                    source_observation,
                    source_observation.c.id == latest_source_observation_id,
                )
                .join(
                    source_fingerprint,
                    and_(
                        source_fingerprint.c.target_kind
                        == EntityKind.FILE_OBSERVATION.value,
                        source_fingerprint.c.target_id == source_observation.c.id,
                        source_fingerprint.c.kind.in_(_SUPPORTED_FINGERPRINTS),
                    ),
                )
                .join(
                    target_fingerprint,
                    and_(
                        target_fingerprint.c.target_kind
                        == EntityKind.FILE_OBSERVATION.value,
                        target_fingerprint.c.kind == source_fingerprint.c.kind,
                        target_fingerprint.c.algorithm == source_fingerprint.c.algorithm,
                        target_fingerprint.c.algorithm_version
                        == source_fingerprint.c.algorithm_version,
                        target_fingerprint.c.value == source_fingerprint.c.value,
                    ),
                )
                .join(
                    target_observation,
                    and_(
                        target_observation.c.id == target_fingerprint.c.target_id,
                        target_observation.c.scan_run_id == str(run.id),
                    ),
                )
                .join(
                    new_event,
                    and_(
                        new_event.c.file_id == target_observation.c.file_id,
                        new_event.c.scan_run_id == str(run.id),
                        new_event.c.change_state == FileChangeState.NEW.value,
                    ),
                )
                .join(target_record, target_record.c.id == new_event.c.file_id)
            )
            .where(
                absent_event.c.scan_run_id == str(run.id),
                absent_event.c.change_state.in_(
                    (FileChangeState.MISSING.value, FileChangeState.DELETED.value)
                ),
                source_record.c.scan_root_id == str(run.scan_root_id),
                target_record.c.scan_root_id == str(run.scan_root_id),
            )
        )

        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return tuple(
            _FingerprintMatch(
                source_file_id=row["source_file_id"],
                target_file_id=row["target_file_id"],
                source_relative_path=row["source_relative_path"],
                target_relative_path=row["target_relative_path"],
                source_fingerprint_id=row["source_fingerprint_id"],
                target_fingerprint_id=row["target_fingerprint_id"],
                fingerprint_kind=row["fingerprint_kind"],
                fingerprint_algorithm=row["fingerprint_algorithm"],
                fingerprint_algorithm_version=row["fingerprint_algorithm_version"],
                fingerprint_value=row["fingerprint_value"],
            )
            for row in rows
        )

    @staticmethod
    def _unambiguous_matches(
        matches: tuple[_FingerprintMatch, ...],
    ) -> tuple[_FingerprintMatch, ...]:
        by_evidence: dict[tuple[str, str, str, str], list[_FingerprintMatch]] = defaultdict(
            list
        )
        for match in matches:
            by_evidence[match.evidence_key].append(match)

        accepted: list[_FingerprintMatch] = []
        for evidence_matches in by_evidence.values():
            source_ids = {match.source_file_id for match in evidence_matches}
            target_ids = {match.target_file_id for match in evidence_matches}
            if len(source_ids) == 1 and len(target_ids) == 1:
                accepted.append(evidence_matches[0])
        return tuple(accepted)

    @staticmethod
    def _to_candidate(
        match: _FingerprintMatch,
        run: ScanRun,
        created_at: datetime,
    ) -> FileRelocationCandidate:
        return FileRelocationCandidate(
            id=EntityId.new(),
            scan_run_id=run.id,
            source_file_id=EntityId.parse(match.source_file_id),
            target_file_id=EntityId.parse(match.target_file_id),
            kind=_path_change_kind(
                match.source_relative_path,
                match.target_relative_path,
            ),
            source_relative_path=match.source_relative_path,
            target_relative_path=match.target_relative_path,
            source_fingerprint_id=EntityId.parse(match.source_fingerprint_id),
            target_fingerprint_id=EntityId.parse(match.target_fingerprint_id),
            fingerprint_kind=match.fingerprint_kind,
            fingerprint_algorithm=match.fingerprint_algorithm,
            fingerprint_algorithm_version=match.fingerprint_algorithm_version,
            created_at=created_at,
        )


def _priority(match: _FingerprintMatch) -> tuple[int, str, str]:
    return (
        _FINGERPRINT_PRIORITY.get(match.fingerprint_kind, 0),
        match.fingerprint_algorithm,
        match.fingerprint_algorithm_version,
    )


def _path_change_kind(source: str, target: str) -> RelocationCandidateKind:
    source_path = PurePosixPath(source)
    target_path = PurePosixPath(target)
    if source_path.parent == target_path.parent:
        return RelocationCandidateKind.RENAMED
    if source_path.name == target_path.name:
        return RelocationCandidateKind.MOVED
    return RelocationCandidateKind.MOVED_AND_RENAMED
