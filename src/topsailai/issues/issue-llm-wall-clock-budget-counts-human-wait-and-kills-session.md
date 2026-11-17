---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# The LLM wall-clock budget charges the human's interactive wait and then kills the session

## Symptom

Two sessions on host `ai-dev` stopped running within 12 seconds of each other and
were left with `status: error`:

| Session | PID | Project workspace | Start | End |
|---|---|---|---|---|
| `wa-83c784a7ebc8` | 4024294 | `/TopsailAI/src/topsailai_agent_cluster` | 2026-11-16T19:28:59 | 2026-11-17T06:54:08 |
| `wa-9451c9fa3832` | 13835 | `/TopsailAI/src/topsailai` | 2026-11-16T23:06:22 | 2026-11-17T06:54:20 |

Both processes exited with code 1 and an uncaught `LLMRequestTimeoutError`. Neither
was killed by a signal: a SIGKILL would have left `status: running` with
`end_ts: null`, and the launcher recorded `Task failed, exit code: 1`.

## Evidence

Both sessions were blocked on the same interactive prompt for about seven hours,
then answered `1` (Retry), and died on the very next loop iteration.

`wa-83c784a7ebc8`, request `operation_id=73093002177b452d9927a95b52e81a02`:

- Request started `2026-11-16T23:19:09.064834`.
- Attempts 1-18 failed (severe repetition, connection error, then repeated HTTP 503
  `服务器繁忙`). Attempt 18 failed at `23:44:07`.
- `LLM retry attempts exhausted. / 1. Retry the same LLM request / 2. Back to chat /
  3. Exit / Select [1-3]:` was printed at `23:44:07`, when the request had already
  consumed `1497.9s` of its `1800s` budget.
- The answer `1` was read at `2026-11-17T06:53:08`, i.e. after `25741s` (7.15 h) of
  human wait.
- Attempt 19 ran `06:53:08` to `06:54:08` and failed with
  `APITimeoutError, First byte timeout after 60.0s`.
- The next loop iteration raised
  `LLMRequestTimeoutError: request exceeded its wall-clock budget after 26853.2s
  over 19 attempts (budget=1800s)`.

`wa-9451c9fa3832`, request `operation_id=66d3fb46efd343c1b846555aad346948`:

- Request started `2026-11-16T23:26:47.550908`.
- Attempts 1-18 failed with HTTP 503. Attempt 18 failed at `23:47:11`, when the
  request had consumed `1223.4s` of its `1800s` budget.
- The answer `1` was read at `2026-11-17T06:53:20`, after `25569s` (7.1 h).
- Attempt 19 failed with `First byte timeout after 60.0s` at `06:54:20`.
- The next iteration raised
  `LLMRequestTimeoutError: request exceeded its wall-clock budget after 27299.2s
  over 19 attempts (budget=1800s)`.

Both tracebacks end at the budget check, not at a provider call:

```
File ".../ai_base/llm_base.py", line 734, in chat
    self._check_request_wall_clock_budget(
File ".../ai_base/llm_base.py", line 389, in _check_request_wall_clock_budget
    raise LLMRequestTimeoutError(
```

The two sessions loaded different commits (`wa-83c784a7ebc8` started before
`2af5e268`, `wa-9451c9fa3832` after it), which is why the traceback line numbers
differ (`724` vs `734`). The ordering that matters is identical in both versions.

## Root cause

Two independent defects combine.

### 1. The budget measures wall-clock time, so the human's thinking time is charged to the request

`ai_base/llm_base.py` captures `request_started_at = time.monotonic()` once per
logical request (line 709) and compares it against
`TOPSAILAI_LLM_REQUEST_WALL_CLOCK_BUDGET_SEC` (default `1800`) at the top of every
retry iteration (line 734). The documented intent is to bound "every retry attempt
and backoff sleep of that request".

The cycle-exhaustion prompt is read inside that same loop (line 769, via
`ai_base/llm_control/llm_retry.py::read_retry_exhaustion_action`, which blocks on
`policy.input_func`). The budget check sits *before* the prompt, so the prompt is
only shown while the budget still has room, but the time spent waiting for the
human is then charged to the next check. A human who takes longer than the
remaining budget guarantees that the retry they just authorized is killed before
it can run.

In both sessions the prompt appeared with only `302s` and `577s` of budget left,
and the human answered about seven hours later. The budget was therefore already
exhausted by the human's own decision time, and the `retry` choice was honored for
exactly one attempt before the loop refused to continue.

### 2. `LLMRequestTimeoutError` is fatal to the session, unlike the provider timeout it replaces

`LLMRequestTimeoutError` subclasses `ModelServiceError`
(`ai_base/llm_control/exception.py:41`), not `LLMProviderError`. The User2Agent loop
recovers only `LLMBackToChatError`, `LLMRetryExhaustedError` and
`RECOVERABLE_PROVIDER_ERRORS` (`workspace/agent/agent_shell_base.py:82-87`, which
lists `LLMProviderInternalServerError`, `LLMProviderConnectionError`,
`LLMProviderTimeoutError`, `LLMProviderReadError`). Every other exception is
re-raised at line 781-786, then caught by `AgentChat.run()`'s `except Exception`,
which writes `status: error` (line 330-337) and re-raises, so the process dies.

The consequence is inconsistent: the same underlying condition (the provider is
unreachable) merely abandons the turn when it surfaces as
`LLMProviderTimeoutError`, but terminates the whole session when it surfaces as
`LLMRequestTimeoutError`. The budget was introduced to stop a stalled request, and
it does stop the request, but it also destroys the session that the retry loop was
protecting.

## Impact

- Two long-running sessions lost their conversation and their in-flight work.
- The operator's explicit `Retry` choice was silently overridden.
- `LLMRequestFailureLog` reports `elapsed_sec=27299`, which is mostly human wait,
  so the telemetry misattributes a seven-hour idle prompt to a slow provider.
- Any interactive session that leaves a retry-exhaustion prompt unanswered for
  longer than the remaining budget will die the moment the operator answers.

## Suggested direction

- Measure the budget over provider work only: exclude time spent blocked in the
  interactive prompt, for example by pausing the budget around
  `read_retry_exhaustion_action` and resuming it afterwards.
- Re-check the budget immediately after the human chooses `retry`, so an expired
  budget is reported before the prompt rather than after the answer.
- Decide whether `LLMRequestTimeoutError` should abandon the turn like a provider
  timeout instead of terminating the process, and make that decision explicit in
  `RECOVERABLE_PROVIDER_ERRORS` or in the loop's handler list.
- Report provider-work elapsed time separately from total wall-clock time in
  `LLMRequestFailureLog`.
