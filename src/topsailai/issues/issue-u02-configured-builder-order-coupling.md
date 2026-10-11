---
maintainer: AI
author: DawsonLin
status: resolved
---

# U02 configured builder ordering compatibility boundary

## Status

Resolved compatibility boundary: U02 committed as `b947b3f036f78dfc336f2524fe44d8aae45c7f49` and independently approved. The minimal configured regression migration was authorized, preserving real isolation and cleanup assertions. U06C configured adapter `17d9e9ac` subsequently connected unified execution. The historical failure below is not a current unstaged/uncommitted candidate.

## Symptom and reproduction

Run the focused test `tests/unit/test_topsailai_hooks/test_simplified_configured_runtime.py` against the U02 candidate. `test_real_scripts_execute_in_explicit_and_folder_order` at line 392 expects explicit execution z,a but observes a,z. Saved evidence: `.tmp/u02/green_test_simplified_configured_runtime.log` (1 failed, 15 passed, no skips).

## Root cause

`hooks/configured_runtime.py` invokes `execute_configured_hook_script`, which rebuilds through `build_hook_point_binding_plan_from_discovery`. Sorting legacy fallback names in that shared builder changes configured execution too; the U02 plan incorrectly assumed configured compatibility remained isolated. The new metadata itself does not require changing discovery-generated names.

## Historical impact and resolved gate

U02 cannot satisfy both its unconditional builder sorting goal and the promised unchanged configured caller order. Stop rather than silently expanding test/consumer scope. Review the minimal additional configured compatibility-test migration or design a separate execution adapter unit; do not invent directory automatic names or weaken shared sorting through an unapproved bypass. Require all scoped compatibility tests, final changed-logic coverage and per-file review before any commit. Existing identifier/architecture issues are separate and untouched.

## Evidence and prevention

Resolution: the approved six-file U02 migration passed 142 focused tests with no failures/skips and changed-logic coverage 100%; per-file review and post-commit approval are recorded in [the plan](../.task/plan_20261010T101643_unified-hooks-contract-repair.md). No production sorting bypass was introduced. This authorized round updates status in place; only the identifier issue is moved to `done/`. Inspect reachable consumers before claiming a shared builder change is scaffolding-only; this prevents deferred Runtime migration from changing behavior invisibly.
