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

## Resolution

Resolved on 2026-11-18. The suspected cause above was wrong: the command does reach the Endpoint.
The defect is in the Endpoint's admission hook, which aborted the command when a courtesy frame
could not be sent.

### Proven root cause

The chain was read from source, link by link, not inferred from the count:

| Step | Site |
|---|---|
| The dispatched intent reaches the executor | `internal/endpoint/service.go:678` |
| The Endpoint journal records `invocation_started` then `endpoint_admitted` | `internal/endpoint/executor.go:231-240` |
| The admission hook runs | `internal/endpoint/executor.go:244-248` |
| The hook sends the `endpoint_admitted` receipt frame | `src/main/agent-cluster-endpoint/main.go:304-316` |
| The channel is detached during the re-home, so the send fails | `internal/channel/endpoint.go:296` returns `ErrOffline` |
| The hook returns that error, so the executor returns an empty receipt | `internal/endpoint/executor.go:246` |
| The service drops the empty receipt and sends nothing | `internal/endpoint/service.go:690-701` |

The provider is never invoked, and the Server never learns anything. Its deadline sweep
(`internal/storage/server/commands.go:121`) converges the still-`accepted` row to `unconfirmed` with
`unknown` effect certainty.

The Endpoint log for the failing run shows both halves of that chain:

```text
{"level":"ERROR","msg":"execute command","error":"endpoint is offline"}
{"level":"ERROR","msg":"execute command","error":"executor returned a receipt without a command ID"}
```

The command record confirms the Endpoint never admitted it:

```json
{"Phase":"accepted","DeliveryBoundary":"not_started","Status":"unconfirmed","EffectCertainty":"unknown","ErrorCode":""}
```

`Phase: accepted` is decisive. The Endpoint journal has no row for this command, so `unconfirmed`
was written by the Server's deadline sweep rather than by any receipt.

### Why the current behaviour is wrong

The admission notification is a courtesy, not a precondition. The provider call needs no channel, and
the final receipt is already retried on reconnect: `service.go:721` retries three times and
`resendPendingReceipts` (`:395`) reloads every `receipt_recorded` row. Aborting on a transport
failure therefore converts a temporary connectivity state into a permanent loss of the command, and
it reports "we do not know whether this ran" for a command that provably never ran.

### The fix

`src/main/agent-cluster-endpoint/admission_notify.go` extracts the hook into an `admissionNotifier`
with injected `send`, `hold`, `wait` and `logger`, so the transport-versus-hold decision is testable.
A send failure is logged at WARN and the command continues. Test hooks keep their abort semantics,
because a hold that cannot be reached means the test premise is broken rather than the transport
being unavailable.

`src/main/agent-cluster-endpoint/main.go:304-328` now builds the notifier and assigns
`notifier.notify` to `executor.AdmissionHook`.

### Verification

Four tests in `src/main/agent-cluster-endpoint/admission_notify_test.go`:

| Test | Proves |
|---|---|
| `TestAdmissionHookTransportFailureDoesNotAbortExecution` | an offline channel returns nil and logs at WARN |
| `TestAdmissionHookTestHookFailureStillAborts` | a hold failure still aborts, so the fix is scoped to transport |
| `TestAdmissionHookSuccessStillSendsTheFrame` | the positive path sends exactly one `FrameReceipt` with `Outcome == "endpoint_admitted"` |
| `TestAdmissionHookRunsTheHoldAfterTheFrame` | call order is `send`, `hold`, `wait` |

The positive test is mandatory: without it, deleting the admission frame entirely would pass both
negative tests.

Four deliberate breakages, each restored afterwards:

| Break | Failure message |
|---|---|
| Restore abort on transport | `an offline channel must not abort the command, got error endpoint is offline` |
| Make hold errors non-fatal | `a hold failure must abort the command, got error <nil>` |
| Disable the frame send | `the lost admission frame must be logged, got ""` / `admission frames sent = 0, want 1` / `call order = [hold wait], want [send hold wait]` |
| Restore abort, at BDD level | `provider invocation count=0, want 1 status=map[string]interface {}(nil)` — the issue's exact message |

The BDD scenario now passes, and the full suite is green: 150 scenarios, 616 steps, 341.967s.

### Why the scenario passed for the wrong reason before

`internal/storage/server/commands.go:121` converges any row whose status is in `(admitted,
dispatched, endpoint_admitted, executing)` once the deadline passes. A command that was never
dispatched therefore satisfies the same predicate as one that was dispatched and still executing, so
the scenario's "converges to unconfirmed" assertion could not distinguish the two. The provider
invocation count is the assertion that actually discriminates, which is why it is the one that failed.

### No existing test protected the old behaviour

`TestExecutorAdmissionHookRunsAfterDurableAdmission` (`internal/endpoint/executor_test.go:277`)
asserts only that the hook was called and observed phase `endpoint_admitted`. It never asserts that a
hook failure aborts, so the fix required no change to it.

### Commits

- `26b86701` fix: keep executing a command when the admission frame cannot be sent
- `b43d7b32` test: assert a failed logs read exits non-zero instead of printing the code

The second commit is a separate pre-existing BDD failure found while verifying this one: the
`tui logs reports unsupported capability` scenario still asserted the old contract, where an error
code was printed to stdout and the process exited zero. Commit `5f8584ac` deliberately changed that
contract, so the scenario failed on its When step. It is a test-only correction and needs no issue
record of its own.
