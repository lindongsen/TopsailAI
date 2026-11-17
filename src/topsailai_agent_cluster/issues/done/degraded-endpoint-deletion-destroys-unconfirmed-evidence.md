---
maintainer: AI
author: DawsonLin
status: resolved
created: 2026-11-14
resolved: 2026-11-17
---

# Degraded endpoint deletion destroys unconfirmed command evidence

## Human decision

Directed by the human on 2026-11-17, wording normalized, meaning preserved:

> 机器到期清理时 `unconfirmed` 一起删、不留痕，这是对的，符合预期的。删除的时候，要打印日志。

This selects **Option C** and adds one requirement: the deletion must be logged.

The cascade removing `unconfirmed` rows is **intended behaviour, not a defect**. An endpoint record
cannot outlive its own retention window, so the lifecycle decision outranks command-evidence
retention. The safety property is preserved by making the deletion observable rather than by
refusing it.

## What was wrong

The behaviour was correct; the **record** was not. Three things were wrong and all three are fixed:

1. The cascade logged only `command_id` and `degraded_retention`. An operator could not tell which
   machine lost the row, what status it held, or whether the lost row was the only evidence of an
   unknown effect. The deletion was therefore silent in the way that mattered.
2. `PurgeExpiredCommands`'s comment promised `unconfirmed` survives, without scoping that promise to
   age-based purge. Read literally, the cascade contradicted it.
3. `docs/agent-cluster-database.md` described one retention policy where two exist.

## Correction: the foreign-key claim in the original report was wrong

The original report claimed that with `PRAGMA foreign_keys = ON` the endpoint delete would be
`BLOCKED -> FOREIGN KEY constraint failed`, and that Option B would therefore need a table rebuild.

That is false. `ExpireDegradedEndpoints` deletes children **before** the parent
(`internal/storage/server/endpoints.go:205-217`): `commands`, then `endpoint_session_state`, then
`endpoints`. Foreign-key enforcement is satisfied by that order, so the cascade succeeds with
enforcement on.

Reproduced on 2026-11-17 against the real schema shape:

```text
fk=1
--- production order: commands, inventory, endpoints ---
RESULT: cascade succeeded with foreign_keys=ON
remaining endpoints=0 commands=0
```

The `BLOCKED` result is reproducible only by deleting the parent first, which production never does:

```text
--- reverse order: endpoints first (NOT what production does) ---
Error: near line 7: FOREIGN KEY constraint failed
```

Consequence: this issue is **not** coupled to `server-sqlite-foreign-keys-not-in-dsn.md`. Enabling
foreign-key enforcement does not break endpoint expiry, and no table rebuild is needed.

## Correction: the measured data in the original report is stale

The original report measured 17 `unconfirmed` rows on degraded endpoints, due for destruction on
2026-12-14 19:02:38. Those rows no longer exist. Checked on 2026-11-17 against a read-only copy of
the live database:

```text
commands by status: finished | 8
unconfirmed count: 0
sample IDs from the report: all absent
all surviving commands created: 2026-11-17
database directory mtime: 2026-11-17 12:51 (rebuilt)
39 "retention sweep complete" lines: deleted_commands=0 in every one
```

The rows were not destroyed by the cascade: the sweep log proves the cascade never ran in the
current container's lifetime. They disappeared when the database was rebuilt on 2026-11-17 12:51.
No direct record of that rebuild was found, so this is the most likely explanation rather than a
proven one.

The urgency argument in the original report therefore no longer applies. The code defect it
described was real and is now resolved.

## Why the state keeps recurring

`unconfirmed` is not legacy residue. `ReconcileExpiredCommands`
(`internal/storage/server/commands.go:121`) runs first in every sweep and rewrites any command past
its deadline that was never confirmed into `unconfirmed`. Any command that times out unconfirmed
therefore enters the state continuously, so the cascade will keep encountering such rows.

## Resolution

**Storage layer** — `internal/storage/server/endpoints.go`

`EndpointExpiryResult.DeletedCommandIDs []string` became `DeletedCommands []DeletedCommand`, where
`DeletedCommand` carries `CommandID`, `EndpointID`, `Status` and `EffectCertainty`. The cascade SQL
now returns those four columns, and `queryDeletedCommands` scans them. A bare ID was not enough: it
does not say which machine lost the row, nor whether the lost row was the only evidence of an
unknown effect.

**Log layer** — `src/main/agent-cluster-server/expiry.go`

Every removed command is logged individually at Info with `command_id`, `endpoint_id`, `status`,
`effect_certainty` and `degraded_retention`. The sweep completion line reports the total as
`deleted_commands`.

**Contract** — `internal/storage/server/commands.go`

The `unconfirmed` guarantee is now explicitly scoped to age-based purge, with endpoint expiry named
as the documented exception and the logging requirement stated at the site that implements it.

**Documentation** — `docs/agent-cluster-database.md`

The retention section now states two policies with two owners, records that endpoint lifecycle takes
precedence, and documents the per-row log fields.

**BDD** — `features/endpoint_expiry.feature`

The scenario was renamed from `deleting a degraded endpoint removes its command evidence` to
`endpoint expiry removes command evidence including an unconfirmed row`, and a comment block now
states that this is intended behaviour and that observability is what preserves the safety property.
The old name implied a general guarantee that does not exist.

## Verification

| Check | Result |
|---|---|
| `go build ./...` | clean |
| `go vet ./src/main/agent-cluster-server/ ./internal/storage/server/` | clean |
| `go test ./src/main/agent-cluster-server/ -run TestExpireEndpointRecords` | PASS |
| `go test ./internal/storage/server/` | `ok 1.390s` |
| Deliberate break: remove `status`/`effect_certainty` from the log | FAIL as expected: `audit field "status=unconfirmed" missing` |
| Deliberate break: return a literal `'unknown'` for `effect_certainty` | FAIL as expected: `EffectCertainty:unknown, want ...` |
| Both restored | PASS again |

Both deliberate breaks were observed to fail before the fix was accepted, so the tests are proven to
distinguish the two behaviours rather than merely passing.

## Deferred

The BDD layer does not yet assert the log line. The harness wires the Server's stdout and stderr to
the test process's streams, so a scenario cannot read them; asserting the log needs a Server log file
option in `tests/harness/cluster.go` and `tests/harness/process.go`, mirroring the existing
`SecondaryLogPath` and `EndpointLogPath` seams. Those two files carry an unrelated in-flight change
from another agent's rehome-fallback work, so the seam was not added here. The unit tests cover the
log content in the meantime.

## Related

- `server-sqlite-foreign-keys-not-in-dsn.md` — independent of this issue; the FK claim above is
  corrected, and enabling enforcement does not break endpoint expiry.
- `endpoint-command-journal-unbounded-growth.md` — the Endpoint-side journal has no deletion path at
  all, which is a separate gap.
