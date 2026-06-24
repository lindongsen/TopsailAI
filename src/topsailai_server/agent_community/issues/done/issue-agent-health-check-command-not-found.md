---
status: done
severity: critical
phase: CLI Manual Testing Phase 6
related_test_cases:
  - CLI-AGENT-001
  - CLI-AGENT-002
  - CLI-AGENT-003
  - CLI-AGENT-004
  - CLI-AGENT-005
  - CLI-AGENT-006
  - CLI-AGENT-007
  - CLI-AGENT-008
  - CLI-AGENT-009
  - CLI-AGENT-010
  - CLI-AGENT-011
  - CLI-AGENT-012
  - CLI-AGENT-013
  - CLI-AGENT-014
  - CLI-AGENT-015
---

# Agent Health Check Fails Because Default Command Is Not on PATH

## Summary
After the agent-response visibility fix was applied, Phase 6 agent-trigger tests still could not pass because the agent executor could not find the default health-check/status commands. The executor runs commands via `sh -c {cmd}` and relied on the shell `PATH`, but the mock scripts live in `/TopsailAI/src/topsailai_server/agent_community/scripts/`, which is not on `PATH` by default.

## Root Cause
`cmd/server/main.go` created the agent executor with `agent.NewExecutor()`, which reads `ACS_AGENT_SCRIPTS_PATH` directly from `os.Getenv`. The value loaded by `internal/config` into `cfg.Agent.ScriptsPath` was never passed to the executor, so the scripts search path was effectively ignored in the server process.

## Fix
1. `cmd/server/main.go`: Changed executor creation from `agent.NewExecutor()` to `agent.NewExecutorWithScriptsPath(cfg.Agent.ScriptsPath)` so the configured scripts search path is actually used.
2. `docs/Environment_Variables.md`: Documented `ACS_AGENT_SCRIPTS_PATH`.
3. `cmd/cli/commands_test.go`: Added `TestHandleMemberUpdateWithInterface` to verify that `/member:update --member-interface` is parsed and sent to the API (the CLI implementation already supported this).

## Verification

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test -count=1 ./internal/agent/... ./cmd/cli/... -run 'TestResolveCommand|TestHandleMemberUpdate' -v
# PASS

go build ./...
# success
```

## Usage

Set the scripts path before starting the server:

```bash
export ACS_AGENT_SCRIPTS_PATH=/TopsailAI/src/topsailai_server/agent_community/scripts
go run ./cmd/server
```

Or set it in the service environment so bare adaptor commands such as `mock_agent_cmd_check_health` are resolved automatically.

## Notes
- The executor already had `resolveCommand` and `NewExecutorWithScriptsPath` support; this fix only wires the configured value into the server.
- A pre-existing unrelated test failure exists in `internal/discovery/discovery_test.go` (`TestDiscovery_LeaderInfo`) and should be addressed separately.
