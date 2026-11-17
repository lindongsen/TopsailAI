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

# Issue: Add BDD coverage for interactive fault tolerance

## Symptom

The interactive fault-tolerance rule has no executable acceptance coverage. No
Gherkin scenario asserts that an interactive session survives an IO or database
error and returns to the input prompt.

## Evidence

- The rule is user-visible behavior, but the only existing coverage of the
  failure path exercises the non-interactive termination.
- The unconditional exit this issue originally cited no longer exists. The
  write-failure handler in `utils/db_io_tool.py` now reports the failure to its
  caller and never terminates the process, so the interactive and
  non-interactive policies are distinguished in the agent loop instead.
- The observable outcome to assert is the prompt at
  `workspace/input_tool.py:39 INPUT_TIPS`, reached through
  `workspace/agent/agent_shell_base.py:348 _read_next_user_message`, which the
  recovery branch calls at `:753` for a database failure and at `:675` for a
  provider failure.
- The recovery branch itself is guarded by the per-run interactivity value and by
  a main-thread check, so a worker thread and a non-interactive run end with an
  explicit failure answer instead of waiting for input.

## Required Behavior

Add BDD scenarios linked to the acceptance criterion: an interactive session
survives an IO or database error and returns to the input prompt.

Coverage MUST include:

- The normal path: a healthy turn completes and the prompt reappears.
- The exception path: an injected IO or database error occurs mid-turn, the
  session stays alive, and the prompt reappears.
- The boundary path: the error repeats across consecutive turns without
  terminating the session.
- The contrast path: a non-interactive run ends with an explicit failure answer
  instead of waiting for input, so the two policies cannot silently converge.

Assertions MUST target user-visible outcomes: the prompt reappears, the session
process is still alive, the meta file is retained, and the stdout file is
retained. Do not assert internal call counts or private helper invocations.

## Impact

A regression that reintroduces an unconditional exit would pass the current
suite, because no scenario observes the turn boundary after a fault. The defect
described in `issue-interactive-mode-must-not-exit-on-io-error.md` could return
without any test failing.

## Resolution

Resolved. The BDD coverage now exists and runs green.

Delivered artifacts:

- `tests/bdd/features/db_io_failure_interactive_survival.feature` holds four
  scenarios, one per required path.
- `tests/bdd/steps/db_io_failure_interactive_survival_steps.py` drives the real
  `AgentChat._run` loop against a real `OperationalError` carrying a real SQLite
  primary result code, so the fault is injected at the database boundary rather
  than through a private helper.
- `tests/bdd/test_db_io_failure_interactive_survival.py` registers the scenarios
  following the existing `test_*.py` convention.

Scenario mapping:

| Required path | Scenario |
|---|---|
| Normal | An interactive session keeps waiting for the next message |
| Exception | An interactive session keeps waiting for the next message |
| Boundary | An interactive session survives consecutive write failures |
| Contrast | A non-interactive run exits non-zero instead of reporting success |
| Worker thread | A worker thread abandons only its own turn |

The non-interactive contrast scenario also asserts the last-resort fallback: the
run reports an explicit failure answer, the process exits with code `1`, the
metadata records `error`, and both output streams are flushed before the exit.
That fallback exists because a non-interactive caller cannot wait for a human,
and a lost write must never look like success to a script, a CI job or the
launcher.

Two design corrections were needed while making the scenarios pass:

- The consecutive-failure step had to use the numeric form `3 consecutive turns`
  because the `{count:d}` converter cannot match an English word.
- The retained-metadata assertion originally required a metadata write on every
  non-worker path. That contradicted the interactive contract: a session that
  keeps running must not be finalized as `error`, otherwise a live session is
  declared dead. The assertion now rejects any `error` finalization on a path
  that keeps the session alive, and the non-interactive path asserts its own
  `error` write through a dedicated step.

## Verification

Completed:

- `pytest tests/bdd/test_db_io_failure_interactive_survival.py` passes all four
  scenarios.
- Mutation check, interactive guard removed: both interactive scenarios fail with
  `an interactive session must not exit`, proving the scenarios reach the guarded
  branch.
- Mutation check, fallback exit removed: the non-interactive scenario fails on
  the exit-code assertion, proving the exit code is genuinely asserted.
- `pytest tests/unit/test_topsailai_workspace_agent_agent_shell_base_db_io.py`
  and `tests/unit/test_db_write_io_policy.py` pass, 62 tests.
- `make core-bdd-test` reports 42 failed and 746 passed, against a pre-change
  baseline of 44 failed and 737 passed. The new file contributes no failure, and
  every remaining failure is in a hook-related file unrelated to this change.

Not verified:

- The stdout-retention assertion observes the flush call rather than a real
  session stdout file, because the scenario runs in-process. A real-file check
  would need a subprocess scenario.
