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
| `-c COMMAND`, `--command COMMAND` | Control action to send. Supported actions: `call_instruction`, `hard_interrupt`, `soft_interrupt`, `clear_interrupt`, `get_runtime_messages`, `get_session_messages`, `llm_control`. |
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

Send the legacy flag-based hard interrupt to all running sessions (not the first-byte waiting-turn operation described below):

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

## First-byte request control (`llm_control`)

This additive action controls an explicitly routed AgentChat LLM request while waiting for request creation or the first decoded streaming record. It does not replace the legacy `--command hard_interrupt` action or `/control.hard_interrupt` shortcut, which set the existing interrupt flag.

| `operation` | Effect |
|-------------|--------|
| `status` | Discover the current route/target, or query a retained command by `command_id`. |
| `hard_interrupt` | Abandon the current Agent2LLM execution and User2Agent turn, keep the chat/session open, and return to fresh input without automatic retry or normal turn-completion effects. Supported only for interactive AgentChat routes. |
| `force_retry` | Abandon the current request attempt and use the existing `LLMModel.chat()` retry loop, remaining budget and backoff. It does not restart the Agent or tools, reset the budget, or guarantee another attempt when the budget is exhausted. |

### Control the current request

Select one session **and process**; omitted filters can broadcast. For a manual
shortcut, omit `target` and let the Handler freeze the current request at command
admission:

```bash
topsailai_send_control --session_id SESSION_ID --pid PID \
  --command llm_control --args '{"operation":"force_retry"}'
topsailai_send_control --session_id SESSION_ID --pid PID \
  --command llm_control --args '{"operation":"hard_interrupt"}'
```

The receipt returns the generated `result.proposal.command_id` and exact
`result.proposal.target`. Each call without an ID is a new intent. For safe retry
after a lost response, supply your own unique stable ID on the first call:

```bash
topsailai_send_control --session_id SESSION_ID --pid PID \
  --command llm_control --args '{"operation":"force_retry","command_id":"unique-command-001"}'
```

Resending that ID and operation on the same route and generation returns the
original target and current retained command state, even if the route is idle,
a newer request is active, or control capacity is now unavailable. It never
rebinds to that newer request. Changed operations conflict; IDs owned by another
route or generation conflict without disclosing that command. Deduplication lasts
only for bounded retained history (terminal records expire after 600 seconds by
default); never reuse old IDs.

A new command with no current target returns `error/no_active_target` and is not
queued for future work. Capacity fallback rejects new commands with
`unavailable/control_capacity`. A target selected at admission may still lose to
normal completion or become stale; it is never retargeted. Explicit `null`, empty
or malformed targets remain invalid, not automatic selection.

Automatic selection may choose request B if A finished before admission. Use the
explicit workflow below when the intent is to control a previously observed A.
An explicit command can be retransmitted without its target using the same ID
and operation. An automatic command can be retransmitted explicitly only with
its original exact target; changing the target conflicts.

### Discover, submit and query

Select one running session **and process** explicitly; omitted filters can broadcast to multiple sessions. Discover its current target first:

```bash
topsailai_send_control --session_id SESSION_ID --pid PID \
  --command llm_control --args '{"operation":"status"}'
```

Proceed only when `result.target` is non-null and the request is still in its first-byte waiting window. Copy all four fields from that exact response: `binding_id`, integer `generation`, `invocation_id`, and `attempt_id`. Do not guess the generation or reuse a target from another attempt, process or replacement Agent. In the following template, replace every `COPY_*` placeholder, including the unquoted integer placeholder, before running:

```bash
topsailai_send_control --session_id SESSION_ID --pid PID \
  --command llm_control \
  --args '{"operation":"hard_interrupt","command_id":"unique-command-001","target":{"binding_id":"COPY_BINDING_ID","generation":COPY_INTEGER_GENERATION,"invocation_id":"COPY_INVOCATION_ID","attempt_id":"COPY_ATTEMPT_ID"}}'
```

For forced retry, change `operation` to `force_retry` and use a new unique `command_id`. Supply a caller-generated unique ID for each new intent. To retransmit after a lost response, resend the **same ID, operation and exact target**; retained identical requests are idempotent, while reusing the ID with different content is rejected as `conflict`. Receipt history is bounded and expires, so this is not permanent deduplication: do not reuse old IDs.

Query the original command on the same route:

```bash
topsailai_send_control --session_id SESSION_ID --pid PID \
  --command llm_control \
  --args '{"operation":"status","command_id":"unique-command-001"}'
```

### Interpret responses

A top-level `status: "ok"` (or CLI exit code `0`) confirms a successful control response, **not** that the requested operation was applied. Inspect `result.state` and `result.reason`:

| Command state | Meaning |
|---------------|---------|
| `queued` | Receipt retained; no coordinator decision yet. The request may finish or time out before selection. |
| `accepted` | The coordinator selected this command; delivery and cleanup are not yet confirmed. |
| `recovery` | The retry/turn consumer received the control signal; cleanup custody remains pending. |
| `applied` | Consumer delivery and owned cleanup have both settled. This does not assert upstream cancellation. |
| `rejected` | The command did not complete as requested; inspect `reason`, for example `stale_target`, `already_decided`, `unsupported_exit_scope`, `capacity`, `conflict`, `retry_budget_exhausted`, `cleanup_pending`, or `interrupted_before_delivery`. |

Malformed/obsolete ownership can instead return top-level `status: "error"`; expired, unknown or replacement-route command queries return `unknown_command`. Route status without a command ID reports route state/reason and target, not a command receipt. A target may become stale immediately after discovery: rediscover for a **new** intent rather than silently retargeting an existing command.

### Scope and operational limits

- The streaming window ends at the **first decoded record**, including metadata-only records, EOF or an error; it is not a wait for the first visible token. Nonstreaming control covers request creation. Post-first-record generation, tools, unrelated background LLM calls and unbound routes are outside this action's scope.
- Existing first-byte timeout deadlines, raising behavior and one-time warning behavior remain in force. Control can remain available with a disabled timeout or after a warn-and-continue timeout; a command does not reset the deadline or outrank an already-decided outcome. Without a command, the original request/retry behavior is preserved.
- When control recovery capacity is exhausted, route status reports `state: "unavailable"`, `reason: "control_capacity"`; new submissions return `unavailable/control_capacity`. The **whole attempt** falls back to legacy execution, with control unavailable even if capacity later frees. Only control-owned resources are finitely bounded; legacy provider workers are not globally capped or rejected by this policy.
- Transport requires POSIX Unix-domain sockets and a running reachable session control channel. Hook polling is cooperative, not a strict response-latency guarantee. Deploy only trusted, nonblocking Hook Modules; they return proposals and the coordinator validates/selects them, with request abandonment outside the Hook. A blocking Hook can delay control.
- Cleanup maintenance continues after a route closes. Permanently blocked or uncertain cleanup retains its finite slot and can force subsequent legacy fallback. Local abandonment cannot guarantee that an upstream request, generation or billing has stopped.
- No new environment variables are required. The CLI `--timeout` controls socket communication, not the LLM first-byte deadline.

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
