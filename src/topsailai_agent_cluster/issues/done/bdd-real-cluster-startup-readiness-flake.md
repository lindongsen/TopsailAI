---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectCode: agent-cluster
programming_language: go
---

# BDD real-cluster startup fails under full-parallel load

## Symptom

`go test -count=1 ./...` fails in `tests/bdd`:

```text
--- FAIL: TestFeatures (244.41s)
    --- FAIL: TestFeatures/dispatched_command_remains_awaiting_confirmation_before_receipt (19.31s)
        suite.go:640: HTTP http://127.0.0.1:44755/healthz did not return 200 before deadline
```

The same scenario passes when run alone: `go test ./tests/bdd -count=1 -run
'TestFeatures/dispatched_command_remains_awaiting_confirmation_before_receipt'`
-> exit 0, `ok ... 5.462s`.

## Reproduction

1. `go test -count=1 ./...` from the project root (all packages in parallel).
2. Observe the failure above.
3. Run the single scenario alone -> passes in about 5 seconds.

## Location

- Scenario: `features/timeouts.feature:17` (`dispatched command remains awaiting
  confirmation before receipt`).
- Startup helper: `tests/harness/cluster.go` (`StartCluster`).
- Polling helper: `tests/harness/process_errors.go` (`WaitHTTPE`).

## Root cause

`StartCluster` waited for the Server health endpoint with a fixed
`15*time.Second` budget. The Server must open its database, load certificates and
start the channel listener before it answers. Under full-parallel package load the
machine runs several clusters at once, so startup exceeded the budget and the
scenario failed before it exercised any behaviour under test.

This is a timing budget, not a logic defect: the scenario passes alone, and 62 of
63 scenarios passed in the same failing run.

## Resolution

Only the deadline moved; the assertion strength is unchanged.

- `tests/harness/cluster.go` now defines `serverReadinessWait = 60 * time.Second`
  and `StartCluster` uses it instead of a literal `15*time.Second`. The poll still
  returns on the first successful response, so a healthy run is not slowed down;
  only a genuinely slow startup waits longer.
- The readiness wait moved into `waitServerReady(cluster, budget)`, which takes the
  budget as a parameter. A caller can therefore bound a diagnostic wait without
  mutating process-wide state, which the project rules prohibit.
- A readiness failure now reports `wait for server readiness: ...` in addition to
  the deadline message, so the failing phase is identifiable from the log without
  re-running the suite.

Guard: `tests/harness/cluster_readiness_test.go` asserts the budget stays generous
and that the failure names both the readiness phase and the deadline. The budget
assertion was proven non-vacuous by setting the constant to `15 * time.Second` and
observing the guard fail.

## Verification

- `gofmt -l tests/harness/` -> clean.
- `go vet ./tests/harness/` -> exit 0.
- `go test ./tests/harness/ -count=1` -> `ok 9.022s`.
- The previously failing scenario passes alone in 5.462s.

Verification limitation: the full `go test -count=1 ./...` suite was not re-run to
green after this change, because `internal/tui` and `tests/bdd/suite_test.go` were
being edited by a parallel agent at the time. The harness package itself is green.
