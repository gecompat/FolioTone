"""Dedicated insert-only SQLite store for resolution and review history."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from sqlalchemy import Engine, and_, insert, or_, select, update
from sqlalchemy.engine import Connection

from foliotone.authority.persisted_resolution import resolution_evidence_fingerprint
from foliotone.core import (
    EntityId,
    EntityKind,
    ResolutionCandidate,
    ResolutionDisposition,
    ResolutionEvidenceKind,
    ResolutionEvidenceLink,
    ReviewCandidateKind,
    ReviewDecision,
    ReviewDecisionValue,
    ReviewItem,
    ReviewItemState,
    ReviewType,
)
from foliotone.persistence import resolution_review_schema as rr_schema
from foliotone.persistence import schema
from foliotone.persistence._mapping import datetime_to_db
from foliotone.persistence.codecs import Codec

MAX_RESOLUTION_EVIDENCE = 256
MAX_RESOLUTION_PAGE = 200
MAX_REVIEW_PAGE = 200


class ResolutionReviewStoreError(RuntimeError):
    """A path-free persistence, consistency, or optimistic-fence failure."""


@dataclass(frozen=True, slots=True)
class ResolutionCandidatePage:
    items: tuple[ResolutionCandidate, ...]
    next_cursor: tuple[datetime, EntityId] | None


@dataclass(frozen=True, slots=True)
class ReviewItemPage:
    items: tuple[ReviewItem, ...]
    next_cursor: tuple[datetime, EntityId] | None


class SQLiteResolutionReviewStore:
    """Persist immutable candidate snapshots and append-only review decisions."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._candidate_codec = Codec(ResolutionCandidate, rr_schema.resolution_candidates)
        self._evidence_codec = Codec(
            ResolutionEvidenceLink,
            rr_schema.resolution_candidate_evidence,
        )
        self._review_codec = Codec(ReviewItem, rr_schema.review_items)
        self._decision_codec = Codec(ReviewDecision, rr_schema.review_decisions)

    def create_or_get_candidate(
        self,
        candidate: ResolutionCandidate,
        evidence: tuple[ResolutionEvidenceLink, ...],
    ) -> ResolutionCandidate:
        """Atomically validate and insert one immutable candidate snapshot."""

        self._validate_evidence_shape(candidate, evidence)
        with self._engine.begin() as connection:
            self._validate_entity_reference(
                connection,
                candidate.subject_kind,
                candidate.subject_id,
            )
            self._validate_entity_reference(
                connection,
                candidate.candidate_kind,
                candidate.candidate_entity_id,
            )
            for link in evidence:
                self._validate_evidence_reference(connection, candidate, link)

            result = connection.execute(
                insert(rr_schema.resolution_candidates)
                .values(**self._candidate_codec.encode(candidate))
                .prefix_with("OR IGNORE")
            )
            if result.rowcount == 1:
                for link in evidence:
                    connection.execute(
                        insert(rr_schema.resolution_candidate_evidence).values(
                            **self._evidence_codec.encode(link)
                        )
                    )
                return candidate

            persisted = self._candidate_by_snapshot(connection, candidate)
            if persisted is None:
                raise ResolutionReviewStoreError("candidate snapshot could not be persisted")
            expected = replace(candidate, id=persisted.id)
            if persisted != expected:
                raise ResolutionReviewStoreError("candidate snapshot is nondeterministic")
            stored_evidence = self._evidence_for_candidate(connection, persisted.id)
            if _material_descriptors(stored_evidence) != _material_descriptors(evidence):
                raise ResolutionReviewStoreError("candidate evidence is nondeterministic")
            return persisted

    def get_candidate(self, candidate_id: EntityId) -> ResolutionCandidate | None:
        with self._engine.connect() as connection:
            return self._get_candidate(connection, candidate_id)

    def list_candidates_for_subject(
        self,
        subject_kind: EntityKind,
        subject_id: EntityId,
        *,
        limit: int = 100,
        after: tuple[datetime, EntityId] | None = None,
    ) -> ResolutionCandidatePage:
        _validate_limit(limit, MAX_RESOLUTION_PAGE)
        table = rr_schema.resolution_candidates
        statement = select(table).where(
            table.c.subject_kind == subject_kind.value,
            table.c.subject_id == str(subject_id),
        )
        if after is not None:
            encoded = _required_datetime(after[0])
            statement = statement.where(
                or_(
                    table.c.created_at > encoded,
                    and_(table.c.created_at == encoded, table.c.id > str(after[1])),
                )
            )
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    statement.order_by(table.c.created_at, table.c.id).limit(limit + 1)
                )
                .mappings()
                .all()
            )
        has_more = len(rows) > limit
        items = tuple(self._candidate_codec.decode(row) for row in rows[:limit])
        cursor = None
        if has_more and items:
            cursor = (items[-1].created_at, items[-1].id)
        return ResolutionCandidatePage(items=items, next_cursor=cursor)

    def list_evidence(
        self,
        candidate_id: EntityId,
        *,
        limit: int = MAX_RESOLUTION_EVIDENCE,
        after_ordinal: int = -1,
    ) -> tuple[ResolutionEvidenceLink, ...]:
        _validate_limit(limit, MAX_RESOLUTION_EVIDENCE)
        if after_ordinal < -1:
            raise ValueError("after_ordinal must be at least -1")
        table = rr_schema.resolution_candidate_evidence
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.resolution_candidate_id == str(candidate_id),
                        table.c.ordinal > after_ordinal,
                    )
                    .order_by(table.c.ordinal)
                    .limit(limit + 1)
                )
                .mappings()
                .all()
            )
        if len(rows) > limit:
            raise ResolutionReviewStoreError("candidate evidence exceeds the requested bound")
        return tuple(self._evidence_codec.decode(row) for row in rows)

    def enqueue_or_get_review(self, item: ReviewItem) -> ReviewItem:
        """Insert one exact review case without overwriting prior history."""

        if item.review_type is not ReviewType.AUTHORITY_RESOLUTION:
            raise ResolutionReviewStoreError("EB-02 only accepts authority review items")
        if item.candidate_kind is not ReviewCandidateKind.RESOLUTION_CANDIDATE:
            raise ResolutionReviewStoreError("authority review requires a resolution candidate")
        if item.state is not ReviewItemState.PENDING:
            raise ResolutionReviewStoreError("new review items must be PENDING")
        with self._engine.begin() as connection:
            candidate = self._get_candidate(connection, item.candidate_id)
            if candidate is None:
                raise ResolutionReviewStoreError("resolution candidate does not exist")
            _require_item_matches_candidate(item, candidate)
            if candidate.disposition is ResolutionDisposition.AUTO_SAFE:
                raise ResolutionReviewStoreError("AUTO_SAFE candidates must not enter review")
            result = connection.execute(
                insert(rr_schema.review_items)
                .values(**self._review_codec.encode(item))
                .prefix_with("OR IGNORE")
            )
            if result.rowcount == 1:
                return item
            persisted = self._review_by_exact_case(connection, item)
            if persisted is None:
                raise ResolutionReviewStoreError("review item could not be persisted")
            expected = replace(item, id=persisted.id, producer_version=persisted.producer_version)
            if persisted != expected:
                raise ResolutionReviewStoreError("review case is nondeterministic")
            return persisted

    def list_queue(
        self,
        *,
        limit: int = 100,
        after: tuple[datetime, EntityId] | None = None,
        review_type: ReviewType | None = None,
    ) -> ReviewItemPage:
        _validate_limit(limit, MAX_REVIEW_PAGE)
        table = rr_schema.review_items
        statement = select(table).where(
            table.c.state.in_([ReviewItemState.PENDING.value, ReviewItemState.DEFERRED.value])
        )
        if review_type is not None:
            statement = statement.where(table.c.review_type == review_type.value)
        if after is not None:
            encoded = _required_datetime(after[0])
            statement = statement.where(
                or_(
                    table.c.created_at > encoded,
                    and_(table.c.created_at == encoded, table.c.id > str(after[1])),
                )
            )
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    statement.order_by(table.c.created_at, table.c.id).limit(limit + 1)
                )
                .mappings()
                .all()
            )
        has_more = len(rows) > limit
        items = tuple(self._review_codec.decode(row) for row in rows[:limit])
        cursor = None
        if has_more and items:
            cursor = (items[-1].created_at, items[-1].id)
        return ReviewItemPage(items=items, next_cursor=cursor)

    def get_review_item(self, item_id: EntityId) -> ReviewItem | None:
        """Return one review item without resolving private Evidence values."""

        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(rr_schema.review_items).where(
                        rr_schema.review_items.c.id == str(item_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._review_codec.decode(row)

    def append_decision(
        self,
        decision: ReviewDecision,
        *,
        expected_latest_decision_id: EntityId | None,
    ) -> ReviewDecision:
        """Append one optimistically fenced decision and update only item state."""

        with self._engine.begin() as connection:
            existing = self._get_decision(connection, decision.id)
            if existing is not None:
                if existing != decision:
                    raise ResolutionReviewStoreError("decision id has different content")
                return existing
            table = rr_schema.review_items
            fence = connection.execute(
                update(table)
                .where(
                    table.c.id == str(decision.review_item_id),
                    table.c.evidence_fingerprint == decision.evidence_fingerprint,
                    table.c.candidate_set_fingerprint == decision.candidate_set_fingerprint,
                    table.c.decision_compatibility_version
                    == decision.decision_compatibility_version,
                )
                .values(state=table.c.state)
            )
            if fence.rowcount != 1:
                raise ResolutionReviewStoreError("review item snapshot is stale")
            latest = self._latest_decision(connection, decision.review_item_id)
            latest_id = None if latest is None else latest.id
            if latest_id != expected_latest_decision_id:
                raise ResolutionReviewStoreError("review decision history changed")
            expected_sequence = 1 if latest is None else latest.sequence_no + 1
            if decision.sequence_no != expected_sequence:
                raise ResolutionReviewStoreError("review decision sequence is not current")
            connection.execute(
                insert(rr_schema.review_decisions).values(**self._decision_codec.encode(decision))
            )
            state = (
                ReviewItemState.DEFERRED
                if decision.decision is ReviewDecisionValue.DEFER
                else ReviewItemState.DECIDED
            )
            connection.execute(
                update(table)
                .where(table.c.id == str(decision.review_item_id))
                .values(state=state.value)
            )
            return decision

    def get_effective_decision(self, item_id: EntityId) -> ReviewDecision | None:
        with self._engine.connect() as connection:
            return self._latest_decision(connection, item_id)

    def list_history(
        self,
        item_id: EntityId,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> tuple[ReviewDecision, ...]:
        _validate_limit(limit, MAX_REVIEW_PAGE)
        if after_sequence < 0:
            raise ValueError("after_sequence must not be negative")
        table = rr_schema.review_decisions
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.review_item_id == str(item_id),
                        table.c.sequence_no > after_sequence,
                    )
                    .order_by(table.c.sequence_no)
                    .limit(limit + 1)
                )
                .mappings()
                .all()
            )
        if len(rows) > limit:
            raise ResolutionReviewStoreError("review history exceeds the requested bound")
        return tuple(self._decision_codec.decode(row) for row in rows)

    def find_reusable_decision(
        self,
        candidate: ResolutionCandidate,
    ) -> ReviewDecision | None:
        """Find ACCEPT/REJECT reuse while ignoring technical resolver versions."""

        candidates = rr_schema.resolution_candidates
        items = rr_schema.review_items
        decisions = rr_schema.review_decisions
        statement = (
            select(decisions)
            .join(items, items.c.id == decisions.c.review_item_id)
            .join(candidates, candidates.c.id == items.c.candidate_id)
            .where(
                items.c.review_type == ReviewType.AUTHORITY_RESOLUTION.value,
                candidates.c.subject_kind == candidate.subject_kind.value,
                candidates.c.subject_id == str(candidate.subject_id),
                candidates.c.candidate_kind == candidate.candidate_kind.value,
                candidates.c.candidate_entity_id == str(candidate.candidate_entity_id),
                candidates.c.resolver_name == candidate.resolver_name,
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

    def _validate_evidence_shape(
        self,
        candidate: ResolutionCandidate,
        evidence: tuple[ResolutionEvidenceLink, ...],
    ) -> None:
        if not evidence or len(evidence) > MAX_RESOLUTION_EVIDENCE:
            raise ResolutionReviewStoreError("candidate evidence count is outside bounds")
        if tuple(link.ordinal for link in evidence) != tuple(range(len(evidence))):
            raise ResolutionReviewStoreError("candidate evidence ordinals must be contiguous")
        if any(link.resolution_candidate_id != candidate.id for link in evidence):
            raise ResolutionReviewStoreError("candidate evidence belongs to another candidate")
        if any(link.asserted_entity_kind is not candidate.candidate_kind for link in evidence):
            raise ResolutionReviewStoreError("candidate evidence targets another identity level")
        if resolution_evidence_fingerprint(evidence) != candidate.evidence_fingerprint:
            raise ResolutionReviewStoreError("candidate evidence fingerprint does not match")
        if candidate.disposition is ResolutionDisposition.AUTO_SAFE and not any(
            link.evidence_kind is ResolutionEvidenceKind.REVIEW_DECISION for link in evidence
        ):
            raise ResolutionReviewStoreError("AUTO_SAFE requires prior accepted local knowledge")

    def _validate_evidence_reference(
        self,
        connection: Connection,
        candidate: ResolutionCandidate,
        link: ResolutionEvidenceLink,
    ) -> None:
        table = _EVIDENCE_TABLES[link.evidence_kind]
        row = connection.execute(
            select(table.c.id).where(table.c.id == str(link.evidence_id))
        ).scalar_one_or_none()
        if row is None:
            raise ResolutionReviewStoreError("resolution evidence record does not exist")
        if link.evidence_kind is ResolutionEvidenceKind.REVIEW_DECISION:
            decision = self._get_decision(connection, link.evidence_id)
            if decision is None or decision.decision is not ReviewDecisionValue.ACCEPT:
                raise ResolutionReviewStoreError("AUTO_SAFE evidence must be an ACCEPT decision")
            if not self._accepted_decision_matches_candidate(
                connection,
                decision,
                candidate,
            ):
                raise ResolutionReviewStoreError("ACCEPT decision is not compatible with candidate")

    @staticmethod
    def _accepted_decision_matches_candidate(
        connection: Connection,
        decision: ReviewDecision,
        candidate: ResolutionCandidate,
    ) -> bool:
        items = rr_schema.review_items
        candidates = rr_schema.resolution_candidates
        row = connection.execute(
            select(items.c.id)
            .join(candidates, candidates.c.id == items.c.candidate_id)
            .where(
                items.c.id == str(decision.review_item_id),
                items.c.review_type == ReviewType.AUTHORITY_RESOLUTION.value,
                candidates.c.subject_kind == candidate.subject_kind.value,
                candidates.c.subject_id == str(candidate.subject_id),
                candidates.c.candidate_kind == candidate.candidate_kind.value,
                candidates.c.candidate_entity_id == str(candidate.candidate_entity_id),
                candidates.c.resolver_name == candidate.resolver_name,
                items.c.decision_compatibility_version == candidate.decision_compatibility_version,
                items.c.evidence_fingerprint == candidate.evidence_fingerprint,
                items.c.candidate_set_fingerprint == candidate.candidate_set_fingerprint,
            )
        ).scalar_one_or_none()
        return row is not None

    def _validate_entity_reference(
        self,
        connection: Connection,
        kind: EntityKind,
        entity_id: EntityId,
    ) -> None:
        table = _ENTITY_TABLES.get(kind)
        if table is None:
            raise ResolutionReviewStoreError("entity kind is unavailable for resolution")
        row = connection.execute(
            select(table.c.id).where(table.c.id == str(entity_id))
        ).scalar_one_or_none()
        if row is None:
            raise ResolutionReviewStoreError("resolution entity does not exist")

    def _get_candidate(
        self,
        connection: Connection,
        candidate_id: EntityId,
    ) -> ResolutionCandidate | None:
        row = (
            connection.execute(
                select(rr_schema.resolution_candidates).where(
                    rr_schema.resolution_candidates.c.id == str(candidate_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else self._candidate_codec.decode(row)

    def _candidate_by_snapshot(
        self,
        connection: Connection,
        candidate: ResolutionCandidate,
    ) -> ResolutionCandidate | None:
        table = rr_schema.resolution_candidates
        row = (
            connection.execute(
                select(table).where(
                    table.c.subject_kind == candidate.subject_kind.value,
                    table.c.subject_id == str(candidate.subject_id),
                    table.c.candidate_kind == candidate.candidate_kind.value,
                    table.c.candidate_entity_id == str(candidate.candidate_entity_id),
                    table.c.resolver_name == candidate.resolver_name,
                    table.c.resolver_version == candidate.resolver_version,
                    table.c.decision_compatibility_version
                    == candidate.decision_compatibility_version,
                    table.c.evidence_fingerprint == candidate.evidence_fingerprint,
                    table.c.candidate_set_fingerprint == candidate.candidate_set_fingerprint,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else self._candidate_codec.decode(row)

    def _evidence_for_candidate(
        self,
        connection: Connection,
        candidate_id: EntityId,
    ) -> tuple[ResolutionEvidenceLink, ...]:
        table = rr_schema.resolution_candidate_evidence
        rows = (
            connection.execute(
                select(table)
                .where(table.c.resolution_candidate_id == str(candidate_id))
                .order_by(table.c.ordinal)
            )
            .mappings()
            .all()
        )
        return tuple(self._evidence_codec.decode(row) for row in rows)

    def _review_by_exact_case(
        self,
        connection: Connection,
        item: ReviewItem,
    ) -> ReviewItem | None:
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

    def _latest_decision(
        self,
        connection: Connection,
        item_id: EntityId,
    ) -> ReviewDecision | None:
        table = rr_schema.review_decisions
        row = (
            connection.execute(
                select(table)
                .where(table.c.review_item_id == str(item_id))
                .order_by(table.c.sequence_no.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else self._decision_codec.decode(row)

    def _get_decision(
        self,
        connection: Connection,
        decision_id: EntityId,
    ) -> ReviewDecision | None:
        row = (
            connection.execute(
                select(rr_schema.review_decisions).where(
                    rr_schema.review_decisions.c.id == str(decision_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else self._decision_codec.decode(row)


def _require_item_matches_candidate(
    item: ReviewItem,
    candidate: ResolutionCandidate,
) -> None:
    if item.subject_kind is not candidate.subject_kind or item.subject_id != candidate.subject_id:
        raise ResolutionReviewStoreError("review subject does not match candidate")
    if (
        item.decision_compatibility_version != candidate.decision_compatibility_version
        or item.evidence_fingerprint != candidate.evidence_fingerprint
        or item.candidate_set_fingerprint != candidate.candidate_set_fingerprint
    ):
        raise ResolutionReviewStoreError("review snapshot does not match candidate")


def _material_descriptors(
    evidence: tuple[ResolutionEvidenceLink, ...],
) -> set[tuple[str, str, str, str]]:
    return {
        (
            link.evidence_kind.value,
            link.evidence_role.value,
            link.asserted_entity_kind.value,
            link.material_fingerprint,
        )
        for link in evidence
    }


def _validate_limit(limit: int, maximum: int) -> None:
    if limit < 1 or limit > maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")


def _required_datetime(value: datetime) -> str:
    encoded = datetime_to_db(value)
    if encoded is None:
        raise AssertionError("non-null datetime encoded as None")
    return encoded


_ENTITY_TABLES = {
    EntityKind.FILE: schema.file_records,
    EntityKind.FILE_OBSERVATION: schema.file_observations,
    EntityKind.AGENT: schema.agents,
    EntityKind.WORK: schema.works,
    EntityKind.EDITION: schema.editions,
    EntityKind.SERIES: schema.series,
}

_EVIDENCE_TABLES = {
    ResolutionEvidenceKind.VALUE_ASSERTION: schema.value_assertions,
    ResolutionEvidenceKind.TOOL_RESULT: schema.tool_results,
    ResolutionEvidenceKind.FINGERPRINT: schema.fingerprints,
    ResolutionEvidenceKind.EXTERNAL_IDENTIFIER: schema.external_identifiers,
    ResolutionEvidenceKind.CLASSIFICATION_ASSERTION: schema.classification_assertions,
    ResolutionEvidenceKind.REVIEW_DECISION: rr_schema.review_decisions,
}
