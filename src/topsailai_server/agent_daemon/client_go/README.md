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
| `--host` | string | `localhost` | Agent daemon host |
| `--port` | string | `7373` | Agent daemon port |
| `--session-id` | string | (none) | Session ID (required) |
| `--message` | string | (none) | Message content (required) |
| `--role` | string | `user` | Message role (`user` or `assistant`) |
| `--wait-interval` | int | `2` | Polling interval in seconds |
| `--max-wait-time` | int | `300` | Max wait time in seconds |
| `--result-only` | bool | `false` | Output only result content, no metadata |

## Environment Variables

All flags can be set via environment variables. Environment variables take precedence over default values but can be overridden by explicit flags.

| Environment Variable | Corresponding Flag | Default |
|---------------------|-------------------|---------|
| `TOPSAILAI_AGENT_DAEMON_HOST` | `--host` | `localhost` |
| `TOPSAILAI_AGENT_DAEMON_PORT` | `--port` | `7373` |
| `TOPSAILAI_SESSION_ID` | `--session-id` | (none) |
| `TOPSAILAI_MESSAGE` | `--message` | (none) |
| `TOPSAILAI_MESSAGE_ROLE` | `--role` | `user` |
| `WAIT_INTERVAL` | `--wait-interval` | `2` |
| `MAX_WAIT_TIME` | `--max-wait-time` | `300` |
| `RESULT_ONLY` | `--result-only` | `false` |

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
new_msg_id: abc123
Done.
```

### Using environment variables only

```bash
export TOPSAILAI_SESSION_ID=my-session
export TOPSAILAI_MESSAGE="Hello, agent"
export RESULT_ONLY=true
./wait_for_message_result
```

Output:
```
new_msg_id: abc123
Done.
```

### Mixed flags and environment variables

```bash
export TOPSAILAI_SESSION_ID=my-session
./wait_for_message_result --message "Hello" --result-only
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
new_msg_id: <msg_id>
<task_result or message>
```

Only the raw result content is printed, no separators or metadata.

## Exit Codes

- `0` — Success, result returned
- `1` — Error (missing required parameters, API error, or timeout)
