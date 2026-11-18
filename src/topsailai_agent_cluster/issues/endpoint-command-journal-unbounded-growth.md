---
maintainer: AI
author: DawsonLin
status: open
created: 2026-11-16
---

# Endpoint command journal grows without bound

## Symptom

`command_journal` in the Endpoint SQLite database only ever gains rows. No code path deletes
or prunes them, so the table grows for the whole lifetime of the Endpoint process.

## Evidence

- `internal/storage/endpoint/internal/migrations/001_initial.sql:1-9` declares the table with
  seven columns and no retention column.
- `internal/storage/endpoint/journal.go` exposes `AdmitJournal`, `MarkInvocationStarted`,
  `MarkEndpointAdmitted`, `RecordReceipt`, `GetJournal`, `ListAcceptedCommands` and
  `ListRecordedReceipts`. None of them deletes a row.
- A repository-wide search for `DELETE FROM command_journal` and for any prune routine returns
  nothing.
- `CommandRetention` (`internal/config/config.go:41-45`) is a Server-side setting. The Endpoint
  never reads it, so the Server's retention policy cannot bound this table.

## Impact

- **Disk growth is the only remaining defect.** Measured on the live Endpoint database
  (`/opt/agent-cluster/data/endpoint/ac.topsail/endpoint.sqlite`, 1.4 MB) on 2026-11-18: 565 rows,
  all `receipt_recorded`, spanning 5.84 days. Average row 1532 bytes (intent 317,768 + receipt
  546,364 = 864,132 bytes total). Daily counts 62, 61, 151, 97, 34, 137, 22, so roughly 86 rows and
  130 KB per day, about 31k rows and 30 MB per year.
- **The reconnect cost claim in the original version of this section was wrong.** It stated that
  `ListRecordedReceipts` scans every recorded receipt so reconnect cost grows with total history.
  `journal.go:138` filters with `NOT EXISTS (SELECT 1 FROM receipt_settlement ...)`, so the query
  returns only unsettled receipts: **4 rows out of 565**, not 565. `resendPendingReceipts`
  (`internal/endpoint/service.go:395-414`) sends exactly what that query returns, so the re-send set
  is already bounded by settlement and does not grow with history. Only the table itself grows.
- This still violates the project rule that data must not grow indefinitely, but the harm is disk
  consumption and a slower full-table scan, not an ever-growing reconnect burst.

## Why it is not fixed by the re-home work

The Endpoint-to-Server re-home work adds a settlement marker so an unsettled receipt can be
retired without deleting the journal row. That bounds the *re-send* set but not the *table*.
Bounding the table needs a retention policy with its own decision about which phases are safe to
delete, and that decision is independent of the re-home work.

## Structural constraint: a retention column is forbidden

`internal/storage/endpoint/downgrade_boundary_guard_test.go:209-228`
(`TestSharedTablesAreIdenticalAcrossVersions`) pins `command_journal` and `source_cache` to
identical column lists across schema versions. Adding a retention column to `command_journal`
therefore fails that guard, and the migration file states the same reason in a comment on
`receipt_settlement`: it is a separate table rather than a column precisely because an older
binary must keep writing `command_journal` unchanged.

Any retention design must therefore delete rows or use a separate table. It must not add a column.

## Two further defects found while analysing this issue

- **`ExecuteBeforeAtMS` is not validated as non-zero.** `internal/endpoint/executor.go:119` guards
  with `if intent.ExecuteBeforeAtMS > 0 && e.now().UnixMilli() > intent.ExecuteBeforeAtMS`, so a
  zero value skips the expiry check entirely and an already-expired command would still execute.
  This is independent of retention: it is an admission defect, and it needs its own issue. It is
  recorded here only because the retention analysis is what surfaced it.
- **`FrameReceiptAck` never persists its settlement.** `internal/endpoint/service.go:561-568`
  deletes only from the in-memory `pendingReceipts` map. An acknowledged receipt therefore stays
  `receipt_recorded` with no `receipt_settlement` row, so it is re-sent on every reconnect and is
  never eligible for retention. This is a distinct defect from table growth and needs its own
  issue.

## Required decision

Which journal phases may be deleted, and after what age? A `receipt_recorded` row is the only
durable evidence that a command reached the provider, so deleting it silently removes audit
evidence. A retention design must therefore state what replaces that evidence before any row is
removed.

Three options were presented on 2026-11-18 and none is approved yet:

- **A** — time-window deletion following the existing `cache_expiry.go` pattern. Delete
  `receipt_recorded` rows that are settled and older than the cutoff, deleting their
  `receipt_settlement` rows in the same transaction. Never delete `accepted`,
  `invocation_started`, `endpoint_admitted`, or unsettled receipts. New variable
  `AGENT_CLUSTER_ENDPOINT_COMMAND_JOURNAL_EXPIRY`, default `720h`, mounted beside
  `expireSourceCache` (`internal/endpoint/collector.go:109-120`).
- **B** — compress deleted rows into a bounded evidence table before removing them.
- **C** — do not fix; document the growth and its measured rate as accepted behaviour.

### Why option A cannot select `accepted` rows by expiry

The first sketch of option A proposed deleting `accepted` rows whose `execute_before_at_ms` had
passed. That predicate is not expressible: `command_journal` has seven columns and
`execute_before_at_ms` is not one of them. The deadline lives only inside `intent_json`, and the
Endpoint storage layer uses no SQLite JSON functions anywhere, so reading it would require parsing
JSON in Go for every candidate row.

Option A therefore deletes only settled `receipt_recorded` rows. An `accepted` row is left in place
because it is the only record that a command was admitted but never executed, which is exactly the
evidence an operator needs when reconciling an interrupted command. `accepted` rows are also rare:
the live database contains none, because every admitted command reached `receipt_recorded`.

## Related

- `.task/plan_20261116T161500_endpoint-server-rehome.md` adds `receipt_settlement` so the re-send
  set is bounded. It deliberately does not delete journal rows.
