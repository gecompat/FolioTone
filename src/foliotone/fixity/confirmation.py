"""Exact, non-retained confirmation for fixity baseline activation."""

from __future__ import annotations

import hashlib
import hmac

from foliotone.core.ids import EntityId

_CONFIRMATION_DOMAIN = b"foliotone:ebook-fixity-baseline-confirmation/v1\x00"


def expected_fixity_baseline_confirmation(manifest_id: EntityId) -> str:
    """Return the exact short-lived confirmation expected by an adapter."""

    if not isinstance(manifest_id, EntityId):
        raise TypeError("manifest_id must be an EntityId")
    return f"ACCEPT FIXITY BASELINE {manifest_id}"


def verify_fixity_baseline_confirmation(manifest_id: EntityId, provided: str) -> str:
    """Verify exact input and return only a domain-separated audit digest."""

    if not isinstance(provided, str):
        raise TypeError("fixity baseline confirmation must be text")
    expected = expected_fixity_baseline_confirmation(manifest_id)
    if not hmac.compare_digest(provided, expected):
        raise ValueError("fixity baseline confirmation does not match")
    return hashlib.sha256(_CONFIRMATION_DOMAIN + provided.encode("utf-8")).hexdigest()
