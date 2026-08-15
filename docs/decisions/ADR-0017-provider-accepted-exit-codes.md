# ADR-0017: Tool execution success follows a provider-specific exit-code contract

- Status: Accepted
- Date: 2026-08-15

## Context

The initial local ToolProvider runtime treated only process exit code `0` as a
successful execution. That rule is valid for many extractors, but it conflates
process failure with a completed domain verdict for validators and inspection
tools.

EPUBCheck, for example, returns exit code `1` when a completed check reports
EPUB conformance errors. The machine-readable report is still the intended
result of the invocation. Treating that execution as failed would discard the
exact evidence FolioTone requested and would make technical availability
indistinguishable from a negative quality finding.

## Decision

Each immutable local or container command declares a non-empty allowlist of
accepted non-negative exit codes. The default remains `{0}`. An adapter may
extend the allowlist only when the upstream command documents another code as
a completed result for that exact operation.

`ToolExecution.status = SUCCEEDED` means that the process completed with an
adapter-accepted exit code and produced every required bounded artifact. The
original exit code is always preserved. A negative domain verdict is stored as
`ToolResult` Evidence and does not become an `error_summary`.

Missing, malformed or oversized required output still makes the execution
unusable. Exit codes outside the fixed allowlist remain `FAILED`; timeouts and
caller cancellation remain `CANCELLED`.

The EPUBCheck `epubcheck-json/1` adapter accepts `{0, 1}`. It then validates the
bounded JSON report before projecting `CONFORMANT` or `NONCONFORMANT` Evidence.
The adapter does not expose `--failonwarnings`, so warnings and usage messages
remain report data rather than caller-controlled exit semantics.

## Consequences

- Existing extractors retain their zero-only behavior without configuration
  changes.
- Validators can distinguish a successful check with findings from a process,
  dependency or artifact failure.
- Callers must use normalized `ToolResult` values for domain decisions instead
  of interpreting `ToolExecution.status` as media quality.
- New non-zero accepted codes require an upstream-documented operation-specific
  contract and automated tests.
