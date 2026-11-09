---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI/src
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# Unverified sessions are visible one by one but have no aggregate count

## Trigger

Raised while fixing `issues/endpoint-container-restart-kills-agents-and-hides-records.md`.
That fix stopped dropping a session whose liveness the provider could not verify, so such a
session is now reported as `state=unknown` with `state_reason=liveness_unverified` instead of
disappearing. The remaining question was whether an operator can tell how many sessions lost
liveness verification in one collection.

## Symptom

An operator cannot see the count. The fleet summary line reports `unknown(3)` whether those
three rows are unverified sessions, unavailable adapter data, or a provider that genuinely
reported `unknown`. The per-row distinction exists, but it is not aggregated anywhere.

## Evidence

`statusCounts` (`internal/tui/table.go:309-338`) tallies rows by `row.State` only:

```go
state := row.State
if state == "" {
    state = "unknown"
}
tally[state]++
```

`SessionRow` (`internal/tui/model.go:11-28`) has no `Unverified` field at all. Only
`HistoryViewRow` (`internal/tui/history.go:56-61`) carries one, and that type is used by the
history view, not by the fleet table. `ListRows` (`internal/tui/model.go:57`) copies
`session.State` straight into the row, so an unverified session arrives as `unknown` and is
indistinguishable from every other unknown.

A probe confirmed the merge. Four rows, two of them unverified, produced:

```text
state="running" count=1
state="unknown" count=3
```

The two unverified rows are inside the `unknown(3)` bucket with no separate marker.

`InventoryReport` (`internal/protocol/inventory.go:4-13`) carries `Adapters` and `Sessions`
but no aggregate counter, so the count cannot be recovered from the report either. A grep for
`Unverified` outside tests returns only the `HistoryViewRow` field, the
`StateReasonLivenessUnverified` constant and the one adapter assignment that sets it.

## Why this matters

The defect this replaced was a silent shrink: sessions vanished from the list and nothing said
so. The fix made each session visible, which is the important half. The aggregate half is still
missing, so a collection that loses liveness verification for twenty sessions looks like a
collection that has twenty unknown sessions. An operator scanning the summary line cannot tell
"the provider restarted and every session is now unverified" from "the provider reported twenty
sessions in an unknown state".

This is the same class of problem as the original defect, one level up: the information exists
per row but the summary hides it. A summary that merges two different unknowns is a summary
that cannot be acted on.

## Not a correctness defect

Admission is unaffected. `resolveRowSelection` (`internal/tui/row_selection.go:27-35`) rejects
an unverified row by checking `Generation == ""` together with `State == unknown`, so the
operator still gets the explicit "use resume to resume it" message. The Endpoint still rejects
every operation except resume on an empty generation
(`internal/endpoint/executor.go:133`). Nothing unsafe happens; the gap is observability only.

## Fix

Add an aggregate count rather than a new state, because the state vocabulary is a protocol
contract and `unknown` is the correct standard state for an unverified session.

1. Add `Unverified bool` to `SessionRow` (`internal/tui/model.go`), set from
   `session.StateReason == protocol.StateReasonLivenessUnverified` in `ListRows`, so the fleet
   table can distinguish the two unknowns without changing the state vocabulary.
2. Render the count separately from the state tally in `writeStatusSummary`
   (`internal/tui/table.go`), for example `unknown(3) | unverified(2)`, so the merged bucket
   stays visible while the unverified subset is named. `unverifiedCount` counts the subset and
   the label is omitted entirely when no row is unverified, so a healthy fleet sees no noise.
   **Superseded on 2026-11-09:** the human directed that the status line must not show
   `unverified` at all. See "Superseded by human direction" below.
3. Keep `statusCounts` keyed on `State` alone. Splitting the tally by a second dimension would
   make the summary line ambiguous about which dimension each number counts.

### Deviation from the proposed `InventoryReport` counter

The proposal above added `UnverifiedSessions int` to `InventoryReport`. That field was not
added, deliberately.

The count is fully derivable from `sessions[].state_reason`, which every report already carries.
A stored counter would be a second source of truth for the same fact, and the two can disagree:
a report whose counter says 2 while its session list holds 3 unverified rows is a contract
inconsistency that the Server would have to validate or silently trust. Deriving the count at
the display layer keeps one source of truth and needs no protocol, storage or schema change, so
adding a second adapter still requires no Server change.

The trade-off is that the count is computed per render instead of read from the report. That is
a linear pass over rows the table already iterates, so the cost is negligible at the documented
scale of 100 Endpoints and 20 sessions each.

## Verification

`internal/tui/unverified_summary_test.go` covers three properties:

- The unknown bucket still counts every unknown row, and the unverified subset is named
  separately (`unknown(3) | unverified(2)`).
- The label is absent when no row is unverified.
- The flag comes from `state_reason`, so an unknown state with a different reason is not marked
  unverified.

The tests were proven to fail before the fix by disabling the subset label and the flag
derivation: both assertions failed with the exact merged summary `running(1) | unknown(3)` and
an unmarked row. They pass after restoring the implementation.

`go build ./...` passes, `gofmt -l internal/tui/` is clean, and `go test ./...` passes across
every package.

## Superseded by human direction

On 2026-11-09 the human directed that the status line must not display `unverified` at all. The
instruction, quoted verbatim:

> unverified 不显示出来，状态栏里面不需要它。我是说状态栏不显示，不是说 sessions 不显示。

The scope is the summary line only. Session rows keep rendering, the `unverified` colour key and
the `SessionRow.Unverified` flag stay, and the `info` detail plus the refusal messages still carry
the per-row distinction. Only the aggregate label is gone.

What changed:

- `writeStatusSummary` (`internal/tui/table.go`) no longer appends the subset label, and the
  `unverifiedCount` helper was deleted because nothing else read it.
- `TestStatusSummaryNamesTheUnverifiedSubset` became
  `TestStatusSummaryMergesUnverifiedIntoUnknown`, asserting `unknown(3)` is present and
  `unverified` is absent.
- `TestUnverifiedSummaryLabelIsDim` became `TestUnverifiedSummaryLabelIsAbsent`, asserting no
  `unverified` text while the unknown bucket keeps its dim colour.

The rationale recorded by the human's direction is that the line reports one dimension, the
reported state. A second label on the same line made the numbers ambiguous about which dimension
each one counted, and the per-row distinction was already available on three other surfaces.

Verification: `make test-unit-cli` passes (`internal/client`, `internal/tui`,
`src/main/agent-cluster-cli`). The two tests were proven to fail by temporarily restoring the
label, which produced the exact old output `running(1) | unknown(3) | unverified(2)` and
`unknown(2) | unverified(1)`; the probe was then removed and `gofmt -l internal/tui/` is clean.

## Status

Implemented, then partially superseded. The visibility fix is committed in `922d8be4`. The
aggregate count was implemented and has now been removed from the status line by human direction;
the observability it provided is carried by the table row, the `info` detail and the refusal
message instead.
