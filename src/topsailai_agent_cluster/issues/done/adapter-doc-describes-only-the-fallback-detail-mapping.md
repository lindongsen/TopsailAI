---
maintainer: AI
author: DawsonLin
status: done
resolved: 2026-11-21
created: 2026-11-21
---

# The adapter document described only the fallback detail mapping

## Symptom

`docs/agent-cluster-adapters.md:398-401` stated one mapping per seam:

| Standard seam | Provider entry |
|---|---|
| `provider_metadata` | `topsailai session info <session_id> --json` |
| `provider_runtime` | `topsailai workspace list --json --local -s <session_id> --include-runtime`, the `items[row].runtime` envelope |

That table described the fallback path only. Since `078879a2 fix: fill both detail seams from one
runtime info read`, the path most reads take is a single `topsailai runtime info -s SESSION -p PID`
call whose document is split by `splitRuntimeMember`.

## Root cause

`078879a2` changed three files and no document:

```text
providers/topsailai/src/exact_target_test.go
providers/topsailai/src/query.go
providers/topsailai/src/read_test.go
```

The dispatch it introduced (`providers/topsailai/src/query.go:727-731`) has two branches, and only
the second one matched the documented table:

```go
if hasExact && exact.PID > 0 {
    return p.detailFromRuntimeInfo(ctx, sessionID, exact.PID)
}
return p.detailFromSessionRecord(ctx, sessionID, requested.ProviderTarget)
```

The first branch is the one the CLI reaches, because it passes the inventory row's `provider_target`
(`internal/tui/commands_info.go:57`, `internal/tui/detail.go:84`) and that slot carries the PID
(`providers/topsailai/src/read.go:307-309`). So the document described the less-travelled branch as if
it were the whole mapping.

## Why it mattered

The table is the only place that records which provider command produces each seam, and
`docs/agent-cluster-adapters.md` states that this is deliberate: provider detail belongs there and
nowhere else. A reader who trusted it would look for `session info` and `workspace list` in a code path
that runs neither, and would not find `splitRuntimeMember` at all.

The consequence was not cosmetic. The document also stated that `provider_runtime` is host-scoped
because the provider read passes `--local`. That is true of the fallback branch and false of the
exact-target branch, which passes no `--local` because it addresses one PID directly. The
unobservable-row explanation therefore described one branch while reading as a property of the seam.

## Fix

Rewrote the mapping section to state both branches, which one the CLI reaches, and which seam is
host-scoped in each branch.

| Site | Change |
|---|---|
| `docs/agent-cluster-adapters.md:398-411` | a four-row table covering both branches, plus the one-call and two-call cost of each |
| `docs/agent-cluster-adapters.md:427-441` | a host-scope table per branch, and the fact that `runtime info` has no `--local` flag because it is host-scoped by construction |
| `docs/agent-cluster-adapters.md:449-452` | the missing-`runtime`-member case, which `splitRuntimeMember` returns whole as metadata |

The seam contract itself did not change: both branches forward bytes verbatim, and the Cluster still
models neither document. Only the provider mapping table was wrong.

## Verified

- `runtime info` registers no `--local` flag (`cli/cli_topsailai/runtime_cli.py:168-180`), and it
  discovers rows from this host's task directory (`cli/cli_topsailai/runtime_info.py:174-208`), so the
  host-scoped claim is a property of the command rather than of a flag.
- `splitRuntimeMember` returns the document whole as metadata with an empty runtime seam when no
  `runtime` member exists (`providers/topsailai/src/query.go:860-862`), which is the behaviour the
  document now states.
- The eight documentation guard tests that read this file still pass:
  `TestDocumentedAdapterFieldSpelling`, `TestCapabilityRevisionDocumentsDoNotStateTheRemovedBehaviour`,
  `TestCapabilityRevisionDocumentsNameTheProviderSource`,
  `TestCapabilityRevisionSeamIsNotDescribedAsTheOnlyProviderSeam`,
  `TestRemovedControlCatalogIsDocumentedAsHistory`, `TestRemovedControlCatalogHeadingIsNotCurrent`,
  `TestZeroAdapterStartupIsDocumented`, `TestZeroAdapterHealthIsDocumented`.

## Status

Resolved. Documentation only; no code changed.
