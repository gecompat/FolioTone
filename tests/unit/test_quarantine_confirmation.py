"""Pure confirmation coverage for one bounded quarantine execution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from foliotone.core import EntityId
from foliotone.quarantine import QuarantineAuthorizationSnapshot
from foliotone.quarantine.confirmation import (
    QuarantineConfirmationError,
    quarantine_confirmation_digest,
    quarantine_confirmation_text,
)
from foliotone.quarantine.contracts import _authorization_content_hash, _authorization_id

NOW = datetime(2026, 8, 23, 11, 0, tzinfo=UTC)
PLAN_ID = EntityId.parse("df000000-0000-0000-0000-000000000001")
CAPABILITY_ID = EntityId.parse("df000000-0000-0000-0000-000000000002")


def test_confirmation_is_exact_path_free_and_time_bound() -> None:
    authorization = _authorization()
    expected = f"CONFIRM QUARANTINE {authorization.id} {PLAN_ID}"

    assert quarantine_confirmation_text(authorization) == expected
    digest = quarantine_confirmation_digest(
        authorization,
        expected,
        confirmed_at=NOW + timedelta(seconds=1),
    )
    later = quarantine_confirmation_digest(
        authorization,
        expected,
        confirmed_at=NOW + timedelta(seconds=2),
    )

    assert len(digest) == 64
    assert digest != later
    assert "epub" not in expected.lower()
    assert "sha256" not in expected.lower()


@pytest.mark.parametrize(
    "supplied",
    (
        "",
        "CONFIRM QUARANTINE",
        f"CONFIRM QUARANTINE {PLAN_ID} {PLAN_ID}",
        f"CONFIRM QUARANTINE  {PLAN_ID}",
    ),
)
def test_confirmation_rejects_every_noncanonical_line(supplied: str) -> None:
    with pytest.raises(QuarantineConfirmationError, match="CONFIRMATION_INVALID"):
        quarantine_confirmation_digest(
            _authorization(),
            supplied,
            confirmed_at=NOW,
        )


@pytest.mark.parametrize(
    "confirmed_at",
    (NOW - timedelta(seconds=1), NOW + timedelta(minutes=15), NOW.replace(tzinfo=None)),
)
def test_confirmation_rejects_outside_or_naive_time(confirmed_at: datetime) -> None:
    authorization = _authorization()
    with pytest.raises(QuarantineConfirmationError, match="CONFIRMATION_INVALID"):
        quarantine_confirmation_digest(
            authorization,
            quarantine_confirmation_text(authorization),
            confirmed_at=confirmed_at,
        )


def _authorization() -> QuarantineAuthorizationSnapshot:
    keeper = EntityId.parse("df000000-0000-0000-0000-000000000003")
    candidate = EntityId.parse("df000000-0000-0000-0000-000000000004")
    keeper_observation = EntityId.parse("df000000-0000-0000-0000-000000000005")
    candidate_observation = EntityId.parse("df000000-0000-0000-0000-000000000006")
    root = EntityId.parse("df000000-0000-0000-0000-000000000007")
    expires_at = NOW + timedelta(minutes=15)
    content_hash = _authorization_content_hash(
        PLAN_ID,
        "a" * 64,
        root,
        keeper,
        candidate,
        keeper_observation,
        candidate_observation,
        "b" * 64,
        "b" * 64,
        CAPABILITY_ID,
        "c" * 64,
        NOW,
        expires_at,
    )
    return QuarantineAuthorizationSnapshot(
        _authorization_id(content_hash),
        PLAN_ID,
        "a" * 64,
        root,
        keeper,
        candidate,
        keeper_observation,
        candidate_observation,
        "b" * 64,
        "b" * 64,
        CAPABILITY_ID,
        "c" * 64,
        NOW,
        expires_at,
        content_hash,
    )
