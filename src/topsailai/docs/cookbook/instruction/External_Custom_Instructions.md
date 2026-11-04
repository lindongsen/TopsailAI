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
| Name separator | `-` (`cmd_tool-exec_cmd`) | `.` (`deploy.status`) |

## Quick Start

```bash
export PYTHONPATH=/TopsailAI/src/topsailai
export TOPSAILAI_PLUGIN_INSTRUCTIONS=/TopsailAI/src/topsailai/docs/cookbook/instruction/examples/my_ops
export MY_OPS_ENV=prod

uv run python cli/topsailai_agent_call_instruction.py -i '/deploy.status' -p 'checkout'
```

Output:

```text
checkout: running (env=prod)
```

The same instructions are available inside an interactive agent session, and `/help`
lists them:

```text
  /deploy.status
    - status,
        Report the deployment status of one service.

  /deploy.rollback
    - rollback,
        Roll one service back to a revision.
```

## Folder Layout

```text
docs/cookbook/instruction/examples/my_ops/
├── deploy.py     # dict form  -> /deploy.status, /deploy.rollback
└── notes.py      # list form  -> /notes.add, /notes.list_notes
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
    "status": status,
    "rollback": rollback,
}
```

Registered names: `/deploy.status`, `/deploy.rollback`.

### List form — the function name is the action name

```python
INSTRUCTIONS = [add, list_notes]
```

Registered names: `/notes.add`, `/notes.list_notes`.

A module without `INSTRUCTIONS` is skipped silently. Any other type prints
`BUG? module=..., values=...` and is skipped.

## Naming Rule

The registered command is always `{module_file_name}.{action_name}`:

| File | `INSTRUCTIONS` | Command |
|---|---|---|
| `deploy.py` | `{"status": status}` | `/deploy.status` |
| `deploy.py` | `{"deploy": deploy}` | `/deploy.deploy` |
| `notes.py` | `[add]` | `/notes.add` |

There is no automatic short alias. The only built-in alias in the codebase is
`git.git` → `/git`, hardcoded in `workspace/plugin_instruction/base/init.py`.
To get a short command, name the module and the action identically, or register an
alias yourself.

## Example: `deploy.py`

```python
"""Deployment helpers exposed as /deploy.* slash instructions."""

# Dict form: the key is the action name, so this module registers
# /deploy.status and /deploy.rollback.

import os


def status(service: str = "") -> str:
    """Report the deployment status of one service."""
    if not service:
        return "Usage: /deploy.status <service>"
    env = os.getenv("MY_OPS_ENV", "dev")
    return f"{service}: running (env={env})"


def rollback(service: str = "", revision: str = "") -> str:
    """Roll one service back to a revision."""
    if not service or not revision:
        return "Usage: /deploy.rollback <service> <revision>"
    return f"{service}: rolled back to {revision}"


INSTRUCTIONS = {
    "status": status,
    "rollback": rollback,
}
```

Every function **must have a docstring**. The docstring becomes the `/help` text; a
function without one raises `ValueError: HookFunc requires a docstring on '...'` while
the registry is built, which aborts agent startup.

## Example: `notes.py`

```python
"""Note helpers exposed as /notes.* slash instructions."""

# List form: the action name is the function name, so this module registers
# /notes.add and /notes.list_notes.

_NOTES: list[str] = []


def add(text: str = "") -> str:
    """Append one note and report the new total."""
    if not text:
        return "Usage: /notes.add <text>"
    _NOTES.append(text)
    return f"added: {text} (total={len(_NOTES)})"


def list_notes() -> str:
    """List every note added in this process."""
    if not _NOTES:
        return "no notes yet"
    return "\n".join(f"{i}. {n}" for i, n in enumerate(_NOTES, 1))


INSTRUCTIONS = [add, list_notes]
```

Module state lives for the process lifetime, so `/notes.add` followed by
`/notes.list_notes` in the same session sees the accumulated notes.

## Passing Arguments

`call_hook` accepts four parameter forms:

| Form | Example | Result |
|---|---|---|
| JSON object | `-p '{"service":"api","revision":"9"}'` | keyword arguments |
| `key=value` pairs | `-p 'service=api;revision=9'` | keyword arguments |
| Space-separated | `-p 'api 9'` | positional arguments |
| Single token | `-p 'api'` | one positional argument |

`key=value` pairs are split on `;` (not on spaces), so `'service=api revision=9'` is
parsed as one key `service` with value `api revision=9` and will not match a
two-parameter signature.

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
uv run python cli/topsailai_agent_call_instruction.py -i '/deploy.status' -p 'checkout'
uv run python cli/topsailai_agent_call_instruction.py -i '/help deploy'
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
