---
maintainer: AI
author: DawsonLin
status: done
severity: medium
created: 2026-11-17
platform: all
---

# `make check` never runs the race detector

## Symptom

`make check` ran vet, the unit suite, coverage, integration, BDD, e2e and the
Windows cross-compile, and none of those stages used `-race`. A search of the
whole repository found no occurrence of the flag:

```
$ grep -rn "\-race" Makefile tests/ | wc -l
0
```

The suite was therefore green on a codebase that contains real concurrency, and
green meant only "no race was observed by a build that cannot observe one".

## Impact

The project has concurrency that an ordinary run cannot check:

- `internal/server/registry.go` keeps the routing table `node_id -> connection`
  behind a mutex, and the same table is read on the request path and written on
  connect, disconnect and replacement.
- `internal/server/channel.go` and `listener.go` move frames between a reader
  goroutine, a writer goroutine and the request path.
- `internal/node/identity_holder.go` and `identity_watch.go` publish a
  regenerated identity from a polling goroutine to every request handler.

A defect in any of those is a data race, and a data race is invisible without
instrumentation: the program may pass every test for months and then corrupt the
registry under load. The verification gap is therefore not "a test is missing" but
"the whole class of defect is unobservable".

## Root cause

The Makefile was written when the suites were small and the concurrency did not
exist yet. Every test target was added as `go test -count=1 -tags ...`, and no
target was ever revisited when the Server gained a registry and the Node gained an
identity watcher. The omission is a design omission rather than a typo: nothing in
the file states which classes of defect the suite is responsible for, so a new
class of defect had no place to be added.

## Detection failure

The gap survived because every signal available said the suite was complete:

- `make check` was green, and a green run reads as "verified".
- The coverage number was 89.9%, which reads as thorough.
- The e2e scripts drive real processes and real sockets, which reads as
  "concurrency is covered".

None of those three can see a race. Coverage measures which lines ran, not whether
two goroutines touched one word; e2e drives concurrency but observes only the
answers, and a racy registry returns correct answers until it does not.

## Fix

A dedicated `test-race` target runs the unit suite and the integration suite under
`-race`, and `check` depends on it:

```make
test-race:
	@mkdir -p $(TMP_DIR)
	go test -count=1 -race -tags '$(UNIT_TAGS)' ./... 2>&1 | tee $(TMP_DIR)/race-unit.log
	go test -count=1 -race -tags '$(INTEGRATION_TAGS)' ./tests/integration/... 2>&1 | tee $(TMP_DIR)/race-integration.log

check: vet test-unit coverage test-race integration bdd e2e build-windows test-windows-compile
```

It is a separate target rather than a flag on `test-unit` for three reasons:

- `-race` needs cgo and roughly doubles the run time, so an ordinary
  `make test-unit` stays fast.
- `coverage` must not be instrumented, because the race runtime changes the
  profile and the reported percentage would stop being comparable with the
  previous runs.
- A separate target names the class of defect it covers, so the next person who
  adds a suite has a place to put it.

The integration suite is included because it is the only suite that drives the
listener and the dialer at the same time. It builds its own Node binary into a
temporary directory, so `test-race` needs no `build` dependency and cannot
overwrite a binary an operator is using.

## Verification

The detector is genuinely active, proven rather than assumed:

```
$ go test -race -c -o probe.test ./internal/security/
$ go tool nm probe.test | grep -c "racefuncenter\|__tsan"
313
$ go test -c -o probe-norace.test ./internal/security/
$ go tool nm probe-norace.test | grep -c "racefuncenter\|__tsan"
0
```

The detector genuinely catches a race on this host, proven with a throwaway module
under `.tmp/` that increments a shared counter from two goroutines without a lock:

```
$ go test -race -count=1 ./...
rc=1
DATA RACE count: 1
```

The project itself is clean under the detector:

```
$ make test-race
rc=0
DATA RACE count in race-unit.log:        0
DATA RACE count in race-integration.log: 0
```

The full pipeline still passes with the new dependency:

```
$ make check
rc=0
```

## Known limitation

The Node process that the integration suite spawns is built without `-race`, so
only the in-process Server and Node code is instrumented. A race inside the
spawned binary would still be missed. Closing that gap would mean building the
spawned binary with `-race` as well, which is a change to the test harness rather
than to this target, and it is not done here.

`-race` requires a C toolchain. A host without one cannot run this target at all.
That is stated in the target's comment rather than handled by skipping the stage,
because a silently skipped race check restores exactly the blind spot this change
closes.
