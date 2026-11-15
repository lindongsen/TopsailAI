---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Token counting returns 0 on a literal special token, which silently disables summarization

## Symptom

Session `wa-fc746aa24c8c` (name `拉取代码编译部署节点`, pid `741456`) stopped
summarizing its Agent2LLM context. The quantity threshold kept firing, but every
attempt was skipped, so the message count grew from 22 to 685 and the prompt
reached 303k-327k tokens.

The operator reported this as "a session that previously set runtime environment
variables no longer summarizes automatically", which suggested a missing
environment variable. No environment variable is missing.

## Evidence

- Last successful summary: `2026-11-15 20:36:51`, `msg_len=[22]`.
- First skip: `2026-11-15 20:50:19`. Total skips: 276, all with
  `reason=estimated_summary_not_smaller`.
- Every skip line reports `current_tokens=0` and `summary_input_tokens=0` while
  `preserved_tokens` is a plausible `~84000`:
  `current_tokens=0, preserved_tokens=83818, summary_token_reserve=4096,
  estimated_after_tokens=87914, summary_input_tokens=0,
  summary_safe_limit=217808, token_threshold=196000`.
- Live `agent.tokens` in the same process reports `Agent2LLM: Messages: 685,
  Estimated tokens: 0` but `User2Agent: Messages: 7, Estimated tokens: 20,812`.
  Token counting fails only for the layer whose text contains the special token.
- `TokenStat` in the same session reports `current_prompt_tokens=303018` and
  later `327346`, so the real context is far from zero.
- The literal string `<|endoftext|>` entered the context at `2026-11-15 20:42:04`
  through a `cmd_tool_exec_cmd` result that dumped Go standard-library strings
  (`strings /opt/...`), which is 8 minutes before the first skip.
- Live environment values equal the startup snapshot, and this session recorded
  no `env.set` at all, so no runtime override is involved.

## Root cause

`context/token.py::count_tokens()` calls `encoding.encode(text)` without
`disallowed_special`, so tiktoken raises
`ValueError: Encountered text corresponding to disallowed special token
'<|endoftext|>'`. The blanket `except Exception` then returns `0`.

`0` is not treated as "unknown". It flows into two decisions:

1. `workspace/context/agent2llm.py::_can_summarize_agent2llm_messages()` compares
   `estimated_after_tokens >= current_tokens`, i.e. `87914 >= 0`, which is always
   true, so the reason becomes `estimated_summary_not_smaller` and summarization
   is skipped forever.
2. `workspace/context/base.py::_check_dynamic_summary_feasibility()` computes
   `safe_input_tokens = 0 * 1.05 = 0`, so the model-capacity guard passes
   vacuously. The guard that should stop an oversized summary request is blind at
   exactly the moment the context is oversized.

The second effect also explains why the session keeps sending 303k-token prompts
while `TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT=256000`: the watermark and feasibility
checks both read the same zero.

## Why the environment-variable theory is wrong

- `TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD=196000`,
  `TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD=137`,
  `TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT=256000` and the watermark ratios are all
  set and live.
- During the earlier override era (`20:50:19`-`21:21:01`) the effective values
  were `summary_safe_limit=961808` and `token_threshold=700000`, i.e. the
  operator had already raised the ceiling to `1000000`. All 118 skips in that
  window still reported `estimated_summary_not_smaller`, so a larger ceiling
  cannot fix it.
- No environment variable can restore `current_tokens`, because
  `_get_current_tokens(self.ai_agent.messages)` passes explicit messages and
  therefore always counts in realtime, ignoring
  `TOPSAILAI_REALTIME_TOKEN_CALCULATION`.

## Secondary configuration mismatch

`TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT=256000` with
`TOPSAILAI_MAX_COMPLETION_TOKENS=30000` and a `8192` margin yields
`send_limit=226000` and `summary_safe_limit=217808`, while the real prompt is
already 303k-327k tokens. Once token counting is fixed, the same session would be
blocked by `summary_input_exceeds_safe_limit` instead. The model registry entry
for `DeepSeek-V4-Flash-Preview` declares no `max_context`, so the real capacity
is unrecorded and the configured value is the only authority.

## Proposed fix

1. Count special-token text as ordinary text instead of failing:
   `encoding.encode(text, disallowed_special=())` in `count_tokens()` and
   `count_tokens_for_model()`. Measured on the same input, the current path
   returns `0` while `disallowed_special=()` returns the correct count.
2. Stop treating a counting failure as a real zero. Return `None` on failure so
   callers can distinguish "unknown" from "empty", and make
   `_can_summarize_agent2llm_messages()` skip the `estimated_summary_not_smaller`
   comparison when the count is unavailable rather than comparing against `0`.
3. Make `_check_dynamic_summary_feasibility()` fail closed when the input count
   is unavailable, instead of passing the capacity guard vacuously.
4. Align `TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT` with the model's real capacity and
   record `max_context` for the model in the registry.

## Impact

Any session whose tool output contains a literal special-token string loses
automatic summarization permanently for the rest of its life, because the
offending text stays in the context. The failure is silent: the trigger log line
still appears, so the session looks like it is summarizing while it grows without
bound.
