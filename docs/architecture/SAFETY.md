# Safety and Non-Destructive Operation

## Baseline

FolioTone starts as an analysis system. Source collections are treated as evidence, not as writable workspace.

## Enforced W0–W9 invariants

- source media mounts are read-only in the standard container configuration;
- no source-media delete command exists;
- no source-media move or rename command exists;
- no metadata writer exists for source media;
- no Calibre write adapter exists;
- external enrichment does not write back to source media;
- W9 consolidation plans are data records only and cannot execute.

## External lookup privacy

External knowledge can improve identification, but network use must not silently disclose unnecessary collection context.

Rules:

- never send absolute local paths to external providers;
- prefer structured identifiers/candidate fields over raw filenames;
- transmit only the minimum fields required for a lookup;
- use provider cache/local datasets to avoid unnecessary repeated disclosure;
- keep API keys and credentials outside Git;
- generic web/AI research creates candidates/evidence, not automatic destructive authority;
- ordinary local scanning/analysis must remain useful with external providers disabled.

## Future W10 requirements

A future executable consolidation engine must not be enabled merely by adding a CLI flag. It requires an explicit accepted ADR and must include at least:

1. dry-run/plan representation;
2. explicit operation approval;
3. source precondition validation immediately before mutation;
4. changed-since-analysis protection;
5. collision handling;
6. audit logging;
7. clear partial-failure semantics;
8. tests on temporary synthetic filesystems;
9. a design for recovery/rollback where feasible;
10. no implicit deletion based on one signal, one provider result, one AI/web inference or one score.

## Persistence is writable; media is not

`/data` is intentionally writable so scans, hashes, normalized metadata, authority/provider cache, decisions, and future plans can be persisted. `/media/...` is read-only in the default compose file.

## Private data

Runtime state may itself contain sensitive metadata about a private collection. `/data` is therefore excluded from Git. Logs should avoid dumping full extracted text, unnecessary absolute paths, raw external queries, or credentials.

Imported/local provider datasets must also stay out of Git unless a future explicit decision establishes that a specific redistributable dataset belongs in the repository.
