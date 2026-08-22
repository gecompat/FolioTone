"""Persistence implementations behind provider-independent core contracts."""

from typing import TYPE_CHECKING, Any

from foliotone.persistence.archive import (
    ArchiveEvidenceCompatibility,
    ArchiveEvidenceSnapshot,
    ArchiveEvidenceSource,
    ArchiveEvidenceStoreError,
    PersistedArchiveEvidence,
    SQLiteArchiveEvidenceStore,
)
from foliotone.persistence.archive_collection import (
    ARCHIVE_COLLECTION_PLAN_BATCH_SIZE,
    ArchiveCollectionPlanEntry,
    ArchiveCollectionStoreError,
    ArchiveCollectionWorkItem,
    SQLiteArchiveCollectionStore,
    archive_collection_plan_content_hash,
)
from foliotone.persistence.calibre_library import (
    CalibreLibraryStoreError,
    SQLiteCalibreLibraryStore,
)
from foliotone.persistence.calibre_library_report import (
    CALIBRE_RECONCILIATION_FINDING_CODES,
    CALIBRE_RECONCILIATION_REPORT_PROFILE,
    CalibreLibraryReportReaderError,
    CalibreReconciliationReport,
    CalibreReconciliationReportCounts,
    CalibreReconciliationReportSnapshot,
    SQLiteCalibreLibraryReportReader,
)
from foliotone.persistence.collection_query import (
    CollectionQueryHit,
    CollectionQueryIndexSummary,
    CollectionQueryPage,
    CollectionQueryPrivateValue,
    CollectionQueryStoreError,
    SQLiteCollectionQueryStore,
)
from foliotone.persistence.collection_state import (
    COLLECTION_STATE_KEYSET_BATCH_SIZE,
    CollectionStateBuildResult,
    CollectionStateStoreError,
    SQLiteCollectionStateStore,
)
from foliotone.persistence.collection_state_diff import (
    CollectionStateDiffStoreError,
    SQLiteCollectionStateDiffReader,
)
from foliotone.persistence.contracts import Repository
from foliotone.persistence.ebook_candidate_hash import (
    EbookCandidateHashLeaseError,
    SQLiteEbookCandidateHashRunStore,
)
from foliotone.persistence.ebook_collection import (
    EBOOK_COLLECTION_PLAN_BATCH_SIZE,
    CreatedEbookCollectionRun,
    EbookCollectionCounts,
    EbookCollectionExecutionSummary,
    EbookCollectionFindingSummary,
    EbookCollectionStoreError,
    EbookCollectionWorkItem,
    SQLiteEbookCollectionStore,
)
from foliotone.persistence.ebook_collection_report import (
    EBOOK_COLLECTION_REPORT_FETCH_SIZE,
    EbookCollectionCandidateGroup,
    EbookCollectionCandidateMember,
    EbookCollectionCandidateSet,
    EbookCollectionFindingAggregate,
    EbookCollectionReportSnapshot,
    EbookCollectionReportStoreError,
    EbookCollectionReviewFinding,
    EbookCollectionReviewItem,
    SQLiteEbookCollectionReportStore,
)
from foliotone.persistence.ebook_inventory_report import (
    EbookInventoryDuplicateGroup,
    EbookInventoryDuplicateMember,
    EbookInventoryDuplicateSet,
    EbookInventoryFormatAggregate,
    EbookInventoryReportSnapshot,
    EbookInventoryReportStoreError,
    SQLiteEbookInventoryReportStore,
)
from foliotone.persistence.evidence_queries import (
    MAX_EVIDENCE_QUERY_EXECUTIONS,
    MAX_EVIDENCE_QUERY_FINGERPRINTS,
    MAX_EVIDENCE_QUERY_OBSERVATIONS,
    MAX_EVIDENCE_QUERY_RESULTS,
    EvidenceQueryLimitError,
    ObservationEvidenceRecords,
    load_observation_evidence,
)
from foliotone.persistence.library_health import (
    LibraryHealthBuildResult,
    LibraryHealthStoreError,
    SQLiteLibraryHealthStore,
)
from foliotone.persistence.metadata_correction import (
    MAX_METADATA_CORRECTION_BLOCKERS,
    MAX_METADATA_CORRECTION_PRECONDITIONS,
    MetadataCorrectionStoreError,
    SQLiteMetadataCorrectionStore,
)
from foliotone.persistence.provider_cache_store import (
    ProviderCacheStoreCandidate,
    ProviderCacheStoreCapacityError,
    ProviderCacheStoreConflictError,
    ProviderCacheStoreEntry,
    ProviderCacheStoreError,
    ProviderCacheStorePort,
    SQLiteProviderCacheStore,
    canonical_provider_cache_content_bytes,
    canonical_provider_cache_content_payload,
    provider_cache_content_hash,
)
from foliotone.persistence.relation_candidates import (
    RelationCandidateStoreError,
    SQLiteRelationCandidateStore,
)
from foliotone.persistence.resolution_review import (
    MAX_RESOLUTION_EVIDENCE,
    MAX_RESOLUTION_PAGE,
    MAX_REVIEW_PAGE,
    ResolutionCandidatePage,
    ResolutionReviewStoreError,
    ReviewItemPage,
    SQLiteResolutionReviewStore,
)
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
    scan_root_write_scope,
)
from foliotone.persistence.sqlite import (
    SQLiteRepository,
    alembic_config,
    create_sqlite_engine,
    create_sqlite_read_only_engine,
    migrate,
    repository,
    transaction,
)

if TYPE_CHECKING:
    from foliotone.persistence.consolidation import (
        ConsolidationStoreError,
        SQLiteConsolidationStore,
    )
    from foliotone.persistence.metadata_write import (
        MetadataWriteStatusEventSnapshot,
        MetadataWriteStatusSnapshot,
        MetadataWriteStoreError,
        SQLiteMetadataWriteStore,
    )
    from foliotone.persistence.quarantine import (
        QuarantineExecutionEvent,
        QuarantineExecutionRun,
        QuarantineStoreError,
        SQLiteQuarantineStore,
    )


def __getattr__(name: str) -> Any:
    """Load cycle-prone persistence modules lazily."""
    if name in {"ConsolidationStoreError", "SQLiteConsolidationStore"}:
        from foliotone.persistence.consolidation import (
            ConsolidationStoreError,
            SQLiteConsolidationStore,
        )

        return {
            "ConsolidationStoreError": ConsolidationStoreError,
            "SQLiteConsolidationStore": SQLiteConsolidationStore,
        }[name]
    if name in {
        "QuarantineExecutionEvent",
        "QuarantineExecutionRun",
        "QuarantineStoreError",
        "SQLiteQuarantineStore",
    }:
        from foliotone.persistence import quarantine

        return getattr(quarantine, name)
    if name in {
        "MetadataWriteStatusEventSnapshot",
        "MetadataWriteStatusSnapshot",
        "MetadataWriteStoreError",
        "SQLiteMetadataWriteStore",
    }:
        from foliotone.persistence import metadata_write

        return getattr(metadata_write, name)
    raise AttributeError(name)


__all__ = [
    "Repository",
    "ArchiveEvidenceSnapshot",
    "ArchiveEvidenceCompatibility",
    "ArchiveEvidenceSource",
    "ArchiveEvidenceStoreError",
    "ARCHIVE_COLLECTION_PLAN_BATCH_SIZE",
    "ArchiveCollectionPlanEntry",
    "ArchiveCollectionStoreError",
    "ArchiveCollectionWorkItem",
    "PersistedArchiveEvidence",
    "SQLiteArchiveEvidenceStore",
    "SQLiteArchiveCollectionStore",
    "archive_collection_plan_content_hash",
    "CalibreLibraryStoreError",
    "ConsolidationStoreError",
    "CALIBRE_RECONCILIATION_FINDING_CODES",
    "CALIBRE_RECONCILIATION_REPORT_PROFILE",
    "CalibreLibraryReportReaderError",
    "CalibreReconciliationReport",
    "CalibreReconciliationReportCounts",
    "CalibreReconciliationReportSnapshot",
    "MAX_RESOLUTION_EVIDENCE",
    "MAX_RESOLUTION_PAGE",
    "MAX_REVIEW_PAGE",
    "MAX_EVIDENCE_QUERY_EXECUTIONS",
    "MAX_EVIDENCE_QUERY_FINGERPRINTS",
    "MAX_EVIDENCE_QUERY_OBSERVATIONS",
    "MAX_EVIDENCE_QUERY_RESULTS",
    "EvidenceQueryLimitError",
    "EBOOK_COLLECTION_PLAN_BATCH_SIZE",
    "CreatedEbookCollectionRun",
    "EbookCollectionCounts",
    "EbookCollectionExecutionSummary",
    "EbookCollectionFindingSummary",
    "EbookCollectionStoreError",
    "EbookCollectionWorkItem",
    "EbookCandidateHashLeaseError",
    "EbookInventoryDuplicateGroup",
    "EbookInventoryDuplicateMember",
    "EbookInventoryDuplicateSet",
    "EbookInventoryFormatAggregate",
    "EbookInventoryReportSnapshot",
    "EbookInventoryReportStoreError",
    "ProviderCacheStoreCapacityError",
    "ProviderCacheStoreCandidate",
    "ProviderCacheStoreConflictError",
    "ProviderCacheStoreEntry",
    "ProviderCacheStorePort",
    "ProviderCacheStoreError",
    "SQLiteProviderCacheStore",
    "canonical_provider_cache_content_bytes",
    "canonical_provider_cache_content_payload",
    "provider_cache_content_hash",
    "EBOOK_COLLECTION_REPORT_FETCH_SIZE",
    "EbookCollectionCandidateGroup",
    "EbookCollectionCandidateMember",
    "EbookCollectionCandidateSet",
    "EbookCollectionFindingAggregate",
    "EbookCollectionReportSnapshot",
    "EbookCollectionReportStoreError",
    "EbookCollectionReviewFinding",
    "EbookCollectionReviewItem",
    "ObservationEvidenceRecords",
    "SQLiteRepository",
    "SQLiteEbookCollectionStore",
    "SQLiteCalibreLibraryStore",
    "SQLiteConsolidationStore",
    "SQLiteCalibreLibraryReportReader",
    "COLLECTION_STATE_KEYSET_BATCH_SIZE",
    "CollectionStateBuildResult",
    "CollectionStateStoreError",
    "SQLiteCollectionStateStore",
    "CollectionQueryHit",
    "CollectionQueryIndexSummary",
    "CollectionQueryPage",
    "CollectionQueryPrivateValue",
    "CollectionQueryStoreError",
    "SQLiteCollectionQueryStore",
    "CollectionStateDiffStoreError",
    "SQLiteCollectionStateDiffReader",
    "LibraryHealthBuildResult",
    "LibraryHealthStoreError",
    "SQLiteLibraryHealthStore",
    "MAX_METADATA_CORRECTION_BLOCKERS",
    "MAX_METADATA_CORRECTION_PRECONDITIONS",
    "MetadataCorrectionStoreError",
    "SQLiteMetadataCorrectionStore",
    "MetadataWriteStatusEventSnapshot",
    "MetadataWriteStatusSnapshot",
    "MetadataWriteStoreError",
    "SQLiteMetadataWriteStore",
    "SQLiteEbookCandidateHashRunStore",
    "SQLiteEbookInventoryReportStore",
    "SQLiteEbookCollectionReportStore",
    "OwnedScanRootWriteLease",
    "ScanRootWriteLeaseError",
    "ScanRootWriteOwnerKind",
    "ResolutionCandidatePage",
    "ResolutionReviewStoreError",
    "RelationCandidateStoreError",
    "ReviewItemPage",
    "SQLiteResolutionReviewStore",
    "SQLiteRelationCandidateStore",
    "SQLiteScanRootWriteLeaseStore",
    "scan_root_write_scope",
    "QuarantineExecutionEvent",
    "QuarantineExecutionRun",
    "QuarantineStoreError",
    "SQLiteQuarantineStore",
    "alembic_config",
    "create_sqlite_engine",
    "create_sqlite_read_only_engine",
    "migrate",
    "load_observation_evidence",
    "repository",
    "transaction",
]
