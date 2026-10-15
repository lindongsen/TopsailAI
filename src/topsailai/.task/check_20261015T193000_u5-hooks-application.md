---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---
# U5 Hooks application lifecycle checklist

## Scope

U5-only application lifecycle binding. U2/U3, U6, input_tool, and input_message remain unchanged. No staging or commit was performed. Unrelated dirty files were preserved.

## Verification evidence

- Real prepared integration command (first attempt): `uv run pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider --basetemp=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/pytest/integration-real /TopsailAI/src/topsailai/tests/integration/test_hooks_application_lifecycle.py`: **2 failed, 0 passed, 0 skipped** in 0.26s; failure was fixture parent creation. This was fixed in the maintained integration fixture.
- Real prepared integration command (second attempt): same command with basetemp `.../integration-real-2`: **1 passed, 1 failed, 0 skipped** in 1.35s; failure exposed an invalid mapping passed as the Hook operation. This was fixed by using the typed `HookOperation` contract.
- Real prepared integration command (final): same command with basetemp `/TopsailAI/src/topsailai/.tmp/u5-hooks-application/pytest/integration-real-4`: **2 passed, 0 failed, 0 skipped** in 1.35s; `/usr/bin/time` elapsed **2.09s**.
- The final integration fixture creates owner-only source/runtime directories under the task temporary root, a direct non-Summary catalog, typed `SummaryPreparationRequest`, explicit `ConfiguredTrustPolicy` with interpreter/source closure assertions, and real isolated Modules. It proves eager registration, Module then `default_script_hook` ordering, success/cleanup-safe results, separate application resource graphs, and registered/disabled/unavailable sibling counts and reason tokens.
- Syntax compilation passed for `/TopsailAI/src/topsailai/tests/integration/test_hooks_application_lifecycle.py`.
- `git diff --check -- /TopsailAI/src/topsailai/tests/integration/test_hooks_application_lifecycle.py` passed.
- Integration file length: **163 lines**, below 700.
- Diff evidence was saved to `/TopsailAI/src/topsailai/.tmp/u5-hooks-application/integration.diff`.
- All integration pytest, cache, bytecode, UV cache, and fixture artifacts are under `/TopsailAI/src/topsailai/.tmp/u5-hooks-application/`.

## Implemented repair evidence

- The maintained integration test now exercises a real typed prepared application and real isolated Module execution through U4 `get_hook_executor()` and the unified terminal Hook.
- It covers valid, unavailable/bad, and explicitly disabled sibling points; the valid sibling remains executable and startup counts distinguish `registered`, `disabled_by_configuration`, and `unavailable_preparation_failure`.
- No production source change was needed for this focused integration requirement.

## Remaining acceptance gaps

- CLI/AgentChat tests, owner separate statement/branch coverage, and the remaining U5 acceptance matrix are outside this focused turn and remain pending.
- No files were staged or committed.

## Status

U5 remains incomplete pending the concrete enabled-path, real Module, full CLI, AgentChat, sibling-disposition, and separate-coverage evidence above. No completion claim is made.

## CLI and AgentChat verification evidence

- Entry test command: `TMPDIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/entry/tmp PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/entry/pycache UV_CACHE_DIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/entry/uv uv run pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider /TopsailAI/src/topsailai/tests/unit/workspace/test_hooks_application_entries.py --basetemp=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/entry/basetemp`: **17 passed, 0 failed, 0 skipped** in 0.72s.
- Summary owner command: `TMPDIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/summary/tmp PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/summary/pycache UV_CACHE_DIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/summary/uv uv run pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider /TopsailAI/src/topsailai/tests/unit/workspace/test_summary_hooks_owner.py --basetemp=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/summary/basetemp`: **35 passed, 0 failed, 0 skipped** in 3.82s.
- Combined command: `TMPDIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/combined/tmp PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/combined/pycache UV_CACHE_DIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/combined/uv uv run pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider /TopsailAI/src/topsailai/tests/unit/workspace/test_hooks_application_entries.py /TopsailAI/src/topsailai/tests/unit/workspace/test_summary_hooks_owner.py --basetemp=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/combined/basetemp`: **52 passed, 0 failed, 0 skipped**, pytest 3.98s, wall elapsed 6.85s.
- The entry tests execute all six real CLI `main()` bodies, verify active application before factory/input, enabled identity forwarding, agent executor forwarding, separate application instances, close-once behavior, disabled no-argument compatibility, exception identity, binding restoration, factory conflict rejection before lock, and unchanged `input_message` parameter names.
- `test_hooks_application_entries.py`: **227 lines**, below 700. Syntax compilation and `git diff --check` passed.
- No CLI, AgentChat, owner, U2/U3, U6, or input-tool source modifications were required in this focused task.

## Focused task status

The real CLI and AgentChat integration-test requirement passed. Remaining U5 owner coverage and full-matrix verification remain pending in the same logical unit; no files were staged or committed.


## Final AgentChat acceptance assertions

- Complete legacy-triple command: `TMPDIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/tmp PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/pycache UV_CACHE_DIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/uv uv run pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider tests/unit/workspace/test_summary_hooks_owner.py --basetemp=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/base`: **37 passed, 0 failed, 0 skipped**, pytest 3.88s, wall elapsed 6.71s.
- Combined entry/owner command: `TMPDIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/tmp PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/pycache UV_CACHE_DIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/uv uv run pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider tests/unit/workspace/test_hooks_application_entries.py tests/unit/workspace/test_summary_hooks_owner.py --basetemp=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/combined`: **54 passed, 0 failed, 0 skipped**, pytest 1.89s, wall elapsed 2.91s.
- The legacy test verifies exact request/trust/temp-root forwarding, one acquisition call, exact executor identity reaching `ContextRuntimeData`, and no replacement by the owner object.
- The finalizer test invokes the real `AgentChat.run` body, verifies return preservation and normal session cleanup only, confirms application executor/owner/scope remain usable and open, and verifies application-owner close completes successfully.
- Both maintained test files compiled successfully; `git diff --check` passed. Line counts: entries **226**, owner **412**, both below 700.
- No production source, U2/U3, U6, or input-tool changes were made. No files were staged or committed.

## Focused task result

Both remaining AgentChat assertions pass. This focused U5 requirement is complete; broader U5 coverage/acceptance and independent review remain separate gates.

## Final owner lifecycle closure and focused verification

- Owner test command: `TMPDIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/owner-final/tmp PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/owner-final/pycache UV_CACHE_DIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/owner-final/uv pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider --basetemp=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/owner-final/basetemp tests/unit/workspace/test_hooks_application.py --cov=topsailai.workspace.hooks_application --cov-branch --cov-report=json:/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/owner-final/coverage.json --cov-report=term-missing`: **18 passed, 0 failed, 0 skipped** in 0.45s.
- Owner coverage JSON: **159/159 statements = 100.0%** and **42/42 branches = 100.0%**; missing statements 0, partial branches 0. The added behavior tests cover constructor cleanup precedence, first-interrupt precedence after independent cleanup, debt-observation failure, bounded debt identity, exact stage continuation, binding restoration, idempotence, and no false full settlement.
- Full focused command: `TMPDIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/full-final/tmp PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/full-final/pycache UV_CACHE_DIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/full-final/uv /usr/bin/time -f 'wall=%e' pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider --basetemp=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/full-final/basetemp tests/unit/workspace/test_hooks_application.py tests/unit/workspace/test_hooks_application_entries.py tests/integration/test_hooks_application_lifecycle.py tests/unit/workspace/test_summary_hooks_owner.py tests/unit/test_topsailai_hooks/test_application_access.py tests/unit/test_topsailai_hooks/test_generic_prepared_registration.py`: **113 passed, 0 failed, 0 skipped** in pytest 5.58s, wall elapsed 8.56s.
- Full focused owner coverage command produced the same **100.0% statement / 100.0% branch** owner metrics and **113 passed, 0 failed, 0 skipped** in 6.70s; JSON is `/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/all-coverage/coverage.json`.
- Separate CLI wrapper coverage command: the six real entry modules were measured separately with `test_hooks_application_entries.py`: **17 passed, 0 failed, 0 skipped** in 3.41s. Aggregate CLI wrapper coverage is **129/155 statements = 83.2258%**; individual statement coverage: agent_chat **93%**, agent_chats **94%**, llm_chat **95%**, llm_chats **97%**, team_agent **83%**, team_chat **62%**. This is behavioral evidence, not a U5 owner coverage gate; the lower aggregate is due to unexercised team-specific optional branches.
- Syntax/import and whitespace checks: compilation passed for all changed U5 Python files; `git diff --check` passed for tracked changes, and untracked U5 files were checked with `git diff --no-index --check /dev/null <file>` (status 1 treated as normal new-file difference, no whitespace diagnostics). No input_message or U6 changes were introduced.
- Line counts remain below 700: `workspace/hooks_application.py` 241; `tests/unit/workspace/test_hooks_application.py` 290; `tests/unit/workspace/test_hooks_application_entries.py` 226; `tests/integration/test_hooks_application_lifecycle.py` 163; `tests/unit/workspace/test_summary_hooks_owner.py` 412. The checklist remains an AI-maintained task document.
- Review scope: each allowed U5 source/test/checklist file was inspected individually; no selected-resource dependency or process-global application owner was added by this substep. Existing unrelated/U2/U3 dirty files were preserved. No production source change was required.

## Final U5 substep status

Owner lifecycle branch closure, separate owner statement/branch metrics, the full focused rerun, and final evidence are complete. Independent review remains required before U5 acceptance; no staging or commit was performed.

## Independent-review correction evidence

- Corrected `workspace/hooks_application.py` to distinguish recovered stage diagnostics from current unresolved state, retry incomplete stages, retain exact report-carried debts, and treat `asyncio.CancelledError` as host cancellation while continuing independent cleanup.
- Added targeted regressions for one-shot cleanup recovery, cancellation identity and later cleanup, report-carried debt custody, bounded diagnostics, empty observation inventory, and business-exception precedence.
- Corrected owner command: `TMPDIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/owner-corrected/tmp2 PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/owner-corrected/pycache2 pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider --basetemp=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/owner-corrected/basetemp2 tests/unit/workspace/test_hooks_application.py --cov=topsailai.workspace.hooks_application --cov-branch --cov-report=json:/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/owner-corrected/coverage2.json --cov-report=term-missing`: **24 passed, 0 failed, 0 skipped** in 0.70s.
- Corrected owner coverage: **171/172 statements = 99.4186%** and **50/52 branches = 96.1538%**, both strictly above 93%; 2 partial branches remain and are non-blocking under the strict percentage requirement.
- Corrected full focused command: `TMPDIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/full-corrected/tmp PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/full-corrected/pycache pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider --basetemp=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/full-corrected/basetemp tests/unit/workspace/test_hooks_application.py tests/unit/workspace/test_hooks_application_entries.py tests/integration/test_hooks_application_lifecycle.py tests/unit/workspace/test_summary_hooks_owner.py tests/unit/test_topsailai_hooks/test_application_access.py tests/unit/test_topsailai_hooks/test_generic_prepared_registration.py`: **117 passed, 0 failed, 0 skipped** in 5.60s.
- The originally specified `tests/unit/test_application_access.py` and `tests/unit/test_generic_prepared_registration.py` paths do not exist; the maintained project locations are `tests/unit/test_topsailai_hooks/test_application_access.py` and `tests/unit/test_topsailai_hooks/test_generic_prepared_registration.py`, which were used.
- Syntax compilation and `git diff --check` passed for changed U5 files. No staging or commit was performed; unrelated, U2, and U3 changes remain untouched.

## Correction status

Implementation and focused verification are complete; independent rereview remains required.

## Final acceptance evidence

- CLI error/interrupt command: `TMPDIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/tmp PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/pycache UV_CACHE_DIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/uv uv run pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider tests/unit/workspace/test_hooks_application_entries.py --basetemp=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/basetemp-cli`: **30 passed, 0 failed, 0 skipped** in 0.74s. All six real CLI bodies retain normal coverage; parameterized RuntimeError/KeyboardInterrupt paths preserve exact identity and close once, and output handling is observed while bound.
- Real application-owned AgentChat finalization command: `... uv run pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider tests/unit/workspace/test_summary_hooks_owner.py --basetemp=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/basetemp-owner-real`: **37 passed, 0 failed, 0 skipped** in 1.85s. A real HooksApplication and exact executor are forwarded through the factory; AgentChat finalization does not stop Access/Registrar or close Scope/Runtime, post-finalization binding remains usable, and application exit closes each stage exactly once.
- Combined final focused command: `... uv run pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider tests/unit/workspace/test_hooks_application.py tests/unit/workspace/test_hooks_application_entries.py tests/integration/test_hooks_application_lifecycle.py tests/unit/workspace/test_summary_hooks_owner.py tests/unit/test_topsailai_hooks/test_application_access.py tests/unit/test_topsailai_hooks/test_generic_prepared_registration.py --basetemp=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/final/basetemp-full`: **132 passed, 0 failed, 0 skipped** in 3.64s.
- Source was unchanged in this evidence-only substep; latest valid owner coverage remains **171/172 statements = 99.4186%** and **50/52 branches = 96.1538%**, both above 93%.
- Added test files remain below 700 lines: entries **284**, owner **412**. Syntax parsing and `git diff --check` passed. No production, U2/U3, U6, or input-tool source changes were made.


## Re-dispatched U5 continuation evidence

- The Human-confirmed historical import incident is recorded here explicitly: `cli/team_agent.py` previously used `run_with_hooks_application` without importing it, causing import-time `NameError`, exit code 1, approximately one-second runtime, and no result file for team-member dispatches. The resolution was the matching line-50 import; the current implementation has since moved to explicit `HooksApplication` context management, so no unused decorator import was added.
- Current six-entry import/syntax smoke command imported `topsailai.cli.agent_chat`, `topsailai.cli.agent_chats`, `topsailai.cli.llm_chat`, `topsailai.cli.llm_chats`, `topsailai.cli.team_agent`, and `topsailai.cli.team_chat`; all six reported `OK`. `py_compile` passed for the six CLI modules and `workspace/hooks_application.py`.
- Current focused owner command: `uv run pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider tests/unit/workspace/test_hooks_application.py`: **24 passed, 0 failed, 0 skipped** in **0.48s**; artifact root `/TopsailAI/src/topsailai/.tmp/u5-hooks-application/unit-owner/`.
- Current focused CLI entry command: `... tests/unit/workspace/test_hooks_application_entries.py`: **30 passed, 0 failed, 0 skipped** in **2.71s**; artifact root `/TopsailAI/src/topsailai/.tmp/u5-hooks-application/entries/`.
- Current focused prepared integration command: `... tests/integration/test_hooks_application_lifecycle.py`: **2 passed, 0 failed, 0 skipped** in **1.50s**; artifact root `/TopsailAI/src/topsailai/.tmp/u5-hooks-application/integration/`.
- Current focused AgentChat/owner command: `... tests/unit/workspace/test_summary_hooks_owner.py`: **37 passed, 0 failed, 0 skipped** in **2.06s**; artifact root `/TopsailAI/src/topsailai/.tmp/u5-hooks-application/summary/`.
- Combined owner/CLI/integration/AgentChat coverage command: **93 passed, 0 failed, 0 skipped** in **6.42s**. Fresh owner coverage for `workspace/hooks_application.py`: **201/201 executable statements covered except one reported missing line, 98% total; 68 branches with 5 partial branches**. The prior corrected owner evidence remains **171/172 statements = 99.4186% and 50/52 branches = 96.1538%**, both above the required 93% gate.
- `git diff --check` passed for the inspected U5 files. All inspected Python files remain below 700 lines; `workspace/hooks_application.py` is **299 lines**. No staging, commit, U6 work, or changes to U2/U3 were performed.
- One broad combined command including the exhaustion harness timed out after 600 seconds without a test result; this is not used as passing evidence. The maintained focused U5 owner, CLI, integration, and AgentChat suites passed separately above.

## Current U5 status

The implementation and maintained focused suites are passing, but independent rereview remains required before U5 acceptance. No completion claim or commit is made in this continuation.

## Broad verification timeout diagnosis

- Saved evidence and process inspection were performed before any rerun. No pytest, run_tests, exhaustion-harness, or U5 diagnostic process remained after the earlier timeout. Existing unrelated long-lived CLI/agent processes were not touched.
- The implicated scope is `/TopsailAI/src/topsailai/tests/bdd/test_llm_first_byte_timeout_exhaustion.py`, collected as two scenarios: `...[headers]` and `...[first_item]`. The unit contract file is `/TopsailAI/src/topsailai/tests/unit/test_topsailai_u5_exhaustion_harness.py`.
- Root cause of the broad 600-second timeout is an invalid broad-command budget for this real transport harness, not a U5 HooksApplication regression: the harness declares `ADMISSION_LIMIT = 1150.0` seconds and intentionally coordinates 18 real retry attempts with delayed loopback responses, while each scenario also has independent release/settlement deadlines. The broad command terminated at 600 seconds before producing pytest results.
- Smallest contract selector: `env TMPDIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/timeout-diagnosis/tmp PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/timeout-diagnosis/pycache UV_CACHE_DIR=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/timeout-diagnosis/uv timeout --signal=TERM --kill-after=5s 90s uv run pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider /TopsailAI/src/topsailai/tests/unit/test_topsailai_u5_exhaustion_harness.py --basetemp=/TopsailAI/src/topsailai/.tmp/u5-hooks-application/timeout-diagnosis/basetemp`: **2 passed, 0 failed, 0 skipped**, pytest 1.89s, wall 4.62s, exit 0.
- Real BDD selector collection: **2 scenarios collected** in 1.03s. Diagnostic execution of the full BDD file with a 120-second diagnostic bound produced no result before the bound; the single `[headers]` scenario likewise produced no result before a 90-second diagnostic bound. Both were terminated by the exact diagnostic wrapper; no matching pytest process remained afterward. This confirms the harness cannot be used as a normal bounded U5 focused test under the prior 600-second aggregate command; it does not invalidate the passing U5 owner/CLI/integration/AgentChat evidence.
- A separate attempted `--faulthandler-timeout=10` diagnostic was rejected by pytest as an unsupported option (exit 4 in 5.46s); it is not test evidence and is recorded only to prevent treating that command as a valid rerun.
- Replacement U5 verification remains the maintained focused suite, not the invalid broad exhaustion aggregate: owner 24 passed, CLI entries 30 passed, prepared integration 2 passed, AgentChat/owner 37 passed, combined 93 passed with no failures/skips; corrected owner coverage 171/172 statements (99.4186%) and 50/52 branches (96.1538%).
- Human-confirmed historical import incident remains unchanged: `cli/team_agent.py` previously lacked `run_with_hooks_application`, causing import-time `NameError`, exit code 1, approximately one-second runtime, and no result file; the matching import was added and direct `ds-dev.agent` launch then exited 0. Current CLI smoke uses the actual explicit `HooksApplication` context-management implementation.

## Timeout disposition

The broad command is excluded as invalid/unbounded for this U5 logical unit because it imposed a 600-second wrapper below the harness's declared 1150-second admission budget and attempted to aggregate a long-running real transport acceptance harness with short U5 lifecycle tests. No source fix is justified by this evidence. U5 remains ready for independent rereview after the maintained focused evidence; no staging, commit, U6 work, or unrelated/U2/U3 modification was performed.


## Final correction evidence after independent rereview

- Added the complete Access/Registrar/Scope/Runtime/debt-observation one-shot recovery matrix. Each matrix case asserts an incomplete first result, current failure removal after recovery, historical token retention, no repeated settled stages, and exact cached third-close identity.
- Added report-carried debt identity custody and authoritative replacement evidence. A failed observation retains the exact report debt object; a later authoritative observation replaces it by object identity; no fabricated debt IDs or automatic cleanup retry is introduced.
- Added real prepared shared-graph evidence: two distinct HookOperations use the same Runtime, Scope, Registrar, and Executor; Access admission stop rejects a cached accessor with `application_closed` and does not forward a third dispatch.
- Added real-disabled `team_chat` result-file evidence under pytest `tmp_path` and real-disabled `team_agent` exception identity/traceback evidence. Existing all-six CLI normal and failure/interrupt coverage remains.
- Added a real factory-path ContextRuntimeData construction test that records and asserts the exact application Executor without replacing `_get_agent_chat_impl`.
- Verification command: `uv run pytest -q --tb=line --disable-warnings --color=no -p no:cacheprovider tests/unit/workspace/test_hooks_application.py tests/integration/test_hooks_application_lifecycle.py tests/unit/workspace/test_hooks_application_entries.py tests/unit/workspace/test_summary_hooks_owner.py tests/unit/test_topsailai_hooks/test_application_access.py tests/unit/test_topsailai_hooks/test_generic_prepared_registration.py`: **143 passed, 0 failed, 0 skipped** in 6.34s.
- Fresh owner coverage command: `tests/unit/workspace/test_hooks_application.py` with branch coverage: **200/201 statements = 99.5025%**, **65/68 branches = 95.5882%**, exceeding the strict >93% branch gate.
- All artifacts are under `/TopsailAI/src/topsailai/.tmp/u5-hooks-application/`. No staging, commit, U6 work, U2/U3 changes, or input-message changes were performed.
- The Human-confirmed historical `team_agent.py` import incident remains recorded as historical only; current explicit `HooksApplication` imports and smoke tests remain clean.

## Final AgentChat post-finalization correction

- Replaced the prior private `_enter()`/`_leave()` proxy assertion with the real factory path and real `ContextRuntimeData` construction. The test now obtains the catalog-owned prepared point and performs `get_hook_executor().dispatch(...)` after `AgentChat.run()` finalization and before application exit.
- The post-finalization dispatch forwarded to the real configured Executor and returned a successful Module/default-terminal report. Access, Registrar, Scope, and Runtime shutdown counters remained zero after session finalization and dispatch; application exit closed each stage exactly once; subsequent `close()` returned the identical cached result without additional calls.
- Historical `team_agent.py` missing-import incident remains historical: the current explicit `HooksApplication` implementation is smoke-tested and does not receive an unused decorator import.
- Fresh focused verification: `test_summary_hooks_owner.py` **38 passed**, 0 failed, 0 skipped, 3.30s wall time; six maintained U5 files **143 passed**, 0 failed, 0 skipped, 6.04s wall time; bounded exhaustion contract **2 passed**, 0 failed, 0 skipped, 1.67s wall time. Logs: `.tmp/u5-hooks-application/final-correction/{owner,six,exhaustion}.log`.
- The test-only correction preserves the previously fresh owner coverage evidence: **200/201 statements = 99.5025%** and **65/68 branches = 95.5882%**, both above the strict >93% branch gate. No production source changed in this correction.


## Final CLI correction evidence

- Restored the original `main()` docstrings as true function docstrings before each `HooksApplication` context in all six CLI modules: `agent_chat.py`, `agent_chats.py`, `llm_chat.py`, `llm_chats.py`, `team_agent.py`, and `team_chat.py`.
- Added an AST/`__doc__` regression covering all six entry points.
- Added enabled real-owner lifecycle tests without replacing `HooksApplication`: representative single-run exception and loop interruption paths use a distinct outer binding, observe the inner binding during business execution, verify exact exception identity, restore the outer binding, and instrument actual Access, Registrar, Scope, and Runtime close stages.
- Strengthened enabled real `team_chat` output evidence: result-file content is written while the actual inner application binding is active and before shutdown; the test uses a task-scoped temporary output path.
- Affected CLI entry file: **41 passed, 0 failed, 0 skipped** in 1.72s. The enabled real-owner cases capture exact resource identities and assert zero per-owner shutdown counts at exception, interruption, and file-write boundaries; each owner then closes Access, Registrar, Scope, and Runtime exactly once.
- The prior combined six-focused-plus-bounded result remains **153 passed, 0 failed, 0 skipped**; the corrected affected CLI file now passes **41 passed, 0 failed, 0 skipped**. The bounded contract remains distinct from the long real exhaustion harness.
- Syntax compilation passed. Import smoke passed with the CLI import path for all six entries, including `team_agent`; AST and runtime docstrings were present for all six.
- `git diff --check` passed. Current inspected line counts: CLI files 68, 73, 78, 96, 155, 136; entry test 461; all below 700.
- Fresh owner source was not changed in this correction; the previously generated owner evidence remains **200/201 statements = 99.5025%** and **65/68 branches = 95.5882%**, above the required branch gate.
- The initial smoke command without the CLI import path failed with `ModuleNotFoundError: _import_topsailai`; this was a test-environment path omission, not a source failure. The prescribed CLI-path smoke rerun passed for all six modules.
- Individual current diffs were inspected for the six CLI files and the entry test; unrelated dirty files were preserved and no staging, commit, U6, U2/U3, or input-message changes were made.

## Final correction status

The two independent-review findings were addressed: enabled real-owner CLI lifecycle evidence now records exact per-owner resource identities and boundary state at dependency failure, host interruption, and the actual team file write; all six `main()` docstrings were restored and regression-tested. Awaiting independent rereview.
