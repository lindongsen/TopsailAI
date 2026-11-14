---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: open
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

Open. The behavior this issue asks to cover is now implemented and committed as
`87791479`, but the BDD coverage itself has not been written. The remaining work
is a feature file plus step definitions under the project BDD test location,
following the existing Gherkin conventions, with one scenario per path listed
above.

The scenarios must drive the real agent loop rather than a private helper, so the
turn boundary after a fault is observed from the outside. The fault must be
injected at the database boundary, and the assertion must be the reappearance of
the prompt, not an internal call count.

## Verification

Pending. Planned checks:

- The new feature file runs green.
- Removing the recovery branch makes the exception-path scenario fail.
- The non-interactive contrast scenario still passes.
- The retained-artifact assertions hold for the meta, stdout and event files.
