"""Bounded, transport-only read helpers for the local product surface."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass


class CursorError(ValueError):
    """An opaque cursor is malformed, tampered with, or bound to another resource."""


@dataclass(frozen=True, slots=True)
class SurfaceCursor:
    """A verified cursor bound to one resource profile and sort order."""

    resource: str
    sort: str
    last_id: str


class CursorCodec:
    """Sign compact resource-bound cursors without exposing database cursor shapes."""

    def __init__(self, key: bytes | None = None) -> None:
        self._key = key or secrets.token_bytes(32)

    def encode(self, *, resource: str, sort: str, last_id: str) -> str:
        payload = json.dumps(
            {"last_id": last_id, "resource": resource, "sort": sort},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        signature = hmac.new(self._key, payload, hashlib.sha256).digest()
        return _encode(payload) + "." + _encode(signature)

    def decode(self, value: str, *, resource: str, sort: str) -> SurfaceCursor:
        try:
            payload_encoded, signature_encoded = value.split(".", 1)
            payload = _decode(payload_encoded)
            signature = _decode(signature_encoded)
            expected = hmac.new(self._key, payload, hashlib.sha256).digest()
            decoded = json.loads(payload)
            cursor = SurfaceCursor(
                resource=str(decoded["resource"]),
                sort=str(decoded["sort"]),
                last_id=str(decoded["last_id"]),
            )
        except (KeyError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            raise CursorError("cursor is invalid") from None
        if (
            not hmac.compare_digest(signature, expected)
            or cursor.resource != resource
            or cursor.sort != sort
        ):
            raise CursorError("cursor is invalid")
        return cursor


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
