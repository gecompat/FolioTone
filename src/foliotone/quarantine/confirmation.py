"""Exact non-logged confirmation for one ADR-0056 quarantine execution."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Final

from foliotone.quarantine.contracts import QuarantineAuthorizationSnapshot

QUARANTINE_CONFIRMATION_PROFILE: Final = "quarantine-execution-confirmation/v1"
_CONFIRMATION_DOMAIN: Final = b"foliotone:quarantine-confirmation/v1\x00"


class QuarantineConfirmationError(ValueError):
    """The exact opaque execution confirmation was not supplied."""

    def __init__(self) -> None:
        super().__init__("CONFIRMATION_INVALID")


def quarantine_confirmation_text(
    authorization: QuarantineAuthorizationSnapshot,
) -> str:
    """Return the sole accepted path- and filename-free confirmation line."""

    if not isinstance(authorization, QuarantineAuthorizationSnapshot):
        raise TypeError("authorization must be a quarantine authorization")
    return f"CONFIRM QUARANTINE {authorization.id} {authorization.plan_id}"


def quarantine_confirmation_digest(
    authorization: QuarantineAuthorizationSnapshot,
    supplied_text: str,
    *,
    confirmed_at: datetime,
) -> str:
    """Validate one exact line and bind it to authority and confirmation time."""

    if (
        not isinstance(authorization, QuarantineAuthorizationSnapshot)
        or not isinstance(supplied_text, str)
        or not isinstance(confirmed_at, datetime)
        or confirmed_at.tzinfo is None
        or confirmed_at.utcoffset() is None
    ):
        raise QuarantineConfirmationError()
    normalized_at = confirmed_at.astimezone(UTC)
    if not authorization.authorized_at <= normalized_at < authorization.expires_at:
        raise QuarantineConfirmationError()
    expected = quarantine_confirmation_text(authorization)
    if not hmac.compare_digest(supplied_text, expected):
        raise QuarantineConfirmationError()
    material = {
        "authorization_content_hash": authorization.content_hash,
        "authorization_id": str(authorization.id),
        "confirmed_at": normalized_at.isoformat(timespec="microseconds"),
        "confirmation": expected,
        "plan_id": str(authorization.plan_id),
        "profile": QUARANTINE_CONFIRMATION_PROFILE,
        "quarantine_capability_id": str(authorization.quarantine_capability_id),
    }
    payload = json.dumps(
        material,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(_CONFIRMATION_DOMAIN + payload).hexdigest()


__all__ = [
    "QUARANTINE_CONFIRMATION_PROFILE",
    "QuarantineConfirmationError",
    "quarantine_confirmation_digest",
    "quarantine_confirmation_text",
]
