from __future__ import annotations

import hashlib
import inspect
from datetime import UTC, datetime

import pytest

from foliotone.core import EntityId
from foliotone.ebook_rename import linux_backend as backend_module
from foliotone.ebook_rename.capabilities import ResolvedEbookRenameCapability
from foliotone.ebook_rename.linux_backend import (
    EBOOK_RENAME_XATTR_FINGERPRINT_PROFILE,
    LinuxEbookRenameBackend,
    LinuxEbookRenameBackendError,
    LinuxEbookRenameBackendErrorCode,
    LinuxEbookRenamePhysicalSnapshot,
    LinuxEbookRenamePhysicalState,
    ebook_rename_xattr_fingerprint,
)


def test_non_linux_probe_fails_closed_without_touching_fixtures(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    probe = tmp_path / "probe"
    root.mkdir()
    probe.mkdir()
    capability = ResolvedEbookRenameCapability(
        ebook_rename_capability_id=EntityId.new(),
        scan_root_id=EntityId.new(),
        scan_root_directory=root,
        probe_directory=probe,
        version=1,
        configuration_fingerprint="a" * 64,
    )
    monkeypatch.setattr(backend_module.sys, "platform", "win32")

    with pytest.raises(LinuxEbookRenameBackendError, match="^TOOL_UNAVAILABLE$") as error:
        LinuxEbookRenameBackend().probe(
            capability,
            probed_at=datetime.now(UTC),
        )

    assert error.value.code is LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE
    assert list(root.iterdir()) == []
    assert list(probe.iterdir()) == []


def test_xattr_fingerprint_is_bounded_order_independent_and_profiled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {"user.z": b"last", "user.a": b"first"}
    monkeypatch.setattr(backend_module.os, "listxattr", lambda _fd: list(values), raising=False)
    monkeypatch.setattr(
        backend_module.os,
        "getxattr",
        lambda _fd, name: values[name],
        raising=False,
    )

    forward = ebook_rename_xattr_fingerprint(7)
    monkeypatch.setattr(
        backend_module.os,
        "listxattr",
        lambda _fd: list(reversed(values)),
        raising=False,
    )

    assert ebook_rename_xattr_fingerprint(7) == forward
    assert len(forward) == hashlib.sha256().digest_size * 2
    assert EBOOK_RENAME_XATTR_FINGERPRINT_PROFILE == "ebook-file-xattrs/v1"

    monkeypatch.setattr(
        backend_module.os,
        "listxattr",
        lambda _fd: [f"user.{index}" for index in range(33)],
        raising=False,
    )
    with pytest.raises(LinuxEbookRenameBackendError, match="^SOURCE_STALE$"):
        ebook_rename_xattr_fingerprint(7)


def test_backend_public_surface_exposes_no_flags_syscalls_or_commands() -> None:
    assert tuple(inspect.signature(LinuxEbookRenameBackend.probe).parameters) == (
        "self",
        "capability",
        "probed_at",
    )
    assert tuple(inspect.signature(LinuxEbookRenameBackend.open_session).parameters) == (
        "self",
        "capability",
        "probe",
        "preparation",
        "authorization",
        "binding",
        "run",
        "source_relative_locator",
        "target_relative_locator",
    )
    assert tuple(
        inspect.signature(
            LinuxEbookRenameBackend.capture_preparation_evidence
        ).parameters
    ) == (
        "self",
        "capability",
        "probe",
        "plan",
        "target_historically_absent",
        "captured_at",
    )


def test_physical_confirmation_hides_its_digest() -> None:
    snapshot = LinuxEbookRenamePhysicalSnapshot(
        state=LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT,
        confirmation_digest="f" * 64,
    )

    assert "f" * 64 not in repr(snapshot)
