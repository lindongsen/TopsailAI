---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: resolved
severity: high
---
# Configured Registrar startup rollback retains stale READY state

## Trigger

Renewed exhaustive G3 review correlated `ConfiguredHookRegistrar.start()` with the documented fail-closed startup contract and exercised the rollback state through a focused in-memory probe.

## Confirmed behavior

For startup mode with `startup_policy="fail"`, when Hook A registers successfully and Hook B then fails deterministically, `start()` retires Hook A's Runtime plan but leaves Hook A's Registrar cell in `READY`.

Observed state:

```text
start_state=failed_deterministic
hook_a_state=ready
hook_b_state=failed_deterministic
retired=['hook_a']
second_ensure_hook_a=ready
```

The second `ensure_registered("hook_a")` returns `READY` without republishing the plan that rollback removed.

## Root cause

`ConfiguredHookRegistrar.start()` calls `retire_configured()` for plans activated earlier in the failed startup attempt, but does not invalidate or otherwise reconcile their `_RegistrationCell` states. Runtime custody and Registrar publication state therefore diverge.

## Impact

The default startup policy fails the current startup call, but the Registrar remains internally inconsistent if retained or observed by later code. A later Executor call can treat the Hook as ready and delegate to a Runtime where the configured plan is absent, violating the fail-closed readiness and lifecycle contract. The existing startup rollback test asserts only the Runtime retirement call and does not assert post-rollback Registrar state or a subsequent ensure/dispatch.

## Required resolution

Repair startup rollback as a separate Developer logical unit. The repair must make Runtime plan retirement and Registrar state reconciliation consistent, preserve bounded singleflight/lifecycle behavior, and add regression coverage for post-failure state and subsequent admission. Re-run the affected focused gates, complete Unit gate as appropriate, and restart exhaustive G3 from the beginning.

Do not weaken startup failure, silently preserve a partially successful layer, or change the default fail policy.

## Resolution

The fail-policy rollback now holds the Registrar condition while changing each newly published matching `READY` cell to `INVALIDATED`, clearing its error and retry metadata, and then retiring its Runtime plan before waiters are notified. The existing lifecycle then performs `INVALIDATED -> REGISTERING -> READY` on a later `ensure_registered()`, which republishes Runtime custody instead of returning stale readiness. Pre-existing `READY` cells, the failed cell, the configuration generation, and whole-layer `disable` semantics are unchanged.

## Detection failure

The original startup rollback test asserted only the list of Runtime retirement calls. Its fake Runtime did not track active custody, and it did not assert Registrar state or a later admission, so the split-brain state was invisible despite the test passing.

## Verification

- The final regression, including explicit absent/present Runtime dispatch checks, passed 20/20 repetitions in 18.705 seconds.
- The Registrar test file passed 15 tests in 0.24 seconds (1.15 seconds wall).
- The related Hook framework set passed 69 tests in 1.36 seconds (2.19 seconds wall).
- All final runs were colorless, disabled the pytest cache, used task-local temporary paths, and reported no failures or skips.

Status: resolved.
