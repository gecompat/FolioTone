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

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "archive" / "7zip-26.02" / "v1"


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
