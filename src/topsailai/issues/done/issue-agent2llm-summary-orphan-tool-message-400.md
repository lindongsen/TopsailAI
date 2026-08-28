---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
references:
  - utils/message_tool.py
  - ai_base/llm_hooks/hook_before_chat/tool_call_pairing.py
  - ai_base/llm_hooks/executor.py
  - ai_base/llm_base.py
  - workspace/context/agent2llm.py
  - workspace/context/ctx_runtime.py
  - docs/Environment_Variables.md
---

# Issue: Sticky `400 No tool call found for function call output` From an Orphaned Tool Message

## Status

Fixed and committed (fixes A-D plus docs, independently reviewed). Recorded here as resolved; the operational mitigation below still applies to already-deployed processes.

## Symptom

An AI team member agent (`AIMember.gpt56sol-programmer`, model `gpt-5.6-sol`, session `20260827T222012`, pid `2364962`) failed every LLM call from 2026-08-28 12:13:48 to at least 12:15:37 with the identical provider error and the identical call id:

```
Error: !!! [3] BadRequestError, Error code: 400 - {'error': {'message': '{
  "error": {
    "message": "No tool call found for function call output with call_id fc_sJRQx5pXlYGYW7c6yqkUeUeB.",
    "type": "invalid_request_error", "param": "input", "code": null } }',
  'type': 'gateway_error', 'code': 400}}
Error: [4] blocking chat 20s ...
```

Attempts `[3]`, `[4]`, `[5]` ... repeated the same failure with backoff 20s -> 25s -> 30s. The failure was deterministic, not transient: the payload was byte-identical on every attempt, so the retry loop could never recover and blocked roughly 680 seconds before dying with `chat to LLM is failed`.

## Root Cause

`workspace/context/agent2llm.py` rebuilt the Agent2LLM context after summarization using a **count-based** tail window (`messages[-tail_offset_to_keep:]`). The assistant message carrying `tool_calls=call_sJRQx5pXlYGYW7c6yqkUeUeB` sat at index `-5` and was replaced by the summary answer, while its `role="tool"` reply at index `-4` was preserved verbatim. The rebuilt list therefore contained a tool output with no owning assistant tool call, which the provider rejects for the whole request.

### Evidence Chain

| Time | Evidence |
|------|----------|
| 12:13:44.755 | `[TokenStat] {'current_tokens': 109794, 'msg_count': 75}` — summarization triggered |
| 12:13:44.759 | `[Agent2LLM] [Summarization] head_offset_to_keep=0, tail_offset_to_keep=4, last_user_message_to_keep=1` |
| 12:13:44.850 | `summarize_processing` after: `messages=15` — rebuilt list contains `role=tool` with `tool_call_id=call_sJRQx5pXlYGYW7c6yqkUeUeB` and no preceding assistant declaring it |
| 12:13:48.694 | First `400 Bad Request` — 3.8 s after the rebuild, i.e. the rebuilt list was the first poisoned payload |
| 12:14:41+ | Same call id repeats for every retry; the sanitizer log never mentions this id |

The tail window immediately after the orphan held a fully intact assistant+tool pair, proving the window boundary can straddle a call group.

### Enabling Configuration

The deployed agent work folder `.env.local` sets `TOPSAILAI_CONTEXT_MESSAGES_TAIL_OFFSET_TO_KEEP=4`, while `env_template` and the deployed `.env` both use the documented default `0`. The non-default value created the split window. The divergence is a configuration-drift risk on its own and should be reconciled.

### Amplifier

`ai_base/llm_base.py::chat()` treated this deterministic request-shape 400 as transient: its `except openai.BadRequestError` branch only raised for the `exceed` / `maximum context` keywords and otherwise retried, so 18 attempts burned the whole backoff budget.

## Fixes

### A — Request-boundary sanitizer

Shared helpers `extract_tool_call_ids()` and `drop_orphaned_tool_messages()` in `utils/message_tool.py`, wired as the pre-chat hook `ai_base/llm_hooks/hook_before_chat/tool_call_pairing.py` and registered in the DEFAULT `TOPSAILAI_HOOK_BEFORE_LLM_CHAT` list (`ai_base/llm_hooks/executor.py`). `workspace/context/agent.py::_drop_orphaned_tool_messages()` now delegates to the shared helper. Covers every producer, including the multimodal path, which uses the same hook key.

### B — Pair-atomic summarization windows

`expand_tail_start_for_tool_pairing()` in `utils/message_tool.py` expands a count-based tail window backwards so it never starts with an orphaned tool result. Used by `workspace/context/agent2llm.py` (`_build_agent2llm_summary_partitions`, `summarize_messages_for_processing`) and `workspace/context/ctx_runtime.py` (`_build_user2agent_summary_partitions`, the persisted raw delete range, and the in-memory rebuild). Expansion is bounded by `max(len(head_portion), head_offset_to_keep)` so it can never swallow the head or cross into the summarized region.

### C — Pair-aware index pruning

`expand_indexes_for_tool_pairing()` in `utils/message_tool.py`, used by `workspace/context/agent2llm.py::del_agent_messages()`: deleting a tool result also removes its owning assistant and sibling results, and deleting the assistant removes its results. `del_session_messages()` (User2Agent) is intentionally unchanged — the session layer stores `tool_calls` stringified (`context/chat_history_manager/__base.py:299-303`), so pairing is undetectable there.

### D — Fail fast on deterministic request-shape 400

`ai_base/llm_base.py`: module constant `_LLM_NON_RETRYABLE_BAD_REQUEST_MARKERS` (`no tool call found`, `function_call_output`, `tool_call_id`) plus `_match_non_retryable_bad_request()`. A match raises immediately with an actionable message naming the matched marker and the likely orphaned-tool-message cause, instead of ~680 s of retries. `TOPSAILAI_LLM_NON_RETRYABLE_BAD_REQUEST_MARKERS` (`;`-separated) extends the built-ins; the built-ins can never be disabled.

## Operational Mitigation (no code change)

Set `TOPSAILAI_CONTEXT_MESSAGES_TAIL_OFFSET_TO_KEEP=0` in the deployed agent work folder `.env.local` (restoring the `env_template` default) and restart affected processes. This removes the split window that produced the orphan. Fixes A-D make the failure impossible to reproduce regardless of this setting.

## Verification

| Scope | Result |
|-------|--------|
| New pairing / message-tool tests | 51 passed |
| `agent2llm` + `ctx_runtime` + `agent_tool` | 181 passed |
| `llm_control/message` + `base_class` + `prompt_base` + `multimodal/llm_base` | 212 passed |
| `test_topsailai_ai_base_llm_base.py` | 67 passed, 5.1 s |
| End-to-end probe through `format_messages()` with the incident payload | orphan removed, intact pair preserved |

## Open Questions / Follow-Ups

- **Trailing assistant `tool_calls` without outputs is deliberately NOT dropped.** No repository or provider evidence shows a 400 for an assistant tool call whose outputs are missing, and the observed failure was exclusively about orphaned outputs. Dropping such a message would risk discarding a legitimate in-flight tool call. Revisit only if a provider error proves otherwise.
- **`ai_base/llm_base.py` is 1106 lines**, over the 700-line guideline (pre-existing; fix D added 51 purely additive lines). Future split candidate.
- **Eight legacy tests in `tests/unit/test_topsailai_ai_base_llm_base.py` now receive a plain `list` for `mock_sleep`** instead of a `MagicMock`, because the global-`time` patch was replaced by a module-local patch. Safe today (the symbol is never asserted), but a future `mock_sleep.assert_called()` would fail with `AttributeError`.
- **`format_messages()` uses `if new_messages:`**, so an empty sanitizer result would be discarded in favour of the unsanitized original. Harmless today because `only_one_system_message` runs first and guarantees a non-empty list.
- **Configuration drift:** the deployed agent work folder `.env.local` diverges from `env_template` for `TOPSAILAI_CONTEXT_MESSAGES_TAIL_OFFSET_TO_KEEP` (`4` vs `0`). Reconcile to avoid re-creating producer-side window splits.
