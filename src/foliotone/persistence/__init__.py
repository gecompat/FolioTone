"""Persistence implementations behind provider-independent core contracts."""

from foliotone.persistence.contracts import Repository
from foliotone.persistence.ebook_collection import (
    EBOOK_COLLECTION_PLAN_BATCH_SIZE,
    CreatedEbookCollectionRun,
    EbookCollectionCounts,
    EbookCollectionStoreError,
    EbookCollectionWorkItem,
    SQLiteEbookCollectionStore,
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
from foliotone.persistence.sqlite import (
    SQLiteRepository,
    alembic_config,
    create_sqlite_engine,
    migrate,
    repository,
    transaction,
)

__all__ = [
    "Repository",
    "MAX_EVIDENCE_QUERY_EXECUTIONS",
    "MAX_EVIDENCE_QUERY_FINGERPRINTS",
    "MAX_EVIDENCE_QUERY_OBSERVATIONS",
    "MAX_EVIDENCE_QUERY_RESULTS",
    "EvidenceQueryLimitError",
    "EBOOK_COLLECTION_PLAN_BATCH_SIZE",
    "CreatedEbookCollectionRun",
    "EbookCollectionCounts",
    "EbookCollectionStoreError",
    "EbookCollectionWorkItem",
    "ObservationEvidenceRecords",
    "SQLiteRepository",
    "SQLiteEbookCollectionStore",
    "alembic_config",
    "create_sqlite_engine",
    "migrate",
    "load_observation_evidence",
    "repository",
    "transaction",
]
