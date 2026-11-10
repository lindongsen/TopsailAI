---
maintainer: AI
author: DawsonLin
---

# Driver never exported the target session project workspace

Status: resolved in working tree.

## Symptom

The session agent driver started its analysis agent without setting
`TOPSAILAI_PROJECT_WORKSPACE` from the target session's stored
`project_workspace`. The agent therefore ran with an empty or inherited
workspace, so the system prompt, skill discovery, workspace lock, and project
history all pointed at the wrong project.

## Root cause

`resolve_project_workspace()` already preferred the stored session value, but it
was used only to render the analysis prompt. Nothing assigned the process
environment variable, and the CLI launches the driver detached with
`cwd=TOPSAILAI_HOME` without that variable.

Assigning the variable alone was also insufficient: `topsailai/tools/skill_tool.py`
calls `reload()` at module import time and scans
`{TOPSAILAI_PROJECT_WORKSPACE}/.topsailai/skills`, and the driver imports
`topsailai.workspace.agent_shell` at module level, which pulls that module in
before any assignment can happen. A probe with a unique skill token showed
`before set: False / after set no reload: False / after reload: True`.

## Fix

Added `apply_project_workspace()` and `restore_project_workspace()` in
`session_agent_driver.py`:

- Resolution order: stored session `project_workspace` -> `TOPSAILAI_PWD` ->
  `os.getcwd()`.
- Writes both `TOPSAILAI_PROJECT_WORKSPACE` and the `TOPSAILAI_PROJECT_FOLDER`
  alias.
- Calls `topsailai.tools.skill_tool.reload()` only when the value changes, and a
  reload failure only warns.
- Applied at driver startup and again before each analysis round; previous
  values are restored on every exit path.

## Verification

- `make test` in `scripts/session_agent_driver`: 202 unit tests and 5 BDD tests
  passed.
- Live check against the real session store: a session with a stored workspace
  produced that exact value in both variables, an unknown session fell back to
  `TOPSAILAI_PWD`, and restore removed the variables again.
