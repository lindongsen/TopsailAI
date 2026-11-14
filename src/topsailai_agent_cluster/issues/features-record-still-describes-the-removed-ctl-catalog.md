---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# The feature record still describes the removed Endpoint-local ctl catalog

## Trigger

Found while closing the documentation consistency items of Unit 9. The catalog
deployment claim and the catalog reference document were corrected in `86ed54e1` and
`f422dc78`, and the removed key was pinned by a guard in this turn. The feature record
was out of scope for those commits and is recorded here instead of being edited in
passing.

## Symptom

`features/90ai-added.md:140-147` describes the `ctl.` surface as driven by
`internal/adapter/topsailai/ctl_config.go`, with the catalog file named by
`AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION_FILE` as the only source of control actions.

Both facts are false today:

- `internal/adapter/topsailai/` does not exist. `ls -d internal/adapter/topsailai`
  exits 2 with "No such file or directory".
- `AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION_FILE` is no longer read. The `ctl.` family is
  advertised from the `ADAPTERS` document, and the Provider CLI reads its own catalog
  through `AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS`.

The section also names `ctl_actions.go`, `controlActionCapabilities` and
`controlActionArgs`, which no longer exist in that form.

## Impact

A reader of the feature record believes the Endpoint parses a provider argv template
and that a catalog file under the Endpoint controls the action surface. An operator
following it configures a key that has no effect and expects actions that are never
advertised. No runtime error points at the record, so the wrong belief survives.

## Expected

The section describes the current design: the `ctl.` family is advertised from the
`ADAPTERS` document, the Provider CLI owns the argv, and the Provider reads its catalog
through `AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS`. Historical sections may stay if they
are labelled as history.

## Scope

Documentation only. No source change is implied, because the implementation is already
correct.

## Verification

After the edit, a guard should pin that the feature record names no removed package
path and no removed key as current configuration. The existing guards in
`src/main/agent-cluster-endpoint/` already pin the removed key in the template and the
reference document, so this record needs its own check rather than a duplicate.
