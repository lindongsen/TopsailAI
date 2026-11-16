---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# HeavyTask cannot observe a request stuck inside the retry loop

## Symptom

Session `wa-fc746aa24c8c` spent 67 minutes inside one logical LLM request while
retrying it. HeavyTask never fired: `Heavy Task Trigger` appears zero times in
both log files, and both the soft reminder and the hard interrupt stayed
unreachable for the whole stall.

## Evidence

- `before_summary_generate` timestamps jump from `16:57:48.994249` to
  `18:05:30.184761`, a 67-minute gap with no hook entry.
- `llm.request.end` for `operation_id=a9db26919d574414a4732727b22fb189`:
  `attempt_count=12`, `duration_sec=4029.748`.
- The retry loop has no wall-clock deadline: `attempts_per_cycle=18` hardcoded,
  `max_manual_retry_cycles=7`, so up to 144 attempts; 30 s sleep per
  `ModelServiceError` and up to 120 s generic backoff.
- `TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT=180` is paired with
  `TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE=0`, so it only warns and does not
  bound the request.

## Root cause

`workspace/agent/agent_chat_base.py` increments
`heavy_task.continuous_summary_times` only after
`summarize_messages_for_processing()` returns. That call wraps the entire retry
loop in `ai_base/llm_base.py`, so while the loop keeps resending the request the
hook is never re-entered and the counter stays frozen. Both HeavyTask stages
compare that counter against a threshold, so neither can trigger.

The blind spot is structural, not a tuning problem: lowering the threshold
cannot help because the counter never moves.

## Fix

Bound one whole logical LLM request by a wall-clock budget measured from the
start of the request, covering every retry attempt plus every backoff sleep.

- `ai_base/llm_control/exception.py`: new `LLMRequestTimeoutError(ModelServiceError)`.
- `ai_base/llm_control/configuration.py`: `get_llm_request_wall_clock_budget()`
  reading `TOPSAILAI_LLM_REQUEST_WALL_CLOCK_BUDGET_SEC`, default `1800`.
- `ai_base/llm_base.py`: read the budget once per request, check it at the top
  of every attempt before any prompt or sleep, and catch
  `LLMRequestTimeoutError` before the generic `ModelServiceError` branch.

The handler order matters: `except ModelServiceError` treats the error as
retryable and would resend the very request the budget exists to stop.

## Scope note

The budget bounds the stall but does not make HeavyTask observe it. HeavyTask
still counts completed summaries only, which is the intended two-stage design
and must not be changed. The budget converts an unbounded stall into a bounded
failure that the existing `ModelServiceError` handling already surfaces.

## Verification

- New unit test file: 21 passed.
- W1, W2 and W4 test files together: 85 passed.
- Affected suites across 13 files: 344 passed.
- Removing the specialized handler: 2 failed. Removing the in-loop check:
  2 failed. Both restored: 21 passed.

## Status

Fixed in `1b16c1f5`. Not deployed.
