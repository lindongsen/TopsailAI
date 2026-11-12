---
maintainer: AI
author: DawsonLin
status: open
created: 2026-11-12
---

# Command-path policy refusals produce a receipt but no log line

## Symptom

An operator auditing "who tried what on this machine" sees every refused **read** and no refused
**write**. The refusal itself is correct: the command is rejected with `policy_denied`,
`delivery_boundary=not_started` and `effect_certainty=not_applied`, and the provider is never
invoked. Only the audit trail is missing.

Measured on the live fleet on 2026-11-12, after a denial matrix that exercised 16 operations
against three Endpoints from a CLI carrying no Endpoint token:

```text
$ grep -ac "access policy refused" /opt/agent-cluster/logs/endpoint.log
42

$ python3 -c "count operations in those 42 lines"
agent.model.list   6
history.read       7
launch.query       3
messages.read      6
output.follow      7
output.read       13
total             42
```

Every one of those 42 is a read. The same matrix produced command-path refusals for
`message.send`, `context.inject`, `execution.interrupt`, `command.exec`, `agent.stop`,
`agent.start`, `agent.drive.start` and `agent.drive.stop`, and **none of them appears in the log**.

## Root cause

The two paths log in different places, and only one of them logs.

- Read path: `internal/endpoint/accesspolicy_enforce.go:47` calls
  `s.loggerWarn("endpoint access policy refused operation", ...)` before returning the refusal.
- Command path: `internal/endpoint/executor.go:138-140` calls `e.PolicyHook`, and on error returns
  `e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "policy_denied"))`.
  `recordEarlyRejection` (`executor.go:397-405`) writes the receipt to storage and returns. It has
  no logger, and `Executor` holds no logger field at all — `grep -n "logger\|Logger" internal/endpoint/executor.go`
  returns only `receipt.ErrorMessage` assignments.

So the refusal is durable in the command journal and invisible in the log. The receipt is
queryable by `command_id`, but only if the operator already knows the ID; nothing announces that a
refusal happened.

## Why this matters

The Endpoint is the only authorizer in this architecture. The Server forwards without deciding, so
the Endpoint log is the single place where a refused attempt is recorded as an event. A read
refusal leaves a trace; a write refusal leaves none. An operator investigating an unexpected
`policy_denied` on a mutating operation therefore has no log evidence that the attempt occurred,
and a repeated probing pattern against write operations is invisible.

This is the same class as the recorded lesson that a failure must be logged with enough detail to
diagnose it without re-running the code: the refusal is correct, but the evidence is absent.

## Suggested fix

Log the refusal where it is decided, not where the receipt is stored, so both paths emit one line
with the same shape. The minimal change is to give `Executor` a logger and emit
`endpoint access policy refused operation` with `operation`, `command_id` and `error` before
`recordEarlyRejection`, matching the read path's message so one grep finds both.

Do not log inside `recordEarlyRejection`: that function also handles `unsupported`,
`profile_required`, `target_still_active` and `target_generation_mismatch`, which are different
decisions and must not be reported as policy refusals.

## Not fixed in this task

Recorded only. The live acceptance result stands on the receipt evidence, which is authoritative
for what happened to the command; this issue concerns the audit trail, not the authorization
decision.
