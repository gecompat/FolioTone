"""Authority identities, names, identifiers, and contributor roles."""

from __future__ import annotations

from dataclasses import dataclass

from foliotone.core._validation import require_non_empty
from foliotone.core.common import Provenance
from foliotone.core.enums import AgentNameType, AgentType, EntityKind
from foliotone.core.ids import EntityId


@dataclass(frozen=True, slots=True)
class Agent:
    """A person, group, ensemble, or organization with one or more roles."""

    id: EntityId
    agent_type: AgentType


@dataclass(frozen=True, slots=True)
class AgentName:
    """One provenance-preserving name form for an Agent."""

    id: EntityId
    agent_id: EntityId
    name_type: AgentNameType
    value: str
    provenance: Provenance
    normalized_value: str | None = None
    language: str | None = None
    script: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", require_non_empty(self.value, "value"))
        for field_name in ("normalized_value", "language", "script"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, require_non_empty(value, field_name))


@dataclass(frozen=True, slots=True)
class ExternalIdentifier:
    """Namespaced identifier associated with a FolioTone entity."""

    id: EntityId
    target_kind: EntityKind
    target_id: EntityId
    namespace: str
    value: str
    provenance: Provenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", require_non_empty(self.namespace, "namespace"))
        object.__setattr__(self, "value", require_non_empty(self.value, "value"))


@dataclass(frozen=True, slots=True)
class Contribution:
    """Typed relationship between an Agent and another domain entity."""

    id: EntityId
    agent_id: EntityId
    target_kind: EntityKind
    target_id: EntityId
    role: str
    provenance: Provenance
    credited_as: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", require_non_empty(self.role, "role"))
        if self.target_kind is EntityKind.AGENT:
            raise ValueError("Contribution target must not be an Agent")
        if self.credited_as is not None:
            object.__setattr__(
                self,
                "credited_as",
                require_non_empty(self.credited_as, "credited_as"),
            )
