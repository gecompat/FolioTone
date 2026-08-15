# CI Workflow Contract

## Status

The GitHub Actions workflow is installed at `.github/workflows/ci.yml`.
Its full quality gate runs exactly once for the normal pull-request path,
instead of repeating on branch push, pull request and merged `main`.

This document preserves the intended workflow contract and the known predecessor failure so future agents can verify CI configuration without reconstructing prior chat context.

## Target path

`.github/workflows/ci.yml`

## Trigger contract

The workflow listens only to:

- `pull_request` targeting `main`;
- `workflow_dispatch` for an explicit manual full run;
- `push` to `main` for a lightweight post-merge contract only.

Ordinary feature-branch pushes do not start a second copy beside the pull-
request run. Workflow concurrency is keyed by pull-request number or ref and
cancels an obsolete run when a newer commit supersedes it.

## Full pull-request gate

The `quality` job runs for pull requests and manual dispatch only. It covers:

1. install;
2. Ruff;
3. Mypy;
4. Pytest;
5. Docker build;
6. migration and persistent `/data` smoke tests;
7. incremental scan and bootstrap smoke tests.

The job has a 15-minute timeout. The full test inventory remains intact; this
contract removes redundant executions, not checks.

## Main post-merge contract

The `post-merge-contract` job is the only job for a `main` push. It performs no
package install, Python test suite or Docker build. It checks out two commits,
requires the new `main` head to have exactly two parents and runs
`git diff-tree --check HEAD^1 HEAD`. A normal successful merge therefore costs
only a few seconds, while an accidental direct push is visibly rejected.

This post-merge signal is detection, not branch protection. Until repository
branch protection is configured explicitly, contributors and agents must keep
using pull requests for every `main` change.

## Known predecessor failure already corrected in FolioTone

The predecessor repository's PR CI installed the Python package successfully but failed Ruff with `E501` because one CLI status line was 107 characters while the configured limit is 100.

The FolioTone `src/foliotone/cli/main.py` status output is already line-wrapped, so do not reintroduce the old line.

## Verification rule

1. verify one `quality` run for the pull-request head;
2. verify Ruff, Mypy, Pytest and all Docker smoke steps in that run;
3. merge only the exact green pull-request head;
4. verify the short `post-merge-contract` on the resulting `main` head;
5. update `PROJECT_STATUS.md` with actual results.

Do not claim FolioTone CI passed based on the predecessor run.
