"""Deterministic private JSON/CSV reports for persisted e-book collection runs."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from foliotone.core import EntityId
from foliotone.persistence import (
    EbookCollectionCandidateSet,
    EbookCollectionReportSnapshot,
    EbookInventoryDuplicateSet,
    EbookInventoryFormatAggregate,
    EbookInventoryReportSnapshot,
    SQLiteEbookCollectionReportStore,
    SQLiteEbookInventoryReportStore,
)
from foliotone.tooling.structured import JsonValue

EBOOK_COLLECTION_REPORT_PROFILE = "ebook-collection-report/v1"
EBOOK_INVENTORY_REPORT_PROFILE = "ebook-inventory-report/v1"
DEFAULT_COLLECTION_REPORT_REVIEW_LIMIT = 10_000
DEFAULT_COLLECTION_REPORT_GROUP_LIMIT = 1_000
DEFAULT_COLLECTION_REPORT_MEMBER_LIMIT = 100
MAX_COLLECTION_REPORT_REVIEW_LIMIT = 100_000
MAX_COLLECTION_REPORT_GROUP_LIMIT = 10_000
MAX_COLLECTION_REPORT_MEMBER_LIMIT = 1_000

_REPORT_JSON = "collection-report.json"
_REVIEW_CSV = "review-items.csv"
_DUPLICATE_CSV = "exact-duplicates.csv"
_VARIANT_CSV = "content-variants.csv"
_CHECKSUMS = "checksums.sha256"
_INVENTORY_REPORT_JSON = "inventory-report.json"
_INVENTORY_DUPLICATE_CSV = "exact-duplicates.csv"


class EbookCollectionReportError(RuntimeError):
    """A private report cannot be generated or persisted safely."""


class EbookInventoryReportError(RuntimeError):
    """A private inventory report cannot be generated or persisted safely."""


class EbookInventoryReportMissingError(EbookInventoryReportError):
    """An expected private inventory report has not been persisted yet."""


@dataclass(frozen=True, slots=True)
class EbookCollectionReportLimits:
    review_items: int = DEFAULT_COLLECTION_REPORT_REVIEW_LIMIT
    candidate_groups: int = DEFAULT_COLLECTION_REPORT_GROUP_LIMIT
    members_per_group: int = DEFAULT_COLLECTION_REPORT_MEMBER_LIMIT

    def __post_init__(self) -> None:
        for value, maximum, name in (
            (self.review_items, MAX_COLLECTION_REPORT_REVIEW_LIMIT, "review_items"),
            (
                self.candidate_groups,
                MAX_COLLECTION_REPORT_GROUP_LIMIT,
                "candidate_groups",
            ),
            (
                self.members_per_group,
                MAX_COLLECTION_REPORT_MEMBER_LIMIT,
                "members_per_group",
            ),
        ):
            if not 1 <= value <= maximum:
                raise ValueError(f"{name} is outside the supported range")


@dataclass(frozen=True, slots=True)
class EbookCollectionReportOutcome:
    run_id: EntityId
    report_directory: Path
    report_sha256: str
    files: tuple[str, ...]
    review_item_total: int
    review_item_emitted: int
    exact_duplicate_groups: int
    content_variant_groups: int
    profile: str = EBOOK_COLLECTION_REPORT_PROFILE


@dataclass(frozen=True, slots=True)
class EbookInventoryReportLimits:
    candidate_groups: int = DEFAULT_COLLECTION_REPORT_GROUP_LIMIT
    members_per_group: int = DEFAULT_COLLECTION_REPORT_MEMBER_LIMIT

    def __post_init__(self) -> None:
        for value, maximum, name in (
            (
                self.candidate_groups,
                MAX_COLLECTION_REPORT_GROUP_LIMIT,
                "candidate_groups",
            ),
            (
                self.members_per_group,
                MAX_COLLECTION_REPORT_MEMBER_LIMIT,
                "members_per_group",
            ),
        ):
            if not 1 <= value <= maximum:
                raise ValueError(f"{name} is outside the supported range")


@dataclass(frozen=True, slots=True)
class EbookInventoryReportOutcome:
    scan_run_id: EntityId
    report_directory: Path
    report_sha256: str
    files: tuple[str, ...]
    observations: int
    total_bytes: int
    formats: tuple[EbookInventoryFormatAggregate, ...]
    full_hash_observations: int
    quick_candidate_groups: int
    quick_candidate_observations: int
    quick_candidates_missing_full_hash: int
    exact_duplicate_groups: int
    exact_duplicate_members: int
    redundant_bytes: int
    profile: str = EBOOK_INVENTORY_REPORT_PROFILE


class EbookCollectionReportService:
    """Build byte-stable local artifacts without reopening source media."""

    def __init__(self, store: SQLiteEbookCollectionReportStore) -> None:
        self._store = store

    def generate(
        self,
        run_id: EntityId,
        report_root: Path,
        *,
        limits: EbookCollectionReportLimits | None = None,
    ) -> EbookCollectionReportOutcome:
        configured = limits or EbookCollectionReportLimits()
        snapshot = self._store.snapshot(
            run_id,
            review_item_limit=configured.review_items,
            candidate_group_limit=configured.candidate_groups,
            candidate_member_limit=configured.members_per_group,
        )
        payload = _report_payload(snapshot, configured)
        report_bytes = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        report_sha256 = hashlib.sha256(report_bytes).hexdigest()
        files = {
            _REPORT_JSON: report_bytes,
            _REVIEW_CSV: _review_csv(snapshot),
            _DUPLICATE_CSV: _candidate_csv(snapshot.exact_duplicates),
            _VARIANT_CSV: _candidate_csv(snapshot.content_variants),
        }
        files[_CHECKSUMS] = _checksums(files)
        try:
            report_directory = _persist_report(
                report_root,
                run_id,
                report_sha256,
                files,
            )
        except OSError as error:
            raise EbookCollectionReportError(
                "collection report storage is unavailable"
            ) from error
        return EbookCollectionReportOutcome(
            run_id=run_id,
            report_directory=report_directory,
            report_sha256=report_sha256,
            files=tuple(sorted(files)),
            review_item_total=snapshot.review_item_total,
            review_item_emitted=len(snapshot.review_items),
            exact_duplicate_groups=snapshot.exact_duplicates.total_groups,
            content_variant_groups=snapshot.content_variants.total_groups,
        )


class EbookInventoryReportService:
    """Build a scan-wide private inventory report without opening source media."""

    def __init__(self, store: SQLiteEbookInventoryReportStore) -> None:
        self._store = store

    def generate(
        self,
        scan_root_id: EntityId,
        report_root: Path,
        *,
        limits: EbookInventoryReportLimits | None = None,
    ) -> EbookInventoryReportOutcome:
        configured = limits or EbookInventoryReportLimits()
        snapshot = self._store.snapshot(
            scan_root_id,
            candidate_group_limit=configured.candidate_groups,
            candidate_member_limit=configured.members_per_group,
        )
        report_sha256, files = render_inventory_report_files(snapshot, configured)
        try:
            report_directory = _persist_report(
                report_root,
                snapshot.scan.id,
                report_sha256,
                files,
            )
        except EbookCollectionReportError as error:
            raise EbookInventoryReportError(str(error)) from error
        except OSError as error:
            raise EbookInventoryReportError(
                "inventory report storage is unavailable"
            ) from error
        return EbookInventoryReportOutcome(
            scan_run_id=snapshot.scan.id,
            report_directory=report_directory,
            report_sha256=report_sha256,
            files=tuple(sorted(files)),
            observations=snapshot.observations,
            total_bytes=snapshot.total_bytes,
            formats=snapshot.formats,
            full_hash_observations=snapshot.full_hash_observations,
            quick_candidate_groups=snapshot.quick_candidate_groups,
            quick_candidate_observations=snapshot.quick_candidate_observations,
            quick_candidates_missing_full_hash=(
                snapshot.quick_candidates_missing_full_hash
            ),
            exact_duplicate_groups=snapshot.exact_duplicates.total_groups,
            exact_duplicate_members=snapshot.exact_duplicates.total_members,
            redundant_bytes=snapshot.exact_duplicates.total_redundant_bytes,
        )


def render_inventory_report_files(
    snapshot: EbookInventoryReportSnapshot,
    limits: EbookInventoryReportLimits,
) -> tuple[str, dict[str, bytes]]:
    """Render one deterministic inventory report without writing any files."""

    payload = _inventory_report_payload(snapshot, limits)
    report_bytes = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    files = {
        _INVENTORY_REPORT_JSON: report_bytes,
        _INVENTORY_DUPLICATE_CSV: _inventory_duplicate_csv(
            snapshot.exact_duplicates
        ),
    }
    files[_CHECKSUMS] = _checksums(files)
    return report_sha256, files


def verify_inventory_report_files(
    report_root: Path,
    expected_sha256: str,
    snapshot: EbookInventoryReportSnapshot,
    limits: EbookInventoryReportLimits,
) -> int:
    """Verify an existing report byte-for-byte without modifying its storage."""

    rendered_sha256, expected_files = render_inventory_report_files(snapshot, limits)
    if not hmac.compare_digest(expected_sha256, rendered_sha256):
        raise EbookInventoryReportError("inventory report lineage is invalid")
    try:
        root = report_root.resolve(strict=True)
    except OSError as error:
        raise EbookInventoryReportMissingError(
            "inventory report is not available"
        ) from error
    if report_root.is_symlink() or not root.is_dir():
        raise EbookInventoryReportError("inventory report root is unsafe")
    run_directory = root / str(snapshot.scan.id)
    target = run_directory / rendered_sha256
    if not target.exists():
        raise EbookInventoryReportMissingError("inventory report is not available")
    if run_directory.is_symlink():
        raise EbookInventoryReportError("inventory report run directory is unsafe")
    try:
        resolved_run_directory = run_directory.resolve(strict=True)
    except OSError as error:
        raise EbookInventoryReportMissingError(
            "inventory report is not available"
        ) from error
    if not resolved_run_directory.is_relative_to(root):
        raise EbookInventoryReportError("inventory report run directory escapes its root")
    try:
        _verify_report_files(target, expected_files, root=resolved_run_directory)
    except EbookCollectionReportError as error:
        raise EbookInventoryReportError(
            "inventory report files are invalid"
        ) from error
    return len(expected_files)


def _inventory_report_payload(
    snapshot: EbookInventoryReportSnapshot,
    limits: EbookInventoryReportLimits,
) -> dict[str, JsonValue]:
    scan = snapshot.scan
    duplicates = snapshot.exact_duplicates
    return {
        "profile": EBOOK_INVENTORY_REPORT_PROFILE,
        "scan": {
            "id": str(scan.id),
            "scan_root_id": str(scan.scan_root_id),
            "status": scan.status.value,
            "started_at": scan.started_at.isoformat(),
            "completed_at": (
                None if scan.completed_at is None else scan.completed_at.isoformat()
            ),
        },
        "limits": {
            "candidate_groups": limits.candidate_groups,
            "members_per_group": limits.members_per_group,
        },
        "aggregate": {
            "observations": snapshot.observations,
            "total_bytes": snapshot.total_bytes,
            "formats": {
                value.format_name: {
                    "observations": value.observations,
                    "total_bytes": value.total_bytes,
                }
                for value in snapshot.formats
            },
        },
        "hash_coverage": {
            "full_hash_observations": snapshot.full_hash_observations,
            "quick_candidate_groups": snapshot.quick_candidate_groups,
            "quick_candidate_observations": snapshot.quick_candidate_observations,
            "quick_candidates_missing_full_hash": (
                snapshot.quick_candidates_missing_full_hash
            ),
        },
        "exact_duplicates": _inventory_duplicate_payload(duplicates),
        "identity_verdict": "NOT_PRODUCED",
        "relation_records_written": 0,
    }


def _inventory_duplicate_payload(
    values: EbookInventoryDuplicateSet,
) -> dict[str, JsonValue]:
    return {
        "total_groups": values.total_groups,
        "emitted_groups": len(values.groups),
        "total_members": values.total_members,
        "emitted_members": values.emitted_members,
        "total_redundant_bytes": values.total_redundant_bytes,
        "groups_truncated": values.groups_truncated,
        "members_truncated": values.members_truncated,
        "groups": [
            {
                "group_id": group.group_id,
                "basis": group.basis,
                "member_count": group.member_count,
                "total_bytes": group.total_bytes,
                "redundant_bytes": group.redundant_bytes,
                "emitted_members": len(group.members),
                "members_truncated": group.members_truncated,
                "members": [
                    {
                        "observation_id": str(member.observation_id),
                        "relative_path": member.relative_path,
                        "format": member.format_name,
                        "size_bytes": member.size_bytes,
                    }
                    for member in group.members
                ],
            }
            for group in values.groups
        ],
    }


def _inventory_duplicate_csv(values: EbookInventoryDuplicateSet) -> bytes:
    rows: list[dict[str, str | int]] = []
    for group in values.groups:
        for member in group.members:
            rows.append(
                {
                    "group_id": group.group_id,
                    "basis": group.basis,
                    "group_member_count": group.member_count,
                    "group_total_bytes": group.total_bytes,
                    "group_redundant_bytes": group.redundant_bytes,
                    "members_truncated": str(group.members_truncated).lower(),
                    "observation_id": str(member.observation_id),
                    "relative_path": member.relative_path,
                    "format": member.format_name,
                    "size_bytes": member.size_bytes,
                }
            )
    return _csv_bytes(
        (
            "group_id",
            "basis",
            "group_member_count",
            "group_total_bytes",
            "group_redundant_bytes",
            "members_truncated",
            "observation_id",
            "relative_path",
            "format",
            "size_bytes",
        ),
        rows,
    )


def _report_payload(
    snapshot: EbookCollectionReportSnapshot,
    limits: EbookCollectionReportLimits,
) -> dict[str, JsonValue]:
    run = snapshot.run
    return {
        "profile": EBOOK_COLLECTION_REPORT_PROFILE,
        "run": {
            "id": str(run.id),
            "scan_root_id": str(run.scan_root_id),
            "source_scan_run_id": str(run.source_scan_run_id),
            "collection_profile": run.profile,
            "analysis_profile": run.analysis_profile,
            "status": run.status.value,
            "fresh": run.fresh,
            "worker_count": run.worker_count,
            "started_at": run.started_at.isoformat(),
            "completed_at": (
                None if run.completed_at is None else run.completed_at.isoformat()
            ),
        },
        "limits": {
            "review_items": limits.review_items,
            "candidate_groups_per_basis": limits.candidate_groups,
            "members_per_group": limits.members_per_group,
        },
        "aggregate": {
            "planned": snapshot.counts.planned,
            "terminal": snapshot.counts.terminal,
            "reused_steps": snapshot.counts.reused_steps,
            "executed_steps": snapshot.counts.executed_steps,
            "findings": snapshot.counts.findings,
            "formats": _count_payload(snapshot.format_counts),
            "analysis_statuses": _count_payload(snapshot.analysis_status_counts),
            "quality_statuses": _count_payload(snapshot.quality_status_counts),
            "finding_codes": [
                {
                    "code": finding.code,
                    "dimension": finding.dimension,
                    "severity": finding.severity,
                    "count": finding.count,
                }
                for finding in snapshot.finding_counts
            ],
        },
        "review": {
            "total_items": snapshot.review_item_total,
            "emitted_items": len(snapshot.review_items),
            "truncated": len(snapshot.review_items) < snapshot.review_item_total,
            "items": [
                {
                    "priority": item.priority,
                    "ordinal": item.ordinal,
                    "observation_id": str(item.observation_id),
                    "relative_path": item.relative_path,
                    "format": item.format_name,
                    "analysis_status": item.analysis_status,
                    "quality_status": item.quality_status,
                    "error_code": item.error_code,
                    "findings": [
                        {
                            "code": finding.code,
                            "dimension": finding.dimension,
                            "severity": finding.severity,
                            "source_execution_ids": [
                                str(execution_id)
                                for execution_id in finding.source_execution_ids
                            ],
                        }
                        for finding in item.findings
                    ],
                }
                for item in snapshot.review_items
            ],
        },
        "candidate_sets": {
            "exact_duplicates": _candidate_payload(snapshot.exact_duplicates),
            "content_variants": _candidate_payload(snapshot.content_variants),
        },
        "identity_verdict": "NOT_PRODUCED",
        "relation_records_written": 0,
    }


def _count_payload(values: tuple[tuple[str, int], ...]) -> dict[str, JsonValue]:
    return {key: count for key, count in values}


def _candidate_payload(values: EbookCollectionCandidateSet) -> dict[str, JsonValue]:
    return {
        "total_groups": values.total_groups,
        "emitted_groups": len(values.groups),
        "total_members": values.total_members,
        "emitted_members": values.emitted_members,
        "groups_truncated": values.groups_truncated,
        "members_truncated": values.members_truncated,
        "groups": [
            {
                "group_id": group.group_id,
                "basis": group.basis,
                "member_count": group.member_count,
                "emitted_members": len(group.members),
                "members_truncated": group.members_truncated,
                "members": [
                    {
                        "ordinal": member.ordinal,
                        "observation_id": str(member.observation_id),
                        "relative_path": member.relative_path,
                        "format": member.format_name,
                    }
                    for member in group.members
                ],
            }
            for group in values.groups
        ],
    }


def _review_csv(snapshot: EbookCollectionReportSnapshot) -> bytes:
    rows: list[dict[str, str | int]] = [
        {
            "priority": item.priority,
            "ordinal": item.ordinal,
            "observation_id": str(item.observation_id),
            "relative_path": item.relative_path,
            "format": item.format_name,
            "analysis_status": item.analysis_status,
            "quality_status": item.quality_status or "",
            "error_code": item.error_code or "",
            "finding_codes": ";".join(finding.code for finding in item.findings),
        }
        for item in snapshot.review_items
    ]
    return _csv_bytes(
        (
            "priority",
            "ordinal",
            "observation_id",
            "relative_path",
            "format",
            "analysis_status",
            "quality_status",
            "error_code",
            "finding_codes",
        ),
        rows,
    )


def _candidate_csv(values: EbookCollectionCandidateSet) -> bytes:
    rows: list[dict[str, str | int]] = []
    for group in values.groups:
        for member in group.members:
            rows.append(
                {
                    "group_id": group.group_id,
                    "basis": group.basis,
                    "group_member_count": group.member_count,
                    "members_truncated": str(group.members_truncated).lower(),
                    "ordinal": member.ordinal,
                    "observation_id": str(member.observation_id),
                    "relative_path": member.relative_path,
                    "format": member.format_name,
                }
            )
    return _csv_bytes(
        (
            "group_id",
            "basis",
            "group_member_count",
            "members_truncated",
            "ordinal",
            "observation_id",
            "relative_path",
            "format",
        ),
        rows,
    )


def _csv_bytes(
    fieldnames: tuple[str, ...],
    rows: list[dict[str, str | int]],
) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=fieldnames,
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    writer.writerows(
        {
            key: _safe_csv_cell(value) if isinstance(value, str) else value
            for key, value in row.items()
        }
        for row in rows
    )
    return stream.getvalue().encode("utf-8")


def _safe_csv_cell(value: str) -> str:
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def _checksums(files: dict[str, bytes]) -> bytes:
    lines = [
        f"{hashlib.sha256(content).hexdigest()}  {name}"
        for name, content in sorted(files.items())
    ]
    return ("\n".join(lines) + "\n").encode("ascii")


def _persist_report(
    report_root: Path,
    run_id: EntityId,
    report_sha256: str,
    files: dict[str, bytes],
) -> Path:
    report_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = report_root.resolve()
    run_directory = root / str(run_id)
    run_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_directory = run_directory.resolve()
    if not run_directory.is_relative_to(root):
        raise EbookCollectionReportError("collection report directory escapes its root")
    target = run_directory / report_sha256
    if not target.resolve().is_relative_to(run_directory):
        raise EbookCollectionReportError("collection report target escapes its root")
    if target.exists():
        _verify_report_files(target, files, root=run_directory)
        return target

    temporary = Path(
        tempfile.mkdtemp(prefix=".pending-", dir=run_directory)
    ).resolve()
    if not temporary.is_relative_to(run_directory):
        raise EbookCollectionReportError("temporary report directory escapes its root")
    try:
        for name, content in files.items():
            path = temporary / name
            with path.open("xb") as stream:
                stream.write(content)
            path.chmod(0o600)
        try:
            os.replace(temporary, target)
        except OSError:
            if not target.is_dir():
                raise
            _verify_report_files(target, files, root=run_directory)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return target


def _verify_report_files(
    directory: Path,
    expected: dict[str, bytes],
    *,
    root: Path,
) -> None:
    resolved = directory.resolve()
    if (
        directory.is_symlink()
        or not resolved.is_relative_to(root)
        or not resolved.is_dir()
    ):
        raise EbookCollectionReportError("collection report target is not a directory")
    entries = tuple(resolved.iterdir())
    if any(
        path.is_symlink()
        or not path.is_file()
        or not path.resolve().is_relative_to(resolved)
        for path in entries
    ):
        raise EbookCollectionReportError("existing collection report contains unsafe files")
    actual_names = {path.name for path in entries}
    if actual_names != set(expected):
        raise EbookCollectionReportError("existing collection report is incomplete")
    for name, content in expected.items():
        path = resolved / name
        if path.read_bytes() != content:
            raise EbookCollectionReportError("existing collection report was modified")
