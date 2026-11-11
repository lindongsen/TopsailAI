---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# A control action reload reaches admission but never the advertised inventory

## Trigger

Found while reviewing the adapter seam. The question was whether a provider can own its own
configuration reload, which required checking what the Endpoint does with a reloaded catalog.

## Symptom

After `SIGHUP` reloads the control action catalog, admission already uses the new action list, but the
inventory still advertises the old one. An operator sees a stale action surface until the Endpoint is
restarted. A newly added action is refused by the TUI as unadvertised even though the Endpoint would
accept it, and a removed action is still offered even though the Endpoint would refuse it.

## Root cause

Two different sources of truth are read at two different times.

Admission re-reads the descriptor on every command, so it always sees the current catalog:

- `internal/endpoint/executor.go:90` calls `instance.Describe(ctx)` per execution
- `internal/endpoint/launch.go:18` does the same for launch queries
- `internal/adapter/topsailai/adapter.go:135` appends `controlActionCapabilities(a.config.ControlActions)`
  to the descriptor, so `Describe` reflects the live set

The advertised inventory is frozen once at startup:

- `src/main/agent-cluster-endpoint/main.go:182` calls `Describe` once per binding
- `src/main/agent-cluster-endpoint/main.go:189` stores the result in `endpointservice.Binding.Capabilities`
- `internal/endpoint/collector.go:110` copies `item.binding.Capabilities` into every `SourceSnapshot`
- `internal/endpoint/composer.go:23` copies that into every `AdapterSummary`

The reload callback only logs:

- `src/main/agent-cluster-endpoint/main.go:144-150` calls `controlActions.WatchReload` with a callback
  that logs the new count and names, and does nothing else

So the reload updates the set that `Describe` reads, and never updates the `Binding` that the collector
publishes.

## Why it was not caught

Every test that exercises the catalog either loads it once before startup or asserts admission behaviour.
No test reloads the catalog and then reads the advertised capabilities, so the two paths are never
compared after a reload. The reload path itself is covered: the log line is asserted, which makes the
reload look verified while the inventory it does not update stays unexamined.

## Impact

The failure is fail-closed for a newly added action and leaves a stale advertisement for a removed one:

- A newly added action is advertised nowhere, so the TUI never offers it. The Endpoint would accept it,
  so the operator cannot reach a capability that is actually enabled.
- A removed action stays advertised, so the TUI offers it and the Endpoint refuses it. The operator sees
  a rejection for an action the interface claims is supported; execution still fails closed.

Neither case is unsafe, because the Endpoint still enforces the live catalog. Both cases make the
advertised surface disagree with the enforced surface, which is exactly the disagreement the catalog
exists to prevent.

## Fix

Implemented on 2026-11-11 with an event-driven descriptor refresh rather than calling `Describe` during every collection:

- A successful control-action reload calls `Describe` once for each affected TopsailAI binding.
- Collector updates the cached descriptor and composes a new revision from existing Session snapshots without provider discovery or changed freshness evidence.
- Endpoint immediately publishes the new revision and retains the latest unacknowledged report.
- Server acknowledges the revision only after committed storage represents it.
- Endpoint retries an unacknowledged report after a bounded delay and after reconnect; newer revisions supersede older pending reports.
- Control-action content contributes to the capability revision, so an action or schema change changes the advertised revision.

## Verification

Passed:

- `make test-unit-common`
- `make test-unit-server`
- `make test-unit-endpoint`
- `make test-integration`

Focused tests cover capability-only recomposition without discovery, preserved Session freshness, capability revision changes, old ACK rejection, matching ACK acceptance, and committed revision reporting.

## Status

Resolved. The inventory advertised by Server now converges on the action catalog loaded by Endpoint without requiring an Endpoint restart or repeated `Describe` calls during normal collection.
