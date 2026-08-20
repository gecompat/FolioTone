"""ADR-0044 fixture and value-free measurement contract."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "archive" / "7zip-26.02" / "v1"
FIXTURES_V2 = ROOT / "tests" / "fixtures" / "archive" / "7zip-26.02" / "v2"


def _load_measurement_module() -> ModuleType:
    script = ROOT / "packaging" / "archive" / "7zip-26.02" / "measure_format_profiles.py"
    spec = importlib.util.spec_from_file_location("archive_format_measurement", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_archive_format_measurement_fixtures_are_raw_hash_bound_and_value_free() -> None:
    expected = (
        (
            "rar-test-files/build/testfile.rar3.rar",
            "dce342bc0c2852fcaa36a03da5e55abb7dd69c045bbd812faebebc1a3844f5a4",
        ),
        (
            "rar-test-files/build/testfile.rar5.rar",
            "a546b39c1aa42669543ef81f5ec8c4ef49fc7c2e5b8d08ab10549e919996e1a4",
        ),
        (
            "rar-test-files/LICENSE.cc0",
            "7179683e8000e6bdc9bbc60d85edf0a4ac8e76f951857f54fcb775d5886f1309",
        ),
        (
            "rar-test-files/LICENSE.md",
            "64d97b29bc28614947511c5cf1872962a274945903ef2984acdbf455e281ceb1",
        ),
        (
            "rar-test-files/README.md",
            "9dd19d40540bbcfce35ca76001e44eeaf003ed66bebe02006841096929e9dd89",
        ),
    )
    for relative, digest in expected:
        assert hashlib.sha256((FIXTURES / relative).read_bytes()).hexdigest() == digest

    module = _load_measurement_module()
    projected = module.project_stream(
        io.BytesIO(
            b"Path = private-name\nFolder = -\nSize = 12\nCRC = ABCD1234\nComment = hidden\n\n"
        ),
        {
            "id": "zip",
            "sha256": "a" * 64,
            "format_kind": "ZIP",
            "record_role": "DIRECT_MEMBER",
            "min_records": 1,
        },
    )
    assert projected == [
        {
            "fixture_id": "zip",
            "fixture_sha256": "a" * 64,
            "format_kind": "ZIP",
            "record_role": "DIRECT_MEMBER",
            "exit_code": 0,
            "record_ordinal": 1,
            "fields": [
                {"name": "Path", "value_class": "PRIVATE_LOCATOR_DISCARDED"},
                {"name": "Folder", "value_class": "BOOL_MINUS"},
                {"name": "Size", "value_class": "CANONICAL_UINT"},
                {"name": "CRC", "value_class": "CRC32"},
                {"name": "Comment", "value_class": "PRIVATE_NONEMPTY_DISCARDED"},
            ],
        }
    ]
    assert b"private-name" not in module._canonical({"records": projected})
    legacy_empty_bool = module.project_stream(
        io.BytesIO(b"Path = private-name\nAlternate Stream = \n\n"),
        {
            "id": "zip",
            "sha256": "a" * 64,
            "format_kind": "ZIP",
            "record_role": "DIRECT_MEMBER",
            "min_records": 1,
        },
    )
    assert legacy_empty_bool[0]["fields"][1] == {
        "name": "Alternate Stream",
        "value_class": "EMPTY",
    }
    argv = module.docker_argv("sha256:" + "a" * 64, FIXTURES, "direct/zip.zip")
    assert "--pull=never" in argv and "--network=none" in argv and "--read-only" in argv
    assert "--cap-drop" in argv and "no-new-privileges" in argv
    assert argv[-2:] == ["--", "/fixtures/direct/zip.zip"]
    assert "@sha256:" not in argv
    mount = argv[argv.index("--mount") + 1]
    assert mount.startswith(f"type=bind,src={FIXTURES.resolve()},")
    assert mount.endswith(",dst=/fixtures,readonly")
    expected = FIXTURES / "expected-measurement.json"
    assert hashlib.sha256(expected.read_bytes()).hexdigest() == (
        "40a6ee8843390cee75712461495c0173d47247696800976c21cc7134ffd3b89e"
    )


def test_archive_format_measurement_uses_the_loaded_config_digest() -> None:
    module = _load_measurement_module()
    lock = module._lock()
    detail = {
        "Id": lock["runtime_config_digest"],
        "Architecture": "amd64",
        "Os": "linux",
        "Config": {
            "User": lock["image_user"],
            "Entrypoint": ["/usr/local/bin/7zzs"],
            "WorkingDir": "/workspace",
            "Env": ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"],
            "Labels": {"org.opencontainers.image.source": "https://github.com/gecompat/FolioTone"},
        },
        "RootFS": {
            "Layers": [lock["runtime_rootfs_diff_id"], lock["runtime_workdir_diff_id"]]
        },
    }
    completed = subprocess.CompletedProcess(
        args=["docker", "image", "inspect"],
        returncode=0,
        stdout=json.dumps([detail]).encode("ascii"),
        stderr=b"",
    )
    with patch.object(module.subprocess, "run", return_value=completed):
        module._verify_image(lock["runtime_config_digest"], lock)
        try:
            module._verify_image(lock["runtime_platform_manifest_digest"], lock)
        except module.MeasurementError as error:
            assert str(error) == "IMAGE_REFERENCE_REJECTED"
        else:
            raise AssertionError("platform manifest digest must not be used as a local image ID")


def test_archive_format_measurement_v2_is_closed_and_value_free() -> None:
    module = _load_measurement_module()
    fixtures = module.load_fixture_manifest(FIXTURES_V2)
    assert len(fixtures) == 18

    manifest = json.loads((FIXTURES_V2 / "fixture-manifest.json").read_bytes())
    assert len(manifest["matrix"]) == 40
    assert {
        (item["format_kind"], item["case_kind"])
        for item in manifest["matrix"]
    } == {
        (format_kind, case_kind)
        for format_kind in module.DIRECT_FORMATS
        for case_kind in module.CASE_KINDS
    }
    expected = (FIXTURES_V2 / "expected-measurement.json").read_bytes()
    assert hashlib.sha256(expected).hexdigest() == (
        "da01ed9108a5ea63097cd1894aa4fbb264f658d65a833e8db3cb526180f2d266"
    )
    measurement = json.loads(expected)
    assert measurement["profile"] == module.PROFILE_V2
    assert len(measurement["records"]) == 21
    assert measurement["fixture_manifest_sha256"] == module.FIXTURE_MANIFEST_V2_SHA256
    assert measurement["deterministic_provenance_sha256"] == (
        module.DETERMINISTIC_PROVENANCE_SHA256
    )
    assert measurement["curation_provenance_sha256"] == (
        module.CURATION_PROVENANCE_SHA256
    )
    assert measurement["matrix_sha256"] == (
        "c2f3e8e3ff7c5244d71e9a7b2f97a6fea3bc120e6f179a080820024a6c8c6f99"
    )
    for forbidden in (
        b"PUBLIC-FIXTURE-NOT-A-SECRET-v2",
        b"clear.txt",
        b"encrypted.txt",
        b"/work/",
        b"/tmp/",
    ):
        assert forbidden not in expected


def test_archive_format_measurement_v2_classifies_material_fields_strictly() -> None:
    module = _load_measurement_module()
    for field in ("Commented", "Split Before", "Split After"):
        assert module._classify(field, "+") == "BOOL_PLUS"
        assert module._classify(field, "-") == "BOOL_MINUS"
        with pytest.raises(module.MeasurementError, match="BOOL_VALUE_REJECTED"):
            module._classify(field, "")
    assert module._classify("Copy Link", "private-target") == (
        "PRIVATE_NONEMPTY_DISCARDED"
    )


def test_archive_format_measurement_v2_workflow_is_verify_only() -> None:
    workflow = (ROOT / ".github" / "workflows" / "archive-image.yml").read_text(
        encoding="utf-8"
    )
    assert workflow.count("--fixtures tests/fixtures/archive/7zip-26.02/v2") == 2
    assert "archive-7zip-format-measurement-v2-a.json" in workflow
    assert "archive-7zip-format-measurement-v2-b.json" in workflow
    assert "tests/fixtures/archive/7zip-26.02/v2/expected-measurement.json" in workflow
    assert "PUBLIC-FIXTURE-NOT-A-SECRET-v2" not in workflow
