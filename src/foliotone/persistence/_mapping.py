"""Shared SQL row/domain conversion helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from foliotone.core.common import Provenance
from foliotone.core.ids import EntityId


def id_to_db(value: EntityId | None) -> str | None:
    """Serialize an internal identifier for SQL storage."""
    return None if value is None else str(value)


def id_from_db(value: str | None) -> EntityId | None:
    """Deserialize an optional internal identifier from SQL storage."""
    return None if value is None else EntityId.parse(value)


def required_id_from_db(value: str) -> EntityId:
    """Deserialize a required internal identifier."""
    return EntityId.parse(value)


def datetime_to_db(value: datetime | None) -> str | None:
    """Serialize aware datetimes as normalized UTC ISO-8601 text."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("persisted datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def datetime_from_db(value: str | None) -> datetime | None:
    """Deserialize an optional ISO-8601 datetime."""
    return None if value is None else datetime.fromisoformat(value)


def required_datetime_from_db(value: str) -> datetime:
    """Deserialize a required ISO-8601 datetime."""
    return datetime.fromisoformat(value)


def provenance_to_row(value: Provenance) -> dict[str, Any]:
    """Flatten provenance into common SQL columns."""
    return {
        "source_kind": value.source_kind,
        "source_name": value.source_name,
        "source_version": value.source_version,
        "observed_at": datetime_to_db(value.observed_at),
    }


def provenance_from_row(row: Any) -> Provenance:
    """Reconstruct provenance from common SQL columns."""
    return Provenance(
        source_kind=str(row["source_kind"]),
        source_name=str(row["source_name"]),
        source_version=None if row["source_version"] is None else str(row["source_version"]),
        observed_at=required_datetime_from_db(str(row["observed_at"])),
    )
