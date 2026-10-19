---
maintainer: AI
author: DawsonLin
---
# Stale CLI control action inventory

## Status
Resolved after ds3 minimal repair, ds1 independent verification and ds2 final acceptance.

## Evidence and cause
Saved CLI regression output at /TopsailAI/src/topsailai/cli/.tmp/fbt-control-shortcuts/regression-final.log records 386 passed and one failure. HEAD test /TopsailAI/src/topsailai/cli/tests/unit/topsailai_send_control/test_topsailai_send_control.py::TestGetParams::test_control_actions_are_discovered_from_runtime_handlers omits llm_control from its exact expected list. Independently inspected HEAD already exposes that action through LLMControlHandler, and runtime_control.get_control_actions queries the discovered registry. The new CLI shortcuts do not change discovery. The historical integration test inventory was not synchronized with backend action registration.

## Approved action and verification
Add llm_control in sorted position between hard_interrupt and soft_interrupt; retain exact equality and all existing actions. Do not weaken assertions or remove the backend action. Developer ds3 repairs; independent Tester ds1 reruns the failed test, full file and approved CLI regression/focused/BDD selections; Reviewer ds2 accepts the final candidate. No tests run by this planning review. This record is explicitly requested despite CLI README's default no-issues convention.

## Developer repair evidence
The approved single-entry expectation repair is implemented. Original failed case: 1 passed (0.71s pytest, 2.28s wall); complete test file: 38 passed (0.83s pytest, 2.22s wall), no skips. Logs: CLI .tmp/fbt-control-shortcuts/inventory-case.log and inventory-file.log. Exact equality and sorted inventory remain intact; per-file diff contains only the one insertion. Status remains pending independent ds1 regression verification and ds2 acceptance; no lifecycle move performed.


## Final independent acceptance
Reviewer ds2 inspected the exact one-entry repair, live candidate hashes and ds1 logs: original case 1 passed, file 38 passed, approved regression 387 passed, focused tests 39 passed and socket BDD 5 passed, with zero failures/skips. Exact registry equality is retained. Final acceptance is recorded in CLI .task/code_20261019T000442_fbt-control-shortcuts-acceptance.md. No source/test edits, staging or commit were made by the Reviewer.
