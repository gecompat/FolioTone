from foliotone import __version__
from foliotone.cli.main import main


def test_package_has_version() -> None:
    assert __version__


def test_status_command_is_non_destructive_bootstrap(capsys: object) -> None:
    result = main(["status"])
    assert result == 0
