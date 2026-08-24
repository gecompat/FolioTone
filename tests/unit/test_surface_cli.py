from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from foliotone.surface import cli


def test_surface_api_migrates_before_opening_its_listener(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []
    database = tmp_path / "surface.sqlite"

    monkeypatch.setattr(cli, "migrate", lambda path: events.append(f"migrate:{path}"))
    monkeypatch.setattr(cli, "create_sqlite_engine", lambda path: events.append(f"engine:{path}"))
    monkeypatch.setattr(cli, "SQLiteSurfaceStore", lambda engine: engine)
    monkeypatch.setattr(cli, "LocalSurfaceService", lambda store: store)
    monkeypatch.setattr(cli, "SQLiteCollectionStateReportReader", lambda engine: engine)
    monkeypatch.setattr(cli, "SQLiteLibraryHealthReportReader", lambda engine: engine)
    monkeypatch.setattr(cli, "CollectionQueryService", lambda engine: engine)
    monkeypatch.setattr(cli, "SQLiteEbookSurfaceReadModel", lambda engine: engine)
    monkeypatch.setattr(cli, "create_surface_app", lambda *args, **kwargs: "app")
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: events.append(f"run:{app}"))

    assert cli.run_surface_api(Namespace(database=database, host="127.0.0.1", port=8765)) == 0
    assert events[:2] == [f"migrate:{database}", f"engine:{database}"]
    assert events[-1] == "run:app"
