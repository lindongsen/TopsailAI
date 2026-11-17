---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# The collector maps an already-cluster resource ID a second time

## Trigger

Discovered while renaming `session.SessionID` to `session.ClusterSessionID` in
`internal/endpoint/collector.go`. The rename made it visible that the value being
mapped is already a cluster ID.

## The defect

The TopsailAI adapter mints the opaque cluster resource ID inside `Discover`:

```go
// internal/adapter/topsailai/adapter.go
clusterSessionID := providerSessionID
if a.config.ResourceMapper != nil {
    mapping, err := a.config.ResourceMapper.GetOrCreateResourceID(ctx, a.config.AdapterID, providerSessionID, ...)
    clusterSessionID = mapping.ResourceID
}
```

The collector then treats that value as a provider key and maps it again:

```go
// internal/endpoint/collector.go
clusterSessionID := session.ClusterSessionID
if c.resourceMapper != nil {
    mapping, err := c.resourceMapper.GetOrCreateResourceID(ctx, session.AdapterID, clusterSessionID, ...)
    clusterSessionID = mapping.ResourceID
}
```

## Why it is currently harmless

`GetOrCreateResourceID` is idempotent for an existing key, so in the happy path the
second call returns the same resource ID it was given. The observable behaviour is
therefore correct today, which is why the defect survived.

## Why it is still a defect

The second call is not a no-op in every case. It creates a mapping row keyed by a
value that is already a cluster ID, so the mapping table accumulates an entry whose
provider key is not a provider key. Two consequences follow:

- A `LookupResourceID` failure on the second call would create a spurious mapping row
  rather than surfacing the real failure, so the error path is wrong even though the
  success path is right.
- The mapping table is the only place the provider-to-cluster relationship is
  recorded. An entry whose key is a cluster ID makes that relationship ambiguous, and
  a future reconciliation that reads the table cannot tell the two kinds of key apart.

## Why it was not fixed with the rename

The rename changed field names only. Removing the second mapping changes which
component owns the mapping decision, which is an architectural question: either the
adapter mints the ID and the collector trusts it, or the adapter reports the provider
key and the collector mints the ID. Both are defensible, and choosing one changes the
adapter contract. That decision does not belong inside a mechanical rename.

## Suggested direction

- Decide the single owner of the mapping. The adapter already needs the cluster ID to
  build a routable session, so the adapter owning it and the collector trusting it is
  the smaller change.
- If the collector keeps the mapping, the adapter must report the provider key in
  `ClusterSessionID`'s place, which contradicts the field name and should be rejected.
- Add a test that asserts the mapping table contains exactly one row per provider
  session after a collection cycle.

## Resolution

Fixed in `378b589f` and `c9e14015`.

### The quoted code was already stale

The issue quotes the collector calling `GetOrCreateResourceID` unconditionally.
Commit `a46e4196` had already added a `LookupResourceID` guard, so the defect was
reachable only in the fallback branch, not on every row as the issue implies.

### The failing test asserted the defect as the remedy

`TestCollectDoesNotReuseWrongKindMapping` asserted that a foreign Task resource ID
is *remapped* into the Session namespace. That remap is the defect: it stores a
mapping row whose `provider_resource_key` is `res_<32 hex>`, so the table can no
longer distinguish a provider key from a Cluster ID. The test certified the bug,
which is why it stayed green.

Only this one test failed. Five other tests named during the investigation pass
because their fixtures report bare provider keys such as `provider-session-1`,
which do not match `protocol.IsClusterResourceID` and therefore take the normal
minting branch.

### Chosen shape

A row whose value is Cluster-ID-shaped is withheld and the cycle is reported
`partial` with `resource_mapping_failed`. The healthy rows observed in the same
cycle are still published, because one unattributable row must not discard them.
A cycle that withholds every row is downgraded to `failed` with `DataKnown=false`,
because publishing `partial` with an empty list reads as "known, and there are no
sessions" and would make existing rows disappear.

`protocol.IsClusterResourceID` was reused rather than a new prefix check being
written, because that helper is documented as the one place the prefix is spelled.

### A second defect found by the test, not by review

The success branch assigned freshness after `mapSessions` returned, overwriting the
downgrade. An all-withheld cycle therefore published `partial` with
`DataKnown=true` and an empty list. The assignment is now guarded by
`CollectionStatus != CollectionFailed`.

### Verification

Each guard was disabled in turn and the matching test failed, then the guard was
restored and the suite passed:

| Disabled | Failure |
|---|---|
| `IsClusterResourceID` case | `1 mapping rows are keyed by a Cluster resource ID, want 0` |
| all-withheld downgrade | `adapter collection status="partial", want "failed"` |
| freshness guard | `adapter summary claims known data although every reported row was withheld` |

`go test ./internal/endpoint/` passes, including in a clean checkout of the
committed tree. `go vet` and `gofmt -l` are clean.

### Concurrent work carried in the same commit

`collector.go` also held another agent's uncommitted partial-discovery work
(`LogCollectionFailure`, the `partial` branch in `apply`, the `mapSessions`
extraction). `mapSessions` did not exist in HEAD, so the two changes are
textually interleaved inside one function and cannot be separated by hunk. The
human approved committing both together, and the commit message names both parts.
