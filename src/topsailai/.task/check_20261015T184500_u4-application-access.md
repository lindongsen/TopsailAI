---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---
# U4 Application Access Test Checklist

- [x] Maintained changes are limited to the U4 test file and this checklist; U2, U5, U6, and unrelated dirty files were not modified.
- [x] Tests cover ContextVar token restoration, owner/thread checks, copied-context and `asyncio.to_thread()` rejection, explicit rebinding, disabled/closed/unbound behavior, valid and forged unavailable paths, stop/admission races, admitted settlement, cancellation and `KeyboardInterrupt` identity, concurrent application isolation, exact argument forwarding, decorator-provider composition, and exceptional nested restoration.
- [x] Unavailable-path doubles expose registration and Runtime call counters. Sync and async forged declarations plus valid stopped, Scope-closed, and context-mismatch paths assert zero registration and zero Runtime calls.
- [x] Side-effect coverage uses a short `monkeypatch.context()` installed before application construction and guards `os.environ` mapping access, `open`, `os.stat`, `Path.exists`, `Path.stat`, and the imported `configured_executor.HookRuntime` boundary. The claim is limited to those guarded operations during construction, binding, lookup, and unavailable dispatch; it does not claim to prove unrelated transitive I/O.
- [x] Focused application-access command:
  `PYTHONPATH=/TopsailAI/src PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/.tmp/u4-application-access/final5/pycache TMPDIR=/TopsailAI/src/topsailai/.tmp/u4-application-access/final5 COVERAGE_FILE=/TopsailAI/src/topsailai/.tmp/u4-application-access/final5/.coverage pytest -q --color=no -p no:cacheprovider --basetemp=/TopsailAI/src/topsailai/.tmp/u4-application-access/final5/pytest2 tests/unit/test_topsailai_hooks/test_application_access.py`
  Result: **24 passed, 0 failed, 0 skipped**; pytest reported 0.22s; measured elapsed 0.22s; syntax compilation passed separately.
- [x] Focused three-file command:
  `COVERAGE_FILE=/TopsailAI/src/topsailai/.tmp/u4-application-access/final5/.coverage PYTHONPATH=/TopsailAI/src PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/.tmp/u4-application-access/final5/pycache TMPDIR=/TopsailAI/src/topsailai/.tmp/u4-application-access/final5 pytest -q --color=no -p no:cacheprovider --basetemp=/TopsailAI/src/topsailai/.tmp/u4-application-access/final5/pytest tests/unit/test_topsailai_hooks/test_application_access.py tests/unit/test_topsailai_hooks/test_configured_executor.py tests/unit/test_topsailai_hooks/test_hook_point_decorator.py`
  Result: **158 passed, 0 failed, 0 skipped**; pytest reported 1.19s; measured elapsed 1.19s.
- [x] Scoped coverage command:
  `COVERAGE_FILE=/TopsailAI/src/topsailai/.tmp/u4-application-access/final5/.coverage_cov PYTHONPATH=/TopsailAI/src PYTHONPYCACHEPREFIX=/TopsailAI/src/topsailai/.tmp/u4-application-access/final5/pycache_cov TMPDIR=/TopsailAI/src/topsailai/.tmp/u4-application-access/final5 pytest -q --color=no -p no:cacheprovider --basetemp=/TopsailAI/src/topsailai/.tmp/u4-application-access/final5/pytest_cov --cov=topsailai.hooks.application_access --cov-branch --cov-report=term-missing --cov-report=json:/TopsailAI/src/topsailai/.tmp/u4-application-access/final5/coverage.json tests/unit/test_topsailai_hooks/test_application_access.py`
  Result: **24 passed, 0 failed, 0 skipped**; pytest reported 0.50s; measured elapsed 0.50s; statement coverage **100% (97/97)**; branch coverage **100% (28/28)**.
- [x] `python -m py_compile tests/unit/test_topsailai_hooks/test_application_access.py` passed.
- [x] Per-file review, whitespace/no-index checks, and unrelated-change status review completed; no files were staged or committed.
- [x] Line counts: `application_access.py` **168**, `test_application_access.py` **699**, checklist **31**; all maintained code/test files remain below 700 lines.

## Acceptance evidence notes

The final verification used no-color output, disabled pytest cache provider, and task-scoped basetemp, bytecode, temporary directory, coverage data, and coverage JSON under `/TopsailAI/src/topsailai/.tmp/u4-application-access/final5/`. The application-access test guards only the explicitly named environment, filesystem, and imported Runtime-construction boundaries while exercising construction, binding, lookup, and unavailable dispatch.
