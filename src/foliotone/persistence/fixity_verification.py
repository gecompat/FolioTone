"""Fenced insert-only persistence for book-only fixity verification v1."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import Engine, func, insert, select, text
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError

from foliotone.core import (
    EntityId,
    MediaType,
    PresenceState,
    ReviewCandidateKind,
    ReviewDecisionValue,
    ReviewType,
    ScanRunStatus,
)
from foliotone.fixity.contracts import canonical_json_bytes
from foliotone.fixity.verification_contracts import (
    EBOOK_FIXITY_DECISION_PROFILE,
    EBOOK_FIXITY_VERIFICATION_PROFILE,
    EbookFixityExpectationAction,
    EbookFixityExpectationDecisionInput,
    EbookFixityExpectationRevision,
    EbookFixityVerificationResult,
    EbookFixityVerificationResultRecord,
    EbookFixityVerificationRun,
    EbookFixityVerificationRunStatus,
)
from foliotone.fixity.verification_fingerprints import (
    verification_candidate_set_fingerprint,
    verification_evidence_fingerprint,
    verification_results_digest,
    verification_run_content_digest,
)
from foliotone.persistence import (
    fixity_schema,
    schema,
)
from foliotone.persistence import (
    fixity_verification_schema as fv_schema,
)
from foliotone.persistence import (
    resolution_review_schema as rr_schema,
)
from foliotone.persistence._mapping import datetime_to_db, required_datetime_from_db
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)

EBOOK_FIXITY_RESULT_PROFILE: Final = "ebook-fixity-result/v1"
EBOOK_FIXITY_SERIALIZER: Final = "canonical-json/v1"
DEFAULT_EBOOK_FIXITY_VERIFICATION_LEASE_DURATION: Final = timedelta(seconds=30)

_WORKSET_CTE: Final = """
WITH latest_revision_per_file AS (
    SELECT file_id, MAX(revision_no) AS revision_no
    FROM ebook_fixity_expectation_revisions
    WHERE scan_root_id=:scan_root_id
      AND baseline_activation_id=:activation_id
      AND revision_no<=:revision_no
    GROUP BY file_id
),
active_expected AS (
    SELECT entry.file_id,
           entry.observation_id AS expected_observation_id,
           entry.expected_size_bytes,
           entry.expected_sha256,
           entry.relative_locator AS expected_relative_locator
    FROM ebook_fixity_baseline_entries AS entry
    JOIN ebook_fixity_baseline_activations AS activation
      ON activation.manifest_id=entry.manifest_id
    LEFT JOIN latest_revision_per_file AS latest ON latest.file_id=entry.file_id
    WHERE activation.activation_id=:activation_id
      AND activation.scan_root_id=:scan_root_id
      AND latest.file_id IS NULL
    UNION ALL
    SELECT revision.file_id,
           revision.expected_observation_id,
           revision.expected_size_bytes,
           revision.expected_sha256,
           revision.expected_relative_locator
    FROM ebook_fixity_expectation_revisions AS revision
    JOIN latest_revision_per_file AS latest
      ON latest.file_id=revision.file_id
     AND latest.revision_no=revision.revision_no
    WHERE revision.scan_root_id=:scan_root_id
      AND revision.baseline_activation_id=:activation_id
      AND revision.action=:accept_action
),
current_snapshot AS (
    SELECT record.id AS file_id,
           observation.id AS current_observation_id,
           observation.size_bytes AS current_size_bytes,
           observation.modified_at AS current_modified_at,
           observation.relative_path AS current_relative_locator
    FROM file_records AS record
    JOIN file_observations AS observation ON observation.file_id=record.id
    WHERE record.scan_root_id=:scan_root_id
      AND record.media_type=:ebook_media_type
      AND record.presence_state=:present_state
      AND observation.scan_run_id=:scan_run_id
      AND observation.relative_path=record.relative_path
      AND observation.size_bytes=record.size_bytes
      AND observation.modified_at=record.modified_at
),
workset_ids AS (
    SELECT file_id FROM active_expected
    UNION
    SELECT file_id FROM current_snapshot
)
"""

_WORKSET_COLUMNS: Final = """
SELECT workset.file_id,
       expected.expected_observation_id,
       expected.expected_size_bytes,
       expected.expected_sha256,
       expected.expected_relative_locator,
       current.current_observation_id,
       current.current_size_bytes,
       current.current_modified_at,
       current.current_relative_locator
FROM workset_ids AS workset
LEFT JOIN active_expected AS expected ON expected.file_id=workset.file_id
LEFT JOIN current_snapshot AS current ON current.file_id=workset.file_id
"""

_WORKSET_PAGE_SQL: Final = (
    _WORKSET_COLUMNS
    + " WHERE workset.file_id>:after_file_id ORDER BY workset.file_id LIMIT :batch_size"
)
_WORKSET_ONE_SQL: Final = _WORKSET_COLUMNS + " WHERE workset.file_id=:selected_file_id"
_WORKSET_COVERAGE_SQL: Final = """
SELECT
  (SELECT COUNT(*) FROM workset_ids) AS workset_count,
  (SELECT COUNT(*) FROM ebook_fixity_verification_results
    WHERE run_id=:run_id) AS result_count,
  (SELECT COUNT(*) FROM workset_ids AS workset
    WHERE NOT EXISTS (
      SELECT 1 FROM ebook_fixity_verification_results AS result
      WHERE result.run_id=:run_id AND result.file_id=workset.file_id
    )) AS missing_count,
  (SELECT COUNT(*) FROM ebook_fixity_verification_results AS result
    WHERE result.run_id=:run_id AND NOT EXISTS (
      SELECT 1 FROM workset_ids AS workset WHERE workset.file_id=result.file_id
    )) AS extra_count
"""


class EbookFixityVerificationStoreError(RuntimeError):
    """A verification or expectation transition failed closed."""


@dataclass(frozen=True, slots=True)
class OwnedEbookFixityVerificationRun:
    run: EbookFixityVerificationRun
    expected_result_count: int
    input_digest: str = field(repr=False)
    write_lease: OwnedScanRootWriteLease = field(repr=False)


@dataclass(frozen=True, slots=True)
class EbookFixityVerificationStatusSnapshot:
    """Bounded standard status without locators, byte hashes, or fence material."""

    run_id: EntityId
    scan_root_id: EntityId
    baseline_activation_id: EntityId
    source_scan_run_id: EntityId
    expectation_revision_no: int
    status: EbookFixityVerificationRunStatus
    started_at: datetime
    completed_at: datetime | None
    expected_result_count: int
    result_count: int
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class EbookFixityVerificationWorkItem:
    """One private, snapshot-bound work item from a bounded keyset page."""

    file_id: EntityId
    expected_observation_id: EntityId | None
    expected_size_bytes: int | None
    expected_sha256: str | None = field(repr=False)
    expected_relative_locator: str | None = field(repr=False)
    current_observation_id: EntityId | None
    current_size_bytes: int | None
    current_modified_at: datetime | None
    current_relative_locator: str | None = field(repr=False)


class SQLiteEbookFixityVerificationStore:
    """Persist verification facts and root-local expected-state revisions."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._leases = SQLiteScanRootWriteLeaseStore(engine)

    def start_run(
        self,
        run_id: EntityId,
        scan_root_id: EntityId,
        *,
        started_at: datetime,
        lease_token: str,
        lease_expires_at: datetime,
    ) -> OwnedEbookFixityVerificationRun:
        try:
            with self._engine.begin() as connection:
                source_scan_run_id = self._latest_completed_scan(connection, scan_root_id)
                baseline_activation_id = self._active_baseline_id(connection, scan_root_id)
                revision_no, revision_digest = self._current_revision(
                    connection,
                    scan_root_id,
                    baseline_activation_id,
                )
                run = EbookFixityVerificationRun(
                    run_id=run_id,
                    baseline_activation_id=baseline_activation_id,
                    scan_root_id=scan_root_id,
                    source_scan_run_id=source_scan_run_id,
                    expectation_revision_no=revision_no,
                    expectation_revision_digest=revision_digest,
                    started_at=started_at,
                    status=EbookFixityVerificationRunStatus.RUNNING,
                )
                self._require_current_snapshot_coverage(
                    connection,
                    run.scan_root_id,
                    run.source_scan_run_id,
                )
                expected_result_count = self._workset_count(connection, run)
                input_digest = _sha256(
                    {
                        "profile": EBOOK_FIXITY_VERIFICATION_PROFILE,
                        "serializer": EBOOK_FIXITY_SERIALIZER,
                        "run_id": str(run.run_id),
                        "scan_root_id": str(run.scan_root_id),
                        "baseline_activation_id": str(run.baseline_activation_id),
                        "expectation_revision_no": revision_no,
                        "expectation_revision_digest": revision_digest,
                        "source_scan_run_id": str(run.source_scan_run_id),
                        "expected_result_count": expected_result_count,
                    }
                )
                lease = self._acquire_or_recover_verification_lease(
                    connection,
                    run,
                    lease_token=lease_token,
                    lease_expires_at=lease_expires_at,
                )
                connection.execute(
                    insert(fv_schema.ebook_fixity_verification_runs),
                    {
                        "id": str(run.run_id),
                        "profile": EBOOK_FIXITY_VERIFICATION_PROFILE,
                        "serializer": EBOOK_FIXITY_SERIALIZER,
                        "scan_root_id": str(run.scan_root_id),
                        "baseline_activation_id": str(run.baseline_activation_id),
                        "expectation_revision_no": revision_no,
                        "expectation_revision_digest": revision_digest,
                        "source_scan_run_id": str(run.source_scan_run_id),
                        "started_at": _datetime(run.started_at),
                        "expected_result_count": expected_result_count,
                        "input_digest": input_digest,
                    },
                )
                self._insert_event(
                    connection,
                    run.run_id,
                    0,
                    EbookFixityVerificationRunStatus.RUNNING,
                    run.started_at,
                )
                return OwnedEbookFixityVerificationRun(
                    run,
                    expected_result_count,
                    input_digest,
                    lease,
                )
        except EbookFixityVerificationStoreError:
            raise
        except (IntegrityError, ScanRootWriteLeaseError, TypeError, ValueError) as error:
            raise EbookFixityVerificationStoreError(
                "fixity verification run could not be started"
            ) from error

    def heartbeat(
        self,
        owned: OwnedEbookFixityVerificationRun,
        *,
        heartbeat_at: datetime,
        lease_expires_at: datetime,
    ) -> OwnedEbookFixityVerificationRun:
        try:
            renewed = self._leases.heartbeat(
                owned.write_lease,
                heartbeat_at=heartbeat_at,
                lease_expires_at=lease_expires_at,
            )
            return replace(owned, write_lease=renewed)
        except (ScanRootWriteLeaseError, ValueError) as error:
            raise EbookFixityVerificationStoreError(
                "fixity verification lease heartbeat failed"
            ) from error

    def read_workset_batch(
        self,
        owned: OwnedEbookFixityVerificationRun,
        *,
        observed_at: datetime,
        after_file_id: EntityId | None = None,
        batch_size: int = 100,
    ) -> tuple[EbookFixityVerificationWorkItem, ...]:
        """Read one stable private workset page without collection materialization."""
        if batch_size < 1 or batch_size > 1_000:
            raise EbookFixityVerificationStoreError(
                "verification workset batch_size must be between 1 and 1000"
            )
        try:
            with self._engine.begin() as connection:
                self._fence_open_run(connection, owned, observed_at)
                self._require_run_binders_current(connection, owned.run)
                rows = connection.execute(
                    text(_WORKSET_CTE + _WORKSET_PAGE_SQL),
                    self._workset_parameters(
                        owned.run,
                        after_file_id=after_file_id,
                        batch_size=batch_size,
                    ),
                ).mappings()
                return tuple(_decode_work_item(row) for row in rows)
        except EbookFixityVerificationStoreError:
            raise
        except (ScanRootWriteLeaseError, TypeError, ValueError) as error:
            raise EbookFixityVerificationStoreError(
                "fixity verification workset page could not be read"
            ) from error

    def read_run(self, run_id: EntityId) -> EbookFixityVerificationRun | None:
        """Read a persisted run through the path-free run contract."""
        status = self.read_status(run_id)
        if status is None:
            return None
        with self._engine.connect() as connection:
            row = self._run_row(connection, run_id)
            terminal = (
                connection.execute(
                    select(fv_schema.ebook_fixity_verification_events)
                    .where(fv_schema.ebook_fixity_verification_events.c.run_id == str(run_id))
                    .order_by(fv_schema.ebook_fixity_verification_events.c.sequence_no.desc())
                    .limit(1)
                )
                .mappings()
                .one()
            )
        return EbookFixityVerificationRun(
            run_id=run_id,
            baseline_activation_id=status.baseline_activation_id,
            scan_root_id=status.scan_root_id,
            source_scan_run_id=status.source_scan_run_id,
            expectation_revision_no=status.expectation_revision_no,
            expectation_revision_digest=str(row["expectation_revision_digest"]),
            started_at=status.started_at,
            status=status.status,
            content_digest=_text_or_none(terminal["content_digest"]),
            completed_at=status.completed_at,
            result_count=status.result_count,
        )

    def read_result(
        self,
        result_id: EntityId,
    ) -> EbookFixityVerificationResultRecord | None:
        """Read one immutable private verification result by opaque ID."""
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(fv_schema.ebook_fixity_verification_results).where(
                        fv_schema.ebook_fixity_verification_results.c.id == str(result_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _decode_result(row)

    def list_result_summaries(
        self, run_id: EntityId, *, after_id: EntityId | None = None, limit: int = 50
    ) -> tuple[
        tuple[tuple[EntityId, EntityId, EbookFixityVerificationResult, str | None], ...],
        EntityId | None,
    ]:
        """Read a bounded public projection without locators, hashes, or material values."""
        if not 1 <= limit <= 100:
            raise ValueError("fixity result page is invalid")
        table = fv_schema.ebook_fixity_verification_results
        statement = (
            select(table.c.id, table.c.file_id, table.c.result_type, table.c.failure_code)
            .where(table.c.run_id == str(run_id))
            .order_by(table.c.id)
            .limit(limit + 1)
        )
        if after_id is not None:
            statement = statement.where(table.c.id > str(after_id))
        with self._engine.connect() as connection:
            exists = connection.execute(
                select(fv_schema.ebook_fixity_verification_runs.c.id).where(
                    fv_schema.ebook_fixity_verification_runs.c.id == str(run_id)
                )
            ).scalar_one_or_none()
            if exists is None:
                raise ValueError("fixity verification run is unavailable")
            rows = connection.execute(statement).mappings().all()
        items = tuple(
            (
                EntityId.parse(str(row["id"])),
                EntityId.parse(str(row["file_id"])),
                EbookFixityVerificationResult(str(row["result_type"])),
                _text_or_none(row["failure_code"]),
            )
            for row in rows[:limit]
        )
        return items, (None if len(rows) <= limit or not items else items[-1][0])

    def review_material_in_transaction(
        self,
        connection: Connection,
        result_id: EntityId,
    ) -> tuple[EbookFixityVerificationResultRecord, str, str]:
        """Derive the closed review binders for the latest actionable result."""

        result_row, run_row = self._result_and_run(connection, result_id)
        record = _decode_result(result_row)
        scan_root_id = EntityId.parse(str(run_row["scan_root_id"]))
        terminal = self._require_completed_run(connection, record.run_id)
        self._require_latest_verification_run(connection, scan_root_id, record.run_id)
        self._require_latest_completed_scan(
            connection,
            scan_root_id,
            EntityId.parse(str(run_row["source_scan_run_id"])),
        )
        revision_no, revision_digest = self._current_revision(
            connection,
            scan_root_id,
            EntityId.parse(str(run_row["baseline_activation_id"])),
        )
        if (
            revision_no != int(run_row["expectation_revision_no"])
            or revision_digest != str(run_row["expectation_revision_digest"])
        ):
            raise EbookFixityVerificationStoreError(
                "fixity review expectation lineage is stale"
            )
        if record.result not in {
            EbookFixityVerificationResult.UNEXPECTED_BYTE_CHANGE,
            EbookFixityVerificationResult.UNBASELINED,
            EbookFixityVerificationResult.MISSING,
        }:
            raise EbookFixityVerificationStoreError(
                "fixity result is not decision-actionable"
            )
        run_digest = _text_or_none(terminal["content_digest"])
        if run_digest is None:
            raise EbookFixityVerificationStoreError(
                "completed fixity run has no content digest"
            )
        evidence = verification_evidence_fingerprint(
            subject_id=record.file_id,
            scan_root_id=scan_root_id,
            baseline_activation_id=EntityId.parse(str(run_row["baseline_activation_id"])),
            expectation_revision_no=revision_no,
            expectation_revision_digest=revision_digest,
            scan_run_id=EntityId.parse(str(run_row["source_scan_run_id"])),
            verification_run_id=record.run_id,
            verification_run_content_digest=run_digest,
            result_id=record.result_id,
            result_content_digest=record.content_digest,
        )
        return record, evidence, verification_candidate_set_fingerprint(record)

    def append_results(
        self,
        owned: OwnedEbookFixityVerificationRun,
        results: tuple[EbookFixityVerificationResultRecord, ...],
        *,
        recorded_at: datetime,
    ) -> tuple[EbookFixityVerificationResultRecord, ...]:
        if not results:
            return ()
        if len({result.file_id for result in results}) != len(results):
            raise EbookFixityVerificationStoreError("result batch contains duplicate files")
        try:
            with self._engine.begin() as connection:
                self._fence_open_run(connection, owned, recorded_at)
                run_row = self._run_row(connection, owned.run.run_id)
                persisted: list[EbookFixityVerificationResultRecord] = []
                for result in results:
                    if result.run_id != owned.run.run_id:
                        raise EbookFixityVerificationStoreError(
                            "verification result belongs to another run"
                        )
                    work_item = self._work_item(connection, owned.run, result.file_id)
                    self._require_result_matches_workset(result, work_item)
                    row = self._result_row(result, recorded_at)
                    inserted = connection.execute(
                        insert(fv_schema.ebook_fixity_verification_results)
                        .values(**row)
                        .prefix_with("OR IGNORE")
                    )
                    if inserted.rowcount == 1:
                        persisted.append(result)
                        continue
                    existing = self._result_for_file(
                        connection,
                        owned.run.run_id,
                        result.file_id,
                    )
                    if existing != result:
                        raise EbookFixityVerificationStoreError(
                            "verification result retry has different content"
                        )
                    persisted.append(existing)
                if str(run_row["input_digest"]) != owned.input_digest:
                    raise EbookFixityVerificationStoreError("verification run input binder changed")
                return tuple(persisted)
        except EbookFixityVerificationStoreError:
            raise
        except (IntegrityError, ScanRootWriteLeaseError, TypeError, ValueError) as error:
            raise EbookFixityVerificationStoreError(
                "fixity verification results could not be persisted"
            ) from error

    def complete_run(
        self,
        owned: OwnedEbookFixityVerificationRun,
        *,
        completed_at: datetime,
    ) -> EbookFixityVerificationRun:
        try:
            with self._engine.begin() as connection:
                self._fence_open_run(connection, owned, completed_at)
                self._require_run_binders_current(connection, owned.run)
                params = self._workset_parameters(owned.run)
                params["run_id"] = str(owned.run.run_id)
                coverage = (
                    connection.execute(text(_WORKSET_CTE + _WORKSET_COVERAGE_SQL), params)
                    .mappings()
                    .one()
                )
                if (
                    int(coverage["missing_count"]) != 0
                    or int(coverage["extra_count"]) != 0
                    or int(coverage["result_count"]) != owned.expected_result_count
                    or int(coverage["workset_count"]) != owned.expected_result_count
                ):
                    raise EbookFixityVerificationStoreError(
                        "verification results do not cover the exact bound workset"
                    )
                content_digest = self._run_content_digest(
                    connection,
                    owned,
                    completed_at,
                )
                self._insert_event(
                    connection,
                    owned.run.run_id,
                    1,
                    EbookFixityVerificationRunStatus.COMPLETED,
                    completed_at,
                    content_digest=content_digest,
                )
                self._leases.release_in_transaction(
                    connection,
                    owned.write_lease,
                    released_at=completed_at,
                )
                return replace(
                    owned.run,
                    status=EbookFixityVerificationRunStatus.COMPLETED,
                    completed_at=completed_at,
                    result_count=owned.expected_result_count,
                    content_digest=content_digest,
                )
        except EbookFixityVerificationStoreError:
            raise
        except (IntegrityError, ScanRootWriteLeaseError, TypeError, ValueError) as error:
            raise EbookFixityVerificationStoreError(
                "fixity verification run could not be completed"
            ) from error

    def fail_run(
        self,
        owned: OwnedEbookFixityVerificationRun,
        *,
        failed_at: datetime,
        failure_code: str,
    ) -> None:
        try:
            with self._engine.begin() as connection:
                self._fence_open_run(connection, owned, failed_at)
                self._insert_event(
                    connection,
                    owned.run.run_id,
                    1,
                    EbookFixityVerificationRunStatus.FAILED,
                    failed_at,
                    failure_code=failure_code,
                )
                self._leases.release_in_transaction(
                    connection,
                    owned.write_lease,
                    released_at=failed_at,
                )
        except (IntegrityError, ScanRootWriteLeaseError, TypeError, ValueError) as error:
            raise EbookFixityVerificationStoreError(
                "fixity verification run could not be failed safely"
            ) from error

    def read_status(
        self,
        run_id: EntityId,
    ) -> EbookFixityVerificationStatusSnapshot | None:
        with self._engine.connect() as connection:
            run = self._run_row_or_none(connection, run_id)
            if run is None:
                return None
            terminal = (
                connection.execute(
                    select(fv_schema.ebook_fixity_verification_events)
                    .where(fv_schema.ebook_fixity_verification_events.c.run_id == str(run_id))
                    .order_by(fv_schema.ebook_fixity_verification_events.c.sequence_no.desc())
                    .limit(1)
                )
                .mappings()
                .one()
            )
            result_count = int(
                connection.execute(
                    select(func.count())
                    .select_from(fv_schema.ebook_fixity_verification_results)
                    .where(fv_schema.ebook_fixity_verification_results.c.run_id == str(run_id))
                ).scalar_one()
            )
        status = EbookFixityVerificationRunStatus(str(terminal["status"]))
        return EbookFixityVerificationStatusSnapshot(
            run_id=run_id,
            scan_root_id=EntityId.parse(str(run["scan_root_id"])),
            baseline_activation_id=EntityId.parse(str(run["baseline_activation_id"])),
            source_scan_run_id=EntityId.parse(str(run["source_scan_run_id"])),
            expectation_revision_no=int(run["expectation_revision_no"]),
            status=status,
            started_at=required_datetime_from_db(str(run["started_at"])),
            completed_at=(
                None
                if status is EbookFixityVerificationRunStatus.RUNNING
                else required_datetime_from_db(str(terminal["occurred_at"]))
            ),
            expected_result_count=int(run["expected_result_count"]),
            result_count=result_count,
            failure_code=_text_or_none(terminal["failure_code"]),
        )

    def append_expectation_revision(
        self,
        decision: EbookFixityExpectationDecisionInput,
        *,
        created_at: datetime,
        lease_token: str,
        lease_expires_at: datetime,
    ) -> EbookFixityExpectationRevision:
        try:
            with self._engine.begin() as connection:
                return self.append_expectation_revision_in_transaction(
                    connection,
                    decision,
                    created_at=created_at,
                    lease_token=lease_token,
                    lease_expires_at=lease_expires_at,
                )
        except EbookFixityVerificationStoreError:
            raise
        except (IntegrityError, ScanRootWriteLeaseError, TypeError, ValueError) as error:
            raise EbookFixityVerificationStoreError(
                "fixity expectation revision could not be appended"
            ) from error

    def append_expectation_revision_in_transaction(
        self,
        connection: Connection,
        decision: EbookFixityExpectationDecisionInput,
        *,
        created_at: datetime,
        lease_token: str,
        lease_expires_at: datetime,
    ) -> EbookFixityExpectationRevision:
        """Connection-scoped core preserving all revision and lease fences."""

        existing = self._revision_by_id(connection, decision.expectation_revision_id)
        if existing is not None:
            self._require_revision_retry_matches(existing, decision, created_at)
            return existing
        result_row, run_row = self._result_and_run(connection, decision.result_id)
        if (
            str(result_row["run_id"]) != str(decision.run_id)
            or str(result_row["file_id"]) != str(decision.file_id)
        ):
            raise EbookFixityVerificationStoreError(
                "expectation decision does not bind the selected result"
            )
        scan_root_id = EntityId.parse(str(run_row["scan_root_id"]))
        lease = self._leases.acquire_in_transaction(
            connection,
            scan_root_id,
            ScanRootWriteOwnerKind.EBOOK_FIXITY_VERIFICATION,
            decision.expectation_revision_id,
            lease_token=lease_token,
            acquired_at=created_at,
            lease_expires_at=lease_expires_at,
        )
        self._leases.fence(connection, lease, created_at)
        self._require_completed_run(connection, decision.run_id)
        self._require_latest_verification_run(connection, scan_root_id, decision.run_id)
        self._require_latest_completed_scan(
            connection,
            scan_root_id,
            EntityId.parse(str(run_row["source_scan_run_id"])),
        )
        activation_id = EntityId.parse(str(run_row["baseline_activation_id"]))
        revision_no, previous_digest = self._current_revision(
            connection,
            scan_root_id,
            activation_id,
        )
        if (
            int(run_row["expectation_revision_no"]) != revision_no
            or str(run_row["expectation_revision_digest"]) != previous_digest
        ):
            raise EbookFixityVerificationStoreError(
                "verification result expectation lineage is stale"
            )
        self._require_latest_accept(connection, decision, result_row, run_row)
        expected = self._revision_expected_state(decision, result_row)
        next_revision_no = revision_no + 1
        review_decision_id = _required_review_decision_id(decision)
        revision_digest = _sha256(
            {
                "profile": EBOOK_FIXITY_DECISION_PROFILE,
                "serializer": EBOOK_FIXITY_SERIALIZER,
                "scan_root_id": str(scan_root_id),
                "baseline_activation_id": str(activation_id),
                "revision_no": next_revision_no,
                "previous_revision_digest": previous_digest,
                "file_id": str(decision.file_id),
                "action": decision.action.value,
                "source_result_id": str(decision.result_id),
                "review_decision_id": str(review_decision_id),
                "expected": {
                    "observation_id": None if expected[0] is None else str(expected[0]),
                    "size_bytes": expected[1],
                    "sha256": expected[2],
                    "relative_locator": expected[3],
                },
            }
        )
        revision = EbookFixityExpectationRevision(
            id=decision.expectation_revision_id,
            file_id=decision.file_id,
            source_result_id=decision.result_id,
            action=decision.action,
            result=_decode_result(result_row),
            scan_root_id=scan_root_id,
            baseline_activation_id=activation_id,
            revision_no=next_revision_no,
            previous_revision_digest=previous_digest,
            revision_digest=revision_digest,
            review_decision_id=review_decision_id,
            expected_observation_id=expected[0],
            expected_size_bytes=expected[1],
            expected_sha256=expected[2],
            expected_relative_locator=expected[3],
            evidence_fingerprint=decision.evidence_fingerprint,
            candidate_set_fingerprint=decision.candidate_set_fingerprint,
            created_at=created_at,
        )
        connection.execute(
            insert(fv_schema.ebook_fixity_expectation_revisions),
            self._revision_row(revision),
        )
        self._leases.release_in_transaction(connection, lease, released_at=created_at)
        return revision

    def _release_best_effort(
        self,
        lease: OwnedScanRootWriteLease,
        released_at: datetime,
    ) -> None:
        try:
            self._leases.release(lease, released_at=released_at)
        except (ScanRootWriteLeaseError, ValueError):
            pass

    def _acquire_or_recover_verification_lease(
        self,
        connection: Connection,
        run: EbookFixityVerificationRun,
        *,
        lease_token: str,
        lease_expires_at: datetime,
    ) -> OwnedScanRootWriteLease:
        current = self._leases.current_in_transaction(connection, run.scan_root_id)
        if current is None:
            return self._leases.acquire_in_transaction(
                connection,
                run.scan_root_id,
                ScanRootWriteOwnerKind.EBOOK_FIXITY_VERIFICATION,
                run.run_id,
                lease_token=lease_token,
                acquired_at=run.started_at,
                lease_expires_at=lease_expires_at,
            )
        if (
            current.owner_kind is not ScanRootWriteOwnerKind.EBOOK_FIXITY_VERIFICATION
            or current.lease_expires_at > run.started_at
        ):
            raise EbookFixityVerificationStoreError(
                "fixity verification ScanRoot lease is unavailable"
            )
        terminal = connection.execute(
            select(fv_schema.ebook_fixity_verification_events.c.run_id)
            .where(
                fv_schema.ebook_fixity_verification_events.c.run_id == str(current.owner_run_id),
                fv_schema.ebook_fixity_verification_events.c.sequence_no == 1,
            )
            .limit(1)
        ).first()
        prior_run = self._run_row_or_none(connection, current.owner_run_id)
        if prior_run is not None and terminal is None:
            self._insert_event(
                connection,
                current.owner_run_id,
                1,
                EbookFixityVerificationRunStatus.FAILED,
                run.started_at,
                failure_code="LEASE_EXPIRED",
            )
        return self._leases.takeover_expired_in_transaction(
            connection,
            current,
            run.run_id,
            lease_token=lease_token,
            acquired_at=run.started_at,
            lease_expires_at=lease_expires_at,
        )

    def _fence_open_run(
        self,
        connection: Connection,
        owned: OwnedEbookFixityVerificationRun,
        now: datetime,
    ) -> None:
        self._leases.fence(connection, owned.write_lease, now)
        terminal = connection.execute(
            select(fv_schema.ebook_fixity_verification_events.c.run_id)
            .where(
                fv_schema.ebook_fixity_verification_events.c.run_id == str(owned.run.run_id),
                fv_schema.ebook_fixity_verification_events.c.sequence_no == 1,
            )
            .limit(1)
        ).first()
        if terminal is not None:
            raise EbookFixityVerificationStoreError("fixity verification run is terminal")

    def _require_run_binders_current(
        self,
        connection: Connection,
        run: EbookFixityVerificationRun,
    ) -> None:
        self._require_latest_completed_scan(
            connection,
            run.scan_root_id,
            run.source_scan_run_id,
        )
        revision_no, revision_digest = self._current_revision(
            connection,
            run.scan_root_id,
            run.baseline_activation_id,
        )
        if (
            revision_no != run.expectation_revision_no
            or revision_digest != run.expectation_revision_digest
        ):
            raise EbookFixityVerificationStoreError(
                "fixity verification expectation revision changed during run"
            )

    @staticmethod
    def _insert_event(
        connection: Connection,
        run_id: EntityId,
        sequence_no: int,
        status: EbookFixityVerificationRunStatus,
        occurred_at: datetime,
        *,
        failure_code: str | None = None,
        content_digest: str | None = None,
    ) -> None:
        connection.execute(
            insert(fv_schema.ebook_fixity_verification_events),
            {
                "run_id": str(run_id),
                "sequence_no": sequence_no,
                "status": status.value,
                "occurred_at": _datetime(occurred_at),
                "failure_code": failure_code,
                "content_digest": content_digest,
            },
        )

    @staticmethod
    def _require_result_matches_workset(
        result: EbookFixityVerificationResultRecord,
        work_item: EbookFixityVerificationWorkItem | None,
    ) -> None:
        if work_item is None:
            raise EbookFixityVerificationStoreError(
                "verification result file is outside the bound workset"
            )
        if (
            result.expected_observation_id,
            result.expected_size_bytes,
            result.expected_sha256,
            result.expected_relative_locator,
        ) != (
            work_item.expected_observation_id,
            work_item.expected_size_bytes,
            work_item.expected_sha256,
            work_item.expected_relative_locator,
        ):
            raise EbookFixityVerificationStoreError(
                "verification result expected state is not the bound revision"
            )
        if (
            result.current_observation_id,
            result.current_size_bytes,
            result.current_relative_locator,
        ) != (
            work_item.current_observation_id,
            work_item.current_size_bytes,
            work_item.current_relative_locator,
        ):
            raise EbookFixityVerificationStoreError(
                "verification result current state is not the bound scan snapshot"
            )

    @staticmethod
    def _result_row(
        result: EbookFixityVerificationResultRecord,
        recorded_at: datetime,
    ) -> dict[str, object]:
        return {
            "id": str(result.result_id),
            "profile": EBOOK_FIXITY_RESULT_PROFILE,
            "run_id": str(result.run_id),
            "file_id": str(result.file_id),
            "result_type": result.result.value,
            "expected_observation_id": _entity_or_none(result.expected_observation_id),
            "expected_size_bytes": result.expected_size_bytes,
            "expected_sha256": result.expected_sha256,
            "expected_relative_locator": result.expected_relative_locator,
            "current_observation_id": _entity_or_none(result.current_observation_id),
            "current_size_bytes": result.current_size_bytes,
            "current_sha256": result.current_sha256,
            "current_relative_locator": result.current_relative_locator,
            "failure_code": result.failure_code,
            "content_digest": result.content_digest,
            "recorded_at": _datetime(recorded_at),
        }

    def _result_for_file(
        self,
        connection: Connection,
        run_id: EntityId,
        file_id: EntityId,
    ) -> EbookFixityVerificationResultRecord | None:
        row = (
            connection.execute(
                select(fv_schema.ebook_fixity_verification_results).where(
                    fv_schema.ebook_fixity_verification_results.c.run_id == str(run_id),
                    fv_schema.ebook_fixity_verification_results.c.file_id == str(file_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _decode_result(row)

    @staticmethod
    def _run_row(connection: Connection, run_id: EntityId) -> RowMapping:
        row = SQLiteEbookFixityVerificationStore._run_row_or_none(connection, run_id)
        if row is None:
            raise EbookFixityVerificationStoreError("fixity verification run is unavailable")
        return row

    @staticmethod
    def _run_row_or_none(connection: Connection, run_id: EntityId) -> RowMapping | None:
        return (
            connection.execute(
                select(fv_schema.ebook_fixity_verification_runs).where(
                    fv_schema.ebook_fixity_verification_runs.c.id == str(run_id)
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _result_and_run(
        connection: Connection,
        result_id: EntityId,
    ) -> tuple[RowMapping, RowMapping]:
        result = (
            connection.execute(
                select(fv_schema.ebook_fixity_verification_results).where(
                    fv_schema.ebook_fixity_verification_results.c.id == str(result_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if result is None:
            raise EbookFixityVerificationStoreError("fixity result is unavailable")
        run = SQLiteEbookFixityVerificationStore._run_row(
            connection,
            EntityId.parse(str(result["run_id"])),
        )
        return result, run

    @staticmethod
    def _require_completed_run(connection: Connection, run_id: EntityId) -> RowMapping:
        row = (
            connection.execute(
                select(fv_schema.ebook_fixity_verification_events).where(
                    fv_schema.ebook_fixity_verification_events.c.run_id == str(run_id),
                    fv_schema.ebook_fixity_verification_events.c.sequence_no == 1,
                    fv_schema.ebook_fixity_verification_events.c.status
                    == EbookFixityVerificationRunStatus.COMPLETED.value,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["content_digest"] is None:
            raise EbookFixityVerificationStoreError(
                "fixity result does not belong to a completed run"
            )
        return row

    @staticmethod
    def _require_latest_accept(
        connection: Connection,
        decision: EbookFixityExpectationDecisionInput,
        result: RowMapping,
        run: RowMapping,
    ) -> None:
        review_decision_id = _required_review_decision_id(decision)
        terminal = SQLiteEbookFixityVerificationStore._require_completed_run(
            connection,
            decision.run_id,
        )
        record = _decode_result(result)
        expected_evidence = verification_evidence_fingerprint(
            subject_id=record.file_id,
            scan_root_id=EntityId.parse(str(run["scan_root_id"])),
            baseline_activation_id=EntityId.parse(str(run["baseline_activation_id"])),
            expectation_revision_no=int(run["expectation_revision_no"]),
            expectation_revision_digest=str(run["expectation_revision_digest"]),
            scan_run_id=EntityId.parse(str(run["source_scan_run_id"])),
            verification_run_id=record.run_id,
            verification_run_content_digest=str(terminal["content_digest"]),
            result_id=record.result_id,
            result_content_digest=record.content_digest,
        )
        expected_candidates = verification_candidate_set_fingerprint(record)
        if (
            decision.evidence_fingerprint != expected_evidence
            or decision.candidate_set_fingerprint != expected_candidates
        ):
            raise EbookFixityVerificationStoreError("expectation decision fingerprints are stale")
        item = rr_schema.review_items
        history = rr_schema.review_decisions
        latest = history.alias("latest_fixity_review_decision")
        row = connection.execute(
            select(history.c.id)
            .join(item, item.c.id == history.c.review_item_id)
            .where(
                history.c.id == str(review_decision_id),
                history.c.decision == ReviewDecisionValue.ACCEPT.value,
                history.c.evidence_fingerprint == expected_evidence,
                history.c.candidate_set_fingerprint == expected_candidates,
                history.c.decision_compatibility_version == EBOOK_FIXITY_DECISION_PROFILE,
                item.c.review_type == ReviewType.FIXITY_EXPECTATION.value,
                item.c.subject_kind == "FILE",
                item.c.subject_id == str(decision.file_id),
                item.c.candidate_kind == ReviewCandidateKind.FIXITY_RESULT.value,
                item.c.candidate_id == str(decision.result_id),
                item.c.evidence_fingerprint == expected_evidence,
                item.c.candidate_set_fingerprint == expected_candidates,
                history.c.sequence_no
                == select(func.max(latest.c.sequence_no))
                .where(latest.c.review_item_id == item.c.id)
                .correlate(item)
                .scalar_subquery(),
            )
        ).one_or_none()
        if row is None:
            raise EbookFixityVerificationStoreError(
                "latest compatible fixity review decision is not ACCEPT"
            )

    @staticmethod
    def _revision_expected_state(
        decision: EbookFixityExpectationDecisionInput,
        result: RowMapping,
    ) -> tuple[EntityId | None, int | None, str | None, str | None]:
        result_type = EbookFixityVerificationResult(str(result["result_type"]))
        if decision.action is EbookFixityExpectationAction.ACCEPT_CURRENT:
            if result_type not in {
                EbookFixityVerificationResult.UNEXPECTED_BYTE_CHANGE,
                EbookFixityVerificationResult.UNBASELINED,
            }:
                raise EbookFixityVerificationStoreError(
                    "ACCEPT_CURRENT requires a changed or unbaselined result"
                )
            values = (
                _entity_id_or_none(result["current_observation_id"]),
                _int_or_none(result["current_size_bytes"]),
                _text_or_none(result["current_sha256"]),
                _text_or_none(result["current_relative_locator"]),
            )
            if any(value is None for value in values):
                raise EbookFixityVerificationStoreError(
                    "ACCEPT_CURRENT result has no complete current state"
                )
            return values
        if result_type is not EbookFixityVerificationResult.MISSING:
            raise EbookFixityVerificationStoreError("RETIRE_MISSING requires a missing result")
        return None, None, None, None

    @staticmethod
    def _revision_row(
        revision: EbookFixityExpectationRevision,
    ) -> dict[str, object]:
        return {
            "id": str(revision.id),
            "profile": EBOOK_FIXITY_DECISION_PROFILE,
            "serializer": EBOOK_FIXITY_SERIALIZER,
            "scan_root_id": str(revision.scan_root_id),
            "baseline_activation_id": str(revision.baseline_activation_id),
            "revision_no": revision.revision_no,
            "previous_revision_digest": revision.previous_revision_digest,
            "revision_digest": revision.revision_digest,
            "file_id": str(revision.file_id),
            "action": revision.action.value,
            "source_result_id": str(revision.source_result_id),
            "review_decision_id": str(revision.review_decision_id),
            "expected_observation_id": _entity_or_none(revision.expected_observation_id),
            "expected_size_bytes": revision.expected_size_bytes,
            "expected_sha256": revision.expected_sha256,
            "expected_relative_locator": revision.expected_relative_locator,
            "evidence_fingerprint": revision.evidence_fingerprint,
            "candidate_set_fingerprint": revision.candidate_set_fingerprint,
            "created_at": _datetime(revision.created_at),
        }

    @staticmethod
    def _revision_by_id(
        connection: Connection,
        revision_id: EntityId,
    ) -> EbookFixityExpectationRevision | None:
        row = (
            connection.execute(
                select(fv_schema.ebook_fixity_expectation_revisions).where(
                    fv_schema.ebook_fixity_expectation_revisions.c.id == str(revision_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        result_row = (
            connection.execute(
                select(fv_schema.ebook_fixity_verification_results).where(
                    fv_schema.ebook_fixity_verification_results.c.id == str(row["source_result_id"])
                )
            )
            .mappings()
            .one_or_none()
        )
        if result_row is None:
            raise EbookFixityVerificationStoreError(
                "expectation revision source result is unavailable"
            )
        return _decode_revision(row, _decode_result(result_row))

    @staticmethod
    def _require_revision_retry_matches(
        existing: EbookFixityExpectationRevision,
        decision: EbookFixityExpectationDecisionInput,
        created_at: datetime,
    ) -> None:
        if (
            existing.id != decision.expectation_revision_id
            or existing.source_result_id != decision.result_id
            or existing.result.run_id != decision.run_id
            or existing.file_id != decision.file_id
            or existing.action is not decision.action
            or existing.review_decision_id != decision.review_decision_id
            or existing.evidence_fingerprint != decision.evidence_fingerprint
            or existing.candidate_set_fingerprint != decision.candidate_set_fingerprint
            or existing.created_at != created_at
        ):
            raise EbookFixityVerificationStoreError(
                "expectation revision ID retry has different immutable content"
            )

    @staticmethod
    def _current_revision(
        connection: Connection,
        scan_root_id: EntityId,
        activation_id: EntityId,
    ) -> tuple[int, str]:
        activation = (
            connection.execute(
                select(
                    fixity_schema.ebook_fixity_baseline_activations.c.activation_digest,
                    fixity_schema.ebook_fixity_baseline_activations.c.scan_root_id,
                ).where(
                    fixity_schema.ebook_fixity_baseline_activations.c.activation_id
                    == str(activation_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if activation is None or str(activation["scan_root_id"]) != str(scan_root_id):
            raise EbookFixityVerificationStoreError(
                "active fixity baseline does not match the ScanRoot"
            )
        latest = (
            connection.execute(
                select(fv_schema.ebook_fixity_expectation_revisions)
                .where(
                    fv_schema.ebook_fixity_expectation_revisions.c.scan_root_id == str(scan_root_id)
                )
                .order_by(fv_schema.ebook_fixity_expectation_revisions.c.revision_no.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if latest is None:
            return 0, str(activation["activation_digest"])
        if str(latest["baseline_activation_id"]) != str(activation_id):
            raise EbookFixityVerificationStoreError(
                "expectation revision belongs to another baseline activation"
            )
        return int(latest["revision_no"]), str(latest["revision_digest"])

    @staticmethod
    def _workset_parameters(
        run: EbookFixityVerificationRun,
        *,
        after_file_id: EntityId | None = None,
        batch_size: int | None = None,
    ) -> dict[str, object]:
        values: dict[str, object] = {
            "scan_root_id": str(run.scan_root_id),
            "activation_id": str(run.baseline_activation_id),
            "revision_no": run.expectation_revision_no,
            "scan_run_id": str(run.source_scan_run_id),
            "ebook_media_type": MediaType.EBOOK.value,
            "present_state": PresenceState.PRESENT.value,
            "accept_action": EbookFixityExpectationAction.ACCEPT_CURRENT.value,
            "after_file_id": "" if after_file_id is None else str(after_file_id),
        }
        if batch_size is not None:
            values["batch_size"] = batch_size
        return values

    def _workset_count(
        self,
        connection: Connection,
        run: EbookFixityVerificationRun,
    ) -> int:
        return int(
            connection.execute(
                text(_WORKSET_CTE + "SELECT COUNT(*) FROM workset_ids"),
                self._workset_parameters(run),
            ).scalar_one()
        )

    def _work_item(
        self,
        connection: Connection,
        run: EbookFixityVerificationRun,
        file_id: EntityId,
    ) -> EbookFixityVerificationWorkItem | None:
        params = self._workset_parameters(run)
        params["selected_file_id"] = str(file_id)
        row = (
            connection.execute(text(_WORKSET_CTE + _WORKSET_ONE_SQL), params)
            .mappings()
            .one_or_none()
        )
        return None if row is None else _decode_work_item(row)

    @staticmethod
    def _require_current_snapshot_coverage(
        connection: Connection,
        scan_root_id: EntityId,
        scan_run_id: EntityId,
    ) -> None:
        missing = connection.execute(
            select(schema.file_records.c.id)
            .where(
                schema.file_records.c.scan_root_id == str(scan_root_id),
                schema.file_records.c.media_type == MediaType.EBOOK.value,
                schema.file_records.c.presence_state == PresenceState.PRESENT.value,
                ~select(schema.file_observations.c.id)
                .where(
                    schema.file_observations.c.scan_run_id == str(scan_run_id),
                    schema.file_observations.c.file_id == schema.file_records.c.id,
                    schema.file_observations.c.relative_path == schema.file_records.c.relative_path,
                    schema.file_observations.c.size_bytes == schema.file_records.c.size_bytes,
                    schema.file_observations.c.modified_at == schema.file_records.c.modified_at,
                )
                .exists(),
            )
            .limit(1)
        ).first()
        if missing is not None:
            raise EbookFixityVerificationStoreError(
                "latest ScanRun does not cover all current PRESENT files"
            )
        duplicate = connection.execute(
            select(schema.file_observations.c.file_id)
            .join(
                schema.file_records,
                schema.file_records.c.id == schema.file_observations.c.file_id,
            )
            .where(
                schema.file_observations.c.scan_run_id == str(scan_run_id),
                schema.file_records.c.scan_root_id == str(scan_root_id),
                schema.file_records.c.media_type == MediaType.EBOOK.value,
                schema.file_records.c.presence_state == PresenceState.PRESENT.value,
                schema.file_observations.c.relative_path == schema.file_records.c.relative_path,
                schema.file_observations.c.size_bytes == schema.file_records.c.size_bytes,
                schema.file_observations.c.modified_at == schema.file_records.c.modified_at,
            )
            .group_by(schema.file_observations.c.file_id)
            .having(func.count() != 1)
            .limit(1)
        ).first()
        if duplicate is not None:
            raise EbookFixityVerificationStoreError(
                "latest ScanRun has ambiguous current PRESENT observations"
            )

    @staticmethod
    def _run_content_digest(
        connection: Connection,
        owned: OwnedEbookFixityVerificationRun,
        completed_at: datetime,
    ) -> str:
        rows = connection.execute(
            select(fv_schema.ebook_fixity_verification_results)
            .where(fv_schema.ebook_fixity_verification_results.c.run_id == str(owned.run.run_id))
            .order_by(fv_schema.ebook_fixity_verification_results.c.file_id)
        ).mappings()
        result_count, results_digest = verification_results_digest(
            _decode_result(row) for row in rows
        )
        if result_count != owned.expected_result_count:
            raise EbookFixityVerificationStoreError(
                "verification result stream changed during completion"
            )
        return verification_run_content_digest(
            run_id=owned.run.run_id,
            baseline_activation_id=owned.run.baseline_activation_id,
            scan_root_id=owned.run.scan_root_id,
            source_scan_run_id=owned.run.source_scan_run_id,
            expectation_revision_no=owned.run.expectation_revision_no,
            expectation_revision_digest=owned.run.expectation_revision_digest,
            result_count=result_count,
            results_digest=results_digest,
            started_at=owned.run.started_at,
            completed_at=completed_at,
        )

    @staticmethod
    def _require_latest_completed_scan(
        connection: Connection,
        scan_root_id: EntityId,
        expected_scan_run_id: EntityId,
    ) -> None:
        latest_id = SQLiteEbookFixityVerificationStore._latest_completed_scan(
            connection, scan_root_id
        )
        if latest_id != expected_scan_run_id:
            raise EbookFixityVerificationStoreError(
                "fixity verification requires the latest completed EBOOK ScanRun"
            )

    @staticmethod
    def _require_latest_verification_run(
        connection: Connection,
        scan_root_id: EntityId,
        expected_run_id: EntityId,
    ) -> None:
        latest_id = connection.execute(
            select(fv_schema.ebook_fixity_verification_runs.c.id)
            .where(
                fv_schema.ebook_fixity_verification_runs.c.scan_root_id
                == str(scan_root_id)
            )
            .order_by(
                fv_schema.ebook_fixity_verification_runs.c.started_at.desc(),
                fv_schema.ebook_fixity_verification_runs.c.id.desc(),
            )
            .limit(1)
        ).scalar_one_or_none()
        if latest_id is None or str(latest_id) != str(expected_run_id):
            raise EbookFixityVerificationStoreError(
                "expectation decision requires the latest verification run"
            )

    @staticmethod
    def _latest_completed_scan(
        connection: Connection,
        scan_root_id: EntityId,
    ) -> EntityId:
        enabled_roots = connection.execute(
            select(schema.scan_roots.c.id)
            .where(
                schema.scan_roots.c.media_type == MediaType.EBOOK.value,
                schema.scan_roots.c.enabled.is_(True),
            )
            .limit(2)
        ).all()
        if len(enabled_roots) != 1 or str(enabled_roots[0][0]) != str(scan_root_id):
            raise EbookFixityVerificationStoreError(
                "fixity verification requires exactly one enabled EBOOK ScanRoot"
            )
        latest = (
            connection.execute(
                select(
                    schema.scan_runs.c.id,
                    schema.scan_runs.c.status,
                    schema.scan_runs.c.completed_at,
                    schema.scan_roots.c.media_type,
                    schema.scan_roots.c.enabled,
                )
                .join(
                    schema.scan_roots,
                    schema.scan_roots.c.id == schema.scan_runs.c.scan_root_id,
                )
                .where(schema.scan_runs.c.scan_root_id == str(scan_root_id))
                .order_by(schema.scan_runs.c.started_at.desc(), schema.scan_runs.c.id.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if (
            latest is None
            or str(latest["status"]) != ScanRunStatus.COMPLETED.value
            or latest["completed_at"] is None
            or str(latest["media_type"]) != MediaType.EBOOK.value
            or not bool(latest["enabled"])
        ):
            raise EbookFixityVerificationStoreError(
                "fixity verification requires the latest completed EBOOK ScanRun"
            )
        return EntityId.parse(str(latest["id"]))

    @staticmethod
    def _active_baseline_id(
        connection: Connection,
        scan_root_id: EntityId,
    ) -> EntityId:
        rows = connection.execute(
            select(fixity_schema.ebook_fixity_baseline_activations.c.activation_id)
            .where(
                fixity_schema.ebook_fixity_baseline_activations.c.scan_root_id == str(scan_root_id),
                fixity_schema.ebook_fixity_baseline_activations.c.profile
                == "ebook-fixity-baseline/v1",
            )
            .limit(2)
        ).all()
        if len(rows) != 1:
            raise EbookFixityVerificationStoreError(
                "fixity verification requires exactly one active EBOOK baseline"
            )
        return EntityId.parse(str(rows[0][0]))


def _decode_result(row: RowMapping) -> EbookFixityVerificationResultRecord:
    return EbookFixityVerificationResultRecord(
        result_id=EntityId.parse(str(row["id"])),
        run_id=EntityId.parse(str(row["run_id"])),
        file_id=EntityId.parse(str(row["file_id"])),
        result=EbookFixityVerificationResult(str(row["result_type"])),
        expected_observation_id=_entity_id_or_none(row["expected_observation_id"]),
        expected_size_bytes=_int_or_none(row["expected_size_bytes"]),
        expected_sha256=_text_or_none(row["expected_sha256"]),
        expected_relative_locator=_text_or_none(row["expected_relative_locator"]),
        current_observation_id=_entity_id_or_none(row["current_observation_id"]),
        current_size_bytes=_int_or_none(row["current_size_bytes"]),
        current_sha256=_text_or_none(row["current_sha256"]),
        current_relative_locator=_text_or_none(row["current_relative_locator"]),
        failure_code=_text_or_none(row["failure_code"]),
        content_digest=str(row["content_digest"]),
    )


def _decode_work_item(row: RowMapping) -> EbookFixityVerificationWorkItem:
    return EbookFixityVerificationWorkItem(
        file_id=EntityId.parse(str(row["file_id"])),
        expected_observation_id=_entity_id_or_none(row["expected_observation_id"]),
        expected_size_bytes=_int_or_none(row["expected_size_bytes"]),
        expected_sha256=_text_or_none(row["expected_sha256"]),
        expected_relative_locator=_text_or_none(row["expected_relative_locator"]),
        current_observation_id=_entity_id_or_none(row["current_observation_id"]),
        current_size_bytes=_int_or_none(row["current_size_bytes"]),
        current_modified_at=(
            None
            if row["current_modified_at"] is None
            else required_datetime_from_db(str(row["current_modified_at"]))
        ),
        current_relative_locator=_text_or_none(row["current_relative_locator"]),
    )


def _decode_revision(
    row: RowMapping,
    result: EbookFixityVerificationResultRecord,
) -> EbookFixityExpectationRevision:
    return EbookFixityExpectationRevision(
        id=EntityId.parse(str(row["id"])),
        file_id=EntityId.parse(str(row["file_id"])),
        source_result_id=EntityId.parse(str(row["source_result_id"])),
        action=EbookFixityExpectationAction(str(row["action"])),
        result=result,
        scan_root_id=EntityId.parse(str(row["scan_root_id"])),
        baseline_activation_id=EntityId.parse(str(row["baseline_activation_id"])),
        revision_no=int(row["revision_no"]),
        previous_revision_digest=str(row["previous_revision_digest"]),
        revision_digest=str(row["revision_digest"]),
        review_decision_id=EntityId.parse(str(row["review_decision_id"])),
        expected_observation_id=_entity_id_or_none(row["expected_observation_id"]),
        expected_size_bytes=_int_or_none(row["expected_size_bytes"]),
        expected_sha256=_text_or_none(row["expected_sha256"]),
        expected_relative_locator=_text_or_none(row["expected_relative_locator"]),
        evidence_fingerprint=str(row["evidence_fingerprint"]),
        candidate_set_fingerprint=str(row["candidate_set_fingerprint"]),
        created_at=required_datetime_from_db(str(row["created_at"])),
    )


def _required_review_decision_id(
    decision: EbookFixityExpectationDecisionInput,
) -> EntityId:
    if decision.review_decision_id is None:
        raise EbookFixityVerificationStoreError(
            "expectation revision requires an exact review decision"
        )
    return decision.review_decision_id


def _sha256(payload: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _datetime(value: datetime) -> str:
    encoded = datetime_to_db(value)
    if encoded is None:
        raise ValueError("fixity verification datetime is required")
    return encoded


def _entity_or_none(value: EntityId | None) -> str | None:
    return None if value is None else str(value)


def _entity_id_or_none(value: object) -> EntityId | None:
    return None if value is None else EntityId.parse(str(value))


def _int_or_none(value: object) -> int | None:
    return None if value is None else int(str(value))


def _text_or_none(value: object) -> str | None:
    return None if value is None else str(value)


__all__ = [
    "DEFAULT_EBOOK_FIXITY_VERIFICATION_LEASE_DURATION",
    "EbookFixityVerificationStatusSnapshot",
    "EbookFixityVerificationStoreError",
    "EbookFixityVerificationWorkItem",
    "OwnedEbookFixityVerificationRun",
    "SQLiteEbookFixityVerificationStore",
]
