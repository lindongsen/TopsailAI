---
status: open
priority: high
component: server
---
# Manager-agent auto-join health check fails when ACS_GROUP_MANAGER_AGENT_CMD_CHECK_HEALTH is omitted

## Summary
When `ACS_GROUP_MANAGER_AGENT_CMD_CHAT` is set but `ACS_GROUP_MANAGER_AGENT_CMD_CHECK_HEALTH` is omitted, the auto-joined manager-agent should be considered always healthy per `docs/Environment_Variables.md`. In practice, the agent is marked unhealthy or the group creation fails because a health check is still attempted.

## Steps to Reproduce
1. Start the server with only `ACS_GROUP_MANAGER_AGENT_CMD_CHAT` set (no `ACS_GROUP_MANAGER_AGENT_CMD_CHECK_HEALTH`).
2. Create a group via `POST /api/v1/groups`.
3. Observe the auto-joined manager-agent status or group creation result.

## Expected Result
- Group creation succeeds.
- Manager-agent member is created with `member_status` set to `online` or `idle`.
- No health-check command is invoked.

## Actual Result
Group creation may fail or the manager-agent member status becomes `offline` because a missing/empty health-check command is executed or the agent is considered unhealthy.

## Root Cause
- `internal/api/handlers/group.go` builds `member_interface` with `cmd_check_health` even when the env var is empty.
- Agent executor or work pool may invoke the empty command and treat the result as a failure.

## Affected Code
- `internal/api/handlers/group.go` — `buildManagerAgentMemberInterface()`
- `internal/agent/executor.go` — health-check invocation logic
- `internal/agent/workpool.go` — status handling

## Suggested Fix
1. In `buildManagerAgentMemberInterface`, only include `cmd_check_health` in `member_interface` when the env var is non-empty.
2. In the agent executor, treat a missing `cmd_check_health` as "always healthy".
3. Ensure `cmd_check_status` is handled the same way.

## Workaround
Set `ACS_GROUP_MANAGER_AGENT_CMD_CHECK_HEALTH` to a script that always exits 0, e.g.:
```bash
#!/bin/bash
echo "healthy"
exit 0
```

## Related
- docs/Environment_Variables.md: "If unset, the agent is always considered healthy."
- ORIGIN.md: Manager-agent auto-join configuration.
- issue-auto-join-manager-agent-on-group-create.md (status: done).
