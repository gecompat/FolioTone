"""Multidimensional media classification package."""

from foliotone.classification.contracts import (
    BookClassificationFacet,
    BookClassificationQuery,
    BookClassificationSet,
    ClassificationDimension,
    build_classification_assertions,
    make_classification_dto,
)

__all__ = [
    "BookClassificationFacet",
    "BookClassificationQuery",
    "BookClassificationSet",
    "ClassificationDimension",
    "build_classification_assertions",
    "make_classification_dto",
]
