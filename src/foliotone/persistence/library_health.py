"""Immutable persistence and bounded projection building for Library Health v1."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field

from sqlalchemy import and_, func, insert, or_, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from foliotone.collection_state.contracts import (
    CollectionStateItemState,
    CollectionStateSnapshot,
    sha256_digest,
)
from foliotone.collection_state.health import (
    LIBRARY_HEALTH_DIMENSION_ORDER,
    LIBRARY_HEALTH_FINDING_ORDER,
    LIBRARY_HEALTH_PROFILE,
    LIBRARY_HEALTH_SERIALIZER,
    MAX_LIBRARY_HEALTH_SAMPLES_PER_FINDING,
    LibraryHealthCoverageState,
    LibraryHealthDimension,
    LibraryHealthDimensionsHasher,
    LibraryHealthDimensionSummary,
    LibraryHealthEvidenceCategory,
    LibraryHealthFinding,
    LibraryHealthFindingCode,
    LibraryHealthItemFacts,
    LibraryHealthSample,
    LibraryHealthSeverity,
    LibraryHealthSnapshot,
    LibraryHealthStatus,
    evaluate_library_health_item,
    library_health_coverage_state,
    library_health_finding_definition,
    library_health_snapshot_id,
    library_health_status,
)
from foliotone.collection_state.query import CollectionQueryValueKind
from foliotone.core.ids import EntityId
from foliotone.persistence import archive_schema, calibre_library_schema, schema
from foliotone.persistence._mapping import datetime_to_db, required_datetime_from_db
from foliotone.persistence.collection_query import CollectionQueryIndexSummary
from foliotone.persistence.collection_query_schema import (
    collection_query_documents,
    collection_query_values,
)
from foliotone.persistence.library_health_schema import (
    library_health_dimensions,
    library_health_findings,
    library_health_samples,
    library_health_snapshots,
)
from foliotone.persistence.resolution_review_schema import review_items


class LibraryHealthStoreError(RuntimeError):
    """The immutable Library Health projection is unavailable or inconsistent."""


@dataclass(frozen=True, slots=True)
class LibraryHealthBuildResult:
    snapshot: LibraryHealthSnapshot
    created: bool


@dataclass(slots=True)
class _FindingAccumulator:
    item_count: int = 0
    samples: list[tuple[EntityId, EntityId]] = field(default_factory=list)

    def add(self, file_id: EntityId, observation_id: EntityId) -> None:
        self.item_count += 1
        if len(self.samples) < MAX_LIBRARY_HEALTH_SAMPLES_PER_FINDING:
            self.samples.append((file_id, observation_id))


@dataclass(slots=True)
class _DimensionAccumulator:
    covered_item_count: int = 0
    affected_item_count: int = 0


_DIMENSION_CATEGORIES: dict[LibraryHealthDimension, tuple[LibraryHealthEvidenceCategory, ...]] = {
    LibraryHealthDimension.SCAN_FIXITY: (
        LibraryHealthEvidenceCategory.COLLECTION_STATE,
        LibraryHealthEvidenceCategory.FIXITY_FINGERPRINT,
    ),
    LibraryHealthDimension.ANALYSIS_TOOL_COVERAGE: (
        LibraryHealthEvidenceCategory.COLLECTION_STATE,
        LibraryHealthEvidenceCategory.TOOL_ANALYSIS,
    ),
    LibraryHealthDimension.METADATA_AUTHORITY_CLASSIFICATION: (
        LibraryHealthEvidenceCategory.COLLECTION_STATE,
        LibraryHealthEvidenceCategory.METADATA_CANDIDATE,
        LibraryHealthEvidenceCategory.AUTHORITY_RESOLUTION,
        LibraryHealthEvidenceCategory.CLASSIFICATION,
    ),
    LibraryHealthDimension.OPEN_REVIEWS: (
        LibraryHealthEvidenceCategory.COLLECTION_STATE,
        LibraryHealthEvidenceCategory.REVIEW_QUEUE,
    ),
    LibraryHealthDimension.DUPLICATE_VARIANT_EVIDENCE: (
        LibraryHealthEvidenceCategory.COLLECTION_STATE,
        LibraryHealthEvidenceCategory.MATCHING,
    ),
    LibraryHealthDimension.DEPENDENCIES: (
        LibraryHealthEvidenceCategory.COLLECTION_STATE,
        LibraryHealthEvidenceCategory.CALIBRE,
        LibraryHealthEvidenceCategory.SIDECAR,
        LibraryHealthEvidenceCategory.ARCHIVE,
    ),
    LibraryHealthDimension.BLOCKED_OPERATIONS: (
        LibraryHealthEvidenceCategory.COLLECTION_STATE,
        LibraryHealthEvidenceCategory.CONSOLIDATION,
        LibraryHealthEvidenceCategory.QUARANTINE,
    ),
}


class SQLiteLibraryHealthStore:
    """Build and verify Library Health without reading source media."""

    def __init__(self, engine: Engine, *, batch_size: int = 250) -> None:
        if isinstance(batch_size, bool) or not 1 <= batch_size <= 1000:
            raise ValueError("Library Health batch_size must be between 1 and 1000")
        self._engine = engine
        self._batch_size = batch_size

    def ensure_for_snapshot(
        self,
        connection: Connection,
        snapshot: CollectionStateSnapshot,
        query_index: CollectionQueryIndexSummary,
    ) -> LibraryHealthBuildResult:
        """Create or verify the projection inside the caller's transaction."""

        if query_index.snapshot_id != snapshot.id or (
            query_index.document_count != snapshot.item_count
        ):
            raise ValueError("Library Health inputs do not describe the same snapshot")
        try:
            existing = self._read_for_collection_state(connection, snapshot.id)
            if existing is not None:
                if (
                    existing.collection_state_content_digest != snapshot.content_digest
                    or existing.query_index_content_digest != query_index.content_digest
                ):
                    raise LibraryHealthStoreError("Library Health input binding is inconsistent")
                return LibraryHealthBuildResult(existing, False)
            projected = self._build_projection(connection, snapshot, query_index)
            self._insert(connection, projected)
            repeated = self._read_for_collection_state(connection, snapshot.id)
            if repeated != projected:
                raise LibraryHealthStoreError("Library Health persistence verification failed")
            return LibraryHealthBuildResult(projected, True)
        except LibraryHealthStoreError:
            raise
        except (IntegrityError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise LibraryHealthStoreError("Library Health persistence failed") from error

    def get_for_collection_state(self, snapshot_id: EntityId) -> LibraryHealthSnapshot | None:
        if not isinstance(snapshot_id, EntityId):
            raise ValueError("CollectionState snapshot ID is invalid")
        try:
            with self._engine.connect() as connection:
                return self._read_for_collection_state(connection, snapshot_id)
        except LibraryHealthStoreError:
            raise
        except (IntegrityError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise LibraryHealthStoreError("Library Health read failed") from error

    def _build_projection(
        self,
        connection: Connection,
        snapshot: CollectionStateSnapshot,
        query_index: CollectionQueryIndexSummary,
    ) -> LibraryHealthSnapshot:
        findings = {code: _FindingAccumulator() for code in LIBRARY_HEALTH_FINDING_ORDER}
        dimensions = {
            dimension: _DimensionAccumulator() for dimension in LIBRARY_HEALTH_DIMENSION_ORDER
        }
        item_count = 0
        previous_file_id: str | None = None
        for facts in self._iter_item_facts(connection, snapshot):
            encoded_file_id = str(facts.file_id)
            if previous_file_id is not None and encoded_file_id <= previous_file_id:
                raise LibraryHealthStoreError("Library Health source items are not ordered")
            previous_file_id = encoded_file_id
            evaluation = evaluate_library_health_item(facts)
            for dimension in evaluation.covered_dimensions:
                dimensions[dimension].covered_item_count += 1
            affected_dimensions: set[LibraryHealthDimension] = set()
            for code in evaluation.finding_codes:
                findings[code].add(facts.file_id, facts.observation_id)
                affected_dimensions.add(library_health_finding_definition(code).dimension)
            for dimension in affected_dimensions:
                dimensions[dimension].affected_item_count += 1
            item_count += 1
        if item_count != snapshot.item_count:
            raise LibraryHealthStoreError("Library Health source item count is inconsistent")

        summaries: list[LibraryHealthDimensionSummary] = []
        for dimension_ordinal, dimension in enumerate(LIBRARY_HEALTH_DIMENSION_ORDER):
            projected_findings: list[LibraryHealthFinding] = []
            for code in LIBRARY_HEALTH_FINDING_ORDER:
                definition = library_health_finding_definition(code)
                accumulator = findings[code]
                if definition.dimension is not dimension or accumulator.item_count == 0:
                    continue
                samples = tuple(
                    LibraryHealthSample(ordinal, file_id, observation_id)
                    for ordinal, (file_id, observation_id) in enumerate(accumulator.samples)
                )
                projected_findings.append(
                    LibraryHealthFinding(
                        ordinal=len(projected_findings),
                        code=code,
                        dimension=dimension,
                        severity=definition.severity,
                        evidence_categories=definition.evidence_categories,
                        item_count=accumulator.item_count,
                        samples=samples,
                    )
                )
            dimension_accumulator = dimensions[dimension]
            summaries.append(
                LibraryHealthDimensionSummary(
                    ordinal=dimension_ordinal,
                    dimension=dimension,
                    status=library_health_status(
                        tuple(finding.severity for finding in projected_findings)
                    ),
                    coverage_state=library_health_coverage_state(
                        item_count, dimension_accumulator.covered_item_count
                    ),
                    assessed_item_count=item_count,
                    covered_item_count=dimension_accumulator.covered_item_count,
                    affected_item_count=dimension_accumulator.affected_item_count,
                    evidence_categories=_DIMENSION_CATEGORIES[dimension],
                    findings=tuple(projected_findings),
                )
            )

        material = {
            "profile": LIBRARY_HEALTH_PROFILE,
            "serializer": LIBRARY_HEALTH_SERIALIZER,
            "collection_state_snapshot_id": str(snapshot.id),
            "scan_root_id": str(snapshot.scan_root_id),
            "source_scan_run_id": str(snapshot.source_scan_run_id),
            "item_count": item_count,
            "collection_state_content_digest": snapshot.content_digest,
            "query_index_content_digest": query_index.content_digest,
            "dimensions": [summary.canonical_payload() for summary in summaries],
        }
        content_digest = sha256_digest(material)
        return LibraryHealthSnapshot(
            id=library_health_snapshot_id(content_digest),
            collection_state_snapshot_id=snapshot.id,
            scan_root_id=snapshot.scan_root_id,
            source_scan_run_id=snapshot.source_scan_run_id,
            created_at=snapshot.created_at,
            item_count=item_count,
            collection_state_content_digest=snapshot.content_digest,
            query_index_content_digest=query_index.content_digest,
            dimensions=tuple(summaries),
            content_digest=content_digest,
        )

    def _iter_item_facts(
        self, connection: Connection, snapshot: CollectionStateSnapshot
    ) -> Iterator[LibraryHealthItemFacts]:
        after_ordinal = -1
        expected_ordinal = 0
        while True:
            rows = (
                connection.execute(
                    select(collection_query_documents)
                    .where(
                        collection_query_documents.c.snapshot_id == str(snapshot.id),
                        collection_query_documents.c.ordinal > after_ordinal,
                    )
                    .order_by(collection_query_documents.c.ordinal)
                    .limit(self._batch_size)
                )
                .mappings()
                .all()
            )
            if not rows:
                break
            ordinals = tuple(int(row["ordinal"]) for row in rows)
            if ordinals[0] != expected_ordinal:
                raise LibraryHealthStoreError("Library Health query documents are incomplete")
            file_ids = tuple(str(row["file_id"]) for row in rows)
            observation_ids = tuple(str(row["observation_id"]) for row in rows)
            metadata_fields, analysis_findings = _load_query_value_presence(
                connection, snapshot.id, ordinals
            )
            full_fixity_counts = _load_full_fixity_counts(connection, observation_ids)
            review_states = _load_review_states(connection, file_ids, observation_ids)
            sidecar_dependencies = _load_sidecar_dependencies(
                connection, snapshot.source_scan_run_id, observation_ids
            )
            for row in rows:
                ordinal = int(row["ordinal"])
                if ordinal != expected_ordinal:
                    raise LibraryHealthStoreError(
                        "Library Health query documents are not contiguous"
                    )
                file_id = str(row["file_id"])
                observation_id = str(row["observation_id"])
                yield LibraryHealthItemFacts(
                    file_id=EntityId.parse(file_id),
                    observation_id=EntityId.parse(observation_id),
                    full_fixity_value_count=full_fixity_counts.get(observation_id, 0),
                    analysis_state=CollectionStateItemState(str(row["analysis_state"])),
                    resolution_state=CollectionStateItemState(str(row["resolution_state"])),
                    classification_state=CollectionStateItemState(str(row["classification_state"])),
                    matching_state=CollectionStateItemState(str(row["matching_state"])),
                    calibre_state=CollectionStateItemState(str(row["calibre_state"])),
                    archive_state=CollectionStateItemState(str(row["archive_state"])),
                    consolidation_state=CollectionStateItemState(str(row["consolidation_state"])),
                    quarantine_state=CollectionStateItemState(str(row["quarantine_state"])),
                    metadata_fields=tuple(sorted(metadata_fields.get(ordinal, set()))),
                    metadata_index_truncated=int(row["truncated_value_count"]) > 0,
                    analysis_finding_present=ordinal in analysis_findings,
                    review_states=tuple(sorted(review_states.get(file_id, set()))),
                    sidecar_dependency_present=observation_id in sidecar_dependencies,
                )
                expected_ordinal += 1
            after_ordinal = ordinals[-1]

    def _insert(self, connection: Connection, snapshot: LibraryHealthSnapshot) -> None:
        hasher = LibraryHealthDimensionsHasher()
        for dimension in snapshot.dimensions:
            hasher.update(dimension)
        connection.execute(
            insert(library_health_snapshots),
            {
                "id": str(snapshot.id),
                "collection_state_snapshot_id": str(snapshot.collection_state_snapshot_id),
                "profile": snapshot.profile,
                "serializer": snapshot.serializer,
                "scan_root_id": str(snapshot.scan_root_id),
                "source_scan_run_id": str(snapshot.source_scan_run_id),
                "created_at": datetime_to_db(snapshot.created_at),
                "item_count": snapshot.item_count,
                "dimension_count": len(snapshot.dimensions),
                "finding_count": snapshot.finding_count,
                "sample_count": snapshot.sample_count,
                "collection_state_content_digest": snapshot.collection_state_content_digest,
                "query_index_content_digest": snapshot.query_index_content_digest,
                "dimensions_digest": hasher.hexdigest(),
                "content_digest": snapshot.content_digest,
            },
        )
        for dimension in snapshot.dimensions:
            connection.execute(
                insert(library_health_dimensions),
                {
                    "snapshot_id": str(snapshot.id),
                    "ordinal": dimension.ordinal,
                    "dimension": dimension.dimension.value,
                    "status": dimension.status.value,
                    "coverage_state": dimension.coverage_state.value,
                    "assessed_item_count": dimension.assessed_item_count,
                    "covered_item_count": dimension.covered_item_count,
                    "affected_item_count": dimension.affected_item_count,
                    "finding_count": len(dimension.findings),
                    "evidence_categories_json": _categories_json(dimension.evidence_categories),
                    "dimension_digest": dimension.dimension_digest,
                },
            )
            for finding in dimension.findings:
                connection.execute(
                    insert(library_health_findings),
                    {
                        "snapshot_id": str(snapshot.id),
                        "dimension_ordinal": dimension.ordinal,
                        "ordinal": finding.ordinal,
                        "code": finding.code.value,
                        "severity": finding.severity.value,
                        "item_count": finding.item_count,
                        "sample_count": len(finding.samples),
                        "evidence_categories_json": _categories_json(finding.evidence_categories),
                        "finding_digest": finding.finding_digest,
                    },
                )
                if finding.samples:
                    connection.execute(
                        insert(library_health_samples),
                        [
                            {
                                "snapshot_id": str(snapshot.id),
                                "dimension_ordinal": dimension.ordinal,
                                "finding_ordinal": finding.ordinal,
                                "ordinal": sample.ordinal,
                                "file_id": str(sample.file_id),
                                "observation_id": str(sample.observation_id),
                                "sample_digest": sample.sample_digest,
                            }
                            for sample in finding.samples
                        ],
                    )

    @staticmethod
    def _read_for_collection_state(
        connection: Connection, collection_state_snapshot_id: EntityId
    ) -> LibraryHealthSnapshot | None:
        parent = (
            connection.execute(
                select(library_health_snapshots).where(
                    library_health_snapshots.c.collection_state_snapshot_id
                    == str(collection_state_snapshot_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if parent is None:
            return None
        health_id = str(parent["id"])
        dimension_rows = (
            connection.execute(
                select(library_health_dimensions)
                .where(library_health_dimensions.c.snapshot_id == health_id)
                .order_by(library_health_dimensions.c.ordinal)
            )
            .mappings()
            .all()
        )
        finding_rows = (
            connection.execute(
                select(library_health_findings)
                .where(library_health_findings.c.snapshot_id == health_id)
                .order_by(
                    library_health_findings.c.dimension_ordinal,
                    library_health_findings.c.ordinal,
                )
            )
            .mappings()
            .all()
        )
        sample_rows = (
            connection.execute(
                select(library_health_samples)
                .where(library_health_samples.c.snapshot_id == health_id)
                .order_by(
                    library_health_samples.c.dimension_ordinal,
                    library_health_samples.c.finding_ordinal,
                    library_health_samples.c.ordinal,
                )
            )
            .mappings()
            .all()
        )
        samples_by_finding: dict[tuple[int, int], list[LibraryHealthSample]] = defaultdict(list)
        for row in sample_rows:
            key = (int(row["dimension_ordinal"]), int(row["finding_ordinal"]))
            samples_by_finding[key].append(
                LibraryHealthSample(
                    ordinal=int(row["ordinal"]),
                    file_id=EntityId.parse(str(row["file_id"])),
                    observation_id=EntityId.parse(str(row["observation_id"])),
                    sample_digest=str(row["sample_digest"]),
                )
            )
        findings_by_dimension: dict[int, list[LibraryHealthFinding]] = defaultdict(list)
        for row in finding_rows:
            dimension_ordinal = int(row["dimension_ordinal"])
            finding_ordinal = int(row["ordinal"])
            findings_by_dimension[dimension_ordinal].append(
                LibraryHealthFinding(
                    ordinal=finding_ordinal,
                    code=LibraryHealthFindingCode(str(row["code"])),
                    dimension=LibraryHealthDimension(
                        LIBRARY_HEALTH_DIMENSION_ORDER[dimension_ordinal]
                    ),
                    severity=LibraryHealthSeverity(str(row["severity"])),
                    evidence_categories=_categories_from_json(str(row["evidence_categories_json"])),
                    item_count=int(row["item_count"]),
                    samples=tuple(samples_by_finding[(dimension_ordinal, finding_ordinal)]),
                    finding_digest=str(row["finding_digest"]),
                )
            )
            if int(row["sample_count"]) != len(
                samples_by_finding[(dimension_ordinal, finding_ordinal)]
            ):
                raise LibraryHealthStoreError("Library Health sample rows are incomplete")
        dimensions: list[LibraryHealthDimensionSummary] = []
        for row in dimension_rows:
            ordinal = int(row["ordinal"])
            finding_values = tuple(findings_by_dimension[ordinal])
            if int(row["finding_count"]) != len(finding_values):
                raise LibraryHealthStoreError("Library Health finding rows are incomplete")
            dimensions.append(
                LibraryHealthDimensionSummary(
                    ordinal=ordinal,
                    dimension=LibraryHealthDimension(str(row["dimension"])),
                    status=LibraryHealthStatus(str(row["status"])),
                    coverage_state=LibraryHealthCoverageState(str(row["coverage_state"])),
                    assessed_item_count=int(row["assessed_item_count"]),
                    covered_item_count=int(row["covered_item_count"]),
                    affected_item_count=int(row["affected_item_count"]),
                    evidence_categories=_categories_from_json(str(row["evidence_categories_json"])),
                    findings=finding_values,
                    dimension_digest=str(row["dimension_digest"]),
                )
            )
        snapshot = LibraryHealthSnapshot(
            id=EntityId.parse(health_id),
            collection_state_snapshot_id=EntityId.parse(
                str(parent["collection_state_snapshot_id"])
            ),
            scan_root_id=EntityId.parse(str(parent["scan_root_id"])),
            source_scan_run_id=EntityId.parse(str(parent["source_scan_run_id"])),
            created_at=required_datetime_from_db(str(parent["created_at"])),
            item_count=int(parent["item_count"]),
            collection_state_content_digest=str(parent["collection_state_content_digest"]),
            query_index_content_digest=str(parent["query_index_content_digest"]),
            dimensions=tuple(dimensions),
            content_digest=str(parent["content_digest"]),
            profile=str(parent["profile"]),
            serializer=str(parent["serializer"]),
        )
        hasher = LibraryHealthDimensionsHasher()
        for dimension in snapshot.dimensions:
            hasher.update(dimension)
        if (
            len(dimension_rows) != int(parent["dimension_count"])
            or len(finding_rows) != int(parent["finding_count"])
            or len(sample_rows) != int(parent["sample_count"])
            or hasher.hexdigest() != str(parent["dimensions_digest"])
        ):
            raise LibraryHealthStoreError("Library Health rows are incomplete")
        return snapshot


def _load_query_value_presence(
    connection: Connection,
    snapshot_id: EntityId,
    document_ordinals: tuple[int, ...],
) -> tuple[dict[int, set[str]], set[int]]:
    metadata: dict[int, set[str]] = defaultdict(set)
    findings: set[int] = set()
    rows = connection.execute(
        select(
            collection_query_values.c.document_ordinal,
            collection_query_values.c.field_name,
            collection_query_values.c.value_kind,
        ).where(
            collection_query_values.c.snapshot_id == str(snapshot_id),
            collection_query_values.c.document_ordinal.in_(document_ordinals),
            collection_query_values.c.value_kind.in_(
                (
                    CollectionQueryValueKind.METADATA_CANDIDATE.value,
                    CollectionQueryValueKind.FINDING_CODE.value,
                )
            ),
        )
    ).mappings()
    for row in rows:
        ordinal = int(row["document_ordinal"])
        if str(row["value_kind"]) == CollectionQueryValueKind.METADATA_CANDIDATE.value:
            metadata[ordinal].add(str(row["field_name"]))
        else:
            findings.add(ordinal)
    return metadata, findings


def _load_full_fixity_counts(
    connection: Connection, observation_ids: tuple[str, ...]
) -> dict[str, int]:
    rows = connection.execute(
        select(
            schema.fingerprints.c.target_id,
            func.count(func.distinct(schema.fingerprints.c.value)).label("value_count"),
        )
        .where(
            schema.fingerprints.c.target_kind == "FILE_OBSERVATION",
            schema.fingerprints.c.target_id.in_(observation_ids),
            schema.fingerprints.c.kind == "FILE_SHA256",
            schema.fingerprints.c.algorithm == "sha256",
            schema.fingerprints.c.algorithm_version == "1",
        )
        .group_by(schema.fingerprints.c.target_id)
    ).mappings()
    return {str(row["target_id"]): int(row["value_count"]) for row in rows}


def _load_review_states(
    connection: Connection,
    file_ids: tuple[str, ...],
    observation_ids: tuple[str, ...],
) -> dict[str, set[str]]:
    observation_to_file = dict(zip(observation_ids, file_ids, strict=True))
    states: dict[str, set[str]] = defaultdict(set)
    rows = connection.execute(
        select(
            review_items.c.subject_kind,
            review_items.c.subject_id,
            review_items.c.state,
        ).where(
            review_items.c.state.in_(("PENDING", "DEFERRED")),
            or_(
                and_(
                    review_items.c.subject_kind == "FILE",
                    review_items.c.subject_id.in_(file_ids),
                ),
                and_(
                    review_items.c.subject_kind == "FILE_OBSERVATION",
                    review_items.c.subject_id.in_(observation_ids),
                ),
            ),
        )
    ).mappings()
    for row in rows:
        subject_id = str(row["subject_id"])
        file_id = (
            subject_id if str(row["subject_kind"]) == "FILE" else observation_to_file[subject_id]
        )
        states[file_id].add(str(row["state"]))
    return states


def _load_sidecar_dependencies(
    connection: Connection,
    source_scan_run_id: EntityId,
    observation_ids: tuple[str, ...],
) -> set[str]:
    dependencies = {
        str(value)
        for value in connection.execute(
            select(calibre_library_schema.calibre_library_sidecars.c.observation_id).where(
                calibre_library_schema.calibre_library_sidecars.c.observation_id.in_(
                    observation_ids
                )
            )
        ).scalars()
        if value is not None
    }
    dependencies.update(
        str(value)
        for value in connection.execute(
            select(calibre_library_schema.calibre_reconciliation_finding_refs.c.ref_id)
            .select_from(
                calibre_library_schema.calibre_reconciliation_finding_refs.join(
                    calibre_library_schema.calibre_reconciliation_findings,
                    calibre_library_schema.calibre_reconciliation_finding_refs.c.finding_id
                    == calibre_library_schema.calibre_reconciliation_findings.c.id,
                ).join(
                    calibre_library_schema.calibre_library_snapshots,
                    calibre_library_schema.calibre_reconciliation_findings.c.snapshot_id
                    == calibre_library_schema.calibre_library_snapshots.c.id,
                )
            )
            .where(
                calibre_library_schema.calibre_library_snapshots.c.source_scan_run_id
                == str(source_scan_run_id),
                calibre_library_schema.calibre_library_snapshots.c.status == "COMPLETED",
                calibre_library_schema.calibre_reconciliation_findings.c.code
                == "CALIBRE_SIDECAR_DEPENDENCY",
                calibre_library_schema.calibre_reconciliation_finding_refs.c.ref_kind
                == "FILE_OBSERVATION",
                calibre_library_schema.calibre_reconciliation_finding_refs.c.ref_id.in_(
                    observation_ids
                ),
            )
        ).scalars()
    )
    inventories = archive_schema.archive_sidecar_inventories
    inventory_items = archive_schema.archive_sidecar_inventory_items
    dependencies.update(
        str(value)
        for value in connection.execute(
            select(inventories.c.archive_file_observation_id).where(
                inventories.c.source_scan_run_id == str(source_scan_run_id),
                inventories.c.archive_file_observation_id.in_(observation_ids),
            )
        ).scalars()
    )
    dependencies.update(
        str(value)
        for value in connection.execute(
            select(inventory_items.c.sidecar_file_observation_id)
            .select_from(
                inventory_items.join(
                    inventories, inventory_items.c.inventory_id == inventories.c.id
                )
            )
            .where(
                inventories.c.source_scan_run_id == str(source_scan_run_id),
                inventory_items.c.sidecar_file_observation_id.in_(observation_ids),
            )
        ).scalars()
    )
    return dependencies


def _categories_json(categories: tuple[LibraryHealthEvidenceCategory, ...]) -> str:
    return json.dumps([value.value for value in categories], separators=(",", ":"))


def _categories_from_json(value: str) -> tuple[LibraryHealthEvidenceCategory, ...]:
    raw = json.loads(value)
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise LibraryHealthStoreError("Library Health evidence categories are invalid")
    return tuple(LibraryHealthEvidenceCategory(item) for item in raw)
