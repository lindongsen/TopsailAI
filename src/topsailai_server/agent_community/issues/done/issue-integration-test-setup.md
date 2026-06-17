---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Integration Test Setup Issues

## Problem

Integration tests fail because the externally-started ACS server is misconfigured:

1. **Database mismatch**: The server uses SQLite (`ACS_DATABASE_DRIVER=sqlite`) while Python tests write fixture rows directly to PostgreSQL (`localhost:5432`, `acs`/`acs`). API queries therefore read from SQLite and cannot see PostgreSQL rows.
2. **Agent commands not resolvable**: The server resolves agent-interface commands as extension-less names (`topsailai_agent_cmd_check_health`, `topsailai_agent_cmd_check_status`, `topsailai_agent_cmd_chat`), but only `.py` versions exist in `scripts/topsailai_agent_cmd/`. The commands are also not in the server `PATH`.

## Affected Tests

- `test_api.py::TestMessageProcessedMsgID::test_list_messages_by_processed_msg_id`
- `test_member_status.py::TestMemberStatusActiveUpdate::test_member_status_processing_then_idle_success`
- `test_member_status.py::TestMemberStatusActiveUpdate::test_member_status_idle_after_agent_failure`

## Fix Plan

1. Create extension-less wrapper scripts in `scripts/topsailai_agent_cmd/` that delegate to the existing `.py` scripts.
2. Add an integration-test service management script (`tests/integration/manage_test_server.sh`) that starts/stops the ACS server with PostgreSQL environment variables and the agent-command directory in `PATH`.
3. Update `Makefile` `test-integration` target to use the service management script so `make test-integration` is self-contained.

## Files to Modify

- `scripts/topsailai_agent_cmd/topsailai_agent_cmd_check_health` (new)
- `scripts/topsailai_agent_cmd/topsailai_agent_cmd_check_status` (new)
- `scripts/topsailai_agent_cmd/topsailai_agent_cmd_chat` (new)
- `tests/integration/manage_test_server.sh` (new)
- `Makefile`
