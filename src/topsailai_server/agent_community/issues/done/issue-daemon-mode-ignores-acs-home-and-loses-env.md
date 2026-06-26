---
status: fixed
related_plan: Manual_Test_Plan_04_CLI_Commands_and_Cluster.md
related_test_case: 4.12
created_by: km1-tester
fixed_by: km3-programmer
---

# Daemon Mode Ignores ACS_HOME and Loses Environment Variables in Forked Child

## Summary

The ACS server daemon mode did not respect the `ACS_HOME` environment variable as documented in `docs/Environment_Variables.md` and `README.md`. Additionally, when starting the daemon, the parent process forked a child without preserving the current environment, so even `TOPSAILAI_HOME` was effectively ignored by the actual daemon process. This caused log files, PID files, and (for SQLite) the database file to be placed in `/topsailai` regardless of the operator's configuration.

## Fix

1. Updated `internal/daemon/daemon.go::getACSHome()` to check `ACS_HOME` first, then `TOPSAILAI_HOME`, then fall back to `/topsailai`.
2. Updated `internal/daemon/daemon.go::StartWithExecutable()` to explicitly set `cmd.Env = os.Environ()` so the daemon child inherits `ACS_HOME`/`TOPSAILAI_HOME`.
3. Updated `cmd/server/main.go::printUsage()` to document both `ACS_HOME` and `TOPSAILAI_HOME`.
4. Added/updated unit tests in `internal/daemon/daemon_test.go` covering `ACS_HOME` priority and environment preservation.

## Files Changed

- `internal/daemon/daemon.go`
- `cmd/server/main.go`
- `internal/daemon/daemon_test.go`

## Verification

- `go test ./internal/daemon/... -count=1` passes.
- `go test ./... -count=1` passes.
- Manual re-verification of Test Case 4.12 is required by the tester.

## Related Documentation

- `docs/Environment_Variables.md` — Daemon Configuration section
- `README.md` — Daemon Configuration and Run sections
