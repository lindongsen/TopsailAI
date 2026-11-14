---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# BDD suite rebuilds three binaries per scenario and fills /tmp

## Trigger

Observed while running `make test-bdd` during the degraded-endpoint lifecycle work on
2026-11-14. An earlier run had already filled the root filesystem to 100% with 24 GB of
`/tmp/TestFeatures*` directories, which had to be deleted by hand.

## Observed behavior

Sampling `/tmp` every 10 seconds during a full suite run:

```text
t=10s   dirs=18   size=170M    free=18120M
t=60s   dirs=46   size=1035M   free=17255M
t=120s  dirs=88   size=2531M   free=15759M
t=200s  dirs=142  size=4242M   free=14047M
t=310s  dirs=223  size=5960M   free=12330M   <- peak
t=320s  dirs=0    size=—       free=18305M   <- suite returned, directory removed
```

Peak usage is about 5.8 GB for a 319-second run. The suite itself passes
(`ok topsailai_agent_cluster/tests/bdd 319.038s`).

## Root cause

Three separate decisions combine into the growth:

1. `tests/bdd/suite_test.go:41` assigns `activeTest = t`, the top-level `*testing.T` of
   `TestFeatures`, not a per-scenario subtest. godog is configured with `TestingT: t`
   (`suite_test.go:44`), so every scenario shares that one `*testing.T`.
2. `tests/bdd/world.go:63` and `tests/harness/cluster.go:198` both call `t.TempDir()` on
   that shared `t`. Go therefore creates a single `/tmp/TestFeatures<random>/` and removes
   it only when `TestFeatures` returns.
3. `tests/harness/cluster.go:204-212` builds three binaries per real-cluster scenario via
   `harness.Build` (`tests/harness/process.go:65-73`, `go build -tags=testhooks`):
   server 16.7 MB + endpoint 24.5 MB + fixture 3.0 MB = 43 MB per scenario.

99 of 128 scenarios use `Given a real cluster` (15 `StartRealCluster` call sites), so the
binaries alone account for roughly 99 x 43 MB = 4.3 GB. Certificates, SQLite databases,
records and logs make up the remainder.

## Impact

- Peak usage scales with scenario count and is unbounded by design.
- The space is held for the whole suite duration, which has been observed at 955 seconds.
- A crash, `SIGKILL`, or a `go test` timeout before `TestFeatures` returns leaves the
  directory behind permanently. This is exactly how the earlier 24 GB incident filled the
  root filesystem to 100%.
- Running the suite on a machine with a small `/tmp` fails for reasons unrelated to the
  code under test.

## Resolution

Fixed on 2026-11-15 by building each binary once per test process instead of once per
scenario.

- `tests/harness/sharedbuild.go` adds a process-scoped build cache. `SharedBinary(name,
  packagePath)` compiles a package on first use and returns the cached path afterwards;
  `sharedBuildDir()` creates one directory lazily under the system temporary directory, or
  honours `AGENT_CLUSTER_TEST_BUILD_DIR` when a caller needs a specific volume.
- `tests/harness/cluster.go` obtains the Server, the Endpoint, the provider fixture and the
  CLI from `SharedBinary`. The TopsailAI adapter still resolves
  `topsailai_session_info` as a sibling, because both fixtures land in the same shared
  directory; `providerDir` is now derived from `filepath.Dir(sessionInfo)`.
- Certificates, SQLite databases, records and logs stay in each scenario's `t.TempDir()`.
  Only the immutable build output moved out.

The cache is process-scoped rather than test-scoped on purpose: a scenario's `t.TempDir()`
is removed when that scenario ends, so a binary stored there cannot be reused. A crash now
leaves at most one copy instead of one per scenario.

Verification:

```text
go build ./...              BUILD_EXIT=0
go vet ./tests/harness/     VET_EXIT=0
gofmt                       clean on both changed files

138 scenarios (138 passed)
551 steps (551 passed)
ok  topsailai_agent_cluster/tests/bdd  55.814s
```

Runtime fell from 319s to 55.8s, consistent with removing 99 redundant compilations. The
scenario and step counts are unchanged, so the speedup is not a silently skipped scenario.

## Remaining limitation

The shared build directory is not removed at process exit; it relies on the operating
system's temporary-directory cleanup. A crash leaves one copy behind. This is the intended
trade-off against one copy per scenario, but it is not yet documented in
`docs/Environment_Variables.md`, which also does not list `AGENT_CLUSTER_TEST_BUILD_DIR`.
