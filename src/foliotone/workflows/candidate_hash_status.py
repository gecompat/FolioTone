"""Path-free status rendering for selective e-book candidate hashing."""

from __future__ import annotations

from datetime import datetime

from foliotone.core import EbookCandidateHashRun


def candidate_hash_status_payload(
    scan_root: str,
    run: EbookCandidateHashRun | None,
    now: datetime,
) -> dict[str, object]:
    """Build the stable machine-readable candidate-hash status contract."""

    payload: dict[str, object] = {
        "schema_version": 1,
        "command": "ebook-hash-status",
        "ok": True,
        "scan_root": scan_root,
        "run": None,
    }
    if run is None:
        return payload

    if run.lease_expires_at is None:
        lease_state = "NONE"
    elif run.lease_expires_at > now:
        lease_state = "ACTIVE"
    else:
        lease_state = "EXPIRED"
    selection = None
    if run.candidate_groups is not None:
        selection = {
            "candidate_groups": run.candidate_groups,
            "candidate_observations": run.candidate_observations,
            "already_hashed": run.already_hashed,
        }
    payload["run"] = {
        "id": str(run.id),
        "source_scan_run_id": str(run.source_scan_run_id),
        "profile": run.profile,
        "status": run.status.value,
        "phase": run.phase.value,
        "started_at": run.started_at.isoformat(),
        "heartbeat_at": run.heartbeat_at.isoformat(),
        "finished_at": None if run.finished_at is None else run.finished_at.isoformat(),
        "lease_expires_at": (
            None if run.lease_expires_at is None else run.lease_expires_at.isoformat()
        ),
        "lease_state": lease_state,
        "selection": selection,
        "progress": {
            "processed": run.processed_count,
            "hashed": run.hashed_count,
            "failures": run.failure_count,
            "remaining": run.remaining_count,
        },
    }
    return payload
