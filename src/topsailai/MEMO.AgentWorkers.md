# MEMO: Agent Workers

This document collects design notes, conventions, and known pitfalls for the **Agent Workers** layer:

- `ai_team/` — Team work mode
- `workspace/` — Worker Entry

## MEMO: Print Usage Restriction

**Date:** 2026-07-02
**File:** `/TopsailAI/src/topsailai/workspace/agent/agent_shell_base.py` (and similar agent/workspace modules)

### Rule
`print()` may only be used when the process is in **interactive mode** or **debug mode**:

```python
if env_tool.is_interactive_mode() or env_tool.is_debug_mode():
    print(...)
```

In all other modes, `print()` output must be avoided so that non-interactive runs stay clean and machine-readable.

### Example from `agent_shell_base.py`

```python
if not env_tool.is_debug_mode() or not env_tool.is_interactive_mode():
    print(answer)

if env_tool.is_interactive_mode() or env_tool.is_debug_mode():
    print()
    print(SPLIT_LINE)
    print(f"[{self.agent_name}] have scheduled tasks [{curr_count}] times")
    ...
```

### Note for maintainers
When adding console output to workspace/agent code, always gate it behind `env_tool.is_interactive_mode() or env_tool.is_debug_mode()`. Prefer the project's logger (`from topsailai.logger import logger` or `logging.getLogger(__name__)`) for diagnostics that should be emitted regardless of mode.

## MEMO: Session Stdout and Pipe Filename Convention

**Date:** 2026-07-02
**Files:**
- `/TopsailAI/src/topsailai/workspace/print_tool.py`
- `/TopsailAI/src/topsailai/workspace/input_tool.py`
- `/TopsailAI/cli/topsailai.py`

### Conclusion
The session stdout tee file and the session input pipe both use filenames that include the process ID so multiple concurrent processes do not collide, and include the session ID when one is available.

The filename formats are:

| Resource | No session ID | With session ID |
|----------|---------------|-----------------|
| Stdout tee | `topsailai.{pid}.session.stdout` | `{session_id}.{pid}.session.stdout` |
| Input pipe | `topsailai.{pid}.session.pipe` | `{session_id}.{pid}.session.pipe` |

For example, a process with PID `12345` and no session writes stdout to `topsailai.12345.session.stdout` and reads input from `topsailai.12345.session.pipe`; with session ID `abc-001` the files are `abc-001.12345.session.stdout` and `abc-001.12345.session.pipe`.

### Note for maintainers
When adding new consumers of the session stdout tee file or input pipe, always parse the filename rather than constructing it from a fixed pattern. The PID component is required to disambiguate concurrent processes, and the session-id component is optional for temporary sessions.

## MEMO: Sending Messages via the Session Input Pipe

**Date:** 2026-07-02
**Files:**
- `/TopsailAI/cli/topsailai.py`
- `/TopsailAI/src/topsailai/workspace/input_tool.py`
- `/TopsailAI/src/topsailai/utils/input_tool.py`
- `/TopsailAI/src/topsailai/docs/Environment_Variables.md`

### Conclusion
When `TOPSAILAI_INPUT_PIPE_ENABLED=1`, a running session reads user input from a session-scoped named pipe instead of `stdin`. Messages can be sent either with the `cli/topsailai.py` `/send` command or by writing directly to the pipe file. Multi-line messages must be terminated with the `EOF` marker on its own line.

### Pipe filename
The pipe filename follows the same convention as the session stdout tee file (see "MEMO: Session Stdout and Pipe Filename Convention"):

| Session | Pipe path |
|---------|-----------|
| No session (temporary) | `{TOPSAILAI_HOME}/workspace/task/topsailai.{pid}.session.pipe` |
| With session ID | `{TOPSAILAI_HOME}/workspace/task/{session_id}.{pid}.session.pipe` |

The PID is the process ID of the running agent/LLM process that owns the stdout file. Use the stdout filename to determine both the session ID and PID.

### Sending a single-line message directly
Write the message followed by a newline and the `EOF` terminator:

```bash
# With session ID and PID
echo -e "hello\nEOF\n" > /root/.topsailai/workspace/task/abc-001.12345.session.pipe

# Temporary session
echo -e "hello\nEOF\n" > /root/.topsailai/workspace/task/topsailai.12345.session.pipe
```

The receiver strips the standalone `EOF` line and returns `hello`.

### Sending a multi-line message directly
Write all content lines, then `EOF` on its own line:

```bash
echo -e "line1\nline2\nline3\nEOF\n" > /root/.topsailai/workspace/task/abc-001.12345.session.pipe
```

The receiver returns `line1\nline2\nline3`. Anything on or after the standalone `EOF` line is discarded.

### Sending via `cli/topsailai.py`
The task watcher provides a `/send` command that resolves the session from the stdout file list and formats the payload correctly.

```bash
python /TopsailAI/cli/topsailai.py
```

Inside the watcher:

```
[workspace]> /send 1 hello
[session:abc-001]> /send hello
[session:abc-001]> /send
[INFO] Enter message (type EOF on its own line to finish):
line1
line2
EOF
```

- In workspace scope: `/send <session_id_or_index> [message...]`.
- In session scope: `/send [message...]`.
- If no message is provided, `/send` enters interactive multi-line input mode and finishes when a standalone `EOF` line is entered.

`/send` locates the target process via the stdout file, builds the pipe path as `{session_id}.{pid}.session.pipe`, and writes the payload with `_format_pipe_payload()`, which ensures the message ends with `\nEOF\n`.

### Relevant environment variables
- `TOPSAILAI_INPUT_PIPE_ENABLED` — must be `1` for the receiver to read from the pipe.
- `TOPSAILAI_INPUT_PIPE_TIMEOUT` — timeout in seconds for the receiver waiting on the pipe, and also used by `/send` when opening the pipe for writing.

### Note for maintainers
- Always use the stdout filename to resolve the PID rather than guessing it; multiple sessions may share the same session ID but have different PIDs.
- When writing directly to the pipe, include the `EOF` terminator; otherwise the receiver will keep waiting.
- The receiver's `input_from_pipe` logic strips the first standalone `EOF` marker and everything after it, so do not place meaningful content after `EOF`.
