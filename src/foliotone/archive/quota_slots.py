"""Filesystem-neutral bounded workspace capability contracts.

The module is intentionally not exported from :mod:`foliotone.archive`.
It cannot mount, format, provision, or select a real backend. A later
platform package must supply the backend hooks and pass its own conformance
gate before archive extraction can use this coordinator.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Lock
from typing import Final

ARCHIVE_BOUNDED_WORKSPACE_PROFILE: Final = "archive-bounded-workspace-capability/v1"
ARCHIVE_BOUNDED_WORKSPACE_COMPATIBILITY: Final = (
    "archive-bounded-workspace-compatibility/v1"
)
MAX_WORKSPACE_BYTES: Final = 8_589_934_592
MIN_HOST_RESERVE_BYTES: Final = 1_073_741_824
MAX_SINGLE_FILE_BYTES: Final = 2_147_483_648
MAX_ARCHIVE_MEMBERS: Final = 10_000
MAX_ACTIVE_EXTRACTIONS: Final = 2

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_OPAQUE_CODEPOINTS: Final = 128
_CAPABILITY_FACTORY_TOKEN: Final = object()
_APPROVED_BACKEND_IDENTITIES: Final[frozenset[tuple[str, str]]] = frozenset()


class ArchiveWorkspaceState(StrEnum):
    AVAILABLE = "AVAILABLE"
    LEASED = "LEASED"
    RETURNED = "RETURNED"
    QUARANTINED = "QUARANTINED"
    UNAVAILABLE = "UNAVAILABLE"


class ArchiveWorkspaceError(RuntimeError):
    """A deliberately detail-free workspace lifecycle failure."""

    def __init__(self) -> None:
        super().__init__("bounded archive workspace operation failed")


@dataclass(frozen=True, slots=True)
class _ArchiveWorkspaceLimits:
    max_workspace_bytes: int = MAX_WORKSPACE_BYTES
    min_host_reserve_bytes: int = MIN_HOST_RESERVE_BYTES
    max_single_file_bytes: int = MAX_SINGLE_FILE_BYTES
    max_archive_members: int = MAX_ARCHIVE_MEMBERS
    max_active_extractions: int = MAX_ACTIVE_EXTRACTIONS

    def __post_init__(self) -> None:
        expected = (
            MAX_WORKSPACE_BYTES,
            MIN_HOST_RESERVE_BYTES,
            MAX_SINGLE_FILE_BYTES,
            MAX_ARCHIVE_MEMBERS,
            MAX_ACTIVE_EXTRACTIONS,
        )
        actual = (
            self.max_workspace_bytes,
            self.min_host_reserve_bytes,
            self.max_single_file_bytes,
            self.max_archive_members,
            self.max_active_extractions,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in actual):
            raise ValueError("archive workspace limits are invalid")
        if actual != expected:
            raise ValueError("archive workspace limits are invalid")


@dataclass(frozen=True, slots=True)
class _ArchiveWorkspaceAttestation:
    profile: str
    compatibility: str
    provider_id: str
    adapter_profile: str
    slot_id: str
    lease_id: str
    lease_generation: int
    attestation_fingerprint: str = field(repr=False)
    limits: _ArchiveWorkspaceLimits
    state: ArchiveWorkspaceState
    empty: bool
    runtime_authorized: bool

    def __post_init__(self) -> None:
        if (
            self.profile != ARCHIVE_BOUNDED_WORKSPACE_PROFILE
            or self.compatibility != ARCHIVE_BOUNDED_WORKSPACE_COMPATIBILITY
        ):
            raise ValueError("archive workspace attestation is invalid")
        _require_opaque("provider_id", self.provider_id)
        _require_profile("adapter_profile", self.adapter_profile)
        _require_opaque("slot_id", self.slot_id)
        _require_opaque("lease_id", self.lease_id)
        if (
            isinstance(self.lease_generation, bool)
            or not isinstance(self.lease_generation, int)
            or self.lease_generation < 1
        ):
            raise ValueError("archive workspace attestation is invalid")
        if not isinstance(self.attestation_fingerprint, str) or not _SHA256.fullmatch(
            self.attestation_fingerprint
        ):
            raise ValueError("archive workspace attestation is invalid")
        if not isinstance(self.limits, _ArchiveWorkspaceLimits):
            raise ValueError("archive workspace attestation is invalid")
        if not isinstance(self.state, ArchiveWorkspaceState):
            raise ValueError("archive workspace attestation is invalid")
        if not isinstance(self.empty, bool) or not isinstance(self.runtime_authorized, bool):
            raise ValueError("archive workspace attestation is invalid")


@dataclass(frozen=True, slots=True)
class _BackendWorkspaceLease:
    attestation: _ArchiveWorkspaceAttestation
    input_root_handle: object = field(repr=False)
    output_root_handle: object = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.attestation, _ArchiveWorkspaceAttestation):
            raise ValueError("archive workspace lease is invalid")
        if (
            self.input_root_handle is None
            or self.output_root_handle is None
            or isinstance(self.input_root_handle, (str, bytes))
            or isinstance(self.output_root_handle, (str, bytes))
            or self.input_root_handle is self.output_root_handle
            or (
                isinstance(self.input_root_handle, int)
                and isinstance(self.output_root_handle, int)
                and self.input_root_handle == self.output_root_handle
            )
        ):
            raise ValueError("archive workspace lease is invalid")


class _ArchiveWorkspaceCapability:
    """Single-use, non-serializable access to two opaque backend handles."""

    __slots__ = ("__backend_lease", "__coordinator_token", "__state")

    def __init__(
        self,
        backend_lease: _BackendWorkspaceLease,
        coordinator_token: object,
        *,
        _factory_token: object,
    ) -> None:
        if _factory_token is not _CAPABILITY_FACTORY_TOKEN:
            raise TypeError("archive workspace capability cannot be constructed directly")
        self.__backend_lease = backend_lease
        self.__coordinator_token = coordinator_token
        self.__state = ArchiveWorkspaceState.LEASED

    @property
    def provider_id(self) -> str:
        return self.__backend_lease.attestation.provider_id

    @property
    def profile(self) -> str:
        return self.__backend_lease.attestation.profile

    @property
    def compatibility(self) -> str:
        return self.__backend_lease.attestation.compatibility

    @property
    def adapter_profile(self) -> str:
        return self.__backend_lease.attestation.adapter_profile

    @property
    def lease_id(self) -> str:
        return self.__backend_lease.attestation.lease_id

    @property
    def lease_generation(self) -> int:
        return self.__backend_lease.attestation.lease_generation

    @property
    def limits(self) -> _ArchiveWorkspaceLimits:
        return self.__backend_lease.attestation.limits

    @property
    def state(self) -> ArchiveWorkspaceState:
        return self.__state

    def borrow_roots(self) -> tuple[object, object]:
        if self.__state is not ArchiveWorkspaceState.LEASED:
            raise ArchiveWorkspaceError()
        return (
            self.__backend_lease.input_root_handle,
            self.__backend_lease.output_root_handle,
        )

    def __repr__(self) -> str:
        return (
            "_ArchiveWorkspaceCapability("
            f"profile={self.profile!r}, compatibility={self.compatibility!r}, "
            f"provider_id={self.provider_id!r}, adapter_profile={self.adapter_profile!r}, "
            f"lease_id={self.lease_id!r}, lease_generation={self.lease_generation!r}, "
            f"state={self.state.value!r})"
        )

    def __copy__(self) -> None:
        raise TypeError("archive workspace capability cannot be copied")

    def __deepcopy__(self, memo: object) -> None:
        del memo
        raise TypeError("archive workspace capability cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("archive workspace capability cannot be serialized")

    def _belongs_to(self, coordinator_token: object) -> bool:
        return self.__coordinator_token is coordinator_token

    def _backend_material(self, coordinator_token: object) -> _BackendWorkspaceLease:
        if not self._belongs_to(coordinator_token):
            raise ArchiveWorkspaceError()
        return self.__backend_lease

    def _invalidate(self, coordinator_token: object, state: ArchiveWorkspaceState) -> None:
        if (
            not self._belongs_to(coordinator_token)
            or self.__state is not ArchiveWorkspaceState.LEASED
        ):
            raise ArchiveWorkspaceError()
        if state not in {ArchiveWorkspaceState.RETURNED, ArchiveWorkspaceState.QUARANTINED}:
            raise ArchiveWorkspaceError()
        self.__state = state

    def _quarantine_after_failed_return(self, coordinator_token: object) -> None:
        if (
            not self._belongs_to(coordinator_token)
            or self.__state is not ArchiveWorkspaceState.RETURNED
        ):
            raise ArchiveWorkspaceError()
        self.__state = ArchiveWorkspaceState.QUARANTINED


class BoundedArchiveWorkspaceProvider(ABC):
    """Neutral coordinator; platform subclasses own all backend authority."""

    def __init__(self) -> None:
        self.__lock = Lock()
        self.__coordinator_token = object()
        self.__active: dict[str, _ArchiveWorkspaceCapability] = {}
        self.__limits = _ArchiveWorkspaceLimits()
        self.__backend_identity: tuple[str, str] | None = None
        self.__highest_generation_by_slot: dict[str, int] = {}

    @property
    def limits(self) -> _ArchiveWorkspaceLimits:
        return self.__limits

    @property
    def active_lease_count(self) -> int:
        with self.__lock:
            return len(self.__active)

    def lease(self) -> _ArchiveWorkspaceCapability | None:
        with self.__lock:
            if len(self.__active) >= MAX_ACTIVE_EXTRACTIONS:
                return None
            try:
                backend_lease = self._acquire_backend_lease(self.__limits)
            except Exception as error:
                raise ArchiveWorkspaceError() from error
            if backend_lease is None:
                return None
            try:
                self.__validate_leased(backend_lease)
                self.__validate_identity_and_generation(backend_lease.attestation)
            except (TypeError, ValueError, ArchiveWorkspaceError) as error:
                self.__quarantine_best_effort(backend_lease)
                raise ArchiveWorkspaceError() from error
            lease_id = backend_lease.attestation.lease_id
            if lease_id in self.__active:
                self.__quarantine_best_effort(backend_lease)
                raise ArchiveWorkspaceError()
            capability = _ArchiveWorkspaceCapability(
                backend_lease,
                self.__coordinator_token,
                _factory_token=_CAPABILITY_FACTORY_TOKEN,
            )
            self.__active[lease_id] = capability
            attestation = backend_lease.attestation
            self.__backend_identity = (attestation.provider_id, attestation.adapter_profile)
            self.__highest_generation_by_slot[attestation.slot_id] = (
                attestation.lease_generation
            )
            return capability

    def return_capability(self, capability: _ArchiveWorkspaceCapability) -> None:
        with self.__lock:
            backend_lease = self.__require_active(capability)
            capability._invalidate(self.__coordinator_token, ArchiveWorkspaceState.RETURNED)
            self.__active.pop(capability.lease_id)
            try:
                returned = self._return_backend_lease(backend_lease)
                self.__validate_returned(backend_lease.attestation, returned)
            except Exception as error:
                capability._quarantine_after_failed_return(self.__coordinator_token)
                self.__quarantine_best_effort(backend_lease)
                raise ArchiveWorkspaceError() from error

    def quarantine_capability(self, capability: _ArchiveWorkspaceCapability) -> None:
        with self.__lock:
            backend_lease = self.__require_active(capability)
            capability._invalidate(self.__coordinator_token, ArchiveWorkspaceState.QUARANTINED)
            self.__active.pop(capability.lease_id)
            try:
                self._quarantine_backend_lease(backend_lease)
            except Exception as error:
                raise ArchiveWorkspaceError() from error

    @abstractmethod
    def _acquire_backend_lease(
        self, limits: _ArchiveWorkspaceLimits
    ) -> _BackendWorkspaceLease | None:
        """Acquire a process-safe fenced backend lease, or return no capacity."""

    @abstractmethod
    def _return_backend_lease(
        self, backend_lease: _BackendWorkspaceLease
    ) -> _ArchiveWorkspaceAttestation:
        """Clean, attest empty, persist return, and release the backend lease."""

    @abstractmethod
    def _quarantine_backend_lease(self, backend_lease: _BackendWorkspaceLease) -> None:
        """Persistently prevent reuse of an unsafe backend lease."""

    def __validate_leased(self, backend_lease: _BackendWorkspaceLease) -> None:
        if not isinstance(backend_lease, _BackendWorkspaceLease):
            raise ValueError("archive workspace lease is invalid")
        attestation = backend_lease.attestation
        if (
            attestation.state is not ArchiveWorkspaceState.LEASED
            or not attestation.empty
            or not attestation.runtime_authorized
            or attestation.limits != self.__limits
            or (attestation.provider_id, attestation.adapter_profile)
            not in _APPROVED_BACKEND_IDENTITIES
        ):
            raise ValueError("archive workspace lease is invalid")

    def __validate_returned(
        self,
        leased: _ArchiveWorkspaceAttestation,
        returned: _ArchiveWorkspaceAttestation,
    ) -> None:
        if not isinstance(returned, _ArchiveWorkspaceAttestation):
            raise ValueError("archive workspace return is invalid")
        if (
            returned.provider_id != leased.provider_id
            or returned.profile != leased.profile
            or returned.compatibility != leased.compatibility
            or returned.adapter_profile != leased.adapter_profile
            or returned.slot_id != leased.slot_id
            or returned.lease_id != leased.lease_id
            or returned.lease_generation != leased.lease_generation
            or returned.attestation_fingerprint != leased.attestation_fingerprint
            or returned.limits != leased.limits
            or returned.state is not ArchiveWorkspaceState.RETURNED
            or not returned.empty
            or not returned.runtime_authorized
        ):
            raise ValueError("archive workspace return is invalid")

    def __validate_identity_and_generation(
        self, attestation: _ArchiveWorkspaceAttestation
    ) -> None:
        identity = (attestation.provider_id, attestation.adapter_profile)
        if self.__backend_identity is not None and identity != self.__backend_identity:
            raise ValueError("archive workspace lease is invalid")
        previous = self.__highest_generation_by_slot.get(attestation.slot_id, 0)
        if attestation.lease_generation <= previous:
            raise ValueError("archive workspace lease is invalid")

    def __require_active(
        self, capability: _ArchiveWorkspaceCapability
    ) -> _BackendWorkspaceLease:
        if not isinstance(capability, _ArchiveWorkspaceCapability):
            raise ArchiveWorkspaceError()
        if not capability._belongs_to(self.__coordinator_token):
            raise ArchiveWorkspaceError()
        if self.__active.get(capability.lease_id) is not capability:
            raise ArchiveWorkspaceError()
        if capability.state is not ArchiveWorkspaceState.LEASED:
            raise ArchiveWorkspaceError()
        return capability._backend_material(self.__coordinator_token)

    def __quarantine_best_effort(self, backend_lease: object) -> None:
        if not isinstance(backend_lease, _BackendWorkspaceLease):
            return
        try:
            self._quarantine_backend_lease(backend_lease)
        except Exception:
            return


def _require_opaque(field_name: str, value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_OPAQUE_CODEPOINTS
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or any(character in value for character in ("/", "\\", ":"))
    ):
        raise ValueError(f"{field_name} must be a bounded opaque identifier")


def _require_profile(field_name: str, value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_OPAQUE_CODEPOINTS
        or value.startswith("/")
        or "\\" in value
        or ":" in value
        or "//" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded profile")
