---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Issue: Distributed lock review fixes

## Description

Code review of `internal/lock/distributed_lock.go` identified several correctness and operational issues. This issue tracks the implementation of the recommended fixes.

## Affected Files

1. `/TopsailAI/src/topsailai_server/agent_community/internal/lock/distributed_lock.go`
   - Removed the `nats.ErrBucketExists` check in `ensureBucket()`. The constant does not exist in `nats.go@v1.51.0`; `CreateKeyValue()` already handles `ErrStreamNameAlreadyInUse` internally and returns the existing bucket when the configuration matches.
   - Replaced the `nats.ErrKeyMismatch` check in `renew()` with a `nats.JetStreamError` inspection. Revision mismatches from `kv.Update()` surface as a JetStream API error with code `JSErrCodeStreamWrongLastSequence`, which is now detected with `errors.As`.

## Review Findings Addressed

1. Lost-lock detection and notification: `Lost() <-chan struct{}` and `IsHeld() (bool, error)` were already present and signal lock loss on token mismatch, key disappearance, or revision mismatch.
2. `ensureBucket()` TOCTOU race: resolved by relying on the library's internal handling of concurrent bucket creation.
3. Renewal context lifecycle: renewal already uses an independent `context.Background()` context, so caller context cancellation does not stop renewal until `Release()` is called.
4. `Acquire()` sentinel error: `ErrLockHeld` was already returned when `kv.Create()` reports `nats.ErrKeyExists`.
5. Logger import path: verified that `github.com/topsailai/agent-community/pkg/logger` matches the module path declared in `go.mod`.
6. Input validation: `validateLockKeyPart()` already rejects empty values and `.` characters in `lockType` and `resourceID`.
7. `Release()` safety: token verification before deletion and `sync.Once` idempotency were already in place.
8. `renew()` error handling: improved by distinguishing `JSErrCodeStreamWrongLastSequence` from other JetStream errors.

## Verification

- [x] `go build ./internal/lock/...` succeeds.
- [x] `go test ./internal/lock/...` reports no test files (no tests exist for this package).
- [x] `git diff` reviewed for the changed file.

## Status

Done.
