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
        "FolioTone W2 foundation is complete; W3 e-book analysis is in progress.",
        "The initial product surface is CLI-only.",
        "A read-only scan CLI is available for controlled smoke tests.",
        (
            "Read-only calibre metadata observations and versioned candidates are available "
            "through ebook-metadata."
        ),
        (
            "Read-only EPUB/MOBI/AZW/AZW3 text fingerprints are available through "
            "ebook-text."
        ),
        (
            "Read-only embedded-cover facts and perceptual fingerprints are available "
            "through ebook-cover."
        ),
        (
            "Unified format-aware read-only e-book orchestration is available through "
            "ebook-analyze."
        ),
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
        "Read-only PDF metadata and text analysis is available through pdf-analyze.",
        "Read-only EPUB conformance evidence is available through epub-validate.",
        "Source-media and external-tool mutation commands are not implemented.",
    ]
