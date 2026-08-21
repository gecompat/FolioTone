from __future__ import annotations

import ast
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from test_consolidation_planner import (
    _clock,
    _inputs,
    _with_candidate_review,
)

from foliotone.consolidation import (
    ConsolidationDependencyState,
    ConsolidationFileRole,
    ConsolidationPlanStatus,
    ConsolidationReviewState,
    build_consolidation_plan,
    consolidation_plan_content_hash,
)
from foliotone.core import EntityId
from foliotone.quarantine import (
    QUARANTINE_AUTHORIZATION_PROFILE,
    QuarantineAuthorizationBlockerCode,
    QuarantineEligibilityStatus,
    QuarantineRunStatus,
    build_quarantine_authorization,
)


def _approved_plan():
    return build_consolidation_plan(
        _with_candidate_review(_inputs(), ConsolidationReviewState.ACCEPTED),
        clock=_clock,
    )


def _assessment(plan=None, **changes):
    plan = _approved_plan() if plan is None else plan
    assert plan.keeper is not None and plan.candidate is not None
    values = {
        "plan": plan,
        "current_keeper": plan.keeper,
        "current_candidate": plan.candidate,
        "current_dependencies": plan.dependencies,
        "current_reviews": plan.required_reviews,
        "quarantine_capability_id": EntityId.parse(
            "90000000-0000-0000-0000-000000000001"
        ),
        "authorized_at": _clock(),
        "expires_at": _clock() + timedelta(minutes=15),
    }
    values.update(changes)
    return build_quarantine_authorization(**values)


def test_approved_current_plan_builds_deterministic_path_free_authorization() -> None:
    first = _assessment()
    second = _assessment()

    assert first == second
    assert first.status is QuarantineEligibilityStatus.ELIGIBLE
    assert first.blockers == ()
    assert first.authorization is not None
    assert first.authorization.profile == QUARANTINE_AUTHORIZATION_PROFILE
    assert first.authorization.expires_at - first.authorization.authorized_at == timedelta(
        minutes=15
    )
    rendered = repr(first.authorization)
    assert "a" * 64 not in rendered
    assert "Synthetic" not in rendered


@pytest.mark.parametrize(
    ("change", "expected"),
    (
        (
            {"expires_at": _clock() + timedelta(minutes=15, microseconds=1)},
            QuarantineAuthorizationBlockerCode.AUTHORIZATION_WINDOW_INVALID,
        ),
        (
            {"quarantine_capability_id": "not-an-id"},
            QuarantineAuthorizationBlockerCode.CAPABILITY_INVALID,
        ),
    ),
)
def test_invalid_window_and_capability_are_blocked(change, expected) -> None:
    assessment = _assessment(**change)
    assert assessment.status is QuarantineEligibilityStatus.BLOCKED
    assert expected in assessment.blockers
    assert assessment.authorization is None


def test_stale_current_evidence_and_nonapproved_plan_are_blocked() -> None:
    plan = _approved_plan()
    assert plan.keeper is not None
    stale_keeper = replace(plan.keeper, expected_size_bytes=plan.keeper.expected_size_bytes + 1)
    stale = _assessment(plan, current_keeper=stale_keeper)
    assert stale.blockers == (
        QuarantineAuthorizationBlockerCode.CURRENT_EVIDENCE_MISMATCH,
    )

    blocked_plan = replace(plan, status=ConsolidationPlanStatus.BLOCKED)
    blocked_plan = replace(
        blocked_plan, content_hash=consolidation_plan_content_hash(blocked_plan)
    )
    blocked = _assessment(blocked_plan)
    assert QuarantineAuthorizationBlockerCode.PLAN_NOT_APPROVED in blocked.blockers


def test_candidate_dependency_and_review_must_remain_safe() -> None:
    plan = _approved_plan()
    changed_dependencies = tuple(
        replace(
            item,
            state=ConsolidationDependencyState.UNKNOWN,
            snapshot_kind="proof",
            snapshot_id=plan.id,
        )
        if item.file_role is ConsolidationFileRole.CANDIDATE
        and item.kind.value == "ARCHIVE"
        else item
        for item in plan.dependencies
    )
    changed_plan = replace(plan, dependencies=changed_dependencies)
    changed_plan = replace(
        changed_plan, content_hash=consolidation_plan_content_hash(changed_plan)
    )
    dependency = _assessment(
        changed_plan, current_dependencies=changed_plan.dependencies
    )
    assert (
        QuarantineAuthorizationBlockerCode.DEPENDENCY_NOT_KNOWN_NONE
        in dependency.blockers
    )

    incomplete_plan = replace(plan, dependencies=plan.dependencies[:-1])
    incomplete_plan = replace(
        incomplete_plan,
        content_hash=consolidation_plan_content_hash(incomplete_plan),
    )
    incomplete = _assessment(
        incomplete_plan,
        current_dependencies=incomplete_plan.dependencies,
    )
    assert (
        QuarantineAuthorizationBlockerCode.DEPENDENCY_NOT_KNOWN_NONE
        in incomplete.blockers
    )

    rejected_reviews = tuple(
        replace(
            item,
            state=ConsolidationReviewState.REJECTED,
        )
        for item in plan.required_reviews
    )
    rejected_plan = replace(plan, required_reviews=rejected_reviews)
    rejected_plan = replace(
        rejected_plan, content_hash=consolidation_plan_content_hash(rejected_plan)
    )
    review = _assessment(rejected_plan, current_reviews=rejected_reviews)
    assert QuarantineAuthorizationBlockerCode.REVIEWS_NOT_ACCEPTED in review.blockers

    foreign_reviews = (
        replace(plan.required_reviews[0], producer_name="foreign-producer"),
        plan.required_reviews[1],
    )
    foreign_plan = replace(plan, required_reviews=foreign_reviews)
    foreign_plan = replace(
        foreign_plan,
        content_hash=consolidation_plan_content_hash(foreign_plan),
    )
    foreign = _assessment(foreign_plan, current_reviews=foreign_reviews)
    assert QuarantineAuthorizationBlockerCode.REVIEWS_NOT_ACCEPTED in foreign.blockers


def test_precondition_material_is_rebound_to_endpoints_dependencies_and_reviews() -> None:
    plan = _approved_plan()
    drifted = replace(
        plan.preconditions[0],
        expected_size_bytes=plan.preconditions[0].expected_size_bytes + 1,
    )
    changed_plan = replace(
        plan,
        preconditions=(drifted, *plan.preconditions[1:]),
    )
    changed_plan = replace(
        changed_plan,
        content_hash=consolidation_plan_content_hash(changed_plan),
    )
    assessment = _assessment(changed_plan)
    assert (
        QuarantineAuthorizationBlockerCode.PRECONDITIONS_INCOMPLETE
        in assessment.blockers
    )


def test_direct_authorization_tamper_and_run_status_literals_fail_closed() -> None:
    assessment = _assessment()
    assert assessment.authorization is not None
    with pytest.raises(ValueError, match="material is inconsistent"):
        replace(
            assessment.authorization,
            candidate_full_sha256="b" * 64,
        )
    assert tuple(item.value for item in QuarantineRunStatus) == (
        "PREPARED",
        "MOVED",
        "VERIFIED",
        "COMPLETED",
        "STALE",
        "TOOL_UNAVAILABLE",
        "VALIDATION_FAILED",
        "FENCED_OUT",
        "MANUAL_REVIEW",
        "CANCELLED",
    )


def test_quarantine_contract_package_has_no_io_or_mutation_surface() -> None:
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse(
        (root / "src/foliotone/quarantine/contracts.py").read_text(encoding="utf-8")
    )
    forbidden_modules = {"os", "pathlib", "shutil", "subprocess", "sqlalchemy"}
    forbidden_calls = {
        "open",
        "remove",
        "rename",
        "replace",
        "unlink",
        "move",
        "rmtree",
        "run",
        "Popen",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(
                alias.name.split(".", 1)[0] not in forbidden_modules
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".", 1)[0] not in forbidden_modules
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls
