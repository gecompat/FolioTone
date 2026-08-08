# CI Workflow Contract

## Status

The GitHub Actions workflow is installed at `.github/workflows/ci.yml`.

This document preserves the intended workflow contract and the known predecessor failure so future agents can verify CI configuration without reconstructing prior chat context.

## Target path

`.github/workflows/ci.yml`

## Expected content

```yaml
name: CI

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install
        run: python -m pip install -e '.[dev]'
      - name: Ruff
        run: ruff check .
      - name: Mypy
        run: mypy src/foliotone
      - name: Tests
        run: pytest
```

## Known predecessor failure already corrected in FolioTone

The predecessor repository's PR CI installed the Python package successfully but failed Ruff with `E501` because one CLI status line was 107 characters while the configured limit is 100.

The FolioTone `src/foliotone/cli/main.py` status output is already line-wrapped, so do not reintroduce the old line.

## Verification rule

1. run/observe the FolioTone GitHub Actions workflow;
2. verify Ruff, Mypy and Pytest results;
3. run the Docker bootstrap if CI does not cover it;
4. update `PROJECT_STATUS.md` with actual results;
5. mark `W0-006` complete only when reality supports it.

Do not claim FolioTone CI passed based on the predecessor run.
