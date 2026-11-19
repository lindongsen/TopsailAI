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
| `--include-runtime` | Add a `runtime` object collected from the running session process. Selects JSON output by itself. |

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
| `runtime` | Runtime record collected from the running process, or `null`. Always present in JSON. |

The human-readable card labels these metrics as `Prompt Tokens`, `Completion Tokens`, `Total Usage Tokens`, and `Cached Prompt Tokens`. The JSON result does not expose the ambiguous `total_tokens` name. No additional database columns are used: `total_prompt_tokens` maps the internal legacy prompt-only `total_tokens` column to an explicit query field, and `total_usage_tokens` is calculated from prompt plus completion totals.

## Runtime Data

`--include-runtime` adds a `runtime` object to the JSON record. It is collected from the session's own control channel, using the same instruction, argument form, timeout, and error vocabulary as `workspace list --include-runtime`, so both commands report identical states for the same process.

- The object is fetched only when the session is running. An idle session has no process to answer, so `runtime` stays `null` instead of reporting a failure for a state that is not a failure.
- The queried PID is the one that proved the session live, so a session owned by a sibling container is reached through its own control channel rather than through the local process table.
- Collection is best effort. Any failure leaves `runtime` as `null` and never breaks the record, so a consumer always receives a complete document.
- The key is always present, which lets a consumer tell "not requested" from "requested but unavailable".

The record shape is:

```json
{
  "state": "ok",
  "error_code": null,
  "pid": 4242,
  "data": { "ok": true, "model": { "name": "example-model" } }
}
```

| `state` | Meaning |
|---------|---------|
| `ok` | Usable runtime data is present in `data`. |
| `rejected` | The process answered but refused the instruction, typically because it started before the instruction existed. |
| `timeout` | The process did not answer within the transport budget. |
| `unavailable` | The endpoint is missing, the instruction reported its own failure, or the transport failed. |

`--include-runtime` selects JSON output by itself, because runtime data has no card representation. It is therefore a request for the data rather than a modifier of an already-chosen format, which is the same contract `workspace list` applies. The failure paths honour it too, so a machine consumer always receives parseable JSON.

## Related Command

`topsailai runtime info` prints the same document for the same session, with one addition: `-p/--pid` selects which process answers the runtime query, because one session may run several agents at the same time. Without `-p` it resolves the answering PID exactly as this command does, so the default invocation is identical. A task (child) agent writes only a `{session}.{pid}[.{task_id}].task.stdout` log, so `-p` accepts that file as ownership evidence and reports `is_task: true` in the `runtime` object; this command always queries the session process, so its own `runtime` never carries a worker's data. See [topsailai](topsailai.md#session-record-with-runtime-data).

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
