---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: fixed
---

# Issue: Resume loses project_workspace and first attempt fails silently (both fixed)

## Symptom

Two defects were observed while resuming four sessions on 2026-11-14. Both are
now fixed. They are kept in this file because they were observed in the same
resume run, and the Evidence section below is the original observation record.

Defect A (fixed by `e61320e9`): every resumed session recorded an empty
`project_workspace` in its new meta file, while the original meta file for the
same session held the real project path.

Defect B (fixed at the CLI launch boundary): the first resume attempt for two of
the four sessions died after 6 to 8 seconds, was recorded as `interrupted`, and
produced no stdout file at all, so the failure left no diagnostic trace.

## Evidence

Defect A, meta comparison for the same session:

| Session | New meta (resumed) | Original meta |
|---|---|---|
| `wa-c2a6583cd3e3` | `project_workspace = ''` | `/TopsailAI/src/topsailai_connector` |
| `wa-ecd67a6e691e` | `project_workspace = ''` | `/TopsailAI/src/topsailai_agent_cluster` |
| `wa-1fb57b5948b4` | `project_workspace = ''` | `/TopsailAI/src/topsailai_agent_cluster` |
| `wa-a1ad42ea0a3f` | `project_workspace = ''` | `/TopsailAI/src/topsailai` |

Root cause (historical, pre-fix): `workspace/session_meta.py:219` read
`os.getenv("TOPSAILAI_PROJECT_WORKSPACE") or ""`, but the resume launch boundary
never injected that variable. `cli/cli_topsailai/project_scope.py:73` defined
`_LAUNCH_ENV_KEYS = ("TOPSAILAI_PWD", "PWD") + _IDENTITY_ENV_KEYS`, and
`_IDENTITY_ENV_KEYS` at line 70 was only
`("TOPSAILAI_SESSION_ID", "SESSION_ID")`. `TOPSAILAI_PROJECT_WORKSPACE` was absent
from both tuples, so the child process inherited an empty value. See the
Resolution section for the fix.

Confirmed in the live process environment of pid `122064`:
`TOPSAILAI_PROJECT_WORKSPACE=` is present but empty, `TOPSAILAI_PWD` is correct,
and `TOPSAILAI_PROJECT_FOLDER` is not set at all.

Consequence: `workspace/lock_tool.py:149 _resolve_project_workspace` returns
`None` because both `TOPSAILAI_PROJECT_WORKSPACE` and `TOPSAILAI_PROJECT_FOLDER`
are empty or unset, and `:272` then yields `False` and returns, so the
project workspace startup lock is silently skipped for every resumed session.
Other consumers read the same variable: `workspace/project_history/history.py:123`
falls back to `TOPSAILAI_PWD`, and `workspace/plugin_instruction/git.py:57` has no
fallback.

Aggravating factor: the session lock is disabled by default in code, so the
missing workspace is currently masked. `workspace/agent/agent_shell_base.py:568`
reads `TOPSAILAI_ENABLE_SESSION_LOCK` with `default=False`, and
`workspace/session_meta.py:203-204` records the same `False` default. With the
lock off, `ctxm_try_session_lock` is never selected and the empty workspace has no
visible effect. The moment an operator enables the lock, every resumed session
silently loses mutual exclusion, which is the worst failure shape: the defect is
invisible until the protection is turned on.

Defect B, first-attempt failures:

| Session | Failed pid | Lifetime | stdout |
|---|---|---|---|
| `wa-c2a6583cd3e3` | `120691` | 08:26:22 to 08:26:28 (6s) | absent |
| `wa-1fb57b5948b4` | `1029091` | 08:23:28 to 08:23:36 (8s) | absent |

Both were recorded as `interrupted` with a populated `end_ts`, and neither left a
`.session.stdout` file, so there is no record of why the launch failed. The
immediately following retry succeeded in both cases.

## Impact

Defect A (resolved): it silently disabled the project workspace lock on every
resumed session, so two agents could work in the same project without mutual
exclusion. It also degraded project history attribution and any plugin that
resolves the project folder from the environment without a fallback.

Defect B (fixed): it made a failed resume indistinguishable from a session that
never started, and left no evidence to diagnose the cause. The launch boundary
now exports the tee switch, so a worker that dies after startup leaves a stdout
file behind.

## Required Behavior

Defect A (satisfied): the resume launch boundary MUST propagate the project
workspace to the child process, so the new meta file records the same
`project_workspace` as the original meta file for that session.

Defect B (satisfied at the launch boundary): a failed resume attempt MUST leave a
diagnostic artifact. The stdout file MUST be created before or at process start,
so a launch that dies early still records why it died. The failure reason MUST be
recoverable from the retained files. The launch boundary now exports the tee
switch, so a worker that reaches `get_agent_chat()` always writes a stdout file.
A child that dies during import is still uncovered; see "Defect B: remaining
gaps".

## Resolution

### Defect A: resolved

Fixed by commit `e61320e9` ("fix: export project workspace on agent resume",
2026-11-14 12:31:40). The launch boundary now forwards the variable and the meta
writer now resolves it from the persisted session record:

- `cli/cli_topsailai/project_scope.py:77` defines
  `_PROJECT_WORKSPACE_ENV_KEY = "TOPSAILAI_PROJECT_WORKSPACE"`.
- `:80-82` includes that key in `_LAUNCH_ENV_KEYS`, so the child process receives
  it instead of an empty value.
- `:997` sets `os.environ[_PROJECT_WORKSPACE_ENV_KEY] = target_folder` before the
  launch.
- `workspace/session_meta.py:231` now calls
  `resolve_project_workspace(session_id=resolved_session_id)`, which prefers the
  environment and falls back to the persisted session record
  (`workspace/project_workspace.py`), so a resumed session no longer records an
  empty `project_workspace`.

The root cause described in the Evidence section is therefore historical: the
line numbers cited there (`project_scope.py:73`, `:70`, `session_meta.py:219`)
describe the pre-fix code.

### Defect B: fixed at the CLI launch boundary

The root cause is narrower than "the default is off". `cli/topsailai.yaml:286,304`
does set `TOPSAILAI_ENABLE_SESSION_TEE_OUT` to `"1"` for the `/agent` and
`/agent_plan` commands, but a resume never goes through those commands. Resume
enters at `cli/cli_topsailai/core.py:95` `_resume_from_workspace_log`, reaches
`cli/cli_topsailai/project_scope.py:1906` `resume_session_result()`, and starts
the worker through `launch_configured_agent()` (background) or
`launch_agent_driver()` (foreground). Neither exported the variable, which is why
`grep -rn ENABLE_SESSION_TEE_OUT cli/cli_topsailai/ scripts/session_agent_driver/`
returned nothing.

The fix exports the switch at the launch boundary, which is the only layer that
knows a launch is happening. Core defaults are deliberately left untouched so
unrelated agent entry points (subagents, team members, tests, scripts) do not
start writing stdout files.

Changed files, all under `cli/`:

- `cli/cli_topsailai/project_scope.py`: new `_SESSION_TEE_ENV_KEY` constant,
  `_SESSION_TEE_ENV_KEY` added to `_LAUNCH_ENV_KEYS` so snapshot and restore
  cover it, `launch_agent_driver(enable_session_tee=True)` plus the
  `setdefault` call inside `_run_owned_launch`.
- `cli/cli_topsailai/agent_launch.py`: new `_enable_session_tee()` helper,
  `launch_configured_agent(enable_session_tee=True)`,
  `_launch_configured_agent_impl(enable_session_tee=True)`, and the helper called
  after `_prepare_environment` on both the background and foreground paths.

`setdefault` is used rather than assignment so an operator who explicitly
exported `"0"` keeps that value.

Setting `os.environ` is sufficient for all three launch mechanisms: `raw` is a
direct child inheriting the environment, `dtach` inherits the parent
environment, and `tmux` explicitly forwards every `TOPSAILAI_*` key at
`project_scope.py:787-790`.

`_prepare_environment` keeps its original two-parameter signature. An earlier
attempt added a third positional parameter and broke eight existing tests that
replace it with a two-argument double; the tee export was moved into a separate
helper instead.

### Defect B: remaining gaps

Two gaps are NOT closed by this fix and stay open:

- **Import-time crash.** `TeeOutput` is constructed at
  `workspace/agent_shell.py:399-403`, so a child that dies during import
  (`ImportError`, syntax error, missing dependency) still leaves no stdout file.
  Covering that needs the child's stdout redirected at spawn time through the
  existing `child_stdout` parameter, which interacts with the JSON-mode
  "stdout must stay clean" constraint.
- **Default disagreement in core.** `workspace/agent_shell.py:400` and
  `workspace/print_tool.py:171` read `default=False`, while
  `workspace/session_meta.py:194-195` records `default=True` and
  `docs/Environment_Variables.md:65` documents `1`. The meta file therefore
  claims tee output is enabled while the writer treats it as disabled. Fixing
  this requires editing core code and `docs/`, which was out of scope for this
  change.

## Verification

Defect A: verified by reading the current source at the four sites listed above
and confirming commit `e61320e9` exists. A live resume re-check was not performed
in this audit.

Defect B: verified by unit tests. `cli/tests/unit/topsailai/test_session_tee_launch.py`
covers eleven checks: the switch is exported by default, an explicit opt-out
leaves it unset, an operator override is respected, the foreground child and the
background supervisor both receive it, the resume driver child receives it, the
parent environment is restored in both launch paths, and `_LAUNCH_ENV_KEYS`
covers the key. Regression runs: 265 passed across the five launch test files,
139 passed in `test_project_scope.py`, and 4483 passed in the full CLI unit
suite with two pre-existing failures attributed at pristine HEAD `ccd54b39`.

Still pending, as deferred checks:

- A deliberately failing resume leaves a non-empty stdout file containing the
  failure reason. This needs a real agent process and was not executed.
- The three `TOPSAILAI_ENABLE_SESSION_TEE_OUT` defaults agree, or the meta record
  reports the value the writer actually used. Blocked by the `cli/`-only scope.
