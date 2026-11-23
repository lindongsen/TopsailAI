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

Fixed. Both operations now have one allowing and one refusing scenario, and both markers are
registered in `operationScenarioMarkers`.

`agent.model.registry` is a read-only `view` query that addresses the machine, so its scenario sits
in `endpoint_query_permission_matrix.feature` beside the other query rows. `agent.model.set` is a
mutating `control` operation, so its scenario sits in `endpoint_permission_matrix.feature` beside the
other command rows.

Four supporting changes were required, and each one is load-bearing rather than incidental:

- The mock Provider had to advertise and answer `agent.model.set`. Without it the Endpoint drops the
  capability at the intersection and the command is refused as unsupported before the policy hook, so
  the refusal scenario would pass while proving nothing about authorization.
- The mock's evidence entry declares version `"1"`, not `"v1"`. The Cluster intersects a capability by
  name AND version, so a `"v1"` entry would be silently dropped and every set command refused as
  unsupported while the descriptor still looked complete.
- The harness capability list had to declare `agent.model.set`, for the same intersection reason.
- The permission-matrix cluster had to declare the operation's own payload schema version through
  `CapabilityVersions`. Declaring the operation without its version advertises it as `"v1"`, which the
  intersection drops.

The `agent.model.set` payload is computed at submit time from a live registry read rather than
hardcoded, because the Endpoint refuses a profile it never minted. That read uses the **view** token,
not the row token: the row token holds only `control`, so reading with it would be refused and the
positive scenario would fail for a reason unrelated to the operation under test.

### Evidence

`make test-bdd` passes all six groups (`rehome-receipts`, `rehome-fallback`, `rehome`, `policy`,
`lifecycle`, `surface`). `make test-unit` passes all 22 packages. `go build ./...` and
`go vet ./tests/bdd/` are clean.

The coverage has teeth, proven by breaking each guard in turn:

| Guard broken | Result |
|---|---|
| The registry scenario removed from the feature file | `1 operation(s) have fewer than two scenarios, so one direction is unproven: [agent.model.registry (marker the model registry is read with the appears 0 time(s), want 2)]` |
| The set refusal scenario removed | `1 operation(s) have fewer than two scenarios, so one direction is unproven: [agent.model.set (marker the agent model set command is submitted appears 1 time(s), want 2)]` |
| The `agent.model.set` version declaration removed from `CapabilityVersions` | The positive scenario failed with `allowed command ended with error_code="unsupported"`, proving the intersection drops the capability and the scenario would otherwise have proven nothing |
