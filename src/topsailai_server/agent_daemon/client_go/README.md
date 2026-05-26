# topsailai_send_message (wait_for_message_result)

A Go CLI client for the agent_daemon HTTP API. It sends a message to a session and waits for the processing result.

## Overview

`wait_for_message_result` sends a message to a specified session via the agent_daemon REST API, then polls for new messages until a result is returned. It outputs the new message ID and the processing result(s).

## Build

```bash
go build -o wait_for_message_result main.go
```

## Command-Line Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--api-base` | string | `http://localhost:7373` | Agent daemon API base URL |
| `--session-id` | string | (none) | Session ID (required for send-message and `/status`) |
| `--message` | string | (none) | Message content or command (required) |
| `--role` | string | `user` | Message role (`user` or `assistant`) |
| `--wait-interval` | int | `2` | Polling interval in seconds |
| `--max-wait-time` | int | `600` | Max wait time in seconds |
| `--result-only` | bool | `false` | Output only result content, no metadata |
| `--api-key` | string | (none) | API key for authentication |
| `--auth-style` | string | `x-api-key` | Authentication header style: `x-api-key` or `bearer` |

## Environment Variables

All flags can be set via environment variables. Environment variables take precedence over default values but can be overridden by explicit flags.

| Environment Variable | Corresponding Flag | Default |
|---------------------|-------------------|---------|
| `TOPSAILAI_AGENT_DAEMON_API_BASE` | `--api-base` | `http://localhost:7373` |
| `TOPSAILAI_AGENT_DAEMON_API_KEY` | `--api-key` | (none) |
| `TOPSAILAI_AGENT_DAEMON_AUTH_STYLE` | `--auth-style` | `x-api-key` |
| `TOPSAILAI_SESSION_ID` | `--session-id` | (none) |
| `TOPSAILAI_MESSAGE` | `--message` | (none) |
| `TOPSAILAI_MESSAGE_ROLE` | `--role` | `user` |
| `WAIT_INTERVAL` | `--wait-interval` | `2` |
| `MAX_WAIT_TIME` | `--max-wait-time` | `600` |
| `RESULT_ONLY` | `--result-only` | `false` |
| `DEBUG` | `--result-only` | `false` (when `DEBUG=1`) or `true` (when `DEBUG=0`) |

> **Note on `DEBUG`:** When `DEBUG` is set, it takes precedence over `RESULT_ONLY`.
> - `DEBUG=0` → `RESULT_ONLY=true`
> - `DEBUG=1` → `RESULT_ONLY=false`

The `--api-base` flag (or `TOPSAILAI_AGENT_DAEMON_API_BASE` env var) accepts a base URL such as:

- `http://172.18.0.4:7373`
- `http://172.18.0.4:7373/api/v1`

If the URL does not end with `/api/v1`, it is automatically appended. The default base URL is `http://localhost:7373`.

## Authentication

If `TOPSAILAI_AGENT_DAEMON_API_KEY` (or `--api-key`) is provided, it is sent in the request header:

- `X-API-Key: <api-key>` when `--auth-style` is `x-api-key` (default)
- `Authorization: Bearer <api-key>` when `--auth-style` is `bearer`

## Commands

When `--message` starts with `/`, it is treated as a command instead of a chat message. Supported commands:

### `/health`

Checks the daemon health endpoint (`GET /health`).

```bash
./wait_for_message_result --message "/health"
```

Output (raw JSON):
```json
{"code":0,"data":{"status":"healthy","database":"healthy","timestamp":"2026-05-26T02:42:54.702850"},"message":"OK"}
```

- Exit code `0` if `code` is `0` (healthy)
- Exit code `1` on HTTP error or `code != 0`

### `/status`

Gets the session status (`GET /api/v1/session/{session_id}`). `--session-id` is required.

```bash
./wait_for_message_result --session-id my-session --message "/status"
```

Output:
```
idle
```

- Exit code `0` if successful, printing `data.status`
- Exit code `1` on HTTP error, `code != 0`, or missing `session-id`

## Usage Examples

### Basic usage with flags

```bash
./wait_for_message_result --session-id my-session --message "Hello, agent"
```

Output:
```
new_msg_id: abc123
---
[2026-04-22T10:00:00] [def456] [assistant]
Hello! How can I help you?
>>> task_id: task-001
>>> task_result: Done.
```

### Using `--result-only`

```bash
./wait_for_message_result --session-id my-session --message "Hello" --result-only
```

Output:
```
Done.
```

### Using environment variables only

```bash
export TOPSAILAI_AGENT_DAEMON_API_BASE=http://172.18.0.4:7373
export TOPSAILAI_AGENT_DAEMON_API_KEY=my-secret-key
export TOPSAILAI_SESSION_ID=my-session
export TOPSAILAI_MESSAGE="Hello, agent"
export RESULT_ONLY=true
./wait_for_message_result
```

Output:
```
Done.
```
### Mixed flags and environment variables

```bash
export TOPSAILAI_AGENT_DAEMON_API_BASE=http://172.18.0.4:7373
export TOPSAILAI_SESSION_ID=my-session
./wait_for_message_result --message "Hello" --result-only
```

### Health check command

```bash
./wait_for_message_result --message "/health"
```

### Status command

```bash
./wait_for_message_result --session-id my-session --message "/status"
```

## Output Format

**Full format (default):**

```
new_msg_id: <msg_id>
---
[<create_time>] [<msg_id>] [<role>]
<message>
>>> task_id: <task_id>
>>> task_result: <task_result>
```

- `task_id` and `task_result` are only included when present.
- Multiple result messages are separated by `---`.

**Result-only format (`--result-only`):**

```
<task_result or message>
```

Only the raw result content is printed, no separators or metadata (including `new_msg_id`).

## Exit Codes

- `0` — Success, result returned or command executed successfully
- `1` — Error (missing required parameters, API error, timeout, or command failure)
