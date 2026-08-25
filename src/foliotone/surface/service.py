"""Application service for the local authentication and job foundation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from foliotone.application.contracts import (
    EbookFixityAnalysisJobCommand,
    EbookFixityBaselineActivationCommand,
    EbookFixityBaselineActivationResult,
    EbookFixityBaselineStatus,
    EbookFixityExpectationRevisionCommand,
    EbookFixityExpectationRevisionResult,
    EbookFixityPrivateBaselineEntry,
    EbookFixityPrivateBaselineEntryPage,
    EbookFixityPrivateBaselineEntryPageQuery,
    EbookFixityPrivateResultDetail,
    EbookFixityPrivateResultDetailQuery,
    EbookFixityPrivateResultMaterial,
    EbookFixityResultSummary,
    EbookFixityReviewCommand,
    EbookFixityReviewQueueItem,
    EbookFixityReviewResult,
    EbookFixityVerificationStatus,
)
from foliotone.core import EntityId
from foliotone.persistence.fixity import (
    SQLiteEbookFixityBaselineStore,
)
from foliotone.persistence.fixity_commands import SQLiteEbookFixityCommandOperation
from foliotone.persistence.fixity_surface import SQLiteEbookFixityBaselineActivationOperation
from foliotone.persistence.fixity_verification import SQLiteEbookFixityVerificationStore
from foliotone.persistence.resolution_review import SQLiteResolutionReviewStore
from foliotone.persistence.surface import (
    EbookFixityAnalysisJobBinder,
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

    def __init__(
        self,
        store: SQLiteSurfaceStore,
        *,
        fixity_baseline_store: SQLiteEbookFixityBaselineStore | None = None,
        fixity_verification_store: SQLiteEbookFixityVerificationStore | None = None,
        fixity_activation_operation: SQLiteEbookFixityBaselineActivationOperation | None = None,
        fixity_review_store: SQLiteResolutionReviewStore | None = None,
        fixity_command_operation: SQLiteEbookFixityCommandOperation | None = None,
    ) -> None:
        self._store = store
        self._fixity_baseline_store = fixity_baseline_store
        self._fixity_verification_store = fixity_verification_store
        self._fixity_activation_operation = fixity_activation_operation
        self._fixity_review_store = fixity_review_store
        self._fixity_command_operation = fixity_command_operation

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
        return self.command_receipt(**arguments)

    def claim_ebook_rename_command_receipt(self, **arguments: str) -> dict[str, object] | None:
        return self.claim_command_receipt(**arguments)

    def record_ebook_rename_command_receipt(
        self, *, response: dict[str, object], **arguments: str
    ) -> dict[str, object]:
        return self.complete_command_receipt(**arguments, response=response)

    def command_receipt(self, **arguments: str) -> dict[str, object] | None:
        return self._store.command_receipt(**arguments)

    def claim_command_receipt(self, **arguments: str) -> dict[str, object] | None:
        return self._store.claim_command_receipt(**arguments)

    def complete_command_receipt(
        self, *, response: dict[str, object], **arguments: str
    ) -> dict[str, object]:
        return self._store.complete_command_receipt(**arguments, response=response)

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

    def enqueue_ebook_fixity_analysis_job(
        self,
        *,
        actor_id: str,
        input_digest: str,
        idempotency_digest: str,
        binder: EbookFixityAnalysisJobBinder,
    ) -> str:
        """Queue only one fixed, read-only fixity profile."""
        return self._store.enqueue_ebook_fixity_analysis_job(
            actor_id=actor_id,
            input_digest=input_digest,
            idempotency_digest=idempotency_digest,
            binder=binder,
        )

    def enqueue_ebook_fixity_command(
        self,
        *,
        actor_id: str,
        input_digest: str,
        idempotency_digest: str,
        command: EbookFixityAnalysisJobCommand,
    ) -> str:
        return self.enqueue_ebook_fixity_analysis_job(
            actor_id=actor_id,
            input_digest=input_digest,
            idempotency_digest=idempotency_digest,
            binder=EbookFixityAnalysisJobBinder(
                profile=command.profile,
                scan_root_id=str(command.scan_root_id),
                worker_count=command.worker_count,
            ),
        )

    def fixity_baseline_status(self, manifest_id: EntityId) -> EbookFixityBaselineStatus | None:
        if self._fixity_baseline_store is None:
            return None
        status = self._fixity_baseline_store.read_status(manifest_id)
        if status is None:
            return None
        return EbookFixityBaselineStatus(
            manifest_id=status.manifest_id,
            scan_root_id=status.scan_root_id,
            source_scan_run_id=status.source_scan_run_id,
            status=status.status.value,
            started_at=status.started_at.isoformat(),
            prepared_at=None if status.prepared_at is None else status.prepared_at.isoformat(),
            expires_at=None if status.expires_at is None else status.expires_at.isoformat(),
            item_count=status.item_count,
            activated_at=None if status.activated_at is None else status.activated_at.isoformat(),
        )

    def fixity_verification_status(self, run_id: EntityId) -> EbookFixityVerificationStatus | None:
        if self._fixity_verification_store is None:
            return None
        status = self._fixity_verification_store.read_status(run_id)
        if status is None:
            return None
        return EbookFixityVerificationStatus(
            run_id=status.run_id,
            scan_root_id=status.scan_root_id,
            baseline_activation_id=status.baseline_activation_id,
            source_scan_run_id=status.source_scan_run_id,
            expectation_revision_no=status.expectation_revision_no,
            status=status.status.value,
            started_at=status.started_at.isoformat(),
            completed_at=None if status.completed_at is None else status.completed_at.isoformat(),
            expected_result_count=status.expected_result_count,
            result_count=status.result_count,
            failure_code=status.failure_code,
        )

    def private_fixity_baseline_entries(
        self, query: EbookFixityPrivateBaselineEntryPageQuery
    ) -> EbookFixityPrivateBaselineEntryPage:
        if self._fixity_baseline_store is None:
            raise RuntimeError("fixity baseline store is unavailable")
        entries, next_after = self._fixity_baseline_store.list_private_entries(
            query.manifest_id,
            after_ordinal=query.after_ordinal,
            limit=query.limit,
        )
        return EbookFixityPrivateBaselineEntryPage(
            manifest_id=query.manifest_id,
            entries=tuple(
                EbookFixityPrivateBaselineEntry(
                    ordinal=entry.ordinal,
                    file_id=entry.file_id,
                    observation_id=entry.observation_id,
                    relative_locator=entry.relative_locator,
                    size_bytes=entry.expected_size_bytes,
                    sha256=entry.expected_sha256,
                )
                for entry in entries
            ),
            next_after_ordinal=next_after,
        )

    def fixity_result_summaries(
        self, run_id: EntityId, *, after_id: EntityId | None, limit: int
    ) -> tuple[tuple[EbookFixityResultSummary, ...], EntityId | None]:
        if self._fixity_verification_store is None:
            raise RuntimeError("fixity verification store is unavailable")
        rows, next_after = self._fixity_verification_store.list_result_summaries(
            run_id, after_id=after_id, limit=limit
        )
        return (
            tuple(
                EbookFixityResultSummary(
                    result_id=result_id,
                    file_id=file_id,
                    result=result.value,
                    failure_code=failure_code,
                )
                for result_id, file_id, result, failure_code in rows
            ),
            next_after,
        )

    def private_fixity_result_detail(
        self,
        query: EbookFixityPrivateResultDetailQuery,
    ) -> EbookFixityPrivateResultDetail | None:
        if self._fixity_verification_store is None:
            raise RuntimeError("fixity verification store is unavailable")
        item = self._fixity_verification_store.read_result(query.result_id)
        if item is None:
            return None
        return EbookFixityPrivateResultDetail(
            result_id=item.result_id,
            run_id=item.run_id,
            file_id=item.file_id,
            result=item.result.value,
            expected=EbookFixityPrivateResultMaterial(
                observation_id=item.expected_observation_id,
                relative_locator=item.expected_relative_locator,
                size_bytes=item.expected_size_bytes,
                sha256=item.expected_sha256,
            ),
            current=EbookFixityPrivateResultMaterial(
                observation_id=item.current_observation_id,
                relative_locator=item.current_relative_locator,
                size_bytes=item.current_size_bytes,
                sha256=item.current_sha256,
            ),
            failure_code=item.failure_code,
        )

    def fixity_review_queue(
        self,
        *,
        after_id: EntityId | None,
        limit: int,
    ) -> tuple[tuple[EbookFixityReviewQueueItem, ...], EntityId | None]:
        if self._fixity_review_store is None:
            raise RuntimeError("fixity review store is unavailable")
        items, next_after = self._fixity_review_store.list_fixity_queue_by_id(
            after_id=after_id,
            limit=limit,
        )
        return (
            tuple(
                EbookFixityReviewQueueItem(
                    review_item_id=item.id,
                    result_id=item.candidate_id,
                    file_id=item.subject_id,
                    state=item.state.value,
                    created_at=item.created_at.isoformat(),
                )
                for item in items
            ),
            next_after,
        )

    def review_fixity_result_command(
        self,
        command: EbookFixityReviewCommand,
        *,
        actor_id: str,
        session_id: str,
        input_digest: str,
        idempotency_digest: str,
    ) -> EbookFixityReviewResult:
        if self._fixity_command_operation is None:
            raise RuntimeError("fixity command operation is unavailable")
        return self._fixity_command_operation.review_result(
            command,
            actor_id=actor_id,
            session_id=session_id,
            input_digest=input_digest,
            idempotency_digest=idempotency_digest,
            decided_at=datetime.now(UTC).replace(microsecond=0),
        )

    def revise_fixity_expectation_command(
        self,
        command: EbookFixityExpectationRevisionCommand,
        *,
        actor_id: str,
        session_id: str,
        input_digest: str,
        idempotency_digest: str,
    ) -> EbookFixityExpectationRevisionResult:
        if self._fixity_command_operation is None:
            raise RuntimeError("fixity command operation is unavailable")
        return self._fixity_command_operation.revise_expectation(
            command,
            actor_id=actor_id,
            session_id=session_id,
            input_digest=input_digest,
            idempotency_digest=idempotency_digest,
            created_at=datetime.now(UTC).replace(microsecond=0),
        )

    def activate_fixity_baseline_command(
        self,
        command: EbookFixityBaselineActivationCommand,
        *,
        actor_id: str,
        session_id: str,
        input_digest: str,
        idempotency_digest: str,
    ) -> EbookFixityBaselineActivationResult:
        if self._fixity_activation_operation is None:
            raise RuntimeError("fixity baseline activation operation is unavailable")
        return self._fixity_activation_operation.activate(
            command,
            actor_id=actor_id,
            session_id=session_id,
            input_digest=input_digest,
            idempotency_digest=idempotency_digest,
            activated_at=datetime.now(UTC).replace(microsecond=0),
        )
