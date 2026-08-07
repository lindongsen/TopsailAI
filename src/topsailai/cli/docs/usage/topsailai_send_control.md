---
maintainer: AI
author: DawsonLin
---

# `topsailai_send_control`

Send JSONL control requests to running TopsailAI sessions over a Unix domain socket (UDS).

## Synopsis

```text
topsailai_send_control [-h] [-s SESSION_ID] [-p PID] -c COMMAND
                        [-a ARGS] [--socket-path SOCKET_PATH]
                        [--timeout TIMEOUT] [--json]
```

## Description

The command discovers running sessions by scanning `{TOPSAILAI_HOME}/workspace/task/` for `*.session.stdout` and `*.task.stdout` files, derives the control socket path for each matching session, and sends a JSONL request to it.

When `--socket-path` is provided, discovery is skipped and only that socket is targeted. Otherwise, all sessions matching `--session_id` and `--pid` filters are targeted.

## Options

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show the help message and exit. |
| `-s SESSION_ID`, `--session_id SESSION_ID` | Target only stdout files whose session ID matches this value. |
| `-p PID`, `--pid PID` | Target only stdout files whose PID matches this value. |
| `-c COMMAND`, `--command COMMAND` | Control action to send. Supported actions: `call_instruction`, `hard_interrupt`, `soft_interrupt`, `clear_interrupt`, `get_runtime_messages`. |
| `-a ARGS`, `--args ARGS` | JSON object with action-specific arguments. Defaults to `{}`. |
| `--socket-path SOCKET_PATH` | Send the request directly to this socket path. |
| `--timeout TIMEOUT` | Set the socket connection timeout in seconds. Defaults to `5.0`. |
| `--json` | Retained for backward compatibility; server responses are always printed as JSON with two-space indentation. |

## Exit Status

| Code | Meaning |
|------|---------|
| `0` | At least one targeted socket returned a successful response. |
| `1` | No sockets were targeted or all targeted requests failed. |

## Examples

Send a hard interrupt to all running sessions:

```bash
topsailai_send_control --command hard_interrupt
```

Send a soft interrupt to a specific session:

```bash
topsailai_send_control --session_id my-session --command soft_interrupt
```

Retrieve runtime messages from a specific process:

```bash
topsailai_send_control --pid 12345 --command get_runtime_messages
```

Invoke a registered `/` instruction with arguments:

```bash
topsailai_send_control --session_id my-session --command call_instruction --args '{"instruction":"ctx.history","args":["arg1"],"kwargs":{"key":"value"}}'
```

Send a supported command with extra arguments:

```bash
topsailai_send_control --session_id my-session --command soft_interrupt --args '{"reason":"timeout"}'
```

## Interactive CLI Usage

When watching a session in `topsailai.py`, you can send a control action through the runtime command:

```text
[runtime:my-session]> /control hard_interrupt
```

To pass arguments, supply a JSON object as the second argument:

```text
[runtime:my-session]> /control soft_interrupt {"reason":"timeout"}
```

### Subcommand shortcuts

Fixed actions can be invoked without writing JSON using the `/control.<subcommand>` form:

```text
[runtime:my-session]> /control.hard_interrupt
[runtime:my-session]> /control.soft_interrupt timeout
[runtime:my-session]> /control.clear_interrupt
[runtime:my-session]> /control.get_runtime_messages
```

`/control.soft_interrupt` accepts an optional free-text reason; the other three take no arguments.

### Interactive wizard for `call_instruction`

`/control.call_instruction` without a JSON payload starts an interactive wizard that prompts for the instruction name, positional arguments, and keyword arguments, then assembles the JSON payload automatically:

```text
[runtime:my-session]> /control.call_instruction
Instruction name: ctx.history
Positional arg (empty to finish): arg1
Positional arg (empty to finish):
Keyword arg (key=value, empty to finish): key=value
Keyword arg (key=value, empty to finish):
```

The wizard sends `{"instruction":"ctx.history","args":["arg1"],"kwargs":{"key":"value"}}`.

### TAB completion

TAB completion is available for:

- `/control.<action>` — completes the action name from the registered control actions.
- `/control.call_instruction <name>` — completes the instruction name from the registered `/` instructions.

## See Also

- `topsailai_session_add_agent2llm_message`
- `topsailai_session_add_message`
- `topsailai.py`
