---
maintainer: AI
author: DawsonLin
status: open
created: 2026-11-18
---

# An acknowledged receipt is never settled, so it is re-sent forever

## Symptom

The Server persists a receipt and acknowledges it. The Endpoint removes the receipt from its
in-memory pending map but writes no settlement row. The receipt therefore stays
`receipt_recorded` with no `receipt_settlement` row, so `ListRecordedReceipts` keeps returning it
and `resendPendingReceipts` re-sends it on every reconnect, for the lifetime of the Endpoint.

## Evidence

- `internal/endpoint/service.go:587-594` handles `FrameReceiptAck` by deleting the key from
  `s.pendingReceipts` and nothing else. There is no storage call in that branch.
- The rejection path does persist: `settleRejectedReceipt` (`service.go:337-357`) calls
  `s.storage.SettleReceipt(...)` at `:350` before deleting from the map. The acknowledgement path
  has no equivalent, so the two terminal outcomes are handled asymmetrically.
- `internal/server/receipt.go:32-48` `PersistReceiptAndAck` calls `store.ApplyReceipt` and then
  `ack(...)`. The Server therefore only acknowledges after a durable write, so an acknowledgement
  is proof that the Server holds the receipt.
- `src/main/agent-cluster-server/main.go:167-170` sends `FrameReceiptAck` with
  `FrameID: receipt.CommandID`.
- `internal/storage/endpoint/journal.go:138` `ListRecordedReceipts` filters with
  `NOT EXISTS (SELECT 1 FROM receipt_settlement ...)`, so a receipt with no settlement row is
  returned on every call.

## Measured impact on the live Endpoint database

Copied `/opt/agent-cluster/data/endpoint/ac.topsail/endpoint.sqlite` to `/tmp` before querying,
because the live Server database returns `database is locked`.

```text
command_journal rows          580
receipt_settlement rows       561   (all reason=unknown_command)
unsettled receipt_recorded     19
```

All 19 unsettled receipts exist on the Server, and every one of them is stored there as
`phase=receipt_recorded effect_certainty=acknowledged`:

```text
receipt_recorded | acknowledged | 19
```

So the Server persisted and acknowledged all 19, and the Endpoint still has no settlement row for
any of them. The oldest is `1794965830824` and the newest `1794972804552`, a span of about 1.9
hours, which means the defect is accumulating continuously rather than being a historical residue.

The consequence is bounded but permanent: 19 receipts are re-sent on every reconnect, and the count
grows by roughly one per acknowledged command. Unlike the settled rows, these can never become
eligible for the command journal retention added in `0c77f5b9`, because retention deletes only
settled rows.

## Why this is not the same defect as the journal growth

The journal growth issue is about rows that are already settled and therefore dead weight. This
defect is about rows that are **not** settled and therefore still active work: they are re-sent on
every reconnect and they are excluded from retention. Fixing retention does not fix this, and
fixing this does not bound the table.

## Root cause

The acknowledgement branch was written to clear the in-memory pending set, which is what makes the
current connection stop retrying. Persisting the settlement was not part of that change, so the
durable state was never updated. The in-memory clear is correct and necessary; it is simply not
sufficient, because `resendPendingReceipts` rebuilds the pending set from storage on every
reconnect (`service.go:395-414`).

## Required decision

Which settlement reason should an acknowledgement record? `protocol.ReceiptRejection` is the
existing vocabulary and it is named for rejections, so an acknowledgement needs either a new value
in that vocabulary or a separate reason field. The choice affects the stored schema semantics of
`receipt_settlement.reason`, which currently holds only `unknown_command`.

Options:

- **A** — add an `acknowledged` value to the settlement reason vocabulary and persist it on
  `FrameReceiptAck`. Smallest change; makes the reason column describe two different events.
- **B** — add a separate `settled_by` column distinguishing acknowledgement from rejection. Clearer
  semantics, but the downgrade guard pins `command_journal` and `source_cache`, not
  `receipt_settlement`, so a column here is legal.
- **C** — treat acknowledgement as settlement with an empty reason and document that an empty
  reason means acknowledged. Cheapest, but an empty value that means something is the kind of
  implicit contract this project avoids.

## Prevention

The asymmetry between the two terminal outcomes is the defect. A test that drives both
`FrameReceiptAck` and `FrameReceiptRejected` and asserts that **both** leave a settlement row would
have caught it, because the rejection path already satisfies that assertion and the acknowledgement
path does not. Any future terminal outcome must be added to that same table-driven test rather than
handled in its own branch.

## Related

- `issues/endpoint-command-journal-unbounded-growth.md` — retention deletes only settled rows, so
  these 19 rows are permanently ineligible.
- `internal/storage/endpoint/journal.go:158-175` — `SettleReceipt`, the function the acknowledgement
  branch should call.
