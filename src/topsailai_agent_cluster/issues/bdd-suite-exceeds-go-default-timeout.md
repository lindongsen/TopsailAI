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
