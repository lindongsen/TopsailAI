---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: resolved
---

# Issue: Interactive session terminates the process on a severe-repetition verdict

## Symptom

Session `wa-7129db647944` (pid `2783340`, workspace `/TopsailAI/src/topsailai_connector`)
died at `2026-11-19T17:01:47` with `status: error` and launcher exit code `1`,
although the session was running in interactive mode.

## Evidence

- `.session.meta` records `status: error`, `end_ts: 2026-11-19T17:01:47.346135`,
  `pid: 2783340`, `project_workspace: /TopsailAI/src/topsailai_connector`.
- `.topsailai/settings.yaml` line 28 sets `TOPSAILAI_INTERACTIVE_MODE: "1"`, and
  `agent-launch.log` records `Merged env keys: ['TOPSAILAI_INTERACTIVE_MODE']`.
  The session was therefore interactive.
- The last session event is `llm.request.end` with `outcome: failed`,
  `attempt_count: 2`, `duration_sec: 604.176`,
  `error_category: LLMSevereRepetitionError`.
- `agent-launch.log` ends with a Python traceback whose final frame is
  `ai_base/llm_control/base_class.py:172 _record_repetition_verdict` raising
  `LLMSevereRepetitionError`, followed by
  `[TopsailAI-Launcher] Task failed, exit code: 1`.
- The repetition verdict reported `total_lines=4800`,
  `exact_duplicate_count=4796`, `repetition_rate=0.9994`, repeating
  `<result>` / `<name>file_tool-write_file</name>` / `<output>OK</output>`.

## Root cause

`LLMSevereRepetitionError` is not in the recoverable allowlist of the User2Agent
turn loop, so it escapes as an uncaught exception.

1. `ai_base/llm_control/base_class.py:172` raises `LLMSevereRepetitionError` once
   `TOPSAILAI_SEVERE_REPETITION_MAX_CONSECUTIVE` (default `2`) consecutive
   verdicts are reached.
2. `ai_base/llm_base.py:1030` catches it before the generic `ModelServiceError`
   branch and re-raises immediately, because a content verdict cannot be fixed by
   resending the identical request. This re-raise happens **inside** the retry
   loop, so it bypasses the interactive retry-exhaustion menu at
   `ai_base/llm_base.py:781` and the human is never asked.
3. `ai_base/agent_base.py:206` re-raises after the error hook.
4. `workspace/agent/agent_shell_base.py:719` matches only `LLMBackToChatError`,
   `LLMRetryExhaustedError`, `RECOVERABLE_PROVIDER_ERRORS` and
   `RECOVERABLE_REQUEST_ERRORS`. `LLMSevereRepetitionError` is absent, so the
   exception falls to `except Exception` at `:798`, where
   `_resolve_db_io_failure()` returns `None` and the branch executes a bare
   `raise`.
5. `workspace/agent/agent_shell_base.py:344` writes `status: error` and re-raises.
6. `cli/agent_chats.py:151` catches only `EOFError`, so the exception escapes as a
   traceback and the process exits with code `1`.

The User2Agent recoverable set is an explicit allowlist, but it applies only after
an error reaches that boundary. Many model-service errors are first retried or
presented through the LLM retry menu and therefore do not automatically escape.
Severe repetition bypassed those LLM-layer recovery paths and was missing from the
User2Agent allowlist, which made this specific verdict fatal in interactive mode.

## Required Behavior

In interactive mode a severe-repetition verdict MUST abandon the current turn and
return to the input prompt instead of terminating the process. The session, the
messages and the user's intent are all intact: only the response content was
unusable.

Non-interactive callers MUST keep the original fail-fast contract, because no
human is present to continue the session.

## Abnormal-exit inventory

Not every exception below automatically terminates a process. The precise chain
has three separate questions:

1. Does the LLM retry loop retry it, ask the human, or re-raise immediately?
2. If it reaches `AgentChat._run()`, is it converted into an abandoned turn or
   re-raised by the generic branch?
3. If `AgentChat.run()` re-raises it, does the executable entry point catch it?

For the `agent_chats.py` executable used by this incident, the final answer is
usually no: that entry point catches only `EOFError`. An exception that escapes
`AgentChat.run()` therefore terminates this worker process with a traceback and
non-zero exit status. A library caller can catch the same exception, so
"escapes `AgentChat.run()`" is not universally equivalent to "kills the process."

### A. Exceptions that can escape the turn loop

`workspace/agent/agent_shell_base.py` re-raises an exception that is neither in a
recoverable turn allowlist nor a recognized database I/O failure.
`AgentChat.run()` then writes `status: error` and re-raises it.

| Error | Actual LLM-layer behavior | Interactive outcome before the User2Agent boundary |
|---|---|---|
| `LLMSevereRepetitionError` | Re-raised immediately after the consecutive content verdict; no retry menu | Before this fix it escaped; now the main interactive loop abandons only the turn. Non-interactive and worker-thread runs still raise. |
| `LLMNullResponseError` | Retried within the 18-attempt cycle | At the next cycle boundary, the human receives Retry / Back / Exit. Back abandons the turn; only Exit, closed input, or exhausted invalid choices raises `LLMRetryExhaustedError`. |
| `LLMServiceSpecialResponseError` | Retried with special-response backoff | Same cycle-boundary Retry / Back / Exit behavior; it does not automatically escape. |
| `LLMProviderRateLimitError` | Retried within the cycle | Same cycle-boundary Retry / Back / Exit behavior; it does not automatically escape. |
| `JsonError` | Retried within the cycle | Same cycle-boundary Retry / Back / Exit behavior; it does not automatically escape. |
| `TypeError` | Retried within the cycle | Same cycle-boundary Retry / Back / Exit behavior; it does not automatically escape. |
| `LLMProviderPermissionDeniedError` | Retried within the cycle | Same cycle-boundary Retry / Back / Exit behavior; it does not automatically escape, although retrying invalid credentials is unlikely to help. |
| Retryable `LLMProviderBadRequestError` | Retried within the cycle | Same cycle-boundary Retry / Back / Exit behavior. |
| Non-retryable or context-exceed `LLMProviderBadRequestError` | Re-raised immediately | Escapes the turn loop and terminates `agent_chats.py` unless a higher launcher catches it. |
| `LLMRequestTimeoutError` | The production wall-clock guard raises it directly before another attempt | Already in the recoverable request set: the main interactive loop abandons the turn. The prior "wrapped timeout" row was a synthetic case, not the observed production path. |
| `AttributeError` from the LLM request path | Treated as an internal contract defect and re-raised immediately | Escapes the turn loop and terminates `agent_chats.py`. |
| `ModelServiceError` containing `token exceed` | Re-raised immediately | Escapes the turn loop and terminates `agent_chats.py`. |
| Other exception inside the generic LLM handler | Interactive mode asks `LLM Retry [yes/no]`; yes retries the same request, no or closed input re-raises | It escapes only after the human/default answer declines retry. Non-interactive mode retries to bounded exhaustion. |
| Unexpected exception outside the LLM retry handler | No LLM-layer retry decision applies | If no more specific Agent/turn handler catches it, it reaches the generic turn branch and is re-raised. |

### B. Deliberate terminal control-flow errors

These end the session without a traceback: the branch sets
`self._terminal_failure = True`, prints `Task terminated: ...`, and `break`s, so
`AgentChat.run()` writes `status: error`.

| Error | Raised at | Condition |
|---|---|---|
| `ContextWindowLimitError` | `agent_chat_base.py:417` | context still above the model send limit after a forced summarization |
| `SummaryWindowLimitError` | `llm_base.py:766` | summary requests exceed the configured window |
| `HeavyTaskError` | `agent_chat_base.py:135` | continuous summarization exceeds the fatal offset |

`HeavyTaskError` is raised inside the summarization pre-chat hook, and
`ai_base/agent_base.py:577` catches it and returns `None`, so it does not reach
the turn-loop branch from that path. The turn-loop branch is reachable only if
another caller raises it.

### C. Explicit process exits

| Site | Trigger | Session status |
|---|---|---|
| `utils/instruction_tool.py:620` | `q`, `exit`, `quit` in `DESCRIPTION_EXIT_SET` | `completed`, via the `except SystemExit` branch at `agent_shell_base.py:334` |
| `workspace/lock_tool.py:307` | human chooses exit at the project-workspace lock prompt | `completed`, exit code `1` |
| `workspace/agent/agent_shell_base.py:194` | database I/O failure in non-interactive mode | metadata left at `running`, `os._exit(1)` |
| `utils/input_tool.py:858` | terminal input helper subprocess only | not the agent process |

### D. Interrupt paths

- `KeyboardInterrupt` and `EOFError` in the turn loop set `flag_abort`, record
  `failed due to abort by Human`, and optionally ask for confirmation. They do not
  crash the process.
- `KeyboardInterrupt` is a `BaseException`, so `AgentChat.run()`'s
  `except Exception` never sees it; the `atexit` handler
  `workspace/session_meta.py:279` rewrites `running` to `interrupted`. This is
  intended.

### E. Entry-point gaps

| Entry point | Handled exceptions |
|---|---|
| `cli/agent_chats.py:151` | `EOFError` only |
| `cli/llm_chats.py:76`, `:92` | `EOFError` only |
| `cli/agent_chat.py` | none |
| `cli/AgentReAct.py` | none |
| `cli/team_agent.py` | none |
| `cli/ai_team.py` | none |
| `cli/llm_chat.py` | none |

Any escaping exception becomes a traceback plus exit code `1`.

### F. Silent summarization failure

`ai_base/prompt_base.py:304` swallows every exception from a pre-chat hook except
`ContextWindowLimitError`, `HeavyTaskError` and `SummaryWindowLimitError`. A
`LLMSevereRepetitionError` raised while generating a summary is therefore logged
and discarded, the summary silently fails, and the loop continues with an
uncompressed context. This is a different failure mode from section A and is not
an abnormal exit.

## Proposed change

Add an explicit recoverable set for content verdicts instead of widening an
existing one, because `RECOVERABLE_REQUEST_ERRORS` describes request-level
failures and a repetition verdict is a content verdict.

- Declare `RECOVERABLE_CONTENT_ERRORS = (LLMSevereRepetitionError,)`.
- Add it to the `except` tuple at `agent_shell_base.py:719`.
- Include it in the direct-match check and in the `LLMRetryExhaustedError`
  unwrapping loop of `_resolve_recoverable_turn_error()`, so a wrapped verdict is
  also recoverable.
- Keep the existing guards: non-interactive runs and worker threads still raise.

## Open decisions

The following are not part of the approved change and need a human decision:

1. Whether `LLMNullResponseError` and `LLMServiceSpecialResponseError` should also
   abandon the turn in interactive mode. Both are transient content failures.
2. Whether `LLMProviderRateLimitError` should be added to
   `RECOVERABLE_PROVIDER_ERRORS`. It is transient, but interactive runs already
   offer the retry-exhaustion menu.
3. Whether the unwrapping loop should also accept `RECOVERABLE_REQUEST_ERRORS`, so
   a wrapped `LLMRequestTimeoutError` matches its documented contract.
4. Whether the summarization path should surface a repetition verdict instead of
   swallowing it.

## Verification plan

- Unit: interactive run abandons the turn and reads the next message; the process
  is not terminated.
- Unit: non-interactive run still raises.
- Unit: worker thread still raises.
- Unit: a wrapped `LLMSevereRepetitionError` inside `LLMRetryExhaustedError`
  resolves as recoverable.
- Unit: `LLMProviderBadRequestError` and `LLMProviderPermissionDeniedError` stay
  fatal, so the allowlist cannot silently widen.
- BDD: an interactive session survives a severe-repetition verdict and returns to
  the input prompt.

## Implementation status

Implemented in `workspace/agent/agent_shell_base.py` (36 insertions, 8 deletions):

- `RECOVERABLE_CONTENT_ERRORS = (LLMSevereRepetitionError,)` declared separately
  from the request-level set.
- Added to the turn-loop `except` tuple and to the direct-match check of
  `_resolve_recoverable_turn_error()`.
- The unwrapping loop accepts provider and content failures only. A wrapped
  `LLMRequestTimeoutError` keeps its original fatal outcome, because widening
  that loop is open decision 3 and was not authorized.
- The `not interactive_enabled` and `not thread_tool.is_main_thread()` guards are
  unchanged, so non-interactive callers and worker threads still fail fast.

## Verification evidence

New file `tests/unit/test_topsailai_workspace_agent_agent_shell_base_content_error.py`
(12 tests). Command:

```text
PYTHONPATH=/TopsailAI/src:/TopsailAI/src/topsailai python -m pytest \
  tests/unit/test_topsailai_workspace_agent_agent_shell_base_content_error.py \
  tests/unit/test_topsailai_workspace_agent_agent_shell_base_provider_error.py \
  -q --color=no --tb=short -p no:cacheprovider
```

Result: `38 passed in 0.83s`.

Negative control at pristine `a065d718` in an isolated worktree, with
`PYTHONPATH` forced to that tree and the imported module verified to resolve
inside it (`.../pristine-content-error/src/topsailai/workspace/agent/agent_shell_base.py`,
`hasattr(..., 'RECOVERABLE_CONTENT_ERRORS') == False`): `6 failed, 6 passed`.
The 6 failures are exactly the behavioral tests; the 6 that pin unchanged
behavior pass on both trees. Worktree removed after the run.

Regression: `tests/unit/workspace/agent` plus both agent-shell files →
`76 passed in 7.31s`.

`tests/unit/test_topsailai_workspace_agent_agent_shell_base_db_io.py` plus
`tests/unit/workspace` → `18 failed, 937 passed`. The same command with the same
environment at pristine `a065d718` produced the identical `18 failed, 937 passed`,
so those failures are PRE-EXISTING cross-file pollution in the session-stats
suites, not caused by this change.

## BDD verification

Added two real HTTP/SSE scenarios in
`tests/bdd/features/severe_repetition_interactive_recovery.feature`:

- Interactive: two production severe-repetition verdicts abandon only the old
  turn; one fresh user message produces a third wire request and completes in
  the same `AgentChat` loop. The specialized verdict does not open the request
  retry menu, and the failure hook runs once.
- Non-interactive: the same two verdicts still raise
  `LLMSevereRepetitionError` from the turn loop after exactly two wire requests.

The scenarios use the real `llm_mock_server`, streaming OpenAI-compatible HTTP,
the production repetition detector, and provider-side request-body evidence.
Focused result: `2 passed in 2.17s`.

Focused severe-repetition and User2Agent boundary unit regression:
`55 passed in 1.00s`.

Existing retry-exhaustion BDD regression: `18 passed in 16.91s`.

## Remaining work

- Open decisions 1-4 still need a human decision.
