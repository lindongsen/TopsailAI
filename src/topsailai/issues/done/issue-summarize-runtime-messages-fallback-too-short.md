# Issue: `_summarize_runtime_messages` falls back to short message lists

## Location
- File: `/TopsailAI/src/topsailai/workspace/context/base.py`
- Method: `ContextRuntimeBase._summarize_runtime_messages`

## Problem
In runtime summary mode, the method prefers `self.ai_agent.messages[:]`. If that list has fewer than 7 messages, it falls back to the caller-provided `messages` argument:

```python
all_messages = self.ai_agent.messages[:] if self.ai_agent else None
if not all_messages or len(all_messages) < 7:
    all_messages = messages
```

For User2Agent summarization, `self.ai_agent.messages` may be empty or short even when `self.messages` (the session) is long, because the agent may not have run yet. The fallback to `messages` is then used, but the threshold checks in the callers already validated `self.messages` or `self.ai_agent.messages`. Using a different message source for the summary than for the threshold decision can lead to summarizing the wrong context.

## Impact
- The LLM may summarize a short/incorrect context while the threshold was triggered by a different, larger context.
- Wastes an LLM call and produces a misleading summary.

## Evidence
```python
all_messages = self.ai_agent.messages[:] if self.ai_agent else None
if not all_messages or len(all_messages) < 7:
    all_messages = messages
```

## Suggested Direction
Use the layer-appropriate message source directly (`self.messages` for User2Agent, `self.ai_agent.messages` for Agent2LLM) and do not fall back to the caller argument based on an arbitrary length check. The callers should pass the correct source, or the base method should rely on `_get_token_calculation_messages`.
