---
status: fixed
priority: high
related_test: docs/cases/TestCase_manual_cli_agent_trigger.md AGENT-013
---

# Per-Group AgentWorkPool Limit Not Enforced

## Problem
Manual test AGENT-013 set `ACS_AGENT_WORK_POOL_PER_GROUP=1` and triggered two worker-agents in the same group. Both agents executed concurrently instead of being serialized, indicating the per-group work-pool limit was not applied.

## Root Cause
`internal/config/config.go` binds `ACS_AGENT_WORK_POOL_ACQUIRE_TIMEOUT` to the Viper key, but it did **not** bind the capacity environment variables:

- `ACS_AGENT_WORK_POOL_PER_NODE`
- `ACS_AGENT_WORK_POOL_PER_USER`
- `ACS_AGENT_WORK_POOL_PER_GROUP`

Because the bindings were missing, Viper always fell back to the hard-coded defaults (`per_node=10`, `per_user=5`, `per_group=5`) regardless of the environment variables documented in `docs/Environment_Variables.md`.

## Impact
- Operators could not tune AgentWorkPool concurrency via environment variables.
- Per-group/per-user/per-node limits documented in `docs/Environment_Variables.md` were effectively ignored.
- Manual test AGENT-013 (and any test relying on these env vars) failed.

## Fix
Added the missing `v.BindEnv` calls in `internal/config/config.go`:

```go
_ = v.BindEnv("agent_work_pool.per_node", "ACS_AGENT_WORK_POOL_PER_NODE")
_ = v.BindEnv("agent_work_pool.per_user", "ACS_AGENT_WORK_POOL_PER_USER")
_ = v.BindEnv("agent_work_pool.per_group", "ACS_AGENT_WORK_POOL_PER_GROUP")
```

Also added `TestLoad_AgentWorkPoolEnvOverrides` in `internal/config/config_test.go` to verify that all four `ACS_AGENT_WORK_POOL_*` environment variables are honored.

## Verification
```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./...
make build
```

- `go test ./...` — all packages pass.
- `make build` — server, CLI, and natsctl build successfully.

## Files Changed
- `internal/config/config.go`
- `internal/config/config_test.go`

## Next Step
Re-run manual test AGENT-013. With `ACS_AGENT_WORK_POOL_PER_GROUP=1`, the two worker-agents in the same group should now be serialized.
