---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Logger unit test hardcoded cwd and missing PYTHONPATH in child process

## Symptom

Running the logger unit test file directly with a bare pytest invocation fails 12 of 43
test cases:

```
python -m pytest --color=no -q tests/unit/test_topsailai_logger_base_logger.py
12 failed, 31 passed
```

Every failure reports the same child-process error, independent of the assertion in the
test body:

```
ModuleNotFoundError: No module named 'topsailai'
```

Failing cases are exactly the ones that call the `_run_in_subprocess` helper:
`test_configure_root_logger_adds_file_handler`,
`test_standard_getlogger_inherits_root_format`,
`test_configure_root_logger_default_is_info`,
`test_configure_root_logger_debug_env`,
`test_configure_root_logger_no_third_party_flood`,
`test_disable_root_logger_config_env_var`,
`test_configure_root_logger_respects_log_level_env_warning`,
`test_configure_root_logger_no_stdout_output`,
`test_configure_root_logger_writes_to_file`,
`test_get_log_folder_fallback_when_import_fails`,
`test_configure_root_logger_disabled_in_subprocess`,
`test_configure_root_logger_adds_file_handler_in_subprocess`.

The same file passes when it is executed through `tests/run_tests.py`, and also passes
when `PYTHONPATH` is exported manually, which is why the defect stayed invisible.

## Root Cause

Two coupled defects in the `_run_in_subprocess` helper in
`tests/unit/test_topsailai_logger_base_logger.py`:

- The working directory was a hardcoded absolute path (`/TopsailAI/src/topsailai`),
  which breaks the project rule that forbids hardcoded file paths and makes the test
  unusable in any other checkout layout.
- The child environment was built with a plain `os.environ.copy()`, so the package root
  was never added to `PYTHONPATH`. Because the child runs `python -c "import topsailai..."`
  with the project folder as cwd, the parent of the package is not on the default import
  path and the import fails.

`tests/run_tests.py` previously masked the second defect: it now prepends the resolved
source root to `PYTHONPATH`, and the child pytest process inherits that value, so the
nested `python -c` process could still import the package.

## Impact

- A developer running the file directly with the documented single-file pytest command
  sees 12 false failures that look like production regressions in the root logger setup.
- The hardcoded path silently pins the test suite to one machine layout.

## Fix

Both defects were fixed inside the test helper only; no production source was changed:

- The working directory is now derived from `__file__`
  (`PROJECT_FOLDER = Path(__file__).resolve().parents[2]`).
- The child environment is obtained from the existing `build_child_env()` helper in
  `tests/run_tests.py`, loaded through `importlib.util.spec_from_file_location` with the
  same convention already used by `tests/unit/test_topsailai_tests_run_tests.py`. The
  runner module is cached under a dedicated module name and `main()` is never executed.

Reusing the runner helper instead of duplicating the logic keeps a single implementation
of the child `PYTHONPATH` construction, which is the project convention for shared
path-resolution code.

## Verification Evidence

Before the fix, bare pytest on the single file:

```
python -m pytest --color=no -q tests/unit/test_topsailai_logger_base_logger.py
12 failed, 31 passed
```

After the fix, same command, no manual `PYTHONPATH`:

```
python -m pytest --color=no -q tests/unit/test_topsailai_logger_base_logger.py
43 passed
```

Additional checks after the fix:

```
python tests/run_tests.py test_topsailai_logger_base_logger.py
COMPLETE: Total=1, Passed=1, Failed=0

python -m pytest --color=no -q tests/unit/test_topsailai_tests_run_tests.py
15 passed

python -m pytest --color=no -q tests/unit/test_topsailai_logger_base_logger.py tests/unit/test_topsailai_workspace_print_tool.py
116 passed

python -m pytest --color=no -q tests/unit/test_topsailai_workspace_print_tool.py tests/unit/test_topsailai_logger_base_logger.py
116 passed

python -m pytest --color=no -q tests/unit/test_topsailai_ai_base_prompt_base.py tests/unit/test_topsailai_logger_base_logger.py
104 passed

python tests/run_tests.py
COMPLETE: Total=203, Passed=203, Failed=0
```

A scan for the hardcoded absolute path in the changed file returns no match.

## Notes

- The combined runs prove the new module-level helper introduces no cross-file
  `sys.modules` pollution with the previously affected files, in either order.
- `tests/run_tests.py` itself was not modified, so its own 15 unit tests stay green.
