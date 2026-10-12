---
maintainer: AI
author: DawsonLin
status: pending
---
# Hook Point default Script Hook architecture mismatch

## Authority and scope

Human clarified on 2026-10-10: each Hook Point has a built-in/default Hook that identifies and executes Scripts; Modules execute first, Scripts second, both by name; every Module exposes `main(*args, **kwargs)`. This issue tracks production architecture correction only. U01–U06 source/test corrections are committed; this issue stays open for U07–U11 lifecycle/migration acceptance and does not authorize core rollout.

References: [target design](../features/feature-unified-hooks-design.md), [API target/current distinction](../docs/Hooks_API.md).

## Historical pre-repair evidence

- `hooks/configured_runtime.py::_ConfiguredPlan` stores script entries separately; `register_configured` calls `HookRegistry.publish_configured` and `_execute_configured` passes `module_bindings=()` to Script execution.
- `hooks/registry.py` maintains separate `bindings` and `configured` indexes. Shared generation/Scheduler is not a single Binding DAG.
- `hooks/configured_registration.py::ConfiguredHookRegistrar` and `hooks/configured_executor.py::ConfiguredHookExecutor` publish/execute that separate plan; `hooks/configured_bootstrap.py::ConfiguredHookBinding` describes only scripts/folder.
- `HookRuntime.register` does not automatically install one default Hook per Hook Point or enforce `module:main`.
- Explicit Script lists preserve caller order; recursive folders use relative-path order; target sorting must consistently use final registered names.
- `hooks/hook_script.py::build_hook_point_binding_plan` retains the correct terminal planning primitive but is not enforced by the main configured path.

## Historical impact

Scripts may execute without the point's Modules or their cleanup-safe predecessor barrier. Default-Hook cardinality/capacity and unified dependencies are not enforced. Tests for isolated terminal planning and separate Script runtime can both pass without proving the original architecture. Core Hook-point rollout must remain deferred.

## Narrow correction direction

Publish and capture one complete Hook-point plan atomically: name-sorted Module Bindings followed by exactly one framework-owned terminal `hook_script`. Use the existing trusted immutable Script snapshot as that default Hook's internal entries, not a peer plan. Route all Executor/admission modes through the unified plan; preserve trust authority, singleflight, rollback, deadline, cancellation and cleanup custody.

Public Modules use `main(*args, **kwargs)`; worker adaptation must pass only detached validated data, never live host objects. Sort Modules by final registered name. Sort Scripts from either source by case-sensitive Unicode final registered names; reject duplicate keys atomically. No naming-format restriction or list-position tie-break, numeric sorting or priority override.

## Migration and acceptance

Decide whether current configured signatures become compatibility adapters or are removed before further adoption; do not silently retain a bypass. Revise the bootstrap schema only after the unified publication contract is specified. Preserve last-valid-plan replacement and ownership recovery. Historical task approvals are implementation evidence, not acceptance of the restored contract.

Required regressions: every point including an empty point has exactly one default Hook; Modules run in name order before any Script; default Hook waits for cleanup-safe predecessors; both sources use identical registered-name order independent of input/scan order; duplicate names reject without mutation; `main` invocation is real; no public path bypasses the unified plan; startup/lazy/reload/close preserve complete-plan custody. No tests executed in this documentation turn.

## Final decision acceptance criteria

- Reject/clean invalid desired revisions, retain the last known good active plan for new admissions, and report desired_revision, active_revision and update_failed_using_last_known_good. First registration failure is unavailable; business blocking remains Catalog-authorized.
- Support only synchronous wait and async await. Existing emit/emit_configured/aemit are outside target scope; remove or explicitly migrate them without a non-waiting target path.
- Main arguments and returns have no required business schema. Framework-owned HandlerResult and HookPointResult separate arbitrary content/presence/representation from execution status, timing, safe diagnostics, cleanup and Catalog-authorized decision. False, None and error-shaped dictionaries remain normal successful returns.
- Preserve isolation: use safe bounded transport, never unsafe pickle; untransportable objects have explicit unavailable representation or a bounded managed reference with release/expiration/close ownership. Do not invoke plugins in the host to obtain values.
- Script names have no format restrictions; duplicates within each kind reject. Directory root-relative name generation is proposed, not Human-approved. Tests must not restore basename-only restrictions or infer block from return values.

## Completed synchronous correction and remaining acceptance

U06A–U06D implement complete immutable-plan synchronous execution, real isolated `main` invocation, name order and one default terminal Hook with cleanup-safe predecessor barriers. Configured adapter `17d9e9ac` calls `execute_hook_point`; ordinary entry `14d61522` adds scope-local source descriptors and exact publication/reader acquisition under a deadline fixed before capture/preparation. Execution-local custody isolates exact-record debt and retains exception ownership. U06D final affected verification is 208 passed with changed line/branch coverage 100%; two accepted provenance REDs remain independent known results. Historical evidence above describes the cause, not the current configured executor.

Still pending: U07 last-known-good/diagnostics and first-failure availability; U08 async cancellation/cleanup; U09 Catalog-authorized decisions; U10 removal of nonwaiting APIs; U11 complete BDD/integration/documentation acceptance. Managed-reference support is not inferred from the result field inventory. Keep this issue open until these remaining gates pass.


## U07–U11E implementation evidence and remaining acceptance

Evidence append only; status remains pending and this Issue is not closed. U07 `33bafa42` implements desired/active LKG diagnostics; U08 `87e756d5` implements awaited cancellation custody; U09 `3168fecd`/`0f4c6f46` enforces Catalog authorization against unified status, not returned data or cleanup-only success; U10 `035b270a`/`0b6dbc4b` removes nonwaiting methods/receipts without aliases and rejects Catalog background mode. These supersede the historical pending inventory above without rewriting incident evidence.

U11A `57925ffa` verifies isolated Module-main order, one default Hook and returns; U11B `f7c0db22` verifies real Registrar/Executor LKG reload and initial unavailable; U11C `ad7ae5ca` verifies cancellation and in-flight shared-deadline successor barriers with a 300ms shared budget below 1000ms local budgets; U11D `dc0df4c4` verifies real sync/async before/success/error wrappers, original exception identity/traceback and no return-derived authority; U11E `0f708a36` verifies public pinned-manifest startup and exact demo/worker exit. Latest selected affected evidence: 480 passed, no skipped/xfail. Evidence is retained under `.tmp/u11/final/`; it is not unrestricted ALL GREEN.

U11F–G are limited documentation synchronization. U11H final regression remains pending; two accepted provenance REDs in `tests/unit/test_topsailai_hooks/test_hook_point_plan_publication.py` remain unchanged and require a Human acceptance-exception decision before Issue closure. Managed references and application-core Hook-point rollout remain deferred. The public facade returns DispatchReport with unified_result, not a bare HookPointResult; trust prerequisites are not weakened.
