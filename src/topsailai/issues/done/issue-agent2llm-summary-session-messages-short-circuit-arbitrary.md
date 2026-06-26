# Issue: Agent2LLM summary session-message keep logic uses arbitrary constants

## Location
- File: `/TopsailAI/src/topsailai/workspace/context/agent2llm.py`
- Method: `ContextRuntimeAgent2LLM.summarize_messages_for_processing`

## Problem
When `TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES=1`, the code decides whether to keep User2Agent session messages in the Agent2LLM context using:

```python
if session_msg_len >= int(ctx_quantity_threshold / 2):
    need_session_messages = False
```

and

```python
if msg_len < (session_msg_len + 17):
    need_session_messages = False
```

The divisor `2` and the magic number `17` are undocumented and arbitrary. They are not mentioned in `docs/Environment_Variables.md` or `env_template`.

## Impact
- Behavior is unpredictable for operators tuning context thresholds.
- A session with just over half the threshold length silently loses session context in Agent2LLM summarization.

## Evidence
```python
if session_msg_len >= int(ctx_quantity_threshold / 2):
    need_session_messages = False
    logger.warning("summary step cannot keep session messages due to it is too long: [%s]", session_msg_len)

if msg_len < (session_msg_len + 17):
    logger.info("no need summarize due to messages too short: [%s]", msg_len)
    return None
```

## Suggested Direction
Expose these constants as environment variables (e.g., `TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO`, `TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES`) or document them clearly.


## Resolution

- Implemented environment variables:
  - `TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO` (default `0.5`)
  - `TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES` (default `17`)
- Fixed a bug where `TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES=0` was ignored due to `or 17` fallback in `workspace/context/agent2llm.py`.
- Updated `env_template` and `docs/Environment_Variables.md` with descriptions and defaults.
- Updated unit tests in `tests/unit/test_topsailai_workspace_context_agent2llm.py`.
- All 46 tests in `test_topsailai_workspace_context_agent2llm.py` pass.
- Issue moved to `issues/done/`.


## Additional Fixes (2026-06-26)
- Fixed `TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO=0` being ignored due to `or 0.5` fallback; now validates `None`/out-of-range values consistently with `TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES`.
- Removed the defensive "use passed-messages due to larger length" fallback in `workspace/context/base.py::_summarize_runtime_messages()` to align with MEMO.md design: `_get_token_calculation_messages()` returns `self.ai_agent.messages` by design when an agent is present.
- Updated related unit tests in `tests/unit/test_topsailai_workspace_context_base.py`, `tests/unit/test_topsailai_workspace_context_ctx_runtime.py`, and `tests/unit/workspace/context/test_agent2llm.py` to match the design.
- Full context test suite passes: 210 passed.
