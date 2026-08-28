---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
---

# Pre-existing cross-file test pollution breaks `workspace/print_tool` tests in shared process

## Symptom

Running `tests/unit/test_topsailai_workspace_print_tool.py` together with
`tests/unit/test_topsailai_ai_base_prompt_base.py` in one pytest process fails 9
tests, while each file passes alone:

- `TestCountTokens::test_plain_text` / `test_non_string_content` / `test_json_string` /
  `test_list_content` / `test_empty_string`
  -> `AssertionError: Expected 'count_tokens' to be called once. Called 0 times.`
- `TestTeeOutput::test_tee_output_need_delete_registers_cleanup_not_eager`,
  `TestDecoratorTeeOutputBySession::test_decorator_tee_output_by_session_*` (3)
  -> `FileNotFoundError: /tmp/{session_id}.{pid}.session.stdout` with a stale pid
  (`2100011`) instead of the current process pid.

## Evidence

- Fails alone? No. `pytest tests/unit/test_topsailai_workspace_print_tool.py` -> 73 passed.
- Pairwise reproduction:
  - `test_topsailai_ai_base_prompt_base.py` + `test_topsailai_workspace_print_tool.py` -> 9 failed.
  - `test_topsailai_ai_base_agent_base.py` + `test_topsailai_workspace_print_tool.py` -> all passed.
  - `test_topsailai_workspace_plugin_instruction_env.py` + `test_topsailai_workspace_print_tool.py` -> all passed.
- Root cause candidate: `tests/unit/test_topsailai_ai_base_prompt_base.py:39-41` deletes every
  `topsailai*` entry from `sys.modules` in setup. Later test modules therefore re-import
  `topsailai.workspace.print_tool`, so module-level state captured at import time (pid-derived
  session stdout path, `token_module` binding) is rebuilt in a patched/environment-altered state
  and no longer matches the assertions.
- Unrelated to `utils/print_tool.py`: `workspace/print_tool.py` does not import or call
  `print_step`, `format_print_step_simple`, or `_format_simple_tool_calls`.

## Impact

- `pytest` invocations that mix these files report false failures; only the per-file runner
  (`tests/run_tests.py`, one process per file) hides the problem.

## Suggested fix (not implemented here)

- Replace the blanket `sys.modules` purge in `test_topsailai_ai_base_prompt_base.py` with a
  save/restore fixture scoped to that module, or drop the purge if targeted patching suffices.
- Make `workspace/print_tool` resolve pid/session paths at call time instead of import time.

## Note on `tests/run_tests.py`

`test_topsailai_init_customize_for_llm.py` and `test_topsailai_logger_base_logger.py` fail under
`python tests/run_tests.py` with `ModuleNotFoundError: No module named 'topsailai'` because their
subprocesses do not inherit an importable path; both pass with `PYTHONPATH=/TopsailAI/src`.
Environment/runner concern, unrelated to product code.

## Status update: `tests/run_tests.py` PYTHONPATH part - FIXED (2026-08-27)

### What was changed

- `tests/run_tests.py` gained two pure, unit-testable helpers:
  - `resolve_src_root(start_dir=None, package_name=None)`: walks up from the script location
    (`Path(__file__).resolve().parents`) until it finds `<package>/__init__.py`, falling back to
    the parent of the script folder. No absolute path is hardcoded, so any checkout layout works.
  - `build_child_env(base_env=None, src_root=None)`: copies the caller environment (never mutates
    it), prepends the resolved source root to `PYTHONPATH` using `os.pathsep`, and drops duplicate
    or already-present entries (compared after `normpath`/`normcase`).
- The pytest child process is now started with `env=build_child_env()`. Everything else in the
  runner (report path, per-file timeout, retries, worker pool, status classification, report order
  restoration) is unchanged.

### Why it fixes the failures

The runner executes every test file with `cwd` set to the unit-test directory using the project
virtualenv interpreter, so the source root is not on the child's default import path. Tests that
shell out (`python -c "import topsailai ..."`) therefore failed with
`ModuleNotFoundError: No module named 'topsailai'`. Prepending the source root to `PYTHONPATH`
restores importability without touching the parent process environment.

### Verification

- `python tests/run_tests.py tests/unit/test_topsailai_init_customize_for_llm.py
  tests/unit/test_topsailai_logger_base_logger.py tests/unit/test_topsailai_tests_run_tests.py`
  -> `COMPLETE: Total=3, Passed=3, Failed=0` (both previously failing files now pass).
- New unit tests: `tests/unit/test_topsailai_tests_run_tests.py` (source-root discovery, PYTHONPATH
  prepend order, inherited-entry preservation, de-duplication, missing/empty `PYTHONPATH`,
  no in-place mutation of the base mapping or of `os.environ`, and that `run_test()` passes the
  built environment plus `cwd` to the subprocess).
- Full suite through the project runner: `python tests/run_tests.py`
  -> `COMPLETE: Total=203, Passed=203, Failed=0`.

### Still pending in this issue

The second problem recorded above is NOT addressed by this change and keeps this issue open:
`tests/unit/test_topsailai_ai_base_prompt_base.py` purges every `topsailai*` entry from
`sys.modules`, which makes `tests/unit/test_topsailai_workspace_print_tool.py` fail with 9 errors
when both modules run in a single pytest process. It requires its own logical change (scoped
save/restore fixture, and/or resolving pid/session paths at call time in `workspace/print_tool`).

## Status update: sys.modules cross-file pollution - FIXED (2026-08-27)

### Root cause

Four unit-test files deleted `sys.modules` entries by namespace prefix
(`k.startswith("topsailai")`) or deleted `topsailai.ai_base.prompt_base` directly. Sibling
modules bind topsailai symbols at import time and patch them by full dotted path, so after
such a purge `@patch("topsailai.workspace.print_tool.token_module.count_tokens")` resolves
against a newly re-imported module object while the test still calls the previously bound
function: mocks report "Called 0 times", and module level path constants keep a stale pid,
which raises `FileNotFoundError` on the session stdout file.

The purge was unnecessary. `StepCallBase.__init__` (`ai_base/tool_call.py`) and
`ThresholdContextHistory.__init__` (`ai_base/prompt_base.py`) read their environment
variables at instance construction, not at import time, so no observed behavior depended on
re-importing the module. All existing environment save/restore pairs in the affected
`setUp`/`tearDown` methods were therefore kept unchanged.

### Fix

Removed every purge site and documented the reason in place:
`test_topsailai_ai_base_prompt_base.py` (1 site), `test_topsailai_ai_base_tool_call.py`
(5 sites), `test_topsailai_ai_base_agent_tool.py` (8 sites),
`test_topsailai_ai_base_prompt_base_threshold.py` (2 blanket plus 5 targeted deletions).
The now unused `import sys` was dropped from those four files.

Two related isolation leaks were fixed in the same logical change:
`test_topsailai_utils_print_tool.py` now snapshots and restores the module level
`print_tool.g_flag_print_step` (9 enable calls versus 2 disable calls, previously never
restored; the environment variable itself was already saved and restored there), and
`test_topsailai_tests_run_tests.py` builds its PYTHONPATH fixture with `os.pathsep` instead
of a hardcoded `:` separator.

### Rejected approach

`unittest.mock.patch.dict(sys.modules, {}, clear=[...])` was tried first because it pairs
save and restore automatically. It is unsafe here: it also removes every module imported
while the context is active, including standard library modules, which broke pytest session
teardown with `KeyError: 'warnings'`.

### Evidence

Before: each polluter paired with `test_topsailai_workspace_print_tool.py` in one pytest
process produced the same 9 failures (9 failed/125 passed, 9/80, 9/88, 9/86); the reverse
order passed 134 tests, which shows the pollution is one directional.

After: the same four pairs pass (134, 89, 97 and 95 passed). A combined run of the four
polluters with the fifteen files that import topsailai path constants passes in both orders
(508 passed) when PYTHONPATH provides the source root. Single file results are unchanged
(prompt_base 61, print_tool 57 and 73, tool_call 16, threshold 24, agent_tool 22,
run_tests 15). The project runner reports Total=203, Passed=203, Failed=0.

### Why the runner suite never exposed this

`tests/run_tests.py` launches every test file in its own subprocess, so the leak cannot
cross file boundaries there; it is observable only when several files share one pytest
process.

Separately, twelve tests in `test_topsailai_logger_base_logger.py` fail under a bare
`python -m pytest` run because they spawn `python -c` subprocesses without an inherited
PYTHONPATH. That failing set is identical with and without the polluters present, so it is
an unrelated pre-existing condition and is not addressed by this change; it needs its own
issue.
