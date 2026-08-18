"""Bounded offline orchestration from candidate blocks to matching review."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import combinations

from sqlalchemy import Engine, Table, select

from foliotone.core import (
    EntityId,
    EntityKind,
    MatchStatus,
    RelationType,
    ReviewCandidateKind,
    ReviewItem,
    ReviewItemState,
    ReviewType,
)
from foliotone.matching import (
    CandidateBlock,
    CandidateBlockType,
    EbookCandidateBlockingError,
    EbookRelationMatcher,
    MatcherFeature,
    MatcherFeatureCode,
    MatcherFeatureState,
    RelationCandidate,
    RelationCandidateEvidenceKind,
    RelationCandidateEvidenceLink,
    SQLiteEbookCandidateBlockReader,
    relation_candidate_set_fingerprint,
)
from foliotone.persistence import (
    RelationCandidateStoreError,
    SQLiteRelationCandidateStore,
    schema,
)
from foliotone.persistence import resolution_review_schema as rr_schema

EBOOK_MATCHING_WORKFLOW_PROFILE = "ebook-matching-workflow/v1"
MAX_MATCHING_CANDIDATES = 500
MAX_MATCHING_BLOCKS = 200
MAX_MATCHING_PAIRWISE_MEMBERS = 32


class EbookMatchingError(RuntimeError):
    """A bounded matching run could not be completed safely."""


@dataclass(frozen=True, slots=True)
class EbookMatchingOutcome:
    scan_root_id: EntityId
    scan_run_id: EntityId
    blocks_seen: int
    candidates_available: int
    candidates_processed: int
    confirmed: int
    rejected: int
    review_queued: int
    decisions_reused: int
    truncated: bool
    profile: str = EBOOK_MATCHING_WORKFLOW_PROFILE


@dataclass(frozen=True, slots=True)
class _PairCase:
    relation_type: RelationType
    endpoint_kind: EntityKind
    left_id: EntityId
    right_id: EntityId
    feature_code: MatcherFeatureCode
    evidence_kind: RelationCandidateEvidenceKind
    evidence_ids: tuple[EntityId, ...]
    material_fingerprint: str

    @property
    def identity(self) -> tuple[RelationType, EntityKind, EntityId, EntityKind, EntityId]:
        return (
            self.relation_type,
            self.endpoint_kind,
            self.left_id,
            self.endpoint_kind,
            self.right_id,
        )


class EbookMatchingService:
    """Persist bounded, reproducible candidates without opening Source Media."""

    def __init__(
        self,
        engine: Engine,
        *,
        id_factory: Callable[[], EntityId] = EntityId.new,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._engine = engine
        self._reader = SQLiteEbookCandidateBlockReader(engine)
        self._store = SQLiteRelationCandidateStore(engine)
        self._id_factory = id_factory
        self._clock = clock

    def run(
        self,
        scan_root_id: EntityId,
        scan_run_id: EntityId,
        *,
        block_limit: int = 100,
        candidate_limit: int = 200,
        pairwise_limit: int = MAX_MATCHING_PAIRWISE_MEMBERS,
    ) -> EbookMatchingOutcome:
        if not 1 <= candidate_limit <= MAX_MATCHING_CANDIDATES:
            raise ValueError(f"candidate_limit must be between 1 and {MAX_MATCHING_CANDIDATES}")
        if not 1 <= block_limit <= MAX_MATCHING_BLOCKS:
            raise ValueError(f"block_limit must be between 1 and {MAX_MATCHING_BLOCKS}")
        if not 2 <= pairwise_limit <= MAX_MATCHING_PAIRWISE_MEMBERS:
            raise ValueError(
                f"pairwise_limit must be between 2 and {MAX_MATCHING_PAIRWISE_MEMBERS}"
            )
        try:
            snapshot = self._reader.snapshot(
                scan_root_id,
                scan_run_id,
                block_types=(
                    CandidateBlockType.FILE_SHA256,
                    CandidateBlockType.EDITION_IDENTIFIER,
                    CandidateBlockType.AGENT_TITLE,
                ),
                block_limit=block_limit,
                member_limit=256,
                pairwise_limit=pairwise_limit,
            )
        except EbookCandidateBlockingError as error:
            raise EbookMatchingError("matching snapshot is unavailable") from error
        block_cases = tuple((block, self._cases(block)) for block in snapshot.blocks)
        candidates_available = sum(len(cases) for _, cases in block_cases)
        processed = confirmed = rejected = queued = reused = 0
        truncated = snapshot.blocks_truncated or candidates_available > candidate_limit

        for _, cases in block_cases:
            if not cases:
                continue
            candidate_set = relation_candidate_set_fingerprint(
                tuple(case.identity for case in cases)
            )
            for case in cases:
                if processed >= candidate_limit:
                    break
                try:
                    candidate = self._persist_case(
                        scan_root_id,
                        scan_run_id,
                        candidate_set,
                        case,
                    )
                except RelationCandidateStoreError as error:
                    raise EbookMatchingError("relation candidate persistence failed") from error
                processed += 1
                if candidate.status is MatchStatus.CONFIRMED:
                    confirmed += 1
                elif candidate.status is MatchStatus.REJECTED:
                    rejected += 1
                else:
                    try:
                        prior = self._store.find_reusable_decision(candidate)
                        if prior is not None:
                            reused += 1
                        else:
                            self._enqueue(candidate)
                            queued += 1
                    except RelationCandidateStoreError as error:
                        raise EbookMatchingError("matching review persistence failed") from error
            if processed >= candidate_limit:
                break
        return EbookMatchingOutcome(
            scan_root_id,
            scan_run_id,
            len(snapshot.blocks),
            candidates_available,
            processed,
            confirmed,
            rejected,
            queued,
            reused,
            truncated,
        )

    def _cases(self, block: CandidateBlock) -> tuple[_PairCase, ...]:
        if block.block_type is CandidateBlockType.FILE_SHA256:
            return _exact_file_cases(block)
        if block.block_type is CandidateBlockType.EDITION_IDENTIFIER:
            return self._entity_cases(
                block,
                EntityKind.EDITION,
                RelationType.SAME_EDITION,
                MatcherFeatureCode.EDITION_IDENTIFIER_COMPATIBLE,
                RelationCandidateEvidenceKind.EXTERNAL_IDENTIFIER,
                schema.external_identifiers,
            )
        if block.block_type is CandidateBlockType.AGENT_TITLE:
            return self._entity_cases(
                block,
                EntityKind.WORK,
                RelationType.SAME_WORK,
                MatcherFeatureCode.TITLE_COMPATIBLE,
                RelationCandidateEvidenceKind.VALUE_ASSERTION,
                schema.value_assertions,
            )
        return ()

    def _entity_cases(
        self,
        block: CandidateBlock,
        endpoint_kind: EntityKind,
        relation_type: RelationType,
        feature_code: MatcherFeatureCode,
        evidence_kind: RelationCandidateEvidenceKind,
        evidence_table: Table,
    ) -> tuple[_PairCase, ...]:
        evidence_ids = tuple(
            sorted(
                {value for member in block.members for value in member.evidence_ids},
                key=str,
            )
        )
        if not evidence_ids:
            return ()
        with self._engine.connect() as connection:
            resolution_rows = connection.execute(
                select(
                    rr_schema.resolution_candidates.c.id,
                    rr_schema.resolution_candidates.c.candidate_entity_id,
                ).where(
                    rr_schema.resolution_candidates.c.id.in_(map(str, evidence_ids)),
                    rr_schema.resolution_candidates.c.candidate_kind == endpoint_kind.value,
                )
            ).all()
            table = evidence_table
            persisted_evidence = {
                EntityId.parse(str(value))
                for value in connection.execute(
                    select(table.c.id).where(table.c.id.in_(map(str, evidence_ids)))
                ).scalars()
            }
        resolution_map = {
            EntityId.parse(str(row.id)): EntityId.parse(str(row.candidate_entity_id))
            for row in resolution_rows
        }
        refs_by_endpoint: dict[EntityId, set[EntityId]] = defaultdict(set)
        for member in block.members:
            member_endpoints = {
                resolution_map[value] for value in member.evidence_ids if value in resolution_map
            }
            references = persisted_evidence.intersection(member.evidence_ids)
            for endpoint in member_endpoints:
                refs_by_endpoint[endpoint].update(references)
        endpoint_ids = tuple(sorted(refs_by_endpoint, key=str))
        cases = []
        for left_id, right_id in combinations(endpoint_ids, 2):
            pair_references = tuple(
                sorted(refs_by_endpoint[left_id] | refs_by_endpoint[right_id], key=str)
            )
            if pair_references:
                cases.append(
                    _PairCase(
                        relation_type,
                        endpoint_kind,
                        left_id,
                        right_id,
                        feature_code,
                        evidence_kind,
                        pair_references,
                        block.key_fingerprint,
                    )
                )
        return tuple(cases)

    def _persist_case(
        self,
        scan_root_id: EntityId,
        scan_run_id: EntityId,
        candidate_set: str,
        case: _PairCase,
    ) -> RelationCandidate:
        feature = MatcherFeature(
            case.feature_code,
            MatcherFeatureState.PRESENT,
            case.material_fingerprint,
            case.evidence_ids,
        )
        outcome = EbookRelationMatcher().score(
            case.relation_type,
            case.endpoint_kind,
            case.left_id,
            case.endpoint_kind,
            case.right_id,
            (feature,),
        )
        candidate = RelationCandidate.from_outcome(
            self._id_factory(),
            scan_root_id,
            scan_run_id,
            candidate_set,
            outcome,
            self._clock(),
        )
        links = tuple(
            RelationCandidateEvidenceLink(
                self._id_factory(),
                candidate.id,
                ordinal,
                feature.code,
                feature.state,
                feature.material_fingerprint,
                case.evidence_kind,
                evidence_id,
            )
            for ordinal, evidence_id in enumerate(case.evidence_ids)
        )
        return self._store.create_or_get(candidate, links)

    def _enqueue(self, candidate: RelationCandidate) -> None:
        item = ReviewItem(
            self._id_factory(),
            ReviewType.MATCH_RELATION,
            candidate.left_kind,
            candidate.left_id,
            ReviewCandidateKind.RELATION,
            candidate.id,
            candidate.matcher_name,
            candidate.matcher_version,
            candidate.decision_compatibility_version,
            candidate.evidence_fingerprint,
            candidate.candidate_set_fingerprint,
            ReviewItemState.PENDING,
            self._clock(),
        )
        self._store.enqueue_review(candidate.id, item)


def _exact_file_cases(block: CandidateBlock) -> tuple[_PairCase, ...]:
    representative = next(
        (
            member
            for member in block.members
            if member.observation_id == block.representative_observation_id
        ),
        None,
    )
    if representative is None:
        raise EbookMatchingError("exact duplicate block has no representative member")
    cases = []
    for member in block.members:
        if member.file_id == representative.file_id:
            continue
        left, right = sorted((representative, member), key=lambda value: str(value.file_id))
        evidence_ids = tuple(sorted(set(left.evidence_ids) | set(right.evidence_ids), key=str))
        if not evidence_ids:
            raise EbookMatchingError("exact duplicate block has no fingerprint evidence")
        cases.append(
            _PairCase(
                RelationType.EXACT_DUPLICATE,
                EntityKind.FILE,
                left.file_id,
                right.file_id,
                MatcherFeatureCode.FILE_SHA256_EQUAL,
                RelationCandidateEvidenceKind.FINGERPRINT,
                evidence_ids,
                block.key_fingerprint,
            )
        )
    return tuple(cases)
