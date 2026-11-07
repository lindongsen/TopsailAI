---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectCode: agent-cluster
programming_language: go
---

# BDD real-cluster stale scenario fails under full-parallel load

## Symptom

`go test -count=1 ./...` fails in `tests/bdd`:

```text
--- FAIL: TestFeatures (434.04s)
    --- FAIL: TestFeatures/failed_source_retains_its_last_successful_data_as_stale (15.46s)
        suite.go:640: real inventory did not reach expected state
```

The same suite passes when run alone: `go test ./tests/bdd -count=1` -> exit 0, `ok ... 371.891s`.

## Reproduction

1. `go test -count=1 ./...` from the project root (all packages in parallel).
2. Observe the failure above.
3. `go test ./tests/bdd -count=1` alone -> passes.

## Location

- Scenario: `features/inventory.feature:30` (`failed source retains its last successful data as stale`).
- Steps: `tests/bdd/steps_inventory.go:339-378`.
- Polling helper: `tests/bdd/steps_inventory.go:406-419` (`waitRealInventory`, 5 s deadline, 50 ms poll).

## Suspected cause

The scenario starts a real cluster with `FaultInjection{ProviderFailAfterN: 1,
CollectionIntervalMS: 100}` and waits at most 5 seconds for the inventory to reach the stale state.
Under full-parallel package load the real Endpoint's collection cycle and the provider fault
injection can exceed that window, so the poll deadline expires before the expected state appears.
The failure is a timing budget that is too tight for a loaded machine, not a logic defect in the
stale-retention behaviour: the identical assertions pass when the machine is idle.

## Impact

- Full-suite verification is not reliably green, so a real regression could be masked by an
  expected flake.
- No user-visible behaviour is affected; the product path is unchanged.

## Suggested direction

- Raise the wait budget for real-cluster scenarios, or make it configurable through the harness.
- Prefer waiting on an observable condition with a generous deadline over a fixed short timeout.
- Keep the assertion strength unchanged; only the deadline should move.
- Consider marking real-cluster scenarios so they can run serially or with a dedicated target.

## Status

Resolved. The wait budget was raised and the timeout diagnostic was made
actionable; the assertion strength is unchanged.

## Resolution

The flake was a timing budget, not a logic defect, so only the deadline moved.

- `tests/bdd/steps_inventory.go` now defines `realInventoryWait = 30 * time.Second`
  and all four real-cluster call sites use it instead of a literal
  `5*time.Second`. The poll still returns on the first match, so a healthy run is
  not slowed down; only a genuinely stuck collection waits longer.
- `waitRealInventory` now reports the budget and the last observed document on
  timeout, instead of the bare `real inventory did not reach expected state`. A
  failure can therefore be diagnosed from the log without re-running the suite,
  which is required by the project error-logging rule.
- The assertion strength is unchanged: the same predicates decide success, and no
  scenario was skipped, marked serial or weakened.

Guard: `tests/bdd/steps_inventory_wait_test.go` asserts the budget stays generous
and that the timeout error names both the budget and the last read error. The
budget assertion was proven non-vacuous by reverting the constant to
`5 * time.Second` and observing the guard fail.

Verification limitation: the full `tests/bdd` suite could not be run to green in
this workspace because `tests/bdd/suite_test.go`, `tests/bdd/steps_watch.go`,
`tests/bdd/steps_unknown_input_offer.go` and `tests/harness/cluster.go` are being
edited by a parallel agent. The package compiles (`go vet ./tests/bdd/` exit 0)
and the new guard tests pass; the real-cluster scenarios themselves were not
re-executed after the change.
