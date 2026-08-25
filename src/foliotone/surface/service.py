"""Application service for the local authentication and job foundation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from foliotone.persistence.surface import (
    EbookRenameOperatorJobBinder,
    SQLiteSurfaceStore,
    SurfaceSession,
    SurfaceUser,
)
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

    def reauthenticate(
        self,
        session: SurfaceSession,
        password: str,
        *,
        scope: Scope = Scope.PRIVATE_READ,
    ) -> tuple[str, str, SurfaceSession] | None:
        """Rotate a session before granting a short-lived elevated read scope."""
        # A query by immutable user ID avoids a transport-level role assertion.
        user = self._store.find_user_by_id(session.user_id)
        if user is None or not verify_password(user.password_hash, password):
            return None
        token, csrf = generate_secret(), generate_secret()
        rotated = self._store.rotate_session(
            session,
            token_digest=secret_digest(token, purpose="session"),
            csrf_digest=secret_digest(csrf, purpose="csrf"),
        )
        self._store.create_grant(rotated, scope)
        return token, csrf, rotated

    def has_active_grant(self, session: SurfaceSession, scope: Scope) -> bool:
        """Check an elevated scope without exposing grant contents to transport adapters."""
        return self._store.has_active_grant(session.id, scope)

    def active_operate_grant_id(self, session: SurfaceSession) -> str | None:
        """Return the exact current OPERATE grant for an immutable W10 job binder."""
        return self._store.active_operate_grant_id(session)

    def has_active_operate_grant(self, *, grant_id: str, actor_id: str) -> bool:
        """Recheck a worker-bound OPERATE grant without exposing it publicly."""
        return self._store.has_active_operate_grant(grant_id=grant_id, actor_id=actor_id)

    def ebook_rename_confirmation_digest(self, **binders: str) -> str:
        """Validate raw confirmation without resolving a capability or source locator."""
        return self._store.ebook_rename_confirmation_digest(**binders)

    def ebook_rename_command_receipt(self, **arguments: str) -> dict[str, object] | None:
        return self._store.ebook_rename_command_receipt(**arguments)

    def claim_ebook_rename_command_receipt(self, **arguments: str) -> dict[str, object] | None:
        return self._store.claim_ebook_rename_command_receipt(**arguments)

    def record_ebook_rename_command_receipt(
        self, *, response: dict[str, object], **arguments: str
    ) -> dict[str, object]:
        return self._store.record_ebook_rename_command_receipt(**arguments, response=response)

    def enqueue_ebook_rename_operator_job(
        self,
        *,
        actor_id: str,
        input_digest: str,
        idempotency_digest: str,
        binder: EbookRenameOperatorJobBinder,
    ) -> str:
        return self._store.enqueue_ebook_rename_operator_job(
            actor_id=actor_id,
            input_digest=input_digest,
            idempotency_digest=idempotency_digest,
            binder=binder,
        )
