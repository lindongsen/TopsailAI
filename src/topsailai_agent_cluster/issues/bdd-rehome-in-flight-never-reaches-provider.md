---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# The re-home in-flight BDD scenario never reaches the provider

## Trigger

`make test-bdd` failed on one scenario while verifying an unrelated change to the message-count
reporting path. The scenario is
`a_command_in_flight_during_a_re-home_is_reported_as_unknown`.

## Observed behaviour

```text
suite.go:640: provider invocation count=0, want 1 status=map[string]interface {}(nil)
```

The provider was invoked zero times, so the command never reached the adapter. The status map is
`nil`, meaning no command record was found either.

## Deterministic, not flaky

The scenario was re-run alone and failed again with the identical message, so this is not a
timing race:

| Run | Result |
|---|---|
| Full `make test-bdd` | fail, `count=0, want 1` |
| Scenario alone, working tree | fail, `count=0, want 1` |
| Scenario alone, detached worktree at HEAD `47e62683` | fail, `count=0, want 1` |

The HEAD worktree contained no working-tree changes, so the failure predates the change under
verification and is not caused by it.

## Why this is a real defect and not a stale test

The scenario exists to prove that a command in flight when an Endpoint is re-homed is reported as
`unknown` rather than silently lost. `count=0` means the setup never got as far as submitting the
command, so the scenario currently proves nothing about the behaviour it names. A scenario that
fails before reaching its subject is worse than a missing scenario, because it occupies the name
of a covered behaviour.

The `status=nil` is consistent with the command never being admitted, which points at the setup
phase rather than at the re-home assertion.

## Suspected cause (not yet investigated)

The setup must submit a command and hold it in flight while the Endpoint moves to a second Server.
If the submission is rejected or never dispatched, the count stays zero. Candidate causes are a
setup ordering problem, a missing Endpoint readiness wait before submission, or a submission that
is refused because the target is not yet routable.

This is a hypothesis. It must be confirmed by reading the scenario's step definitions and the
Server log for the run, not inferred from the count alone.

## Impact

`make test-bdd` cannot be used as a pass/fail gate while this scenario fails, and the re-home
in-flight behaviour is currently unverified despite having a named scenario.

## Fix direction (not yet decided)

- Read the scenario's Given/When steps and confirm the command is actually submitted before the
  re-home begins.
- Check the Server log for the run for a refusal or a dispatch failure on that command.
- If the setup is at fault, fix the setup and confirm the scenario fails when the `unknown`
  convergence is removed, so the scenario is proven to test its subject.
- Do not delete or skip the scenario to make the suite green; that would remove the only named
  coverage of the behaviour.

## Verification limitation

Only one host was used, under concurrent load from other agents in the same workspace. The
deterministic reproduction on three separate runs, including a clean HEAD worktree, is what
establishes that the failure is real rather than environmental.
