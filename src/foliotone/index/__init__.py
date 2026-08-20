"""Filesystem indexing, hashing, and incremental scan support."""

from foliotone.index.candidate_hashing import (
    DEFAULT_DUPLICATE_HASH_LEASE_DURATION,
    DUPLICATE_HASH_PROFILE,
    MAX_DUPLICATE_HASH_BATCH_SIZE,
    MAX_DUPLICATE_HASH_WORKERS,
    DuplicateHashCandidateError,
    DuplicateHashCandidateService,
    DuplicateHashCandidateSummary,
)
from foliotone.index.deletion import DeletionConfirmationPolicy
from foliotone.index.discovery import DiscoveredFile, ScanRootBinding, discover_files
from foliotone.index.hashing import (
    FingerprintWriter,
    HashMode,
    HashValues,
    calculate_hashes,
    quick_file_fingerprint,
    stream_sha256,
)
from foliotone.index.relocation import RelocationCandidateDetector
from foliotone.index.scanner import (
    MAX_SCAN_HASH_WORKERS,
    IncrementalScanner,
    ScanProgress,
    ScanProgressPhase,
    ScanSummary,
)
from foliotone.index.store import BatchOutcome, ScanLeaseError, SQLiteIndexStore

__all__ = [
    "BatchOutcome",
    "DeletionConfirmationPolicy",
    "DiscoveredFile",
    "DUPLICATE_HASH_PROFILE",
    "DEFAULT_DUPLICATE_HASH_LEASE_DURATION",
    "DuplicateHashCandidateError",
    "DuplicateHashCandidateService",
    "DuplicateHashCandidateSummary",
    "FingerprintWriter",
    "HashMode",
    "HashValues",
    "IncrementalScanner",
    "MAX_SCAN_HASH_WORKERS",
    "MAX_DUPLICATE_HASH_BATCH_SIZE",
    "MAX_DUPLICATE_HASH_WORKERS",
    "RelocationCandidateDetector",
    "SQLiteIndexStore",
    "ScanLeaseError",
    "ScanRootBinding",
    "ScanProgress",
    "ScanProgressPhase",
    "ScanSummary",
    "calculate_hashes",
    "discover_files",
    "quick_file_fingerprint",
    "stream_sha256",
]
