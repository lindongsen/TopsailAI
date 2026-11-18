---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
status: resolved
created: 2026-11-17
---

# The BDD messages body injection never reaches the mock Provider

## Trigger

While reviewing `issues/messages-body-json-quoted-into-one-line.md`, the claim "the BDD layer covers
the unwrapping path" was checked against the code instead of being accepted. It does not hold: the
BDD scenario declares a real provider step record, but that value never reaches the mock Provider, so
the assertion passes on the mock's own default body.

## Root cause

Three facts combine into a dead channel.

1. The BDD step sets the body through the fault-injection seam:

   ```go
   Faults: harness.FaultInjection{
       MessagesBody:  messagesStepRecord,
       MessagesCount: 2,
   }
   ```

2. `appendFaultEnvironment` (`tests/harness/cluster.go`) turns that into
   `AGENT_CLUSTER_TEST_MESSAGES_BODY=...` and appends it to the **Endpoint** process environment.

3. The mock Provider never reads that variable. It reads only the `--messages-body` flag
   (`providers/mock/main.go`, `flag.StringVar(&options.messagesBody, "messages-body", ...)`), and
   `providerFaultArgs` does not add `--messages-body` to argv. The variable cannot arrive by
   environment either, because `processRunner.command`
   (`internal/adapter/genericcli/runner.go`) sets the provider child environment to exactly the
   configured `Environment`, which is empty for this adapter document.

The harness comment above `providerFaultArgs` already states the rule: "argv is the only channel the
harness controls, which is why the mock accepts these as flags." The messages body was wired to the
environment anyway.

## Why the scenario still passes

The mock's default body is `"topsailai.task\nthe operator wrote this"`
(`sessionMessagesResult`), and its default `--messages-count` is `2`. The BDD constants are
`messagesStepLabel = "topsailai.task"`, `messagesStepText = "the operator wrote this"`, and the
scenario requests `MessagesCount: 2`. The defaults therefore equal the expected values exactly, so
`strings.Contains(text, messagesStepLabel)` succeeds without the injected record ever being used.

This is the "a green test proves nothing until it has been seen to fail" failure mode: the assertion
cannot distinguish "the record was unwrapped" from "the mock answered with prose that happens to look
unwrapped".

## Impact

The BDD layer does not cover provider step-record unwrapping, which is exactly the gap that let
`issues/messages-body-json-quoted-into-one-line.md` reach a live deployment. Any future regression in
`providerStepText` would keep the BDD suite green.

## Resolution

Resolved in two parts, because the issue's own fix list was incomplete and its prescribed proof would
have broken another test.

### Part 1 — the argv wiring was already fixed

`9dab1393` (`test: deliver the bdd messages body through provider argv`) added the two flags to
`providerFaultArgs` (`tests/harness/cluster.go:890-895`) and removed the dead
`AGENT_CLUSTER_TEST_MESSAGES_BODY` / `..._MESSAGES_COUNT` entries from `appendFaultEnvironment`. The
channel now works.

### Part 2 — the coincidence was still there, and the issue's step 3 was never done

The wiring being correct is not the same as the scenario being able to detect a broken wiring. The
mock default still equalled the fixture, so the scenario could not fail. This was verified rather than
assumed: disabling the argv emission (`if false && faults.MessagesBody != ""`) left the scenario
**green**:

```text
150 scenarios (1 passed, 149 undefined)
3 steps (3 passed)
--- PASS: TestFeatures/a_structured_body_is_unwrapped_instead_of_printed_as_JSON
```

The issue's step 3 proposed changing the mock default to prove the scenario can fail. That direction
was rejected because `tests/integration/messages_roundtrip_test.go:23` deliberately depends on the
default: `messagesFirstBody` is the unwrapped form of that exact default, and three assertions compare
against it. Changing the default would have broken the integration layer to fix the BDD layer.

The fix was therefore the inverse and smaller: make the BDD fixture **distinguishable** from the
default, so a broken channel falls back to the default and the assertion fails.

| Constant | Before | After |
|---|---|---|
| `messagesStepRecord` | `{"step_name":"task","raw_text":"the operator wrote this"}` | `{"step_name":"bddtask","raw_text":"the operator wrote this bdd record"}` |
| `messagesStepLabel` | `topsailai.task` | `topsailai.bddtask` |
| `messagesStepText` | `the operator wrote this` | `the operator wrote this bdd record` |

The mock default was left untouched, so the integration layer is unaffected.

### Part 3 — a guard so the coincidence cannot return

`tests/bdd/messages_fixture_guard_test.go` reads `providers/mock/main.go` as text and fails when it
contains either expected value. Absence is the property that matters: the mock cannot answer with a
value it does not contain, so a default that coincides with the fixture is impossible while the guard
holds. It also asserts the configured body is still a step record, because a prose body would make the
unwrapping scenario pass without anything being unwrapped.

## Verification

The decisive check is the one the issue asked for and never got: break the channel, confirm the
scenario fails.

| Check | Result |
|---|---|
| Channel intact, distinctive fixture | 4 messages scenarios pass (13 steps) |
| Channel broken (`if false && faults.MessagesBody != ""`) | **FAILS**: `the step label "topsailai.bddtask" is missing, so the unwrapped body did not reach the terminal` |
| Guard with the coincidence present | **FAILS**: `the mock provider source contains the operator text "the operator wrote this bdd record", so its default answer can satisfy the assertion without the configured body arriving` |
| Guard with the coincidence absent | passes |
| Integration messages round trip | `ok tests/integration 5.957s` — the mock default was correctly left alone |
| Full BDD suite | 148 passed, 2 failed — both pre-existing, see below |
| Committed tree, extracted with `git archive` | guard passes, unwrapping scenario passes |

### The two remaining BDD failures are pre-existing

`tui logs reports unsupported capability` and `a command in flight during a re-home is reported as
unknown` both fail at pristine HEAD `a815e14f`, reproduced in a detached extraction before any of this
change existed. The second is already tracked as `issues/bdd-rehome-in-flight-never-reaches-provider.md`.

### The issue's "blocking observation" is outdated

The issue recorded that the whole BDD suite was red with `endpoint "endpoint-1" was not found`, and
that the fix could not be validated until that was resolved. That is no longer true: the suite runs,
and the messages scenarios pass. The blocking claim was checked rather than trusted, and it did not
hold.

## Commits

- `4edfea32` `test: make the bdd messages fixture distinguishable from the mock default`
- `9dab1393` (pre-existing) `test: deliver the bdd messages body through provider argv`
