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

- `ListRecordedReceipts` (`journal.go:132-151`) scans every recorded receipt on every reconnect,
  so reconnect cost grows with total command history rather than with the number of unsettled
  receipts.
- `resendPendingReceipts` (`internal/endpoint/service.go:309-330`) then re-sends every row it
  returns, so a long-lived Endpoint re-sends an ever-growing set of frames on every reconnect.
- This violates the project rule that data must not grow indefinitely.

## Why it is not fixed by the re-home work

The Endpoint-to-Server re-home work adds a settlement marker so an unsettled receipt can be
retired without deleting the journal row. That bounds the *re-send* set but not the *table*.
Bounding the table needs a retention policy with its own decision about which phases are safe to
delete, and that decision is independent of the re-home work.

## Required decision

Which journal phases may be deleted, and after what age? A `receipt_recorded` row is the only
durable evidence that a command reached the provider, so deleting it silently removes audit
evidence. A retention design must therefore state what replaces that evidence before any row is
removed.

## Related

- `.task/plan_20261116T161500_endpoint-server-rehome.md` adds `receipt_settlement` so the re-send
  set is bounded. It deliberately does not delete journal rows.
