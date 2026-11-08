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
CollectionDelayMS: 100}` and waits at most 5 seconds for the inventory to reach the stale state.
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

## Correction: the earlier root cause was wrong

The resolution above raised the budget from 5 s to 30 s and concluded the flake
was "a timing budget, not a logic defect". That conclusion was wrong, and the
flake reappeared after the merge with the 30 s budget already in place. Raising a
deadline cannot fix a missed window, so the budget was never the lever.

### Measured root cause

The scenario injects `ProviderFailAfterN: 1`, so discovery call 1 succeeds and
call 2 fails. `collectionLoop` publishes immediately, then waits
`CollectionDelayMS` (100 ms) and publishes again. The non-stale successful
document therefore exists only for one collection delay.

Measured on this host with a 5 ms probe: the non-stale document was observable
for 46-65 ms across four runs (51.9, 60.4, 46.7, 65.5 ms), while
`waitRealInventory` polls every 50 ms. A poll interval that is comparable to the
window cannot reliably observe it, so the first wait usually missed it and then
waited the full budget for a state that had already gone. The 30 s budget made
each failure slower, not rarer.

The earlier "passes when run alone" observation is consistent with this: an idle
machine polls at a phase that happens to land inside the window, and load shifts
the phase.

### Fix

The scenario no longer races the transient window. The durable stale document
carries the same evidence, so the steps assert on it:

- `the real Endpoint refreshes inventory after provider failure` waits for the
  durable stale document: one adapter, `Stale`, `DataKnown`,
  `CollectionFailed`, a recorded `LastSuccessAtMS` and retained sessions.
- `the real source retains its sessions and is automatically marked stale`
  asserts `LastSuccessAtMS < LastAttemptAtMS`, which is the durable proof that a
  successful collection happened first and its data was kept, plus that every
  retained session is non-empty and attributable to the stale adapter.

Assertion strength was not reduced. The previous version compared the stale
document against a captured first document; the new version proves the same
ordering from the durable document alone, and additionally checks session
attribution.

### Verification

- Scenario run 5 times in isolation: 5/5 pass (4.06-4.71 s each).
- Full suite `go test ./...`: exit 0, 19 packages ok, 0 FAIL.
- Non-vacuity proven by two mutations of `internal/endpoint/collector.go`:
  - `snapshot.Stale = true` -> `false` in the retained-data branch: scenario
    fails with `Stale:false`.
  - `snapshot.Sessions = previous.Sessions` -> `nil`: scenario fails with
    `sessions=0`.
  Both mutations were reverted and `collector.go` is unchanged.
