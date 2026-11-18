---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# BDD suite exceeds the Go default test timeout

## Trigger

During the post-commit review of the component environment-variable migration on 2026-11-12,
`make test-bdd` reached Go's default 10-minute package timeout.

## Observed behavior

The suite executed scenarios continuously for 600 seconds and then failed with:

```text
panic: test timed out after 10m0s
running tests:
    TestFeatures (10m0s)
    TestFeatures/accepting_the_offer_sends_the_literal_line (1s)
```

The active scenario had run for only one second. More than 80 preceding scenarios had continued to
pass, so the evidence does not identify that scenario as hung. A previous successful full BDD run for
the environment-variable task took 563.20 seconds, leaving less than 37 seconds below the same
600-second default.

## Impact

A small host-load variation can make an otherwise healthy full BDD run fail near its end. The timeout
then reports whichever scenario happened to start at the package deadline, which can misattribute a
suite-duration problem to an unrelated scenario and discards the remaining scenario results.

## Evidence that the reviewed change works

The real three-process scenario was rerun independently:

```text
go test ./tests/bdd -count=1 -v -run '^TestFeatures$/^real_cluster_reports_inventory_through_the_real_boundary$'
```

It passed in 17.64 seconds. The scenario starts the Server and Endpoint and exercises the CLI through
the real HTTP boundary using `AGENT_CLUSTER_CLI_SERVER_TOKEN`, so the environment-variable migration's
composed path is verified independently of the full-suite duration.

## Required correction

Keep the normal verification command free of an arbitrary debugging timeout, but make the suite fit
reliably within its runner budget. Measure per-feature and per-scenario durations, then split the BDD
registry into bounded independently reported groups or reduce repeated real-cluster startup cost.
Do not simply increase the timeout without first identifying the accumulated cost, because that would
hide continuing growth and still attribute a future package deadline to the wrong scenario.

## Status

Open. This is a pre-existing BDD execution-budget defect discovered during review; it is not caused by
the CLI Server token rename.

## Resolution

Resolved on 2026-11-18 by commit `72e1bc8d`.

### The mechanism, which decides the shape of the fix

Go's `-timeout` is a budget for the whole test binary, not for one `t.Run` subtest. Splitting
`TestFeatures` into subtests would therefore have reproduced the original defect exactly: one long
group would still decide whether every other group reported at all. A group only gets its own budget
and its own report when it runs in its own `go test` process, so the fix is one process per group,
driven by the Makefile.

### Measured cost, before choosing the split

The issue forbids raising the timeout without first identifying the accumulated cost, so every feature
was measured in its own process with `AGENT_CLUSTER_BDD_FEATURES` selecting one feature at a time.
All 26 features exited 0. Total: 352.9s.

```text
130.2s  endpoint_server_rehome_receipts
 96.6s  endpoint_server_rehome_fallback
 15.8s  endpoint_server_rehome_deployment
 11.7s  endpoint_permission_matrix
 10.7s  tui
 10.6s  output_follow
  8.5s  cancellation
  8.2s  endpoint_server_rehome_connection
  7.8s  timeouts
  6.5s  endpoint_access_policy
  4.9s  command_recovery
  4.7s  model_command
  4.6s  messages
  4.4s  endpoint_expiry
  4.2s  endpoint_query_permission_matrix
  3.6s  provider_response
  3.2s  unknown_input_offer
  2.9s  inventory
  2.7s  output_scope
  2.4s  bidirectional_channel
  2.1s  real_boundary
  1.7s  lifecycle
  1.6s  commands
  1.2s  notifications
  1.1s  command_idempotency
  1.1s  capability
```

Two features are 64% of the suite. Keeping them in one group would have reproduced the defect, so the
split follows measured duration rather than topic alone.

### The partition

| Group | Features | Measured |
|---|---|---|
| `rehome-receipts` | 1 | 129.6s |
| `rehome-fallback` | 1 | 95.8s |
| `rehome` | 2 | 23.1s |
| `policy` | 3 | 30.3s |
| `lifecycle` | 6 | 31.6s |
| `surface` | 12 | 52.2s |

The longest group is 129.6s against a 20m per-group ceiling, so the ceiling is a hung-scenario guard
rather than an expected duration.

### A defect in the runner, found only by running it

The first Makefile version used `set -e`, so the first failing group aborted the loop and every later
group never ran. That is precisely the "one failure discards the remaining results" behaviour this
issue exists to remove. Every guard test passed, `make -n` looked correct, and a single-group run
passed; only a two-group run with a deliberately failing first group exposed it.

Observed before the fix, with `BDD_GROUPS="capability policy"`:

```text
=== BDD group: capability ===
FAIL
EXIT=2
```

`policy` never started. After replacing `set -e` with a failure accumulator:

```text
=== BDD group capability: FAIL ===
=== BDD group policy: FAIL ===
=== BDD groups failed: capability policy ===
EXIT=2
```

Both groups reported. This is the same class as the recorded lesson that a green test proves nothing
until it has been seen to fail: the runner's own failure-continuation behaviour had no test.

### Verification

Full grouped run, 6 groups, all PASS, 150 scenarios, total 362.6s, `EXIT=0`:

```text
rehome-receipts   ok  129.621s  PASS
rehome-fallback   ok   95.773s  PASS
rehome            ok   23.113s  PASS
policy            ok   30.332s  PASS
lifecycle         ok   31.586s  PASS
surface           ok   52.171s  PASS
=== all BDD groups passed ===
```

Seven new guards cover the partition, the run order, the default selection, the two-selector conflict,
group resolution, an unregistered feature and an empty entry. Each was proven by deliberate breakage:

| Break | Failure message |
|---|---|
| Drop `inventory` from its group | `1 registered feature(s) belong to no group, so their scenarios never run: [inventory]` |
| Duplicate `inventory` into `surface` | `1 feature(s) belong to more than one group, so they run twice: [inventory in lifecycle+surface]` |
| Remove `surface` from `groupOrder` | `1 group(s) exist but are absent from groupOrder, so the runner never runs them: [surface]` |
| Narrow the default to `featurePaths[:3]` | `default selection returned 3 path(s), want all 26 registered features` |
| Remove the two-selector conflict check | `two selectors were accepted; want an error so the subset is unambiguous` |
| Build a path from an unregistered basename | `an unregistered feature was accepted; want an error so a selector cannot bypass the registry` |

All six were restored and the guards returned green. The committed tree was extracted with
`git archive HEAD src/topsailai_agent_cluster | tar -x --strip-components=2` and verified in isolation:
`go build ./...` clean, guards green.

### A build error the test run could not see

`suite_groups.go` was first written as a non-test file, but it reads `featurePaths`, which is declared
in `suite_test.go`. `go vet ./tests/bdd/` and `go test ./tests/bdd/` both passed because they compile
the test binary, where `suite_test.go` is present; only `go build ./...` failed with
`undefined: featurePaths`. The mechanism is test-only configuration that no production code reads, so
the file was renamed to `suite_groups_test.go` and the guards to `suite_groups_guard_test.go`,
following the project's existing `*_guard_test.go` convention. This is the same class as the recorded
lesson that a check and the behaviour can live in different places, so a passing check certifies
nothing about the other.

### Files changed

| File | Change |
|---|---|
| `tests/bdd/suite_test.go` | `TestFeatures` uses `selectedFeaturePaths()`; 4 comment lines explain the process-per-group requirement |
| `tests/bdd/suite_groups_test.go` | Group definitions, run order, and the two selectors with fail-closed resolution |
| `tests/bdd/suite_groups_guard_test.go` | 7 guards |
| `Makefile` | `BDD_GROUPS`/`BDD_GROUP_TIMEOUT`/`BDD_BUILD_DIR` with `?=`; `test-bdd` runs one `go test` per group and continues after a failure |

`BDD_BUILD_DIR` reuses the existing `AGENT_CLUSTER_TEST_BUILD_DIR` seam
(`tests/harness/sharedbuild.go:16`) so the Server, Endpoint and provider fixture are built once
instead of once per group.
