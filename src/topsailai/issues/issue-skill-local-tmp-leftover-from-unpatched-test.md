---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: open
---

# Issue: `skill/local` Accumulates Empty `tmp*` Folders

## Symptom

`{TOPSAILAI_HOME}/skill/local/` accumulated empty folders named `tmp` plus eight
random characters, with permission `0700`. The count grew every time the unit test
suite ran, and nothing ever removed them.

## Reproduction

```text
ls -A /root/.topsailai/skill/local | wc -l          # 0
pytest tests/unit/test_topsailai_skill_hub.py::TestSkillRepoInstallFromLocal
ls -A /root/.topsailai/skill/local | wc -l          # 1
```

Per-file measurement isolated the source: `test_topsailai_skill_hub.py` produced
`+1` per run, while `test_topsailai_skill_hub_skill_repo.py`,
`test_topsailai_skill_hub_skill_tool.py` and
`test_topsailai_workspace_plugin_instruction_skill_repo.py` produced `0`.

## Root Cause

Two independent defects combined.

1. **Test isolation gap.** `TestSkillRepoInstallFromLocal` never patched
   `skill_repo.FOLDER_SKILL`, so `install_from_local()` resolved its destination
   against the real `TOPSAILAI_HOME/skill/local`. The source folder came from
   `tempfile.mkdtemp()`, so the copied folder inherited the `tmpXXXXXXXX` name and
   `0700` permission. The sibling file
   `test_topsailai_skill_hub_skill_repo.py` already patched `FOLDER_SKILL` for every
   case, which is why only this file leaked.
2. **No rollback on validation failure.** Every install path moves content into its
   final destination and only then validates it. On failure it raised `ValueError`
   without removing the destination, leaving an empty or invalid folder behind.

The fingerprint that identifies this combination is: `tmp` prefix, empty content,
`0700` permission. It means an empty source folder was copied and then failed
validation.

## Impact

- Unbounded accumulation of empty folders in the user's home directory.
- No functional impact: `list_skills()` does not recognize these folders as skills.
- `skill/local` is not tracked by git, so the repository was never polluted.
- The same missing rollback existed in `install_from_git`, `install_from_zip` and
  `install_from_url`, reachable by any real failed install, not only by tests.

## Fix

- Added `_rollback_failed_installation(dest_folder)` in `skill_hub/skill_repo.py`.
  It returns immediately when the folder is absent, removes it with `shutil.rmtree`
  and logs a warning on success, and logs an error without masking the original
  exception when removal fails.
- Called it at all four validation-failure branches: `install_from_git`,
  `install_from_zip`, `install_from_url`, `install_from_local`.
- Patched `FOLDER_SKILL` to a temporary root in
  `TestSkillRepoInstallFromLocal.setUp()` and restored it in `tearDown()`.
- Added `test_local_path_without_skill_md_rolls_back_destination` asserting the
  destination does not exist after a failed install.

## Verification

- Five skill-related test files: `270 passed`, and `skill/local` stayed at `0`.
- Probe over both failure paths (`zip`, `local`): `leftover exists = False`.
- A pre-existing valid skill survived a later failed install attempt, so the
  rollback does not delete unrelated content.
- Negative control: removing the `install_from_local` rollback call made the new
  test fail with `Failed installation left a leftover folder: ...`; restoring it
  returned `4 passed`.

## Regression Scope

`tests/unit/test_topsailai_skill_hub.py`,
`tests/unit/test_topsailai_skill_hub_skill_repo.py`,
`tests/unit/test_topsailai_skill_hub_skill_tool.py`,
`tests/unit/test_topsailai_workspace_plugin_instruction_skill_repo.py`,
`tests/unit/test_topsailai_tools_skill_tool.py`.

## Notes

A full `tests/unit` collection currently fails on a duplicate `test_config.py`
module name in `tests/unit/workspace/event_channel/` and
`tests/unit/test_topsailai_tools_jev_tool/`. That is a pre-existing collection
problem unrelated to this issue, so verification used per-file and grouped runs.
