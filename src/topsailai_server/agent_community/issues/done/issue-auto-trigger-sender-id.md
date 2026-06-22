---
maintainer: AI
status: open
related_files:
  - tests/integration/test_agent_trigger_api.py
labels:
  - bug
  - agent-trigger
  - auto-trigger
---

# Auto-trigger uses original sender account id instead of manager-agent member id

## Summary

When a message is auto-triggered (single-user group or idle timeout), the
resulting agent response message is created with the original human sender's
`account_id` as `sender_id` and `user` as `sender_type`, instead of the
auto-joined `manager-agent` member id and `manager-agent` type.

## Expected Behavior

Per `docs/API.md` and `ORIGIN.md`, auto-triggered messages should be processed
by the group's `manager-agent`. The response message should have:

- `sender_id`: `manager-agent` (or the configured manager-agent member id)
- `sender_type`: `manager-agent`
- `processed_msg_id`: the id of the original user message

## Actual Behavior

The response message is created with:

- `sender_id`: the original human sender's account id (e.g. `acc-55733ef5...`)
- `sender_type`: `user`
- `processed_msg_id`: the id of the original user message

The mock agent invocation records confirm that `manager-agent` is invoked, so
the trigger routing is correct; only the response message metadata is wrong.

## Steps to Reproduce

1. Start ACS with `ACS_GROUP_MANAGER_AGENT_CMD_CHAT` configured.
2. Create a group (auto-joins `manager-agent`).
3. Add one user member.
4. Send a message with no mentions.
5. Wait for auto-trigger.
6. List messages and inspect the response message's `sender_id` and
   `sender_type`.

## Impact

- Breaks the contract that agent responses are identifiable by `sender_type`
  ending in `-agent`.
- May cause `NO_TRIGGER_CASES` logic to misclassify auto-trigger responses,
  potentially leading to re-trigger loops or skipped triggers.
- Confuses clients that display message sender information.

## Workaround

Integration tests currently verify that a response exists and that the
manager-agent was invoked, without asserting the exact `sender_id`/`sender_type`.

## References

- `docs/API.md` - Agent Triggering / Auto-Trigger
- `ORIGIN.md` - How to trigger agent / auto-trigger
- `tests/integration/test_agent_trigger_api.py` - `TestAutoTrigger`
