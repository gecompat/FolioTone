"""Exact second-confirmation contract for one bounded e-book rename."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Final

from foliotone.ebook_rename.authority import EbookRenameAuthorizationSnapshot

EBOOK_RENAME_CONFIRMATION_PROFILE: Final = "ebook-file-rename-confirmation/v1"
_CONFIRMATION_DOMAIN: Final = b"foliotone:ebook-file-rename-confirmation/v1\x00"
_PROMPT_PREFIX: Final = "CONFIRM EBOOK RENAME "
_MAX_CONFIRMATION_CHARACTERS: Final = 256


class EbookRenameConfirmationError(ValueError):
    """The bounded confirmation did not exactly match its authorization."""

    def __init__(self) -> None:
        super().__init__("EBOOK_RENAME_CONFIRMATION_INVALID")


def ebook_rename_confirmation_text(
    authorization: EbookRenameAuthorizationSnapshot,
) -> str:
    """Return the only accepted human confirmation line."""

    if not isinstance(authorization, EbookRenameAuthorizationSnapshot):
        raise EbookRenameConfirmationError()
    return f"{_PROMPT_PREFIX}{authorization.id}"


def ebook_rename_confirmation_digest(
    authorization: EbookRenameAuthorizationSnapshot,
    supplied_text: str,
) -> str:
    """Validate one exact line and return a domain-separated private digest."""

    expected = ebook_rename_confirmation_text(authorization)
    if (
        not isinstance(supplied_text, str)
        or len(supplied_text) > _MAX_CONFIRMATION_CHARACTERS
        or "\r" in supplied_text
        or "\n" in supplied_text
        or not hmac.compare_digest(supplied_text, expected)
    ):
        raise EbookRenameConfirmationError()
    material = {
        "authorization_content_hash": authorization.content_hash,
        "authorization_id": str(authorization.id),
        "capability_id": str(authorization.ebook_rename_capability_id),
        "plan_content_hash": authorization.plan_content_hash,
        "plan_id": str(authorization.plan_id),
        "profile": EBOOK_RENAME_CONFIRMATION_PROFILE,
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
    "EBOOK_RENAME_CONFIRMATION_PROFILE",
    "EbookRenameConfirmationError",
    "ebook_rename_confirmation_digest",
    "ebook_rename_confirmation_text",
]
