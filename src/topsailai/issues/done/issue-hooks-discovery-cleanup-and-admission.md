---
maintainer: AI
author: DawsonLin
status: resolved
---

# Discovery cleanup ownership and admission failures

## Evidence

Source review of hooks/module_discovery.py confirms that its local IsolatedProcessBackend is discarded after probing and that WorkerResult.cleanup_confirmed/cleanup_debt are ignored. hooks/process_cleanup.py can return a successful result with unconfirmed cleanup and retains recovery authority in the backend. Thus a later probe can start while previous owned resources remain unsettled, and callers cannot recover the debt through the returned manifest.

The enumerator also converts root iteration OSError into a successful empty manifest. A resolved child has no root-containment check after the prior symlink test, allowing an observed replacement escape to reach probing.

## Required regression and repair

Use deterministic backend results with retained cleanup debt to verify no later probe starts and exact cleanup ownership remains reachable until settlement. Include the interrupted path; preserve existing process cleanup semantics. Inject enumeration failure and require rejection with zero probes, with a readable-empty-directory control. Exercise a child replacement before resolution and require rejection of a resolved escape. These are discovery integration regressions, not the separately blocked cancellation/deadline proofs or immutable-artifact work.

## Verification status

Source-confirmed; not reproduced in this review. Existing independent tests pass: eight discovery contracts and 204 other Hooks tests. Those green results do not cover these failure paths. Original implementer gpt56sol-programmer owns correction; gpt56luna-tester independently verifies; Planner re-accepts. No next script unit or commit is authorized.

## Review lesson

A caller of a bounded process backend must retain its recovery owner and inspect cleanup settlement, not infer complete cleanup from a successful payload. Admission must distinguish an authoritative empty enumeration from an unavailable one.

## Correction implemented

The discovery manifest now distinguishes enumeration failure from an authoritative empty directory, rejects a candidate whose post-resolution path is outside the canonical module root, and inspects cleanup settlement after every isolated probe. An unconfirmed result is represented as `cleanup_pending` with `entry_valid=False`; no later candidate is probed, and the immutable manifest retains a `ModuleCleanupOwner` delegating debt inspection and exact retry to the same backend instance.

Focused regressions cover retained cleanup authority and continuation gating, enumeration failure plus readable-empty control, and resolved path escape. Verification passed 12 focused tests and 208 Hooks tests with zero new outside-`.tmp` cache paths. Independent Tester and Planner acceptance remain pending; issue status remains open until acceptance.


## Planner re-review: interruption ownership still open

Normal-return cleanup_pending ownership, enumeration rejection and resolved containment fixes are confirmed by source review and independent passing execution (12 focused, 208 Hooks). Acceptance remains blocked: ModuleCleanupOwner is created only after execute returns, while backend execute can retain cleanup debt and re-raise a host interruption. Discovery does not hand that backend authority to the caller on this path. Add an explicit recovery handoff preserving the primary interruption and a deterministic regression proving exact-backend retry and no later probe; do not substitute traceback inspection or suppress host interruption. This was part of the original interrupted-path requirement, not an expansion into blocked cancellation proofs.

The tester zero-cache result used Git-filtered inventory and cannot prove absence of ignored cache additions. Repeat inventory through a bounded workspace filesystem walk excluding .tmp/.git only, preserving existing caches. Existing successful test results and logged final temp removal are valid; no failure reproduction was run by Planner. Root cause: recovery ownership was transferred only through successful function return. Detection gap: the new cleanup regression returned WorkerResult and never exercised execute raising with retained debt. Prevent recurrence by testing both return and interruption handoff paths at the discovery/backend boundary. No hook_script unit or commit is authorized.


## Interruption recovery correction implemented

`build_module_manifest()` now catches an isolated probe interruption only to inspect the same backend's retained cleanup debts. When debt exists, it attaches an immutable `ModuleCleanupOwner` to the original exception and re-raises that exact exception with its traceback unchanged. Callers retrieve the owner through `get_interruption_recovery_owner(error)`, then query or retry the exact backend debt; later candidates never start.

A focused regression proves `KeyboardInterrupt` identity propagation, first-candidate-only probing, explicit owner retrieval, exact retained debt visibility, and successful retry settlement. Focused discovery tests pass 13 cases and the complete Hooks unit directory passes 209 cases. Cache verification now inventories the real workspace filesystem before and after testing, pruning only `.tmp` and `.git`; both inventories contain 298 cache paths and the new-path delta is zero. Independent Tester and Planner acceptance remain pending, so the issue stays open.

## Closure

Status: resolved

Closed on 2026-10-02 after independent review and verification of the interruption-ownership correction and the committed module discovery work in `042ecc5`. The complete Hooks unit-test directory passed 277 of 277 tests with zero failures, errors, or skips, including `test_module_discovery_admission.py` and `test_module_discovery_manifest_red.py`.

The verified behavior covers enumeration failure versus authoritative emptiness, canonical-root containment, cleanup settlement and continuation gating, retained cleanup ownership, exact-backend debt retry, and host-interruption recovery handoff. Separate future work identified by the design—such as aggregate discovery deadlines, immutable artifacts, and full application integration—is outside this issue and does not block closure.
