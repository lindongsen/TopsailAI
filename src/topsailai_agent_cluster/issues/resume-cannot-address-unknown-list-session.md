---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI/src
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# Resume could not address an unknown session that the list displays

## Trigger

Reported by the human on 2026-11-10, quoted verbatim:

> cli中的resume要支持可以对 unknown 状态的session进行resume，严格一点，可以再加一个判断：有且仅有1个session记录并且状态是unknown

Clarified by the human after a structured question, quoted verbatim:

> 支持list的unknown行，且是provider session_id唯一unknown 时允许 resume

## Symptom

An operator could see a session in `list` and still had no way to resume it.

`resume` resolved its row number only against `state.history`, and refused to act at all when
no history render had happened:

```text
resume requires a history row; run history first
```

## Root cause

The two tables are different provider surfaces, and only one of them contains the sessions that
need resume.

- `history` reads the provider's past session records through `project list_sessions`, capped at
  30 rows with `truncated=true`. It is a bounded historical view.
- `list` reads the current inventory, which reports a session whose liveness the provider could
  not verify as `state=unknown` with `state_reason=liveness_unverified` and an empty generation
  (`docs/agent-cluster-protocol.md`, "Implemented unverified session reporting and admission").

An unverified session is exactly the session resume exists for, and it is frequently absent from
the bounded history view. Verified on the live cluster: `wa-7bb879625589` and `wa-6922e9283de2`
appear in `list` for `ai-dev` with `state=unknown` and `generation=""`, and do not appear in
`history ai-dev` at all.

So the only resume entry point was a table that does not contain the target, while the table that
does contain it was not accepted. The operator's recovery step was unreachable.

## Why the Endpoint was never the blocker

The Endpoint already authorizes this case, so the defect was purely client-side:

- `internal/endpoint/executor.go:111-124` authorizes `agent.resume` on `Live == false`.
- `internal/adapter/topsailai/adapter.go:392` reports `Live = generation != ""`.
- The provider's `session_liveness` returns `idle` for a session whose process is gone, so
  `workspace resume -s` succeeds.

## Fix

`resume` now resolves its row number against whichever table is currently rendered, and accepts a
bare `resume` under a strict uniqueness rule.

| Input | Accepted when | Rejected otherwise with |
|---|---|---|
| `resume <n>` after `history` | the adapter reports the row resumable | the adapter's own reason, unchanged |
| `resume <n>` after `list` | `state == unknown` **and** `generation == ""` | `use cd <n> to enter it` when a generation was reported, or the reported state when it is not unknown |
| `resume` (bare) | exactly one listed session is `unknown` | the candidate row numbers when several are unknown, or a `run list` hint when none is |

The generation check runs before the state check, so a contradictory row (`state=unknown` with a
generation) is told to `cd` rather than told its state is wrong. That row is the only case where
the generation guard is the sole rejecting site, and it has its own regression test.

Live sessions never count toward the bare-resume ambiguity, so a busy fleet does not disable the
shortcut.

After a successful resume both `state.history` and `state.Rows` are cleared, because a resume
changes the inventory and a number from either table can be stale afterwards. The notice names the
command that refreshes the table the operator was actually using.

## Safety

The client-side guard is not the authority. `validateResumeAbsence` re-reads the inventory before
submission, requires the endpoint to be online and the report complete, and rejects any matching
session that now carries a generation. A stale list row therefore cannot resume a session that has
started in the meantime.

## Verification

- `go build ./...` clean.
- `make test-unit-cli` and `make test-unit` pass for every component group.
- Each new guard was deliberately broken and observed to fail, then restored: the generation
  guard, the uniqueness guard and the state guard each have a test that fails only when that guard
  is removed.

## Files

- `internal/tui/interactive_history.go`
- `internal/tui/help.go`
- `internal/tui/interactive_history_test.go`
- `internal/tui/unit_c_batch2_queue_test.go`
- `internal/tui/unit_c_start_parse_test.go`
