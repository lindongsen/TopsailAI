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
