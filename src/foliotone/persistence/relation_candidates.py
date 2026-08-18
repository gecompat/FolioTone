"""Insert-only SQLite store for scored relation candidates."""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import Engine, insert, select
from sqlalchemy.engine import Connection

from foliotone.core import (
    EntityId,
    EntityKind,
    MatchStatus,
    ReviewCandidateKind,
    ReviewDecision,
    ReviewDecisionValue,
    ReviewItem,
    ReviewItemState,
    ReviewType,
    ScanRunStatus,
)
from foliotone.matching.relation_candidates import (
    MAX_RELATION_CANDIDATE_EVIDENCE,
    RelationCandidate,
    RelationCandidateEvidenceKind,
    RelationCandidateEvidenceLink,
)
from foliotone.matching.scoring import (
    EbookRelationMatcher,
    MatcherFeature,
    MatcherFeatureCode,
    MatcherFeatureState,
)
from foliotone.persistence import relation_candidate_schema as rc_schema
from foliotone.persistence import resolution_review_schema as rr_schema
from foliotone.persistence import schema
from foliotone.persistence.codecs import Codec


class RelationCandidateStoreError(RuntimeError):
    """A path-free relation candidate persistence failure."""


class SQLiteRelationCandidateStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._candidate_codec = Codec(RelationCandidate, rc_schema.relation_candidates)
        self._evidence_codec = Codec(
            RelationCandidateEvidenceLink,
            rc_schema.relation_candidate_evidence,
        )
        self._review_codec = Codec(ReviewItem, rr_schema.review_items)
        self._decision_codec = Codec(ReviewDecision, rr_schema.review_decisions)

    def create_or_get(
        self,
        candidate: RelationCandidate,
        evidence: tuple[RelationCandidateEvidenceLink, ...],
    ) -> RelationCandidate:
        features = self._validate_shape(candidate, evidence)
        outcome = EbookRelationMatcher().score(
            candidate.relation_type,
            candidate.left_kind,
            candidate.left_id,
            candidate.right_kind,
            candidate.right_id,
            features,
        )
        if (
            outcome.matcher_name != candidate.matcher_name
            or outcome.matcher_version != candidate.matcher_version
            or outcome.decision_compatibility_version != candidate.decision_compatibility_version
            or outcome.evidence_fingerprint != candidate.evidence_fingerprint
            or outcome.confidence != candidate.confidence
            or outcome.status is not candidate.status
        ):
            raise RelationCandidateStoreError("relation candidate does not match matcher output")

        with self._engine.begin() as connection:
            self._validate_lineage(connection, candidate)
            self._validate_endpoint(connection, candidate.left_kind, candidate.left_id)
            self._validate_endpoint(connection, candidate.right_kind, candidate.right_id)
            for link in evidence:
                self._validate_reference(connection, link)
            result = connection.execute(
                insert(rc_schema.relation_candidates)
                .values(**self._candidate_codec.encode(candidate))
                .prefix_with("OR IGNORE")
            )
            if result.rowcount == 1:
                connection.execute(
                    insert(rc_schema.relation_candidate_evidence),
                    [self._evidence_codec.encode(link) for link in evidence],
                )
                return candidate
            persisted = self._by_snapshot(connection, candidate)
            if persisted is None:
                raise RelationCandidateStoreError("relation candidate could not be persisted")
            persisted_links = self._evidence_for(connection, persisted.id)
            if _material_links(persisted_links) != _material_links(evidence):
                raise RelationCandidateStoreError("relation candidate evidence is nondeterministic")
            return persisted

    def get(self, candidate_id: EntityId) -> RelationCandidate | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(rc_schema.relation_candidates).where(
                        rc_schema.relation_candidates.c.id == str(candidate_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._candidate_codec.decode(row)

    def evidence(self, candidate_id: EntityId) -> tuple[RelationCandidateEvidenceLink, ...]:
        with self._engine.connect() as connection:
            return self._evidence_for(connection, candidate_id)

    def enqueue_review(self, candidate_id: EntityId, item: ReviewItem) -> ReviewItem:
        """Insert one exact matching-review case without changing the candidate."""

        with self._engine.begin() as connection:
            candidate = self._get(connection, candidate_id)
            if candidate is None:
                raise RelationCandidateStoreError("relation candidate does not exist")
            if candidate.status is not MatchStatus.REVIEW_REQUIRED:
                raise RelationCandidateStoreError("relation candidate must not enter review")
            _require_review_matches(candidate, item)
            result = connection.execute(
                insert(rr_schema.review_items)
                .values(**self._review_codec.encode(item))
                .prefix_with("OR IGNORE")
            )
            if result.rowcount == 1:
                return item
            persisted = self._review_by_case(connection, item)
            if persisted is None:
                raise RelationCandidateStoreError("matching review could not be persisted")
            expected = replace(
                item,
                id=persisted.id,
                producer_version=persisted.producer_version,
            )
            if persisted != expected:
                raise RelationCandidateStoreError("matching review case is nondeterministic")
            return persisted

    def find_reusable_decision(self, candidate: RelationCandidate) -> ReviewDecision | None:
        candidates = rc_schema.relation_candidates
        items = rr_schema.review_items
        decisions = rr_schema.review_decisions
        statement = (
            select(decisions)
            .join(items, items.c.id == decisions.c.review_item_id)
            .join(candidates, candidates.c.id == items.c.candidate_id)
            .where(
                items.c.review_type == ReviewType.MATCH_RELATION.value,
                candidates.c.left_kind == candidate.left_kind.value,
                candidates.c.left_id == str(candidate.left_id),
                candidates.c.right_kind == candidate.right_kind.value,
                candidates.c.right_id == str(candidate.right_id),
                candidates.c.relation_type == candidate.relation_type.value,
                candidates.c.matcher_name == candidate.matcher_name,
                items.c.decision_compatibility_version == candidate.decision_compatibility_version,
                items.c.evidence_fingerprint == candidate.evidence_fingerprint,
                items.c.candidate_set_fingerprint == candidate.candidate_set_fingerprint,
            )
            .order_by(
                decisions.c.decided_at.desc(),
                decisions.c.sequence_no.desc(),
                decisions.c.id.desc(),
            )
            .limit(1)
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            return None
        decision = self._decision_codec.decode(row)
        return None if decision.decision is ReviewDecisionValue.DEFER else decision

    @staticmethod
    def _validate_shape(
        candidate: RelationCandidate,
        evidence: tuple[RelationCandidateEvidenceLink, ...],
    ) -> tuple[MatcherFeature, ...]:
        if not evidence or len(evidence) > MAX_RELATION_CANDIDATE_EVIDENCE:
            raise RelationCandidateStoreError("relation candidate evidence count is outside bounds")
        if tuple(link.ordinal for link in evidence) != tuple(range(len(evidence))):
            raise RelationCandidateStoreError(
                "relation candidate evidence ordinals must be contiguous"
            )
        if any(link.relation_candidate_id != candidate.id for link in evidence):
            raise RelationCandidateStoreError(
                "relation candidate evidence belongs to another candidate"
            )
        grouped: dict[MatcherFeatureCode, list[RelationCandidateEvidenceLink]] = {}
        for link in evidence:
            grouped.setdefault(link.feature_code, []).append(link)
        features: list[MatcherFeature] = []
        for code, links in grouped.items():
            states = {link.feature_state for link in links}
            materials = {link.material_fingerprint for link in links}
            if len(states) != 1 or len(materials) != 1:
                raise RelationCandidateStoreError("feature evidence semantics are inconsistent")
            state = next(iter(states))
            if state is MatcherFeatureState.PRESENT and any(
                link.evidence_id is None for link in links
            ):
                raise RelationCandidateStoreError("present feature evidence requires references")
            if state is MatcherFeatureState.ABSENT and (
                len(links) != 1 or links[0].evidence_id is not None
            ):
                raise RelationCandidateStoreError("absent feature evidence must be unreferenced")
            evidence_ids = tuple(
                sorted(
                    (link.evidence_id for link in links if link.evidence_id is not None),
                    key=str,
                )
            )
            features.append(MatcherFeature(code, state, next(iter(materials)), evidence_ids))
        return tuple(sorted(features, key=lambda item: item.code.value))

    @staticmethod
    def _validate_lineage(connection: Connection, candidate: RelationCandidate) -> None:
        row = connection.execute(
            select(schema.scan_runs.c.scan_root_id, schema.scan_runs.c.status).where(
                schema.scan_runs.c.id == str(candidate.source_scan_run_id)
            )
        ).one_or_none()
        if row is None or str(row.scan_root_id) != str(candidate.scan_root_id):
            raise RelationCandidateStoreError("relation candidate scan lineage is invalid")
        if str(row.status) != ScanRunStatus.COMPLETED.value:
            raise RelationCandidateStoreError("relation candidate requires a completed scan")

    @staticmethod
    def _validate_endpoint(connection: Connection, kind: EntityKind, entity_id: EntityId) -> None:
        table = _ENDPOINT_TABLES[kind]
        if (
            connection.execute(
                select(table.c.id).where(table.c.id == str(entity_id))
            ).scalar_one_or_none()
            is None
        ):
            raise RelationCandidateStoreError("relation candidate endpoint does not exist")

    @staticmethod
    def _validate_reference(connection: Connection, link: RelationCandidateEvidenceLink) -> None:
        if link.evidence_kind is None or link.evidence_id is None:
            return
        table = _EVIDENCE_TABLES[link.evidence_kind]
        if (
            connection.execute(
                select(table.c.id).where(table.c.id == str(link.evidence_id))
            ).scalar_one_or_none()
            is None
        ):
            raise RelationCandidateStoreError("relation candidate evidence does not exist")

    def _by_snapshot(
        self, connection: Connection, candidate: RelationCandidate
    ) -> RelationCandidate | None:
        table = rc_schema.relation_candidates
        row = (
            connection.execute(
                select(table).where(
                    table.c.scan_root_id == str(candidate.scan_root_id),
                    table.c.source_scan_run_id == str(candidate.source_scan_run_id),
                    table.c.left_kind == candidate.left_kind.value,
                    table.c.left_id == str(candidate.left_id),
                    table.c.right_kind == candidate.right_kind.value,
                    table.c.right_id == str(candidate.right_id),
                    table.c.relation_type == candidate.relation_type.value,
                    table.c.matcher_name == candidate.matcher_name,
                    table.c.matcher_version == candidate.matcher_version,
                    table.c.decision_compatibility_version
                    == candidate.decision_compatibility_version,
                    table.c.evidence_fingerprint == candidate.evidence_fingerprint,
                    table.c.candidate_set_fingerprint == candidate.candidate_set_fingerprint,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        persisted = self._candidate_codec.decode(row)
        if persisted.confidence != candidate.confidence or persisted.status is not candidate.status:
            raise RelationCandidateStoreError("relation candidate snapshot is nondeterministic")
        return persisted

    def _get(
        self,
        connection: Connection,
        candidate_id: EntityId,
    ) -> RelationCandidate | None:
        row = (
            connection.execute(
                select(rc_schema.relation_candidates).where(
                    rc_schema.relation_candidates.c.id == str(candidate_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else self._candidate_codec.decode(row)

    def _review_by_case(self, connection: Connection, item: ReviewItem) -> ReviewItem | None:
        table = rr_schema.review_items
        row = (
            connection.execute(
                select(table).where(
                    table.c.review_type == item.review_type.value,
                    table.c.subject_kind == item.subject_kind.value,
                    table.c.subject_id == str(item.subject_id),
                    table.c.candidate_kind == item.candidate_kind.value,
                    table.c.candidate_id == str(item.candidate_id),
                    table.c.producer_name == item.producer_name,
                    table.c.decision_compatibility_version == item.decision_compatibility_version,
                    table.c.evidence_fingerprint == item.evidence_fingerprint,
                    table.c.candidate_set_fingerprint == item.candidate_set_fingerprint,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else self._review_codec.decode(row)

    def _evidence_for(
        self, connection: Connection, candidate_id: EntityId
    ) -> tuple[RelationCandidateEvidenceLink, ...]:
        rows = (
            connection.execute(
                select(rc_schema.relation_candidate_evidence)
                .where(
                    rc_schema.relation_candidate_evidence.c.relation_candidate_id
                    == str(candidate_id)
                )
                .order_by(rc_schema.relation_candidate_evidence.c.ordinal)
            )
            .mappings()
            .all()
        )
        return tuple(self._evidence_codec.decode(row) for row in rows)


def _material_links(
    links: tuple[RelationCandidateEvidenceLink, ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            link.ordinal,
            link.feature_code,
            link.feature_state,
            link.material_fingerprint,
            link.evidence_kind,
            link.evidence_id,
        )
        for link in links
    )


def _require_review_matches(candidate: RelationCandidate, item: ReviewItem) -> None:
    if (
        item.review_type is not ReviewType.MATCH_RELATION
        or item.candidate_kind is not ReviewCandidateKind.RELATION
        or item.candidate_id != candidate.id
        or item.subject_kind is not candidate.left_kind
        or item.subject_id != candidate.left_id
        or item.producer_name != candidate.matcher_name
        or item.producer_version != candidate.matcher_version
        or item.decision_compatibility_version != candidate.decision_compatibility_version
        or item.evidence_fingerprint != candidate.evidence_fingerprint
        or item.candidate_set_fingerprint != candidate.candidate_set_fingerprint
        or item.state is not ReviewItemState.PENDING
    ):
        raise RelationCandidateStoreError("matching review does not match candidate")


_ENDPOINT_TABLES = {
    EntityKind.FILE: schema.file_records,
    EntityKind.EDITION: schema.editions,
    EntityKind.WORK: schema.works,
}

_EVIDENCE_TABLES = {
    RelationCandidateEvidenceKind.FINGERPRINT: schema.fingerprints,
    RelationCandidateEvidenceKind.VALUE_ASSERTION: schema.value_assertions,
    RelationCandidateEvidenceKind.EXTERNAL_IDENTIFIER: schema.external_identifiers,
    RelationCandidateEvidenceKind.RESOLUTION_CANDIDATE: rr_schema.resolution_candidates,
    RelationCandidateEvidenceKind.TOOL_RESULT: schema.tool_results,
    RelationCandidateEvidenceKind.CLASSIFICATION_ASSERTION: schema.classification_assertions,
    RelationCandidateEvidenceKind.REVIEW_DECISION: rr_schema.review_decisions,
}
