---
maintainer: AI
author: DawsonLin
---

# Model registry selection depends on Go map iteration order

## Symptom

`TestExecutorModelRegistryCombinesEveryCapableAdapter` fails intermittently:

```text
model_registry_test.go:126: selection="mp-b" source="project"
```

The test expects `mp-a` / `workspace`, because the `first` adapter was configured before
`second`. It fails roughly 2 times in 10 runs.

## Reproduction

```bash
cd src/topsailai_agent_cluster
for i in $(seq 1 12); do
  go test ./internal/endpoint/ -run TestExecutorModelRegistryCombinesEveryCapableAdapter -count=1
done
```

Observed 3 failures in 12 runs on 2026-11-21. The same loop in a detached worktree at
`5a7b0368` failed 2 times in 10 runs, so the defect predates the version-flag change and is
not caused by it.

## Root cause

`Executor.ModelRegistry` (`internal/endpoint/model_registry.go:32`) iterates
`e.registry.AcquireAll()`, and `AcquireAll` (`internal/adapter/registry.go:220-228`) builds its
slice by ranging over `r.instances`, which is a `map[string]*instance`. Go randomises map
iteration order, so the slice order is a scheduling outcome rather than configuration order.

The selection rule at `internal/endpoint/model_registry.go:64-67` is "the first adapter that
reports a selection wins", and the comment above it states the intent:

> The current selection is a machine-level fact, so the first adapter that reports one wins and a
> later adapter cannot overwrite it. Overwriting would make the answer depend on configuration
> order, which is exactly the ambiguity the Endpoint refuses elsewhere.

The intent is to make the answer independent of configuration order. The implementation makes it
depend on map iteration order instead, which is worse: it is not reproducible and it is not
observable from the configuration.

## Impact

A machine with two Adapter instances that both report a current model profile returns a different
`CurrentProfileID` and `CurrentSource` on different invocations of the same read. An operator who
asks twice receives two different answers, and neither is wrong by any rule the contract states.

The `Entries` list is unaffected, because it is appended in whatever order the adapters are
visited and the test only asserts its length. `ObservedAtMS` is unaffected, because it takes the
maximum.

## Why the test did not catch it earlier

The test asserts a specific winner, so it does catch the defect, but only on the runs where the
map order happens to disagree with the configured order. A single green run therefore looks like
confirmation. This is the same class as the recorded lesson about a green test proving nothing
until it has been seen to fail: the assertion is correct and the failure is real, but the
probability of observing it in one run is low enough that it reads as flake.

## Possible fixes

1. **Order the instances deterministically.** Sort `AcquireAll`'s result by `adapter_id` before
   returning it, so every caller sees one stable order. This fixes the read and any other caller
   that depends on order, and it makes the selection rule reproducible.
2. **Make the selection rule order-independent.** Define the winner by a property of the data,
   such as the newest `ObservedAtMS`, or report every adapter's selection and let the consumer
   decide. This changes the contract, so it needs a decision rather than a fix.
3. **Assert the set instead of the winner.** This would make the test pass without fixing the
   defect, so it is not a fix.

Option 1 is the smallest change that preserves the stated contract. It belongs in
`internal/adapter`, not in the Endpoint, because the map is the registry's own storage and every
caller of `AcquireAll` inherits the same nondeterminism.

## Status

Recorded, not fixed. The version-flag change that discovered it does not touch the model registry,
and fixing an unrelated defect inside that commit would mix two logical units.
