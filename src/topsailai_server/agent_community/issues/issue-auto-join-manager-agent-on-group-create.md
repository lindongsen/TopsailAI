---
status: done
labels:
  - feature
  - group
  - manager-agent
---

# Auto-Join Default Manager-Agent on Group Creation

## Problem

Previously, creating a group via `POST /api/v1/groups` only created the `group` record. According to the ACS design, every group should have at least one `manager-agent` to coordinate tasks, but callers had to explicitly join a manager-agent via `POST /api/v1/groups/:group_id/members`. This was error-prone and inconsistent with the design intent.

## Solution

When the server is configured with `ACS_GROUP_MANAGER_AGENT_CMD_CHAT`, creating a group now automatically joins a default `manager-agent` member as part of the same database transaction.

## Changes

### Configuration (`internal/config/config.go`)

- Added `ManagerAgentConfig` under `AgentConfig` to hold all manager-agent auto-join settings.
- Bound the following environment variables:
  - `ACS_GROUP_MANAGER_AGENT_CMD_CHAT` (required, enables auto-join when set)
  - `ACS_GROUP_MANAGER_AGENT_CMD_CHECK_HEALTH`
  - `ACS_GROUP_MANAGER_AGENT_CMD_CHECK_STATUS`
  - `ACS_GROUP_MANAGER_AGENT_API_BASE`
  - `ACS_GROUP_MANAGER_AGENT_API_KEY`
  - `ACS_GROUP_MANAGER_AGENT_API_AUTH`
  - `ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHAT`
  - `ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHECK_HEALTH`
  - `ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHECK_STATUS`
  - `ACS_GROUP_MANAGER_AGENT_MEMBER_ID` (default: `manager-agent`)
  - `ACS_GROUP_MANAGER_AGENT_MEMBER_NAME` (default: `manager-agent`)
  - `ACS_GROUP_MANAGER_AGENT_MEMBER_DESCRIPTION`
  - `ACS_GROUP_MANAGER_AGENT_ADAPTOR` (default: `topsailai_agent`)

### Group Handler (`internal/api/handlers/group.go`)

- `GroupHandler` now receives `*config.Config`.
- `CreateGroup` runs group creation and optional manager-agent member creation inside a GORM transaction.
- Added `buildManagerAgentMemberInterface()` to construct the `member_interface` JSON from configuration.
- Publishes both `group` and `group_member` create events to NATS after the transaction commits.

### Router (`internal/api/router.go`)

- Updated `NewGroupHandler` call to pass the loaded configuration.

### Documentation

- Updated `docs/Environment_Variables.md` with the new manager-agent auto-join variables.
- Updated `docs/API.md` to describe the auto-join behavior on `POST /api/v1/groups`.

## Behavior

- If `ACS_GROUP_MANAGER_AGENT_CMD_CHAT` is unset, group creation behaves exactly as before.
- If `ACS_GROUP_MANAGER_AGENT_CMD_CHAT` is set:
  - A `group_member` record with `member_type=manager-agent` is created.
  - The member uses configured defaults or explicit env var values.
  - The `member_interface` includes `adaptor`, `environments` (API base/key/auth when set), `timeout_*`, and `cmd_*` fields.
  - Both group and member creation are atomic; if either fails, the transaction rolls back.

## Testing

- Unit tests added for config parsing and `buildManagerAgentMemberInterface`.
- Integration tests added to verify that a group created with `ACS_GROUP_MANAGER_AGENT_CMD_CHAT` set contains the auto-joined manager-agent member.

## Related Files

- `internal/config/config.go`
- `internal/api/handlers/group.go`
- `internal/api/router.go`
- `docs/Environment_Variables.md`
- `docs/API.md`
- `internal/config/config_test.go`
- `internal/api/handlers/group_test.go`
- `tests/integration/test_api.py`
