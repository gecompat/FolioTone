"""Application service for the local authentication and job foundation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from foliotone.persistence.surface import SQLiteSurfaceStore, SurfaceSession, SurfaceUser
from foliotone.surface.contracts import Scope
from foliotone.surface.security import (
    PASSWORD_PROFILE,
    generate_secret,
    hash_password,
    secret_digest,
    secure_equals,
    validate_username,
    verify_password,
)


class LocalSurfaceService:
    """Keep HTTP and CLI adapters outside the auth and persistence decisions."""

    def __init__(self, store: SQLiteSurfaceStore) -> None:
        self._store = store

    def bootstrap(self) -> str:
        code = generate_secret()
        self._store.create_bootstrap(
            secret_digest(code, purpose="bootstrap"),
            expires_at=datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=15),
        )
        return code

    def setup(self, *, bootstrap_code: str, username: str, password: str) -> SurfaceUser | None:
        username, username_key = validate_username(username)
        password_hash = hash_password(password)
        digest = secret_digest(bootstrap_code, purpose="bootstrap")
        user = self._store.create_first_user(
            token_digest=digest,
            username=username,
            username_key=username_key,
            password_hash=password_hash,
            password_profile=PASSWORD_PROFILE,
        )
        if user is None:
            self._store.register_bootstrap_failure(digest)
        return user

    def login(self, *, username: str, password: str) -> tuple[str, str, SurfaceSession] | None:
        _, username_key = validate_username(username)
        principal_digest = secret_digest(username_key, purpose="login")
        if not self._store.login_allowed(principal_digest):
            return None
        user = self._store.find_user(username_key)
        if user is None or not user.active or not verify_password(user.password_hash, password):
            self._store.record_login_failure(principal_digest)
            return None
        self._store.clear_login_failures(principal_digest, user.id)
        token, csrf = generate_secret(), generate_secret()
        return (
            token,
            csrf,
            self._store.create_session(
                user_id=user.id,
                token_digest=secret_digest(token, purpose="session"),
                csrf_digest=secret_digest(csrf, purpose="csrf"),
            ),
        )

    def authenticate(self, token: str) -> SurfaceSession | None:
        return self._store.session_for_token(secret_digest(token, purpose="session"))

    def csrf_valid(self, session: SurfaceSession, csrf: str) -> bool:
        return secure_equals(session.csrf_digest, secret_digest(csrf, purpose="csrf"))

    def logout(self, session: SurfaceSession) -> None:
        self._store.revoke_session(session.id, actor_id=session.user_id)

    def reset(self, password: str) -> bool:
        user = self._store.only_user()
        if user is None:
            return False
        self._store.reset_password(user.id, hash_password(password), PASSWORD_PROFILE)
        return True

    def setup_required(self) -> bool:
        return not self._store.has_user()

    def grant_after_reauth(self, session: SurfaceSession, password: str) -> bool:
        # A query by immutable user ID avoids a transport-level role assertion.
        user = self._store.find_user_by_id(session.user_id)
        if user is None or not verify_password(user.password_hash, password):
            return False
        self._store.create_grant(session.id, Scope.OPERATE)
        return True
