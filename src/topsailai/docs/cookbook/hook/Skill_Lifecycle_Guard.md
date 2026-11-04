---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
references:
  - skill_hub/skill_hook.py
  - tools/skill_tool.py
  - utils/module_tool.py
  - docs/cookbook/README.md
  - docs/cookbook/hook/External_Tool_Execution_Audit.md
---

# Skill Lifecycle Guard

## Why This Exists

A release gate skill decides whether a tag may ship. Compliance wants a durable record of every gate execution: which skill folder ran, with which arguments, whether the session was locked or refreshed, and what exit code the script returned. The record is reviewed after an incident, long after the agent's terminal output is gone, so it must live in an external system with its own retention policy.

The skill lifecycle hook is the natural extension point. `call_skill` already owns the whole execution: it resolves the folder, normalizes the command, decides whether to lock the session, runs the script, and decides whether to request a refresh. A hook module registered through `TOPSAILAI_HOOK_MODULE_SKILLS` observes those exact phases, and the skill script itself stays unaware that auditing exists.

| Aspect | This recipe |
|---|---|
| Extension point | `TOPSAILAI_HOOK_MODULE_SKILLS` |
| Extension shape | A folder of Python modules exporting `HOOKS` |
| Observed phases | Before the script starts, after the script returns |
| External system | A bounded JSONL compliance ledger |
| Failure isolation | A raising hook is logged; the skill still runs |
| Bounded growth | The ledger keeps the most recent 500 records |

## Quick Start

Point the hook variable at the example folder and give the ledger an absolute path:

```bash
export TOPSAILAI_HOOK_MODULE_SKILLS=/TopsailAI/src/topsailai/docs/cookbook/hook/examples/skill_guard
export TOPSAILAI_COOKBOOK_SKILL_LEDGER_FILE=/tmp/cookbook_skill_ledger.jsonl
```

Run the release gate skill against a clean repository:

```bash
uv run python -c "
from topsailai.tools.skill_tool import call_skill
print('RESULT:', call_skill(
    skill_folder='/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check',
    script_path='scripts/check_tree.py',
    script_parameters=['/tmp/cookbook_skill_repo', 'v9.9.9'],
))
"
```

The skill returns its verdict:

```text
RESULT: (0, 'release gate for tag v9.9.9\nbranch: master\nhead: fe720ec\nupstream: origin/master\nuntracked files: 0\nverdict: READY', '')
```

The ledger now holds two records, one per observed phase:

```json
{"at": "2026-11-04T18:04:41+08:00", "cmd": ["/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check/scripts/check_tree.py", "/tmp/cookbook_skill_repo", "v9.9.9"], "lock_session": false, "phase": "before", "refresh_session": false, "skill_folder": "/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check"}
{"at": "2026-11-04T18:04:41+08:00", "cmd": ["/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check/scripts/check_tree.py", "/tmp/cookbook_skill_repo", "v9.9.9"], "exit_code": 0, "phase": "after", "skill_folder": "/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check"}
```

A blocked gate is recorded the same way, with the real exit code:

```text
RESULT: (1, 'release gate for tag v9.9.9\nbranch: master\nhead: fe720ec\nupstream: origin/master\nuntracked files: 0\nverdict: BLOCKED\ntracked files modified: 1\n   M README.md', '')
```

```json
{"at": "2026-11-04T18:05:33+08:00", "cmd": ["/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check/scripts/check_tree.py", "/tmp/cookbook_skill_repo", "v9.9.9"], "lock_session": false, "phase": "before", "refresh_session": false, "skill_folder": "/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check"}
{"at": "2026-11-04T18:05:33+08:00", "cmd": ["/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check/scripts/check_tree.py", "/tmp/cookbook_skill_repo", "v9.9.9"], "exit_code": 1, "phase": "after", "skill_folder": "/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check"}
```

## Folder Layout

```text
docs/cookbook/hook/examples/skill_guard/
  guard.py
```

One module is enough. `get_external_function_map` imports every direct child module of the configured folder and merges its `HOOKS` mapping, so a folder may hold several modules when the hooks belong to different concerns. Each merged key is prefixed with its module name, which is why the log messages below read `guard.handle_before_call_skill`.

## Hook Contract

`SkillHookHandler` passes itself to every matching hook. The fields a guard needs:

| Field | Type | Meaning |
|---|---|---|
| `skill_folder` | `str` | The skill folder being executed |
| `cmd_list` | `list[str]` | The normalized command list, executable first |
| `need_lock_session` | `bool` | Whether `call_skill` will lock the session |
| `need_refresh_session` | `bool` | Whether `call_skill` will request a session refresh |
| `data_agent_refresh_session.tool_result` | `tuple` | `(exit_code, stdout, stderr)` after the script returns |

`handle_before_call_skill` runs after the lock decision and before the script starts. `handle_after_call_skill` runs after the script returns and after `tool_result` is assigned, but before the refresh decision is acted on.

The registry key must be a bare function name. The loader prefixes the module name, so writing `guard.handle_before_call_skill` inside `HOOKS` produces a key that never matches.

## Example Hook

```python
#!/usr/bin/env python3
"""Record every skill execution into a compliance ledger.

Scenario: a platform team lets the agent run release-check skills against
production. Compliance requires an auditable record of which skill ran, with
which arguments, and whether it succeeded, because the ledger is reviewed after
an incident and the agent's own terminal output is gone by then. The ledger is
an external system with its own retention, so the skill tool must not embed a
writer for it. This Hook module observes the skill lifecycle and appends one
bounded record per execution.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

LEDGER_ENV = "TOPSAILAI_COOKBOOK_SKILL_LEDGER_FILE"
MAX_RECORDS = 500


def _ledger_path() -> Path:
    """Return the absolute ledger path selected by the operator.

    Returns:
        The ledger file path.

    Raises:
        ValueError: When the variable is unset or not absolute.
    """
    raw = os.getenv(LEDGER_ENV, "").strip()
    if not raw or not os.path.isabs(raw):
        raise ValueError(f"{LEDGER_ENV} must name an absolute file path")
    return Path(raw)


def _read_records(path: Path) -> list[dict]:
    """Load existing ledger records, tolerating a missing or broken file.

    Args:
        path: The ledger file path.

    Returns:
        The stored records, or an empty list when the file cannot be used.
    """
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _append(record: dict) -> None:
    """Append one record to the bounded ledger, replacing it atomically.

    Args:
        record: The ledger entry to store.
    """
    path = _ledger_path()
    records = _read_records(path)
    records.append(record)
    records = records[-MAX_RECORDS:]
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )
    temporary.replace(path)


def _now() -> str:
    """Return the current local time as an ISO-8601 string.

    Returns:
        The timestamp with a timezone offset.
    """
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def handle_before_call_skill(handler) -> None:
    """Record the intent to run a skill before the script starts.

    Args:
        handler: The skill hook handler exposing the folder and command list.
    """
    _append(
        {
            "phase": "before",
            "at": _now(),
            "skill_folder": handler.skill_folder,
            "cmd": list(handler.cmd_list),
            "lock_session": bool(handler.need_lock_session),
            "refresh_session": bool(handler.need_refresh_session),
        }
    )


def handle_after_call_skill(handler) -> None:
    """Record the outcome of a skill run after the script finished.

    Args:
        handler: The skill hook handler exposing the tool result.
    """
    result = handler.data_agent_refresh_session.tool_result
    code = None
    if isinstance(result, tuple) and result:
        code = result[0]
    _append(
        {
            "phase": "after",
            "at": _now(),
            "skill_folder": handler.skill_folder,
            "cmd": list(handler.cmd_list),
            "exit_code": code,
        }
    )


HOOKS = {
    "handle_before_call_skill": handle_before_call_skill,
    "handle_after_call_skill": handle_after_call_skill,
}
```

## Recording The Session Flags

`need_lock_session` and `need_refresh_session` are resolved from two more variables, matched against the skill folder by `is_matched_skill`. Setting both to the skill folder basename records `true`:

```bash
export TOPSAILAI_SESSION_LOCK_ON_SKILLS=release_check
export TOPSAILAI_SESSION_REFRESH_ON_SKILLS=release_check
```

```json
{"at": "2026-11-04T18:05:26+08:00", "cmd": ["/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check/scripts/check_tree.py", "/tmp/cookbook_skill_repo", "v9.9.9"], "lock_session": true, "phase": "before", "refresh_session": true, "skill_folder": "/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check"}
```

`*` matches every skill. The match rule is `startswith` or `endswith` on the folder path, so a basename is enough.

## Failure Path

Remove the ledger variable and run the same skill:

```bash
unset TOPSAILAI_COOKBOOK_SKILL_LEDGER_FILE
```

The skill still runs and still returns its verdict:

```text
RESULT: (0, 'release gate for tag v9.9.9\nbranch: master\nhead: fe720ec\nupstream: origin/master\nuntracked files: 0\nverdict: READY', '')
```

The hook failure is logged and isolated. It does not appear on stdout; it is written to the process log:

```text
call hook failed: [guard.handle_before_call_skill] [<function handle_before_call_skill at 0x7f1f991d0fe0>], TOPSAILAI_COOKBOOK_SKILL_LEDGER_FILE must name an absolute file path (/TopsailAI/src/topsailai/skill_hub/skill_hook.py:145)
call hook failed: [guard.handle_after_call_skill] [<function handle_after_call_skill at 0x7f1f991d1080>], TOPSAILAI_COOKBOOK_SKILL_LEDGER_FILE must name an absolute file path (/TopsailAI/src/topsailai/skill_hub/skill_hook.py:145)
```

A relative ledger path produces the same message, because the guard rejects both cases with one check:

```bash
export TOPSAILAI_COOKBOOK_SKILL_LEDGER_FILE=relative/ledger.jsonl
```

```text
call hook failed: [guard.handle_before_call_skill] [<function handle_before_call_skill at 0x7fa5bc540fe0>], TOPSAILAI_COOKBOOK_SKILL_LEDGER_FILE must name an absolute file path (/TopsailAI/src/topsailai/skill_hub/skill_hook.py:145)
```

## Rejected Inputs

| Input | Observed result |
|---|---|
| `TOPSAILAI_HOOK_MODULE_SKILLS` unset | No ledger file; skill returns `verdict: READY` |
| Ledger variable unset | `call hook failed ... must name an absolute file path`; skill returns `verdict: READY` |
| Relative ledger path | Same message; skill returns `verdict: READY` |
| Hook folder whose name starts with `.` | `TypeError: 'NoneType' object is not iterable`; the skill call fails before the script starts |
| Skill script exceeds its timeout | Ledger holds only the `before` record; `handle_after_call_skill` never runs |
| `timeout=1` with no timeout map | The argument is raised to `600`; the script completes and both records are written |
| Changing `TOPSAILAI_HOOK_MODULE_SKILLS` after the first load | Previously loaded hooks stay; a restart is required |

The timeout case is worth showing in full, because it silently produces an unbalanced ledger:

```bash
export TOPSAILAI_CALL_SKILL_TIMEOUT_MAP="slow_skill=1"
```

```text
RESULT: (1, '', 'Skill script timed out after 1s. Increase the timeout argument or optimize the script.')
```

```json
{"at": "2026-11-04T18:06:05+08:00", "cmd": ["/tmp/slow_skill/scripts/slow.py"], "lock_session": false, "phase": "before", "refresh_session": false, "skill_folder": "/tmp/slow_skill"}
```

One record only. `call_skill` returns from the `except subprocess.TimeoutExpired` branch before assigning `tool_result` and before calling `handle_after_call_skill`.

## Loader Behavior

| Aspect | Behavior |
|---|---|
| Variable | `TOPSAILAI_HOOK_MODULE_SKILLS` |
| Separator | `;` and `,` both accepted; `get_list_str` is called with `separator=None` |
| Order | Not guaranteed; paths are collected through a `set` |
| Load timing | First non-empty load; the result is cached in `g_hooks` for the process lifetime |
| Module discovery | Every direct child module of each folder is imported |
| Registry key | `HOOKS` keys must be bare function names; the loader prefixes the module name |
| Match rule | `hook_name.endswith(key)` |
| Isolation | A raising hook is logged and does not stop the other hooks |
| Folder requirement | The folder must be importable; a leading `.` yields an invalid package name |
| Session flags | `TOPSAILAI_SESSION_LOCK_ON_SKILLS` and `TOPSAILAI_SESSION_REFRESH_ON_SKILLS`, matched by `is_matched_skill` |
| Timeout | `TOPSAILAI_CALL_SKILL_TIMEOUT_MAP`; the caller's `timeout` is raised to the configured value, never lowered |

Two of these rows were confirmed directly. Both separators parse to the same list, and the order is reversed relative to the input:

```text
'/a/b;/c/d' -> ['/c/d', '/a/b']
'/a/b,/c/d' -> ['/c/d', '/a/b']
```

The cache is process-level, so a second read after changing the variable returns the first result:

```text
first: ['extra.handle_before_call_skill']
second: ['extra.handle_before_call_skill']
```

## What This Recipe Cannot Do

- It cannot block a skill. A hook that raises is logged and the skill continues.
- It cannot observe a timed-out skill. `call_skill` returns before `handle_after_call_skill` runs, so the ledger keeps an unmatched `before` record.
- It cannot shorten a skill timeout. `call_skill` applies `max(timeout, get_call_skill_timeout(skill_folder))`, and the default is `600`.
- It cannot reload hooks without a restart. `g_hooks` is process-level and is never invalidated.
- It cannot read the skill's stdout or stderr. Only `tool_result[0]` is exposed to the hook.
- It cannot guarantee hook order across modules. Paths are collected through a `set`.
- It cannot record a skill that fails before the handler is built. A hook folder with an invalid package name raises inside `SkillHookHandler` construction, outside the `try` block that guards script execution.
- It cannot report hook failures to the caller. They are logged at ERROR level in the process log, not returned in the tool result.

## Related Documents

- [Cookbook README](../README.md)
- [External Tool Execution Audit](External_Tool_Execution_Audit.md)
- [Memory Sync To External Index](Memory_Sync_To_External_Index.md)
- [Post Final Answer Notification](Post_Final_Answer_Notification.md)
