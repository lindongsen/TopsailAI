---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# `TestSyncerRetriesSSEConnectFailure` fails intermittently under load

## Symptom

`make test-unit` and `make test-unit-cli` fail intermittently with:

```text
--- FAIL: TestSyncerRetriesSSEConnectFailure (0.02s)
    sync_test.go:136: SSE attempts=0 resyncs=0, want retry and resync
```

The same test passes in isolation, passes 5 consecutive runs with `-count=1`, and passes when
`internal/client` is run alone. It failed twice in a row during a full `make test-unit` run while
other packages were compiling and running, and passed on the immediate retry of
`make test-unit-cli`.

## Root cause

The test bounds its own lifetime with a wall-clock sleep rather than with an observable event:

```go
go func() {
    time.Sleep(20 * time.Millisecond)
    cancel()
}()
err := s.Run(ctx, func(Manifest) error { resyncs.Add(1); return nil })
```

`Run` must complete a manifest fetch, observe a `502` from the SSE endpoint, honour the injected
no-op `sleep`, and start a second SSE attempt — all inside 20 ms. On a loaded machine the context is
cancelled before the first SSE attempt is even issued, so `events.Load()` is `0` and the assertion
reports `attempts=0 resyncs=0`. The failure message names the retry behaviour, but the actual cause is
that the deadline expired before the behaviour could start.

## Why it was not caught earlier

The test is green on an idle machine, and the failure only appears when the package runs alongside
other packages. A single-package run is the normal way to investigate a failure, and that run passes,
so the natural conclusion is "flaky, ignore". The `0.02s` duration in the failure line is the tell: the
test finished in the time it was supposed to spend waiting.

## Impact

Low. It is a test-only defect: the production retry path is exercised by the passing runs, and no
product behaviour depends on the 20 ms budget. The cost is a red `make test-unit` that has to be
re-run to distinguish a real regression from this flake, which is exactly the situation where a real
regression gets dismissed.

## Suggested fix

Replace the wall-clock cancel with an observable condition. Cancel from inside the handler once the
second SSE attempt has been observed, or poll `events.Load() >= 2` with a bounded deadline before
cancelling. Either form makes the test wait for the behaviour it asserts instead of racing it.

## Status

Resolved. Both retry tests now cancel only after the retry they assert has been observed, and the
sibling `TestSyncerRetriesManifestOnConnectionRefused` was fixed in the same change because it carried
the identical wall-clock pattern and would have failed the same way.

Reproduced before the fix: 50 runs under concurrent `go build` load failed with
`SSE attempts=0 resyncs=0`, while 50 idle runs passed. After the fix, 50 idle runs and 50 loaded runs
both passed.

Teeth verified by breaking the production path twice: removing the SSE retry loop made
`TestSyncerRetriesSSEConnectFailure` fail, and removing the manifest retry made
`TestSyncerRetriesManifestOnConnectionRefused` fail. Both were restored and the package re-ran green.
