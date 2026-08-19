import json
from datetime import UTC, datetime
from uuid import UUID

from foliotone.consolidation import (
    CONSOLIDATION_PLAN_PROFILE,
    CONSOLIDATION_PLAN_SERIALIZER_VERSION,
    CONSOLIDATION_PLAN_VERSION,
    ConsolidationBlocker,
    ConsolidationBlockerCode,
    ConsolidationEvidenceKind,
    ConsolidationEvidenceReference,
    ConsolidationEvidenceRole,
    ConsolidationExecutionState,
    ConsolidationPlan,
    ConsolidationPlanStatus,
)
from foliotone.core import EntityId
from foliotone.persistence.consolidation_report import ConsolidationPlanReport

_STAMP = datetime(2026, 8, 19, tzinfo=UTC)
_HASH = "a" * 64


def _id(number: int) -> EntityId:
    return EntityId(UUID(f"00000000-0000-0000-0000-{number:012d}"))


def test_consolidation_plan_report_payload_is_path_free_and_keep_minimal_contract() -> None:
    first = ConsolidationEvidenceReference(
        ConsolidationEvidenceKind.TOOL_RESULT,
        "zeta",
        ConsolidationEvidenceRole.DEPENDENCY,
        "b" * 64,
    )
    second = ConsolidationEvidenceReference(
        ConsolidationEvidenceKind.FINGERPRINT,
        "private/path/book.epub",
        ConsolidationEvidenceRole.IDENTITY,
        "c" * 64,
    )
    plan = ConsolidationPlan(
        id=_id(1),
        profile=CONSOLIDATION_PLAN_PROFILE,
        plan_version=CONSOLIDATION_PLAN_VERSION,
        serializer_version=CONSOLIDATION_PLAN_SERIALIZER_VERSION,
        scan_root_id=_id(2),
        source_scan_run_id=_id(3),
        identity=None,
        keeper=None,
        candidate=None,
        keep_preference=None,
        consolidation_candidate=None,
        dependencies=(),
        quality_evidence=(),
        required_reviews=(),
        preconditions=(),
        future_operation_intents=(),
        blockers=(
            ConsolidationBlocker(
                ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE,
                (first, second),
            ),
            ConsolidationBlocker(
                ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE,
                (
                    ConsolidationEvidenceReference(
                        ConsolidationEvidenceKind.FINGERPRINT,
                        "alpha",
                        ConsolidationEvidenceRole.IDENTITY,
                        "d" * 64,
                    ),
                ),
            ),
            ConsolidationBlocker(ConsolidationBlockerCode.QUALITY_EVIDENCE_INCOMPLETE),
        ),
        status=ConsolidationPlanStatus.BLOCKED,
        execution_state=ConsolidationExecutionState.NOT_EXECUTABLE,
        content_hash=_HASH,
        created_at=_STAMP,
    )

    payload = ConsolidationPlanReport.from_plan(plan).payload()
    encoded = json.dumps(payload, sort_keys=True)

    assert payload == {
        "schema_version": 1,
        "command": "ebook-consolidation-report",
        "ok": True,
        "plan_id": str(plan.id),
        "profile": plan.profile,
        "status": "BLOCKED",
        "execution_state": "NOT_EXECUTABLE",
        "content_hash": _HASH,
        "counts": {
            "dependencies": 0,
            "quality_evidence": 0,
            "required_reviews": 0,
            "preconditions": 0,
            "future_operation_intents": 0,
            "blockers": 3,
            "blocker_evidence_refs": 3,
            "review_items": 0,
            "decisions": 0,
        },
        "blocker_codes": [
            "IDENTITY_NOT_ACTIONABLE",
            "IDENTITY_NOT_ACTIONABLE",
            "QUALITY_EVIDENCE_INCOMPLETE",
        ],
        "keeper_file_id": None,
        "candidate_file_id": None,
    }
    assert "private/path" not in encoded
    assert ("b" * 64) not in encoded
    assert ("c" * 64) not in encoded
    assert "scan_root_id" not in payload
    assert "source_scan_run_id" not in payload
