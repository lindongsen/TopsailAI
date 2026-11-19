---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-19
---

# Session info drops PID before reading row-specific runtime detail

## Symptom

The operator selects one exact Cluster session row, but `info` forwards only its provider session ID.
When several Provider rows share that session ID, the TopsailAI Provider chooses the first non-task
row for `provider_runtime`, which may not be the row the operator selected.

## Evidence

- The resolved inventory `Session` contains both `ProviderSessionID` and `ProviderPID`.
- `internal/tui/interactive_info.go:39` and `internal/tui/commands_info.go:57` call
  `readSessionDetail` with only `session.ProviderSessionID`.
- `internal/protocol/detail.go:94-96` defines `SessionDetailQuery` with only `ProviderSessionID`.
- `internal/adapter/genericcli/adapter.go:610` therefore sends a session-scoped Provider target and an
  empty detail payload.
- `providers/topsailai/src/query.go:610-626` implements `runtimeRow` by returning the first non-task
  row with the same session ID, or the first task row as fallback.
- `runtimeEnvelope` at `query.go:704-713` obtains all matching local rows through
  `workspace list --json --local -s SESSION --include-runtime` and applies that selector.

## Root cause

The detail contract combines two documents with different identity scopes but carries only the
session-scoped identity:

- `provider_metadata` is correctly session-scoped and comes from `session info --json`;
- `provider_runtime` is process-row-scoped but receives no PID.

## Required direction

Add the provider PID as an optional detail selector when `info` starts from an inventory row.
Continue reading `provider_metadata` by session ID. Read `provider_runtime` for the exact session/PID
row, using the Provider's exact runtime-info surface, and retain the session-only behavior for history
or offline callers that genuinely have no PID.

## Why this matters

This is not only avoidable work. It is an identity correctness defect: two rows can share a provider
session ID while representing different processes and runtime counters. A session-only selector can
return valid data for the wrong row, so the output looks trustworthy while describing another target.
