"""Shared pytest fixtures for isolated SQLite integration databases."""

from collections.abc import Callable, Iterator
from hashlib import sha256
from pathlib import Path
from shutil import copyfile

import pytest

from foliotone.persistence import migrate

HeadDatabaseFactory = Callable[[str], Path]


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@pytest.fixture(scope="session")
def _head_database_template(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Create the current migrated schema once and prove the template stays immutable."""

    template = tmp_path_factory.mktemp("foliotone-head-schema") / "foliotone.db"
    migrate(template)
    expected_digest = _file_sha256(template)
    yield template
    assert _file_sha256(template) == expected_digest, "head database template was modified"


@pytest.fixture
def head_database_factory(
    tmp_path: Path,
    _head_database_template: Path,
) -> HeadDatabaseFactory:
    """Return a factory producing isolated copies of the migrated head database."""

    def create(name: str = "foliotone.db") -> Path:
        if not name or "/" in name or "\\" in name or Path(name).name != name:
            raise ValueError("database copy name must be one non-empty filename")
        target = tmp_path / name
        if target.exists():
            raise FileExistsError("database copy target already exists")
        copyfile(_head_database_template, target)
        return target

    return create


@pytest.fixture
def head_database(head_database_factory: HeadDatabaseFactory) -> Path:
    """Provide one isolated current-schema database for a test."""

    return head_database_factory("foliotone.db")
