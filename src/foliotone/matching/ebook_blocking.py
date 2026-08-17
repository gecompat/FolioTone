"""Bounded read-only candidate blocking over one completed e-book scan."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, Select, and_, exists, func, or_, select

from foliotone.analyzers.ebook import TEXT_FINGERPRINT_KIND
from foliotone.core import (
    EBOOK_COLLECTION_FORMATS,
    EntityId,
    EntityKind,
    MediaType,
    PresenceState,
    ResolutionDisposition,
    ReviewCandidateKind,
    ReviewDecisionValue,
    ReviewItemState,
    ReviewType,
    ScanRunStatus,
)
from foliotone.matching.contracts import (
    CandidateBlock,
    CandidateBlockMember,
    CandidateBlockStatus,
    CandidateBlockStrength,
    CandidateBlockType,
    build_candidate_block_key,
)
from foliotone.persistence import resolution_review_schema as rr_schema
from foliotone.persistence import schema

EBOOK_BLOCKING_PROFILE = "ebook-candidate-blocking/v1"
MAX_BLOCK_PAGE = 200
MAX_BLOCK_MEMBERS = 256
MAX_PAIRWISE_MEMBERS = 64
BLOCKING_FETCH_SIZE = 500
_FULL_FILE_PROFILE = ("FILE_SHA256", "sha256", "1")
_PRIMARY_BLOCK_TYPES = (
    CandidateBlockType.FILE_SHA256,
    CandidateBlockType.EDITION_IDENTIFIER,
    CandidateBlockType.RESOLVED_EDITION,
    CandidateBlockType.RESOLVED_WORK,
    CandidateBlockType.AGENT_TITLE,
    CandidateBlockType.TEXT_FINGERPRINT,
    CandidateBlockType.SERIES_CONTEXT,
)


class EbookCandidateBlockingError(RuntimeError):
    """A persisted scan snapshot cannot be blocked safely."""


@dataclass(frozen=True, slots=True)
class EbookCandidateBlockSnapshot:
    """Bounded path-free blocks for one explicit completed scan."""

    scan_root_id: EntityId
    scan_run_id: EntityId
    blocks: tuple[CandidateBlock, ...]
    blocks_truncated: bool
    profile: str = EBOOK_BLOCKING_PROFILE


@dataclass(frozen=True, slots=True)
class _BlockSource:
    block_type: CandidateBlockType
    block_version: str
    key_columns: tuple[str, ...]
    statement: Select[tuple[object, ...]]


class SQLiteEbookCandidateBlockReader:
    """Project existing Evidence into bounded blocks without writing SQLite."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def snapshot(
        self,
        scan_root_id: EntityId,
        scan_run_id: EntityId,
        *,
        block_types: Sequence[CandidateBlockType] = _PRIMARY_BLOCK_TYPES,
        block_limit: int = 100,
        member_limit: int = MAX_BLOCK_MEMBERS,
        pairwise_limit: int = MAX_PAIRWISE_MEMBERS,
    ) -> EbookCandidateBlockSnapshot:
        """Return deterministic candidate blocks for the latest completed scan."""

        _validate_limits(block_limit, member_limit, pairwise_limit)
        requested = tuple(block_types)
        if not requested or len(requested) != len(set(requested)):
            raise ValueError("block_types must be non-empty and unique")
        if any(block_type not in _PRIMARY_BLOCK_TYPES for block_type in requested):
            raise ValueError("block_types contains an unsupported e-book block type")

        with self._engine.connect() as connection, connection.begin():
            self._validate_scan(connection, scan_root_id, scan_run_id)
            current = _current_observations(scan_root_id, scan_run_id)
            sources = _sources(connection, current, requested)
            blocks: list[CandidateBlock] = []
            overflow = False
            for source in sources:
                source_blocks, source_overflow = _read_source_blocks(
                    connection,
                    source,
                    block_limit=block_limit,
                    member_limit=member_limit,
                    pairwise_limit=pairwise_limit,
                )
                blocks.extend(source_blocks)
                overflow = overflow or source_overflow

        blocks.sort(key=lambda block: (block.block_type.value, block.key_fingerprint))
        if len(blocks) > block_limit:
            overflow = True
            blocks = blocks[:block_limit]
        return EbookCandidateBlockSnapshot(
            scan_root_id=scan_root_id,
            scan_run_id=scan_run_id,
            blocks=tuple(blocks),
            blocks_truncated=overflow,
        )

    @staticmethod
    def _validate_scan(
        connection: Connection,
        scan_root_id: EntityId,
        scan_run_id: EntityId,
    ) -> None:
        run = schema.scan_runs
        row = connection.execute(
            select(run.c.id, run.c.status)
            .where(
                run.c.id == str(scan_run_id),
                run.c.scan_root_id == str(scan_root_id),
            )
            .limit(1)
        ).one_or_none()
        if row is None:
            raise EbookCandidateBlockingError("ScanRun does not belong to ScanRoot")
        if str(row.status) != ScanRunStatus.COMPLETED.value:
            raise EbookCandidateBlockingError("ScanRun must be COMPLETED before blocking")
        latest = connection.execute(
            select(run.c.id)
            .where(
                run.c.scan_root_id == str(scan_root_id),
                run.c.status == ScanRunStatus.COMPLETED.value,
            )
            .order_by(run.c.started_at.desc(), run.c.id.desc())
            .limit(1)
        ).scalar_one()
        if str(latest) != str(scan_run_id):
            raise EbookCandidateBlockingError("blocking requires the latest ScanRun")


def _validate_limits(block_limit: int, member_limit: int, pairwise_limit: int) -> None:
    if not 1 <= block_limit <= MAX_BLOCK_PAGE:
        raise ValueError(f"block_limit must be between 1 and {MAX_BLOCK_PAGE}")
    if not 2 <= member_limit <= MAX_BLOCK_MEMBERS:
        raise ValueError(f"member_limit must be between 2 and {MAX_BLOCK_MEMBERS}")
    if not 2 <= pairwise_limit <= MAX_PAIRWISE_MEMBERS:
        raise ValueError(
            f"pairwise_limit must be between 2 and {MAX_PAIRWISE_MEMBERS}"
        )
    if pairwise_limit > member_limit:
        raise ValueError("pairwise_limit must not exceed member_limit")


def _current_observations(scan_root_id: EntityId, scan_run_id: EntityId) -> Any:
    observation = schema.file_observations
    record = schema.file_records
    return (
        select(
            observation.c.id.label("observation_id"),
            observation.c.file_id.label("file_id"),
        )
        .select_from(observation.join(record, record.c.id == observation.c.file_id))
        .where(
            observation.c.scan_run_id == str(scan_run_id),
            record.c.scan_root_id == str(scan_root_id),
            record.c.media_type == MediaType.EBOOK.value,
            record.c.presence_state == PresenceState.PRESENT.value,
            record.c.relative_path == observation.c.relative_path,
            record.c.size_bytes == observation.c.size_bytes,
            record.c.modified_at == observation.c.modified_at,
            or_(
                *(
                    func.lower(record.c.relative_path).like(f"%.{suffix.lower()}")
                    for suffix in sorted(EBOOK_COLLECTION_FORMATS)
                )
            ),
        )
        .subquery("current_ebook_blocking_observations")
    )


def _sources(
    connection: Connection,
    current: Any,
    requested: tuple[CandidateBlockType, ...],
) -> tuple[_BlockSource, ...]:
    del connection
    resolved = _resolved_mappings(current)
    factories = {
        CandidateBlockType.FILE_SHA256: lambda: _fingerprint_source(
            current,
            CandidateBlockType.FILE_SHA256,
            kind=_FULL_FILE_PROFILE[0],
            algorithm=_FULL_FILE_PROFILE[1],
            algorithm_version=_FULL_FILE_PROFILE[2],
            fixed_profile=True,
        ),
        CandidateBlockType.TEXT_FINGERPRINT: lambda: _fingerprint_source(
            current,
            CandidateBlockType.TEXT_FINGERPRINT,
            kind=TEXT_FINGERPRINT_KIND,
            algorithm=None,
            algorithm_version=None,
            fixed_profile=False,
        ),
        CandidateBlockType.RESOLVED_EDITION: lambda: _resolved_source(
            resolved,
            CandidateBlockType.RESOLVED_EDITION,
            EntityKind.EDITION,
        ),
        CandidateBlockType.RESOLVED_WORK: lambda: _resolved_source(
            resolved,
            CandidateBlockType.RESOLVED_WORK,
            EntityKind.WORK,
        ),
        CandidateBlockType.SERIES_CONTEXT: lambda: _resolved_source(
            resolved,
            CandidateBlockType.SERIES_CONTEXT,
            EntityKind.SERIES,
        ),
        CandidateBlockType.EDITION_IDENTIFIER: lambda: _edition_identifier_source(
            resolved
        ),
        CandidateBlockType.AGENT_TITLE: lambda: _agent_title_source(resolved),
    }
    return tuple(factories[block_type]() for block_type in requested)


def _fingerprint_source(
    current: Any,
    block_type: CandidateBlockType,
    *,
    kind: str,
    algorithm: str | None,
    algorithm_version: str | None,
    fixed_profile: bool,
) -> _BlockSource:
    fingerprint = schema.fingerprints
    conditions = [
        fingerprint.c.target_kind == EntityKind.FILE_OBSERVATION.value,
        fingerprint.c.kind == kind,
    ]
    if algorithm is not None:
        conditions.append(fingerprint.c.algorithm == algorithm)
    if algorithm_version is not None:
        conditions.append(fingerprint.c.algorithm_version == algorithm_version)
    consistent = (
        select(
            fingerprint.c.target_id.label("observation_id"),
            fingerprint.c.algorithm.label("key_algorithm"),
            fingerprint.c.algorithm_version.label("key_version"),
            func.min(fingerprint.c.value).label("key_value"),
            func.min(fingerprint.c.id).label("evidence_id_1"),
        )
        .where(*conditions)
        .group_by(
            fingerprint.c.target_id,
            fingerprint.c.algorithm,
            fingerprint.c.algorithm_version,
        )
        .having(func.count(func.distinct(fingerprint.c.value)) == 1)
        .subquery()
    )
    key_columns = ("key_value",) if fixed_profile else (
        "key_algorithm",
        "key_version",
        "key_value",
    )
    statement = (
        select(
            current.c.observation_id,
            current.c.file_id,
            *(consistent.c[name] for name in key_columns),
            consistent.c.evidence_id_1,
        )
        .select_from(
            current.join(
                consistent,
                consistent.c.observation_id == current.c.observation_id,
            )
        )
        .order_by(
            *(consistent.c[name] for name in key_columns),
            current.c.observation_id,
        )
    )
    version = (
        "file-sha256/v1"
        if fixed_profile
        else "normalized-text-profile-aware/v1"
    )
    return _BlockSource(block_type, version, key_columns, statement)


def _resolved_mappings(current: Any) -> Any:
    candidate = rr_schema.resolution_candidates
    item = rr_schema.review_items
    decision = rr_schema.review_decisions
    latest_value = (
        select(decision.c.decision)
        .where(decision.c.review_item_id == item.c.id)
        .order_by(decision.c.sequence_no.desc())
        .limit(1)
        .correlate(item)
        .scalar_subquery()
    )
    accepted = exists(
        select(item.c.id).where(
            item.c.candidate_kind
            == ReviewCandidateKind.RESOLUTION_CANDIDATE.value,
            item.c.candidate_id == candidate.c.id,
            item.c.review_type == ReviewType.AUTHORITY_RESOLUTION.value,
            item.c.state == ReviewItemState.DECIDED.value,
            item.c.decision_compatibility_version
            == candidate.c.decision_compatibility_version,
            item.c.evidence_fingerprint == candidate.c.evidence_fingerprint,
            item.c.candidate_set_fingerprint == candidate.c.candidate_set_fingerprint,
            latest_value == ReviewDecisionValue.ACCEPT.value,
        )
    )
    return (
        select(
            current.c.observation_id,
            current.c.file_id,
            candidate.c.candidate_kind,
            candidate.c.candidate_entity_id,
            candidate.c.id.label("resolution_candidate_id"),
        )
        .select_from(current.join(candidate, _candidate_targets_current(candidate, current)))
        .where(
            or_(
                candidate.c.disposition == ResolutionDisposition.AUTO_SAFE.value,
                accepted,
            )
        )
        .distinct()
        .subquery("accepted_ebook_resolution_mappings")
    )


def _candidate_targets_current(candidate: Any, current: Any) -> Any:
    return or_(
        and_(
            candidate.c.subject_kind == EntityKind.FILE_OBSERVATION.value,
            candidate.c.subject_id == current.c.observation_id,
        ),
        and_(
            candidate.c.subject_kind == EntityKind.FILE.value,
            candidate.c.subject_id == current.c.file_id,
        ),
    )


def _resolved_source(
    resolved: Any,
    block_type: CandidateBlockType,
    kind: EntityKind,
) -> _BlockSource:
    statement = (
        select(
            resolved.c.observation_id,
            resolved.c.file_id,
            resolved.c.candidate_entity_id.label("key_entity_id"),
            resolved.c.resolution_candidate_id.label("evidence_id_1"),
        )
        .where(resolved.c.candidate_kind == kind.value)
        .order_by(resolved.c.candidate_entity_id, resolved.c.observation_id)
    )
    return _BlockSource(
        block_type,
        f"accepted-{kind.value.lower()}-resolution/v1",
        ("key_entity_id",),
        statement,
    )


def _edition_identifier_source(resolved: Any) -> _BlockSource:
    identifier = schema.external_identifiers
    statement = (
        select(
            resolved.c.observation_id,
            resolved.c.file_id,
            identifier.c.namespace.label("key_namespace"),
            identifier.c.value.label("key_value"),
            resolved.c.resolution_candidate_id.label("evidence_id_1"),
            identifier.c.id.label("evidence_id_2"),
        )
        .select_from(
            resolved.join(
                identifier,
                and_(
                    resolved.c.candidate_kind == EntityKind.EDITION.value,
                    identifier.c.target_kind == EntityKind.EDITION.value,
                    identifier.c.target_id == resolved.c.candidate_entity_id,
                ),
            )
        )
        .order_by(
            identifier.c.namespace,
            identifier.c.value,
            resolved.c.observation_id,
        )
    )
    return _BlockSource(
        CandidateBlockType.EDITION_IDENTIFIER,
        "edition-identifier/v1",
        ("key_namespace", "key_value"),
        statement,
    )


def _agent_title_source(resolved: Any) -> _BlockSource:
    assertion = schema.value_assertions
    contribution = schema.contributions
    statement = (
        select(
            resolved.c.observation_id,
            resolved.c.file_id,
            contribution.c.agent_id.label("key_agent_id"),
            assertion.c.value.label("key_title"),
            resolved.c.resolution_candidate_id.label("evidence_id_1"),
            contribution.c.id.label("evidence_id_2"),
            assertion.c.id.label("evidence_id_3"),
        )
        .select_from(
            resolved.join(
                contribution,
                and_(
                    resolved.c.candidate_kind == EntityKind.WORK.value,
                    contribution.c.target_kind == EntityKind.WORK.value,
                    contribution.c.target_id == resolved.c.candidate_entity_id,
                    func.lower(contribution.c.role) == "author",
                ),
            ).join(
                assertion,
                and_(
                    assertion.c.target_kind == EntityKind.WORK.value,
                    assertion.c.target_id == resolved.c.candidate_entity_id,
                    assertion.c.field_name == "work.title.normalized",
                ),
            )
        )
        .order_by(
            contribution.c.agent_id,
            assertion.c.value,
            resolved.c.observation_id,
        )
    )
    return _BlockSource(
        CandidateBlockType.AGENT_TITLE,
        "resolved-agent-normalized-work-title/v1",
        ("key_agent_id", "key_title"),
        statement,
    )


def _read_source_blocks(
    connection: Connection,
    source: _BlockSource,
    *,
    block_limit: int,
    member_limit: int,
    pairwise_limit: int,
) -> tuple[list[CandidateBlock], bool]:
    rows = connection.execution_options(stream_results=True).execute(source.statement)
    mappings = rows.mappings()
    blocks: list[CandidateBlock] = []
    overflow = False
    current_key: tuple[str, ...] | None = None
    current_observation: EntityId | None = None
    current_file: EntityId | None = None
    current_evidence: set[EntityId] = set()
    members: list[CandidateBlockMember] = []
    member_count = 0

    def finish_member() -> None:
        nonlocal member_count
        if current_observation is None or current_file is None:
            return
        member_count += 1
        if len(members) < member_limit:
            members.append(
                CandidateBlockMember(
                    observation_id=current_observation,
                    file_id=current_file,
                    evidence_ids=tuple(sorted(current_evidence, key=str)),
                )
            )

    def finish_group() -> None:
        nonlocal overflow, members, member_count
        if current_key is None or member_count < 2:
            members = []
            member_count = 0
            return
        if len(blocks) >= block_limit + 1:
            overflow = True
            members = []
            member_count = 0
            return
        status = _block_status(source.block_type, member_count, pairwise_limit)
        representative = (
            members[0].observation_id
            if status is CandidateBlockStatus.EXACT_GROUP and members
            else None
        )
        blocks.append(
            CandidateBlock(
                block_type=source.block_type,
                key_fingerprint=build_candidate_block_key(
                    source.block_type,
                    source.block_version,
                    tuple(
                        f"{column}={value}"
                        for column, value in zip(
                            source.key_columns,
                            current_key,
                            strict=True,
                        )
                    ),
                ),
                block_version=source.block_version,
                identity_level=_identity_level(source.block_type),
                strength=_strength(source.block_type),
                member_count=member_count,
                members=tuple(members),
                status=status,
                representative_observation_id=representative,
            )
        )
        members = []
        member_count = 0

    stop = False
    while not stop and (batch := mappings.fetchmany(BLOCKING_FETCH_SIZE)):
        for row in batch:
            key = tuple(str(row[column]) for column in source.key_columns)
            observation_id = EntityId.parse(str(row["observation_id"]))
            file_id = EntityId.parse(str(row["file_id"]))
            if current_key is not None and key != current_key:
                finish_member()
                finish_group()
                current_observation = None
                current_file = None
                current_evidence = set()
                if overflow:
                    stop = True
                    break
            if current_observation is not None and observation_id != current_observation:
                finish_member()
                current_evidence = set()
            current_key = key
            current_observation = observation_id
            current_file = file_id
            current_evidence.update(_row_evidence_ids(row))
    if not stop:
        finish_member()
        finish_group()
    if len(blocks) > block_limit:
        overflow = True
        blocks = blocks[:block_limit]
    return blocks, overflow


def _row_evidence_ids(row: Any) -> Iterable[EntityId]:
    for ordinal in range(1, 5):
        value = row.get(f"evidence_id_{ordinal}")
        if value is not None:
            yield EntityId.parse(str(value))


def _block_status(
    block_type: CandidateBlockType,
    member_count: int,
    pairwise_limit: int,
) -> CandidateBlockStatus:
    if block_type is CandidateBlockType.FILE_SHA256:
        return CandidateBlockStatus.EXACT_GROUP
    if member_count > pairwise_limit:
        return CandidateBlockStatus.SECONDARY_REQUIRED
    return CandidateBlockStatus.READY


def _identity_level(block_type: CandidateBlockType) -> EntityKind:
    if block_type in {
        CandidateBlockType.FILE_SHA256,
        CandidateBlockType.TEXT_FINGERPRINT,
    }:
        return EntityKind.FILE
    if block_type in {
        CandidateBlockType.EDITION_IDENTIFIER,
        CandidateBlockType.RESOLVED_EDITION,
    }:
        return EntityKind.EDITION
    if block_type in {
        CandidateBlockType.RESOLVED_WORK,
        CandidateBlockType.AGENT_TITLE,
    }:
        return EntityKind.WORK
    return EntityKind.SERIES


def _strength(block_type: CandidateBlockType) -> CandidateBlockStrength:
    if block_type is CandidateBlockType.SERIES_CONTEXT:
        return CandidateBlockStrength.SUPPORTING_ONLY
    return CandidateBlockStrength.IDENTITY_CAPABLE
