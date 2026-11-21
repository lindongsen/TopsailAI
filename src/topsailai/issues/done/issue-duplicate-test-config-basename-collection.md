---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: done
---

# Issue: Duplicate `test_config.py` Basenames Abort Full Unit Collection

## Symptom

`pytest tests/unit` aborted before running a single test:

```text
import file mismatch:
imported module 'test_config' has this __file__ attribute:
  .../tests/unit/test_topsailai_tools_jev_tool/test_config.py
which is not the same as the test file we want to collect:
  .../tests/unit/workspace/event_channel/test_config.py
```

Three files shared the basename `test_config.py`:

- `tests/unit/events/test_config.py`
- `tests/unit/workspace/event_channel/test_config.py`
- `tests/unit/test_topsailai_tools_jev_tool/test_config.py`

## Root Cause

The collision was a symptom of inconsistent packaging, not of duplicate names. Under
pytest's default `prepend` import mode, a test module's name is derived by walking up
the directory tree while `__init__.py` exists.

- `tests/unit/events/` had `__init__.py`, so its file became
  `tests.unit.events.test_config`.
- `tests/unit/workspace/` and `tests/unit/test_topsailai_tools_jev_tool/` had no
  `__init__.py`, so both files fell back to the bare name `test_config` and collided.

Nine directories containing test files were missing the marker while six already had it.

## Impact

- Direct `pytest tests/unit` could not run at all, so the whole unit suite was
  unreachable through the most obvious command.
- The mandated runner `tests/run_tests.py` was unaffected because it spawns one pytest
  process per file, which is why the problem stayed hidden.
- Any future duplicate basename would collide again wherever coverage remained partial.

## Fix

Added `__init__.py` to every directory under `tests/unit` that contains test files and
lacked the marker, matching the existing `tests/unit/__init__.py` convention:

```text
tests/unit/test_topsailai_tools_jev_tool/__init__.py
tests/unit/workspace/__init__.py
tests/unit/workspace/agent/__init__.py
tests/unit/workspace/context/__init__.py
tests/unit/workspace/control_channel/__init__.py
tests/unit/workspace/event_channel/__init__.py
tests/unit/workspace/plugin_instruction/__init__.py
tests/unit/workspace/project_history/__init__.py
tests/unit/workspace/task/__init__.py
```

Each file contains only `# unit tests package`. No test file was renamed, because renaming
fixes one pair and leaves the next duplicate to reappear.

## Verification

- Collection: `14256 collected, 1 error` became `14270 collected, 0 errors`. The 14 extra
  tests were previously unreachable behind the aborted collection.
- Mandated runner on the three formerly colliding files plus a workspace file:
  `4/4 PASS`, `98 passed`.
- Full suite on the fixed tree: `276 failed, 13993 passed, 1 skipped`.
- Full suite at pristine HEAD (colliding file excluded so it could collect):
  `277 failed, 13978 passed, 1 skipped`.
- Failure-set diff: **zero new failures**. The only difference is one test that fails at
  pristine and passes on the fixed tree
  (`test_topsailai_tools_memory_stat.py::TestMemoryStatValidation::test_persistent_unparseable_stat_rebuilds_zero_counts`).
- The remaining 276 failures are pre-existing and reproduce identically at pristine HEAD:
  255 in `test_topsailai_hooks`, 18 in `tests/unit/workspace`, 2 in `test_bdd_entrypoints`,
  1 in `test_topsailai_utils_input_tool`. The last two groups are cross-file pollution that
  only appears in a shared process, consistent with
  `issues/done/issue-unit-test-cross-file-pollution-workspace-print-tool.md`.

## Notes

Pristine attribution used an isolated `git worktree` at the same HEAD with `PYTHONPATH`
forced to that tree, and the imported `topsailai.__file__` was printed to prove resolution
inside the worktree. The worktree was removed after the comparison.

The pre-existing failures are out of scope for this issue and are not caused by the
`__init__.py` change.
