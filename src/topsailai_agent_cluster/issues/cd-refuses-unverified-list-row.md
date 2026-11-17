---
maintainer: AI
author: DawsonLin
---

# cd refuses an unverified list row and names a remedy that cannot work

## Symptom

`list` renders a row as `unknown`, and `cd` into that row is refused. The operator cannot
reach the session to look at its log, even though the row is visible and the provider can
read the same session's output.

Reproduced on 2026-11-17 against the running cluster (`http://192.168.2.3:53680`, endpoint
`ac.ai-dev`).

`list` rendered two `unknown` rows with an empty generation and
`state_reason: liveness_unverified`:

```text
2  wa-83c784a7ebc8  unknown  generation:   liveness_unverified
3  wa-9451c9fa3832  unknown  generation:   liveness_unverified
```

```text
workspace> cd 2
error: row 2 has no generation; run list again
```

The advice is wrong. `list` again returns the same row with the same empty generation, so
the operator repeats a step that cannot change the outcome.

## Why this is a defect

Two separate problems, and only one of them is about `cd`.

The refusal message names a remedy that cannot work. `run list again` re-reads the same
persisted inventory document, so a row that has no generation keeps having no generation.
The accurate message already exists one function away in the same package
(`internal/tui/navigation.go:621`): the session record exists but no process holds it, so
it cannot be entered, use resume. `cdRowNumber` duplicates the check with different and
misleading text instead of reusing it.

The read path is broken for exactly the rows the operator wants to read. Even if `cd` were
allowed, the automatic tail and `logs` both fail, because the Endpoint requires a
generation for output reads:

```text
workspace> logs ac.ai-dev res_8d0ba9868150ab59fef204dfdcfcc434
error: invalid_target
```

The provider can read that session. Run directly:

```text
topsailai runtime logs -s wa-83c784a7ebc8 -n 5 --json
```

returned 5 real lines from `wa-83c784a7ebc8.4024294.session.stdout`. The data is readable;
only the cluster's generation gate blocks it.

## The trigger is a stale inventory window, not a permanent state

This is the fact that reframes the defect. The two `unknown` rows were not dead sessions.

`topsailai workspace list --json --local` reported both sessions as `running` with
different PIDs (204339 and 204574) and real generations (582515441 and 582517536), while
the cluster still held the old PID 4024294. After
`agent-cluster-cli refresh ac.ai-dev`, both rows became `running` and the `unknown` rows
disappeared entirely (`running(6)`).

So the operator hit a window where the persisted inventory was older than the provider's
truth. The Endpoint collection delay defaults to 5 s
(`src/main/agent-cluster-endpoint/runtime_hooks_default.go:19`), which is short, yet the
window was long enough to matter in practice.

Consequence: the operator's real need is to read a session that is probably alive, during a
window where the cluster cannot prove it. The message must name `refresh`, because that is
the only step that closes the window, and it must name the read path, because reading is
what the operator wanted.

## Root cause

`cdRowNumber` (`internal/tui/navigation.go:290-305`) rejects any row with an empty
`ProviderGeneration`:

```go
return fmt.Errorf("row %d has no generation; run list again", number)
```

The Endpoint refuses the read for the same reason, in two places:

- `Executor.ReadOutput` (`internal/endpoint/executor.go:267-268`) returns `invalid_target`
  when `ProviderGeneration` is empty.
- `Executor.FollowOutput` (`internal/endpoint/executor.go:328-329`) does the same.

## The safety rule that must be preserved

`Executor.Execute` (`internal/endpoint/executor.go:185-192`) rejects every operation except
`agent.resume`, `agent.drive.stop` and `workspace.clean` when the generation is empty. The
comment states the reason: `revalidateGeneration` compares the requested generation with
the observed one, and two empty strings compare equal, so without the guard an unverified
session would pass the comparison and reach the provider as if it were live.

That reasoning is correct for a mutation and must not be weakened. It does not transfer to
a read, and the difference is the whole argument for a fix:

- A generation proves **liveness**: which process an operation would reach.
- A read needs **identity**: which record's output to return.

Identity for a read is already proven without a generation. The Endpoint resolves the
cluster resource ID through `store.LookupResourceID` (`executor.go:270`), and the provider
proves the row by digest over `(session_id, provider_row_key, is_task)` or falls back to
discovery (`providers/topsailai/resolve_digest.go:158-167`). The provider read path never
consults a generation at all (`providers/topsailai/output.go:17-53`).

One trap must be recorded, because it makes the obvious fix wrong. Dropping the guard at
`executor.go:267` alone is not sufficient and is actively unsafe: `ReadOutput` then calls
`revalidateGeneration` at line 283, which compares with `!=` at line 365, so an empty
requested generation compares **equal** to an empty snapshot generation and passes. A read
relaxation must therefore be explicit about skipping the liveness comparison, not merely
tolerant of an empty value.

## Fix direction

Two directions remain, and the choice belongs to the human.

**Direction A (recommended): fix the message and allow reads on an unproven target.**

- Replace the `cdRowNumber` message with the accurate wording that already exists, naming
  `refresh` as the step that closes a stale window and `resume` for a genuinely dead
  session.
- Allow `ReadOutput` and `FollowOutput` to address a target with an empty generation, while
  keeping every mutation gated by `executor.go:185-192` unchanged.
- The relaxation must skip the liveness comparison explicitly rather than let empty compare
  equal to empty, and must keep the mapping lookup and the provider's own row proof as the
  identity authority.
- `cd` itself stays strict, because entering session scope arms a live tail and pins a
  generation for later `send`/`stop`; `autoFollowAfterStart`
  (`internal/tui/interactive_ops.go:871-876`) already documents that arming a tail with an
  empty generation is refused with `generation_required`.

**Direction B: fix only the message.**

- Smallest change, TUI-only, no protocol impact.
- `logs <row>` on an `unknown` row keeps failing with `invalid_target`, so the operator's
  actual need stays unmet during the stale window.

Direction C, allowing `cd` and letting the Endpoint refuse later, is rejected: the operator
would enter a scope where every action fails.

## Existing convention that already solves the read half

`resolveReadRowSelection`, `resolveReadSessionToken` and `resolveReadSessionTokenInEndpoint`
(`internal/tui/row_selection.go:55-108`) return the row as rendered instead of refusing it.
`info`, `show`, `messages` and `clean` use them; `cd`, `send`, `stop`, `inject` and
`interrupt` deliberately keep the strict resolver. That split was established by
`issues/done/cli-info-show-cannot-read-every-list-row.md` and must not be collapsed.

## Affected files

- `internal/tui/navigation.go` — the misleading message at line 305.
- `internal/endpoint/executor.go` — the read guards at lines 267 and 329, and the
  `revalidateGeneration` call at line 283 (Direction A only).
- `internal/tui/row_selection.go` — reference for the read resolver, unchanged.
- Tests: `internal/tui` message assertion, and an Endpoint read test that fails when the
  guard regresses.

## Verification

- `make test-unit-cli` for the message change.
- `make test-unit-endpoint` for the read relaxation, including a negative test that a
  mutation with an empty generation still returns `generation_required`.
- Live: `logs <row>` on an `unknown` row returns content instead of `invalid_target`
  (Direction A), and `send`/`stop` on the same row still refuse.

## Related

- `issues/done/cli-info-show-cannot-read-every-list-row.md` — established the read resolver
  split.
- `issues/resume-cannot-address-unknown-list-session.md` — the resume path for a session
  with no live process.
- `docs/agent-cluster-protocol.md` — the unverified session reporting and admission rule.

## Resolution

Direction A was approved by the human on 2026-11-17: fix the misleading message and relax the read
path, while leaving the mutation gate untouched.

The distinction that decides the fix: a generation proves **liveness**, which is what a mutation needs
in order to know which process it would reach. A read needs **identity**, which record's output to
return. Identity is already proven without a generation, because the resource ID resolves through the
durable mapping and the provider proves the row by digest or refuses an ambiguous or absent match.

Four gates were relaxed or corrected:

- `internal/endpoint/executor.go` `ReadOutput` no longer requires a generation. The liveness
  comparison is **skipped** when the generation is empty rather than merely tolerated, because
  `revalidateGeneration` compares with `!=` and an empty requested generation would compare equal to
  an empty observed one and pass while proving nothing.
- `internal/endpoint/executor.go` `FollowOutput` applies the same relaxation for the same reason.
- `internal/adapter/genericcli/adapter.go` `ReadOutput` passes `requireGeneration=false`, because the
  provider itself tolerates an empty generation for reads; only `execute` validates it.
- `internal/tui/interactive_ops.go` `logs` resolves through the read resolver instead of the strict
  one. This gate was previously unnoticed: `logs 2` was refused in the TUI before the Endpoint was
  ever reached, because a read was using the write resolver.

Two messages were corrected:

- `internal/tui/navigation.go` `cd` now reports that the row is unverified and names `refresh` and
  `resume`. The previous advice, "run list again", could never work, because `list` re-reads the same
  persisted inventory document.
- `internal/tui/row_selection.go` names `refresh` for the same reason.

The mutation gate is deliberately unchanged. `Executor.Execute` still rejects every operation except
`agent.resume`, `agent.drive.stop` and `workspace.clean` when the generation is empty, and `cd` itself
stays strict because entering session scope arms a live tail and pins a generation for a later
`send` or `stop`.

Verification:

- `TestReadOutputAcceptsUnverifiedTarget` and `TestFollowOutputAcceptsUnverifiedTarget` fail when the
  old generation requirement is restored, so they cover the relaxation rather than the fixed code.
- `TestReadOutputStillRequiresResourceID` and `TestFollowOutputRejectsIncompleteTarget` prove the
  identity check was not removed along with the liveness check.
- `TestLogsReadsUnverifiedRow` drives the real REPL and asserts the client sent an empty generation
  for the unverified row; it fails when the strict resolver is restored.
- `TestLiveCommandsStillRefuseUnverifiedRow` proves `cd` and `stop` still refuse the same row.
- `make test-unit`, `make test-integration` and `make test-bdd` all pass.

The underlying trigger is a stale inventory window, not a dead session: the two reported rows were
`running` in the provider with new PIDs while the cluster still held an older document. `refresh` is
therefore the correct first remedy, and the corrected message says so.
