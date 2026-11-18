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

Line numbers below are from the commit that reported the defect (`0ebe1cbc`); the fix moved them.

- `internal/endpoint/service.go:587-594` handled `FrameReceiptAck` by deleting the key from
  `s.pendingReceipts` and nothing else. There was no storage call in that branch.
- The rejection path did persist: `settleRejectedReceipt` (`service.go:337-357`) called
  `s.storage.SettleReceipt(...)` at `:350` before deleting from the map. The acknowledgement path
  had no equivalent, so the two terminal outcomes were handled asymmetrically.
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

## Resolution

Option **B** was chosen: a separate `settled_by` column distinguishes an acknowledgement from a
rejection. `reason` became nullable, because an acknowledgement carries no rejection reason and an
empty string that means something is the implicit contract this schema avoids.

The two terminal outcomes are now symmetric. `settleAcknowledgedReceipt` writes the settlement
before it drops the in-memory entry, exactly as `settleRejectedReceipt` already did, and both are
dispatched through `dispatchBusiness` so a slow settlement cannot block the channel read loop.

### Schema change

`receipt_settlement` gained `settled_by TEXT NOT NULL DEFAULT 'rejection'` and lost the `NOT NULL`
on `reason`. SQLite cannot relax an existing `NOT NULL` in place, so migration
`003_receipt_settlement_origin.sql` rebuilds the table inside one `BEGIN IMMEDIATE` transaction and
classifies every pre-existing row as `rejection`, which is correct: an older binary could only ever
write a rejection.

The `DEFAULT 'rejection'` is a downgrade requirement, not a convenience. An older binary inserts
only `(command_id, reason, settled_at_ms)`; without the default that insert fails against the
migrated table with `NOT NULL constraint failed: receipt_settlement.settled_by`. A test proves the
three-column insert still succeeds.

`SettleAllRecordedReceipts` writes the origin as a literal rather than accepting it as a parameter,
so no caller can record an acknowledgement without evidence that the Server stored anything.

### Live data re-measured

The issue's figures were stale and understated the defect. A copy of
`/opt/agent-cluster/data/endpoint/ac.topsail/endpoint.sqlite` taken on 2026-11-18 shows:

| Measure | Issue | Measured |
|---|---|---|
| `command_journal` rows | 580 | 623 |
| `receipt_settlement` rows | 561 | 561 |
| Unsettled `receipt_recorded` | 19 | 62 |
| Span | 1.9 h | 8.1 h |

The count grew by 43 during the interval, so the leak was still active.

### Behaviour change that the BDD suite exposed

Settling on acknowledgement means the receipt is never re-sent, so the Server never gets the chance
to reject it. The four existing rejection scenarios therefore stopped reaching the rejection path.
That is a real consequence of the fix, not a test artefact: a rejection is only reachable when the
acknowledgement was lost.

The scenarios now use the harness's existing `FaultInjection.DropAck` fault
(`AGENT_CLUSTER_TEST_DROP_ACK=1`), which makes the Server persist the receipt without acknowledging
it. A new scenario, `an acknowledged receipt is settled and never re-sent`, covers the behaviour
this fix introduces.

### Verification

Six deliberate breakages were each confirmed to fail before being restored:

| Breakage | Failure |
|---|---|
| Acknowledgement clears memory only | `a acknowledgement left no settlement row, so the next reconnect re-sends the receipt` |
| `nullableReason` always returns the reason | `reason="" for an acknowledgement, want NULL` |
| Drop `DEFAULT 'rejection'` from `003` | `an older binary's three-column insert failed ... NOT NULL constraint failed: receipt_settlement.settled_by` |
| Keep `reason TEXT NOT NULL` in `003` | `the converted table still refuses a NULL reason` |
| Re-home scenario delivers the acknowledgement | `settlement origin = "acknowledgement", want "rejection"` |
| Acknowledgement does not persist | `no settlement recorded ... within 1m0s` |

`go build ./...` passes; `internal/storage/endpoint`, `internal/endpoint`, `internal/protocol` and
`internal/server` are green; the BDD group `rehome-receipts` passes 5 scenarios and 22 steps;
`gofmt` and `go vet` are clean for every touched package.

## Prevention

The asymmetry between the two terminal outcomes is the defect. A test that drives both
`FrameReceiptAck` and `FrameReceiptRejected` and asserts that **both** leave a settlement row would
have caught it, because the rejection path already satisfies that assertion and the acknowledgement
path does not. Any future terminal outcome must be added to that same table-driven test rather than
handled in its own branch.

## Related

- `issues/endpoint-command-journal-unbounded-growth.md` — retention deletes only settled rows, so
  these rows are permanently ineligible while they stay unsettled.
- `internal/storage/endpoint/journal.go:172-187` — `SettleReceipt`, the function the acknowledgement
  branch should call.
