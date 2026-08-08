"""Filesystem indexing, hashing, and incremental scan support."""

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
from foliotone.index.scanner import IncrementalScanner, ScanSummary
from foliotone.index.store import BatchOutcome, SQLiteIndexStore

__all__ = [
    "BatchOutcome",
    "DeletionConfirmationPolicy",
    "DiscoveredFile",
    "FingerprintWriter",
    "HashMode",
    "HashValues",
    "IncrementalScanner",
    "SQLiteIndexStore",
    "ScanRootBinding",
    "ScanSummary",
    "calculate_hashes",
    "discover_files",
    "quick_file_fingerprint",
    "stream_sha256",
]
