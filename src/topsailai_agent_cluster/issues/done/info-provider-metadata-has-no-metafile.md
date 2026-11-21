---
maintainer: AI
author: DawsonLin
status: done
resolved: 2026-11-20
created: 2026-11-19
---

# `info` provider_metadata had no `metafile`, because its source command never emits one

## Trigger

Reported by the human on 2026-11-19, wording normalized, meaning preserved:

> The `info` output's `provider_metadata` has no `metafile` field, but the TopsailAI provider does
> provide it. Find out why.

## Symptom

`agent-cluster-cli info <session>` printed a `provider_metadata` section containing the session
record fields (`session_id`, `session_name`, `task`, token totals, `status`, `is_running`, ...) and
no `metafile` key. The same session's row in `topsailai workspace list --json` did carry a complete
`metafile` object.

## Root cause

The two surfaces read two different provider commands, and only one of them produces `metafile`.

`provider_metadata` was defined as the provider's own `session info --json` record
(`docs/agent-cluster-adapters.md:400`), and the provider CLI implemented exactly that
(`providers/topsailai/src/query.go:773`):

```go
stdout, stderr, runErr := p.runner.Run(ctx, []string{"session", "info", sessionID, "--json"}, nil)
```

`metafile` is produced by a different command. It is built in
`src/topsailai/cli/cli_topsailai/core.py:1579-1607` from the row's on-disk
`{session_id}.{pid}.session.meta` record and emitted as a `workspace list --json` item field:

```python
metafile = file_info.get("_workspace_session_meta_data")
if not isinstance(metafile, dict):
    metafile = None
...
"metafile": metafile,
```

`session info --json` is built by `_session_to_dict`
(`src/topsailai/cli/topsailai_session_info.py:105-150`) from the session database record
(`SessionData`), and that dictionary has no `metafile` key at all. It is a session-database
projection, not a workspace-row projection. A full-text search for `metafile` in
`topsailai_session_info.py` returns zero hits.

## Nothing was dropped cluster-side

The whole cluster chain forwards the document verbatim, so the absence was inherited from the source
and not introduced by the cluster:

| Layer | Site | Behaviour |
|---|---|---|
| Provider CLI | `providers/topsailai/src/query.go:773` | forwards `session info --json` stdout as `provider_metadata` |
| Generic CLI Adapter | `internal/adapter/genericcli/adapter.go:707` | copies `ProviderMetadata` unchanged |
| Protocol | `internal/protocol/detail.go:37-43` | opaque `string`, no modelling |
| CLI | `internal/tui/commands_info.go:26`, `internal/tui/detail.go:111,127-128` | renders the document through `renderStructuredBody` |

`renderStructuredBody` (`internal/tui/messages_body.go:56-93`) decodes the document and renders every
key it finds, so a key present in the source would be printed. It cannot add a key the source never
sent.

## Why the field was absent rather than empty

`metafile` is a per-row fact: it is the exact `{session_id}.{pid}.session.meta` record for one stdout
file, and one session identifier may own several rows. `session info` answers for the session, not for
a row, so it has no single metafile to report. This is the same reason the runtime envelope is read
from `workspace list` rather than from `session info`.

## Resolution

Resolved by `078879a2 fix: fill both detail seams from one runtime info read` on 2026-11-20, which
took a fourth option that this record did not list: replace the two-call path with one
`topsailai runtime info -s SESSION -p PID` call and split its document.

`detail()` now dispatches on whether the caller supplied an exact row with a PID
(`providers/topsailai/src/query.go:727-731`):

```go
if hasExact && exact.PID > 0 {
    return p.detailFromRuntimeInfo(ctx, sessionID, exact.PID)
}
return p.detailFromSessionRecord(ctx, sessionID, requested.ProviderTarget)
```

`detailFromRuntimeInfo` (`query.go:743`) runs `runtime info` and `splitRuntimeMember`
(`query.go:830`) gives the `runtime` member to `provider_runtime` and every other member to
`provider_metadata`. `runtime info` publishes the workspace-list item for one exact process, so
`metafile` is now part of the metadata seam.

The property is asserted by `TestSplitRuntimeMemberPreservesEveryOtherMember`
(`providers/topsailai/src/read_test.go:1001-1017`), whose fixture contains
`"metafile":{"pid":77,"status":"running"}` and requires it to appear unchanged in the metadata seam.

## What remains, and why it is not a defect

The fallback path `detailFromSessionRecord` (`query.go:772`) still reads `session info --json` and
therefore still reports no `metafile`. It is reached when the caller supplies no exact row, or a row
whose PID is zero, which is the unverified-session case: there is no process to address `runtime info`
with, so there is no row-level metafile to report. That is an unobservable row rather than a lost
field, and it is the same distinction `TestSessionDetailReportsNoRuntimeForAnUnobservableRow`
(`read_test.go:924`) already guards for the runtime seam.

## Options that were considered and not taken

1. **Provider-side.** Add `metafile` to `_session_to_dict` in the TopsailAI project. Not taken: it
   would mix a file record into a database projection, and per `MEMORY.md` a seam's content belongs
   to the Provider, so the Cluster must not push this change.
2. **Cluster-side, no new provider call.** Model `workspaceItem.Metafile` and forward it. Not taken:
   it would make `provider_metadata` carry two sources, and the single-call split above achieved the
   same result without a second document.
3. **Leave as is.** Superseded by the resolution above.

## Residual documentation defect

`docs/agent-cluster-adapters.md:400-401` still describes the two-call mapping as the only mapping,
because `078879a2` changed only `query.go`, `exact_target_test.go` and `read_test.go`. The table now
describes the fallback path and omits the exact-target path that most reads take. This is tracked
separately rather than fixed here, because it is a documentation change to a provider mapping table.
