---
maintainer: AI
status: closed
related_files:
  - internal/services/bootstrap.go
  - internal/services/bootstrap_test.go
  - internal/services/bootstrap_file_test.go
  - internal/lock/distributed_lock.go
labels:
  - bug
  - bootstrap
  - distributed-lock
  - multi-node
---

# Bootstrap Distributed Lock Uses Invalid NATS KV Key

## Summary
The bootstrap service attempted to acquire a distributed lock around default account creation using the key `acs:lock:bootstrap:default-accounts`. NATS KV rejects keys containing `:`, so `kv.Create()` returned `nats: invalid key`. The service fell back to a per-process in-memory mutex, which did **not** protect against concurrent bootstrap across multiple ACS nodes. This violated the documented guarantee that default account creation is guarded by a NATS KV distributed lock and only executed by the Service-Leader.

## Impact
- Multiple ACS server instances started against the same database could race during bootstrap.
- Duplicate default admin/manager accounts and API keys could be created or regenerated.
- Existing API key files could be invalidated and overwritten by a second node, causing authentication failures on the first node.
- Cluster/multi-node deployments were unsafe on startup.

## Root Cause
`internal/services/bootstrap.go` hardcoded the lock key with colons:
```go
lockKey := "acs:lock:bootstrap:default-accounts"
```
NATS KV keys may not contain `:`. The project's own `internal/lock/distributed_lock.go` uses the valid dotted format:
```go
lockKeyFormat = "acs.lock.%s.%s"
```

## Fix
- Changed the bootstrap lock key to `acs.lock.bootstrap.default-accounts`.
- Removed the unsafe per-process in-memory lock fallback.
- `acquireLock` now requires a non-nil NATS KV and returns an error when KV is unavailable or lock creation fails for any reason other than `ErrKeyExists`.
- Updated unit tests to verify the lock key format, lock-held skip behavior, and nil-KV failure path.

## Files Changed
- `internal/services/bootstrap.go`
- `internal/services/bootstrap_test.go`
- `internal/services/bootstrap_file_test.go`

## Verification
- `go test ./internal/services/... ./internal/lock/... -count=1` — PASS
- `go test ./... -count=1` — all packages PASS

## References
- `internal/services/bootstrap.go` `Run()` and `acquireLock()`
- `internal/lock/distributed_lock.go` `lockKeyFormat`
- `README.md` "Default Accounts" section
- `ORIGIN.md` "Default Accounts (admin/manager role)"
