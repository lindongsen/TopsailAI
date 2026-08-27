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
