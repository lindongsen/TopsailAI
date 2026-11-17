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

## Resolution

Fixed on 2026-11-17 in commit `122fee9b`.

### What changed

`Executor` gained an optional `Logger *slog.Logger` field
(`internal/endpoint/executor.go:32-36`). It is optional rather than required because every existing
construction path builds an executor without one, and a nil logger must mean "journal only", which
is the previous behaviour, not a crash.

The refusal is logged at the decision site, immediately before `recordEarlyRejection`
(`executor.go:205-212`), through a new `logPolicyRefusal` method (`executor.go:593-610`). The
message is `endpoint access policy refused operation`, identical to the read path's message at
`internal/endpoint/accesspolicy_enforce.go:47`, so one grep finds both paths. Fields are
`operation`, `command_id` and `error`.

The token is deliberately absent from the line. It is a secret, and a log that records it turns
every log reader into a credential holder. The command ID is enough to correlate the refusal with
the caller's own record and with the stored receipt.

`src/main/agent-cluster-endpoint/main.go:271` wires `executor.Logger = logger` before installing
`PolicyHook`, so the hook that produces the refusal always has a logger.

### Why the log is not inside `recordEarlyRejection`

`recordEarlyRejection` also records `unsupported`, `profile_required`, `target_still_active` and
`target_generation_mismatch`. Reporting those as policy refusals would send an operator to a policy
file that is correct. This was proven by moving the call into `recordEarlyRejection` as a deliberate
break: `TestNonPolicyRejectionLogsNoRefusal` failed with

```text
an unsupported operation must not be logged as a policy refusal, got map[command_id:policy-unsupported error:policy denied level:WARN msg:endpoint access policy refused operation operation:message.send]
```

### Tests

`internal/endpoint/executor_policy_log_test.go`:

| Test | What it pins |
|---|---|
| `TestPolicyRefusalIsLogged` | exactly one WARN record, with operation, command_id and the real refusal reason, and the adapter never invoked |
| `TestPermittedCommandLogsNoRefusal` | the paired negative: a permitted command logs nothing, so the test cannot pass by logging unconditionally |
| `TestNonPolicyRejectionLogsNoRefusal` | an unsupported operation logs nothing, which is what proves the log is not inside `recordEarlyRejection` |
| `TestPolicyRefusalToleratesANilLogger` | the default construction path does not panic |

`src/main/agent-cluster-endpoint/executor_logger_call_guard_test.go`:

| Test | What it pins |
|---|---|
| `TestExecutorLoggerIsWired` | `main.go` contains `executor.Logger = logger` |
| `TestExecutorLoggerIsWiredBeforeThePolicyHook` | the wiring precedes `executor.PolicyHook = func(`, because a hook installed on a logger-less executor refuses silently |

The guard tests exist because the behavioural tests construct their own `Executor` and set `Logger`
directly. Removing the wiring line from `main.go` kept all four behavioural tests green, which was
measured rather than assumed. This is the same gap the access policy warning fix had, and it is
closed the same way, following `catalog_deployment_guard_test.go`.

### Deliberate breakage evidence

Every test was proven by breaking the code it guards, then restoring it.

| Break | Result |
|---|---|
| Removed `e.logPolicyRefusal(intent, policyErr)` | `TestPolicyRefusalIsLogged` failed: `one policy refusal must produce exactly one log record, got 0: []` |
| Moved the call into `recordEarlyRejection` | `TestNonPolicyRejectionLogsNoRefusal` failed, naming the unsupported operation that was logged as a refusal |
| Downgraded `Warn` to `Info` | `TestPolicyRefusalIsLogged` failed: `the refusal must be logged at WARN, got INFO` |
| Removed `executor.Logger = logger` from `main.go` | all four behavioural tests still passed, exposing the call-site gap that the guard tests now close |
| Removed the wiring, with guard tests present | both guard tests failed, naming the missing assignment |
| Moved the wiring after the hook install | `TestExecutorLoggerIsWiredBeforeThePolicyHook` failed: `the policy hook is installed before the executor logger is wired` |

### Verification

```text
go test ./internal/endpoint/                          ok  7.265s
go test ./src/main/agent-cluster-endpoint/            ok  0.499s
go build ./...                                        clean
go vet ./internal/endpoint/ ./src/main/agent-cluster-endpoint/   clean
gofmt -l internal/endpoint/ src/main/agent-cluster-endpoint/     clean
```

### Limitation

The guard tests prove that `main.go` contains the wiring and that it precedes the hook. They do not
prove that a running Endpoint emits the line, because that requires a live Endpoint with a policy
that denies a mutating operation. The behavioural tests prove the executor emits exactly one WARN
record when its `PolicyHook` refuses, which is the decision the fix is about.

The deployed Endpoint binary predates this commit, so the live fleet will not emit the line until
the Endpoint is rebuilt and restarted. That restart is deliberately deferred while provider sessions
are running.
