---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# Test runs leave build trees outside the project with no cleanup path

## Trigger

Raised by session `wa-d915ac55365c` in the sibling project `/TopsailAI/src/topsailai`,
which staged a cross-project report at
`/TopsailAI/src/topsailai/.tmp/project.topsailai_agent_cluster.tmp-build-tree-leak.md`
after its own disk-growth issue was closed. That session observed the root filesystem
at 86% with roughly 30 GB under `/tmp`, of which about 25 GB was `TestFeatures*`
directories and about 5 GB was `agent-cluster-test-bin-*` directories.

Every claim in that report was verified against this project's source before this
issue was written. Three of its statements needed correction, and one defect it did
not name was found during verification. Both are recorded below.

## Observed behavior

Two independent families of directories accumulate under the system temporary
directory, and neither has a cleanup path in this project.

| Family | Producer | Created by | Removed by |
|---|---|---|---|
| `TestFeatures*` | `tests/bdd/suite_test.go:49` via `tests/bdd/world.go:95` | `t.TempDir()` | Go, when the test function returns |
| `agent-cluster-test-bin-*` | `tests/harness/sharedbuild.go:49` | `os.MkdirTemp("", ...)` | nothing |

The only `RemoveAll` under `tests/` is `tests/packaging/deb_layout_test.go:85`, which
is unrelated. The only `TestMain` is `tests/packaging/deb_layout_test.go:82`, so
`tests/bdd`, `tests/harness` and `tests/integration` have no process-exit hook at all.

`make test-bdd` was already bounded, because `Makefile:348` passes
`BDD_BUILD_DIR=.tmp/bdd-build` and `Makefile:355` forwards it as
`AGENT_CLUSTER_TEST_BUILD_DIR`. The leak therefore came from two paths that bypass
that bound: a direct `go test ./tests/bdd`, and any run that was killed, timed out or
interrupted before the suite returned.

## Corrections to the staged report

The staged report is accurate about the mechanism and inaccurate about the scale and
the trigger. Recording the corrections here keeps the issue actionable.

**The 30 GB figure is already stale.** The raising session deleted the residue itself
at 15:33–15:34 on 2026-11-18: 109 `agent-cluster-test-bin-*` directories and 162 other
`Test*` directories. Measured immediately after: `/tmp` at 5167 MB, zero
`agent-cluster-test-bin-*` remaining, root filesystem down from 86% to 78%. This issue
is therefore about a mechanism that will regrow, not about a present 30 GB.

**Most of the 25 GB of `TestFeatures*` is history, not current per-run cost.** The
raising session's own data shows the split: directories dated 2026-11-12, 11-13 and
11-14 are 3.5–5.7 GB each, while those dated 11-16 and 11-17 are 147–440 MB. The
boundary is the 2026-11-15 `sharedbuild` change, which replaced one compile per
scenario with one compile per process. The large directories hold the pre-change
accounting of 43 MB × 99 scenarios. Reporting both families as one 30 GB total
overstates the urgency of the current behaviour by roughly an order of magnitude.

**The shared build directory leaks on every run, not only on a crash.** The staged
report repeated an older issue's phrasing that "a crash leaves at most one copy".
`os.MkdirTemp` never removes its directory, and this package has no `TestMain` and no
`defer RemoveAll`, so a normally completed `go test ./tests/bdd` also leaves about
48 MB behind. The 109 directories spread over four days are repeated runs, not
repeated crashes.

## Defect the staged report did not name

`tests/harness/sharedbuild.go` documented the opposite of what it did:

- Line 15 stated the default directory "is removed when the test process exits".
- Lines 28–29 stated it "is removed by the process exit, and a crash leaves at most
  one copy instead of one per scenario".

Both statements were false. Worse, `issues/done/bdd-suite-rebuilds-binaries-per-scenario.md:100`
states the truth for the same directory — that it "relies on the operating system's
temporary-directory cleanup". The code comment and the issue document contradicted
each other, and the comment is the only one a later reader of the code sees. A false
comment is more damaging than a missing cleanup path, because it tells the reader the
problem was already handled.

## Why this matters

The residue is invisible to `du` on the project tree, so it accumulates until the
filesystem fills and then appears as an unrelated write failure. The system cleanup
policy exists — `/usr/lib/tmpfiles.d/tmp.conf:11` carries `q /tmp 1777 root root 10d`
— but the raising session observed 18-day-old directories still present, so it cannot
be relied on.

A killed run is the common case, not an exotic one: `Makefile:343` sets
`BDD_GROUP_TIMEOUT ?= 20m`, and a timeout kills the test process before any deferred
cleanup runs.

## Resolution

Four logical units, all applied.

**`tests/harness/sharedbuild.go`** — the default became the fixed project-local path
`.tmp/test-build` instead of `os.MkdirTemp`. A fixed reused path is bounded by
construction, while deleting after every run would force a rebuild per process. The
cache records whether it created the directory, so a caller-supplied
`AGENT_CLUSTER_TEST_BUILD_DIR` is never removed; without that rule the first BDD group
would delete the cache the next five depend on. Builds are written to
`<path>.tmp-<pid>` and renamed, so concurrent test processes never execute a partial
binary. A binary is reused only when it is newer than every build input, so the fixed
path does not reintroduce a rebuild per process. `CleanupSharedBuildDir` removes only
harness-created directories, and the two false comments were corrected.

**`Makefile`** — `BDD_BUILD_DIR` converged onto the harness default so a direct
`go test` and `make test-bdd` share one location. `TEST_TMP_DIR` was added and passed
as `TMPDIR` to every test target, so `t.TempDir()` roots land inside the project.
`test-clean` removes both directories and refuses to run when either variable is
empty, because `rm -rf $(TEST_TMP_DIR)` with an empty value becomes `rm -rf /`.

**`docs/Environment_Variables.md`** — a "Test-only variables" section documents
`AGENT_CLUSTER_TEST_BUILD_DIR`, `TMPDIR`, `BDD_BUILD_DIR` and `TEST_TMP_DIR`, which
were previously undocumented anywhere.

**`tests/harness/sharedbuild_test.go`** — five tests cover the fixed default, the
override, the ownership rule, the freshness comparison and the build-input probe.
Each was proven to fail when its guard was broken and to pass when restored.

## Verification

`make test-harness` passes. After a run, `.tmp/test-build` holds the shared binaries
and `.tmp/test-tmp` is empty, which is the intended steady state. `make -n test-clean`
and `make -n test-bdd` expand the expected paths. `make test-clean TEST_TMP_DIR=` and
`make test-clean BDD_BUILD_DIR=` both refuse with exit 2.

## Residual risk

A process killed with `SIGKILL` cannot run any cleanup, so `.tmp/test-tmp` can still
hold a partial scenario tree. That residue is now inside the project, visible to `du`
and removable by `make test-clean`, which is the property this issue asked for. A
`SIGKILL`-proof design would need a supervisor outside the test process and is not
proposed here.
