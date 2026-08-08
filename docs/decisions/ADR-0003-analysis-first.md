# ADR-0003: Analysis-only product mode before consolidation execution

- Status: Accepted
- Date: 2026-08-08

## Context

Duplicate/entity-resolution decisions in a large personal media collection can produce false positives. Destructive operations have much higher risk than analysis.

The roadmap now contains a dedicated Authority/Entity Resolution/Enrichment wave before Matching, so non-executable consolidation planning occurs in W9 and write-capable consolidation moves to W10.

## Decision

FolioTone is read-only with respect to source media during W0–W9. It may index, analyze, resolve identities, enrich/classify, match, review, read Calibre metadata, and persist non-executable consolidation plans. No source-media mutation is implemented before W10.

## Consequences

- Safety is architectural rather than merely a default CLI option.
- Early development can improve identity/matching quality without risking source data.
- External provider or web/AI evidence does not create a source-media write path.
- W10 requires a new explicit ADR before write-capable consolidation is implemented.
