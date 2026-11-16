---
maintainer: AI
author: DawsonLin
---
# `create_time_raw` is a redundant field that a sibling project still consumes

## Status

Producer removed. Consumer not yet updated. The field is gone from
`topsailai project list_sessions --json` in this workspace, but
`/TopsailAI/src/topsailai_agent_cluster` still reads it, so its
`created_at_ms` history value is now always zero until the cluster switches to
`create_time`. The human accepted this ordering and will handle the cluster
side.

## Requested by the human

While reviewing which fields `topsailai project list_sessions --json` adds on
top of `topsailai_list_sessions --json`, the human approved removing
`create_time_raw` and asked to check whether anything uses it first. The check
found a real consumer in a sibling project, so the removal was deferred and the
human instructed: file one issue for it. The human then instructed: remove it
now, and the cluster side will be handled separately.

## Summary

`create_time_raw` is a byte-for-byte duplicate of the upstream `create_time`
field. Nothing inside `cli/` reads it. However,
`topsailai_agent_cluster/providers/topsailai/query.go` declares it in its
`historyEntry` struct and converts it into `created_at_ms`, so removing the
field today would silently zero that value in the cluster's history output.

## Evidence that the field is redundant inside this workspace

Measured against 30 real rows from `topsailai project list_sessions --json`:

```
create_time_raw == create_time : 30/30
```

A repository-wide search for `create_time_raw` inside `cli/` finds only the
producer, its docstring, the usage document, and one test assertion. No reader.

The one other hit, `cli_topsailai/projects.py:345`, is an unrelated local
variable of the same name that reads `created_at` from a managed-project record.
It is not this JSON field and must not be touched.

## The external consumer

`/TopsailAI/src/topsailai_agent_cluster/providers/topsailai/query.go`:

```go
type historyEntry struct {
	SessionID        string `json:"session_id"`
	SessionName      string `json:"session_name"`
	ProjectWorkspace string `json:"project_workspace"`
	ModifiedTimeRaw  string `json:"modified_time_raw"`
	CreateTimeRaw    string `json:"create_time_raw"`
	Task             string `json:"task"`
	No               int    `json:"no"`
	Status           string `json:"status"`
}
```

The struct is populated by running this exact command:

```go
runJSON(ctx, p.runner, []string{"project", "list_sessions", "--json"}, maxHistoryBytes, &entries)
```

`CreateTimeRaw` is then converted at `query.go:223`:

```go
providerTimeMS(entry.CreateTimeRaw)
```

and stored as `historyRowFact.CreatedAtMS` (`json:"created_at_ms,omitempty"`).

## Downstream reach of the value

`CreatedAtMS` is not cosmetic. It travels:

1. `providers/topsailai/query.go` → `historyRowFact.CreatedAtMS`
2. `internal/adapter/genericcli/adapter.go:400` → `protocol.HistoryRow.CreatedAtMS`
3. `internal/tui/history.go:124` → `HistoryViewRow.CreatedAtMS`
4. `internal/tui/history.go:307` → `RenderJSON(out, view)` in JSON mode

It is **not** rendered in the human-readable history table: `historyCells()`
does not reference it. So the visible table would look unchanged, which is
exactly why the loss would be easy to miss. The JSON consumer would see
`created_at_ms` disappear because of `omitempty` on a zero value.

## Why `providerTimeMS` makes the loss silent

```go
func providerTimeMS(raw string) int64 {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return 0
	}
	...
	return 0
}
```

An absent field decodes to `""`, which returns `0` with no error. The cluster
cannot distinguish "the provider never had a creation time" from "the provider
stopped sending the field". There is no failure, no warning, and no log line.

## A second decode site that is unaffected

`providers/topsailai/mutation_authority.go:150` also decodes
`project list_sessions --json` into `[]historyEntry`, but it only reads
`entry.SessionID`. That path does not depend on `create_time_raw` and needs no
change.

## Required change in the sibling project

Before this workspace can drop the field, the cluster must read the upstream
`create_time` instead:

- Add `CreateTime string \`json:"create_time"\`` to `historyEntry`, or rename
  the existing tag to `create_time`.
- Update `query.go:223` to pass the new field to `providerTimeMS`.
- Confirm the conformance fixture still exercises the path. Note that
  `tests/fixtures/topsailai_provider_conformance/main.go:90` currently emits an
  empty array for `list_sessions`, so no fixture pins this field today; a
  fixture row carrying `create_time` would make the contract explicit.

## Change already applied in this workspace

The human chose to remove the producer first, so all four steps are done:

1. Removed `"create_time_raw": create_time_raw` from the `entry.update()` call in
   `cli_topsailai/project_scope.py`.
2. Renamed the local variable to `create_time_value`, because it is still the
   fallback for `modified_time_raw` but no longer names an output field.
3. Updated the `Returns` docstring and the `project list_sessions` row in
   `docs/usage/topsailai.md`.
4. Updated the field list in
   `tests/unit/topsailai/test_project_scope.py::test_json_keeps_every_upstream_field`.

Verified: `topsailai project list_sessions --json` now emits 38 fields per row
instead of 39, `create_time_raw` is absent, `create_time` is still present, and
the project-scope additions are exactly `no`, `modified_time`,
`modified_time_raw` and `status`. Unit suite 3489 passed, BDD suite 141 passed.

## Current breakage until the cluster is updated

`topsailai_agent_cluster` decodes `create_time_raw` into `CreateTimeRaw` and
converts it with `providerTimeMS`, which returns `0` for an absent field. Until
the cluster reads `create_time` instead, every history row it builds carries
`created_at_ms: 0`, and `omitempty` removes the key from its JSON output. The
human-readable history table is unaffected because it never renders that value.

## Why this was filed before the fix

The workspace README states that a change requiring a corresponding change in a
sibling source tree is out of scope and must be reported rather than edited.
The issue records the consumer contract so the cluster change can be made
deliberately instead of being discovered from a silently zeroed timestamp.
