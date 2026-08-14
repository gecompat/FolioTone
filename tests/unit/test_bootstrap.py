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
        "Read-only calibre metadata extraction is available through ebook-metadata.",
        "Read-only EPUB text fingerprints are available through ebook-text.",
        "Source-media and external-tool mutation commands are not implemented.",
    ]
