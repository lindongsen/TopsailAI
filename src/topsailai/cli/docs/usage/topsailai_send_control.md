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
| `-c COMMAND`, `--command COMMAND` | Control action to send. Supported actions: `call_instruction`, `clear_interrupt`, `get_runtime_messages`, `get_session_messages`, `hard_interrupt`, `heartbeat`, `llm_control`, `soft_interrupt`. See [Control handlers](#control-handlers) for payloads, results and errors. |
| `-a ARGS`, `--args ARGS` | JSON object with action-specific arguments. Defaults to `{}`. |
| `--socket-path SOCKET_PATH` | Send the request directly to this socket path. |
| `--timeout TIMEOUT` | Set the socket connection timeout in seconds. Defaults to `5.0`. |
| `--json` | Print the raw server response as JSON instead of readable text. Use this for scripts; the default output is for humans. See [Output](#output). |

## Exit Status

| Code | Meaning |
|------|---------|
| `0` | At least one targeted socket returned a successful response. |
| `1` | No sockets were targeted or all targeted requests failed. |

## Output

The default output is readable text intended for a human. `--json` prints the raw server response instead and is the machine-readable contract.

### Readable output (default)

The first line reports the response status and request ID. An `error` line follows when the response carries one. The `result` is then printed after a blank line.

```text
status: ok    request_id: cfc6806abd80454db046c6b372518bff

-------------------------------------------------------------------------
Instructions:

  /env.set
    - set_env,
        set environment

        Args:
            k (str): key
            v (str): value

-------------------------------------------------------------------------
```

Rendering depends on the result type:

| Result type | Rendering |
|-------------|-----------|
| String | Printed verbatim, so real newlines, indentation and separator widths are preserved. |
| Object or array | Printed as JSON with two-space indentation. |
| Other scalar | Printed with `str()`. |

A non-empty `result` is always printed, whatever the status is. A response with `status: error` therefore shows both the `error` line and the `result`. Only an empty result is omitted: `null`, an empty or whitespace-only string, and an empty object, array, tuple or set.

Terminal escape sequences and control characters other than newline and tab are removed from the status, request ID, error and result, because a control response originates from the agent process and may carry them. Color is used only when standard output is a terminal and `NO_COLOR` is unset.

When more than one socket is targeted, each block is preceded by a `=== <socket path> ===` header and followed by a blank line.

### JSON output (`--json`)

`--json` prints each response with `json.dumps(..., ensure_ascii=False, indent=2)` and performs no sanitizing, so the output is exactly what the server returned. When more than one socket is targeted, the responses are printed one after another; the combined output is not a single JSON document.

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
topsailai_send_control --session_id my-session --command soft_interrupt --args '{"message":"timeout"}'
```

## Control handlers

Handlers are discovered from the live registry, so the accepted action names can grow through plugins. The table below documents the handlers registered by the current implementation.

| Action | Payload | Result on success | Typical errors |
|--------|---------|-------------------|----------------|
| `call_instruction` | `instruction` (required string), `args` (optional list), `kwargs` (optional object) | The instruction's own return value | `missing or invalid instruction`, `args must be a list`, `kwargs must be an object`, `unknown instruction: NAME`, `instruction failed: ...` |
| `clear_interrupt` | none | `action`, `session_id`, `pid`, `flag_path`, `removed`, `message` | `missing session_id`, `missing pid`, `failed to clear interrupt flag: ...` |
| `get_runtime_messages` | none | `count`, `messages` | `no active agent in control context or current thread`, `active agent has no messages attribute` |
| `get_session_messages` | `session_id` (required string) | `count`, `messages` | `missing or empty session_id`, `session manager is not available`, `session not found: ID`, `failed to retrieve session messages: ...` |
| `hard_interrupt` | none | `action`, `session_id`, `pid`, `flag_path`, `message` | `missing session_id`, `missing pid`, `failed to write interrupt flag: ...` |
| `heartbeat` | must be empty | `alive`, `pid`, `hostname`, `session_id` (nullable) | `invalid_payload` when any payload field is supplied |
| `llm_control` | `operation` (must be `force_retry`) | `state: "flag_written"` | `unavailable`, `invalid_operation`, `unsupported_target`, `flag_write_failed`, `not_waiting` |
| `soft_interrupt` | `message` (optional string) | `action`, `session_id`, `pid`, `file_path`, `message` | `missing session_id`, `missing pid`, `failed to append inject message: ...` |

A handler that rejects a request returns top-level `status: "error"` with an `error` string; the CLI then exits non-zero. A successful response means the handler accepted and performed its own local step, not that the agent has already reacted to it.

### `call_instruction`

Invokes a registered `/` instruction inside the target agent and returns its result. `instruction` may be written with or without the leading `/`. `args` must be a list and `kwargs` must be an object; both default to empty.

```bash
topsailai_send_control --session_id SESSION_ID --pid PID \
  --command call_instruction \
  --args '{"instruction":"ctx.history","args":["arg1"],"kwargs":{"key":"value"}}'
```

The handler requires a live agent chat context; a request sent to a process without one fails with `hook instruction is not available in control context`.

### `hard_interrupt` and `clear_interrupt`

`hard_interrupt` atomically writes the session's interrupt flag file, which the agent observes on its next check. `clear_interrupt` removes that flag and reports `removed: false` when no flag existed, so clearing is idempotent.

```bash
topsailai_send_control --session_id SESSION_ID --pid PID --command hard_interrupt
topsailai_send_control --session_id SESSION_ID --pid PID --command clear_interrupt
```

Both handlers resolve `session_id`, `pid` and the task folder from the request context, falling back to the responding process identity. Writing the flag does not prove the agent has stopped.

### `soft_interrupt`

Appends a user message to the session's `agent2llm` inject JSONL file, asking the agent to stop calling tools, summarize progress and end the task. Supplying `message` replaces the default instruction text.

```bash
topsailai_send_control --session_id SESSION_ID --pid PID --command soft_interrupt
topsailai_send_control --session_id SESSION_ID --pid PID \
  --command soft_interrupt --args '{"message":"Stop and summarize now."}'
```

The message is queued for the next LLM call; appending it does not prove the agent has consumed it.

### `get_runtime_messages` and `get_session_messages`

`get_runtime_messages` returns the target process's current `agent2llm` messages. `get_session_messages` returns the persisted `user2agent` messages for a session ID; when `-s/--session_id` is given and the payload omits `session_id`, the CLI fills it in automatically.

```bash
topsailai_send_control --session_id SESSION_ID --pid PID --command get_runtime_messages
topsailai_send_control --session_id SESSION_ID --command get_session_messages
```

Both results contain `count` and `messages`, with each message serialized to JSON-compatible primitives. Message bodies can contain sensitive conversation content.

### `heartbeat`

Confirms that the target process is answering on its control channel. The payload must be empty; any supplied field is rejected with `invalid_payload`.

```bash
topsailai_send_control --session_id SESSION_ID --pid PID --command heartbeat
```

The result reports `alive`, the responding `pid`, `hostname` and a nullable `session_id`. It proves control-channel reachability only, not agent or LLM progress.

### `llm_control`

Stages a first-byte retry flag for the current LLM wait of the responding process. The only accepted operation is `force_retry`; a `target` field is rejected with `unsupported_target`, and the handler refuses to act unless the request reached the process that owns the wait.

```bash
topsailai_send_control --session_id SESSION_ID --pid PID \
  --command llm_control --args '{"operation":"force_retry"}'
```

A successful result is `{"state":"flag_written"}`. `not_waiting` means no first-byte wait marker existed, so nothing was staged; `unavailable` means the request reached a process without an active agent chat. Staging a flag is not proof that a retry happened.

## First-byte request control (`llm_control`)

This section describes the routed first-byte control contract. The handler registered by the current implementation accepts only `operation: "force_retry"` with no `target` field, as documented in [Control handlers](#control-handlers); the `status` and `hard_interrupt` operations below require a routing-capable handler that this build does not register, so they are rejected with `invalid_operation`. This action does not replace the legacy `--command hard_interrupt` action or `/control.hard_interrupt` shortcut, which set the existing interrupt flag.

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
[runtime:my-session]> /control.soft_interrupt {"message":"timeout"}
[runtime:my-session]> /control.clear_interrupt
[runtime:my-session]> /control.get_runtime_messages
```

`/control.soft_interrupt` accepts an optional JSON object whose `message` field replaces the default instruction text; the other three take no arguments. The payload must be a JSON object, so a bare word such as `timeout` is rejected as invalid JSON.

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
