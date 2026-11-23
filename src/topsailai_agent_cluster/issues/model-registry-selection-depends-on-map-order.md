# Model registry selection depends on map iteration order

## Symptom

`TestExecutorModelRegistryCombinesEveryCapableAdapter` fails intermittently:

```text
--- FAIL: TestExecutorModelRegistryCombinesEveryCapableAdapter (0.00s)
    model_registry_test.go:126: selection="mp-b" source="project"
```

The test expects `mp-a` / `workspace` (the `first` adapter's selection) and sometimes
observes `mp-b` / `project` (the `second` adapter's selection).

## Reproduction

Pre-existing at HEAD `df0d2a90`. Reproduced in a detached worktree at HEAD, full
`./internal/endpoint` package, 1 failure in 5 runs, and again in 1 of 8 runs:

```bash
git worktree add --detach .tmp/head-check HEAD
cd .tmp/head-check/src/topsailai_agent_cluster
for i in $(seq 1 8); do
  TMPDIR=/tmp/head-tmp go test -count=1 ./internal/endpoint 2>&1 | grep -E '^--- FAIL'
done
```

Passes 5/5 in isolation and 2/2 as a full package run on the working tree, so it is
load-sensitive rather than deterministic.

## Root cause

`internal/adapter/registry.go:55` stores configured instances in a map:

```go
instances map[string]*instance
```

`Executor.ModelRegistry` iterates that map to combine every capable adapter's
registry. Go randomises map iteration order, so which adapter is visited first
varies between runs.

The test's own comment states the opposite of what the code does:

```go
// The first adapter that reports a selection wins, so the answer never depends
// on configuration order.
if result.CurrentProfileID != "mp-a" || result.CurrentSource != protocol.ModelSourceWorkspace {
```

The comment describes an intent the implementation does not provide. The
combination rule is "whichever adapter the map yields first", which is exactly a
dependence on configuration order.

## Detection gap

The test asserts a specific winner while the implementation has no defined winner.
It passes whenever the map happens to yield `first` first, which is most runs, so
the assertion looks like it verifies a rule. Only a repeated full-package run
exposes it, and a single green run certifies nothing.

This is the same class as the recorded lesson about a test that indexes a shared
slice by position: the test asserts an ordering the runtime does not guarantee.

## Impact

Operator-visible on a machine with more than one capable Adapter instance that
reports a selection: `model registry` can report a different current model on
consecutive invocations with no configuration change. The combined `entries` list
is unaffected; only `current_profile_id` and `current_source` are ambiguous.

## Not fixed here

Outside the scope of the interrupt-warning change that discovered it. Two possible
resolutions, and the choice is a contract decision rather than a bugfix:

1. Define a deterministic winner, for example the lexicographically smallest
   `adapter_id`, and sort the iteration.
2. Report the ambiguity instead of picking one, for example an empty
   `current_profile_id` with a reason, because two adapters disagreeing about the
   machine's model is a real disagreement rather than something to resolve
   silently.

Option 2 matches the existing rule that a machine with several models per folder
reports `current_source` separately rather than folding them into one value.

## Verification of the claim

- `git worktree add --detach .tmp/head-check HEAD` at `df0d2a90`.
- 8 full-package runs, 1 failure, same test, same message.
- The change under review touches no file in `internal/adapter/registry.go` or
  `internal/endpoint/model_registry*.go`.
