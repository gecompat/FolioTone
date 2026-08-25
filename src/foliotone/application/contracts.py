"""Versioned adapter-neutral Application contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

from foliotone.collection_state import DEFAULT_LIBRARY_HEALTH_DETAIL_LIMIT, CollectionQuerySpec
from foliotone.core.ids import EntityId

APPLICATION_CONTRACTS_PROFILE: Final = "application-contracts/v1"


class ApplicationError(RuntimeError):
    """A caller supplied an invalid request for the Application boundary."""


class EbookRenameOperatorJobProfile(StrEnum):
    """The fixed ADR-0069 commands delegated to the isolated operator role."""

    AUTHORIZE = "ebook-rename-operator-authorize/v1"
    EXECUTE = "ebook-rename-operator-execute/v1"
    RECOVER = "ebook-rename-operator-recover/v1"


class EbookFixityAnalysisJobProfile(StrEnum):
    """The only read-only fixity commands an analysis worker may execute."""

    BASELINE_BUILD = "ebook-fixity-baseline-build/v1"
    VERIFICATION = "ebook-fixity-verification/v1"


class MediaLine(StrEnum):
    """A separately activated product entry point."""

    EBOOK = "EBOOK"
    MUSIC = "MUSIC"
    IMAGE = "IMAGE"


@dataclass(frozen=True, slots=True)
class ApplicationContext:
    """Versioned request context independent of CLI, HTTP, or worker transport."""

    profile: str = APPLICATION_CONTRACTS_PROFILE
    media_line: MediaLine = MediaLine.EBOOK

    def __post_init__(self) -> None:
        if self.profile != APPLICATION_CONTRACTS_PROFILE:
            raise ApplicationError("Application context profile is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplicationCommand:
    """Base contract for a future state-changing Application request."""

    context: ApplicationContext = field(default_factory=ApplicationContext)


@dataclass(frozen=True, slots=True, kw_only=True)
class EbookRenameOperatorJobCommand(ApplicationCommand):
    """Path-free immutable input for one operation-specific worker job."""

    profile: EbookRenameOperatorJobProfile
    plan_id: EntityId | None
    plan_content_hash: str | None
    capability_id: EntityId | None
    operate_grant_id: EntityId
    authorization_id: EntityId | None = None
    run_id: EntityId | None = None
    confirmation_digest: str | None = None

    def __post_init__(self) -> None:
        shapes = {
            EbookRenameOperatorJobProfile.AUTHORIZE: (
                "required",
                "required",
                "required",
                None,
                None,
                None,
            ),
            EbookRenameOperatorJobProfile.EXECUTE: (
                "required",
                "required",
                "required",
                "required",
                None,
                "required",
            ),
            EbookRenameOperatorJobProfile.RECOVER: (None, None, None, None, "required", None),
        }
        expected = shapes[self.profile]
        actual = (
            self.plan_id,
            self.plan_content_hash,
            self.capability_id,
            self.authorization_id,
            self.run_id,
            self.confirmation_digest,
        )
        if any(
            (need == "required") != (value is not None)
            for need, value in zip(expected, actual, strict=True)
        ):
            raise ApplicationError("E-book rename operator command shape is invalid")
        if self.plan_content_hash is not None and (
            len(self.plan_content_hash) != 64
            or any(value not in "0123456789abcdef" for value in self.plan_content_hash)
        ):
            raise ApplicationError("E-book rename operator plan hash is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class EbookFixityAnalysisJobCommand(ApplicationCommand):
    """Immutable, path-free input for a read-only fixity analysis job."""

    profile: EbookFixityAnalysisJobProfile
    scan_root_id: EntityId
    worker_count: int = 1

    def __post_init__(self) -> None:
        if not 1 <= self.worker_count <= 2:
            raise ApplicationError("fixity analysis worker count is invalid")


@dataclass(frozen=True, slots=True)
class EbookFixityBaselineStatus:
    manifest_id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    status: str
    started_at: str
    prepared_at: str | None
    expires_at: str | None
    item_count: int | None
    activated_at: str | None


@dataclass(frozen=True, slots=True)
class EbookFixityVerificationStatus:
    run_id: EntityId
    scan_root_id: EntityId
    baseline_activation_id: EntityId
    source_scan_run_id: EntityId
    expectation_revision_no: int
    status: str
    started_at: str
    completed_at: str | None
    expected_result_count: int
    result_count: int
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class EbookFixityBaselineActivationResult:
    activation_id: EntityId
    manifest_id: EntityId


@dataclass(frozen=True, slots=True)
class EbookFixityReviewResult:
    result_id: EntityId
    review_item_id: EntityId
    decision_id: EntityId
    decision: str
    sequence_no: int

    def __post_init__(self) -> None:
        if self.decision not in {"ACCEPT", "REJECT", "DEFER"} or self.sequence_no < 1:
            raise ApplicationError("fixity review result is invalid")


@dataclass(frozen=True, slots=True)
class EbookFixityExpectationRevisionResult:
    result_id: EntityId
    revision_id: EntityId
    action: str
    revision_no: int

    def __post_init__(self) -> None:
        if self.action not in {"ACCEPT_CURRENT", "RETIRE_MISSING"} or self.revision_no < 1:
            raise ApplicationError("fixity expectation result is invalid")


@dataclass(frozen=True, slots=True)
class EbookFixityReviewQueueItem:
    review_item_id: EntityId
    result_id: EntityId
    file_id: EntityId
    state: str
    created_at: str


@dataclass(frozen=True, slots=True)
class EbookFixityResultSummary:
    result_id: EntityId
    file_id: EntityId
    result: str
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class EbookFixityPrivateBaselineEntry:
    """One explicitly private baseline entry exposed only after PRIVATE_READ."""

    ordinal: int
    file_id: EntityId
    observation_id: EntityId
    relative_locator: str = field(repr=False)
    size_bytes: int
    sha256: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class EbookFixityPrivateBaselineEntryPage:
    manifest_id: EntityId
    entries: tuple[EbookFixityPrivateBaselineEntry, ...]
    next_after_ordinal: int | None


@dataclass(frozen=True, slots=True)
class EbookFixityPrivateResultMaterial:
    observation_id: EntityId | None
    relative_locator: str | None = field(repr=False)
    size_bytes: int | None
    sha256: str | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class EbookFixityPrivateResultDetail:
    result_id: EntityId
    run_id: EntityId
    file_id: EntityId
    result: str
    expected: EbookFixityPrivateResultMaterial
    current: EbookFixityPrivateResultMaterial
    failure_code: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class EbookFixityBaselineActivationCommand(ApplicationCommand):
    """Ephemeral exact activation input; adapters must never retain its plaintext."""

    manifest_id: EntityId
    confirmation: str = field(repr=False)

    def __post_init__(self) -> None:
        if not 1 <= len(self.confirmation) <= 256:
            raise ApplicationError("fixity baseline activation confirmation is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class EbookFixityExpectationRevisionCommand(ApplicationCommand):
    """A path-free, single-result expectation action; material is derived server-side."""

    result_id: EntityId
    action: str

    def __post_init__(self) -> None:
        if self.action not in {"ACCEPT_CURRENT", "RETIRE_MISSING"}:
            raise ApplicationError("fixity expectation action is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class EbookFixityReviewCommand(ApplicationCommand):
    """A path-free decision for one immutable Fixity result."""

    result_id: EntityId
    decision: str

    def __post_init__(self) -> None:
        if self.decision not in {"ACCEPT", "REJECT", "DEFER"}:
            raise ApplicationError("fixity review decision is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class EbookRenameProposalCommand(ApplicationCommand):
    observation_id: EntityId
    dependency_scope_id: EntityId
    target_basename: str


@dataclass(frozen=True, slots=True, kw_only=True)
class EbookRenameReviewCommand(ApplicationCommand):
    candidate_id: EntityId
    decision: str


@dataclass(frozen=True, slots=True, kw_only=True)
class EbookRenamePlanCommand(ApplicationCommand):
    candidate_id: EntityId


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplicationQuery:
    """Base contract for a read-only Application request."""

    context: ApplicationContext = field(default_factory=ApplicationContext)


@dataclass(frozen=True, slots=True)
class EbookRenamePreviewQuery(ApplicationQuery):
    candidate_id: EntityId


@dataclass(frozen=True, slots=True)
class MediaLineDescriptor:
    """One bounded product entry point without a transport-specific route."""

    media_line: MediaLine
    enabled: bool


@dataclass(frozen=True, slots=True)
class MediaLineRegistry:
    """Stable registry of active and future media lines."""

    profile: str
    entries: tuple[MediaLineDescriptor, ...]

    def __post_init__(self) -> None:
        if self.profile != APPLICATION_CONTRACTS_PROFILE:
            raise ApplicationError("Application registry profile is invalid")
        if tuple(entry.media_line for entry in self.entries) != tuple(MediaLine):
            raise ApplicationError("Application media-line registry is incomplete")
        if not self.entries[0].enabled or any(entry.enabled for entry in self.entries[1:]):
            raise ApplicationError("Application media-line activation is invalid")

    @classmethod
    def default(cls) -> MediaLineRegistry:
        return cls(
            profile=APPLICATION_CONTRACTS_PROFILE,
            entries=(
                MediaLineDescriptor(MediaLine.EBOOK, True),
                MediaLineDescriptor(MediaLine.MUSIC, False),
                MediaLineDescriptor(MediaLine.IMAGE, False),
            ),
        )


@dataclass(frozen=True, slots=True)
class EbookToolchainReadinessQuery(ApplicationQuery):
    """Read-only request for the existing E-Book toolchain Doctor."""

    ebook_meta_executable: str
    ebook_convert_executable: str
    calibre_debug_executable: str
    pdfinfo_executable: str
    pdftotext_executable: str
    java_executable: str
    epubcheck_jar: Path


@dataclass(frozen=True, slots=True)
class LibraryHealthQuery(ApplicationQuery):
    """Read-only request for one persisted Library Health projection."""

    snapshot_id: EntityId
    baseline_snapshot_id: EntityId | None = None
    sample_limit: int = DEFAULT_LIBRARY_HEALTH_DETAIL_LIMIT


@dataclass(frozen=True, slots=True)
class CollectionStateQuery(ApplicationQuery):
    """Read-only request for one immutable CollectionState snapshot."""

    snapshot_id: EntityId


@dataclass(frozen=True, slots=True)
class CollectionSearchQuery(ApplicationQuery):
    """Read-only, bounded search request for one CollectionState snapshot."""

    snapshot_id: EntityId
    spec: CollectionQuerySpec
    private_details: bool = False


@dataclass(frozen=True, slots=True)
class SurfacePageQuery(ApplicationQuery):
    """Bounded opaque-id page request for surface-owned read models."""

    after_id: str | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100:
            raise ApplicationError("Surface page limit is invalid")


@dataclass(frozen=True, slots=True)
class ApplicationJobDetailQuery(ApplicationQuery):
    """Read exactly one public ApplicationJob projection."""

    job_id: str


@dataclass(frozen=True, slots=True)
class EbookProjectionQuery(ApplicationQuery):
    """Read one bounded E-Book projection by its opaque persisted identifier."""

    projection_id: EntityId


@dataclass(frozen=True, slots=True)
class EbookFixityResultPageQuery(ApplicationQuery):
    run_id: EntityId
    after_id: EntityId | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100:
            raise ApplicationError("fixity result page limit is invalid")


@dataclass(frozen=True, slots=True)
class EbookFixityPrivateBaselineEntryPageQuery(ApplicationQuery):
    manifest_id: EntityId
    after_ordinal: int | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if self.after_ordinal is not None and self.after_ordinal < 0:
            raise ApplicationError("fixity baseline entry cursor is invalid")
        if not 1 <= self.limit <= 100:
            raise ApplicationError("fixity baseline entry page limit is invalid")


@dataclass(frozen=True, slots=True)
class EbookFixityPrivateResultDetailQuery(ApplicationQuery):
    result_id: EntityId
