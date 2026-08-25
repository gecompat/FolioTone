from argparse import Namespace
from pathlib import Path

import pytest

import foliotone.surface.cli as surface_cli


def _arguments(tmp_path: Path, *, container: bool) -> Namespace:
    return Namespace(
        database=tmp_path / "surface.sqlite",
        host="127.0.0.1",
        port=8765,
        container_loopback_publish=container,
    )


def test_container_listener_is_rejected_outside_a_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(surface_cli, "_container_runtime_detected", lambda: False)

    assert surface_cli.run_surface_api(_arguments(tmp_path, container=True)) == 2
    assert "requires an IPv4 Docker or Podman container" in capsys.readouterr().err
    assert not (tmp_path / "surface.sqlite").exists()


def test_container_listener_keeps_public_origin_on_loopback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(surface_cli, "_container_runtime_detected", lambda: True)
    monkeypatch.setattr(surface_cli, "migrate", lambda _database: None)
    monkeypatch.setattr(surface_cli, "create_sqlite_engine", lambda _database: object())
    monkeypatch.setattr(surface_cli, "SQLiteSurfaceStore", lambda _engine: object())
    monkeypatch.setattr(surface_cli, "LocalSurfaceService", lambda _store: object())
    monkeypatch.setattr(surface_cli, "SQLiteCollectionStateReportReader", lambda _engine: object())
    monkeypatch.setattr(surface_cli, "SQLiteLibraryHealthReportReader", lambda _engine: object())
    monkeypatch.setattr(surface_cli, "CollectionQueryService", lambda _engine: object())
    monkeypatch.setattr(surface_cli, "SQLiteEbookSurfaceReadModel", lambda _engine: object())
    monkeypatch.setattr(surface_cli, "EbookRenamePlanningService", lambda *_args: object())
    monkeypatch.setattr(surface_cli, "EbookRenameDependencyScopeResolver", lambda: object())

    def fake_app(_service: object, **values: object) -> object:
        captured["config"] = values["config"]
        return object()

    def fake_run(_app: object, **values: object) -> None:
        captured.update(values)

    monkeypatch.setattr(surface_cli, "create_surface_app", fake_app)
    monkeypatch.setattr(surface_cli.uvicorn, "run", fake_run)

    assert surface_cli.run_surface_api(_arguments(tmp_path, container=True)) == 0
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8765
    assert captured["proxy_headers"] is False
    assert captured["config"].origin == "http://127.0.0.1:8765"  # type: ignore[union-attr]


def test_surface_api_migrates_before_opening_its_listener(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    database = tmp_path / "surface.sqlite"

    monkeypatch.setattr(
        surface_cli, "migrate", lambda path: events.append(f"migrate:{path}")
    )
    monkeypatch.setattr(
        surface_cli, "create_sqlite_engine", lambda path: events.append(f"engine:{path}")
    )
    monkeypatch.setattr(surface_cli, "SQLiteSurfaceStore", lambda engine: engine)
    monkeypatch.setattr(surface_cli, "LocalSurfaceService", lambda store: store)
    monkeypatch.setattr(
        surface_cli, "SQLiteCollectionStateReportReader", lambda engine: engine
    )
    monkeypatch.setattr(
        surface_cli, "SQLiteLibraryHealthReportReader", lambda engine: engine
    )
    monkeypatch.setattr(surface_cli, "CollectionQueryService", lambda engine: engine)
    monkeypatch.setattr(surface_cli, "SQLiteEbookSurfaceReadModel", lambda engine: engine)
    monkeypatch.setattr(surface_cli, "EbookRenamePlanningService", lambda *_args: object())
    monkeypatch.setattr(
        surface_cli, "EbookRenameDependencyScopeResolver", lambda: object()
    )
    monkeypatch.setattr(surface_cli, "create_surface_app", lambda *args, **kwargs: "app")
    monkeypatch.setattr(
        surface_cli.uvicorn,
        "run",
        lambda app, **kwargs: events.append(f"run:{app}"),
    )

    assert surface_cli.run_surface_api(_arguments(tmp_path, container=False)) == 0
    assert events[:2] == [f"migrate:{database}", f"engine:{database}"]
    assert events[-1] == "run:app"
