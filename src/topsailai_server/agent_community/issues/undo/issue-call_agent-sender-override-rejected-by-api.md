---
status: undo
priority: high
component: skills/agent_community_client
---

# Issue: call_agent skill sender override rejected by ACS API

## Summary

The `agent_community_client` skill's `call_agent.py` script sends new messages with explicit `sender_id=ACS_AGENT_ID` and `sender_type=ACS_AGENT_TYPE`. The ACS API rejects this unless the authenticated caller is authorized to send as that sender.

This behavior is **expected and by design**, as recorded in `/TopsailAI/src/topsailai_server/agent_community/MEMO.md`.

## Design Decision

`internal/api/handlers/message.go::resolveSenderIdentity` requires that when `sender_id`/`sender_type` are explicitly provided:

1. The caller must be a member of the group.
2. The requested sender identity must either match the caller's own member record, or be a `manager-agent`.

Therefore, the `agent_community_client` skill's `call_agent.py` script **cannot** override `sender_id`/`sender_type` to send as a `worker-agent`. The skill contract should be understood as only valid for `manager-agent` senders, or the skill should omit explicit sender override and let the API derive the sender from the authenticated caller.

## Original Reproduction Steps

1. Start ACS server with a fresh database and default admin account.
2. Create a group via `group_lifecycle.py create-group`.
3. Add a worker-agent member (e.g. `mock-agent-1`) to the group.
4. Send an initial message to the group and note its `message_id`.
5. Run `call_agent.py` with:
   - `ACS_AGENT_ID=mock-agent-1`
   - `ACS_AGENT_TYPE=worker-agent`
   - `ACS_GROUP_ID=<group_id>`
   - `ACS_MESSAGE_ID=<initial_message_id>`
   - `-m "@mock-agent-1 please respond"`

## Actual Behavior

`call_agent.py` fails at step 1 with:

```
ERROR __main__ Failed to send message: caller is not authorized to send as the specified sender
```

This is the intended API behavior.

## Impact

- The `call_agent` skill cannot be used with worker-agents as originally documented.
- Any external agent using this skill to delegate tasks to another agent must either:
  - Be a `manager-agent` member of the group, or
  - Omit explicit `sender_id`/`sender_type` and let the API derive the sender from the authenticated caller.

## Recommended Resolutions

1. **Update the skill contract/scripts** to omit `sender_id`/`sender_type` and let the server derive them from authentication. This aligns with `docs/API.md`.
2. **Clarify the contract** and require the caller to be a member of the group and the target agent to be a `manager-agent`.

## Related Files

- `/TopsailAI/src/topsailai_server/agent_community/MEMO.md`
- `skills/agent_community_client.md`
- `skills/agent_community_client/scripts/call_agent.py`
- `skills/agent_community_client/scripts/api_client.py`
- `internal/api/handlers/message.go`
- `docs/API.md`
