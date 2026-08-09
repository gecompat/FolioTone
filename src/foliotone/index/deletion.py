"""Conservative policy for confirming persistent file absence as DELETED."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from foliotone.core._validation import require_aware_datetime


@dataclass(frozen=True, slots=True)
class DeletionConfirmationPolicy:
    """Require repeated successful absence observations plus elapsed time."""

    min_consecutive_missing_scans: int = 3
    min_missing_age: timedelta = timedelta(hours=24)

    def __post_init__(self) -> None:
        if self.min_consecutive_missing_scans < 2:
            raise ValueError("min_consecutive_missing_scans must be at least 2")
        if self.min_missing_age <= timedelta(0):
            raise ValueError("min_missing_age must be greater than zero")

    def confirms(
        self,
        *,
        consecutive_missing_scans: int,
        missing_since_at: datetime,
        evaluated_at: datetime,
    ) -> bool:
        """Return whether the accumulated absence evidence satisfies this policy."""
        require_aware_datetime(missing_since_at, "missing_since_at")
        require_aware_datetime(evaluated_at, "evaluated_at")
        if consecutive_missing_scans < 1:
            raise ValueError("consecutive_missing_scans must be positive")
        if evaluated_at < missing_since_at:
            raise ValueError("evaluated_at must not be before missing_since_at")
        return (
            consecutive_missing_scans >= self.min_consecutive_missing_scans
            and evaluated_at - missing_since_at >= self.min_missing_age
        )
