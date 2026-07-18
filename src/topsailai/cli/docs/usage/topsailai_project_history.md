---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_project_history

Display recent project/workspace navigation history entries.

## Purpose

Reads `.project_history.jsonl` from `TOPSAILAI_HOME` and prints the latest N entries as a formatted table or as JSON. Sessions that are still running are highlighted in green.

## Invocation

```bash
./topsailai_project_history.py
./topsailai_project_history.py -n 10
./topsailai_project_history.py --json
```

Because the script is registered in `../bin/` as `topsailai_project_history`, you can also run it as:

```bash
topsailai_project_history
topsailai_project_history -n 10
```

## Options

| Option | Description |
|--------|-------------|
| `-n`, `--limit <N>` | Maximum number of recent entries to display (default: 20). |
| `--home <path>` | Override `TOPSAILAI_HOME` directory. |
| `--json` | Output entries as JSON instead of a formatted table. |

## Table Columns

| Column | Description |
|--------|-------------|
| `No` | Row number, 1 is the most recent. |
| `Timestamp` | Human-readable local timestamp. |
| `Session ID` | Session identifier; `(temp)` for transient sessions. |
| `PID` | Recorded process ID. |
| `Project Workspace` | Recorded project workspace path. |
| `PWD` | Recorded working directory. |
| `Status` | `Running` (green) if the session PID is alive, otherwise `Idle`. |

## Examples

```bash
# Show the latest 20 entries
topsailai_project_history

# Show the latest 10 entries
topsailai_project_history -n 10

# Machine-readable output
topsailai_project_history --json

# Use a custom home directory
topsailai_project_history --home /path/to/home --limit 5
```

## Notes

- Running detection uses the most recently modified `{session_id}.{pid}.session.stdout` file in `{TOPSAILAI_HOME}/workspace/task/`.
- `--limit` must be a positive integer.
