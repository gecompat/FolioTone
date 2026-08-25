"""Application services over existing FolioTone workflows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from foliotone.application.contracts import (
    ApplicationJobDetailQuery,
    CollectionSearchQuery,
    CollectionStateQuery,
    EbookProjectionQuery,
    EbookRenamePlanCommand,
    EbookRenamePreviewQuery,
    EbookRenameProposalCommand,
    EbookRenameReviewCommand,
    EbookToolchainReadinessQuery,
    LibraryHealthQuery,
    MediaLineRegistry,
    SurfacePageQuery,
)
from foliotone.collection_state import CollectionQuerySpec
from foliotone.core.ids import EntityId
from foliotone.core.review_models import ReviewDecisionValue
from foliotone.tooling.ebook_readiness import EbookToolchainReadinessReport
from foliotone.workflows.collection_state import CollectionStateReport
from foliotone.workflows.collection_state_query import CollectionQueryReport
from foliotone.workflows.ebook_rename_planning import (
    EbookRenamePlanResult,
    EbookRenamePreview,
    EbookRenameProposalResult,
    EbookRenameReviewResult,
)
from foliotone.workflows.library_health import LibraryHealthReport


class LibraryHealthReader(Protocol):
    """Port for reading a persisted Health projection."""

    def read(
        self,
        snapshot_id: EntityId,
        *,
        baseline_snapshot_id: EntityId | None,
        sample_limit: int,
    ) -> LibraryHealthReport: ...


class CollectionStateReader(Protocol):
    """Port for reading one immutable CollectionState projection."""

    def read(self, snapshot_id: EntityId) -> CollectionStateReport: ...


class CollectionSearchReader(Protocol):
    """Port for the bounded persisted CollectionState search projection."""

    def search(
        self,
        snapshot_id: EntityId,
        spec: CollectionQuerySpec,
        *,
        private_details: bool = False,
    ) -> CollectionQueryReport: ...


class SurfaceReadModel(Protocol):
    """Port for public, bounded surface-owned job and audit projections."""

    def list_jobs(
        self, *, after_id: str | None, limit: int
    ) -> tuple[tuple[dict[str, object], ...], str | None]: ...

    def job_detail(self, job_id: str) -> dict[str, object] | None: ...

    def list_audit_events(
        self, *, after_id: str | None, limit: int
    ) -> tuple[tuple[dict[str, object], ...], str | None]: ...


class EbookReadModel(Protocol):
    """Port for path-free persisted E-Book status and evidence projections."""

    def scan_status(self, scan_root_id: EntityId) -> dict[str, object] | None: ...

    def inventory(self, scan_root_id: EntityId) -> dict[str, object] | None: ...

    def collection_analysis(self, run_id: EntityId) -> dict[str, object] | None: ...

    def review_queue(
        self, run_id: EntityId, *, after_id: str | None, limit: int
    ) -> tuple[tuple[dict[str, object], ...], str | None]: ...

    def candidate_evidence(self, run_id: EntityId) -> dict[str, object] | None: ...

    def list_plans(
        self, *, after_id: str | None, limit: int
    ) -> tuple[tuple[dict[str, object], ...], str | None]: ...

    def plan_report(self, plan_id: EntityId) -> dict[str, object] | None: ...


class EbookRenamePlanningPort(Protocol):
    """The existing ADR-0066 planning workflow behind the Application boundary."""

    def propose(
        self, observation_id: EntityId, dependency_scope_id: EntityId, target_basename: str
    ) -> EbookRenameProposalResult: ...

    def preview(self, candidate_id: EntityId) -> EbookRenamePreview: ...

    def review(
        self, candidate_id: EntityId, decision: ReviewDecisionValue
    ) -> EbookRenameReviewResult: ...

    def plan(self, candidate_id: EntityId) -> EbookRenamePlanResult: ...


class FolioToneApplication:
    """Adapter-neutral read-only Application surface for the first product slice."""

    def __init__(
        self,
        *,
        media_lines: MediaLineRegistry,
        toolchain_inspector: Callable[..., EbookToolchainReadinessReport],
    ) -> None:
        self._media_lines = media_lines
        self._toolchain_inspector = toolchain_inspector

    @property
    def media_lines(self) -> MediaLineRegistry:
        """Return the stable product-entry registry."""
        return self._media_lines

    def ebook_toolchain_readiness(
        self, query: EbookToolchainReadinessQuery
    ) -> EbookToolchainReadinessReport:
        """Run the existing non-mutating Doctor through the Application boundary."""
        return self._toolchain_inspector(
            ebook_meta_executable=query.ebook_meta_executable,
            ebook_convert_executable=query.ebook_convert_executable,
            calibre_debug_executable=query.calibre_debug_executable,
            pdfinfo_executable=query.pdfinfo_executable,
            pdftotext_executable=query.pdftotext_executable,
            java_executable=query.java_executable,
            epubcheck_jar=query.epubcheck_jar,
        )

    def library_health_report(
        self, reader: LibraryHealthReader, query: LibraryHealthQuery
    ) -> LibraryHealthReport:
        """Read an immutable Health projection through an injected persistence port."""
        return reader.read(
            query.snapshot_id,
            baseline_snapshot_id=query.baseline_snapshot_id,
            sample_limit=query.sample_limit,
        )

    def collection_state_report(
        self,
        reader: CollectionStateReader,
        query: CollectionStateQuery,
    ) -> CollectionStateReport:
        """Read one immutable CollectionState through an injected persistence port."""
        return reader.read(query.snapshot_id)

    def collection_search(
        self,
        reader: CollectionSearchReader,
        query: CollectionSearchQuery,
    ) -> CollectionQueryReport:
        """Run an existing bounded search through the application boundary."""
        return reader.search(query.snapshot_id, query.spec, private_details=query.private_details)

    def jobs(
        self, reader: SurfaceReadModel, query: SurfacePageQuery
    ) -> tuple[tuple[dict[str, object], ...], str | None]:
        """Read a bounded public job list through the application boundary."""
        return reader.list_jobs(after_id=query.after_id, limit=query.limit)

    def job_detail(
        self, reader: SurfaceReadModel, query: ApplicationJobDetailQuery
    ) -> dict[str, object] | None:
        """Read one public job detail through the application boundary."""
        return reader.job_detail(query.job_id)

    def audit_events(
        self, reader: SurfaceReadModel, query: SurfacePageQuery
    ) -> tuple[tuple[dict[str, object], ...], str | None]:
        """Read a bounded, path-free audit list through the application boundary."""
        return reader.list_audit_events(after_id=query.after_id, limit=query.limit)

    def ebook_projection(
        self, reader: EbookReadModel, query: EbookProjectionQuery, kind: str
    ) -> dict[str, object] | None:
        """Read one explicitly named E-Book projection through its port."""
        readers = {
            "scan-status": reader.scan_status,
            "inventory": reader.inventory,
            "collection-analysis": reader.collection_analysis,
            "candidate-evidence": reader.candidate_evidence,
            "plan-report": reader.plan_report,
        }
        try:
            return readers[kind](query.projection_id)
        except KeyError as error:
            raise ValueError("E-Book projection kind is invalid") from error

    def ebook_review_queue(
        self, reader: EbookReadModel, query: EbookProjectionQuery, page: SurfacePageQuery
    ) -> tuple[tuple[dict[str, object], ...], str | None]:
        """Read a bounded Review Queue without exposing source locators."""
        return reader.review_queue(query.projection_id, after_id=page.after_id, limit=page.limit)

    def ebook_plans(
        self, reader: EbookReadModel, page: SurfacePageQuery
    ) -> tuple[tuple[dict[str, object], ...], str | None]:
        """Read bounded permanently non-executable plan summaries."""
        return reader.list_plans(after_id=page.after_id, limit=page.limit)

    def ebook_rename_proposal(
        self, service: EbookRenamePlanningPort, command: EbookRenameProposalCommand
    ) -> EbookRenameProposalResult:
        return service.propose(
            command.observation_id, command.dependency_scope_id, command.target_basename
        )

    def ebook_rename_preview(
        self, service: EbookRenamePlanningPort, query: EbookRenamePreviewQuery
    ) -> EbookRenamePreview:
        return service.preview(query.candidate_id)

    def ebook_rename_review(
        self, service: EbookRenamePlanningPort, command: EbookRenameReviewCommand
    ) -> EbookRenameReviewResult:
        try:
            decision = ReviewDecisionValue(command.decision)
        except ValueError as error:
            raise ValueError("E-book rename review decision is invalid") from error
        return service.review(command.candidate_id, decision)

    def ebook_rename_plan(
        self, service: EbookRenamePlanningPort, command: EbookRenamePlanCommand
    ) -> EbookRenamePlanResult:
        return service.plan(command.candidate_id)
