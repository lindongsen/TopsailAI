# ACS Project Decisions

## 2026-06-26: call_agent sender override behavior is by design

**Issue:** `issues/issue-call_agent-sender-override-rejected-by-api.md`

**Decision:** The current API behavior is expected and by design.

`internal/api/handlers/message.go::resolveSenderIdentity` requires that when `sender_id`/`sender_type` are explicitly provided:

1. The caller must be a member of the group.
2. The requested sender identity must either match the caller's own member record, or be a `manager-agent`.

**Implication:** The `agent_community_client` skill's `call_agent.py` script cannot override `sender_id`/`sender_type` to send as a `worker-agent`. The skill contract should be understood as only valid for `manager-agent` senders, or the skill should omit explicit sender override and let the API derive the sender from the authenticated caller.

**Recorded by:** km3-programmer
