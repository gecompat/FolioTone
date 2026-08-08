# ADR-0013: Conservative DELETED confirmation from repeated successful absence

- Status: Accepted
- Date: 2026-08-09

## Context

`MISSING` means that a previously known file was not observed during one successfully completed scan of an available `ScanRoot`. This is useful evidence, but it does not prove that the file was permanently deleted. Temporary storage problems, intentionally disconnected media, transient directory availability or an incomplete external mount can all produce absence without a durable deletion.

FolioTone therefore needs a stronger `DELETED` state without weakening the existing rule that unavailable or failed scans must not create false absence evidence. The decision must also remain compatible with the W0-W9 safety boundary: `DELETED` is an observed/classified state in the index and does not authorize or execute a filesystem delete operation.

## Decision

Automatic `DELETED` confirmation is **disabled by default**.

When explicitly enabled for a scanner, a known file can transition from `MISSING` to `DELETED` only when both conditions are satisfied:

1. the file has been absent in at least a configured minimum number of consecutive successful full scans; the minimum accepted value is 2;
2. at least a configured minimum duration has elapsed since the first absence in the current consecutive `MISSING` series.

The default values of `DeletionConfirmationPolicy`, when a caller explicitly constructs it, are three consecutive missing scans and 24 hours. The CLI remains opt-in: `--confirm-deleted-after-missing-scans` enables confirmation, while `--confirm-deleted-after-hours` can override the 24-hour minimum.

`FileRecord` persists the current absence-series state:

- `missing_since_at` records when the current consecutive absence series began;
- `consecutive_missing_scans` records how many successful full scans have confirmed that absence.

Only the successful post-discovery absence phase advances these values. A scan that fails or is interrupted before successful completion does not call the absence-confirmation phase and therefore cannot advance the series.

When both configured thresholds are met, the current scan emits `FileChangeState.DELETED` and the `FileRecord.presence_state` becomes `DELETED`. Further scans do not repeatedly emit absence events for that record while it remains absent.

If the same relative path is observed again, including after `DELETED`, FolioTone emits `REAPPEARED`, restores `PRESENT`, and clears the persisted absence-series state.

## Migration behavior

Alembic revision `0003_deletion_confirmation` adds the two absence-series fields to `file_records`.

Existing databases upgraded from `0002_incremental_index` are treated conservatively. Existing records receive no inferred historical absence start and a count of zero. FolioTone does not reconstruct a deletion-confirmation streak from incomplete legacy state; a new confirmed series begins on subsequent successful scans.

## Safety consequences

- one `MISSING` event can never imply `DELETED`;
- repeatedly invoking scans in a short period cannot satisfy the policy when the minimum age has not elapsed;
- failed or unavailable-root scans cannot contribute to deletion confirmation;
- `DELETED` remains reversible when a file reappears;
- no filesystem delete, move, rename, retag or other source-media mutation is introduced;
- W10 remains blocked and unchanged.

## Operational consequences

The persisted counter avoids rescanning the full historical event stream for every missing file, which keeps confirmation work bounded by the current set of absent records. `FileScanEvent` remains the audit trail for each `MISSING`, `DELETED` and later `REAPPEARED` classification.

The thresholds are policy parameters rather than universal facts. Different storage environments may require substantially longer confirmation windows. FolioTone therefore does not silently enable one threshold set for all collections.
