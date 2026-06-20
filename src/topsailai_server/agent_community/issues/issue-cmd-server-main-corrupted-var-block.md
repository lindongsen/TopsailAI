---
status: fixed
related_files:
  - cmd/server/main.go
---

# cmd/server/main.go: corrupted variable declaration block

## Problem

During the server-bootstrap unit-test refactor, the variable declaration block near the top of `runServer` became corrupted: the `var (` keyword and the `disc *discovery.Discovery` field were duplicated, and `sub` was declared with the wrong type (`*nats.Subscription` instead of `*natsgo.Subscription`). This caused `cmd/server/main.go` to fail compilation.

## Impact

- `go build ./cmd/server/...` failed.
- All package-level tests depending on a successful build were blocked.

## Fix

Removed the duplicated lines and restored a single, correct variable declaration block:

```go
var (
    natsClient  *nats.Client
    lockManager *lock.DistributedLock
    publisher   *nats.Publisher
    sub         *natsgo.Subscription
    disc        *discovery.Discovery
)
```

## Verification

- `go build ./cmd/server/...` passes.
- `go test -race -count=1 ./...` passes.
- `go vet ./...` passes.
