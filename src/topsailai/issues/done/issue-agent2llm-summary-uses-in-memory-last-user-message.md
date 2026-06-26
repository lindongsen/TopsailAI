# Issue: Agent2LLM summary uses in-memory `last_user_message` from User2Agent session

## Location
- File: `/TopsailAI/src/topsailai/workspace/context/agent2llm.py`
- Method: `ContextRuntimeAgent2LLM.summarize_messages_for_processing`

## Problem
The method preserves the tail using:

```python
last_user_msg = self.last_user_message
```

`last_user_message` is defined in `base.py` and scans `self.messages` (the **User2Agent** session store), not `self.ai_agent.messages` (the **Agent2LLM** runtime store). In Agent2LLM summarization, the "last user message" that should be preserved is the last user message within the Agent2LLM context, which may differ from the last user message in the persisted session.

## Impact
- The wrong tail message may be preserved after Agent2LLM summarization.
- The ReAct loop can lose the most recent user/tool observation that it actually needs to respond to.

## Evidence
```python
# base.py
@property
def last_user_message(self):
    last_user_msg = None
    for msg in reversed(self.messages):   # User2Agent session messages
        msg_dict = json_tool.json_load(msg)
        if msg_dict["role"] == ROLE_USER:
            last_user_msg = msg
            break
    return last_user_msg
```

```python
# agent2llm.py
last_user_msg = self.last_user_message
```

## Suggested Direction
Add an Agent2LLM-specific helper that scans `self.ai_agent.messages` for the last user message, or parameterize `last_user_message` to accept a message source.


---

## Resolution

- **Status:** closed as expected behavior
- **Reason:** Per `MEMO.md`, `last_user_message` intentionally scans `self.messages` (User2Agent persisted session layer) rather than `self.ai_agent.messages` (Agent2LLM ephemeral context). The tail message to preserve is the most recent real human input, not an internal tool observation or ReAct turn.
- **Verified by:** AIMember.km2-reviewer
- **Date:** 2026-06-26
