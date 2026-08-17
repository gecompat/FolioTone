from datetime import UTC, datetime

import pytest

from foliotone.core import EntityId, EntityKind, MatchStatus, Relation, RelationType
from foliotone.matching import (
    RELATION_CONTRACTS,
    CandidateBlock,
    CandidateBlockMember,
    CandidateBlockStatus,
    CandidateBlockStrength,
    CandidateBlockType,
    RelationIdentityEffect,
    build_candidate_block_key,
    validate_relation_endpoints,
)


def ids(count: int) -> list[EntityId]:
    return [
        EntityId.parse(f"00000000-0000-4000-8000-{index:012d}") for index in range(1, count + 1)
    ]


def members(count: int = 2) -> tuple[CandidateBlockMember, ...]:
    values = ids(count * 2)
    return tuple(
        CandidateBlockMember(values[index * 2], values[index * 2 + 1]) for index in range(count)
    )


def block(**overrides: object) -> CandidateBlock:
    values = members()
    data: dict[str, object] = {
        "block_type": CandidateBlockType.RESOLVED_WORK,
        "key_fingerprint": "a" * 64,
        "block_version": "v1",
        "identity_level": EntityKind.WORK,
        "strength": CandidateBlockStrength.IDENTITY_CAPABLE,
        "member_count": len(values),
        "members": values,
        "status": CandidateBlockStatus.READY,
    }
    data.update(overrides)
    return CandidateBlock(**data)


def test_literals_and_key_are_deterministic_and_path_free() -> None:
    assert {item.value for item in CandidateBlockType} == {
        "FILE_SHA256",
        "EDITION_IDENTIFIER",
        "RESOLVED_EDITION",
        "RESOLVED_WORK",
        "AGENT_TITLE",
        "TEXT_FINGERPRINT",
        "SERIES_CONTEXT",
    }
    first = build_candidate_block_key(CandidateBlockType.AGENT_TITLE, "v1", ("title", "agent"))
    assert first == build_candidate_block_key(
        CandidateBlockType.AGENT_TITLE, "v1", ("agent", "title")
    )
    assert first != build_candidate_block_key(
        CandidateBlockType.AGENT_TITLE,
        "v1",
        ("agent=title", "title=agent"),
    )
    assert len(first) == 64
    assert "\\" not in repr(block())
    assert "/" not in repr(block())


def test_member_and_block_order_is_canonical_and_exact_group_is_represented() -> None:
    value = ids(4)
    member_a = CandidateBlockMember(value[2], value[3], (value[0], value[1]))
    member_b = CandidateBlockMember(value[0], value[1])
    result = CandidateBlock(
        CandidateBlockType.FILE_SHA256,
        "b" * 64,
        "v1",
        EntityKind.FILE,
        CandidateBlockStrength.IDENTITY_CAPABLE,
        2,
        (member_b, member_a),
        CandidateBlockStatus.EXACT_GROUP,
        value[0],
    )
    assert result.members[0] == member_b
    assert member_a.evidence_ids == tuple(sorted(member_a.evidence_ids, key=str))
    assert not result.is_pairwise_expandable

    with pytest.raises(ValueError, match="unique observations"):
        CandidateBlock(
            CandidateBlockType.RESOLVED_WORK,
            "c" * 64,
            "v1",
            EntityKind.WORK,
            CandidateBlockStrength.IDENTITY_CAPABLE,
            2,
            (
                CandidateBlockMember(value[0], value[1]),
                CandidateBlockMember(value[0], value[2]),
            ),
        )


def test_block_invariants_and_secondary_guard() -> None:
    with pytest.raises(ValueError):
        block(member_count=3)
    with pytest.raises(ValueError):
        block(key_fingerprint="A" * 64)
    with pytest.raises(ValueError):
        block(block_type=CandidateBlockType.RESOLVED_WORK, status=CandidateBlockStatus.EXACT_GROUP)
    with pytest.raises(ValueError, match="FILE_SHA256"):
        block(
            block_type=CandidateBlockType.FILE_SHA256,
            identity_level=EntityKind.FILE,
        )
    secondary = block(status=CandidateBlockStatus.SECONDARY_REQUIRED)
    assert not secondary.is_pairwise_expandable
    assert not secondary.can_expand_pairs
    with pytest.raises(ValueError):
        block(members=tuple(reversed(members())))


def test_all_relation_contracts_and_relation_endpoint_validation() -> None:
    expected = {
        RelationType.EXACT_DUPLICATE: (EntityKind.FILE, RelationIdentityEffect.CONFIRMS_IDENTITY),
        RelationType.CONTENT_DUPLICATE: (EntityKind.FILE, RelationIdentityEffect.NONE),
        RelationType.FORMAT_VARIANT: (EntityKind.FILE, RelationIdentityEffect.NONE),
        RelationType.QUALITY_VARIANT: (EntityKind.FILE, RelationIdentityEffect.NONE),
        RelationType.SAME_EDITION: (EntityKind.EDITION, RelationIdentityEffect.CONFIRMS_IDENTITY),
        RelationType.DIFFERENT_EDITION: (
            EntityKind.EDITION,
            RelationIdentityEffect.CONTRADICTS_IDENTITY,
        ),
        RelationType.SAME_WORK: (EntityKind.WORK, RelationIdentityEffect.CONFIRMS_IDENTITY),
    }
    assert set(expected) <= set(RELATION_CONTRACTS)
    for relation_type, (endpoint, effect) in expected.items():
        contract = RELATION_CONTRACTS[relation_type]
        assert contract.endpoint_kind is endpoint
        assert contract.symmetric
        assert contract.identity_effect is effect
        assert contract.required_evidence_codes
        relation = Relation(
            EntityId.new(),
            endpoint,
            EntityId.new(),
            endpoint,
            EntityId.new(),
            relation_type,
            1.0,
            MatchStatus.CONFIRMED,
            datetime.now(UTC),
        )
        assert validate_relation_endpoints(
            relation.relation_type,
            relation.left_kind,
            relation.right_kind,
        ) is contract
        wrong = EntityKind.WORK if endpoint is not EntityKind.WORK else EntityKind.FILE
        with pytest.raises(ValueError):
            validate_relation_endpoints(
                relation_type,
                wrong,
                wrong,
            )


def test_large_block_has_bounded_representation() -> None:
    value = block(
        member_count=1000,
        members=members(128),
        status=CandidateBlockStatus.SECONDARY_REQUIRED,
    )
    assert len(value.members) == 128
    assert value.member_count == 1000
    assert len(value.members) < value.member_count
    assert not value.is_pairwise_expandable
