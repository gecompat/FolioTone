from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any, cast

import pytest

from foliotone.core import EntityId
from foliotone.ebook_rename import (
    EbookRenameConfirmationError,
    EbookRenameReconciliationOutcome,
    EbookRenameRunStatus,
    build_ebook_rename_reconciliation,
    ebook_rename_confirmation_digest,
    ebook_rename_confirmation_text,
)
from foliotone.workflows.ebook_rename_operation import (
    EbookRenameOperatorError,
    EbookRenameOperatorErrorCode,
    EbookRenameOperatorService,
)
from tests.unit.test_ebook_rename_authority import NOW, _material


def _reconciliation(outcome: EbookRenameReconciliationOutcome):
    plan, _capability, _probe, preparation, authorization = _material()
    source_observation_id = (
        None if outcome is EbookRenameReconciliationOutcome.VERIFIED else EntityId.new()
    )
    target_file_id = (
        EntityId.new() if outcome is EbookRenameReconciliationOutcome.VERIFIED else None
    )
    target_observation_id = (
        EntityId.new() if outcome is EbookRenameReconciliationOutcome.VERIFIED else None
    )
    target_scan_event_id = (
        EntityId.new() if outcome is EbookRenameReconciliationOutcome.VERIFIED else None
    )
    return build_ebook_rename_reconciliation(
        run_id=EntityId.new(),
        authorization_id=authorization.id,
        authorization_content_hash=authorization.content_hash,
        preparation_id=preparation.id,
        preparation_content_hash=preparation.content_hash,
        outcome=outcome,
        scan_run_id=EntityId.new(),
        source_file_id=plan.candidate.sources[0].file_id,
        source_before_observation_id=preparation.source_observation_id,
        source_scan_event_id=EntityId.new(),
        source_observation_id=source_observation_id,
        target_file_id=target_file_id,
        target_observation_id=target_observation_id,
        target_scan_event_id=target_scan_event_id,
        collection_state_snapshot_id=EntityId.new(),
        collection_state_content_digest="1" * 64,
        expected_full_sha256=preparation.source_full_sha256,
        expected_size_bytes=preparation.source_size_bytes,
        target_absence_fingerprint=preparation.target_absence_fingerprint,
        physical_confirmation_digest="2" * 64,
        reconciled_at=NOW + timedelta(minutes=2),
    )


def test_confirmation_is_exact_deterministic_and_private() -> None:
    plan, _capability, _probe, _preparation, authorization = _material()
    prompt = f"CONFIRM EBOOK RENAME {authorization.id}"

    assert ebook_rename_confirmation_text(authorization) == prompt
    first = ebook_rename_confirmation_digest(authorization, prompt)
    assert ebook_rename_confirmation_digest(authorization, prompt) == first
    assert len(first) == 64
    assert plan.content_hash not in prompt

    for invalid in (f"{prompt} ", f"{prompt}\n", f"{prompt}\r", "CONFIRM EBOOK RENAME"):
        with pytest.raises(EbookRenameConfirmationError):
            ebook_rename_confirmation_digest(authorization, invalid)


@pytest.mark.parametrize("outcome", tuple(EbookRenameReconciliationOutcome))
def test_reconciliation_is_deterministic_and_keeps_private_binders_out_of_repr(
    outcome: EbookRenameReconciliationOutcome,
) -> None:
    value = _reconciliation(outcome)

    rebuilt = build_ebook_rename_reconciliation(
        run_id=value.run_id,
        authorization_id=value.authorization_id,
        authorization_content_hash=value.authorization_content_hash,
        preparation_id=value.preparation_id,
        preparation_content_hash=value.preparation_content_hash,
        outcome=value.outcome,
        scan_run_id=value.scan_run_id,
        source_file_id=value.source_file_id,
        source_before_observation_id=value.source_before_observation_id,
        source_scan_event_id=value.source_scan_event_id,
        source_observation_id=value.source_observation_id,
        target_file_id=value.target_file_id,
        target_observation_id=value.target_observation_id,
        target_scan_event_id=value.target_scan_event_id,
        collection_state_snapshot_id=value.collection_state_snapshot_id,
        collection_state_content_digest=value.collection_state_content_digest,
        expected_full_sha256=value.expected_full_sha256,
        expected_size_bytes=value.expected_size_bytes,
        target_absence_fingerprint=value.target_absence_fingerprint,
        physical_confirmation_digest=value.physical_confirmation_digest,
        reconciled_at=value.reconciled_at,
    )

    assert rebuilt == value
    rendered = repr(value)
    for private in (
        value.authorization_content_hash,
        value.preparation_content_hash,
        value.expected_full_sha256,
        value.target_absence_fingerprint,
        value.physical_confirmation_digest,
        value.collection_state_content_digest,
        value.content_hash,
    ):
        assert private not in rendered


def test_reconciliation_rejects_mixed_forward_and_recovery_evidence() -> None:
    verified = _reconciliation(EbookRenameReconciliationOutcome.VERIFIED)
    recovered = _reconciliation(EbookRenameReconciliationOutcome.RECOVERED)

    with pytest.raises(ValueError, match="outcome shape"):
        replace(verified, source_observation_id=EntityId.new())
    with pytest.raises(ValueError, match="outcome shape"):
        replace(recovered, target_file_id=EntityId.new())
    with pytest.raises(ValueError, match="content hash differs"):
        replace(verified, content_hash="f" * 64)


def test_terminal_recovered_event_without_reconciliation_fails_closed() -> None:
    service = object.__new__(EbookRenameOperatorService)

    with pytest.raises(EbookRenameOperatorError, match="^RECONCILIATION_PENDING$") as failure:
        service._prepare_handoff(
            cast(Any, object()),
            EbookRenameRunStatus.RECOVERED,
            cast(Any, object()),
        )

    assert failure.value.code is EbookRenameOperatorErrorCode.RECONCILIATION_PENDING
