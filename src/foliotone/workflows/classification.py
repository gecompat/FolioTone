"""Bounded offline reprojection of immutable book-classification evidence."""

from __future__ import annotations

from dataclasses import dataclass

from foliotone.classification.contracts import BOOK_CLASSIFICATION_ASSERTION_PROFILE
from foliotone.classification.projection import (
    BOOK_CLASSIFICATION_PROJECTION_PROFILE,
    BookClassificationProjection,
    reduce_book_classification_assertions,
)
from foliotone.core import EntityId, EntityKind
from foliotone.persistence.classification import SQLiteClassificationStore

CLASSIFICATION_REPROJECTION_LIMIT = 500


class ClassificationWorkflowError(RuntimeError):
    """A bounded classification reprojection cannot safely be represented."""


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
