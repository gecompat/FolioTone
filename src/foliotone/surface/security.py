"""Password, token, and input validation without network dependencies."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import unicodedata
from dataclasses import dataclass
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

TOKEN_BYTES: Final = 32
TOKEN_DOMAIN: Final = b"foliotone:local-surface-token/v1\\0"
PASSWORD_PROFILE: Final = "argon2id/owasp-19mib-v1"
_COMMON_PASSWORDS: Final = frozenset(
    {"passwordpassword", "correcthorsebatterystaple", "123456789012345"}
)


class SurfaceSecurityError(ValueError):
    """Raised for a deliberately non-specific security validation failure."""


@dataclass(frozen=True, slots=True)
class PasswordProfile:
    """Versioned production Argon2id parameters, separated from test parameters."""

    version: str = PASSWORD_PROFILE
    time_cost: int = 2
    memory_cost: int = 19_456
    parallelism: int = 1
    hash_len: int = 32
    salt_len: int = 16

    def hasher(self) -> PasswordHasher:
        return PasswordHasher(
            time_cost=self.time_cost,
            memory_cost=self.memory_cost,
            parallelism=self.parallelism,
            hash_len=self.hash_len,
            salt_len=self.salt_len,
            type=Type.ID,
        )


def normalize_password(value: str) -> str:
    """Validate and NFC-normalize a password without trimming or case folding."""
    normalized = unicodedata.normalize("NFC", value)
    if not 15 <= len(normalized) <= 1024 or len(normalized.encode("utf-8")) > 4096:
        raise SurfaceSecurityError("password does not meet local policy")
    if normalized.casefold() in _COMMON_PASSWORDS:
        raise SurfaceSecurityError("password does not meet local policy")
    return normalized


def validate_username(value: str) -> tuple[str, str]:
    """Return the original username and its versioned uniqueness key."""
    if (
        not 3 <= len(value) <= 64
        or value != value.strip()
        or any(ch.isspace() and ch in "\\r\\n" for ch in value)
    ):
        raise SurfaceSecurityError("username does not meet local policy")
    if any(unicodedata.category(ch).startswith("C") for ch in value):
        raise SurfaceSecurityError("username does not meet local policy")
    return value, unicodedata.normalize("NFKC", value).casefold()


def generate_secret() -> str:
    """Generate an opaque 256-bit value for bootstrap, session, CSRF, or lease use."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def secret_digest(value: str, *, purpose: str) -> str:
    """Create a domain-separated digest; clear tokens are never persisted."""
    return hashlib.sha256(
        TOKEN_DOMAIN + purpose.encode("ascii") + b"\\0" + value.encode("utf-8")
    ).hexdigest()


def secure_equals(left: str, right: str) -> bool:
    """Compare stored digests without a timing side channel."""
    return hmac.compare_digest(left, right)


def password_hasher() -> PasswordHasher:
    """Return the production Argon2id hasher."""
    return PasswordProfile().hasher()


def hash_password(value: str) -> str:
    """Hash a normalized password with the versioned Argon2id profile."""
    return password_hasher().hash(normalize_password(value))


def verify_password(stored_hash: str, candidate: str) -> bool:
    """Verify a candidate without exposing Argon2 parser or mismatch detail."""
    try:
        return password_hasher().verify(stored_hash, normalize_password(candidate))
    except (InvalidHashError, VerificationError, SurfaceSecurityError):
        return False
