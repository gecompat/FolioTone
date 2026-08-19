import pytest

from foliotone.core import EntityId
from foliotone.persistence import (
    CALIBRE_RECONCILIATION_FINDING_CODES,
    CalibreReconciliationReport,
    CalibreReconciliationReportCounts,
)


def test_calibre_reconciliation_report_payload_is_path_free_and_complete() -> None:
    report = CalibreReconciliationReport(
        snapshot_id=EntityId.parse("00000000-0000-0000-0000-000000000001"),
        scan_root_id=EntityId.parse("00000000-0000-0000-0000-000000000002"),
        source_scan_run_id=EntityId.parse("00000000-0000-0000-0000-000000000003"),
        snapshot_status="COMPLETED",
        counts=CalibreReconciliationReportCounts(2, 3, 1, 7, 4, 9),
        finding_counts=tuple(
            (code, index) for index, code in enumerate(CALIBRE_RECONCILIATION_FINDING_CODES)
        ),
    )

    payload = report.payload()
    assert payload["profile"] == "calibre-reconciliation-report/v1"
    assert payload["snapshot_id"] == "00000000-0000-0000-0000-000000000001"
    assert payload["scan_root_id"] == "00000000-0000-0000-0000-000000000002"
    assert payload["source_scan_run_id"] == "00000000-0000-0000-0000-000000000003"
    assert payload["snapshot_status"] == "COMPLETED"
    assert payload["counts"] == {
        "records": 2,
        "formats": 3,
        "sidecars": 1,
        "findings": 7,
        "review_required": 4,
        "refs": 9,
    }
    assert tuple(payload["finding_counts"]) == CALIBRE_RECONCILIATION_FINDING_CODES
    assert all("path" not in key.lower() for key in str(payload).split())


@pytest.mark.parametrize("status", ["RUNNING", "COMPLETED", "INVALIDATED", "FAILED"])
def test_calibre_reconciliation_report_payload_keeps_persisted_statuses_with_zero_counts(
    status: str,
) -> None:
    report = CalibreReconciliationReport(
        snapshot_id=EntityId.parse("00000000-0000-0000-0000-000000000004"),
        scan_root_id=EntityId.parse("00000000-0000-0000-0000-000000000005"),
        source_scan_run_id=EntityId.parse("00000000-0000-0000-0000-000000000006"),
        snapshot_status=status,
        counts=CalibreReconciliationReportCounts(0, 0, 0, 0, 0, 0),
        finding_counts=tuple((code, 0) for code in CALIBRE_RECONCILIATION_FINDING_CODES),
    )

    payload = report.payload()
    assert payload["snapshot_status"] == status
    assert payload["counts"] == {
        "records": 0,
        "formats": 0,
        "sidecars": 0,
        "findings": 0,
        "review_required": 0,
        "refs": 0,
    }
