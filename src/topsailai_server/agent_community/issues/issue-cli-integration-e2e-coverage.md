# Issue: CLI interactive/IO-bound paths need integration/e2e coverage

## Status
open

## Module
cmd/cli

## Description
The `cmd/cli` package unit-test coverage has reached **50.1%** after covering the NATS manager, display helpers, prompt state, and interactive parsing functions. The remaining uncovered code is primarily interactive or I/O-bound and is difficult to exercise with pure unit tests:

- `main.go` — `run()` loop, command dispatch, signal handling, and env-helper functions.
- `prompt.go` — TTY-bound prompt state and terminal interaction paths.
- `startPolling` / `pollMessages` — long-running HTTP polling goroutines.

## Why Unit Tests Are Not Enough

These paths depend on:
- Real terminal stdin/stdout/stderr (TTY detection, readline-like behavior).
- Long-running goroutines and cancellation semantics.
- End-to-end interaction with a running ACS server and/or NATS bus.

Mocking all of these would provide low-value coverage and would not catch real integration issues (e.g., prompt rendering, command parsing edge cases, graceful shutdown).

## Proposed Solution

Add integration/e2e tests under `tests/integration/` or `tests/e2e/` that:

1. Start a real ACS server (or use a lightweight test server).
2. Drive the CLI via a pseudo-terminal (pty) or scripted stdin.
3. Exercise the main command loop, group creation, member listing, message sending, and NATS event subscription.
4. Verify graceful shutdown on SIGINT/SIGTERM.

## Acceptance Criteria

- [ ] An integration or e2e test script exists that launches `acs-cli` and exercises the `run()` loop.
- [ ] Prompt/TTY paths are covered by at least one automated test using a pty or equivalent.
- [ ] Polling paths (`startPolling`, `pollMessages`) are covered by at least one test against a real or mocked ACS server.
- [ ] The test runs in CI without requiring a real human operator.

## Related

- `.task/Test_Execution_Checklist.md` — Unit-test checklist for `cmd/cli`.
- `docs/cases/TestCase_manual_api.md` — Manual API test scenarios that can be automated.

## Notes

This issue is intentionally scoped to integration/e2e coverage. Do not block further unit-test work on other modules while this issue is open.
