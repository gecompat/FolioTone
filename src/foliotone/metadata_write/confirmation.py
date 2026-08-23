"""Non-logged second-confirmation contract for one metadata-write run."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Final

from foliotone.metadata_write.authorization import MetadataWriteAuthorizationSnapshot

METADATA_WRITE_CONFIRMATION_PROFILE: Final = "metadata-write-execution-confirmation/v1"
_CONFIRMATION_DOMAIN: Final = b"foliotone:metadata-write-confirmation/v1\x00"


class MetadataWriteConfirmationError(ValueError):
    """The exact opaque execution confirmation was not supplied."""

    def __init__(self) -> None:
        super().__init__("CONFIRMATION_INVALID")


def metadata_write_confirmation_text(
    authorization: MetadataWriteAuthorizationSnapshot,
) -> str:
    """Return the sole accepted path- and metadata-value-free confirmation line."""

    if not isinstance(authorization, MetadataWriteAuthorizationSnapshot):
        raise TypeError("authorization must be a metadata-write authorization")
    return f"CONFIRM METADATA WRITE {authorization.id}"


def metadata_write_confirmation_digest(
    authorization: MetadataWriteAuthorizationSnapshot,
    supplied_text: str,
) -> str:
    """Validate one exact line and bind its success to the immutable authority."""

    if not isinstance(authorization, MetadataWriteAuthorizationSnapshot) or not isinstance(
        supplied_text, str
    ):
        raise MetadataWriteConfirmationError()
    expected = metadata_write_confirmation_text(authorization)
    if not hmac.compare_digest(supplied_text, expected):
        raise MetadataWriteConfirmationError()
    material = {
        "authorization_content_hash": authorization.content_hash,
        "authorization_id": str(authorization.id),
        "capability_id": str(authorization.metadata_write_capability_id),
        "confirmation": expected,
        "plan_content_hash": authorization.plan_content_hash,
        "plan_id": str(authorization.plan_id),
        "profile": METADATA_WRITE_CONFIRMATION_PROFILE,
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
    "METADATA_WRITE_CONFIRMATION_PROFILE",
    "MetadataWriteConfirmationError",
    "metadata_write_confirmation_digest",
    "metadata_write_confirmation_text",
]
