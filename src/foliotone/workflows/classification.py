"""Bounded offline reprojection of immutable book-classification evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, select

from foliotone.classification.contracts import (
    BOOK_CLASSIFICATION_ASSERTION_PROFILE,
    ClassificationDimension,
)
from foliotone.classification.projection import (
    BOOK_CLASSIFICATION_PROJECTION_PROFILE,
    BookClassificationProjection,
    reduce_book_classification_assertions,
)
from foliotone.core import EntityId, EntityKind
from foliotone.persistence import classification_schema
from foliotone.persistence.classification import (
    ClassificationStoreError,
    SQLiteClassificationStore,
)

CLASSIFICATION_REPROJECTION_LIMIT = 500


class ClassificationWorkflowError(RuntimeError):
    """A bounded classification reprojection cannot safely be represented."""


class ClassificationReportError(RuntimeError):
    """A read-only classification summary cannot safely be represented."""


@dataclass(frozen=True, slots=True)
class ClassificationFacetReport:
    """Validated path-free summary of one canonical facet."""

    dimension: str
    status: str
    value_count: int
    conflict: str | None

    def __post_init__(self) -> None:
        if self.dimension not in {item.value for item in ClassificationDimension}:
            raise ValueError("unsupported classification facet")
        if self.status not in {"EMPTY", "PROJECTED", "CONFLICT"}:
            raise ValueError("unsupported classification facet status")
        if isinstance(self.value_count, bool) or not isinstance(self.value_count, int):
            raise ValueError("classification facet count must be an integer")
        if self.value_count < 0:
            raise ValueError("classification facet count must be nonnegative")
        if self.status == "EMPTY" and self.value_count != 0:
            raise ValueError("empty facet must have zero values")
        if self.status == "CONFLICT" and self.value_count != 0:
            raise ValueError("conflicted facet must have zero values")
        if self.status == "PROJECTED" and self.value_count <= 0:
            raise ValueError("projected facet must have values")
        if self.status == "PROJECTED" and self.conflict is not None:
            raise ValueError("projected facet cannot have a conflict")
        if self.status == "CONFLICT" and self.conflict not in {
            "MULTIPLE_EXCLUSIVE_VALUES",
            "CARDINALITY_EXCEEDED",
            "CONFIRMED_CONTRADICTION",
        }:
            raise ValueError("conflicted facet requires a conflict code")
        if self.status != "CONFLICT" and self.conflict is not None:
            raise ValueError("only conflicted facets can have a conflict code")

    def payload(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "status": self.status,
            "value_count": self.value_count,
            "conflict": self.conflict,
        }


@dataclass(frozen=True, slots=True)
class ClassificationReportCounts:
    """Validated nonnegative bounded counts for a classification report."""

    facets: int
    projected_values: int
    assertion_links: int
    selected_links: int
    considered_links: int
    conflicting_links: int

    def __post_init__(self) -> None:
        if self.facets != len(ClassificationDimension):
            raise ValueError("classification report must contain exactly seven facets")
        for value in (
            self.facets,
            self.projected_values,
            self.assertion_links,
            self.selected_links,
            self.considered_links,
            self.conflicting_links,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("classification report counts must be nonnegative integers")
        if self.assertion_links != (
            self.selected_links + self.considered_links + self.conflicting_links
        ):
            raise ValueError("classification link counts must balance")

    def payload(self) -> dict[str, int]:
        return {
            "facets": self.facets,
            "projected_values": self.projected_values,
            "assertion_links": self.assertion_links,
            "selected_links": self.selected_links,
            "considered_links": self.considered_links,
            "conflicting_links": self.conflicting_links,
        }


@dataclass(frozen=True, slots=True)
class ClassificationReadOnlyReport:
    """Path-free, bounded projection summary for the CLI."""

    target_kind: str
    target_id: str
    projection_id: str
    assertion_profile_version: str
    projection_profile_version: str
    status: str
    facets: tuple[ClassificationFacetReport, ...]
    counts: ClassificationReportCounts
    truncated: bool = False

    def __post_init__(self) -> None:
        if self.target_kind not in {EntityKind.WORK.value, EntityKind.EDITION.value}:
            raise ValueError("unsupported classification target kind")
        for value in (self.target_id, self.projection_id):
            if str(EntityId.parse(value)) != value:
                raise ValueError("classification IDs must be canonical UUID strings")
        if self.assertion_profile_version != BOOK_CLASSIFICATION_ASSERTION_PROFILE:
            raise ValueError("unsupported assertion profile")
        if self.projection_profile_version != BOOK_CLASSIFICATION_PROJECTION_PROFILE:
            raise ValueError("unsupported projection profile")
        if self.status not in {"EMPTY", "PROJECTED", "REVIEW_REQUIRED"}:
            raise ValueError("unsupported classification projection status")
        if not isinstance(self.truncated, bool):
            raise ValueError("classification truncation marker must be boolean")
        expected = tuple(item.value for item in ClassificationDimension)
        if tuple(item.dimension for item in self.facets) != expected:
            raise ValueError("classification facets must use canonical order")
        if self.counts.facets != len(self.facets):
            raise ValueError("classification facet count does not match facets")

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "command": "ebook-classification-report",
            "ok": True,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "projection_id": self.projection_id,
            "profiles": {
                "assertion": self.assertion_profile_version,
                "projection": self.projection_profile_version,
            },
            "status": self.status,
            "facets": [facet.payload() for facet in self.facets],
            "counts": self.counts.payload(),
            "truncated": self.truncated,
        }


def read_book_classification_report(
    engine: Engine,
    target_kind: EntityKind,
    target_id: EntityId,
    *,
    projection_id: EntityId | None = None,
    projection_profile_version: str = BOOK_CLASSIFICATION_PROJECTION_PROFILE,
) -> ClassificationReadOnlyReport:
    """Read one immutable projection using a real bounded read-only query."""

    if target_kind not in (EntityKind.WORK, EntityKind.EDITION):
        raise ClassificationReportError("classification target kind is unavailable")
    if projection_profile_version != BOOK_CLASSIFICATION_PROJECTION_PROFILE:
        raise ClassificationReportError("unsupported projection profile version")
    projections = classification_schema.book_classification_projections
    with engine.connect() as connection:
        statement = select(projections).where(
            projections.c.target_kind == target_kind.value,
            projections.c.target_id == str(target_id),
            projections.c.projection_profile_version == projection_profile_version,
        )
        if projection_id is not None:
            statement = statement.where(projections.c.id == str(projection_id)).limit(1)
        else:
            statement = statement.order_by(
                projections.c.created_at.desc(), projections.c.id.desc()
            ).limit(1)
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise ClassificationReportError("classification projection unavailable")

        projection_key = str(row["id"])
    try:
        projection = SQLiteClassificationStore(engine).get_projection(
            EntityId.parse(projection_key)
        )
    except (ClassificationStoreError, ValueError) as error:
        raise ClassificationReportError("classification projection is invalid") from error
    if projection is None:
        raise ClassificationReportError("classification projection unavailable")
    if (
        projection.id != EntityId.parse(projection_key)
        or projection.target_kind is not target_kind
        or projection.target_id != target_id
        or projection.projection_profile_version != projection_profile_version
    ):
        raise ClassificationReportError("classification projection binding is invalid")
    facets = tuple(
        ClassificationFacetReport(
            dimension=facet.dimension.value,
            status=facet.status.value,
            value_count=len(facet.values),
            conflict=None if facet.conflict_code is None else facet.conflict_code.value,
        )
        for facet in projection.facets
    )
    if len(facets) != len(ClassificationDimension):
        raise ClassificationReportError("classification projection facets are incomplete")
    link_counts = {
        role: sum(1 for link in projection.assertion_links if link.role.value == role)
        for role in ("SELECTED", "CONSIDERED", "CONFLICTING")
    }
    return ClassificationReadOnlyReport(
        target_kind=str(row["target_kind"]),
        target_id=str(row["target_id"]),
        projection_id=projection_key,
        assertion_profile_version=str(row["assertion_profile_version"]),
        projection_profile_version=str(row["projection_profile_version"]),
        status=str(row["status"]),
        facets=facets,
        counts=ClassificationReportCounts(
            facets=len(facets),
            projected_values=sum(
                item.value_count for item in facets if item.status == "PROJECTED"
            ),
            assertion_links=sum(link_counts.values()),
            selected_links=link_counts["SELECTED"],
            considered_links=link_counts["CONSIDERED"],
            conflicting_links=link_counts["CONFLICTING"],
        ),
    )


@dataclass(frozen=True, slots=True)
class ClassificationReprojectionOutcome:
    """Path-free result of one target-specific immutable reprojection."""

    projection: BookClassificationProjection
    created: bool


class BookClassificationProjectionWorkflow:
    """Compose the pure reducer and insert-only store without source mutation."""

    def __init__(self, store: SQLiteClassificationStore) -> None:
        self._store = store

    def reproject(
        self,
        target_kind: EntityKind,
        target_id: EntityId,
        *,
        assertion_profile_version: str = BOOK_CLASSIFICATION_ASSERTION_PROFILE,
        projection_profile_version: str = BOOK_CLASSIFICATION_PROJECTION_PROFILE,
    ) -> ClassificationReprojectionOutcome:
        """Read at most one complete v1 target set and persist its pure snapshot."""

        if assertion_profile_version != BOOK_CLASSIFICATION_ASSERTION_PROFILE:
            raise ClassificationWorkflowError("unsupported assertion profile version")
        if projection_profile_version != BOOK_CLASSIFICATION_PROJECTION_PROFILE:
            raise ClassificationWorkflowError("unsupported projection profile version")
        try:
            assertions = self._store.list_profiled_for_target(
                target_kind,
                target_id,
                assertion_profile_version=assertion_profile_version,
                limit=CLASSIFICATION_REPROJECTION_LIMIT,
            )
            projection = reduce_book_classification_assertions(
                target_kind=target_kind,
                target_id=target_id,
                assertions=assertions,
            )
            result = self._store.create_or_get_projection_result(projection)
        except (RuntimeError, ValueError) as error:
            raise ClassificationWorkflowError(
                "classification reprojection failed closed"
            ) from error
        return ClassificationReprojectionOutcome(
            projection=result.projection,
            created=result.created,
        )


def reproject_book_classification(
    store: SQLiteClassificationStore,
    target_kind: EntityKind,
    target_id: EntityId,
    *,
    assertion_profile_version: str = BOOK_CLASSIFICATION_ASSERTION_PROFILE,
    projection_profile_version: str = BOOK_CLASSIFICATION_PROJECTION_PROFILE,
) -> ClassificationReprojectionOutcome:
    """Run the bounded v1 classification workflow for exactly one book target."""

    return BookClassificationProjectionWorkflow(store).reproject(
        target_kind,
        target_id,
        assertion_profile_version=assertion_profile_version,
        projection_profile_version=projection_profile_version,
    )
