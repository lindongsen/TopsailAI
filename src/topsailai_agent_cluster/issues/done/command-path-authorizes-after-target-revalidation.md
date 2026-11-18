---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
status: open
created: 2026-11-18
---

# The command path revalidates the target before it authorizes the caller

## Symptom

A caller whose token the Endpoint policy refuses can still learn whether a resource exists on
that machine. The refusal code differs depending on the target:

```text
gd-dev token + nonexistent resource  -> error_code: target_not_found
gd-dev token + existing resource     -> error_code: target_generation_mismatch
gd-dev token + existing resource, correct generation -> error_code: policy_denied
```

The third line is the only one that is a policy refusal. The first two answer a question the
caller was never authorized to ask.

## Cause

`internal/endpoint/executor.go` runs the target checks before the policy hook:

```text
199  } else if err := e.revalidateGeneration(ctx, instance, adapterID, *intent.Target); err != nil {
203  if e.PolicyHook != nil {
204      if policyErr := e.PolicyHook(ctx, intent); policyErr != nil {
```

Lines 186-199 also return `target_not_found` and `generation_required` before line 203. So an
unauthorized caller reaches the target checks, and the receipt it receives names the target's
state.

## Why this contradicts the read path

`internal/endpoint/history.go:44-46` states the rule and implements it:

```go
// The policy check runs before the adapter is consulted, so a refused caller
// cannot infer whether this Endpoint can read history at all.
if err := s.permitOperation(frame, OperationHistoryRead); err != nil {
```

`internal/endpoint/accesspolicy_enforce.go:24-28` states the same intent for every operation:

```go
// The check runs before the transport is consulted and before the handler looks
// at the request, so a refused caller cannot infer from a status code or a
// response time whether the Endpoint has an adapter, a provider or a reachable
// session.
```

The command path does not honour that intent. Two paths, one stated rule, opposite order.

## Impact

Bounded but real. The caller must already hold a token the Server accepts, and the Server forwards
it without interpreting it, so the caller must be someone who can reach the cluster. What leaks is
resource existence and generation state on a machine whose policy refuses that caller. It does not
leak content, and no mutation is applied: every case above reports `effect_certainty: not_applied`.

The leak matters because the policy exists to confine a caller to specific machines. A caller
refused by `ac.ai-dev` can currently enumerate which resource IDs exist there by trying each one
and reading the code.

## Why it was not caught

`internal/endpoint/executor_policy_test.go:102` and `executor_policy_log_test.go:150` assert that a
refused command produces `policy_denied`. Both use a target that passes the earlier checks, so the
policy hook is reached and the assertion holds. No test supplies a target that fails an earlier
check together with a refused token, so the ordering is never exercised.

This is the recorded pattern: a test that asserts the refusal certifies the guard while leaving the
order unproven.

## Not fixed here

Moving the policy hook above the target checks changes which code an authorized caller receives for
a bad target, so it is a behaviour change on the authorized path as well. It needs its own unit with
its own tests, and the decision about whether an authorized caller should still get the precise
target code (it should) while an unauthorized one gets only `policy_denied`.

The fix shape: run the policy hook first, then the target checks. An authorized caller keeps every
precise code it has today; an unauthorized caller gets `policy_denied` for every target, existing or
not.

## Verification that the current behaviour is otherwise correct

Measured on the live fleet at `1.0.0+3466+gf9e3fa99`:

- gd-dev token refused on `ac.topsail`, `ac.ai-dev`, `ac.topsailai-dev`: HTTP 403 `policy_denied`.
- Fleet token accepted on the same three: HTTP 200.
- gd-dev token with a correct generation: `policy_denied`, `not_applied`, target state unchanged
  (`waiting_input`, generation `583342749` before and after).
- gd-dev's own policy is `deny-all`, so it refuses the fleet token on `ac.gd-dev` as well.
- gd-dev's CLI has no `AGENT_CLUSTER_CLI_ENDPOINT_TOKENS` at all, so it cannot present any endpoint
  token.
- gd-dev cannot reach either Server API: `172.19.1.1:53680` and `192.168.2.1:53680` both CLOSED from
  that host.

## Resolution

Fixed in `417c56a8`. The policy hook now runs immediately after the journal's terminal and
recovery returns, before `adapterForIntent`, `Describe`, the profile checks, `supports` and every
target check.

### The leak was wider than this issue recorded

The issue named the target checks at `executor.go:186-199`. Those were not the only checks that ran
before the hook. The full pre-hook sequence was:

| Step | What a refused caller could learn |
|---|---|
| `adapterForIntent` | whether a resource ID is mapped, and which adapter owns it (`target_not_found`, `adapter_not_configured`, `target_required`) |
| `instance.Describe` | whether this Endpoint has a working adapter (`capability_unavailable`) |
| profile checks | whether a launch profile exists and its revision (`profile_required`, `profile_not_found`, `profile_revision_mismatch`) |
| `supports` | which operations this machine serves (`unsupported`) |
| target checks | whether a resource exists and its generation (`target_not_found`, `generation_required`, `target_generation_mismatch`, `target_still_active`) |

So a refused caller could enumerate the machine's adapter health, its capability surface and its
resource IDs. The issue's three-line symptom was the smallest part of it.

### Why the hook cannot move earlier than it did

Two constraints bound the placement, and both are now recorded in the code comment:

- `RecordReceipt` is an `UPDATE command_journal ... WHERE command_id=?` (`journal.go:82`), so the
  journal row must exist before a refusal can be recorded. The hook therefore cannot precede
  `AdmitJournal`.
- The hook must stay after the `receipt_recorded` and `invocation_started` returns. Moving it above
  them was tried as a deliberate breakage and failed with
  `command "policy-order-replay" is not invocation-started`: a replay would try to re-record a
  receipt for a command that already reached a terminal or in-flight phase. A refusal must never
  replace a real outcome, because the effect already happened.

### A pre-existing test certified the old ordering

`TestNonPolicyRejectionLogsNoRefusal` (`executor_policy_log_test.go:116`) asserted
`t.Fatal("the policy hook must not run for an unsupported operation")`. That assertion is the old
ordering written down as a requirement.

Its intent is still valid and was preserved: an unsupported operation must not be logged as a policy
refusal, because that would send an operator to a policy file that is correct. The test now uses a
**permitted** hook, which is the only case where an unsupported rejection can still happen once the
policy check runs first. The log-site property is unchanged and still proven: moving
`logPolicyRefusal` into `recordEarlyRejection` fails it with
`an unsupported operation must not be logged as a policy refusal`.

### Tests

`internal/endpoint/executor_policy_order_test.go`, four tests:

| Test | Proves |
|---|---|
| `TestRefusedCallerLearnsNothingAboutTheTarget` | four target shapes (missing, wrong generation, correct generation, empty generation) all answer `policy_denied` to a refused caller |
| `TestAuthorizedCallerKeepsThePreciseTargetCode` | an authorized caller still receives `target_not_found`, `target_generation_mismatch` and `generation_required` |
| `TestRefusedCallerIsRefusedBeforeTheAdapterIsDescribed` | an operation the adapter does not advertise answers `policy_denied`, not `unsupported` |
| `TestRefusalDoesNotOverwriteAnAlreadyRecordedOutcome` | a replay after the token is refused returns the recorded outcome |

The authorized-caller test is mandatory: without it, refusing every command would also satisfy the
refused-caller test.

### Deliberate breakages

| Breakage | Result |
|---|---|
| Move the hook back after the target checks | `got error code "target_not_found"`, `"target_generation_mismatch"`, `"generation_required"`, and `"unsupported"` — the issue's exact symptom |
| Move the hook above the recovery returns | `command "policy-order-replay" is not invocation-started` |
| Move `logPolicyRefusal` into `recordEarlyRejection` | `an unsupported operation must not be logged as a policy refusal` |

All three restored; `go test ./internal/endpoint/` green at 7.1 s, and green again from a clean
`git archive` extraction of the committed tree.

### Behaviour change on the authorized path

None. An authorized caller keeps every precise code it had before, which the second test asserts
case by case. The only change is that a refused caller now receives `policy_denied` for every target
instead of a code that describes the target.

### Not covered here

`internal/server/http.go` was being edited concurrently by another agent, and its new
`follow_failed` branch makes `TestOutputFollowReportsEndpointOffline` fail. That failure is not
caused by this change: the test passes at HEAD and the file's modification time precedes this work.
It is left untouched.
