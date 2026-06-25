# Issue: User2Agent token threshold check uses Agent2LLM token count

## Location
- File: `/TopsailAI/src/topsailai/workspace/context/ctx_runtime.py`
- Method: `ContextRuntimeData.is_need_summarize_for_processed`

## Problem
`is_need_summarize_for_processed` calls `self._get_current_tokens()` without `realtime=True` and without overriding `_get_token_calculation_messages` in a way that is guaranteed at call time. The base implementation returns `self.ai_agent.messages` when `self.ai_agent` exists:

```python
def _get_token_calculation_messages(self):
    if self.ai_agent:
        return self.ai_agent.messages
    return self.messages
```

Although `ctx_runtime.py` overrides this method to return `self.messages`, the override is defined **after** `is_need_summarize_for_processed` in the same class. More critically, when `realtime=False` (the default), `_get_current_tokens` bypasses the override entirely and reads `self.ai_agent.llm_model.tokenStat.current_tokens`, which reflects **Agent2LLM** tokens, not User2Agent session tokens.

Therefore `TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD` is compared against the wrong token counter.

## Impact
- User2Agent token-based summarization is triggered (or not triggered) based on Agent2LLM token usage.
- Violates the documented behavior in `docs/Environment_Variables.md`.

## Evidence
```python
def is_need_summarize_for_processed(self) -> bool:
    ...
    if token_threshold > 0:
        current_tokens = self._get_current_tokens() or 0   # realtime defaults to False
        if current_tokens > token_threshold:
            ...
```

```python
# base.py _get_current_tokens when not realtime
try:
    if self.ai_agent and self.ai_agent.llm_model and self.ai_agent.llm_model.tokenStat:
        return int(self.ai_agent.llm_model.tokenStat.current_tokens)
```

## Suggested Direction
Force real-time token calculation for the User2Agent layer, or maintain a separate `tokenStat` for User2Agent session messages. At minimum, `is_need_summarize_for_processed` should call `self._get_current_tokens(realtime=True)` so the override in `ctx_runtime.py` is used.
