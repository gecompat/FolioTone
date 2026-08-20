import copy
import pickle
from dataclasses import replace
from pathlib import Path

import pytest

import foliotone.archive.quota_slots as quota_slots
from foliotone.archive.quota_slots import (
    ARCHIVE_BOUNDED_WORKSPACE_COMPATIBILITY,
    ARCHIVE_BOUNDED_WORKSPACE_PROFILE,
    MAX_ACTIVE_EXTRACTIONS,
    MAX_ARCHIVE_MEMBERS,
    MAX_SINGLE_FILE_BYTES,
    MAX_WORKSPACE_BYTES,
    MIN_HOST_RESERVE_BYTES,
    ArchiveWorkspaceError,
    ArchiveWorkspaceState,
    BoundedArchiveWorkspaceProvider,
    _ArchiveWorkspaceAttestation,
    _ArchiveWorkspaceCapability,
    _ArchiveWorkspaceLimits,
    _BackendWorkspaceLease,
)

_FINGERPRINT = "a" * 64


@pytest.fixture(autouse=True)
def _approve_only_the_contract_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        quota_slots,
        "_APPROVED_BACKEND_IDENTITIES",
        frozenset({("fake-provider", "archive-fake-workspace/v1")}),
    )


class _Handle:
    def __init__(self, private_value: str) -> None:
        self.private_value = private_value


class _FakeProvider(BoundedArchiveWorkspaceProvider):
    def __init__(self) -> None:
        super().__init__()
        self.available = ["slot-1", "slot-2"]
        self.generations = {"slot-1": 0, "slot-2": 0}
        self.quarantined: list[str] = []
        self.returned: list[str] = []
        self.fail_acquire = False
        self.fail_return = False
        self.override_attestation: _ArchiveWorkspaceAttestation | None = None
        self.return_mutation: dict[str, object] = {}

    def _acquire_backend_lease(
        self, limits: _ArchiveWorkspaceLimits
    ) -> _BackendWorkspaceLease | None:
        if self.fail_acquire:
            raise RuntimeError("C:/private/acquire")
        if not self.available:
            return None
        slot_id = self.available.pop(0)
        self.generations[slot_id] += 1
        generation = self.generations[slot_id]
        attestation = self.override_attestation or _ArchiveWorkspaceAttestation(
            profile=ARCHIVE_BOUNDED_WORKSPACE_PROFILE,
            compatibility=ARCHIVE_BOUNDED_WORKSPACE_COMPATIBILITY,
            provider_id="fake-provider",
            adapter_profile="archive-fake-workspace/v1",
            slot_id=slot_id,
            lease_id=f"lease-{slot_id}-{generation}",
            lease_generation=generation,
            attestation_fingerprint=_FINGERPRINT,
            limits=limits,
            state=ArchiveWorkspaceState.LEASED,
            empty=True,
            runtime_authorized=True,
        )
        return _BackendWorkspaceLease(
            attestation=attestation,
            input_root_handle=_Handle("C:/private/input"),
            output_root_handle=_Handle("C:/private/output"),
        )

    def _return_backend_lease(
        self, backend_lease: _BackendWorkspaceLease
    ) -> _ArchiveWorkspaceAttestation:
        if self.fail_return:
            raise RuntimeError("C:/private/return")
        self.returned.append(backend_lease.attestation.slot_id)
        return replace(
            backend_lease.attestation,
            state=ArchiveWorkspaceState.RETURNED,
            empty=True,
            **self.return_mutation,  # type: ignore[arg-type]
        )

    def _quarantine_backend_lease(self, backend_lease: _BackendWorkspaceLease) -> None:
        self.quarantined.append(backend_lease.attestation.slot_id)


def test_fixed_limits_and_profiles_are_exact() -> None:
    assert ARCHIVE_BOUNDED_WORKSPACE_PROFILE == "archive-bounded-workspace-capability/v1"
    assert (
        ARCHIVE_BOUNDED_WORKSPACE_COMPATIBILITY
        == "archive-bounded-workspace-compatibility/v1"
    )
    assert _ArchiveWorkspaceLimits() == _ArchiveWorkspaceLimits(
        max_workspace_bytes=MAX_WORKSPACE_BYTES,
        min_host_reserve_bytes=MIN_HOST_RESERVE_BYTES,
        max_single_file_bytes=MAX_SINGLE_FILE_BYTES,
        max_archive_members=MAX_ARCHIVE_MEMBERS,
        max_active_extractions=MAX_ACTIVE_EXTRACTIONS,
    )
    with pytest.raises(ValueError):
        _ArchiveWorkspaceLimits(max_workspace_bytes=MAX_WORKSPACE_BYTES + 1)
    with pytest.raises(ValueError):
        _ArchiveWorkspaceLimits(max_archive_members=True)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        _ArchiveWorkspaceAttestation(
            profile="archive-bounded-workspace-capability/v2",
            compatibility=ARCHIVE_BOUNDED_WORKSPACE_COMPATIBILITY,
            provider_id="fake-provider",
            adapter_profile="archive-fake-workspace/v1",
            slot_id="slot-x",
            lease_id="lease-x-1",
            lease_generation=1,
            attestation_fingerprint=_FINGERPRINT,
            limits=_ArchiveWorkspaceLimits(),
            state=ArchiveWorkspaceState.LEASED,
            empty=True,
            runtime_authorized=True,
        )


def test_lease_is_single_use_path_free_and_non_serializable() -> None:
    provider = _FakeProvider()
    capability = provider.lease()
    assert capability is not None
    assert capability.state is ArchiveWorkspaceState.LEASED
    assert capability.profile == ARCHIVE_BOUNDED_WORKSPACE_PROFILE
    assert capability.compatibility == ARCHIVE_BOUNDED_WORKSPACE_COMPATIBILITY
    assert capability.limits == provider.limits
    input_handle, output_handle = capability.borrow_roots()
    assert input_handle is not output_handle
    assert "C:/private" not in repr(capability)
    with pytest.raises(TypeError):
        copy.copy(capability)
    with pytest.raises(TypeError):
        copy.deepcopy(capability)
    with pytest.raises(TypeError):
        pickle.dumps(capability)

    provider.return_capability(capability)
    assert capability.state is ArchiveWorkspaceState.RETURNED
    assert provider.active_lease_count == 0
    with pytest.raises(ArchiveWorkspaceError):
        capability.borrow_roots()
    with pytest.raises(ArchiveWorkspaceError):
        provider.return_capability(capability)


def test_provider_never_exceeds_two_active_leases() -> None:
    provider = _FakeProvider()
    first = provider.lease()
    second = provider.lease()
    assert first is not None and second is not None
    assert provider.active_lease_count == 2
    assert provider.lease() is None


def test_return_failure_invalidates_and_quarantines() -> None:
    provider = _FakeProvider()
    capability = provider.lease()
    assert capability is not None
    provider.fail_return = True
    with pytest.raises(ArchiveWorkspaceError) as error:
        provider.return_capability(capability)
    assert "C:/private" not in str(error.value)
    assert capability.state is ArchiveWorkspaceState.QUARANTINED
    assert provider.active_lease_count == 0
    assert provider.quarantined == ["slot-1"]


def test_return_attestation_drift_invalidates_and_quarantines() -> None:
    provider = _FakeProvider()
    capability = provider.lease()
    assert capability is not None
    provider.return_mutation = {"attestation_fingerprint": "b" * 64}
    with pytest.raises(ArchiveWorkspaceError):
        provider.return_capability(capability)
    assert capability.state is ArchiveWorkspaceState.QUARANTINED
    assert provider.quarantined == ["slot-1"]


def test_explicit_quarantine_is_terminal() -> None:
    provider = _FakeProvider()
    capability = provider.lease()
    assert capability is not None
    provider.quarantine_capability(capability)
    assert capability.state is ArchiveWorkspaceState.QUARANTINED
    assert provider.quarantined == ["slot-1"]
    with pytest.raises(ArchiveWorkspaceError):
        capability.borrow_roots()


@pytest.mark.parametrize(
    "mutation",
    [
        {"state": ArchiveWorkspaceState.AVAILABLE},
        {"empty": False},
        {"runtime_authorized": False},
    ],
)
def test_invalid_backend_attestation_is_rejected_and_quarantined(
    mutation: dict[str, object],
) -> None:
    provider = _FakeProvider()
    base = _ArchiveWorkspaceAttestation(
        profile=ARCHIVE_BOUNDED_WORKSPACE_PROFILE,
        compatibility=ARCHIVE_BOUNDED_WORKSPACE_COMPATIBILITY,
        provider_id="fake-provider",
        adapter_profile="archive-fake-workspace/v1",
        slot_id="slot-x",
        lease_id="lease-x-1",
        lease_generation=1,
        attestation_fingerprint=_FINGERPRINT,
        limits=provider.limits,
        state=ArchiveWorkspaceState.LEASED,
        empty=True,
        runtime_authorized=True,
    )
    provider.override_attestation = replace(base, **mutation)  # type: ignore[arg-type]
    with pytest.raises((ArchiveWorkspaceError, TypeError, ValueError)):
        provider.lease()
    assert provider.active_lease_count == 0


def test_neutral_package_authorizes_no_real_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quota_slots, "_APPROVED_BACKEND_IDENTITIES", frozenset())
    provider = _FakeProvider()
    with pytest.raises(ArchiveWorkspaceError):
        provider.lease()
    assert provider.quarantined == ["slot-1"]


def test_foreign_capability_cannot_be_returned() -> None:
    first_provider = _FakeProvider()
    second_provider = _FakeProvider()
    capability = first_provider.lease()
    assert capability is not None
    with pytest.raises(ArchiveWorkspaceError):
        second_provider.return_capability(capability)
    assert capability.state is ArchiveWorkspaceState.LEASED


def test_replayed_slot_generation_is_rejected() -> None:
    provider = _FakeProvider()
    capability = provider.lease()
    assert capability is not None
    provider.return_capability(capability)
    provider.available.insert(0, "slot-1")
    provider.generations["slot-1"] = 0
    with pytest.raises(ArchiveWorkspaceError):
        provider.lease()
    assert provider.quarantined == ["slot-1"]


@pytest.mark.parametrize("handle", [None, "C:/private/root", b"private"])
def test_backend_handles_cannot_be_path_material(handle: object) -> None:
    attestation = _ArchiveWorkspaceAttestation(
        profile=ARCHIVE_BOUNDED_WORKSPACE_PROFILE,
        compatibility=ARCHIVE_BOUNDED_WORKSPACE_COMPATIBILITY,
        provider_id="fake-provider",
        adapter_profile="archive-fake-workspace/v1",
        slot_id="slot-x",
        lease_id="lease-x-1",
        lease_generation=1,
        attestation_fingerprint=_FINGERPRINT,
        limits=_ArchiveWorkspaceLimits(),
        state=ArchiveWorkspaceState.LEASED,
        empty=True,
        runtime_authorized=True,
    )
    with pytest.raises(ValueError):
        _BackendWorkspaceLease(attestation, handle, object())


def test_direct_capability_construction_is_closed() -> None:
    with pytest.raises(TypeError):
        _ArchiveWorkspaceCapability(  # type: ignore[call-arg]
            object(),
            object(),
            _factory_token=object(),
        )


def test_backend_exception_is_reduced_to_fixed_error() -> None:
    provider = _FakeProvider()
    provider.fail_acquire = True
    with pytest.raises(ArchiveWorkspaceError) as error:
        provider.lease()
    assert str(error.value) == "bounded archive workspace operation failed"


def test_contract_module_has_no_filesystem_or_process_authority() -> None:
    source = (
        Path(__file__).parents[2] / "src" / "foliotone" / "archive" / "quota_slots.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "import os",
        "import pathlib",
        "import subprocess",
        "import sqlite3",
        "mkfs",
        "losetup",
        "CAP_SYS_ADMIN",
    )
    assert not any(marker in source for marker in forbidden)
