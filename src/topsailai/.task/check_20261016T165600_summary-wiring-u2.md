---
maintainer: AI
author: DawsonLin
---
# Summary business wiring U2

Scope: preserve exact business checkpoints and legacy prepared framework; remove business Hook parameters and CLI forwarding, not owner files. New finite operation context resolves eight direct entries, owns checkpoint consumption and restores exact nesting tokens. Copied contexts cannot borrow another thread/task's operation. Existing business exceptions outrank error observers.

## Verification plan

- Migrate lifecycle tests to observe direct entries without Executor injection; retain two layers x two modes, generation/application failure stages, human rejection, feasibility/local-empty skips, exception identity and traceback.
- Test duplicate checkpoint, invalid fields before consumption, phase-two rejection, nesting/exception restoration, thread/task isolation and sequential operation IDs.
- Run lifecycle, snapshot, direct-entry real-worker, retained adapter/observer and focused existing context regression tests in colorless mode. Artifacts and coverage remain in .tmp/summary-wiring-u2.
- Review per-file diffs and added executable coverage; owners and unrelated cli/team_agent.py stay untouched. No commit/push. Broader BDD/harness migration and whole-project acceptance must be disclosed if not completed.

## Human CLI restoration clarification

Human requested all affected CLIs return to their pre-HooksApplication form and explicitly authorized handling the manually edited cli/team_agent.py. Preserve unrelated changes. Verify six entries against 9a1f846b^, parse syntax, require parameterless main and absence of Hook plumbing; no commit or push.

CLI restoration: all six entries are byte-identical to 9a1f846b^ after confirming no intervening committed changes since 9a1f846b. Syntax parses, main is parameterless, and Hook plumbing is absent. Initial transformation check stopped on docstring indentation in agent_chats before writing that file; historical restoration resolves it. Live CLI/LLM regression remains pending.

## U2 resumed scope and verification

Human accepted the six CLI restorations; do not modify CLI files again. Owners remain until U3. Add lifecycle expiration so saved contexts cannot resurrect an ended operation; verify exception precedence, at-most-once marking before entry including failures/reentry, nested restoration, copied thread/task isolation, both layers and modes, phase-two inactivity and real bundled workers. Run existing context regressions separately where import isolation requires it. Broader legacy owner/BDD harness migration is not claimed by focused unit acceptance.

## U2 developer verification results

Awaiting independent review; no commit or push. Kept owners, shared prepared/trust/application_access and all six already accepted CLI files untouched during resumed task. Removed only summary-specific factory/constructor/generation keywords and their forwarding; preserved business application actions and exception re-raise sites. Direct operation calls existing point build_payload before consuming a checkpoint, then invokes exactly one same-named entry; retained legacy adapter is unchanged. New operation lifetime expiration prevents same-thread saved Context resurrection after return. Exact thread/task custody prevents foreign context borrowing; nested token restoration preserves outer custody.

Artifacts: .tmp/summary-wiring-u2/resumed/. Initial focused run: 154 passed in 7.34 seconds, exit 0. Final coverage run: 419 passed in 18.37 seconds, exit 0; regression append: 150 passed in 11.12 seconds, exit 0. No failures/errors/skips in these runs. Coverage run initially warned agent_shell was not imported; the appended factory regression imports and covers it. Changed production statements: summary_adapter 51/51, base 11/11, ctx_runtime 4/4, agent2llm 4/4, agent_shell 1/1; aggregate 71/71 (100%). Branch arcs originating on added lines: adapter 10/10, base 2/2, total 12/12 (100%). Coverage JSON generated after both runs. git diff --check clean. Reviewed git diff individually for all six tracked changed files and read the complete new operation test. Intentional deletions remove old injected plumbing and obsolete default-disabled test expectations, not business operations.

The 12 real-worker lifecycle cases cover two layers x message/runtime x success/generation failure/application failure, with actual named entries, actual bundled observer processes, operation identity, exact point names and zero pending cleanup. Other cases cover confirmation rejection, persistence/write/delete/reload order, partial application, token failures, tool pairing, exact exceptions/source frames, active-error observer precedence, reentry deduplication, nesting, copied thread/task contexts and concurrent operations. Phase-two remains inactive.

Exact common environment: PYTHONDONTWRITEBYTECODE=1; PYTHONPATH=/TopsailAI/src/topsailai:/TopsailAI/src:/TopsailAI; TOPSAILAI_HOME=/TopsailAI/src/topsailai/.tmp/summary-wiring-u2/resumed/home; TMPDIR=/TopsailAI/src/topsailai/.tmp/summary-wiring-u2/resumed/tmp; NO_COLOR=1; COVERAGE_FILE=/TopsailAI/src/topsailai/.tmp/summary-wiring-u2/resumed/.coverage. Executable: /TopsailAI/.venv/bin/python.

Coverage command: -m coverage run --branch --source=topsailai.hooks.points.context,topsailai.workspace.context,topsailai.workspace.agent_shell -m pytest --color=no -q --tb=short -o cache_dir=/TopsailAI/src/topsailai/.tmp/summary-wiring-u2/resumed/coverage-cache --basetemp=/TopsailAI/src/topsailai/.tmp/summary-wiring-u2/resumed/coverage-temp followed by absolute paths for tests/unit/workspace/context/test_summary_hooks_lifecycle.py and tests/unit/test_topsailai_hooks/{test_summary_operation_context.py,test_summary_direct_entry.py,test_summary_snapshot.py,test_summary_hook_points.py,test_summary_events_observer_wiring.py}. Output: coverage.log.

Regression command: -m coverage run --append --branch --source=topsailai.hooks.points.context,topsailai.workspace.context,topsailai.workspace.agent_shell -m pytest --color=no -q --tb=short -o cache_dir=/TopsailAI/src/topsailai/.tmp/summary-wiring-u2/resumed/regression-cache --basetemp=/TopsailAI/src/topsailai/.tmp/summary-wiring-u2/resumed/regression-temp followed by absolute paths for tests/unit/workspace/context/test_agent2llm.py, tests/unit/workspace/context/test_ctx_runtime.py and tests/unit/test_topsailai_workspace_agent_shell.py. Output: regression.log.

Limitations: focused developer verification only, not independent acceptance or full-project GREEN. No real HTTP/SSE BDD rerun; existing summary BDD harnesses/integration/owner tests still inject removed executor keywords and need migration under the remaining plan. Do not invoke those old harnesses and infer compatibility. Current new path retains generic direct-entry POSIX/budget/cleanup limitations; scripts receive no summary payload; worker success does not establish observer persistence. No owner deletion, legacy framework deletion, native capability expansion or broader rollout approval.

## U2 review repair plan

Independent review rejected deferral of business harness migration. Migrate both business harnesses to configured direct entries and real subprocess observations; retain startup dispositions and immutable prepared snapshot assertions only as explicitly legacy checks. Preserve HTTP/SSE, provider bodies/counts, history/token equivalence, exception identity/traceback, skips and observer failure assertions. Run previously failing real_summaries selection first, then complete both Summary BDD suites and Script integration. No CLI/source/owner deletion or commit. Test artifacts: .tmp/summary-wiring-u2/repair.

## U2 review repair verification

The rejected business harness gap is repaired. Business factory calls no longer pass removed keywords; direct configuration selects actual external Modules and executable Scripts. Metadata remains Module-only; Scripts assert empty stdin. Original HTTP/SSE bodies/counts, layer checkpoints, persisted history/token equivalence, error identity/traceback and skip assertions remain. Legacy startup dispositions are isolated in _prepare_legacy; existing prepared snapshot/stale-authority integration remains separate. Direct membership added after configuration is now tested as discoverable, not as a trust rejection. No scenario was deleted or skipped to conceal the migration gap.

Final verification uses PYTHONDONTWRITEBYTECODE=1, PYTHONPATH=/TopsailAI/src/topsailai:/TopsailAI/src:/TopsailAI, TOPSAILAI_HOME=/TopsailAI/src/topsailai/.tmp/summary-wiring-u2/repair/home, TMPDIR=/TopsailAI/src/topsailai/.tmp/summary-wiring-u2/repair/tmp and NO_COLOR=1.

Exact final commands:

```text
/TopsailAI/.venv/bin/python -m pytest --color=no -q --tb=short -x -k real_summaries -o cache_dir=/TopsailAI/src/topsailai/.tmp/summary-wiring-u2/repair/cache --basetemp=/TopsailAI/src/topsailai/.tmp/summary-wiring-u2/repair/final-selection-temp /TopsailAI/src/topsailai/tests/bdd/test_summarize_hooks.py
/TopsailAI/.venv/bin/python -m pytest --color=no -q --tb=short -x -o cache_dir=/TopsailAI/src/topsailai/.tmp/summary-wiring-u2/repair/cache --basetemp=/TopsailAI/src/topsailai/.tmp/summary-wiring-u2/repair/final-bdd-temp /TopsailAI/src/topsailai/tests/bdd/test_summarize_hooks.py /TopsailAI/src/topsailai/tests/bdd/test_summary_script_membership.py
/TopsailAI/.venv/bin/python -m pytest --color=no -q --tb=short -x -o cache_dir=/TopsailAI/src/topsailai/.tmp/summary-wiring-u2/repair/cache --basetemp=/TopsailAI/src/topsailai/.tmp/summary-wiring-u2/repair/integration-temp /TopsailAI/src/topsailai/tests/integration/test_summary_script_membership.py
```

Results: original failing selection 2 passed, 15 deselected in 3.67 seconds; complete BDD 36 passed in 58.61 seconds; integration 10 passed in 41.30 seconds. All exit 0. The selection is a subset of the complete BDD count; 46 distinct complete-suite cases passed. Logs: final-selection.log, final-bdd.log, integration.log under .tmp/summary-wiring-u2/repair. Integration includes real direct execution ordering for both layers, checkpoint deduplication, independent operation IDs, Script error continuation and real timeout cleanup. Complete BDD covers both layers, normal summaries, generation/application failures, skip paths and observer failure without provider/business changes.

Self-review: ran git diff separately for each of the five repair files, checked intentional removal of obsolete owner/report assertions, retained legacy integration, no removed scenarios and no new skips. git diff --check passes. No production changes in this repair; earlier production line coverage 71/71 and arcs 12/12 is unchanged, not a newly rerun coverage claim. Startup/owner tests outside these migrated business harnesses remain U3 scope; full project and cross-platform acceptance not established. No CLI edits, owner deletion, commit or push. Awaiting independent re-review.

Repair files relative to HEAD: tests/bdd/summarize_hooks_harness.py; tests/bdd/summary_script_membership_harness.py; tests/integration/test_summary_script_membership.py; tests/bdd/features/summarize_hooks.feature; tests/bdd/features/summary_script_membership.feature. This task record is updated separately.
