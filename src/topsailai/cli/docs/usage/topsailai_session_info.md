---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_session_info

Display detailed information about a single session.

## Purpose

Queries the session storage for the given session ID and prints metadata such as ID, name, task, creation time, token usage, and running status. Running status is determined by checking for a live `{session_id}.{pid}.session.stdout` file under `{TOPSAILAI_HOME}/workspace/task/`.

## Invocation

```bash
./topsailai_session_info.py <session_id>
./topsailai_session_info.py <session_id> --json
```

Because the script is registered in `../bin/` as `topsailai_session_info`, you can also run it as:

```bash
topsailai_session_info <session_id>
```

## Options

| Option | Description |
|--------|-------------|
| `session_id` | Positional argument: the session identifier to look up. |
| `--db-conn <string>` | Optional database connection string (default: use session manager default). |
| `--home <path>` | Override `TOPSAILAI_HOME` directory. |
| `--no-color` | Disable colored output. |
| `--json` | Output the session information as JSON. |

## Output Fields

| Field | Description |
|-------|-------------|
| `session_id` | Session identifier. |
| `session_name` | Human-readable session name. |
| `task` | Task description. |
| `project_workspace` | Recorded project workspace path. |
| `pwd` | Recorded working directory. |
| `topsailai_home` | Recorded `TOPSAILAI_HOME` path. |
| `total_tokens` | Legacy JSON field for accumulated prompt tokens; retained for compatibility. |
| `total_prompt_tokens` | Accumulated prompt tokens under an explicit name. |
| `total_completion_tokens` | Accumulated completion tokens. |
| `total_usage_tokens` | Combined prompt and completion tokens. |
| `total_cached_tokens` | Accumulated cached prompt tokens. |
| `create_time` | Creation timestamp. |
| `status` | `Running` or `Idle`. |
| `is_running` | Boolean running status (JSON output only). |
| `create_time_relative` | Human-readable relative time, e.g. "3 minutes ago". |

The human-readable card labels these metrics as `Prompt Tokens`, `Completion Tokens`, `Total Usage Tokens`, and `Cached Prompt Tokens`. No additional database columns are used: `total_prompt_tokens` aliases the legacy prompt-only `total_tokens` column, and `total_usage_tokens` is calculated from prompt plus completion totals.

## Examples

```bash
# Display a session card
topsailai_session_info my-session

# JSON output
topsailai_session_info my-session --json

# Use a custom home directory
topsailai_session_info my-session --home /path/to/home
```
