from pytest import CaptureFixture

from foliotone import __version__
from foliotone.cli.main import main


def test_package_has_version() -> None:
    assert __version__


def test_status_command_is_non_destructive_bootstrap(
    capsys: CaptureFixture[str],
) -> None:
    result = main(["status"])

    assert result == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "FolioTone local-single-operator/v1 is implemented for the EBOOK product line.",
        (
            "The loopback-only browser surface and CLI are available; MUSIC and IMAGE "
            "remain inactive."
        ),
        "A read-only scan CLI is available for controlled smoke tests.",
        (
            "Read-only calibre metadata observations and versioned candidates are available "
            "through ebook-metadata."
        ),
        ("Read-only EPUB/MOBI/AZW/AZW3 text fingerprints are available through ebook-text."),
        (
            "Read-only embedded-cover facts and perceptual fingerprints are available "
            "through ebook-cover."
        ),
        ("Unified format-aware read-only e-book orchestration is available through ebook-analyze."),
        (
            "Versioned multi-dimensional e-book quality findings are available through "
            "ebook-analyze."
        ),
        (
            "Provider-neutral persisted e-book Evidence comparison is available through "
            "ebook-compare."
        ),
        (
            "Bounded resumable e-book collection analysis is available through "
            "ebook-collection-analyze."
        ),
        (
            "Deterministic private collection summaries and review sets are available "
            "through ebook-collection-report."
        ),
        (
            "Read-only resumable collection maintenance (analyze + optional hash/enhance "
            "reports) is available through ebook-collection-maintain."
        ),
        (
            "Quick duplicate candidates can be selectively confirmed with full SHA-256 "
            "through ebook-hash-candidates."
        ),
        (
            "Path-free candidate-hash leases and heartbeats can be inspected through "
            "ebook-hash-status."
        ),
        (
            "Scan-wide format, size, hash-coverage, and exact-duplicate reports are "
            "available through ebook-inventory-report."
        ),
        ("The bounded postscan lineage can be verified read-only through ebook-postscan-verify."),
        (
            "Persisted Calibre reconciliation snapshots can be inspected read-only through "
            "calibre-reconciliation-report."
        ),
        (
            "Immutable book-only collection snapshots can be built and inspected through "
            "collection-state-build and collection-state-report."
        ),
        (
            "Compatible snapshots can be compared and their bounded local metadata index "
            "searched through collection-state-diff and collection-search."
        ),
        (
            "Persisted non-executable metadata correction plans can be inspected read-only "
            "through ebook-metadata-correction-report."
        ),
        (
            "Persisted non-executable e-book operation recipes can be inspected read-only "
            "through ebook-operation-recipe-report."
        ),
        (
            "Bounded offline relation candidates and append-only matching review are "
            "available through ebook-match and ebook-match-review-* commands."
        ),
        "Read-only PDF metadata and text analysis is available through pdf-analyze.",
        "Read-only EPUB conformance evidence is available through epub-validate.",
        "Explicit e-book specialist readiness is available through ebook-tools-doctor.",
        (
            "The bounded reviewed EPUB title writer is available through "
            "metadata-write-authorize, metadata-write-execute, metadata-write-recover, "
            "and metadata-write-status."
        ),
        (
            "Bounded single-file quarantine authorization, execution, and recovery are "
            "available through quarantine-authorize, quarantine-execute, and "
            "quarantine-recover."
        ),
        (
            "Non-mutating same-parent e-book rename planning is available through "
            "ebook-rename-propose, ebook-rename-preview, ebook-rename-review, and "
            "ebook-rename-plan."
        ),
        (
            "The bounded same-parent e-book rename writer is available through "
            "ebook-rename-authorize, ebook-rename-execute, ebook-rename-recover, "
            "and ebook-rename-status."
        ),
        "Other source-media and external-tool mutation commands remain unavailable.",
    ]
