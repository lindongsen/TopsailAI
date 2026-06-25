# Issue: Agent2LLM `del_agent_messages` drops the system-message prefix

## Location
- File: `/TopsailAI/src/topsailai/workspace/context/agent2llm.py`
- Method: `ContextRuntimeAgent2LLM.del_agent_messages`

## Problem
`del_agent_messages` builds `new_messages` from `self.ai_agent.messages[first_position:]`, removes the requested indexes, and then assigns:

```python
self.ai_agent.messages = new_messages
```

`first_position` is the first non-system message index (from `get_work_memory_first_position`). Any system messages before `first_position` are therefore **dropped** from `ai_agent.messages` even though the method is documented to delete only non-system messages.

## Impact
- System prompts/instructions are silently lost after an agent self-prunes Agent2LLM messages.
- Subsequent LLM calls may receive messages without the required system context, degrading behavior.

## Evidence
```python
first_position = self.ai_agent.get_work_memory_first_position()
...
new_messages = []
for i, msg in enumerate(self.ai_agent.messages[first_position:]):
    ...
self.ai_agent.messages = new_messages   # drops messages[:first_position]
```

## Suggested Direction
Preserve the work-memory prefix when rebuilding the list, e.g.:

```python
self.ai_agent.messages = self.ai_agent.messages[:first_position] + new_messages
```

Then update token accounting as usual.

---

## Resolution

- **Status:** fixed
- **Fix location:** `/TopsailAI/src/topsailai/workspace/context/agent2llm.py`
- **Change made:** In `ContextRuntimeAgent2LLM.del_agent_messages()`, replaced `self.ai_agent.messages = new_messages` with `self.ai_agent.messages = self.ai_agent.messages[:first_position] + new_messages`.
- **Test result:** 34 passed in `tests/unit/workspace/context/test_agent2llm.py`
- **Resolved by:** AIMember.km3-programmer
