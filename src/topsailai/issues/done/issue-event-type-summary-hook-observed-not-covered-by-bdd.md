---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: resolved
---

# Event type not covered by BDD: summary.hook.observed

## Status

Registered only. Not fixed in this change.

## Summary

`summary.hook.observed` is a real production event type, but no BDD scenario
asserts it. The other three previously uncovered event types
(`llm.response.raw`, `tool_call.warning`, `thought.line_pattern.warning`) were
covered by the same change that registers this issue.

## Producer

| Item | Value |
|---|---|
| Event type | `summary.hook.observed` |
| Producer | `hooks/points/context/summary_events_observer/observer.py:20` |
| Trigger | A context summarization Hook Point runs |
| Default state | Active whenever summarization runs |

## Why it is not covered

Reaching this producer requires a full summarization cycle: enough messages to
cross a quantity or token threshold, a real summarization LLM request, and the
Hook Point dispatch that follows. That is a materially larger scenario than the
other three, which each need only one configuration switch and one production
call.

The event is also not part of the change that wired approval and LLM request
events (`3d48db8d`, `a1b2febb`, `0ae9e7fe`), so it carries no regression risk
from that work.

## Risk assessment

| Dimension | Assessment |
|---|---|
| Changed by recent event-source work | No |
| Default enabled | Yes |
| Observed in real session files | Yes (28 and 84 records in two real sessions) |
| Failure impact if broken | Missing observability only; no business behavior change |
| Overall risk | Low |

## Evidence that it does produce records

Two real session event files written by production code contain this type:

```text
wa-a1ad42ea0a3f.3552162.session.events     28  summary.hook.observed
topsailai.282221.session.events            84  summary.hook.observed
```

This confirms the producer is reachable in real usage. It does not confirm the
payload shape, because no assertion checks it.

## What a future scenario must assert

1. A real summarization cycle runs through the real Hook Point dispatch.
2. The events file holds at least one `summary.hook.observed` record.
3. The payload carries the fields the observer writes.
4. Summarization output is unchanged by the event recording.

## Reproduction of the current gap

```text
grep -c "summary.hook.observed" tests/bdd/features/event_source_file.feature
0
```

## Scope statement

No production code, test code, or configuration was changed by this issue
record. It documents a known coverage gap so the gap is traceable rather than
silently forgotten.

## Resolution

Resolved on 2026-11-17. The producer was already correct; the gap was a harness
capability mismatch that made a real summary cycle impossible to drive.

### Root cause

The first attempt to drive a summary cycle hung with no output. A
`faulthandler.dump_traceback_later(20, exit=True)` probe localized the block
exactly:

```text
File "ai_base/llm_base.py", line 849 in chat          <- time.sleep(sec) retry backoff
File "workspace/context/base.py", line 1479 in _chat_for_summary
File "workspace/context/base.py", line 1650 in _summarize_runtime_messages
File "workspace/context/ctx_runtime.py", line 468 in summarize_messages_for_processed
```

Re-running the same probe with `TOPSAILAI_LLM_REQUEST_WALL_CLOCK_BUDGET_SEC=6`
and `TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT=3` replaced the hang with the underlying
error:

```text
LLMRequestTimeoutError: LLM Service: request exceeded its wall-clock budget
after 15.1s over 3 attempts (budget=6s); retrying the same request cannot recover
```

The cause is a provider capability mismatch, not a production defect:

| Layer | Behavior |
|---|---|
| `workspace/llm_shell.py:119` | passes `for_stream=True` unconditionally, so every summary request streams |
| `tests/bdd/event_source_file_harness.py` | built `MockServerConfig(port=0, reply="bdd reply")` with `stream_chunks=None` |
| `tests/mock/llm_mock_server.py:542-550` | answers HTTP 400 `streaming is not supported` when all three stream fields are `None` |

The client therefore retried a request the provider could never satisfy until
the wall-clock budget expired. A probe that swapped in a server built with
`stream_chunks=(reply,)` returned `result: 'probe concise summary'` and produced
exactly two `summary.hook.observed` records with the expected payloads and
`source: hooks.summary_events_observer`.

### Changes

`tests/bdd/event_source_file_harness.py` — added an opt-in
`stream_chunks: tuple[str, ...] | None = None` parameter forwarded to
`MockServerConfig`. The default stays `None`, so all ten pre-existing scenarios
keep their current non-streaming behavior; `send_llm_request` calls
`LLMModel.chat` with the default `for_stream=False`, which the mock already
serves.

`tests/bdd/event_source_file_extended_harness.py` — added
`summary_events_enabled`, `_summary_values()` (the sixteen switches a real
summary cycle needs), `run_summary()` (builds a real `AgentChat`, sets three
messages on both layers, calls `summarize_messages_for_processed(force=True)`),
and a `close()` override that closes the summary chat before the base harness
resources.

`tests/bdd/features/event_source_file.feature` — two scenarios: the positive
cycle and an events-disabled negative control.

`tests/bdd/steps/event_source_file_steps.py` — `exactly_two_records`, two
`@given` fixtures, `real_summary_cycle`, and four `@then` steps asserting the
outcome order, the exact `point_name` list, one shared `operation_id`, the
`source` value, and a payload key set of exactly
`{schema_version, operation_id, point_name, outcome}` with no prompt text.

### Verification

```text
Run 1: 1 failed, 11 passed   -> StepDefinitionNotFoundError: "exactly two ... records"
Run 2: 12 passed, 6 warnings in 7.73s   EXIT=0
After observer restore: 12 passed in 10.45s   EXIT=0
```

Negative control: disabling the observer's `record_event` call made the new
scenario fail with

```text
AssertionError: [('llm.request.start', {...}), ('llm.request.end', {...})]
```

The events file held only LLM records and no `summary.hook.observed`, proving
the scenario observes the producer rather than passing on its own. The observer
was restored and `git diff --stat` confirmed zero residual change.

### Assertions the scenario makes

1. A real summarization cycle runs through the real Hook Point dispatch.
2. The events file holds exactly two `summary.hook.observed` records.
3. The payload carries only the four metadata fields the observer writes.
4. The records come from `hooks.summary_events_observer`.
5. With event recording disabled, no events file is written.

### Limitations

- Only `tests/bdd/test_event_source_file.py` was run. The wider BDD suite has
  known pre-existing failures recorded in `LEARN.md`
  (`test_instruction_message_integrity.py` 10, `test_session_meta_name.py` 1,
  `test_session_name_startup_context.py` 2) and was not re-verified here.
- The scenario drives the User2Agent summary path. The Agent2LLM summary path
  uses the same observer and the same Hook Points, so it is covered by the same
  producer assertion rather than by a second scenario.
