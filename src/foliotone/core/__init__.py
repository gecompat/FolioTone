"""Shared domain models and core contracts."""

from foliotone.core.authority_models import Agent, AgentName, Contribution, ExternalIdentifier
from foliotone.core.candidate_hash_models import EbookCandidateHashRun
from foliotone.core.collection_models import (
    EBOOK_COLLECTION_FORMATS,
    MAX_EBOOK_COLLECTION_WORKERS,
    EbookCollectionItem,
    EbookCollectionRun,
)
from foliotone.core.common import Provenance, ValueAssertion
from foliotone.core.ebook_models import Edition, Series, SeriesMembership, Work
from foliotone.core.enums import (
    AgentNameType,
    AgentType,
    EbookCandidateHashPhase,
    EbookCandidateHashRunStatus,
    EbookCollectionItemStatus,
    EbookCollectionRunStatus,
    EntityKind,
    FileChangeState,
    MatchStatus,
    MediaType,
    MusicWorkRelationType,
    PresenceState,
    RelationType,
    ScanRunStatus,
    ToolCapability,
    ToolExecutionStatus,
    ValueState,
)
from foliotone.core.evidence_models import ClassificationAssertion, Evidence, Fingerprint, Relation
from foliotone.core.ids import EntityId
from foliotone.core.index_models import FileObservation, FileRecord, ScanRoot, ScanRun
from foliotone.core.music_models import (
    CatalogDesignation,
    MusicWork,
    MusicWorkRelation,
    Recording,
    Release,
    ReleaseGroup,
    ReleaseRecording,
)
from foliotone.core.relocation_models import FileRelocationCandidate, RelocationCandidateKind
from foliotone.core.scan_events import FileScanEvent

__all__ = [
    "Agent",
    "AgentName",
    "AgentNameType",
    "AgentType",
    "CatalogDesignation",
    "ClassificationAssertion",
    "Contribution",
    "Edition",
    "EBOOK_COLLECTION_FORMATS",
    "MAX_EBOOK_COLLECTION_WORKERS",
    "EbookCollectionItem",
    "EbookCollectionItemStatus",
    "EbookCollectionRun",
    "EbookCollectionRunStatus",
    "EbookCandidateHashPhase",
    "EbookCandidateHashRun",
    "EbookCandidateHashRunStatus",
    "EntityId",
    "EntityKind",
    "Evidence",
    "ExternalIdentifier",
    "FileChangeState",
    "FileObservation",
    "FileRecord",
    "FileRelocationCandidate",
    "FileScanEvent",
    "Fingerprint",
    "MatchStatus",
    "MediaType",
    "MusicWork",
    "MusicWorkRelation",
    "MusicWorkRelationType",
    "PresenceState",
    "Provenance",
    "Recording",
    "Relation",
    "RelationType",
    "Release",
    "ReleaseGroup",
    "ReleaseRecording",
    "RelocationCandidateKind",
    "ScanRoot",
    "ScanRun",
    "ScanRunStatus",
    "Series",
    "SeriesMembership",
    "ToolCapability",
    "ToolExecutionStatus",
    "ValueAssertion",
    "ValueState",
    "Work",
]
