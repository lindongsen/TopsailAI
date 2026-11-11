---
maintainer: AI
author: DawsonLin
---

# CLI info/show cannot read every row that list renders

## Symptom

`list` renders rows that `info` and `show` refuse to read by row number. The operator
sees an item in the table and has no way to inspect it, even though the same item is
readable when addressed by identifier.

Reproduced on 2026-11-11 against the running cluster
(`http://172.18.0.1:53680`, endpoints `ai-dev`, `local-endpoint`, `topsailai-dev`).

`list` rendered 11 rows. Rows 6 and 7 were `unknown` with an empty generation
(unverified sessions). Row 11 was the `no sessions` placeholder for `topsailai-dev`.

```text
workspace> info 6
error: row 6 is unverified: the session record exists but no process holds it, so it cannot be addressed; use resume to resume it

workspace> show 6
error: row 6 is unverified: the session record exists but no process holds it, so it cannot be addressed; use resume to resume it

workspace> show 11
error: row 11 does not identify a session; choose a session row

workspace> info 11
error: row 11 does not identify a session; choose a session row
```

## Why this is a defect

The requirement is that every item `list` renders is readable. A visible row that
cannot be read is a dead end, and the refusal message is actively misleading for a
read-only command: it tells the operator to `resume` a session merely to look at it.

The data is present and readable. The same items succeed by identifier:

```text
$ agent-cluster-cli info 20261111094237
session_id: res_9ee20049f4b3570f60b7d12e999437ad
provider_session_id: 20261111094237
state: unknown
state_reason: liveness_unverified

$ agent-cluster-cli show topsailai-dev
endpoint: topsailai-dev (online)
collection_status: succeeded
```

So the defect is confined to interactive row-number resolution, not to the data, the
protocol or the standalone surface.

## Root cause

`resolveRowSelection` (`internal/tui/row_selection.go:12-37`) is shared by every
command that addresses a live process, and it rejects two row shapes:

- `row_selection.go:24-26` rejects a row with an empty `ClusterSessionID`, which is the
  endpoint placeholder row (`internal/tui/model.go:51,60`).
- `row_selection.go:27-34` rejects a row with an empty `ProviderGeneration`, which is
  the unverified session reported as `unknown` with `state_reason=liveness_unverified`.

`interactiveShow` (`internal/tui/interactive.go:1086`) and `interactiveInfo`
(`internal/tui/interactive_info.go:94` via `resolveInfoTarget`) both resolve a row
number through `resolveSessionToken` → `resolveRowSelection`, so both inherit both
refusals.

The refusals are correct for their original callers. `cd`, `send`, `stop`, `inject` and
`interrupt` address a live process, and an empty generation cannot prove which process
an operation would reach. `info` and `show` are read-only and address persisted report
data, so the same refusal is wrong for them.

## Existing convention that already solves this

`messagesListRow` (`internal/tui/interactive_messages.go:130-152`) deliberately does
not reuse `resolveRowSelection`, and documents the reason: a conversation read
addresses persisted provider data, so a session the provider listed but could not prove
live is still readable, and refusing it would hide exactly the sessions an operator
most wants to inspect.

`info` and `show` are the same class of read, so the fix reuses that convention rather
than inventing a new one.

## Fix direction

Add a read-only row resolver that requires only the identity a read needs, and route
`info` and `show` through it. Keep `resolveRowSelection` unchanged so the live-process
guard cannot be weakened.

- `info <row>` and `show <row>` on an unverified row render the real detail, including
  `state: unknown` and `state_reason: liveness_unverified`.
- `show <row>` on an endpoint placeholder row renders endpoint detail, because `show`
  is documented as `show [endpoint-or-session]` (`internal/tui/help.go:38`) and
  `FindSession` already returns a nil session for an endpoint ID
  (`internal/tui/model.go:101-104`).
- `info <row>` on an endpoint placeholder row keeps refusing, because `info` is
  session-only by contract (`internal/tui/commands_info.go:60-62`), but the message
  must name the remedy: the row is an endpoint, so `show <endpoint-id>` reads it.
- `cd`, `send`, `stop`, `inject` and `interrupt` keep every existing refusal.

## Affected files

- `internal/tui/row_selection.go`
- `internal/tui/interactive.go`
- `internal/tui/interactive_info.go`
- `internal/tui/*_test.go`

## Verification

Unit tests for each acceptance criterion, each observed to fail before the fix, then
`make test-unit-cli` and `make test-unit`, then a live REPL check through tmux for
`info 6`, `show 6`, `show 11`, `info 11`, `cd 6` and `stop 6`.

## Related

- `issues/resume-cannot-address-unknown-list-session.md` established the dual-namespace
  row rule and the unverified-session resume path.
- `docs/agent-cluster-protocol.md`, "Implemented unverified session reporting and
  admission" defines why an empty generation must fail closed for live-process
  operations. That rule is preserved; only read-only commands are widened.

## Resolution

Fixed on 2026-11-11. `info` and `show` now resolve a row number through a read-only resolver
(`resolveReadRowSelection`, `resolveReadSessionToken`, `resolveReadSessionTokenInEndpoint` in
`internal/tui/row_selection.go`), which returns the row as rendered instead of refusing it for an
empty generation or an absent session identity. `resolveRowSelection` is unchanged, so `cd`, `send`,
`stop`, `inject` and `interrupt` keep every existing refusal.

- `show <row>` renders an unverified session's real detail, and falls back to the row's endpoint
  identifier when the row carries no session identity, so the `no sessions` placeholder row renders
  endpoint detail exactly as `show <endpoint-id>` already does.
- `info <row>` renders an unverified session's real detail. A placeholder row is still refused,
  because `info` is a session command, but the refusal now names the endpoint and the command that
  does read it: `row N is endpoint "X", not a session; use show X for endpoint detail`.

Verified live through the interactive REPL: `info 6`, `show 6`, `show 13` and `info 13` behave as
described, while `cd 6` and `stop 6` still refuse the unverified row. `make test-unit-cli` and
`make test-unit` pass. The pre-existing `TestShowRowNumberRejectsPlaceholderRow` asserted the removed
behaviour and was replaced by `TestShowReadsEndpointPlaceholderRow`.

Plan and evidence: `.task/plan_20261111T102500_cli-info-show-full-read-coverage.md`.
