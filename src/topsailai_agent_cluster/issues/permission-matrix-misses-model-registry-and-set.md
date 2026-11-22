---
maintainer: AI
author: DawsonLin
---

# The permission matrix has no scenario for agent.model.registry or agent.model.set

## Symptom

`make test-bdd` fails in six of its groups, and every failure is the same test:

```text
permission_matrix_coverage_test.go:123: 2 operation(s) are served by this build but have no
scenario marker registered, so the matrix cannot cover them: [agent.model.registry agent.model.set]
--- FAIL: TestPermissionMatrixCoversEveryKnownOperation (0.00s)
```

The six failing groups are `rehome-receipts`, `rehome-fallback`, `rehome`, `policy`, `lifecycle`
and `surface`. Each group runs the whole BDD package, so one failing test fails all of them. No
other test in the suite fails.

## Reproduction

```text
make test-bdd
```

The failure is deterministic, not intermittent.

## This defect predates the CLI surface parity work

Verified in a detached worktree at `06aebb88~1`, which is the commit before the first CLI parity
change:

```text
git worktree add --detach .tmp/wt-pre 06aebb88~1
cd .tmp/wt-pre/src/topsailai_agent_cluster
go test ./tests/bdd/ -run TestPermissionMatrixCoversEveryKnownOperation -count=1
```

Result: the same failure with the same two operation names. The five CLI parity commits do not
touch `tests/bdd/`, `features/` or `internal/endpoint/accesspolicy.go`; `git diff --stat
06aebb88~1..HEAD -- tests/bdd/ features/ internal/endpoint/accesspolicy.go` is empty.

## Root cause

`internal/endpoint/accesspolicy.go` serves both operations and lists them in
`KnownAccessOperations()`:

- `protocol.OperationAgentModelRegistry` at `accesspolicy.go:79` and `:708`
- `protocol.OperationAgentModelSet` at `accesspolicy.go:104` and `:711`

They were registered by `ef8a3bea` (registry read) and `21a93b0e` (model set contract). Neither
commit added a scenario marker to `tests/bdd/permission_matrix_coverage_test.go`, and neither
added the matching scenarios to `features/endpoint_permission_matrix.feature` or
`features/endpoint_query_permission_matrix.feature`.

The guard is working exactly as designed. Its own doc comment states the intent: "adding an
operation to knownAccessOperations without adding a scenario fails the build, instead of leaving
the matrix silently one row short while the suite stays green." The two operations were added and
the scenario was not, so the guard reports the omission.

## Why it was not noticed

`make test-unit` does not run the BDD package, so the unit suite stayed green through both
commits. The defect is visible only in `make test-bdd`, which is a separate target. A contributor
who ran only the unit target would see no problem.

## Impact

The permission matrix claims to prove both directions of authorization for every operation the
build serves: one scenario that allows the operation and one that refuses it. For these two
operations neither direction is proven. `agent.model.set` is a mutating `control` operation that
changes a machine-wide declaration, so an unproven refusal direction is the more serious half: a
policy that fails to refuse it would not be caught by any test.

## Resolution

Not yet fixed. Two scenarios are needed per operation, one allowing and one refusing, in the two
feature files named by `permissionMatrixFeatureFiles`, plus the marker entries in
`operationScenarioMarkers`. The marker must be a phrase that identifies the operation's own steps
and cannot be satisfied by another operation's steps, and it must appear at least twice in the
corpus because the guard requires both directions.

`agent.model.registry` is a read-only `view` query that addresses the machine, so its scenario
belongs in `endpoint_query_permission_matrix.feature` beside the other query rows.
`agent.model.set` is a mutating `control` operation, so its scenario belongs in
`endpoint_permission_matrix.feature` beside the other command rows.
