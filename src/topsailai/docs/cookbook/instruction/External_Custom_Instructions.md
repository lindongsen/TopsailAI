---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
---

# External Custom Instructions

How to load your own `/` slash instructions from an external folder, the same way
`TOPSAILAI_PLUGIN_TOOLS` loads external tools.

## Purpose

Built-in instructions (`/ctx.history`, `/env.get`, `/agent.tokens`, ...) live inside
`workspace/plugin_instruction/`. This cookbook shows how to keep your own instructions
in a separate folder outside the package and have the agent register them at startup.

The mechanism is already implemented; no source change is required.

| Aspect | Tools | Instructions |
|---|---|---|
| Environment variable | `TOPSAILAI_PLUGIN_TOOLS` | `TOPSAILAI_PLUGIN_INSTRUCTIONS` |
| Loader entry | `tools/base/common.py` `expand_plugin_tools()` | `workspace/plugin_instruction/base/init.py` `expand_plugin_instructions()` |
| Shared implementation | `utils/module_tool.py` `get_external_function_map()` | same function |
| Registry variable | `TOOLS` | `INSTRUCTIONS` |
| Name separator | `-` (`cmd_tool-exec_cmd`) | `.` (`session_audit.stats`) |

## Quick Start

```bash
export PYTHONPATH=/TopsailAI/src/topsailai
export TOPSAILAI_PLUGIN_INSTRUCTIONS=/TopsailAI/src/topsailai/docs/cookbook/instruction/examples/my_ops

uv run python cli/topsailai_agent_call_instruction.py -i '/session_audit.stats' -p '3'
```

Output on a host with recorded sessions:

```text
sessions: 914
status: completed=786, interrupted=118, running=9, error=1
model: gpt-5.6-luna=457, gpt-6.1-sol=209, DeepSeek-V4-Flash-Preview=183, gpt-6-luna=64, topsailai-team-values=1
recent (limit=3):
   status=running name=- model=DeepSeek-V4-Flash-Preview
  20261027152208 status=running name=统一Agent管理方案 model=gpt-6.1-sol
  wa-440a09e9fb4a status=running name=Codex Gateway 400 Error model=gpt-6-luna
```

The same instructions are available inside an interactive agent session, and `/help`
lists them with their docstrings:

```text
  /session_audit.stats
    - stats,
        Summarize the sessions recorded on this host.

        Args:
            limit: How many recent sessions to list, as a decimal string. Capped at 20.

        Returns:
            Status and model counts, then the most recent sessions, or an error message.

  /session_audit.events
    - events,
        Count the recorded events of one session.
```

## Folder Layout

```text
docs/cookbook/instruction/examples/my_ops/
├── session_audit.py   # dict form  -> /session_audit.stats, /session_audit.events
└── env_audit.py       # list form  -> /env_audit.dump, /env_audit.check
```

Rules that matter:

- The folder is the plugin root. Each **direct child `.py` file** is one module.
- `__init__.py` is **not required**; it is also harmless if present.
- Sub-folders are **not** scanned. `my_ops/sub/deep.py` is never loaded.
- The folder path must be **absolute** and must **not** end with `/`.

## The `INSTRUCTIONS` Contract

Every module exports a variable named `INSTRUCTIONS`. Two shapes are accepted.

### Dict form — you choose the action name

```python
INSTRUCTIONS = {
    "stats": stats,
    "events": events,
}
```

Registered names: `/session_audit.stats`, `/session_audit.events`.

### List form — the function name is the action name

```python
INSTRUCTIONS = [dump, check]
```

Registered names: `/env_audit.dump`, `/env_audit.check`.

A module without `INSTRUCTIONS` is skipped silently. Any other type prints
`BUG? module=..., values=...` and is skipped.

## Naming Rule

The registered command is always `{module_file_name}.{action_name}`:

| File | `INSTRUCTIONS` | Command |
|---|---|---|
| `session_audit.py` | `{"stats": stats}` | `/session_audit.stats` |
| `session_audit.py` | `{"audit": audit}` | `/session_audit.audit` |
| `env_audit.py` | `[dump]` | `/env_audit.dump` |

There is no automatic short alias. The only built-in alias in the codebase is
`git.git` → `/git`, hardcoded in `workspace/plugin_instruction/base/init.py`.
To get a short command, name the module and the action identically, or register an
alias yourself.

## Example: `session_audit.py`

This is the dict form. It reads the real session metadata files under
`FOLDER_WORKSPACE_TASK` and prints a bounded summary, which is exactly the kind of
output you want on screen but do not want to spend LLM context on.

```python
"""Session audit helpers exposed as /session_audit.* slash instructions."""

# Dict form: the key is the action name, so this module registers
# /session_audit.stats and /session_audit.events.
#
# Scenario: a session misbehaved and you want to know what ran on this host.
# Dumping the raw metadata and event files into the LLM context is expensive and
# usually truncated, so both actions read the real files under
# FOLDER_WORKSPACE_TASK and print a bounded summary for you instead.

import json
from collections import Counter
from pathlib import Path

from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK

MAX_ITEMS = 20


def _meta_files() -> list[Path]:
    """Return the session metadata files, newest first.

    Returns:
        The metadata paths sorted by modification time, newest first. A file
        that disappears between listing and stat is skipped.
    """
    folder = Path(FOLDER_WORKSPACE_TASK)
    if not folder.is_dir():
        return []

    found = []
    for path in folder.glob("*.session.meta"):
        try:
            found.append((path.stat().st_mtime, path))
        except OSError:
            continue
    found.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in found]


def _load_meta(path: Path) -> dict:
    """Load one metadata file, tolerating a partially written record.

    Args:
        path: The metadata file path.

    Returns:
        The decoded record, or an empty mapping when it cannot be read.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _parse_limit(limit: str) -> int | None:
    """Convert the limit argument, which always arrives as a string.

    Args:
        limit: A decimal string.

    Returns:
        The bounded positive limit, or None when the value is invalid.
    """
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return min(value, MAX_ITEMS)


def stats(limit: str = "10") -> str:
    """Summarize the sessions recorded on this host.

    Args:
        limit: How many recent sessions to list, as a decimal string. Capped at 20.

    Returns:
        Status and model counts, then the most recent sessions, or an error message.
    """
    shown = _parse_limit(limit)
    if shown is None:
        return "error: limit must be a positive integer"

    files = _meta_files()
    if not files:
        return f"no session metadata under {FOLDER_WORKSPACE_TASK}"

    records = [(path, _load_meta(path)) for path in files]
    statuses = Counter(rec.get("status", "unknown") for _, rec in records)
    models = Counter(rec.get("model_name", "unknown") for _, rec in records)

    lines = [f"sessions: {len(records)}"]
    lines.append("status: " + ", ".join(f"{k}={v}" for k, v in statuses.most_common()))
    lines.append("model: " + ", ".join(f"{k}={v}" for k, v in models.most_common()))
    lines.append(f"recent (limit={shown}):")
    for path, rec in records[:shown]:
        lines.append(
            f"  {rec.get('session_id', path.stem)}"
            f" status={rec.get('status', 'unknown')}"
            f" name={rec.get('session_name') or '-'}"
            f" model={rec.get('model_name', 'unknown')}"
        )
    return "\n".join(lines)


def events(session_id: str = "", limit: str = "10") -> str:
    """Count the recorded events of one session.

    Args:
        session_id: The session id to inspect. Empty means the newest session.
        limit: How many event types to list, as a decimal string. Capped at 20.

    Returns:
        The event type counts, or an error message.
    """
    shown = _parse_limit(limit)
    if shown is None:
        return "error: limit must be a positive integer"

    files = _meta_files()
    if not files:
        return f"no session metadata under {FOLDER_WORKSPACE_TASK}"

    target = None
    for path in files:
        record = _load_meta(path)
        if not session_id or record.get("session_id") == session_id:
            target = (path, record)
            break
    if target is None:
        return f"no session found for id={session_id}"

    path, record = target
    events_name = (record.get("files") or {}).get("events", "")
    if not events_name:
        return f"session {record.get('session_id', path.stem)} has no events file recorded"

    events_path = Path(FOLDER_WORKSPACE_TASK) / events_name
    if not events_path.is_file():
        return f"events file missing: {events_path}"

    counts = Counter()
    total = 0
    try:
        with events_path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    counts[json.loads(line).get("event_type", "unknown")] += 1
                except json.JSONDecodeError:
                    counts["<unparsed>"] += 1
    except OSError as exc:
        return f"error: {exc}"

    lines = [f"session: {record.get('session_id', path.stem)} events={total}"]
    for name, count in counts.most_common(shown):
        lines.append(f"  {name}={count}")
    return "\n".join(lines)


INSTRUCTIONS = {
    "stats": stats,
    "events": events,
}
```

Real output of `/session_audit.events 20261020173453 3`:

```text
session: 20261020173453 events=23
  llm.response.raw=8
  tool_call.start=8
  tool_call.end=7
```

Every function **must have a docstring**. The docstring becomes the `/help` text; a
function without one raises `ValueError: HookFunc requires a docstring on '...'` while
the registry is built, which aborts agent startup.

## Example: `env_audit.py`

This is the list form. It reads the real process environment, masks values whose names
match the project's own `PRINT_STEP_SENSITIVE_ARG_KEYS` list, and prints the result.

```python
"""Environment audit helpers exposed as /env_audit.* slash instructions."""

# List form: the action name is the function name, so this module registers
# /env_audit.dump and /env_audit.check.
#
# Scenario: the agent behaves differently than expected and you suspect a stray
# TOPSAILAI_* variable. Printing the whole environment into the LLM context would
# leak credentials, so these actions read the real process environment, mask
# values whose names match the project's own sensitive-key list, and print the
# result for you instead.

import os

from topsailai.utils.print_tool import PRINT_STEP_SENSITIVE_ARG_KEYS

PREFIX = "TOPSAILAI_"
MASK = "***"


def _is_sensitive(name: str) -> bool:
    """Report whether a variable name looks like it carries a credential.

    Args:
        name: The environment variable name.

    Returns:
        True when the lowered name contains any sensitive keyword.
    """
    lowered = name.lower()
    return any(word in lowered for word in PRINT_STEP_SENSITIVE_ARG_KEYS)


def _topsailai_vars() -> list[tuple[str, str]]:
    """Collect the TOPSAILAI_* variables of this process.

    Returns:
        Sorted name/value pairs, with sensitive values already masked.
    """
    pairs = []
    for name in sorted(os.environ):
        if not name.startswith(PREFIX):
            continue
        value = os.environ[name]
        pairs.append((name, MASK if _is_sensitive(name) else value))
    return pairs


def dump(prefix: str = "") -> str:
    """Print the TOPSAILAI_* variables of this process with secrets masked.

    Args:
        prefix: Optional extra name filter applied after the TOPSAILAI_ prefix.

    Returns:
        One name=value line per variable, or a message when nothing matches.
    """
    pairs = _topsailai_vars()
    if prefix:
        pairs = [(name, value) for name, value in pairs if prefix in name]
    if not pairs:
        return f"no {PREFIX}* variable matches prefix={prefix!r}"

    lines = [f"{PREFIX}* variables: {len(pairs)}"]
    lines.extend(f"  {name}={value}" for name, value in pairs)
    return "\n".join(lines)


def check(name: str = "") -> str:
    """Report whether one variable is set, without revealing its value.

    Args:
        name: The exact variable name to inspect.

    Returns:
        The set/unset state, the value length, and whether it is masked.
    """
    if not name:
        return "Usage: /env_audit.check <NAME>"

    if name not in os.environ:
        return f"{name}: unset"

    value = os.environ[name]
    sensitive = _is_sensitive(name)
    shown = MASK if sensitive else (value if value else "<empty>")
    return f"{name}: set len={len(value)} sensitive={sensitive} value={shown}"


INSTRUCTIONS = [dump, check]
```

Real output with `MY_OPS_TOKEN=supersecret123` exported:

```text
MY_OPS_TOKEN: set len=14 sensitive=True value=***
TOPSAILAI_AGENT_NAME: set len=9 sensitive=False value=TopsailAI
NOPE_XYZ: unset
```

The masking is substring-based, so it also hides harmless names that merely contain a
keyword: `TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD` is printed as `***` because
its name contains `token`. That is the project's own convention, not a bug in this
example, and it is the safe direction to err in.

## Passing Arguments

`call_hook` accepts four parameter forms:

| Form | Example | Result |
|---|---|---|
| JSON object | `-p '{"session_id":"20261020173453","limit":"3"}'` | keyword arguments |
| `key=value` pairs | `-p 'session_id=20261020173453;limit=3'` | keyword arguments |
| Space-separated | `-p '20261020173453 3'` | positional arguments |
| Single token | `-p '3'` | one positional argument |

`key=value` pairs are split on `;` (not on spaces), so `'session_id=x limit=3'` is
parsed as one key `session_id` with value `x limit=3` and will not match a
two-parameter signature.

Positional order follows the function signature, which is easy to get wrong.
`/session_audit.events` takes `session_id` first and `limit` second, so `-p '5'` is
read as `session_id="5"` and answers `no session found for id=5` rather than listing
five event types. Use the `key=value` form when you mean the second parameter:

```bash
uv run python cli/topsailai_agent_call_instruction.py -i '/session_audit.events' -p 'limit=2'
```

## Multiple Folders

Separate folders with `;`:

```bash
export TOPSAILAI_PLUGIN_INSTRUCTIONS="/opt/ops/instructions;/opt/team/instructions"
```

Empty entries and a trailing `;` are tolerated. Only `;` works — a comma-separated
value is treated as one invalid path.

If two folders define the same module name, the **last** folder wins.

## Verifying Without an Agent Session

`topsailai_agent_call_instruction` runs one instruction and prints its real output:

```bash
uv run python cli/topsailai_agent_call_instruction.py -i '/session_audit.stats' -p '3'
uv run python cli/topsailai_agent_call_instruction.py -i '/env_audit.check' -p 'TOPSAILAI_AGENT_NAME'
uv run python cli/topsailai_agent_call_instruction.py -i '/help session_audit'
```

## Requirements and Limitations

| Topic | Behavior |
|---|---|
| Absolute path | **Required.** A relative path fails with `TypeError: 'NoneType' object is not iterable`. |
| Trailing slash | **Rejected.** `/path/my_ops/` fails with `AssertionError: no found pkg_path for this path`, or `TypeError: 'NoneType' object is not iterable` when the path is inside the project tree. |
| Single `.py` file | **Not supported.** Pass the containing folder instead. |
| Sub-folders | **Not scanned.** Only direct child modules are loaded. |
| `__init__.py` | Not required; optional. |
| Separator | `;` only. |
| Docstring | **Mandatory** on every registered function. |
| Dotted import path | Also accepted, e.g. `docs.cookbook.instruction.examples.my_ops`, when the package is importable. |
| Path equal to a `sys.path` entry | Silently loads **nothing** (no error). Point at the plugin folder itself, not at its parent. |
| Duplicate module names | Last folder in the list wins. |
| Built-in collision | A plugin key silently **overrides** the built-in of the same name; other built-ins in that module stay intact. |
| Enable/disable filter | **None.** There is no `TOPSAILAI_DISABLED_INSTRUCTIONS` equivalent. |
| Reload | **None.** The variable is read once when `plugin_instruction.base.init` is imported, so it must be set before the process starts. Changing it later requires a restart. |
| Error isolation | **None.** A bad path, a syntax error, or a missing docstring aborts startup instead of being skipped with a warning. |

## Load Timing

`expand_plugin_instructions()` runs at import time of
`topsailai.workspace.plugin_instruction.base.init`. `HookInstruction.__init__` then
copies the registry into its own `hook_map`.

Consequences:

- Set `TOPSAILAI_PLUGIN_INSTRUCTIONS` **before** the process starts.
- Adding entries to `INSTRUCTIONS` at runtime does not reach an already-created
  `HookInstruction` instance; a newly created instance does see them.

## Related Documents

- `docs/Environment_Variables.md` — `TOPSAILAI_PLUGIN_INSTRUCTIONS` reference.
- `workspace/plugin_instruction/readme.md` — key format and CLI testing workflow.
- `features/feature-plugin-mechanisms.md` — plugin, hook, and event responsibilities.
