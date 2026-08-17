"""Immutable candidate-block and relation contracts for e-book matching."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from foliotone.core.enums import EntityKind, RelationType
from foliotone.core.ids import EntityId


class CandidateBlockType(StrEnum):
    FILE_SHA256 = "FILE_SHA256"
    EDITION_IDENTIFIER = "EDITION_IDENTIFIER"
    RESOLVED_EDITION = "RESOLVED_EDITION"
    RESOLVED_WORK = "RESOLVED_WORK"
    AGENT_TITLE = "AGENT_TITLE"
    TEXT_FINGERPRINT = "TEXT_FINGERPRINT"
    SERIES_CONTEXT = "SERIES_CONTEXT"


class CandidateBlockStrength(StrEnum):
    IDENTITY_CAPABLE = "IDENTITY_CAPABLE"
    SUPPORTING_ONLY = "SUPPORTING_ONLY"


class CandidateBlockStatus(StrEnum):
    READY = "READY"
    EXACT_GROUP = "EXACT_GROUP"
    SECONDARY_REQUIRED = "SECONDARY_REQUIRED"


class RelationIdentityEffect(StrEnum):
    CONFIRMS_IDENTITY = "CONFIRMS_IDENTITY"
    CONTRADICTS_IDENTITY = "CONTRADICTS_IDENTITY"
    NONE = "NONE"


MAX_CANDIDATE_BLOCK_MEMBERS = 256
MAX_CANDIDATE_BLOCK_EVIDENCE_IDS = 256
_SHA256_HEX_LENGTH = 64


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != _SHA256_HEX_LENGTH or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hexadecimal digest")
    return value


def _sorted_unique_ids(values: Iterable[EntityId], field_name: str) -> tuple[EntityId, ...]:
    result = tuple(values)
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must contain unique identifiers")
    if result != tuple(sorted(result, key=str)):
        raise ValueError(f"{field_name} must be sorted")
    return result


@dataclass(frozen=True, slots=True)
class CandidateBlockMember:
    """Path-free observation membership and its bounded evidence references."""

    observation_id: EntityId
    file_id: EntityId
    evidence_ids: tuple[EntityId, ...] = ()

    def __post_init__(self) -> None:
        evidence_ids = _sorted_unique_ids(self.evidence_ids, "evidence_ids")
        if len(evidence_ids) > MAX_CANDIDATE_BLOCK_EVIDENCE_IDS:
            raise ValueError("evidence_ids exceeds the bounded member limit")
        object.__setattr__(self, "evidence_ids", evidence_ids)


@dataclass(frozen=True, slots=True)
class CandidateBlock:
    """Bounded, deterministic candidate block without raw collection values."""

    block_type: CandidateBlockType
    key_fingerprint: str
    block_version: str
    identity_level: EntityKind
    strength: CandidateBlockStrength
    member_count: int
    members: tuple[CandidateBlockMember, ...]
    status: CandidateBlockStatus = CandidateBlockStatus.READY
    representative_observation_id: EntityId | None = None

    def __post_init__(self) -> None:
        _require_sha256(self.key_fingerprint, "key_fingerprint")
        if not self.block_version.strip():
            raise ValueError("block_version must not be empty")
        if self.member_count < 2:
            raise ValueError("member_count must be at least 2")
        if len(self.members) > MAX_CANDIDATE_BLOCK_MEMBERS:
            raise ValueError("members exceeds the bounded representation limit")
        members = tuple(self.members)
        if len(set(members)) != len(members):
            raise ValueError("members must be unique")
        if len({member.observation_id for member in members}) != len(members):
            raise ValueError("members must contain unique observations")
        if members != tuple(
            sorted(members, key=lambda item: (str(item.observation_id), str(item.file_id)))
        ):
            raise ValueError("members must be sorted")
        if len(members) > self.member_count:
            raise ValueError("members cannot exceed member_count")
        if self.status is CandidateBlockStatus.READY and len(members) != self.member_count:
            raise ValueError("READY blocks must include all members")
        expected_level, expected_strength = _BLOCK_TYPE_POLICY[self.block_type]
        if self.identity_level is not expected_level or self.strength is not expected_strength:
            raise ValueError("identity_level and strength do not match block_type")
        if (
            self.block_type is CandidateBlockType.FILE_SHA256
            and self.status is not CandidateBlockStatus.EXACT_GROUP
        ):
            raise ValueError("FILE_SHA256 blocks must use EXACT_GROUP")
        if self.status is CandidateBlockStatus.EXACT_GROUP:
            if self.block_type is not CandidateBlockType.FILE_SHA256:
                raise ValueError("EXACT_GROUP is only valid for FILE_SHA256 blocks")
            if self.representative_observation_id is None:
                raise ValueError("EXACT_GROUP requires a representative observation")
        if self.representative_observation_id is not None and not any(
            member.observation_id == self.representative_observation_id for member in members
        ):
            raise ValueError("representative_observation_id must be a block member")
        object.__setattr__(self, "members", members)

    @property
    def is_pairwise_expandable(self) -> bool:
        """Whether the block may be expanded into pair candidates."""
        return self.status is CandidateBlockStatus.READY

    @property
    def can_expand_pairs(self) -> bool:
        """Compatibility alias for the pair-expansion guard."""
        return self.is_pairwise_expandable

    @property
    def members_truncated(self) -> bool:
        """Whether the bounded member projection omits block members."""
        return len(self.members) < self.member_count


def build_candidate_block_key(
    block_type: CandidateBlockType,
    block_version: str,
    material_components: Sequence[str],
) -> str:
    """Build a domain-separated, order-independent SHA-256 block key."""
    version = block_version.strip()
    if not version:
        raise ValueError("block_version must not be empty")
    components = tuple(sorted(set(component.strip() for component in material_components)))
    if not components or any(not component for component in components):
        raise ValueError("material_components must contain non-empty values")
    encoded = [b"foliotone:candidate-block", block_type.value.encode(), version.encode()]
    encoded.extend(f"{len(component)}:".encode() + component.encode() for component in components)
    return hashlib.sha256(b"\x00".join(encoded)).hexdigest()


@dataclass(frozen=True, slots=True)
class RelationContract:
    """Book-only relation semantics and endpoint validation."""

    relation_type: RelationType
    left_kind: EntityKind
    right_kind: EntityKind
    symmetric: bool
    identity_effect: RelationIdentityEffect
    required_evidence_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.required_evidence_codes or any(
            not code.strip() for code in self.required_evidence_codes
        ):
            raise ValueError("required_evidence_codes must be non-empty")
        if len(set(self.required_evidence_codes)) != len(self.required_evidence_codes):
            raise ValueError("required_evidence_codes must be unique")

    @property
    def endpoint_kind(self) -> EntityKind:
        if self.left_kind is not self.right_kind:
            raise ValueError("relation contract endpoints are not a single level")
        return self.left_kind


def _contract(
    relation_type: RelationType,
    endpoint: EntityKind,
    effect: RelationIdentityEffect,
    evidence: tuple[str, ...],
) -> RelationContract:
    return RelationContract(relation_type, endpoint, endpoint, True, effect, evidence)


RELATION_CONTRACTS: dict[RelationType, RelationContract] = {
    RelationType.EXACT_DUPLICATE: _contract(
        RelationType.EXACT_DUPLICATE,
        EntityKind.FILE,
        RelationIdentityEffect.CONFIRMS_IDENTITY,
        ("FILE_SHA256",),
    ),
    RelationType.CONTENT_DUPLICATE: _contract(
        RelationType.CONTENT_DUPLICATE,
        EntityKind.FILE,
        RelationIdentityEffect.NONE,
        ("CONTENT_FINGERPRINT",),
    ),
    RelationType.FORMAT_VARIANT: _contract(
        RelationType.FORMAT_VARIANT,
        EntityKind.FILE,
        RelationIdentityEffect.NONE,
        ("FORMAT_EVIDENCE",),
    ),
    RelationType.QUALITY_VARIANT: _contract(
        RelationType.QUALITY_VARIANT,
        EntityKind.FILE,
        RelationIdentityEffect.NONE,
        ("QUALITY_EVIDENCE",),
    ),
    RelationType.SAME_EDITION: _contract(
        RelationType.SAME_EDITION,
        EntityKind.EDITION,
        RelationIdentityEffect.CONFIRMS_IDENTITY,
        ("EDITION_IDENTIFIER",),
    ),
    RelationType.DIFFERENT_EDITION: _contract(
        RelationType.DIFFERENT_EDITION,
        EntityKind.EDITION,
        RelationIdentityEffect.CONTRADICTS_IDENTITY,
        ("WORK_RESOLUTION", "EDITION_IDENTIFIER"),
    ),
    RelationType.SAME_WORK: _contract(
        RelationType.SAME_WORK,
        EntityKind.WORK,
        RelationIdentityEffect.CONFIRMS_IDENTITY,
        ("WORK_RESOLUTION",),
    ),
}


def relation_contract_for(relation_type: RelationType) -> RelationContract | None:
    """Return the book relation contract, if this type is in the matrix."""
    return RELATION_CONTRACTS.get(relation_type)


def validate_relation_endpoints(
    relation_type: RelationType,
    left_kind: EntityKind,
    right_kind: EntityKind,
) -> RelationContract:
    """Validate book-only endpoint levels without coupling core to matching."""

    contract = relation_contract_for(relation_type)
    if contract is None:
        raise ValueError("relation_type has no book-only relation contract")
    if left_kind is not contract.left_kind or right_kind is not contract.right_kind:
        raise ValueError(
            f"{relation_type} requires "
            f"{contract.left_kind}/{contract.right_kind} endpoints"
        )
    return contract


_BLOCK_TYPE_POLICY: dict[CandidateBlockType, tuple[EntityKind, CandidateBlockStrength]] = {
    CandidateBlockType.FILE_SHA256: (EntityKind.FILE, CandidateBlockStrength.IDENTITY_CAPABLE),
    CandidateBlockType.EDITION_IDENTIFIER: (
        EntityKind.EDITION,
        CandidateBlockStrength.IDENTITY_CAPABLE,
    ),
    CandidateBlockType.RESOLVED_EDITION: (
        EntityKind.EDITION,
        CandidateBlockStrength.IDENTITY_CAPABLE,
    ),
    CandidateBlockType.RESOLVED_WORK: (EntityKind.WORK, CandidateBlockStrength.IDENTITY_CAPABLE),
    CandidateBlockType.AGENT_TITLE: (EntityKind.WORK, CandidateBlockStrength.IDENTITY_CAPABLE),
    CandidateBlockType.TEXT_FINGERPRINT: (EntityKind.FILE, CandidateBlockStrength.IDENTITY_CAPABLE),
    CandidateBlockType.SERIES_CONTEXT: (EntityKind.SERIES, CandidateBlockStrength.SUPPORTING_ONLY),
}
