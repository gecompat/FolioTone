"""Public immutable contracts for non-executable consolidation planning."""

from foliotone.consolidation import contracts as _contracts
from foliotone.consolidation.blockers import (
    ConsolidationBlockerInputs,
    ConsolidationHardBlockerInputs,
    build_consolidation_blockers,
    build_consolidation_hard_blockers,
)
from foliotone.consolidation.contracts import *  # noqa: F403
from foliotone.consolidation.preconditions import (
    ConsolidationFilePreconditionInputs,
    build_consolidation_file_preconditions,
)
from foliotone.consolidation.serialization import (
    canonical_consolidation_plan_payload,
    canonical_plan_bytes,
    compute_consolidation_plan_content_hash,
    consolidation_plan_content_hash,
    serialize_consolidation_plan,
)

__all__ = [
    *_contracts.__all__,
    "canonical_consolidation_plan_payload",
    "canonical_plan_bytes",
    "compute_consolidation_plan_content_hash",
    "consolidation_plan_content_hash",
    "serialize_consolidation_plan",
    "ConsolidationFilePreconditionInputs",
    "build_consolidation_file_preconditions",
    "ConsolidationBlockerInputs",
    "ConsolidationHardBlockerInputs",
    "build_consolidation_blockers",
    "build_consolidation_hard_blockers",
]
