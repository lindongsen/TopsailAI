---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# External Custom Tools

How to give the agent a new capability by pointing one environment variable at a folder.

## Why This Exists

A tool is not a command the human types. It is a function the **LLM decides to call**, so the
contract has two readers: the model that must choose it, and the runtime that must dispatch it.
`TOPSAILAI_PLUGIN_TOOLS` lets you add such functions without editing the project, and the loader
reads the same `TOOLS` variable that the built-in tool modules use.

| Aspect | Tools (`TOPSAILAI_PLUGIN_TOOLS`) | Instructions (`TOPSAILAI_PLUGIN_INSTRUCTIONS`) |
|--------|----------------------------------|-----------------------------------------------|
| Who invokes it | The LLM, through a tool call | The human, by typing `/name` |
| Registry variable | `TOOLS` and `TOOLS_INFO` | `INSTRUCTIONS` |
| Name separator | `TOPSAILAI_TOOL_CONN_CHAR`, default `-` | Always `.` |
| Folder separator | `;` and `,` | `;` only |
| Enable/disable filter | Yes, `TOPSAILAI_ENABLED_TOOLS` / `TOPSAILAI_DISABLED_TOOLS` | None |
| Module-level extras | `TOOLS_INFO`, `FLAG_TOOL_ENABLED` | None |
| Loader | `tools/base/common.py:expand_plugin_tools()` | `workspace/plugin_instruction/base/init.py` |

Both loaders share `utils/module_tool.py:get_external_function_map()`, so the folder rules are
identical. The differences above are what this document has to explain.

## Quick Start

```bash
export TOPSAILAI_PLUGIN_TOOLS=/TopsailAI/src/topsailai/docs/cookbook/tool/examples/my_tools
uv run python -c "from topsailai.tools.base.common import TOOLS; print(sorted(k for k in TOOLS if 'inspect' in k))"
```

```text
['db_inspect-query', 'db_inspect-tables', 'log_inspect-scan', 'log_inspect-tail']
```

Four tools are now registered. The agent can call them exactly like `file_tool-read_file`.

## Folder Layout

```text
my_tools/                  <- point TOPSAILAI_PLUGIN_TOOLS here
├── db_inspect.py          <- registers db_inspect-query, db_inspect-tables
└── log_inspect.py         <- registers log_inspect-scan, log_inspect-tail
```

Four rules decide whether a folder loads:

- **Direct children only.** `pkgutil.iter_modules` is not recursive, so `my_tools/sub/deep.py` is
  never imported.
- **No `__init__.py` needed.** The folder is treated as a namespace package.
- **Absolute path, no trailing slash.** A trailing `/` aborts the load.
- **The folder name must be a valid Python identifier.** A hidden folder such as `.tmp/plugins`
  produces the dotted path `.tmp.plugins`, which cannot be imported.

## The `TOOLS` Contract

Each module declares one of two shapes. The shape decides where the action name comes from.

### Dict form: the key is the action name

```python
TOOLS = {
    "query": query,
    "tables": tables,
}
```

Registered as `db_inspect-query` and `db_inspect-tables`.

### List form: the function name is the action name

```python
TOOLS = [scan, tail]
```

Registered as `log_inspect-scan` and `log_inspect-tail`.

Use the dict form when the public name should differ from the Python function name, and the list
form when they should stay identical. A module without a `TOOLS` variable is skipped silently.

## Naming Rule

The registered name is `{module_file_name}{conn_char}{action_name}`.

| Module file | Action | Registered name |
|-------------|--------|-----------------|
| `db_inspect.py` | `"query"` | `db_inspect-query` |
| `db_inspect.py` | `"tables"` | `db_inspect-tables` |
| `log_inspect.py` | `scan` | `log_inspect-scan` |
| `log_inspect.py` | `tail` | `log_inspect-tail` |

The prefix is the **file name**, not a name you choose inside the file. Renaming `db_inspect.py`
to `sqlite.py` silently renames both tools to `sqlite-query` and `sqlite-tables`, which is why the
module names here avoid colliding with the standard library.

`TOPSAILAI_TOOL_CONN_CHAR` replaces the separator, and it must be exactly one character:

```bash
export TOPSAILAI_TOOL_CONN_CHAR=_
```

```text
['db_inspect_query', 'db_inspect_tables', 'log_inspect_scan', 'log_inspect_tail']
```

A two-character value aborts the import with `AssertionError`, because the loader asserts
`len(conn_char) == 1`.

## Example: Read-Only Database Inspection

**Scenario.** An operator points the agent at a local SQLite file and asks what is inside it. The
agent will generate SQL, and a generated `DELETE` must not be able to damage the database. The
connection is therefore opened read-only, and the statement is checked before it runs.

`docs/cookbook/tool/examples/my_tools/db_inspect.py`:

```python
"""Read-only SQLite inspection exposed as db_inspect-query and db_inspect-tables tools."""

# Dict form: the key is the action name, so this module registers
# db_inspect-query and db_inspect-tables.
#
# Scenario: an operator points the agent at a local SQLite file and asks what is
# inside it. The connection is opened read-only, so a generated INSERT/UPDATE
# cannot damage the database.

import sqlite3
from pathlib import Path

MAX_ROWS = 200


def _connect(db: str) -> sqlite3.Connection:
    """Open one SQLite file read-only.

    Args:
        db: Absolute path of the SQLite file.

    Returns:
        A read-only connection.
    """
    path = Path(db).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"no such database: {path}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def query(db: str = "", sql: str = "", limit: str = "50") -> str:
    """Run one read-only SELECT and return the rows as text.

    Args:
        db: Absolute path of the SQLite file.
        sql: A single SELECT statement. Other statements are rejected.
        limit: Maximum rows to return, as a decimal string. Capped at 200.

    Returns:
        A header line, then one pipe-separated line per row, or an error message.
    """
    if not db or not sql:
        return "error: db and sql are required"
    if not sql.lstrip().lower().startswith(("select", "with", "pragma")):
        return "error: only SELECT, WITH and PRAGMA statements are allowed"

    try:
        max_rows = int(limit)
    except (TypeError, ValueError):
        return "error: limit must be an integer"
    if max_rows <= 0:
        return "error: limit must be positive"
    max_rows = min(max_rows, MAX_ROWS)

    try:
        with _connect(db) as conn:
            cursor = conn.execute(sql)
            columns = [item[0] for item in cursor.description or []]
            rows = cursor.fetchmany(max_rows)
    except (sqlite3.Error, OSError) as exc:
        return f"error: {exc}"

    if not columns:
        return "error: statement returned no columns"
    lines = ["|".join(columns)]
    lines.extend("|".join("" if v is None else str(v) for v in row) for row in rows)
    lines.append(f"rows: {len(rows)} (limit={max_rows})")
    return "\n".join(lines)


def tables(db: str = "") -> str:
    """List the tables and views of one SQLite file with their row counts.

    Args:
        db: Absolute path of the SQLite file.

    Returns:
        One line per table as name|type|rows, or an error message.
    """
    if not db:
        return "error: db is required"

    try:
        with _connect(db) as conn:
            names = conn.execute(
                "SELECT name, type FROM sqlite_master "
                "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ).fetchall()
            lines = []
            for name, kind in names:
                count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                lines.append(f"{name}|{kind}|{count}")
    except (sqlite3.Error, OSError) as exc:
        return f"error: {exc}"

    if not lines:
        return "no table found"
    return "\n".join(lines)


TOOLS = {
    "query": query,
    "tables": tables,
}
```

Against a three-row `orders` table and a one-row `customers` table:

```text
db_inspect-tables(db="/tmp/demo.db")
customers|table|1
orders|table|3
```

```text
db_inspect-query(db="/tmp/demo.db", sql="SELECT sku, qty FROM orders ORDER BY qty DESC", limit="2")
sku|qty
C-3|5
A-1|2
rows: 2 (limit=2)
```

The guard rejects a write before SQLite ever sees it:

```text
db_inspect-query(db="/tmp/demo.db", sql="DELETE FROM orders")
error: only SELECT, WITH and PRAGMA statements are allowed
```

Three design points are worth copying:

- **The read-only URI is the real protection.** The keyword check is a second layer; `mode=ro` is
  what makes a mistake harmless.
- **`limit` is a string.** The LLM sends `"2"`, not `2`, so the tool converts and returns a
  readable error instead of raising.
- **Every failure is a returned string.** A tool that raises produces a traceback in the agent
  context; a tool that returns `error: ...` lets the model correct itself.

## Example: Bounded Log Inspection

**Scenario.** A run failed and the agent must explain why. Reading a whole log into the context is
expensive and usually truncated, so both tools return a bounded number of lines and report how
many lines they skipped. The agent can then decide whether to widen the window.

`docs/cookbook/tool/examples/my_tools/log_inspect.py`:

```python
"""Bounded log inspection exposed as log_inspect-scan and log_inspect-tail tools."""

# List form: the action name is the function name, so this module registers
# log_inspect-scan and log_inspect-tail.
#
# Scenario: the agent must explain why a run failed. Reading a whole log into the
# context is expensive and usually truncated, so both tools return a bounded
# number of matching lines and report how many lines they skipped.

import json
import os
from pathlib import Path

MAX_LINES = 100


def _resolve(path: str) -> Path:
    """Resolve a log path, defaulting to the agent log folder.

    Args:
        path: Absolute file path, or a bare file name inside the agent log folder.

    Returns:
        The resolved file path.
    """
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    home = os.getenv("TOPSAILAI_HOME", "")
    if not home:
        raise FileNotFoundError("relative path needs TOPSAILAI_HOME")
    return Path(home) / "log" / candidate


def _parse_patterns(patterns: str) -> list[str]:
    """Parse the patterns argument, which may arrive as a JSON list or a plain string.

    Args:
        patterns: A JSON array such as ["ERROR","Traceback"], or one plain substring.

    Returns:
        The list of substrings to match.
    """
    text = (patterns or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item)]
        return [text]
    return [item.strip() for item in text.split(",") if item.strip()]


def scan(path: str = "", patterns: str = "", limit: str = "40") -> str:
    """Return the last matching lines of one log file.

    Args:
        path: Absolute log path, or a file name inside the agent log folder.
        patterns: JSON array or comma-separated substrings; a line matches any of them.
        limit: Maximum matching lines to return, as a decimal string. Capped at 100.

    Returns:
        A summary line, then the matching lines in file order, or an error message.
    """
    if not path:
        return "error: path is required"

    try:
        max_lines = int(limit)
    except (TypeError, ValueError):
        return "error: limit must be an integer"
    if max_lines <= 0:
        return "error: limit must be positive"
    max_lines = min(max_lines, MAX_LINES)

    needles = _parse_patterns(patterns)
    try:
        target = _resolve(path)
        with target.open(encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as exc:
        return f"error: {exc}"

    matched = [
        line.rstrip("\n")
        for line in lines
        if not needles or any(needle in line for needle in needles)
    ]
    if not matched:
        return f"no match in {target.name} (lines={len(lines)}, patterns={needles})"

    shown = matched[-max_lines:]
    header = (
        f"{target.name}: matched={len(matched)} shown={len(shown)} "
        f"total_lines={len(lines)} patterns={needles}"
    )
    return "\n".join([header, *shown])


def tail(path: str = "", lines_count: str = "20") -> str:
    """Return the last lines of one log file without any filtering.

    Args:
        path: Absolute log path, or a file name inside the agent log folder.
        lines_count: Number of trailing lines to return, as a decimal string. Capped at 100.

    Returns:
        The trailing lines, or an error message.
    """
    if not path:
        return "error: path is required"

    try:
        count = int(lines_count)
    except (TypeError, ValueError):
        return "error: lines_count must be an integer"
    if count <= 0:
        return "error: lines_count must be positive"
    count = min(count, MAX_LINES)

    try:
        target = _resolve(path)
        with target.open(encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as exc:
        return f"error: {exc}"

    if not lines:
        return f"{target.name}: empty"
    return "\n".join(line.rstrip("\n") for line in lines[-count:])


TOOLS = [scan, tail]
```

A JSON array of patterns matches any of them:

```text
log_inspect-scan(path="run.log", patterns="[\"ERROR\",\"Traceback\"]", limit="3")
run.log: matched=3 shown=3 total_lines=7 patterns=['ERROR', 'Traceback']
2026-11-04 10:00:03 ERROR connect timeout host=db1
2026-11-04 10:00:05 ERROR connect timeout host=db1
2026-11-04 10:00:06 Traceback (most recent call last):
```

A plain string works too, and the header reports the truncation honestly:

```text
log_inspect-scan(path="run.log", patterns="ERROR", limit="1")
run.log: matched=2 shown=1 total_lines=7 patterns=['ERROR']
2026-11-04 10:00:05 ERROR connect timeout host=db1
```

`matched=2 shown=1` tells the model that one more match exists, so it can raise `limit` instead of
guessing. That single field is what makes the bounded output safe rather than lossy.

## What the LLM Actually Sees

The docstring is the tool description. It is not documentation for humans only.

```text
## db_inspect-tables

List the tables and views of one SQLite file with their row counts.

Args:
    db: Absolute path of the SQLite file.

Returns:
    One line per table as name|type|rows, or an error message.
```

The prompt renders each tool as a `## name` heading followed by the docstring in a code fence.

A missing docstring is not an error, but it renders the literal text `null` into the prompt, so
always write one.

### Parameter schemas are empty by default

When a tool has no `TOOLS_INFO` entry, the generated schema carries no parameter information:

```json
{"type": "function", "function": {"name": "db_inspect-tables", "description": "...", "parameters": {"type": "object"}}}
```

`parameters` is `{"type": "object"}` with no `properties`. The model learns the arguments only from
the docstring text, so the `Args:` section is the real contract. If you need a strict schema,
declare `TOOLS_INFO` in the module:

```python
TOOLS_INFO = {
    "echo": {
        "type": "function",
        "function": {
            "name": "WRONG_NAME",
            "description": "Custom schema description.",
            "parameters": {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
            },
        },
    },
}
```

The `name` field is overwritten with the registered name, so `WRONG_NAME` becomes `withinfo-echo`
and the rest of the schema is kept as written.

## Parameters Are Always Strings

LLM output is non-deterministic, so a declared `int` may arrive as `"2"`. Every parameter in these
examples is typed `str` and converted inside the function, returning a readable error on failure:

```text
db_inspect-query(db="/tmp/demo.db", sql="SELECT sku FROM orders", limit="abc")
error: limit must be an integer
```

Declared `list` or `dict` parameters must attempt `json.loads`, which is what `_parse_patterns()`
does while still accepting a plain comma-separated string.

## Module Variables

| Variable | Effect |
|----------|--------|
| `TOOLS` | Required. Dict or list of callables. |
| `TOOLS_INFO` | Optional. Per-action JSON schema, merged over the generated one. |
| `FLAG_TOOL_ENABLED` | Optional. `False` hides the module unless explicitly enabled. |
| `PROMPT` | Ignored for external modules. |

`PROMPT` is read only from the built-in `topsailai.tools.{module}` path, so a `PROMPT` string in an
external module never reaches the tool prompt. Put shared guidance in the docstrings instead.

## Enable and Disable Filtering

`FLAG_TOOL_ENABLED = False` hides a module by default. For a folder whose only module is
`flagged.py` with that flag set:

```text
TOPSAILAI_PLUGIN_TOOLS=<folder>                -> []
TOPSAILAI_ENABLED_TOOLS='*'                    -> ['flagged-hidden']
TOPSAILAI_ENABLED_TOOLS=flagged                -> ['flagged-hidden']
```

`TOPSAILAI_DISABLED_TOOLS` and `TOPSAILAI_ENABLED_TOOLS` both match by prefix, so one entry can
retire a whole module:

```text
TOPSAILAI_DISABLED_TOOLS=log_inspect  -> ['db_inspect-query', 'db_inspect-tables']
TOPSAILAI_ENABLED_TOOLS=db_inspect    -> ['db_inspect-query', 'db_inspect-tables']
```

`TOPSAILAI_DISABLED_TOOLS` is evaluated first and wins: with both variables naming the same module
the result is empty, because `is_tool_enabled()` returns `False` on the disabled match before it
ever reaches the enabled branch.

```text
TOPSAILAI_DISABLED_TOOLS=db_inspect
TOPSAILAI_ENABLED_TOOLS=db_inspect     -> []
```

Used alone, each variable has a distinct meaning: `TOPSAILAI_DISABLED_TOOLS` is a denylist, while
`TOPSAILAI_ENABLED_TOOLS` is an allowlist. A `+` entry in the allowlist means "keep everything
else", which turns it back into a denylist:

```text
TOPSAILAI_ENABLED_TOOLS='db_inspect;+' -> ['db_inspect-query', 'db_inspect-tables', 'log_inspect-scan', 'log_inspect-tail']
```

## Multiple Folders

Separate folders with `;` or `,`:

```bash
export TOPSAILAI_PLUGIN_TOOLS="/opt/team_tools;/opt/local_tools"
```

Both separators work, unlike instructions which accept only `;`. Empty and unset values are
harmless: the loader returns early and the built-in tools load normally.

**Duplicate module names have undefined precedence.** When two folders both contain `same.py`, the
winner varies between runs because the folder list is built from a set:

```text
run 1: A    run 2: A    run 3: A    run 4: B    run 5: B    run 6: B
```

Never rely on one folder overriding another. Give each module a unique file name.

## Verifying Without an Agent Session

`topsailai_simulate_agent_execute` runs the execution phase headlessly, so a tool can be tested
without a live LLM:

```bash
export TOPSAILAI_PLUGIN_TOOLS=/TopsailAI/src/topsailai/docs/cookbook/tool/examples/my_tools
export TOPSAILAI_HOME=/tmp/simdemo/home          # holds log/run.log
uv run python cli/topsailai_simulate_agent_execute.py \
    --show-tools --only-tools log_inspect \
    --file /tmp/simdemo/resp.txt
```

The response file uses the plain `topsailai.<step>` format:

```text
topsailai.thought
The run failed; I will inspect the log for errors.
topsailai.action
{"tool_call": "log_inspect-scan", "tool_args": {"path": "run.log", "patterns": "[\"ERROR\"]", "limit": "2"}}
topsailai.final_answer
Two connect timeouts to db1.
```

```text
[available_tools] [2] ['log_inspect-scan', 'log_inspect-tail']
[0] thought
The run failed; I will inspect the log for errors.
Two connect timeouts to db1.

[1] action
{"tool_call": "log_inspect-scan", "tool_args": {"path": "run.log", "patterns": "[\"ERROR\"]", "limit": "2"}}
-> observation: {'step_name': 'observation', 'raw_text': "run.log: matched=2 shown=2 total_lines=7 patterns=['ERROR']\n2026-11-04 10:00:03 ERROR connect timeout host=db1\n2026-11-04 10:00:05 ERROR connect timeout host=db1"}

Final answer:
Two connect timeouts to db1.
```

`--only-tools` and `--exclude-tools` accept `;`-separated prefixes, which keeps the output short
while you iterate on one module.

Note that a `final_answer` placed directly after an `action` is folded into the preceding `thought`
by the `action_with_final_answer` mistake rule, which is why the transcript above shows both
sentences under `[0] thought` instead of a separate final step. The run still completes and prints
a final answer. That is expected framework behavior, not a tool defect.

## Requirements and Limitations

| Requirement | Behavior |
|-------------|----------|
| Absolute folder path | Required. A relative path fails with `TypeError`. |
| No trailing slash | Required. A trailing `/` fails with `TypeError: 'NoneType' object is not iterable` when the path is inside the project tree, or `AssertionError: no found pkg_path for this path` when it is not. |
| Folder name is an identifier | Required. A hidden folder such as `.tmp/plugins` fails with `TypeError`. |
| Folder is not a `sys.path` entry | Required. Pointing at a `sys.path` entry fails with `AssertionError`. |
| Folder, not a file | Required. A single `.py` path fails with `TypeError`. |
| Direct children only | Nested sub-folders are not scanned. |
| `__init__.py` | Not required. |
| `TOOLS` variable | Required. A module without it is skipped silently. |
| Docstring | Recommended. Missing docstrings render `null` in the prompt. |
| `TOOL_CONN_CHAR` length | Exactly one character, otherwise `AssertionError`. |
| Duplicate module names | Undefined precedence across folders. |
| External `PROMPT` | Ignored. |

## Load Timing

`expand_plugin_tools()` runs once, when `topsailai.tools.base` is imported. Consequences:

- The environment variable must be set **before** the process starts.
- Adding a module to the folder later has no effect until the process restarts.
- There is no reload hook for external tools.

## Related Documents

- [Environment Variables](../../Environment_Variables.md) — `TOPSAILAI_PLUGIN_TOOLS`, `TOPSAILAI_TOOL_CONN_CHAR`, `TOPSAILAI_ENABLED_TOOLS`, `TOPSAILAI_DISABLED_TOOLS`
- [Tools readme](../../../tools/readme.md) — tool prompt, `PROMPT` versus docstring, string-first parameters
- [External Custom Instructions](../instruction/External_Custom_Instructions.md) — the same mechanism for `/` commands
- [Plugin Mechanisms](../../../features/feature-plugin-mechanisms.md) — how plugins, hooks and events differ
