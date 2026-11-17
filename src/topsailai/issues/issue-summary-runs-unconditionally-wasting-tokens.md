---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: open
---

# Summary runs unconditionally in the dynamic watermark branch

## Symptom

Session `wa-fc746aa24c8c` ran 28 Agent2LLM summarizations inside a single turn,
many at `msg_len` of 25, 26, 27, 47, 48 and 49, far below the configured
quantity threshold of 137. Most of those summaries saved only a few thousand
tokens, so the LLM calls were almost pure waste.

## Evidence

- Pre-summary tokens cluster at 151452-171156. With `summary_safe_limit=217808`
  and `low_limit≈158999`, the safety coefficient `1.05` turns an ordinary
  151600-token context into `159180`, which exceeds LOW by 181 tokens.
- Post-summary tokens fall to 118135-130324 and climb back over LOW within a few
  turns, producing a sawtooth.
- Worst reductions: `25 msgs / 166561 tok -> 17 / 164290` saving 2271,
  `25 / 165419 -> 17 / 162141` saving 3278, `26 / 171156 -> 17 / 161478`
  saving 9678.
- `Heavy Task Trigger` fired once at `16:25:45` and never again.

## Root cause

`workspace/agent/agent_chat_base.py::hook_summarize_messages()` computes
`need_processed_summary` and `need_processing_summary` inside the
`dynamic_summary` branch and then never uses them; both summarize calls run
unconditionally. Because LOW is entered by the `1.05` coefficient rather than by
the configured thresholds, every turn summarizes regardless of
`is_need_summarize_for_processing()`.

`force=True` at HIGH and HARD additionally bypasses the `total_len <= 2` guard,
the `msg_len < session_msg_len + min_extra_messages` guard, and the
`_can_summarize_agent2llm_messages(force=force)` feasibility check.

The existing per-turn counter cannot stop it. `HeavyTaskBase` warns above
`threshold_continuous_summary_times` (default 5) and raises `HeavyTaskError` at
`threshold + 7` (12), but `hook_after_init_prompt` calls `reset_count()` at every
turn start, `reset()` calls it again, and the
`elif dynamic_summary or need_processing_summary` branch clears the counter
whenever a summary returns no answer. The fatal threshold is therefore
effectively unreachable, and when it does fire it terminates the task instead of
skipping the wasted summarization.

## Impact

Every ineffective summary is a full LLM call over the entire context. 28 calls
in one turn, most saving under 10k tokens, is pure waste and directly inflates
token spend. The sawtooth also keeps the context permanently near the LOW
boundary, so the waste repeats every turn.

## Proposed fix

- Add an effectiveness guard that skips summarization when the previous summary
  reduced tokens by less than a configurable ratio.
- Add a soft consecutive cap that skips summarization instead of terminating the
  task.
- Make the per-turn counter reachable by not resetting it on every turn and not
  clearing it when a summary returns no answer.
- Stop letting `force` bypass the feasibility check.

## Constraint

`tests/unit/test_topsailai_workspace_agent_agent_chat_base_context_guard.py::test_low_runs_ordinary_summarization_at_current_checkpoint`
asserts that LOW summarizes both layers unconditionally with `force=False`.
Gating LOW on the `need_*` flags would break that test and contradict the
documented intent, so any guard must be additive rather than a rewrite of LOW
semantics.

## Runtime mitigation applied

`TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT` was raised to `1000000` and both token
thresholds to `700000` in the affected process memory only, moving the LOW
boundary from about 159k to about 702k tokens. This reduces the frequency but
does not remove the unconditional call, so the defect remains.
