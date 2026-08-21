"""Insert-only immutable archive evidence persistence from ADR-0052."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import Engine, func, insert, select
from sqlalchemy.engine import Connection

from foliotone.archive.provider import (
    ARCHIVE_PROVIDER_PROFILE,
    ARCHIVE_WRAPPER_PROVIDER_PROFILE,
    ArchiveProviderOutcome,
    _command_identity,
)
from foliotone.archive.sevenzip import (
    ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
    build_7zzs_tar_stdin_integrity_command,
    build_7zzs_tar_stdin_listing_command,
    build_7zzs_wrapper_decode_command,
)
from foliotone.archive.sevenzip_slt import (
    ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE,
    ARCHIVE_7ZIP_FORMAT_LOCK_SHA256,
    ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE,
    ArchiveSevenZipSltParseStatus,
)
from foliotone.archive.signatures import (
    ArchiveContainerClass,
    ArchiveOuterCompressionKind,
    ArchivePublicationKind,
    ArchiveRecognitionStatus,
    ArchiveSignatureObservationV2,
    ArchiveStorageFamily,
)
from foliotone.archive.workflow import (
    ARCHIVE_EXTRACTION_PROFILE,
    ARCHIVE_INTEGRITY_PROFILE,
    ARCHIVE_LISTING_PROFILE,
    ARCHIVE_MEMBER_PROFILE,
    NONE_SECRET_VERSION,
    ArchiveReuseKey,
    build_archive_member_identity,
)
from foliotone.core import EntityId
from foliotone.persistence import archive_schema, schema
from foliotone.persistence._mapping import datetime_to_db
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)

if TYPE_CHECKING:
    from foliotone.consolidation.archive_dependencies import (
        ArchiveSourceDependencyBinding,
    )

ARCHIVE_OBSERVATION_PROFILE: Final = "archive-observation/v1"
ARCHIVE_CONTENT_FINGERPRINT_DOMAIN: Final = b"archive-content-fingerprint/v1\x00"
ARCHIVE_VOLUME_GROUP_DOMAIN: Final = b"archive-volume-group/v1\x00"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_STAGING = re.compile(r"archive(?:\.[A-Za-z0-9]{1,24})?\Z")
_WRAPPER_RUNNER_PROFILE: Final = "archive-wrapper-container-runner/v1"
_WRAPPER_IMAGE_REFERENCE: Final = (
    "ghcr.io/gecompat/foliotone-archive-7zip@sha256:"
    "26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287"
)
_WRITER_KINDS = {
    ScanRootWriteOwnerKind.EBOOK_ANALYSIS,
    ScanRootWriteOwnerKind.EBOOK_COLLECTION_RUN,
    ScanRootWriteOwnerKind.ARCHIVE_COLLECTION_RUN,
}


class ArchiveEvidenceStoreError(RuntimeError):
    """Path-, locator-, and secret-free archive persistence failure."""


@dataclass(frozen=True, slots=True)
class ArchiveEvidenceSource:
    """One ordered, opaque source observation in an archive volume group."""

    file_observation_id: EntityId
    full_sha256: str
    size_bytes: int
    staging_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.file_observation_id, EntityId):
            raise ValueError("archive source requires an EntityId")
        _require_sha256(self.full_sha256)
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("archive source size is invalid")
        if not isinstance(self.staging_name, str) or _STAGING.fullmatch(
            self.staging_name
        ) is None:
            raise ValueError("archive staging name is invalid")


@dataclass(frozen=True, slots=True)
class ArchiveEvidenceSnapshot:
    """Same-run private provider material ready for one fenced insert."""

    id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    observed_at: datetime
    signature: ArchiveSignatureObservationV2 = field(repr=False)
    outcome: ArchiveProviderOutcome = field(repr=False)
    sources: tuple[ArchiveEvidenceSource, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, EntityId)
            for value in (self.id, self.scan_root_id, self.source_scan_run_id)
        ):
            raise ValueError("archive snapshot IDs are invalid")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("archive observation time must be timezone-aware")
        if not isinstance(self.signature, ArchiveSignatureObservationV2):
            raise ValueError("archive signature is invalid")
        if not isinstance(self.outcome, ArchiveProviderOutcome):
            raise ValueError("archive provider outcome is invalid")
        if (
            not isinstance(self.sources, tuple)
            or not 1 <= len(self.sources) <= 256
            or any(not isinstance(item, ArchiveEvidenceSource) for item in self.sources)
        ):
            raise ValueError("archive sources are invalid or exceed the bound")
        names = tuple(item.staging_name.casefold() for item in self.sources)
        if len(set(names)) != len(names) or names.count("archive") != 1:
            raise ValueError("archive sources require one unique primary volume")
        handoff = self.outcome._persistence_handoff
        result = self.outcome.result
        if (
            result is None
            or (
                result.listing_status.value != "NOT_ATTEMPTED"
                and handoff is None
            )
            or (result.listing_status.value == "LISTED" and handoff is None)
        ):
            raise ValueError("archive snapshot lacks sealed same-run parser material")
        if handoff is not None and (
            handoff.outcome is not self.outcome
            or handoff.signature is not self.signature
            or handoff.listing_result.reuse_key is not result.reuse_key
            or any(
                item.archive_observation_id != str(self.id)
                for item in handoff.listing_result.members
            )
        ):
            raise ValueError("archive snapshot parser lineage is inconsistent")
        primary = next(item for item in self.sources if item.staging_name == "archive")
        if primary.full_sha256 != result.reuse_key.archive_full_sha256:
            raise ValueError("archive primary source does not match provider material")
        if _volume_group_fingerprint(self.sources) != (
            result.reuse_key.volume_group_fingerprint
        ):
            raise ValueError("archive volume group does not match provider material")


@dataclass(frozen=True, slots=True)
class ArchiveEvidenceCompatibility:
    """Exact signature/parser/provider compatibility for one reuse lookup."""

    signature: ArchiveSignatureObservationV2
    provider_profile: str
    runner_profile: str
    parser_status: ArchiveSevenZipSltParseStatus
    format_case_kind: str | None
    wrapper_image_reference: str | None = None
    wrapper_command_identity: str | None = None
    listing_command_identity: str | None = None
    integrity_command_identity: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.signature, ArchiveSignatureObservationV2):
            raise ValueError("archive reuse signature is invalid")
        if self.provider_profile not in {
            ARCHIVE_PROVIDER_PROFILE,
            ARCHIVE_WRAPPER_PROVIDER_PROFILE,
        }:
            raise ValueError("archive reuse provider profile is invalid")
        if not isinstance(self.parser_status, ArchiveSevenZipSltParseStatus):
            raise ValueError("archive reuse parser status is invalid")
        if (self.parser_status is ArchiveSevenZipSltParseStatus.PARSED) is not (
            self.format_case_kind is not None
        ):
            raise ValueError("archive reuse parser case is inconsistent")
        wrapper_values = (
            self.wrapper_image_reference,
            self.wrapper_command_identity,
            self.listing_command_identity,
            self.integrity_command_identity,
        )
        if self.provider_profile == ARCHIVE_WRAPPER_PROVIDER_PROFILE:
            if (
                self.runner_profile != _WRAPPER_RUNNER_PROFILE
                or self.wrapper_image_reference != _WRAPPER_IMAGE_REFERENCE
                or any(value is None for value in wrapper_values)
            ):
                raise ValueError("wrapper reuse compatibility is incomplete")
            for value in wrapper_values[1:]:
                assert value is not None
                _require_sha256(value)
        elif (
            self.runner_profile != ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE
            or any(value is not None for value in wrapper_values)
        ):
            raise ValueError("direct archive reuse cannot carry wrapper compatibility")
        if self.format_case_kind is not None and self.format_case_kind not in {
            "PLAINTEXT_REGULAR",
            "DIRECTORY",
            "ALL_ENCRYPTED",
            "MIXED",
            "SYMBOLIC_LINK",
            "HARD_LINK",
        }:
            raise ValueError("archive reuse parser case is invalid")


@dataclass(frozen=True, slots=True)
class PersistedArchiveEvidence:
    """Locator-free public projection of one validated persisted graph."""

    id: EntityId
    content_hash: str
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    observed_at: datetime
    listing_status: str
    integrity_status: str
    extraction_status: str
    member_count: int
    source_count: int
    execution_count: int
    has_wrapper_lineage: bool

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, EntityId)
            for value in (self.id, self.scan_root_id, self.source_scan_run_id)
        ):
            raise ValueError("persisted archive IDs are invalid")
        _require_sha256(self.content_hash)
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("persisted archive time is invalid")
        for value, lower, bound in (
            (self.member_count, 0, 10_000),
            (self.source_count, 1, 256),
            (self.execution_count, 0, 3),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= bound:
                raise ValueError("persisted archive count is invalid")
            if value < lower:
                raise ValueError("persisted archive count is invalid")
        if not isinstance(self.has_wrapper_lineage, bool):
            raise ValueError("persisted wrapper lineage flag is invalid")
        expected_executions = (
            0
            if self.listing_status == "NOT_ATTEMPTED"
            else 1 + (self.integrity_status != "NOT_TESTED")
        )
        if (
            self.listing_status
            not in {
                "NOT_ATTEMPTED",
                "LISTED",
                "LIMIT_EXCEEDED",
                "TIMED_OUT",
                "TOOL_UNAVAILABLE",
                "TOOL_FAILED",
                "POLICY_REJECTED",
            }
            or self.integrity_status
            not in {
                "NOT_TESTED",
                "PASSED",
                "LIMIT_EXCEEDED",
                "TIMED_OUT",
                "TOOL_UNAVAILABLE",
                "TOOL_FAILED",
                "POLICY_REJECTED",
            }
            or self.extraction_status != "NOT_ATTEMPTED"
            or self.execution_count != expected_executions
            or (self.listing_status != "LISTED" and self.member_count != 0)
        ):
            raise ValueError("persisted archive status projection is invalid")


@dataclass(frozen=True, slots=True)
class _PersistedArchiveEvidenceGraph:
    """Lossless, immutable database graph represented by canonical row tuples."""

    parent: tuple[tuple[str, Any], ...]
    sources: tuple[tuple[tuple[str, Any], ...], ...]
    executions: tuple[tuple[tuple[str, Any], ...], ...]
    members: tuple[tuple[tuple[str, Any], ...], ...]
    wrapper: tuple[tuple[str, Any], ...] | None

    def __post_init__(self) -> None:
        if not isinstance(self.parent, tuple):
            raise ValueError("archive parent row is invalid")
        parent = dict(self.parent)
        observation_id = str(parent.get("id", ""))
        EntityId.parse(observation_id)
        _require_sha256(str(parent.get("content_hash", "")))
        for rows, bound, label in (
            (self.sources, 256, "source"),
            (self.executions, 3, "execution"),
            (self.members, 10_000, "member"),
        ):
            if (
                not isinstance(rows, tuple)
                or len(rows) > bound
                or any(
                    dict(row).get("archive_observation_id") != observation_id
                    for row in rows
                )
            ):
                raise ValueError(f"archive {label} rows are invalid")
        if tuple(dict(row)["source_ordinal"] for row in self.sources) != tuple(
            range(len(self.sources))
        ):
            raise ValueError("archive source ordinals are not contiguous")
        source_rows = tuple(dict(row) for row in self.sources)
        names = tuple(str(row["staging_name"]).casefold() for row in source_rows)
        if (
            not source_rows
            or names.count("archive") != 1
            or len(set(names)) != len(names)
            or _content_fingerprint_from_rows(source_rows)
            != parent.get("archive_content_fingerprint")
            or _volume_fingerprint_from_rows(source_rows)
            != parent.get("volume_group_fingerprint")
        ):
            raise ValueError("archive source material is inconsistent")
        if tuple(dict(row)["member_ordinal"] for row in self.members) != tuple(
            range(len(self.members))
        ) or int(parent.get("member_count", -1)) != len(self.members):
            raise ValueError("archive member rows are not contiguous")
        member_rows = tuple(dict(row) for row in self.members)
        if any(
            row["member_identity"]
            != build_archive_member_identity(
                archive_full_sha256=str(parent["archive_full_sha256"]),
                volume_group_fingerprint=str(parent["volume_group_fingerprint"]),
                member_path_safe=str(row["member_path_safe"]),
                member_ordinal=int(row["member_ordinal"]),
                listing_profile=str(row["listing_profile"]),
            )
            for row in member_rows
        ) or len({row["member_identity"] for row in member_rows}) != len(member_rows):
            raise ValueError("archive member identity is inconsistent")
        wrapper_required = parent.get("recognition_status") == "OUTER_COMPRESSION_ONLY"
        if wrapper_required is not (self.wrapper is not None) or (
            self.wrapper is not None
            and dict(self.wrapper).get("archive_observation_id") != observation_id
        ):
            raise ValueError("archive wrapper row is invalid")
        roles = {str(dict(row)["execution_role"]) for row in self.executions}
        expected_roles = set()
        if parent.get("listing_status") != "NOT_ATTEMPTED":
            expected_roles.add("LISTING")
        if parent.get("integrity_status") != "NOT_TESTED":
            expected_roles.add("INTEGRITY")
        if parent.get("extraction_status") != "NOT_ATTEMPTED":
            expected_roles.add("EXTRACTION")
        if roles != expected_roles:
            raise ValueError("archive execution roles are inconsistent")
        if _content_hash_for_graph(self) != self.content_hash:
            raise ValueError("archive graph content hash is invalid")

    @property
    def id(self) -> EntityId:
        return EntityId.parse(str(dict(self.parent)["id"]))

    @property
    def content_hash(self) -> str:
        return str(dict(self.parent)["content_hash"])


class SQLiteArchiveEvidenceStore:
    """Persist one bounded archive graph under a root-wide writer fence."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._leases = SQLiteScanRootWriteLeaseStore(engine)

    def create_or_get(
        self,
        snapshot: ArchiveEvidenceSnapshot,
        write_lease: OwnedScanRootWriteLease,
        committed_at: datetime,
    ) -> PersistedArchiveEvidence:
        if not isinstance(snapshot, ArchiveEvidenceSnapshot):
            raise ValueError("snapshot must be ArchiveEvidenceSnapshot")
        if not isinstance(write_lease, OwnedScanRootWriteLease):
            raise ValueError("write_lease must be OwnedScanRootWriteLease")
        if (
            write_lease.scan_root_id != snapshot.scan_root_id
            or write_lease.owner_kind not in _WRITER_KINDS
        ):
            raise ArchiveEvidenceStoreError("archive writer lease does not match the snapshot")
        try:
            with self._engine.begin() as connection:
                self._leases.fence(connection, write_lease, committed_at)
                graph = _graph(snapshot, write_lease)
                self._validate_sources(connection, snapshot)
                self._validate_executions(connection, snapshot, write_lease)
                existing = self._read(connection, snapshot.id)
                if existing is not None:
                    if existing != graph:
                        raise ArchiveEvidenceStoreError(
                            "archive observation identity has different immutable content"
                        )
                    self._leases.fence(connection, write_lease, committed_at)
                    return _project_graph(existing)
                collision = connection.execute(
                    select(archive_schema.archive_observations.c.id).where(
                        archive_schema.archive_observations.c.content_hash
                        == graph.content_hash
                    )
                ).scalar_one_or_none()
                if collision is not None:
                    raise ArchiveEvidenceStoreError(
                        "archive content hash collides with another observation"
                    )
                _insert_graph(connection, graph)
                stored = self._read(connection, snapshot.id)
                if stored != graph:
                    raise ArchiveEvidenceStoreError(
                        "persisted archive graph cannot be rehydrated losslessly: "
                        + _graph_difference(graph, stored)
                    )
                self._leases.fence(connection, write_lease, committed_at)
                return _project_graph(graph)
        except ArchiveEvidenceStoreError:
            raise
        except Exception:
            raise ArchiveEvidenceStoreError("archive evidence write failed") from None

    def get_by_id(self, observation_id: EntityId) -> PersistedArchiveEvidence | None:
        if not isinstance(observation_id, EntityId):
            raise ValueError("observation_id must be EntityId")
        with self._engine.connect() as connection:
            graph = self._read(connection, observation_id)
        if graph is not None and _content_hash_for_graph(graph) != graph.content_hash:
            raise ArchiveEvidenceStoreError("persisted archive graph is corrupt")
        return None if graph is None else _project_graph(graph)

    def list_for_source_observation(
        self, file_observation_id: EntityId, limit: int
    ) -> tuple[PersistedArchiveEvidence, ...]:
        if not isinstance(file_observation_id, EntityId):
            raise ValueError("file_observation_id must be EntityId")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("archive evidence limit must be between 1 and 100")
        with self._engine.connect() as connection:
            ids = connection.execute(
                select(archive_schema.archive_observation_sources.c.archive_observation_id)
                .where(
                    archive_schema.archive_observation_sources.c.file_observation_id
                    == str(file_observation_id)
                )
                .order_by(
                    archive_schema.archive_observation_sources.c.archive_observation_id
                )
                .limit(limit + 1)
            ).scalars().all()
            if len(ids) > limit:
                raise ArchiveEvidenceStoreError("archive evidence query exceeds the bound")
            graphs = tuple(
                graph
                for value in ids
                if (graph := self._read(connection, EntityId.parse(str(value)))) is not None
            )
        return tuple(_project_graph(_validated_graph(graph)) for graph in graphs)

    def list_source_dependency_bindings(
        self,
        file_observation_ids: tuple[EntityId, ...],
        scan_root_id: EntityId,
        source_scan_run_id: EntityId,
    ) -> tuple[ArchiveSourceDependencyBinding, ...]:
        """Read canonical archive-source bindings for at most two endpoints."""

        with self._engine.connect() as connection:
            return _read_archive_source_dependency_bindings(
                connection,
                file_observation_ids,
                scan_root_id,
                source_scan_run_id,
            )

    def find_listing_reuse(
        self,
        key: ArchiveReuseKey,
        compatibility: ArchiveEvidenceCompatibility,
        *,
        scan_root_id: EntityId | None = None,
        source_scan_run_id: EntityId | None = None,
        sources: tuple[ArchiveEvidenceSource, ...] | None = None,
    ) -> PersistedArchiveEvidence | None:
        if not isinstance(key, ArchiveReuseKey):
            raise ValueError("key must be ArchiveReuseKey")
        if not isinstance(compatibility, ArchiveEvidenceCompatibility):
            raise ValueError("compatibility must be ArchiveEvidenceCompatibility")
        scoped = (scan_root_id, source_scan_run_id, sources)
        if any(value is None for value in scoped) and not all(
            value is None for value in scoped
        ):
            raise ValueError("archive reuse source scope must be complete")
        if sources is not None and (
            not isinstance(scan_root_id, EntityId)
            or not isinstance(source_scan_run_id, EntityId)
            or not isinstance(sources, tuple)
            or not 1 <= len(sources) <= 256
            or any(not isinstance(value, ArchiveEvidenceSource) for value in sources)
        ):
            raise ValueError("archive reuse source scope is invalid")
        parent = archive_schema.archive_observations
        links = archive_schema.archive_observation_executions
        tools = schema.tool_executions
        statement = (
            select(parent.c.id)
            .join(
                links,
                (links.c.archive_observation_id == parent.c.id)
                & (links.c.execution_role == "LISTING"),
            )
            .join(tools, tools.c.id == links.c.tool_execution_id)
            .where(
                parent.c.archive_full_sha256 == key.archive_full_sha256,
                parent.c.volume_group_fingerprint == key.volume_group_fingerprint,
                parent.c.provider_profile == compatibility.provider_profile,
                parent.c.runner_profile == compatibility.runner_profile,
                parent.c.parser_profile == key.parser_version,
                parent.c.parser_status == compatibility.parser_status.value,
                parent.c.format_case_kind == compatibility.format_case_kind,
                parent.c.format_lock_profile == ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE,
                parent.c.format_lock_sha256 == ARCHIVE_7ZIP_FORMAT_LOCK_SHA256,
                parent.c.signature_profile == compatibility.signature.profile,
                parent.c.compatibility_profile == compatibility.signature.compatibility,
                parent.c.container_class == compatibility.signature.container_class.value,
                parent.c.suffix_kind == compatibility.signature.suffix_kind.value,
                parent.c.publication_kind == compatibility.signature.publication_kind.value,
                parent.c.storage_family == compatibility.signature.storage_family.value,
                parent.c.outer_compression_kind
                == compatibility.signature.outer_compression_kind.value,
                parent.c.recognition_status == compatibility.signature.recognition_status.value,
                parent.c.inspected_bytes == compatibility.signature.inspected_bytes,
                parent.c.structural_confirmation_required
                == compatibility.signature.structural_confirmation_required,
                parent.c.listing_profile == key.listing_profile,
                parent.c.extraction_profile == key.extraction_profile,
                parent.c.safety_profile == key.safety_profile,
                parent.c.secret_version == key.secret_version,
                parent.c.listing_status == "LISTED",
                tools.c.provider_id == key.tool_provider_id,
                tools.c.tool_version == key.tool_version,
                tools.c.adapter_version == key.adapter_version,
                tools.c.capability == "ARCHIVE_LISTING",
                tools.c.config_identity == ARCHIVE_PROVIDER_PROFILE,
                tools.c.status == "SUCCEEDED",
            )
            .order_by(parent.c.observed_at.desc(), parent.c.id.desc())
            .limit(1)
        )
        if compatibility.provider_profile == ARCHIVE_WRAPPER_PROVIDER_PROFILE:
            wrapper = archive_schema.archive_wrapper_lineage
            statement = statement.join(
                wrapper, wrapper.c.archive_observation_id == parent.c.id
            ).where(
                wrapper.c.image_reference == compatibility.wrapper_image_reference,
                wrapper.c.wrapper_command_identity
                == compatibility.wrapper_command_identity,
                wrapper.c.listing_command_identity
                == compatibility.listing_command_identity,
                wrapper.c.integrity_command_identity
                == compatibility.integrity_command_identity,
            )
        if sources is not None:
            assert scan_root_id is not None and source_scan_run_id is not None
            source_rows = archive_schema.archive_observation_sources
            statement = statement.where(
                parent.c.scan_root_id == str(scan_root_id),
                parent.c.source_scan_run_id == str(source_scan_run_id),
                select(func.count())
                .select_from(source_rows)
                .where(source_rows.c.archive_observation_id == parent.c.id)
                .scalar_subquery()
                == len(sources),
            )
            for ordinal, source in enumerate(sources):
                statement = statement.where(
                    select(source_rows.c.archive_observation_id)
                    .where(
                        source_rows.c.archive_observation_id == parent.c.id,
                        source_rows.c.source_ordinal == ordinal,
                        source_rows.c.file_observation_id
                        == str(source.file_observation_id),
                        source_rows.c.source_full_sha256 == source.full_sha256,
                        source_rows.c.source_size_bytes == source.size_bytes,
                        source_rows.c.staging_name == source.staging_name,
                    )
                    .exists()
                )
        with self._engine.connect() as connection:
            value = connection.execute(statement).scalar_one_or_none()
            graph = (
                None
                if value is None
                else self._read(connection, EntityId.parse(str(value)))
            )
        return None if graph is None else _project_graph(_validated_graph(graph))

    def find_member_reuse(
        self,
        key: ArchiveReuseKey,
        compatibility: ArchiveEvidenceCompatibility,
    ) -> PersistedArchiveEvidence | None:
        """Return no v1 member reuse until extraction evidence is authorized."""

        if not isinstance(key, ArchiveReuseKey) or not isinstance(
            compatibility, ArchiveEvidenceCompatibility
        ):
            raise ValueError("member reuse inputs are invalid")
        return None

    def _read(
        self, connection: Connection, observation_id: EntityId
    ) -> _PersistedArchiveEvidenceGraph | None:
        return _read_archive_graph(connection, observation_id)

    def _validate_sources(
        self, connection: Connection, snapshot: ArchiveEvidenceSnapshot
    ) -> None:
        for source in snapshot.sources:
            row = connection.execute(
                select(
                    schema.file_observations.c.scan_run_id,
                    schema.file_observations.c.size_bytes,
                    schema.file_records.c.scan_root_id,
                    schema.file_records.c.presence_state,
                    schema.file_records.c.size_bytes.label("record_size"),
                    schema.scan_runs.c.status,
                    schema.scan_runs.c.scan_root_id.label("run_root"),
                )
                .join(
                    schema.file_records,
                    schema.file_records.c.id == schema.file_observations.c.file_id,
                )
                .join(
                    schema.scan_runs,
                    schema.scan_runs.c.id == schema.file_observations.c.scan_run_id,
                )
                .where(schema.file_observations.c.id == str(source.file_observation_id))
            ).mappings().one_or_none()
            fingerprint = connection.execute(
                select(schema.fingerprints.c.id).where(
                    schema.fingerprints.c.target_kind == "FILE_OBSERVATION",
                    schema.fingerprints.c.target_id == str(source.file_observation_id),
                    schema.fingerprints.c.kind == "FILE_SHA256",
                    schema.fingerprints.c.algorithm == "sha256",
                    schema.fingerprints.c.algorithm_version == "1",
                    schema.fingerprints.c.value == source.full_sha256,
                ).limit(1)
            ).scalar_one_or_none()
            if (
                row is None
                or fingerprint is None
                or str(row["scan_run_id"]) != str(snapshot.source_scan_run_id)
                or str(row["scan_root_id"]) != str(snapshot.scan_root_id)
                or str(row["run_root"]) != str(snapshot.scan_root_id)
                or row["status"] != "COMPLETED"
                or row["presence_state"] != "PRESENT"
                or int(row["size_bytes"]) != source.size_bytes
                or int(row["record_size"]) != source.size_bytes
            ):
                raise ArchiveEvidenceStoreError("archive source lineage is invalid")

    def _validate_executions(
        self,
        connection: Connection,
        snapshot: ArchiveEvidenceSnapshot,
        write_lease: OwnedScanRootWriteLease,
    ) -> None:
        result = snapshot.outcome.result
        assert result is not None
        for execution in snapshot.outcome.executions:
            row = connection.execute(
                select(schema.tool_executions).where(
                    schema.tool_executions.c.id == str(execution.id)
                )
            ).mappings().one_or_none()
            if (
                row is None
                and write_lease.owner_kind
                is ScanRootWriteOwnerKind.ARCHIVE_COLLECTION_RUN
            ):
                connection.execute(
                    insert(schema.tool_executions).values(
                        id=str(execution.id),
                        provider_id=execution.provider_id,
                        tool_version=execution.tool_version,
                        adapter_version=execution.adapter_version,
                        capability=execution.capability.value,
                        input_identity=execution.input_identity,
                        config_identity=execution.config_identity,
                        started_at=datetime_to_db(execution.started_at),
                        finished_at=datetime_to_db(execution.finished_at),
                        status=execution.status.value,
                        exit_code=execution.exit_code,
                        error_summary=execution.error_summary,
                    )
                )
                row = connection.execute(
                    select(schema.tool_executions).where(
                        schema.tool_executions.c.id == str(execution.id)
                    )
                ).mappings().one_or_none()
            if row is None or any(
                row[key] != expected
                for key, expected in (
                    ("provider_id", execution.provider_id),
                    ("tool_version", execution.tool_version),
                    ("adapter_version", execution.adapter_version),
                    ("capability", execution.capability.value),
                    ("input_identity", execution.input_identity),
                    ("config_identity", execution.config_identity),
                    ("started_at", datetime_to_db(execution.started_at)),
                    ("finished_at", datetime_to_db(execution.finished_at)),
                    ("status", execution.status.value),
                    ("exit_code", execution.exit_code),
                    ("error_summary", execution.error_summary),
                )
            ):
                raise ArchiveEvidenceStoreError("archive execution lineage is invalid")


def _graph(
    snapshot: ArchiveEvidenceSnapshot, lease: OwnedScanRootWriteLease
) -> _PersistedArchiveEvidenceGraph:
    handoff = snapshot.outcome._persistence_handoff
    result = snapshot.outcome.result
    assert result is not None
    wrapper_signature = (
        snapshot.signature.recognition_status.value == "OUTER_COMPRESSION_ONLY"
    )
    wrapper = None if handoff is None else handoff.wrapper_listing_run
    provider_profile = (
        ARCHIVE_WRAPPER_PROVIDER_PROFILE if wrapper_signature else ARCHIVE_PROVIDER_PROFILE
    )
    runner_profile = (
        _WRAPPER_RUNNER_PROFILE
        if wrapper_signature
        else ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE
    )
    sources = tuple(
        _row_tuple(
            {
                "archive_observation_id": str(snapshot.id),
                "source_ordinal": ordinal,
                "file_observation_id": str(source.file_observation_id),
                "source_full_sha256": source.full_sha256,
                "source_size_bytes": source.size_bytes,
                "staging_name": source.staging_name,
            }
        )
        for ordinal, source in enumerate(snapshot.sources)
    )
    executions = tuple(
        sorted(
            (
                _row_tuple(
                    {
                        "archive_observation_id": str(snapshot.id),
                        "execution_role": "LISTING" if ordinal == 0 else "INTEGRITY",
                        "tool_execution_id": str(execution.id),
                    }
                )
                for ordinal, execution in enumerate(snapshot.outcome.executions)
            ),
            key=lambda row: str(dict(row)["execution_role"]),
        )
    )
    members = tuple(
        _row_tuple(
            {
                "archive_observation_id": str(snapshot.id),
                "member_ordinal": member.member_ordinal,
                "profile": ARCHIVE_MEMBER_PROFILE,
                "member_identity": member.member_identity,
                "member_path_safe": member.member_path_safe,
                "member_kind": member.member_kind.value,
                "declared_compressed_bytes": member.declared_compressed_bytes,
                "declared_uncompressed_bytes": member.declared_uncompressed_bytes,
                "observed_uncompressed_bytes": None,
                "member_sha256": None,
                "crc_status": member.crc_status.value,
                "encryption_status": member.encryption_status.value,
                "listing_profile": member.listing_profile,
                "extraction_profile": member.extraction_profile,
                "safety_profile": member.safety_profile,
                "secret_version": member.secret_version,
            }
        )
        for member in (() if handoff is None else handoff.listing_result.members)
    )
    wrapper_row = None
    if wrapper_signature:
        reuse = snapshot.outcome._wrapper_reuse_evidence
        has_inner = (
            wrapper is not None
            and wrapper.inner_stream_sha256 is not None
            and wrapper.inner_stream_size_bytes >= 1_024
        )
        wrapper_row = _row_tuple(
            {
                "archive_observation_id": str(snapshot.id),
                "profile": ARCHIVE_WRAPPER_PROVIDER_PROFILE,
                "inner_storage_family": "TAR",
                "inner_stream_size_bytes": wrapper.inner_stream_size_bytes
                if has_inner and wrapper is not None
                else None,
                "inner_stream_sha256": wrapper.inner_stream_sha256
                if has_inner and wrapper is not None
                else None,
                "frame_profile": "archive-tar-stream-frame/v1",
                "wrapper_runner_profile": "archive-wrapper-container-runner/v1",
                "image_reference": (
                    _WRAPPER_IMAGE_REFERENCE
                ),
                "wrapper_command_identity": reuse.wrapper_command_identity
                if reuse is not None
                else _command_identity(build_7zzs_wrapper_decode_command()),
                "listing_command_identity": reuse.listing_command_identity
                if reuse is not None
                else _command_identity(build_7zzs_tar_stdin_listing_command()),
                "integrity_command_identity": reuse.integrity_command_identity
                if reuse is not None
                else _command_identity(build_7zzs_tar_stdin_integrity_command()),
            }
        )
    parent: dict[str, Any] = {
        "id": str(snapshot.id),
        "profile": ARCHIVE_OBSERVATION_PROFILE,
        "content_hash": "",
        "scan_root_id": str(snapshot.scan_root_id),
        "source_scan_run_id": str(snapshot.source_scan_run_id),
        "observed_at": datetime_to_db(snapshot.observed_at),
        "archive_full_sha256": result.reuse_key.archive_full_sha256,
        "archive_content_fingerprint": _archive_content_fingerprint(snapshot.sources),
        "volume_group_fingerprint": result.reuse_key.volume_group_fingerprint,
        "signature_profile": snapshot.signature.profile,
        "compatibility_profile": snapshot.signature.compatibility,
        "container_class": snapshot.signature.container_class.value,
        "suffix_kind": snapshot.signature.suffix_kind.value,
        "publication_kind": snapshot.signature.publication_kind.value,
        "storage_family": snapshot.signature.storage_family.value,
        "outer_compression_kind": snapshot.signature.outer_compression_kind.value,
        "recognition_status": snapshot.signature.recognition_status.value,
        "inspected_bytes": snapshot.signature.inspected_bytes,
        "structural_confirmation_required": snapshot.signature.structural_confirmation_required,
        "provider_profile": provider_profile,
        "runner_profile": runner_profile,
        "parser_profile": ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE,
        "parser_status": None
        if handoff is None
        else handoff.parser_result.public.status.value,
        "format_case_kind": None
        if handoff is None or handoff.parser_result.public.case_kind is None
        else _required_case_value(handoff.parser_result.public.case_kind),
        "format_lock_profile": ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE,
        "format_lock_sha256": ARCHIVE_7ZIP_FORMAT_LOCK_SHA256,
        "listing_profile": ARCHIVE_LISTING_PROFILE,
        "integrity_profile": ARCHIVE_INTEGRITY_PROFILE,
        "extraction_profile": ARCHIVE_EXTRACTION_PROFILE,
        "safety_profile": result.reuse_key.safety_profile,
        "secret_version": NONE_SECRET_VERSION,
        "listing_status": result.listing_status.value,
        "encryption_status": result.encryption_status.value,
        "integrity_status": result.integrity_status.value,
        "extraction_status": "NOT_ATTEMPTED",
        "password_attempt_status": result.password_attempt_status.value,
        "extraction_policy_status": result.extraction_policy_status.value,
        "member_count": len(members),
        "writer_owner_kind": lease.owner_kind.value,
        "writer_owner_run_id": str(lease.owner_run_id),
        "writer_fence_epoch": lease.fence_epoch,
    }
    parent["content_hash"] = _content_hash_material(
        parent, sources, executions, members, wrapper_row
    )
    return _PersistedArchiveEvidenceGraph(
        _row_tuple(parent), sources, executions, members, wrapper_row
    )


def _insert_graph(connection: Connection, graph: _PersistedArchiveEvidenceGraph) -> None:
    connection.execute(insert(archive_schema.archive_observations).values(**dict(graph.parent)))
    for table, rows in (
        (archive_schema.archive_observation_sources, graph.sources),
        (archive_schema.archive_observation_executions, graph.executions),
        (archive_schema.archive_member_observations, graph.members),
    ):
        if rows:
            connection.execute(insert(table), [dict(row) for row in rows])
    if graph.wrapper is not None:
        connection.execute(insert(archive_schema.archive_wrapper_lineage).values(**dict(graph.wrapper)))


def _read_archive_graph(
    connection: Connection, observation_id: EntityId
) -> _PersistedArchiveEvidenceGraph | None:
    parent = connection.execute(
        select(archive_schema.archive_observations).where(
            archive_schema.archive_observations.c.id == str(observation_id)
        )
    ).mappings().one_or_none()
    if parent is None:
        return None
    try:
        return _PersistedArchiveEvidenceGraph(
            _row_tuple(parent),
            _children(
                connection, archive_schema.archive_observation_sources, observation_id
            ),
            _children(
                connection, archive_schema.archive_observation_executions, observation_id
            ),
            _children(
                connection, archive_schema.archive_member_observations, observation_id
            ),
            _optional_child(
                connection, archive_schema.archive_wrapper_lineage, observation_id
            ),
        )
    except (TypeError, ValueError):
        raise ArchiveEvidenceStoreError("persisted archive graph is corrupt") from None


def _read_archive_source_dependency_bindings(
    connection: Connection,
    file_observation_ids: tuple[EntityId, ...],
    scan_root_id: EntityId,
    source_scan_run_id: EntityId,
) -> tuple[ArchiveSourceDependencyBinding, ...]:
    from foliotone.consolidation.archive_dependencies import (
        MAX_ARCHIVE_SOURCE_DEPENDENCY_BINDINGS,
        ArchiveSourceDependencyBinding,
    )

    if (
        not isinstance(file_observation_ids, tuple)
        or not 1 <= len(file_observation_ids) <= 2
        or any(not isinstance(value, EntityId) for value in file_observation_ids)
        or len(set(file_observation_ids)) != len(file_observation_ids)
        or not isinstance(scan_root_id, EntityId)
        or not isinstance(source_scan_run_id, EntityId)
    ):
        raise ValueError("archive dependency query scope is invalid")
    requested = tuple(sorted(str(value) for value in file_observation_ids))
    parent = archive_schema.archive_observations
    source = archive_schema.archive_observation_sources
    observation = schema.file_observations
    record = schema.file_records
    run = schema.scan_runs
    fingerprint_exists = (
        select(schema.fingerprints.c.id)
        .where(
            schema.fingerprints.c.target_kind == "FILE_OBSERVATION",
            schema.fingerprints.c.target_id == source.c.file_observation_id,
            schema.fingerprints.c.kind == "FILE_SHA256",
            schema.fingerprints.c.algorithm == "sha256",
            schema.fingerprints.c.algorithm_version == "1",
            schema.fingerprints.c.value == source.c.source_full_sha256,
        )
        .limit(1)
        .exists()
    )
    scoped_observation_count = connection.execute(
        select(func.count())
        .select_from(
            observation.join(record, record.c.id == observation.c.file_id).join(
                run, run.c.id == observation.c.scan_run_id
            )
        )
        .where(
            observation.c.id.in_(requested),
            observation.c.scan_run_id == str(source_scan_run_id),
            record.c.scan_root_id == str(scan_root_id),
            record.c.presence_state == "PRESENT",
            run.c.scan_root_id == str(scan_root_id),
            run.c.status == "COMPLETED",
        )
    ).scalar_one()
    if int(scoped_observation_count) != len(requested):
        raise ArchiveEvidenceStoreError("archive dependency endpoint lineage is invalid")
    rows = connection.execute(
        select(
            source.c.archive_observation_id,
            source.c.source_ordinal,
            source.c.file_observation_id,
            source.c.source_size_bytes,
            parent.c.scan_root_id.label("archive_root_id"),
            parent.c.source_scan_run_id.label("archive_scan_run_id"),
            observation.c.scan_run_id.label("observation_scan_run_id"),
            observation.c.size_bytes.label("observation_size"),
            record.c.scan_root_id.label("record_root_id"),
            record.c.presence_state,
            record.c.size_bytes.label("record_size"),
            run.c.scan_root_id.label("run_root_id"),
            run.c.status.label("run_status"),
            fingerprint_exists.label("has_full_fingerprint"),
        )
        .select_from(
            source.join(parent, parent.c.id == source.c.archive_observation_id)
            .join(observation, observation.c.id == source.c.file_observation_id)
            .join(record, record.c.id == observation.c.file_id)
            .join(run, run.c.id == observation.c.scan_run_id)
        )
        .where(
            source.c.file_observation_id.in_(requested),
        )
        .order_by(
            source.c.file_observation_id,
            source.c.archive_observation_id,
            source.c.source_ordinal,
        )
        .limit(2 * MAX_ARCHIVE_SOURCE_DEPENDENCY_BINDINGS + 1)
    ).mappings().all()
    if len(rows) > 2 * MAX_ARCHIVE_SOURCE_DEPENDENCY_BINDINGS:
        raise ArchiveEvidenceStoreError("archive dependency query exceeds the bound")
    counts = {value: 0 for value in requested}
    graphs: dict[str, _PersistedArchiveEvidenceGraph] = {}
    bindings: list[ArchiveSourceDependencyBinding] = []
    for row in rows:
        if (
            str(row["archive_root_id"]) != str(scan_root_id)
            or str(row["archive_scan_run_id"]) != str(source_scan_run_id)
            or str(row["observation_scan_run_id"]) != str(source_scan_run_id)
            or str(row["record_root_id"]) != str(scan_root_id)
            or str(row["run_root_id"]) != str(scan_root_id)
            or str(row["presence_state"]) != "PRESENT"
            or str(row["run_status"]) != "COMPLETED"
            or int(row["observation_size"]) != int(row["source_size_bytes"])
            or int(row["record_size"]) != int(row["source_size_bytes"])
            or not bool(row["has_full_fingerprint"])
        ):
            raise ArchiveEvidenceStoreError(
                "archive dependency source lineage is inconsistent"
            )
        file_observation_id = str(row["file_observation_id"])
        counts[file_observation_id] += 1
        if counts[file_observation_id] > MAX_ARCHIVE_SOURCE_DEPENDENCY_BINDINGS:
            raise ArchiveEvidenceStoreError("archive dependency query exceeds the bound")
        observation_id = str(row["archive_observation_id"])
        graph = graphs.get(observation_id)
        if graph is None:
            loaded = _read_archive_graph(connection, EntityId.parse(observation_id))
            if loaded is None:
                raise ArchiveEvidenceStoreError("archive dependency graph is missing")
            graph = _validated_graph(loaded)
            graphs[observation_id] = graph
        material = dict(graph.parent)
        source_row = next(
            (
                dict(value)
                for value in graph.sources
                if int(dict(value)["source_ordinal"]) == int(row["source_ordinal"])
            ),
            None,
        )
        if (
            source_row is None
            or str(source_row["file_observation_id"]) != file_observation_id
        ):
            raise ArchiveEvidenceStoreError("archive dependency source is inconsistent")
        bindings.append(
            ArchiveSourceDependencyBinding(
                archive_observation_id=EntityId.parse(observation_id),
                file_observation_id=EntityId.parse(file_observation_id),
                scan_root_id=EntityId.parse(str(material["scan_root_id"])),
                source_scan_run_id=EntityId.parse(
                    str(material["source_scan_run_id"])
                ),
                source_ordinal=int(row["source_ordinal"]),
                container_class=ArchiveContainerClass(
                    str(material["container_class"])
                ),
                publication_kind=ArchivePublicationKind(
                    str(material["publication_kind"])
                ),
                storage_family=ArchiveStorageFamily(
                    str(material["storage_family"])
                ),
                outer_compression_kind=ArchiveOuterCompressionKind(
                    str(material["outer_compression_kind"])
                ),
                recognition_status=ArchiveRecognitionStatus(
                    str(material["recognition_status"])
                ),
                archive_content_hash=str(material["content_hash"]),
                archive_profile=str(material["profile"]),
            )
        )
    return tuple(bindings)


def _children(
    connection: Connection, table: Any, observation_id: EntityId
) -> tuple[tuple[tuple[str, Any], ...], ...]:
    rows = connection.execute(
        select(table)
        .where(table.c.archive_observation_id == str(observation_id))
        .order_by(*tuple(table.primary_key.columns))
        .limit(10_001)
    ).mappings().all()
    return tuple(_row_tuple(row) for row in rows)


def _optional_child(
    connection: Connection, table: Any, observation_id: EntityId
) -> tuple[tuple[str, Any], ...] | None:
    row = connection.execute(
        select(table).where(table.c.archive_observation_id == str(observation_id)).limit(2)
    ).mappings().one_or_none()
    return None if row is None else _row_tuple(row)


def _content_hash_for_graph(graph: _PersistedArchiveEvidenceGraph) -> str:
    return _content_hash_material(
        dict(graph.parent),
        graph.sources,
        graph.executions,
        graph.members,
        graph.wrapper,
    )


def _content_hash_material(
    parent: dict[str, Any],
    sources: tuple[tuple[tuple[str, Any], ...], ...],
    executions: tuple[tuple[tuple[str, Any], ...], ...],
    members: tuple[tuple[tuple[str, Any], ...], ...],
    wrapper: tuple[tuple[str, Any], ...] | None,
) -> str:
    parent = dict(parent)
    parent.pop("content_hash", None)
    material = {
        "parent": parent,
        "sources": [dict(row) for row in sources],
        "executions": [dict(row) for row in executions],
        "members": [dict(row) for row in members],
        "wrapper": None if wrapper is None else dict(wrapper),
    }
    return hashlib.sha256(_canonical_json(material)).hexdigest()


def _validated_graph(graph: _PersistedArchiveEvidenceGraph) -> _PersistedArchiveEvidenceGraph:
    if _content_hash_for_graph(graph) != graph.content_hash:
        raise ArchiveEvidenceStoreError("persisted archive graph is corrupt")
    return graph


def _project_graph(graph: _PersistedArchiveEvidenceGraph) -> PersistedArchiveEvidence:
    graph = _validated_graph(graph)
    parent = dict(graph.parent)
    return PersistedArchiveEvidence(
        EntityId.parse(str(parent["id"])),
        str(parent["content_hash"]),
        EntityId.parse(str(parent["scan_root_id"])),
        EntityId.parse(str(parent["source_scan_run_id"])),
        datetime.fromisoformat(str(parent["observed_at"])),
        str(parent["listing_status"]),
        str(parent["integrity_status"]),
        str(parent["extraction_status"]),
        int(parent["member_count"]),
        len(graph.sources),
        len(graph.executions),
        graph.wrapper is not None,
    )


def _archive_content_fingerprint(sources: tuple[ArchiveEvidenceSource, ...]) -> str:
    material = [
        {
            "file_observation_id": str(source.file_observation_id),
            "source_full_sha256": source.full_sha256,
        }
        for source in sources
    ]
    return hashlib.sha256(
        ARCHIVE_CONTENT_FINGERPRINT_DOMAIN + _canonical_json(material)
    ).hexdigest()


def _content_fingerprint_from_rows(rows: tuple[dict[str, Any], ...]) -> str:
    material = [
        {
            "file_observation_id": str(row["file_observation_id"]),
            "source_full_sha256": str(row["source_full_sha256"]),
        }
        for row in rows
    ]
    return hashlib.sha256(
        ARCHIVE_CONTENT_FINGERPRINT_DOMAIN + _canonical_json(material)
    ).hexdigest()


def _volume_group_fingerprint(sources: tuple[ArchiveEvidenceSource, ...]) -> str:
    material = [
        {
            "full_sha256": source.full_sha256,
            "size_bytes": source.size_bytes,
            "staging_name": source.staging_name,
        }
        for source in sources
    ]
    return hashlib.sha256(ARCHIVE_VOLUME_GROUP_DOMAIN + _canonical_json(material)).hexdigest()


def _volume_fingerprint_from_rows(rows: tuple[dict[str, Any], ...]) -> str:
    material = [
        {
            "full_sha256": str(row["source_full_sha256"]),
            "size_bytes": int(row["source_size_bytes"]),
            "staging_name": str(row["staging_name"]),
        }
        for row in rows
    ]
    return hashlib.sha256(ARCHIVE_VOLUME_GROUP_DOMAIN + _canonical_json(material)).hexdigest()


def _required_case_value(value: Any) -> str:
    if value is None:
        raise ArchiveEvidenceStoreError("listed archive parser case is missing")
    return str(value.value)


def _canonical_json(material: object) -> bytes:
    normalized = unicodedata.normalize(
        "NFC", json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return normalized.encode("utf-8")


def _row_tuple(row: Any) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted(((str(key), value) for key, value in dict(row).items())))


def _require_sha256(value: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("archive digest must be lowercase SHA-256")


def _graph_difference(
    expected: _PersistedArchiveEvidenceGraph,
    actual: _PersistedArchiveEvidenceGraph | None,
) -> str:
    if actual is None:
        return "parent"
    for name in ("parent", "sources", "executions", "members", "wrapper"):
        if getattr(expected, name) != getattr(actual, name):
            return name
    return "unknown"
