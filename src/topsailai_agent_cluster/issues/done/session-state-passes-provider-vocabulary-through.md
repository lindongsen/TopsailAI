---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# Session state publishes the provider's own vocabulary

## Trigger

Discovered while renaming cluster and provider field names. The rename made the
producer of every field explicit, and `state` was the one field whose producer could
not be stated: it is neither purely cluster nor purely provider.

## The defect

`internal/adapter/topsailai/adapter.go` assigns the provider's own words to the
standard `state` field:

```go
state := item.State
if state == "" {
    state = item.Status
}
if generation == "" {
    state = protocol.SessionStateUnknown
}
```

Only the third branch produces a cluster word. The first two pass the provider's
`state` and `status` strings through unchanged, so the wire value is whatever the
provider happened to print.

## Why this contradicts the contract

`docs/agent-cluster-protocol.md` states the rule:

> Map only states supported by actual evidence; publish only a standard bounded
> reason code/message, keeping provider-specific diagnostics local.

The document also names a closed vocabulary: `running`, `idle`, `waiting_input`,
`stopped`, `unknown`. The code does not enforce it, so a provider that reports a new
word reaches the operator surface unchanged.

## Why it matters

The TUI colour mapping and the fleet summary both switch on `state`. An unrecognized
value falls through to the `default` branch, which is the uncertain middle. A provider
that renames `running` to `active` would therefore turn every healthy session yellow
with no cluster-side change, and the summary counts would silently move from the
running bucket to the unknown bucket.

This is the same class of defect as the `StatusLabel` finding recorded in `MEMORY.md`:
a cluster-side mapping that looks operation-agnostic is a cluster defect even when the
only shipped adapter cannot reach it, because the contract is what a second adapter
will be written against.

## Why it was not fixed with the rename

The rename changed field names only. Fixing this requires deciding the mapping table
for every provider word, and deciding what to do with an unrecognized word: reject the
report, or map it to `unknown` and keep the provider word in `state_reason`. That is a
behaviour change with its own acceptance criteria, so bundling it into a rename would
have hidden it inside a diff that reviewers read as mechanical.

## Suggested direction

- Map the provider's documented words to the closed cluster vocabulary in the adapter,
  and keep the provider's original word in `state_reason`.
- Map an unrecognized word to `unknown` rather than passing it through, so the colour
  mapping and the summary stay correct.
- Add a test that feeds an unrecognized provider word and asserts the published state
  is `unknown` with the provider word preserved as the reason.
