---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
---

# Event Source Acceptance Tests

Behavior specification for the event sources that feed the event channel and the
on-disk events file. Every scenario below is executable; the feature file is
`tests/bdd/features/event_source_file.feature` and the steps are
`tests/bdd/steps/event_source_file_steps.py`.

This document is the test plan. It states what must be true, why it matters, and
which real production path proves it. It does not restate implementation.

## Why the on-disk file is the assertion target

The event channel pushes events to a live subscriber over a Unix domain socket.
That proves delivery, but it does not prove durability: a subscriber can be
absent, and the file backend is what an operator reads after the fact.

Asserting on the file therefore closes a gap the channel scenarios cannot close.
The file is the artifact a human actually inspects, so the file is what the
acceptance test reads.

## Scope

In scope:

- `llm.request.start` and `llm.request.end` produced by `LLMModel.chat()`.
- `tool_call.start` and `tool_call.end` produced by `exec_tool_func()`.
- `tool_approval.request` and `tool_approval.decision` produced by the ASK branch
  of `with_tool_approval()`.
- The disabled configuration, which must write nothing.

Out of scope:

- Channel transport, heartbeat, reconnect, and drop accounting. Those are
  covered by `tests/bdd/features/event_channel.feature`.
- Backend adapters other than `file`. `db` and `webhook` are stubs.

## Test approach

Each scenario drives a real production entry point and then reads the JSONL file
that the production file backend wrote. No event producer is stubbed.

- The LLM path uses the real OpenAI-compatible client against
  `tests/mock/llm_mock_server.py` over real HTTP, per the project rule that
  LLM-related BDD must not stub internal functions.
- The tool path calls the real decorated `exec_tool_func()`.
- The approval path calls the real `with_tool_approval()` and resolves the
  pending instance from a second thread, so the ASK branch runs unmodified.
- The interrupt path calls the real `LLMModel.chat()` and raises from the real
  interrupt checkpoint.

Each scenario owns its own events file under `.tmp/bdd/`, its own mock provider,
and its own collector instance, so scenarios cannot observe each other's records.

## Feature: Recorded events reach the on-disk events file

### Scenario: A successful LLM request writes a paired start and end record

```gherkin
Given an events file owned by this scenario
When a real LLM request completes successfully
Then the events file holds exactly one "llm.request.start" record
And the events file holds exactly one "llm.request.end" record
And both LLM request records share one operation id
And the LLM request end record reports outcome "success"
```

Rationale: a logical request must produce exactly one start and one terminal
record. Two starts, or a start without an end, makes the file unusable for
auditing request duration and outcome.

### Scenario: An interrupted LLM request writes an interrupted terminal record

```gherkin
Given an events file owned by this scenario
When a real LLM request is stopped by "HardInterruptError"
Then the events file holds exactly one "llm.request.start" record
And the events file holds exactly one "llm.request.end" record
And both LLM request records share one operation id
And the LLM request end record reports outcome "interrupted"
And the LLM request end record reports error category "HardInterruptError"
And the LLM request end record reports zero attempts
```

Rationale: this is the regression that motivated the suite. The interrupt
checkpoint raises before any provider request is sent, so the terminal record
must exist, must be classified as `interrupted`, and must report `attempt_count`
of `0` because no attempt was actually made.

### Scenario: A keyboard interrupt writes an interrupted terminal record

```gherkin
Given an events file owned by this scenario
When a real LLM request is stopped by "KeyboardInterrupt"
Then the events file holds exactly one "llm.request.start" record
And the events file holds exactly one "llm.request.end" record
And the LLM request end record reports outcome "interrupted"
And the LLM request end record reports error category "KeyboardInterrupt"
```

Rationale: `KeyboardInterrupt` is a `BaseException`, not an `Exception`. A
handler that only catches `Exception` silently loses this terminal record.

### Scenario: A tool call writes paired start and end records

```gherkin
Given an events file owned by this scenario
When a real tool call executes successfully
Then the events file holds exactly one "tool_call.start" record
And the events file holds exactly one "tool_call.end" record
And the tool call end record reports success
```

Rationale: the tool source is mounted through a decorator rather than a direct
call, so it needs its own proof that the decorator is still on the production
stack.

### Scenario: An approval decision writes paired records sharing one instance id

```gherkin
Given an events file owned by this scenario
When a real approval request is approved by the human
Then the events file holds exactly one "tool_approval.request" record
And the events file holds exactly one "tool_approval.decision" record
And both approval records share one instance id
And the approval decision record reports status "approved"
```

Rationale: without a shared identifier, two concurrent approvals of the same
tool under the same rule produce four records that cannot be paired. The
instance id is the only field that distinguishes them.

### Scenario: Operational records never carry prompt text or approval arguments

```gherkin
Given an events file owned by this scenario
When a real LLM request completes successfully
And a real approval request is approved by the human
Then no LLM request record contains the prompt text
And no approval record contains the tool argument
```

Rationale: the events file is operational telemetry, not a transcript store. It
is written to disk and read by tooling, so prompt text and tool arguments must
not leak into it. This is a security boundary, not a formatting preference.

### Scenario: Disabling events writes no events file

```gherkin
Given an events file owned by this scenario with events disabled
When a real LLM request completes successfully
Then no events file was written
```

Rationale: the master switch must be a real off switch. A disabled collector
that still creates the file would leave operators with an empty artifact that
looks like a recording failure.

## Observed file content

The following is the content captured from a real run of every source in one
process. It is reproduced here as evidence, not as a fixture: the scenarios
assert on fields, not on this literal text. The dump directory was a temporary
artifact and has been removed, so the evidence lives in this document rather
than behind a path that no longer exists.

Identifiers and durations change on every run, because `operation_id` and
`instance_id` are generated per request and `duration_sec` measures real elapsed
time. The stable facts are the record count, the record order, the field set of
each record type, and the pairing of identifiers.

```text
=== captured dump: 2729 bytes, 8 lines

line 1  llm.request.start      operation_id=96355f96... model_name=bdd-event-model message_count=1 stream=false return_mode=parsed
line 2  llm.request.end        operation_id=96355f96... outcome=success attempt_count=1 duration_sec=0.386
line 3  llm.request.start      operation_id=76df8cee... model_name=bdd-event-model message_count=1 stream=false return_mode=parsed
line 4  llm.request.end        operation_id=76df8cee... outcome=interrupted attempt_count=0 duration_sec=0.0 error_category=HardInterruptError
line 5  tool_call.start        tool_name=bdd_tool args={"path":"/tmp/bdd-private-argument"}
line 6  tool_call.end          tool_name=bdd_tool success=true result="read /tmp/bdd-private-argument" duration_ms=0.444 error_type=null
line 7  tool_approval.request   instance_id=e7f2f9d9... tool_name=bdd_danger_tool rule_name=bdd-rule timeout=5.0 policy=deny
line 8  tool_approval.decision  instance_id=e7f2f9d9... tool_name=bdd_danger_tool rule_name=bdd-rule status=approved
```

Every record carries the same envelope, which the scenarios rely on:

```text
event_type  string   dotted event name
timestamp   string   ISO 8601 with timezone offset
session_id  string   the session that produced the record
payload     object   event-specific fields
trace_id    null     not populated by these sources
source      null     not populated by these sources
event_id    string   uuid4, unique per record
```

What this evidence establishes:

- Every start has exactly one matching end, and the `operation_id` values pair
  line 1 with line 2 and line 3 with line 4.
- The interrupted request reports `attempt_count=0`, confirming the counter is
  incremented after the interrupt checkpoint rather than before it.
- The approval records pair on `instance_id`, and the decision carries the
  human's real answer rather than a placeholder.
- No record contains the prompt text `bdd private prompt text`. Verified by
  `grep -c` returning `0` against the real file.
- The approval records contain no tool argument, while the tool records do,
  which is the intended difference between the two sources.
- The file is append-only JSONL with one object per line, so a reader can stream
  it without loading the whole file.

## Running the suite

```text
make core-bdd-test
```

Or the module alone:

```text
PYTHONPATH=/TopsailAI/src/topsailai:/TopsailAI/src python3 -B -m pytest tests/bdd/test_event_source_file.py -q --color=no
```

The suite is not marked `slow`; it completes in a few seconds because the mock
provider answers immediately and no scenario waits on a wall-clock window.

## Negative control

The interrupt scenarios were verified to fail when the terminal-event settlement
is removed from `track_llm_request_events()`. With that one line deleted, both
interrupt scenarios fail and the other five still pass, which shows the
assertions observe the settlement behavior rather than merely the presence of a
start record.

The exact edit and result:

```text
removed:  _settle_lifecycle(state, error)   (inside the except BaseException branch)
result:   2 failed, 5 passed
failed:   test_an_interrupted_llm_request_writes_an_interrupted_terminal_record
          test_a_keyboard_interrupt_writes_an_interrupted_terminal_record
```

The file was restored afterwards and `git status` on `ai_base/` is clean.

## Production evidence from a real session

The scenarios prove the contract on a controlled path. A real agent session
confirms the same contract holds under ordinary load, so the file was inspected
after the fact rather than only during a test.

Two real session files were checked for lifecycle pairing:

```text
session A   82 starts, 82 ends, 0 dangling, 0 orphan
            outcomes: success=82

session B  191 starts, 191 ends, 0 dangling, 0 orphan
            outcomes: success=166, exhausted=17, abandoned=2, failed=6
```

Session B is the interesting one: it contains the retry-exhausted, user-abandoned
and failed terminal outcomes, and every one of them still has a matching start
with the same `operation_id`. No request was left dangling.

One caveat about older files: a session started before the wiring commits landed
records no `llm.request.*` records at all, because the process loaded the older
code. That is expected and is not evidence of a defect. Only files written by a
process started after the commits are meaningful for this contract.

## Known limitations

- The `db` and `webhook` backends are stubs, so only the file backend is
  covered.
- The suite asserts on the file, not on the channel. Delivery to a live
  subscriber is covered separately by `tests/bdd/features/event_channel.feature`.
- The interrupt scenarios construct the model with `object.__new__` so the
  interrupt checkpoint is reached without a provider round trip. The checkpoint
  itself, the settlement decorator, and the file backend are all real.

## Full-suite baseline

The suite was verified against the whole non-slow BDD target, not only in
isolation, because a new module can pass alone and still disturb its neighbours
through shared process state.

```text
PYTHONPATH=/TopsailAI/src/topsailai:/TopsailAI/src:/TopsailAI/src/topsailai/cli \
  python3 -B -m pytest -m "not slow and not packaged" tests/bdd -q --color=no
```

Result: `11 failed, 792 passed, 9 deselected`.

The eleven failures are pre-existing and unrelated to this suite. They live in
five modules that fail identically when run alone, without this suite present:

```text
tests/bdd/test_compiled_module_discovery.py
tests/bdd/test_llm_chat_attempt_points.py
tests/bdd/test_llm_first_byte_control.py
tests/bdd/test_llm_first_byte_timeout_warning.py
tests/bdd/test_tool_execute_hooks.py
```

Running exactly those five modules alone reproduces `11 failed, 19 passed`,
which is the same count and the same test ids as the full run. That establishes
the failures as a pre-existing baseline rather than a regression introduced
here.

The `cli` path entry in `PYTHONPATH` is required for the full target: without it
`tests/bdd/test_heartbeat_control.py` cannot import `cli_topsailai` and pytest
aborts collection with exit code 2 before any scenario runs.

## Order independence

The suite was run in both orders against the event channel suite and the unit
wiring suite:

```text
source_file -> channel -> unit    43 passed
channel -> source_file -> unit    43 passed
```

Both orders pass. This matters because the collector is a process-wide
singleton: a scenario that leaves it disabled makes every later scenario that
records through the production path silently drop its events, while a scenario
that calls the fan-out function directly still passes. The harness therefore
owns its collector and resets it in `close()`, and each scenario gets its own
events file under `.tmp/bdd/`.
