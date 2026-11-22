---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# Model registry selection depends on Go map iteration order

## Symptom

`TestExecutorModelRegistryCombinesEveryCapableAdapter` fails intermittently:

```text
--- FAIL: TestExecutorModelRegistryCombinesEveryCapableAdapter (0.00s)
    model_registry_test.go:126: selection="mp-b" source="project"
```

The test expects `mp-a` / `workspace`, because the `first` adapter was configured before
`second`. It fails roughly 2 times in 10 runs.

## Reproduction

Repeating the test inside one process reproduces it reliably, because Go randomises map
iteration order per range statement rather than per process:

```bash
cd src/topsailai_agent_cluster
go test ./internal/endpoint/ -run TestExecutorModelRegistryCombinesEveryCapableAdapter -count=20
```

Observed 2 failures in 20 runs on 2026-11-22. A single `-count=1` run passed 6 times in a row,
which is why the failure reads as flake.

The same loop in a detached worktree at `5a7b0368` failed 2 times in 10 runs, so the defect
predates the version-flag change and is not caused by it. It also reproduces at `acbaa889`:
`git diff acbaa889 HEAD` is empty for `model_registry.go`, `registry.go` and
`model_registry_test.go`, so the code under test is byte-identical there.

It has also been seen once inside `make test-unit-endpoint`, which runs `./internal/endpoint`
(`Makefile:88-91`), so the failure is reachable from the project's own test entry point and not
only from an ad-hoc `go test` invocation.

## Root cause

`Executor.ModelRegistry` (`internal/endpoint/model_registry.go:30`) iterates
`e.registry.AcquireAll()` (called at `:32`, loop at `:35`), and `AcquireAll`
(`internal/adapter/registry.go:220-239`) builds its slice by ranging over `r.instances`
(`registry.go:55`), which is a `map[string]*instance`. Go randomises map iteration order, so the
slice order is a scheduling outcome rather than configuration order.

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

### The defect is latent in the current deployment, not active

Both the shipped template and the installed node configure exactly one Adapter:

```text
conf/node.endpoint.conf.example:67   "adapter_id": "topsailai-local"
/opt/agent-cluster/conf/endpoint/node.conf:12   "adapter_id": "topsailai-local"
```

With one Adapter the winner is unambiguous, so no operator can observe the flip today. The defect
becomes reachable the moment a second Adapter is configured and both report a selection, which is
a supported deployment: `ADAPTERS` is a JSON array, and
`docs/agent-cluster-architecture.md` states that two Adapter instances of the same provider may
use different locally approved roots or execution identities.

This distinction matters for triage. It is not a live fault, so it does not justify an emergency
change; it is a latent contract defect that the test suite already detects.

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
2. **Make the selection rule order-independent.** Refuse the ambiguity: when two adapters report
   different selections, report the selection as unknown and name the conflict.
3. **Assert the set instead of the winner.** This would make the test pass without fixing the
   defect, so it is not a fix.

### A sorted order already exists in this package

Option 1 is not a new convention. `Registry.IDs()` (`internal/adapter/registry.go:181-190`)
already sorts by `adapter_id`, and its doc comment states the reason:

> The order is sorted rather than map order, because a caller that must choose one adapter
> without an identity to attribute has to make the same choice on every run. Map iteration order
> would make such a choice depend on the process, so the same command could reach a different
> adapter after a restart.

So if ordering is ever chosen, it should reuse that established rule rather than introduce a
second one. `AcquireAll` is the only accessor that still returns map order.

### Why ordering alone is not enough

Sorting makes the answer reproducible, but it does not make it correct. When two adapters
genuinely disagree about which model is in use, a sorted order still picks one arbitrarily — it
just picks the same one every time. The contract already refuses that class of ambiguity
elsewhere: the Provider rejects a registry that marks more than one entry as `selected`
(`providers/topsailai/src/model_registry.go:137`), and
`docs/agent-cluster-adapters.md` states that "which model is in use" must have exactly one
answer. Two adapters each reporting a different selection is the same ambiguity one layer up.

## Decision

Directed by the human on 2026-11-22, wording normalized, meaning preserved:

> 同意报冲突。

Option 2 is chosen: a conflicting selection is reported as a conflict rather than resolved by
order. The read must not silently pick a winner, whether that winner is decided by map order or by
sort order.

The implementation is deliberately deferred. The human directed that the code not be changed in
this unit, so this record carries the decision and the reasoning, not a patch.

Implementation notes for whoever picks this up:

- The conflict is a property of the combined answer, so it is detected in `Executor.ModelRegistry`
  after every capable adapter has answered, not inside `AcquireAll`. `AcquireAll` must keep
  returning every instance; it is a registry accessor, not a policy site.
- The existing `ModelRegistrySelectionInvalid` code is the closest fit and already maps to HTTP
  `409 Conflict` (`internal/server/model_registry.go:74`) and to an operator message in the TUI
  (`internal/tui/interactive_model_registry.go:131`). Reusing it keeps one vocabulary; a new code
  would need a Server mapping, a TUI message and a test for each.
- The message must name the conflict rather than the symptom. "The endpoint holds a model
  selection that cannot be resolved" is true but does not tell the operator that two adapters
  disagree, which is the fact they must act on.
- The `Entries` list should still be returned. Two adapters disagreeing about the current
  selection does not make their model lists invalid, and dropping the list would turn a selection
  conflict into an unusable registry.
- The test at `internal/endpoint/model_registry_test.go:126` must be rewritten, not relaxed. It
  currently asserts a winner, which encodes the behaviour being removed. The replacement must
  assert the conflict, and it must be proven to fail when the conflict detection is removed —
  otherwise it certifies nothing.

## Status

Recorded, not fixed. The version-flag change that discovered it does not touch the model registry,
and fixing an unrelated defect inside that commit would mix two logical units. The fix direction is
decided (report the conflict); the code change is pending.
