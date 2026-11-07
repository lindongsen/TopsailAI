---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectCode: agent-cluster
programming_language: go
---

# TUI status wording scenario asserts a mid-lifecycle state

## Symptom

`go test ./... -count=1` fails in `tests/bdd` while every other package passes:

```text
--- Failed steps:

  Scenario: TUI status wording preserves lifecycle evidence # ../../features/tui.feature:24
    And the output contains "request delivered" # ../../features/tui.feature:28
      Error: human TUI output "endpoint received\n" does not contain "request delivered"

59 scenarios (58 passed, 1 failed)
--- FAIL: TestFeatures (249.50s)
```

The same suite passes when run alone: `go test ./tests/bdd -count=1` -> exit 0,
`ok ... 301.939s`.

## Reproduction

1. `go test ./... -count=1` from the project root.
2. Observe the failure above.
3. `go test ./tests/bdd -count=1` alone -> passes.

## Location

- Scenario: `features/tui.feature:24` (`TUI status wording preserves lifecycle evidence`).
- Step: `tests/bdd/steps_tui.go:167` (`evaluateTUIStatusWording`).
- Assertion: `tests/bdd/steps_u20.go:19` (`assertHumanTUIWording`).
- Wording mapper: `internal/tui/model.go:108-116`.

## Suspected cause

`evaluateTUIStatusWording` submits a real command and then immediately runs
`agent-cluster-cli status <id>`. The assertion then requires the exact wording of
one specific lifecycle stage, `request delivered`, which is
`protocol.StatusDispatched` (`internal/tui/model.go:113`).

The command keeps advancing while the status read happens, so a faster run
legitimately observes a later stage. The observed value in the failure,
`endpoint received`, is `protocol.StatusEndpointAdmitted`
(`internal/tui/model.go:115`), which is strictly later than `dispatched`. The
scenario therefore asserts a transient stage rather than a durable property, and
under full-parallel load the timing shifts enough to skip it.

This is a test defect, not a wording regression: `internal/tui/model.go` and
`features/tui.feature` are both clean at HEAD, and the mapper still returns
`request delivered` for `StatusDispatched`.

## Suggested fix

Assert the durable property instead of one transient stage. Accept any stage at or
after dispatch, or assert that the wording is one of the known lifecycle strings
and that `submitted` is never rendered as ready. The existing
`Scenario Outline: tui renders each command state with distinct wording`
(`features/tui.feature:38-50`) already pins each individual wording against a
controlled state, so this scenario does not need to re-pin one exact stage from a
live race.

## Impact

Intermittent full-suite failure only. No product behaviour is affected, and the
drive command work is unrelated: the first failing run contains no drive-related
failure, and the owned packages pass in both runs.

## Resolution

Fixed in commit `87cdb53b` (`test: assert a durable lifecycle stage in tui status
scenario`).

- `features/tui.feature:28` now reads `And the output shows a recognized lifecycle
  stage` instead of pinning `request delivered`.
- `tests/bdd/steps_tui.go` registers and implements
  `assertRecognizedLifecycleStage`. It inspects only the first output line, the
  status label, and requires an exact match against the full `StatusLabel`
  vocabulary: `server received`, `request delivered`, `endpoint received`,
  `executing`, `effect unknown`, `confirmed result`, `failed`, `delivery
  unconfirmed, effect unknown`, plus the raw fall-through spellings `expired` and
  `cancelled_before_execution`.
- Matching the whole body was rejected because `renderReceiptDetails`
  (`internal/tui/command_actions.go:104`) prints `outcome: failed` and similar
  fields, so a substring match over the body would pass vacuously even when the
  label were unrecognized. Anchoring to the label line keeps the assertion
  meaningful.
- The `Scenario Outline: tui renders each command state with distinct wording`
  still pins every individual wording deterministically, so no per-stage coverage
  was lost.

Verification: `gofmt -l` clean, `go vet ./tests/bdd/` clean, and
`go test ./tests/bdd -count=1 -v -run TestFeatures` -> `59 scenarios (59 passed)`,
`225 steps (225 passed)`, with
`--- PASS: TestFeatures/TUI_status_wording_preserves_lifecycle_evidence (10.30s)`.
`go test ./internal/tui -count=1` -> `ok ... 119.375s`.

Note: several intermediate runs failed with `build ./src/main/agent-cluster-cli:
exit status 1` caused by a concurrent agent's in-progress edits to
`internal/tui` (`executor.go`, `interactive.go`, `command_completion.go`,
`help.go`, `watch.go`). Those failures never mentioned this step, and the suite
passed once the tree compiled again.
