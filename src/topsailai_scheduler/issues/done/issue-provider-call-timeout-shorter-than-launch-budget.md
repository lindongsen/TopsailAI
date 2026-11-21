---
maintainer: AI
author: DawsonLin
status: resolved
severity: medium
created: 2026-11-21
resolved: 2026-11-22
---

# The scheduler's default call timeout is shorter than the provider's launch budget

## Symptom

With default settings, a provider call was abandoned after 30 seconds, but the
provider itself waits up to 120 seconds before giving up. The scheduler therefore
reported its own timeout and the provider's real diagnosis was never seen.

Observed with the old defaults:

```text
start did not answer within 30s
```

Observed with `SCHEDULER_PROVIDER_CALL_TIMEOUT=180s`, which let the provider
finish and report the actual cause:

```text
start run: provider "..." start exited 1: topsailai-provider: topsailai did not answer within 120s
```

## Root cause

Two independent defaults that were never reconciled:

| Side | Setting | Old default |
|---|---|---|
| Scheduler | `SCHEDULER_PROVIDER_CALL_TIMEOUT` | `30s` (`src/config/config.go`) |
| Provider | `LAUNCH_TIMEOUT` | `120` seconds (`bin/scheduler-provider-topsailai`) |

The scheduler's budget must exceed the provider's, otherwise the outer timeout
always fires first.

## Resolution

`DefaultProviderCallTimeout` is now `180s` (`src/config/config.go`), which leaves
room for the reference provider's 120-second launch budget plus its own overhead.
The constant carries a comment stating the constraint, so the next person to
change either number sees why they are related.

The constraint is now documented where a provider author will read it:

- `docs/Provider_Contract.md` — the default is stated, and a provider whose own
  budget is longer must say so.
- `docs/Seam.md` — the same rule at the seam description.
- `docs/Environment_Variables.md` — the default and the reason.
- `src/main/main.go` — the `--help` text.
- `providers/scheduler-provider-topsailai/docs/Live_Test.md` — the live test still
  sets the value explicitly, so a future mismatch is visible in the test rather
  than hidden in a default.

## Verification

`make check` passes: `go vet ./...` clean and `go test ./... -race -count=1` green
for all 12 packages. The config test asserts against the constant rather than a
literal, so it follows the new default automatically.

## Remaining note

A provider with a budget longer than 180 seconds still needs the scheduler's value
raised. The contract now says so explicitly instead of leaving the relationship
implicit.
