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
| `category` | Stored session category; empty values are displayed as `(none)` in text and `""` in JSON. |
| `task` | Task description. |
| `project_workspace` | Recorded project workspace path. |
| `pwd` | Recorded working directory. |
| `topsailai_home` | Recorded `TOPSAILAI_HOME` path. |
| `total_prompt_tokens` | Accumulated prompt tokens under an explicit name. |
| `total_completion_tokens` | Accumulated completion tokens. |
| `total_usage_tokens` | Combined prompt and completion tokens. |
| `total_cached_tokens` | Accumulated cached prompt tokens. |
| `create_time` | Creation timestamp. |
| `status` | `Running` or `Idle`. |
| `is_running` | Boolean running status (JSON output only). |
| `create_time_relative` | Human-readable relative time, e.g. "3 minutes ago". |

The human-readable card labels these metrics as `Prompt Tokens`, `Completion Tokens`, `Total Usage Tokens`, and `Cached Prompt Tokens`. The JSON result does not expose the ambiguous `total_tokens` name. No additional database columns are used: `total_prompt_tokens` maps the internal legacy prompt-only `total_tokens` column to an explicit query field, and `total_usage_tokens` is calculated from prompt plus completion totals.

## Failure Output

`--json` always prints exactly one JSON object on stdout, including when the lookup fails. A failure object carries only the identity and the failure facts, because a session that was never found has no name, task, or token totals:

```json
{
  "session_id": "missing",
  "error_code": "session_not_found",
  "message": "Session not found: missing"
}
```

| `error_code` | Meaning |
|--------------|---------|
| `session_not_found` | No stored session has this identifier. |
| `lookup_failed` | The session storage could not be queried; `message` carries the error. |

A failure object never contains the success fields, so a consumer decides on `error_code` instead of mistaking a failure for a real session whose fields happen to be empty. No ANSI escape sequence is written in JSON mode, so the output is always parseable.

Without `--json` the same failures are printed as the human-readable `[INFO] Session not found: <id>` or `[ERROR] <message>` line.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | The session was found and printed. |
| 1 | The session was not found, or the session storage could not be queried. |

## Examples

```bash
# Display a session card
topsailai_session_info my-session

# JSON output
topsailai_session_info my-session --json

# Use a custom home directory
topsailai_session_info my-session --home /path/to/home
```
