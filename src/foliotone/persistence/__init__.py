"""Persistence implementations behind provider-independent core contracts."""

from typing import TYPE_CHECKING, Any

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


def __getattr__(name: str) -> Any:
    """Load consolidation persistence lazily to avoid workflow import cycles."""
    if name in {"ConsolidationStoreError", "SQLiteConsolidationStore"}:
        from foliotone.persistence.consolidation import (
            ConsolidationStoreError,
            SQLiteConsolidationStore,
        )

        return {
            "ConsolidationStoreError": ConsolidationStoreError,
            "SQLiteConsolidationStore": SQLiteConsolidationStore,
        }[name]
    raise AttributeError(name)

__all__ = [
    "Repository",
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
    "alembic_config",
    "create_sqlite_engine",
    "create_sqlite_read_only_engine",
    "migrate",
    "load_observation_evidence",
    "repository",
    "transaction",
]
