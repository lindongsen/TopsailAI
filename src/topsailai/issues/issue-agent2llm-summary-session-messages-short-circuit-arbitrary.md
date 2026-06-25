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
