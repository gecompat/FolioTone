"""Bounded SQLite reads for observation-bound analysis Evidence."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import Engine, select

from foliotone.core import EntityId, EntityKind, Fingerprint
from foliotone.persistence.codecs import codec_for
from foliotone.tooling import ToolExecution, ToolResult

MAX_EVIDENCE_QUERY_OBSERVATIONS = 16
MAX_EVIDENCE_QUERY_EXECUTIONS = 1_024
MAX_EVIDENCE_QUERY_RESULTS = 16_384
MAX_EVIDENCE_QUERY_FINGERPRINTS = 4_096


class EvidenceQueryLimitError(RuntimeError):
    """A bounded Evidence read would exceed its explicit safety limit."""


@dataclass(frozen=True, slots=True)
class ObservationEvidenceRecords:
    """Persisted records loaded only for an explicit observation set."""

    executions: tuple[ToolExecution, ...]
    results: tuple[ToolResult, ...]
    fingerprints: tuple[Fingerprint, ...]


def load_observation_evidence(
    engine: Engine,
    observation_ids: Collection[EntityId],
) -> ObservationEvidenceRecords:
    """Load a bounded Evidence projection without scanning collection-wide tables."""
    selected_ids = tuple(sorted(set(observation_ids), key=str))
    if len(selected_ids) > MAX_EVIDENCE_QUERY_OBSERVATIONS:
        raise EvidenceQueryLimitError("too many observation IDs for one Evidence query")
    if not selected_ids:
        return ObservationEvidenceRecords((), (), ())

    identities = tuple(f"file-observation:{value}" for value in selected_ids)
    target_ids = tuple(str(value) for value in selected_ids)
    execution_codec = codec_for(ToolExecution)
    result_codec = codec_for(ToolResult)
    fingerprint_codec = codec_for(Fingerprint)

    with engine.connect() as connection:
        execution_rows = connection.execute(
            select(execution_codec.table)
            .where(execution_codec.table.c.input_identity.in_(identities))
            .order_by(execution_codec.table.c.id)
            .limit(MAX_EVIDENCE_QUERY_EXECUTIONS + 1)
        ).mappings().all()
        _check_limit(
            "ToolExecution",
            len(execution_rows),
            MAX_EVIDENCE_QUERY_EXECUTIONS,
        )

        result_rows = connection.execute(
            select(result_codec.table)
            .where(
                result_codec.table.c.target_kind == EntityKind.FILE_OBSERVATION.value,
                result_codec.table.c.target_id.in_(target_ids),
            )
            .order_by(result_codec.table.c.id)
            .limit(MAX_EVIDENCE_QUERY_RESULTS + 1)
        ).mappings().all()
        _check_limit("ToolResult", len(result_rows), MAX_EVIDENCE_QUERY_RESULTS)

        fingerprint_rows = connection.execute(
            select(fingerprint_codec.table)
            .where(
                fingerprint_codec.table.c.target_kind
                == EntityKind.FILE_OBSERVATION.value,
                fingerprint_codec.table.c.target_id.in_(target_ids),
            )
            .order_by(fingerprint_codec.table.c.id)
            .limit(MAX_EVIDENCE_QUERY_FINGERPRINTS + 1)
        ).mappings().all()
        _check_limit(
            "Fingerprint",
            len(fingerprint_rows),
            MAX_EVIDENCE_QUERY_FINGERPRINTS,
        )

    return ObservationEvidenceRecords(
        executions=tuple(execution_codec.decode(row) for row in execution_rows),
        results=tuple(result_codec.decode(row) for row in result_rows),
        fingerprints=tuple(
            fingerprint_codec.decode(row) for row in fingerprint_rows
        ),
    )


def _check_limit(record_type: str, count: int, maximum: int) -> None:
    if count > maximum:
        raise EvidenceQueryLimitError(
            f"{record_type} Evidence exceeds the per-request safety limit"
        )
