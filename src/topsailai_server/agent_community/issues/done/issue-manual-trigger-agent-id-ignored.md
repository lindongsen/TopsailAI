---
maintainer: AI
status: fixed
related_files:
  - tests/integration/test_agent_trigger_api.py
  - docs/API.md
labels:
  - bug
  - agent-trigger
  - manual-trigger
---

# Manual trigger ignores the provided agent_id and routes to manager-agent

## Summary

When calling `POST /api/v1/groups/{group_id}/messages/{message_id}/trigger` with
an explicit `agent_id` in the request body, the server accepts the request and
returns `status: pending`, but the actual agent invocation is routed to the
auto-joined `manager-agent` instead of the requested worker-agent.

## Expected Behavior

Per `docs/API.md`:

> `agent_id`: Optional. If provided, only this specific agent will be triggered.
> Must be a member of the group with type ending in `-agent`.

The response message should be sent by the requested `agent_id`.

## Actual Behavior

The response message is sent by `manager-agent` (the auto-joined manager-agent),
not the requested worker-agent. The mock agent invocation records confirm that
`manager-agent` was invoked even though the request specified a worker-agent id.

## Steps to Reproduce

1. Start ACS with `ACS_GROUP_MANAGER_AGENT_CMD_CHAT` configured.
2. Create a group (auto-joins `manager-agent`).
3. Add a worker-agent member.
4. Send a user message.
5. Call `POST /api/v1/groups/{group_id}/messages/{message_id}/trigger` with
   `{"agent_id": "worker-xxx"}`.
6. Wait for the response message and inspect `sender_id`.

## Impact

- Callers cannot manually route processing to a specific agent.
- The manager-agent may be overloaded with manual triggers intended for
  worker-agents.
- Violates the documented API contract.

## Workaround

Integration tests currently verify that a response is generated and that the
manager-agent was invoked, without asserting that the requested agent id was
used.

## References

- `docs/API.md` - Trigger Message endpoint
- `tests/integration/test_agent_trigger_api.py` - `TestManualTrigger`
