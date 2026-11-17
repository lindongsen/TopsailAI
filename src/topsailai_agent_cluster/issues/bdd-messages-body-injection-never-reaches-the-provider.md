---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
status: open
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
   },
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

## Fix

1. Add the body and count to `providerFaultArgs` so they travel by argv:

   ```go
   if faults.MessagesBody != "" {
       args = append(args, "--messages-body", faults.MessagesBody)
   }
   if faults.MessagesCount > 0 {
       args = append(args, "--messages-count", fmt.Sprint(faults.MessagesCount))
   }
   ```

2. Remove the now-misleading `AGENT_CLUSTER_TEST_MESSAGES_BODY` / `..._MESSAGES_COUNT` entries from
   `appendFaultEnvironment`, or keep them only if some other consumer genuinely reads them.

3. Prove the fix by making the scenario fail first: change the mock default body to a different
   string, confirm `a_structured_body_is_unwrapped_instead_of_printed_as_JSON` goes red, then restore
   the default and confirm it goes green. Without that step the change is unverified, because the
   current pass is indistinguishable from the coincidental pass.

## Verification

Not yet performed. The BDD suite is currently red for an unrelated reason (see below), so the fix
cannot be validated until that is resolved.

## Blocking observation

At HEAD `41250a46` with a clean Go tree, `go test ./tests/bdd` fails broadly with
`endpoint "endpoint-1" was not found` and `endpoint "endpoint-1" inventory not found`, including
scenarios unrelated to messages. Reproduced in isolation:

```text
go test ./tests/bdd -count=1 -run 'TestFeatures/a_structured_body_is_unwrapped_instead_of_printed_as_JSON' -v
--- FAIL: TestFeatures (8.21s)
the step label "topsailai.task" is missing, so the record was not unwrapped: endpoint "endpoint-1" was not found
```

The Endpoint process starts and logs `begin accepted command recovery` / `accepted command recovery
channel ready`, but never registers with the Server, so `WaitInventoryForE` times out. This is
pre-existing and independent of the messages body wiring; it needs its own investigation before the
fix above can be proven.
