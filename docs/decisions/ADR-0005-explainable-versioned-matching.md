# ADR-0005: Matching must be explainable and versioned

- Status: Accepted
- Date: 2026-08-08

## Context

Metadata can be wrong, editions/releases differ subtly, and content fingerprints can disagree with metadata. A single similarity score is insufficient for safe review or future consolidation.

## Decision

Every material match result must retain its relation proposal, score/confidence, evidence/explanation, and relevant matcher/rule/fingerprint versions. Candidate generation and scoring are separate stages.

## Consequences

- Review can explain why items were grouped.
- Results can be re-evaluated selectively after algorithm changes.
- Storage schemas must account for versioned derived data.
- False-positive protection has priority over aggressive automatic consolidation.
