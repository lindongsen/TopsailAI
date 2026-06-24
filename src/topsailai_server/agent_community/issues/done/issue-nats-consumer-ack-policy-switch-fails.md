---
maintainer: AI
status: fixed
severity: medium
related_test: CLI-ENV-004
---

# Issue: `ACS_NATS_PENDING_MESSAGE_NO_ACK` Semantics Misaligned with WorkQueue Stream

## Summary

The original implementation treated `ACS_NATS_PENDING_MESSAGE_NO_ACK=true` as a consumer ack-policy switch (`AckExplicit` → `AckNone`). This failed because the pending-messages JetStream stream uses `WorkQueuePolicy`, which requires explicit ack.

After review, the user clarified the intended semantics: keep the NATS producer-consumer model unchanged; the variable should only control whether the **publisher** waits for the JetStream publish ack after delivering a pending message.

## Final Semantics

- **Consumer side**: always uses explicit ack (`AckExplicit`) and the existing reliable-mode logic (ack/nak/in-progress). The env var does NOT affect consumer configuration.
- **Publisher side**:
  - `ACS_NATS_PENDING_MESSAGE_NO_ACK=false` (default): synchronous JetStream publish; the API waits for and checks the publish ack.
  - `ACS_NATS_PENDING_MESSAGE_NO_ACK=true`: asynchronous JetStream publish (`js.PublishAsync`); the API returns success immediately without waiting for the publish ack.

## Changes Made

1. `internal/nats/publisher.go`: added `noAck` field to `Publisher`; pending-message publishes use `PublishAsync` when no-ack is enabled.
2. `internal/nats/client.go`: removed consumer ack-policy switching; consumer always uses `AckExplicit`.
3. `internal/nats/consumer.go`:
   - Removed no-ack special handling in handler; always uses reliable ack/nak/in-progress.
   - Updated `checkAndCreateRunningRecord` to first upgrade an existing `pending` reservation (created by the auto-trigger task) to `running`, then fall back to inserting a new `running` record. This prevents duplicate-key failures when the consumer processes a pending message for which the auto-trigger task has already inserted a pending record.
4. `internal/nats/auto_trigger.go`: creates the pending processing record BEFORE publishing the pending message, so duplicate scans skip in-flight messages and the consumer can claim the reservation atomically.
5. `cmd/server/main.go`: pass `cfg.NATS.PendingMessageNoAck` to `NewPublisher`.
6. Updated unit tests in `internal/nats/publisher_test.go`, `internal/nats/client_test.go`, `internal/nats/consumer_duplicate_test.go`, and removed obsolete `internal/nats/consumer_noack_test.go`.
7. Updated `docs/Environment_Variables.md` and `docs/cases/TestCase_manual_cli_complete.md`.

## Verification

- `make build-server` passes.
- `go test ./internal/nats/...` passes.
- `CLI-ENV-004` should be re-verified by `km1-tester` after code review approval.
