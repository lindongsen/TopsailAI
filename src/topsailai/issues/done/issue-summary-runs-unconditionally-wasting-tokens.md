---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: resolved
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

## Resolution

### Corrected root cause: the checkpoint runs per iteration, not per turn

The issue described "28 summarizations inside a single turn". A probe showed the
real granularity: `hooks_pre_chat` is invoked once per **Agent2LLM ReAct
iteration** (`ai_base/agent_base.py:576`), not once per User2Agent turn. So the
28 calls were 28 iterations, each re-entering LOW and re-summarizing. This
matters because it means no per-turn counter can ever bound the waste: the
counter is reset at turn start and the loop that wastes tokens lives inside the
turn.

Probe before the fix, three consecutive LOW iterations:

```
iteration 1: processed_calls=1, processing_calls=1, heavy_task_count=1
iteration 2: processed_calls=2, processing_calls=2, heavy_task_count=2
iteration 3: processed_calls=3, processing_calls=3, heavy_task_count=3
total LLM summarization calls: 6
```

`is_need_summarize_for_processing()` returned `False` on every one of those
iterations, confirming the two `need_*` variables are computed and unused for
gating. A log line from the incident shows the same shape:
`before=151657 after=159896 level=LOW` — the summary made the context larger,
and the next iteration was still LOW and summarized again.

### Fix: additive LOW-only effectiveness guard

Implemented option A from the proposed list. The guard is additive, so
`test_low_runs_ordinary_summarization_at_current_checkpoint` keeps passing
unchanged: LOW still summarizes unconditionally the first time, and only a
*repeat* LOW checkpoint is skipped, and only when the previous summary already
proved ineffective.

- `workspace/agent/agent_chat_base.py` records the token reduction ratio of each
  completed summary (`_record_summary_reduction`) and skips the next LOW
  checkpoint when that ratio is below
  `TOPSAILAI_CONTEXT_SUMMARY_MIN_REDUCTION_RATIO` (default `0.10`).
- HIGH and HARD are untouched and stay forced, so a context that keeps growing
  is still compressed before it can exceed the send limit. HARD remains the last
  chance and is never skipped.
- The marker is cleared at turn start (`hook_after_init_prompt`, `reset()`), so
  a new turn always gets one fresh summarization attempt.
- A skipped checkpoint leaves the marker untouched, so LOW keeps skipping until
  a HIGH or HARD forced summary produces a real reduction.
- The skip is observable on all three channels required by project memory: a
  `print_warning` (rare and consequential, so not `print_step` or `print_info`),
  a `logger.warning` with the decision inputs, and a bounded
  `context.summary.skipped_ineffective_low` event wrapped in `try/except` so
  observability can never interrupt the business path.
- `0` or below disables the guard entirely; invalid, non-finite or out-of-range
  values log a warning and fall back to `0.10`.

Probe after the fix, same three iterations:

```
iteration 1: processed_calls=1, processing_calls=1, heavy_task_count=1
Warning: skip LOW summarization: the previous summary reduced tokens by 0.0050, below the required 0.1, current_tokens=597
iteration 2: processed_calls=1, processing_calls=1, heavy_task_count=0
Warning: skip LOW summarization: the previous summary reduced tokens by 0.0050, below the required 0.1, current_tokens=594
iteration 3: processed_calls=1, processing_calls=1, heavy_task_count=0
total LLM summarization calls: 2
```

**6 calls reduced to 2.** The remaining 2 are the two layers of the first
checkpoint, which is the intended behaviour.

### Verification

| Check | Result |
|---|---|
| `ast.parse` syntax check | syntax OK |
| Guard test file | 19 passed (1.84s) |
| `tests/unit/workspace/agent` + `test_..._agent_chat_base.py` + `tests/unit/workspace/context` | 347 passed (7.39s) |
| `tests/run_tests.py` on the guard file | PASS, 19 cases, 0 failures |
| Probe before fix | 6 summarization calls over 3 LOW iterations |
| Probe after fix | 2 summarization calls over 3 LOW iterations |
| Negative control (guard disabled) | 3 calls vs 1 with guard active |
| Event probe | 1 event, type `context.summary.skipped_ineffective_low`, bounded payload |

Nine tests were added: skip on ineffective repeat, keep summarizing on effective
repeat, HIGH stays forced, HARD stays forced, `0` disables the guard, marker
cleared at turn start, invalid ratio falls back to default, the skip records a
bounded event with an exact key set, and the skip survives a failing event
recorder.

### Pristine-HEAD attribution

`tests/unit/workspace` as a whole reports 18 failures in
`test_session_stats_service.py`. A detached worktree at `HEAD` with explicit
`PYTHONPATH` and a verified `module: .../pristine_wt/src/topsailai/...` path
reproduced the identical 18 failures, so they are **PRE-EXISTING cross-file
pollution**, not caused by this change. That file passes alone (64 passed) and
contains zero references to `agent_chat_base`. The worktree was removed with a
logged deletion message.

### Decision provenance

`MEMORY.md` requires explicit approval before behavioural changes. The choice
among four candidate fixes was put to the Human, the question timed out at 600
seconds, and the documented default applied: **option A, LOW-only effectiveness
guard, ratio 0.10**. This is a timeout default, not explicit approval, and is
recorded here so the Human can reverse it.

### Deferred

- `need_processed_summary` is still computed and unused. Removing it broke the
  pre-existing `test_high_runs_forced_summarization_and_bypasses_disabled_legacy_thresholds`
  (`Expected 'is_need_summarize_for_processed' to be called once. Called 0
  times.`), which encodes the current contract. Removing the variable is a
  separate cleanup with its own test update.
- The soft consecutive cap that skips instead of terminating the task.
- Making the per-turn counter reachable across turns.
- Stopping `force` from bypassing the feasibility check.

### Commits

- `bf73517d fix: skip ineffective low-watermark summarization` (3 files, 348
  insertions, 6 deletions, 8 hunks in `agent_chat_base.py`).
