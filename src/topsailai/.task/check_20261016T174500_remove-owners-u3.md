---
maintainer: AI
author: DawsonLin
status: awaiting-review
---
# Unit 3 owner removal

## Scope and decisions

Delete only workspace/hooks_application.py and workspace/summary_hooks_owner.py. Preserve hooks/application_access.py and all shared prepared/trust APIs. No CLI changes, commits or pushes. Human: "yes, 没有阻塞的话，请自行推进任务". ds-coder implements; independent acceptance remains with gpt-sol.

Legacy prepared tests use an explicitly assembled test-only resource graph and request builder; no replacement production owner, process singleton or application binding is introduced. Owner-exclusive acquisition/close-state-machine tests retire; live CLI, input, ordinary factory and real prepared execution assertions migrate. Existing direct-entry lifecycle/operation tests retain isolation and interruption coverage.

## Test plan before execution

1. Run migrated CLI/factory/input unit files and direct entry/operation/lifecycle regressions.
2. Run each legacy prepared observer/directory/deployment test importing the removed owner, including generic registration.
3. Run Summary BDD and Script integration through real HTTP/SSE and workers, plus input and prepared integration.
4. Run input Hook resource/failure BDD regressions. Stop dependent progression on failure, repair locally and rerun.
5. Inspect each changed file diff and whitespace, confirm only two production deletions and retained application_access.py. No production additions; coverage of removed code is not meaningful, disclose any coverage not rerun.

## Retirement mapping

Owner-only tests for singleton acquisition, constructor policy, owner close reports and binding shutdown no longer describe a live API. Retained shared Runtime/Registrar/access tests remain unchanged. CLI returns, exceptions/tracebacks, run counts, roles, output writes and input retry order are migrated rather than skipped.

## Evidence

Implementation complete; independent review pending. No commit or push.

Final affected run: 117 passed in 202.26 seconds, exit 0. Regression run: 363 passed in 514.10 seconds, exit 0; two third-party Gherkin DeprecationWarnings. No final failures, skips or xfails. Unique final selected cases: 480. A separate entries-only run passed 30 in 1.39 seconds; it is included in 117 and not counted again.

Earlier failures were test-migration defects: LLM output assertions expected a returned chat value although main prints the first message; input-hook instrumentation incorrectly passed a callable instead of the HookInstruction interface; the test graph initially omitted actual Scope/Runtime close reports. They were corrected and rerun. Final self-review also removed an EOF blank-line whitespace diagnostic.

### Exact final commands

```text
cd /TopsailAI/src/topsailai && HOME=/TopsailAI/src/topsailai/.tmp/owners-u3/home TMPDIR=/TopsailAI/src/topsailai/.tmp/owners-u3/tmp PYTHONDONTWRITEBYTECODE=1 /TopsailAI/.venv/bin/python -m pytest --color=no -q --tb=short -x -o cache_dir=/TopsailAI/src/topsailai/.tmp/owners-u3/cache --basetemp=/TopsailAI/src/topsailai/.tmp/owners-u3/base7 /TopsailAI/src/topsailai/tests/unit/workspace/test_hooks_application_entries.py /TopsailAI/src/topsailai/tests/integration/test_input_application_checkpoint.py /TopsailAI/src/topsailai/tests/integration/test_hooks_application_lifecycle.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_deployment_authorization.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_generic_prepared_registration.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_events_observer_lifecycle.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_module_directories.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_script_directories.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_script_directory_lifecycle.py > /TopsailAI/src/topsailai/.tmp/owners-u3/affected-reviewed.log 2>&1
cd /TopsailAI/src/topsailai && HOME=/TopsailAI/src/topsailai/.tmp/owners-u3/home TMPDIR=/TopsailAI/src/topsailai/.tmp/owners-u3/tmp PYTHONDONTWRITEBYTECODE=1 /TopsailAI/.venv/bin/python -m pytest --color=no -q --tb=short -x -o cache_dir=/TopsailAI/src/topsailai/.tmp/owners-u3/cache --basetemp=/TopsailAI/src/topsailai/.tmp/owners-u3/base5 /TopsailAI/src/topsailai/tests/bdd/test_summarize_hooks.py /TopsailAI/src/topsailai/tests/bdd/test_summary_script_membership.py /TopsailAI/src/topsailai/tests/integration/test_summary_script_membership.py /TopsailAI/src/topsailai/tests/bdd/test_hook_point_resources.py /TopsailAI/src/topsailai/tests/bdd/test_hook_point_resource_cleanup.py /TopsailAI/src/topsailai/tests/unit/workspace/context/test_summary_hooks_lifecycle.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_operation_context.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_summary_direct_entry.py /TopsailAI/src/topsailai/tests/unit/test_topsailai_hooks/test_application_access.py > /TopsailAI/src/topsailai/.tmp/owners-u3/regression.log 2>&1
```

### Per-file tracked diff

```text
5	9	src/topsailai/tests/bdd/summarize_hooks_harness.py
4	4	src/topsailai/tests/bdd/summary_script_membership_harness.py
14	16	src/topsailai/tests/integration/test_hooks_application_lifecycle.py
65	233	src/topsailai/tests/integration/test_input_application_checkpoint.py
2	2	src/topsailai/tests/unit/test_topsailai_hooks/test_deployment_authorization.py
0	17	src/topsailai/tests/unit/test_topsailai_hooks/test_generic_prepared_registration.py
3	5	src/topsailai/tests/unit/test_topsailai_hooks/test_summary_events_observer_lifecycle.py
2	2	src/topsailai/tests/unit/test_topsailai_hooks/test_summary_module_directories.py
1	1	src/topsailai/tests/unit/test_topsailai_hooks/test_summary_script_directories.py
2	2	src/topsailai/tests/unit/test_topsailai_hooks/test_summary_script_directory_lifecycle.py
0	493	src/topsailai/tests/unit/workspace/test_hooks_application.py
65	366	src/topsailai/tests/unit/workspace/test_hooks_application_entries.py
0	502	src/topsailai/tests/unit/workspace/test_summary_hooks_owner.py
0	298	src/topsailai/workspace/hooks_application.py
0	247	src/topsailai/workspace/summary_hooks_owner.py

```

Additional new test helper: tests/legacy_prepared_support.py, 88 insertions, zero deletions. This AI task record is ignored by Git and not staged.

### Intentional retirement and live coverage mapping

- workspace/hooks_application.py and workspace/summary_hooks_owner.py: delete obsolete application assembly, singleton acquisition, injected Executor and owner-only close state machines. No replacement production application class.
- tests/unit/workspace/test_hooks_application.py: retire wrapper-specific construction/context-manager/owner-close tests. Preserve shared access implementation and its unmodified suite within the 363 regression selection; prepared execution/sibling disposition remains integration-tested.
- tests/unit/workspace/test_summary_hooks_owner.py: retire singleton identity, legacy keyword forwarding, owner-only shutdown/retry and owner Catalog-constructor tests. Real standard factory/context construction remains in test_summary_events_observer_lifecycle.py; real session finalizer success/failure, agent/control-server cleanup and exact original error are migrated to test_hooks_application_entries.py.
- test_generic_prepared_registration.py: remove only the two parameterized deleted SummaryHooksOwner constructor-policy cases; keep generic prepared registration tests. Eight-point membership and phase-two exclusion remain covered by directory/direct-entry/operation suites.
- test_input_application_checkpoint.py: migrate live input retry/checkpoint/error behavior to real direct Module/Script execution. Old input binding-forwarding expectations are retired because input no longer uses that access path; general access isolation tests remain unchanged.
- Other legacy prepared tests use an explicit test-only Runtime/Scope/Registrar/Executor graph with real cleanup-debt assertions and original authority checks. Helper startup metrics are test projections of real registrar dispositions, not production lifecycle/observability guarantees.
- CLI mains remain unchanged; tests retain return/output, manager role, exact single/unlimited run parameters, original error identity/traceback, docstrings. No business Hook keyword injection.

### Review, boundaries and limitations

Every tracked file was reviewed separately with git diff; removed APIs and their exclusive assertions are intentional. New helper was read in full. No skip/xfail was added. Both production owner paths are absent; hooks/application_access.py remains present and unchanged. No shared hooks/prepared/trust source, CLI, issue move or project.yaml changed. Only production change is deletion of the two owners.

No new executable production lines: coverage measurement not rerun for this deletion/test migration unit. Full project tests/run_tests.py, cross-platform and packaged-launcher acceptance are not run; full-project GREEN is not claimed. Existing direct-entry platform/time/cleanup limitations remain unchanged. Test graph is not an equivalent replacement for retired owner guarantees. Independent reviewer must assess the retirement mapping and full diff before acceptance.
