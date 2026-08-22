"""Public contracts for immutable, non-executable metadata correction planning."""

from foliotone.metadata_correction import contracts as _contracts
from foliotone.metadata_correction.contracts import *  # noqa: F403
from foliotone.metadata_correction.planner import (
    MetadataCorrectionCandidateInputs,
    MetadataCorrectionPlanInputs,
    build_metadata_correction_candidate,
    build_metadata_correction_plan,
    build_metadata_field_correction,
    build_metadata_writer_requirement,
    build_non_executable_metadata_correction_plan,
)
from foliotone.metadata_correction.serialization import (
    canonical_metadata_correction_candidate_payload,
    canonical_metadata_correction_plan_payload,
    metadata_correction_candidate_content_hash,
    metadata_correction_candidate_evidence_fingerprint,
    metadata_correction_candidate_id,
    metadata_correction_plan_content_hash,
    metadata_correction_plan_id,
    metadata_correction_precondition_fingerprint,
    metadata_correction_selected_fields_fingerprint,
    metadata_field_selection_fingerprint,
    metadata_writer_requirement_fingerprint,
    serialize_metadata_correction_candidate,
    serialize_metadata_correction_plan,
)

__all__ = [
    *_contracts.__all__,
    "MetadataCorrectionCandidateInputs",
    "MetadataCorrectionPlanInputs",
    "build_metadata_correction_candidate",
    "build_metadata_correction_plan",
    "build_metadata_field_correction",
    "build_metadata_writer_requirement",
    "build_non_executable_metadata_correction_plan",
    "canonical_metadata_correction_candidate_payload",
    "canonical_metadata_correction_plan_payload",
    "metadata_correction_candidate_content_hash",
    "metadata_correction_candidate_evidence_fingerprint",
    "metadata_correction_candidate_id",
    "metadata_correction_plan_content_hash",
    "metadata_correction_plan_id",
    "metadata_correction_precondition_fingerprint",
    "metadata_correction_selected_fields_fingerprint",
    "metadata_field_selection_fingerprint",
    "metadata_writer_requirement_fingerprint",
    "serialize_metadata_correction_candidate",
    "serialize_metadata_correction_plan",
]
