"""Public pure contracts for explicitly authorized future quarantine work."""

from foliotone.quarantine.contracts import (
    MAX_QUARANTINE_AUTHORIZATION_LIFETIME,
    QUARANTINE_AUTHORIZATION_NAMESPACE,
    QUARANTINE_AUTHORIZATION_PROFILE,
    QUARANTINE_EXECUTION_PROFILE,
    QuarantineAuthorizationAssessment,
    QuarantineAuthorizationBlockerCode,
    QuarantineAuthorizationSnapshot,
    QuarantineEligibilityStatus,
    QuarantineRunStatus,
    build_quarantine_authorization,
)

__all__ = [
    "MAX_QUARANTINE_AUTHORIZATION_LIFETIME",
    "QUARANTINE_AUTHORIZATION_NAMESPACE",
    "QUARANTINE_AUTHORIZATION_PROFILE",
    "QUARANTINE_EXECUTION_PROFILE",
    "QuarantineAuthorizationAssessment",
    "QuarantineAuthorizationBlockerCode",
    "QuarantineAuthorizationSnapshot",
    "QuarantineEligibilityStatus",
    "QuarantineRunStatus",
    "build_quarantine_authorization",
]
