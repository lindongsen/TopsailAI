# Issue: Agent2LLM summary updates tokenStat with full messages instead of delta

## Location
- File: `/TopsailAI/src/topsailai/workspace/context/agent2llm.py`
- Method: `ContextRuntimeAgent2LLM.summarize_messages_for_processing`

## Problem
After rebuilding `self.ai_agent.messages`, the code calls:

```python
self.ai_agent.llm_model.tokenStat.add_msgs(self.ai_agent.messages)
```

`add_msgs` is typically additive (it accumulates token counts). Calling it with the **entire** rebuilt message list after summarization double-counts the head prefix and any retained messages that were already accounted for. This inflates `tokenStat.current_tokens` and can cause premature token-threshold triggers or misleading logs.

## Impact
- Token accounting becomes inaccurate after Agent2LLM summarization.
- May trigger false "token exceeded" alerts or hide real token growth.

## Evidence
```python
self.ai_agent.messages = self.ai_agent.messages[:index] + new_messages
self.ai_agent.llm_model.tokenStat.add_msgs(self.ai_agent.messages)
```

## Suggested Direction
Either:
1. Reset tokenStat and re-add the final messages (`tokenStat.reset()` then `add_msgs(self.ai_agent.messages)`), or
2. Only `add_msgs` for the newly added summary message (and any net-new retained messages).

Make the behavior consistent with `ctx_runtime.py`, which does not call `add_msgs` after summarization and relies on `_get_current_tokens(realtime=True)` for logging.
