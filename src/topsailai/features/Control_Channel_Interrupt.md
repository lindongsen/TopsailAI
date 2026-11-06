# Control Channel Interrupt

## Overview

This document describes how external processes can interrupt the running Agent2LLM loop through the control channel. The control channel infrastructure lives in `workspace/control_channel/` and provides transport, protocol framing, and handler registration. Business handlers live in `workspace/control_handlers/` and are auto-discovered when the control channel starts.

Three control modes are supported:

- **Hard interrupt**: immediately stop the current Agent2LLM loop and keep the session in an interrupted state until the user sends a new message.
- **Soft interrupt**: inject a message into the Agent2LLM context asking the agent to summarize current progress and terminate gracefully.
- **Pause**: block the Agent2LLM loop at a safe point on a continue prompt, then resume or interrupt according to the answer.

All three mechanisms use file-based signaling under the same session-scoped naming convention. Hard interrupt only sets a marker file and does not inject any message. Soft interrupt only appends to the existing Agent2LLM runtime message injection file. Pause writes a JSON marker that the agent consumes exactly once before prompting. The mechanisms are intentionally separate.

## File Paths and Naming

All files are placed in the workspace task folder. The exact folder is resolved by `workspace/folder_constants.py` as `FOLDER_WORKSPACE_TASK`.

### Hard Interrupt Flag

```
{FOLDER_WORKSPACE_TASK}/{session_id}.{pid}.session.agent2llm_interrupt.flag
```

This is a simple marker file. Writing any content to it, for example `1`, requests a hard interrupt. The agent loop checks for the file at safe points, deletes it when detected, and raises a dedicated exception.

### Soft Interrupt Inject File

```
{FOLDER_WORKSPACE_TASK}/{session_id}.{pid}.session.agent2llm_inject_messages.jsonl
```

This file is reused from the existing Agent2LLM runtime message source. The soft interrupt handler appends a JSONL line representing a user message. The runtime message source consumes the file before the next LLM call.

### Pause Marker

```
{FOLDER_WORKSPACE_TASK}/{session_id}.{pid}.session.agent2llm_pause.flag
```

This marker carries a JSON payload instead of a bare flag, because the prompt text, the wait budget and the timeout policy must travel from the control plane to the agent thread:

```json
{"reason": "operator requested pause", "prompt": "Continue? [yes/no] ", "timeout_seconds": 0, "default": "continue"}
```

`timeout_seconds` of `0` waits indefinitely. `default` is `continue` or `interrupt` and decides the outcome when the budget expires. Writers publish it atomically with `mkstemp` plus `os.replace`, so the agent never reads a partial file. The suffix is registered in `context/session_activity.py::_OWNER_SUFFIXES`; an unregistered session-scoped file would be treated as malformed evidence and would block session cleanup permanently.

### Session ID and PID Resolution

The file name uses the same convention as the session stdout tee file and the input pipe:

- `session_id` comes from `env_tool.get_session_id()` or falls back to `"topsailai"`.
- `pid` is `os.getpid()` of the agent process.

The helper `workspace/agent/runtime_message_sources/file.py::get_default_inject_message_file_path` already implements this resolution for the JSONL inject file. The hard interrupt flag uses the same prefix and only changes the suffix.

External writers that target a specific running session can discover the correct `session_id` and `pid` by scanning the task folder for files matching `{session_id}.{pid}.session.stdout` or `{session_id}.{pid}[.{other}].task.stdout`. The CLI script `cli/topsailai_session_add_agent2llm_message.py` demonstrates this discovery pattern.

## Hard Interrupt Flow

### Who Writes the Flag

Any authorized process can write the flag file:

- The control channel handler `hard_interrupt`.
- A CLI utility similar to `topsailai_session_add_agent2llm_message.py`.
- An external automation script that knows the target `session_id` and `pid`.

### Atomic Write

Writers should create a temporary file in the same directory and then rename it to the target path. This avoids the agent reading a partially written marker.

```python
import os
import tempfile

def set_hard_interrupt_flag(path: str) -> bool:
    dir_name = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("1")
        os.replace(tmp_path, path)
        return True
    except Exception:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return False
```

### Safe Check Points

The agent loop checks for the hard interrupt flag at deterministic points where stopping is safe:

- At the start of each ReAct iteration, before calling `_inject_runtime_messages()`.
- Immediately before each LLM call.
- After each tool call returns.
- During streaming response reads, ideally between chunks or at a bounded interval.

The check is implemented inside `ai_base/agent_base.py::AgentRun._run`. If the flag is present, the loop deletes the file and raises `HardInterruptError`.

### Dedicated Exception

A new exception class is introduced, for example `HardInterruptError`. It can live in `ai_base/exception.py` or `workspace/agent/agent_constants.py`. It must not be a subclass of `AssertionError` or any exception that is swallowed by generic catch-all handlers.

```python
class HardInterruptError(Exception):
    """Raised when a hard interrupt is requested via the control channel."""
```

### Flag Cleanup

When the agent detects the flag, it deletes the file immediately. If deletion fails, the agent logs a warning and continues with the interrupt anyway. The outer loop is responsible for preventing the same stale flag from triggering another interrupt on the next turn.

### Outer Loop Behavior

`workspace/agent/agent_shell_base.py::AgentChat._run` catches `HardInterruptError`:

- It stops the current agent loop.
- It sets `self.interrupted = True` on the `AgentChat` instance.
- It records the interrupted state in the session metadata if appropriate.
- It does not save an assistant answer for the aborted turn.

Before starting a new agent loop on the next user input, `AgentChat._run` checks `self.interrupted`. If true, it requires a non-empty new user message. Receiving that message clears `self.interrupted` and starts a fresh Agent2LLM loop. The fresh loop begins with a clean context, so any stale flag from the previous loop is irrelevant unless it is rewritten.

## Soft Interrupt Flow

### Message Payload

The soft interrupt handler appends a single JSONL line to the inject file. The payload follows the schema already used by `workspace/agent/runtime_message_sources/file.py::write_message`:

```json
{"role": "user", "content": "请立即总结当前已完成的进展，给出最终结论，并结束本次任务。", "step_name": "observation", "ts": "2026-08-04T00:00:00+00:00"}
```

- `role`: always `user` so the agent treats it as a new user turn.
- `content`: the interrupt request text.
- `step_name`: `observation` to align with runtime message injection conventions.
- `ts`: ISO 8601 UTC timestamp for observability. The consumer strips this field before injecting the message.

### Consumption

`FileAgent2LLMMessageSource.consume_messages` reads the entire file, parses each line, clears the file, and returns the parsed messages. `ai_base/agent_base.py::_inject_runtime_messages` appends those messages to `self.messages` before the next LLM call.

### Expected Agent Behavior

After injection, the agent sees a new user message in its context. The next LLM call will generate a response to that message. With a well-designed prompt, the agent summarizes progress and returns a final answer, ending the ReAct loop normally. No exception is raised and no flag file is created.

## Pause Flow

### Two-Stage Delivery

The control plane only delivers intent; the execution plane blocks. `PauseHandler` writes the marker and returns `{"state": "pause_requested"}` immediately. The agent main thread consumes the marker at a safe point and blocks on the continue prompt.

A blocking handler is impossible here: `cli_topsailai/runtime_control.py::send_to_control` requires a correlated response frame within a short default budget, the control thread would stay occupied and starve `heartbeat` and `hard_interrupt`, and the protocol has no channel to return the human's answer. Acceptance therefore never means the agent has already paused, exactly like `hard_interrupt`.

### Consumption and Prompting

`ai_base/agent_base.py::AgentRun._check_pause_request` runs immediately after each `_check_hard_interrupt()` call, so a hard interrupt always wins. It:

1. Returns immediately unless `KEY_AGENT_DEEP` is `1`. Nested subagents share the same session and pid path but have no usable interactive input, so they would degrade to the default answer and leave the parent unable to pause.
2. Reads and deletes the marker before prompting, so the request is consumed exactly once and repeated requests cannot stack a second prompt. A malformed payload is still consumed and falls back to the default prompt and default policy.
3. Prompts through `utils/input_tool.py::input_yes_or_no_with_timeout`, preferring the agent-runtime input channel and falling back to the terminal. The wait is sliced into roughly one-second polls and `_check_hard_interrupt()` runs between slices, so a pause stays interruptible.
4. Raises `HardInterruptError` when the answer is no, reusing the verified `AgentChat._run` interrupted path: no fake answer is saved, the session stays open and the next user message starts a fresh loop.

The banner is printed with `print(..., flush=True)` rather than `print_info()`, because `print_info()` is gated by `is_print_enabled()` and would silently drop the prompt in exactly the non-interactive case where the operator needs to see it.

### Constraints

- Pause is never checked during streaming. `ai_base/llm_base.py::_check_stream_interrupt` stays hard-interrupt only, because blocking mid-response would break the pairing between the response message and its tool calls.
- Pause is never checked at the User2Agent input prompt, which is already waiting for a human.
- When neither a runtime input channel nor a TTY exists, the agent logs a warning and continues instead of blocking forever.
- On startup, `workspace/agent_shell.py::_cleanup_stale_interrupt_flag` removes both the hard interrupt flag and the pause marker, so a restarted process never inherits a pause nobody asked for.

## Control Channel Handlers

`workspace/control_handlers/interrupt.py` provides the interrupt handlers and `workspace/control_handlers/pause.py` provides the pause handlers:

| Action | Class | Behavior |
|---|---|---|
| `hard_interrupt` | `HardInterruptHandler` | Writes the hard interrupt flag file for the target session. |
| `soft_interrupt` | `SoftInterruptHandler` | Appends a terminate-and-summarize user message to the inject JSONL file. |
| `clear_interrupt` | `ClearInterruptHandler` | Removes the hard interrupt flag file if it exists. Optional, mainly for external tooling. |
| `pause` | `PauseHandler` | Writes the pause marker carrying prompt, timeout and default policy. |
| `clear_pause` | `ClearPauseHandler` | Removes an unconsumed pause marker if it exists. |

### Required ControlContext Fields

The handlers need enough context to build the correct file paths:

- `session_id`: target session identifier.
- `pid`: target process identifier.
- `task_folder`: resolved `FOLDER_WORKSPACE_TASK` path.

If `ControlContext` already carries an `agent_chat` or `agent_object` reference, `HardInterruptHandler` can also set an in-memory interrupt flag for faster detection. However, the file-based flag remains the authoritative signal and must always be written.

## State Machine

The session moves through the following states with respect to control handling:

| State | Description |
|---|---|
| `running` | The agent loop is executing normally. |
| `pause_requested` | A pause marker was written. The agent has not reached a safe point yet. |
| `paused` | The marker was consumed and the agent is blocked on the continue prompt. |
| `interrupted` | A hard interrupt was requested, or a pause was answered no, and the current loop has stopped. No new loop starts until the user sends a message. |
| `resuming` | A new user message has arrived and the next agent loop is starting. This is a transient state. |

Transitions:

- `running` -> `pause_requested`: the `pause` handler writes the marker.
- `pause_requested` -> `paused`: the agent consumes the marker at a safe point and starts prompting.
- `paused` -> `running`: the answer is yes, or the timeout default is `continue`.
- `paused` -> `interrupted`: the answer is no, or the timeout default is `interrupt`.
- `pause_requested` -> `interrupted`: a hard interrupt arrives first and discards the unconsumed marker.
- `running` -> `interrupted`: hard interrupt flag is detected inside the agent loop.
- `interrupted` -> `resuming`: user provides a new message.
- `resuming` -> `running`: the new agent loop begins successfully.
- `running` -> `running`: soft interrupt injects a message; the agent loop ends naturally after summarization.

## Error Handling and Edge Cases

### Missing Session ID or PID

Handlers must validate `session_id` and `pid`. If either is missing, the handler returns an error response without touching the filesystem.

### Concurrent Hard and Soft Interrupt

Both files are independent. A hard interrupt may stop the loop before the soft interrupt message is consumed. A soft interrupt may be consumed first and the loop may end naturally before the hard interrupt flag is checked. This is acceptable because both actions express the user's intent to stop the current task.

### Concurrent Pause and Hard Interrupt

A hard interrupt always wins. `_check_hard_interrupt()` clears any unconsumed pause marker before raising `HardInterruptError`, so a pause request that arrives together with a hard interrupt cannot leave a marker behind that would pause the next loop unexpectedly. If the pause marker was already consumed and the agent is blocked on the continue prompt, the sliced polling loop rechecks the hard interrupt between slices and abandons the prompt.

### Pause Without an Input Channel

When neither a TTY nor a runtime input function is available, the pause checkpoint must not block forever. It logs a warning and applies the payload `default` (fail-open), so a headless deployment degrades to a no-op instead of hanging the session.

### Pause Timeout

`timeout_seconds` defaults to `0`, which waits indefinitely. A positive value bounds the wait; on expiry the payload `default` decides between `continue` and `interrupt`. An indefinite wait is intentional for interactive operation but means an unanswered pause keeps the session blocked until a hard interrupt or process exit.

### Agent Not Running

If the flag file is written when no agent loop is active, the next loop that starts will detect the stale flag immediately and raise `HardInterruptError`. The outer loop should treat a stale flag at startup as a no-op and clear it, because there is no running task to interrupt.

### Tool Call in Progress

If a hard interrupt arrives while a tool call is executing, the flag cannot be checked until the tool returns. Long-running tools should therefore support cooperative cancellation where possible. The tool call decorator can also check the flag for tools that are expected to run for a long time.

### Process Restart

The flag file may outlive the agent process. On startup, `AgentChat` should check for and remove any existing flag file for its own `session_id` and `pid` before entering the main loop. This prevents a stale flag from immediately interrupting a fresh session.

## Security and Approval

Interrupting an agent is a destructive control action. The control channel should respect the same authorization boundaries as other runtime control operations:

- If tool approval is enabled, hard interrupt should be logged and may require approval depending on deployment policy.
- All interrupt requests should be recorded in the event log with the requester identity, timestamp, and action type.
- External writers must have write access to `FOLDER_WORKSPACE_TASK`. The agent process should run with a dedicated user or group so that arbitrary processes cannot write interrupt flags.

## Related Files

- `workspace/control_channel/handler.py`: handler registry and base class.
- `workspace/control_handlers/__init__.py`: auto-discovery of business handlers.
- `workspace/control_handlers/message.py`: example handlers that inspect runtime and session messages.
- `workspace/agent/runtime_message_sources/file.py`: file-based Agent2LLM message source.
- `cli/topsailai_session_add_agent2llm_message.py`: CLI utility that writes to the inject file.
- `ai_base/agent_base.py`: Agent2LLM loop where interrupt checks are inserted.
- `workspace/agent/agent_shell_base.py`: User2Agent loop that catches `HardInterruptError` and manages the interrupted state.
- `workspace/folder_constants.py`: resolves `FOLDER_WORKSPACE_TASK`.
- `utils/env_tool.py`: resolves `session_id` from environment.
- `workspace/control_handlers/pause.py`: pause and clear-pause handlers.
- `workspace/folder_utils.py`: resolves the interrupt and pause marker paths.
- `utils/input_tool.py`: generic timeout-aware yes/no prompt used by the pause checkpoint.
- `tests/bdd/features/control_pause.feature`: acceptance scenarios for the pause flow.
- `tests/bdd/steps/control_pause_steps.py`: real control server, real ReAct loop, and real session FIFO steps.
- `tests/bdd/test_control_pause.py`: pytest-bdd entry point for the pause scenarios.

## Open Decisions

1. Should `HardInterruptError` live in `ai_base/exception.py` or `workspace/agent/agent_constants.py`?
2. Should the control channel expose a query action, for example `get_interrupt_state`, so external tools can check whether a session is currently interrupted?
3. Should the hard interrupt flag carry a payload, such as a reason or timestamp, or remain a simple boolean marker?
4. Should stale flag cleanup on startup also remove stale inject JSONL files from previous process lifetimes?
5. Should the control channel expose a `get_pause_state` action so external tooling can distinguish `pause_requested` from `paused` without reading the marker file?
