---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community/scripts/
programming_language: python
references:
  - hermes_agent_cmd_check_health.py
  - hermes_agent_cmd_check_status.py
  - hermes_agent_cmd_chat.py
  - cli/hermes_health.sh
  - cli/hermes_status.py
  - cli/hermes_chat.py
---

# Hermes Agent Command Interface — Implementation Plan

## Overview

This document is the **implementation plan** for `hermes_agent_cmd` wrapper scripts. The Hermes agent exposes a REST API (default `http://127.0.0.1:8642`) for session management and chat. The `cli/` directory contains the **raw/native** command implementations. This plan defines the **wrapper scripts** (`hermes_agent_cmd_xxx.py`) that ACS will actually invoke, translating ACS-standard environment variables into Hermes-native calls.

The wrapper pattern follows `topsailai_agent_cmd`:
- Read `ACS_*` environment variables (per ORIGIN.md `agent_interface` spec).
- Map them to `HERMES_*` variables expected by `cli/` scripts.
- Invoke the underlying `cli/` script via `subprocess`.
- Pass through stdout, stderr, and exit code.
- Handle edge cases (missing session, group context initialization, mode switching).

---

## File Structure (Target)

```
scripts/hermes_agent_cmd/
├── cli/
│   ├── hermes_chat.py          # [EXISTS] Native chat client
│   ├── hermes_health.sh        # [EXISTS] Native health check
│   └── hermes_status.py        # [EXISTS] Native status check
├── hermes_agent_cmd_check_health.py   # [TO WRITE] Wrapper for health
├── hermes_agent_cmd_check_status.py   # [TO WRITE] Wrapper for status
├── hermes_agent_cmd_chat.py           # [TO WRITE] Wrapper for chat
└── hermes_agent_cmd.md                # [THIS DOC] Implementation plan
```

> **Note on compiled binaries:** Scripts in `cli/` may be compiled to binary files without extensions (e.g., `hermes_chat.py` → `hermes_chat`). Wrappers MUST look for both forms and prefer the compiled binary if present.

---

## Environment Variable Mapping

All wrapper scripts read the ACS-standard variables and map them as follows:

| ACS Variable (Input) | Maps To | Target Variable | Used By |
|----------------------|---------|-----------------|---------|
| `ACS_AGENT_API_BASE` | `HERMES_API_BASE` | `cli/` scripts | All |
| `ACS_AGENT_API_KEY` | `HERMES_API_KEY` | `cli/` scripts | All |
| `ACS_AGENT_API_AUTH` | Ignored | — | All |
| `ACS_AGENT_TIMEOUT` | `HERMES_AGENT_TIMEOUT` | `cli/` scripts | chat |
| `ACS_GROUP_ID` | `session_id` | CLI arg / env | status, chat |
| `ACS_AGENT_MESSAGE` | `message` | CLI arg / env | chat |
| `ACS_AGENT_MODE` | Mode logic | Internal | chat |
| `ACS_AGENT_TYPE` | Mode logic | Internal | chat |
| `ACS_AGENT_PROMPT` | `system_message` | CLI arg / env | chat |
| `ACS_GROUP_CONTEXT` | Session init message | Internal | chat |

> `ACS_AGENT_API_AUTH`: Hermes `cli/` scripts only support Bearer token via `HERMES_API_KEY`. The auth scheme is fixed to Bearer. Unsupported auth schemes are silently ignored — the wrapper does NOT explicitly fail.

---

## Script Discovery (Compiled Binary Support)

All wrapper scripts MUST implement a `find_cli_executable(name)` helper that resolves the correct `cli/` executable:

```python
def find_cli_executable(name: str) -> str:
    """
    Find the cli executable for the given name.
    Looks for compiled binary first, then .py script.
    e.g., name='hermes_chat' -> tries 'cli/hermes_chat', then 'cli/hermes_chat.py'
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cli_dir = os.path.join(script_dir, "cli")

    # Try compiled binary first (no extension)
    binary_path = os.path.join(cli_dir, name)
    if os.path.isfile(binary_path) and os.access(binary_path, os.X_OK):
        return binary_path

    # Fallback to Python script
    py_path = os.path.join(cli_dir, f"{name}.py")
    if os.path.isfile(py_path):
        return py_path

    raise FileNotFoundError(f"Neither {name} nor {name}.py found in {cli_dir}")
```

---

## Script 1: `hermes_agent_cmd_check_health.py`

### Purpose
Wrap `cli/hermes_health.sh` to provide an ACS-compatible health check.

### Behavior
1. Read `ACS_AGENT_API_BASE` → set `HERMES_API_BASE`.
2. Read `ACS_AGENT_API_KEY` → set `HERMES_API_KEY`.
3. Discover the cli executable via `find_cli_executable("hermes_health")`.
4. Execute `cli/hermes_health.sh` via `subprocess`.
5. Capture stdout (raw HTTP response body).
6. **Parse the JSON response.** If the `status` field is not `"ok"`, print error to stderr and exit with code `1`.
7. If healthy, print the raw response to stdout and exit with code `0`.

### Exit Codes
| Code | Meaning |
|------|---------|
| `0` | Agent is healthy (`status: ok` in response) |
| `1` | Agent is unhealthy, HTTP error, network failure, or invalid JSON |

### Input
- Environment variables only (no CLI arguments).

### Output
- **stdout:** Raw JSON response from `/health` (e.g., `{"status":"ok"}`).
- **stderr:** Error details on failure.

### Error Handling
- If `ACS_AGENT_API_BASE` is missing, the underlying script defaults to `http://127.0.0.1:8642`.
- If `ACS_AGENT_API_KEY` is missing, the underlying script will fail (curl without auth may get 401).
- If the response is not valid JSON, treat as unhealthy (exit `1`).
- If the `status` field is missing or not `"ok"`, treat as unhealthy (exit `1`).

### Example
```bash
ACS_AGENT_API_BASE=http://127.0.0.1:8642 ACS_AGENT_API_KEY=xxx ./hermes_agent_cmd_check_health.py
# stdout: {"status":"ok"}
# exit: 0
```

---

## Script 2: `hermes_agent_cmd_check_status.py`

### Purpose
Wrap `cli/hermes_status.py` to provide an ACS-compatible status check that outputs a plain status string.

### Behavior
1. Read `ACS_AGENT_API_BASE` → set `HERMES_API_BASE`.
2. Read `ACS_AGENT_API_KEY` → set `HERMES_API_KEY`.
3. Read `ACS_GROUP_ID` → use as `session_id`.
4. Discover the cli executable via `find_cli_executable("hermes_status")`.
5. Execute `cli/hermes_status.py <session_id>` via `subprocess`.
6. Capture stdout (JSON output from native script).
7. Parse JSON, extract the `"status"` field value (`idle`, `processing`, `not_found`, `error`).
8. Print **only** the status string to stdout.
9. Exit with code `0` if the script executed successfully (even if status is `not_found` or `error` — per spec, `ret_code=0` means the check itself succeeded).

### Exit Codes
| Code | Meaning |
|------|---------|
| `0` | Status check executed successfully (stdout contains the status string) |
| `1` | Missing `ACS_GROUP_ID`, cli executable not found, or the underlying script crashed |

### Input
- `ACS_GROUP_ID` (required): Maps to Hermes `session_id`.
- `ACS_AGENT_API_BASE` (optional).
- `ACS_AGENT_API_KEY` (optional).

### Output
- **stdout:** Plain status string — one of `idle`, `processing`, `not_found`, `error`.
- **stderr:** Forwarded from underlying script (human-readable summary).

### Error Handling
- If `ACS_GROUP_ID` is empty/missing, print error to stderr and exit `1`.
- If the cli executable is not found, print error to stderr and exit `1`.
- If the underlying script returns non-zero, forward stderr and exit `1`.
- If the underlying script outputs invalid JSON, print error to stderr and exit `1`.

### Example
```bash
ACS_AGENT_API_BASE=http://127.0.0.1:8642 ACS_AGENT_API_KEY=xxx ACS_GROUP_ID=group-abc \
  ./hermes_agent_cmd_check_status.py
# stdout: idle
# exit: 0
```

---

## Script 3: `hermes_agent_cmd_chat.py`

### Purpose
Wrap `cli/hermes_chat.py` to provide an ACS-compatible chat invocation.

### Behavior

#### Step 1: Environment Setup
1. Read `ACS_AGENT_API_BASE` → set `HERMES_API_BASE`.
2. Read `ACS_AGENT_API_KEY` → set `HERMES_API_KEY`.
3. Read `ACS_AGENT_TIMEOUT` → set `HERMES_AGENT_TIMEOUT` (maps directly; cli script handles default 600, min 300).
4. Read `ACS_GROUP_ID` → use as `--session` argument.
5. Read `ACS_AGENT_MESSAGE` → use as the message positional argument.
6. Read `ACS_AGENT_PROMPT` → if non-empty, pass as `--system` argument.

#### Step 2: Group Context Initialization (Optional)
If `ACS_GROUP_CONTEXT` is non-empty:
1. Call `hermes_agent_cmd_check_status.py` with the same environment.
2. If exit code == 0 **and** stdout contains `"not_found"` (session does not exist):
   - Send `ACS_GROUP_CONTEXT` as an initial user message to create and seed the session.
   - Execute: `hermes_chat.py --session <group_id> --system "" "<group_context>"`
   - This establishes the session with group context as a **user message** before the real message.

> Rationale: When `last_read_message_id` is empty, ACS passes `ACS_GROUP_CONTEXT`. The Hermes session model requires a session to exist before chatting. If the session is missing, we seed it with the group context as a user message (NOT a system message, per review decision).

#### Step 3: Mode Handling
| `ACS_AGENT_MODE` | `ACS_AGENT_TYPE` | Action |
|------------------|------------------|--------|
| `chat` | `manager-agent` | Send message normally |
| `chat` | not `manager-agent` | Append to message: `\n! DONOT INVOKE ANY TOOLS/SKILLS, Think directly and give the final answer !` |
| `agent` (or any other) | any | Send message normally |

#### Step 4: Invoke Chat
Discover the cli executable via `find_cli_executable("hermes_chat")`, then execute with constructed arguments:
```bash
hermes_chat.py \
  --session <ACS_GROUP_ID> \
  [--system <ACS_AGENT_PROMPT>] \
  "<message_content>"
```

> Note: The cli script also accepts `HERMES_USER_MESSAGE` and `HERMES_SYSTEM_PROMPT` env vars. Use environment variables as the PRIMARY mechanism (not CLI arguments).

#### Step 5: Pass Through
Forward stdout, stderr, and exit code directly to ACS.

### Exit Codes
| Code | Meaning |
|------|---------|
| `0` | Message sent and response received successfully |
| `1` | Missing required env var, cli executable not found, API error, or network failure |

### Input (Environment Variables)
| Variable | Required | Description |
|----------|----------|-------------|
| `ACS_AGENT_API_BASE` | No | Hermes API base URL |
| `ACS_AGENT_API_KEY` | No | Bearer token |
| `ACS_AGENT_TIMEOUT` | No | HTTP timeout in seconds (default 600, min 300 enforced by cli) |
| `ACS_GROUP_ID` | **Yes** | Session ID |
| `ACS_AGENT_MESSAGE` | **Yes** | Message content to send |
| `ACS_AGENT_MODE` | No | `chat` or `agent` |
| `ACS_AGENT_TYPE` | No | `manager-agent` or `worker-agent` |
| `ACS_AGENT_PROMPT` | No | System prompt / instructions |
| `ACS_GROUP_CONTEXT` | No | Group context for session initialization (sent as user message) |

### Output
- **stdout:** Agent's response content (plain text, from `cli/hermes_chat.py`).
- **stderr:** Info/warning messages (session creation, errors).

### Error Handling
- If `ACS_GROUP_ID` is missing, print error to stderr and exit `1`.
- If `ACS_AGENT_MESSAGE` is missing, print error to stderr and exit `1`.
- If the cli executable is not found, print error to stderr and exit `1`.
- If `cli/hermes_chat.py` exits non-zero, pass through stdout/stderr/exit code unchanged.
- If session initialization (group context) fails, log warning to stderr but continue with the main message.

### Known Limitations
1. **Streaming:** `cli/hermes_chat.py` does not support SSE streaming via stdlib. The wrapper does not add streaming support.
2. **Session Mapping:** Hermes `session_id` is directly mapped from `ACS_GROUP_ID`. No separate mapping table is maintained.
3. **Session Auto-Creation:** The cli script auto-creates sessions when not found (if `DEBUG=1`). The wrapper explicitly handles session creation via group context to ensure deterministic behavior.

### Example
```bash
export ACS_AGENT_API_BASE=http://127.0.0.1:8642
export ACS_AGENT_API_KEY=xxx
export ACS_GROUP_ID=group-abc
export ACS_AGENT_MESSAGE="What is the weather?"
export ACS_AGENT_MODE=agent
export ACS_AGENT_PROMPT="You are a helpful assistant."

./hermes_agent_cmd_chat.py
# stdout: The weather today is sunny with a high of 25°C.
# exit: 0
```

---

## Shared Implementation Details

### Finding `cli/` Scripts
All wrapper scripts must locate the `cli/` directory relative to themselves and support compiled binaries:

```python
import os

def find_cli_executable(name: str) -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cli_dir = os.path.join(script_dir, "cli")

    # Try compiled binary first (no extension)
    binary_path = os.path.join(cli_dir, name)
    if os.path.isfile(binary_path) and os.access(binary_path, os.X_OK):
        return binary_path

    # Fallback to Python script
    py_path = os.path.join(cli_dir, f"{name}.py")
    if os.path.isfile(py_path):
        return py_path

    raise FileNotFoundError(f"Neither {name} nor {name}.py found in {cli_dir}")
```

### Subprocess Invocation Pattern
```python
import os
import subprocess
import sys
import json

env = os.environ.copy()
# Map ACS_* to HERMES_*
if env.get("ACS_AGENT_API_BASE"):
    env["HERMES_API_BASE"] = env["ACS_AGENT_API_BASE"]
if env.get("ACS_AGENT_API_KEY"):
    env["HERMES_API_KEY"] = env["ACS_AGENT_API_KEY"]
if env.get("ACS_AGENT_TIMEOUT"):
    env["HERMES_AGENT_TIMEOUT"] = env["ACS_AGENT_TIMEOUT"]

result = subprocess.run(
    [cmd_path, ...args],
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
sys.exit(result.returncode)
```

### JSON Parsing Safety
When parsing stdout from `cli/` scripts, always handle:
- `json.JSONDecodeError` → treat as error, exit `1`.
- Empty stdout → treat as error, exit `1`.
- Missing expected keys → treat as error, exit `1`.

---

## Dependencies

- **Python 3.7+** (all wrapper scripts are Python).
- **No third-party packages** — use only stdlib (`os`, `sys`, `subprocess`, `json`).
- **External binaries used by `cli/`:**
  - `curl` (used by `hermes_health.sh`)
  - `python3` (used by `hermes_chat.py`, `hermes_status.py`)

---

## Testing Checklist (Post-Implementation)

- [ ] `hermes_agent_cmd_check_health.py` returns `0` when Hermes is healthy.
- [ ] `hermes_agent_cmd_check_health.py` returns `1` when Hermes returns non-ok status or invalid JSON.
- [ ] `hermes_agent_cmd_check_status.py` outputs plain `idle` / `processing` / `not_found` / `error` to stdout.
- [ ] `hermes_agent_cmd_check_status.py` returns `1` when `ACS_GROUP_ID` is missing.
- [ ] `hermes_agent_cmd_chat.py` sends message and returns agent response.
- [ ] `hermes_agent_cmd_chat.py` appends "DONOT INVOKE ANY TOOLS/SKILLS" when `ACS_AGENT_MODE=chat` and `ACS_AGENT_TYPE!=manager-agent`.
- [ ] `hermes_agent_cmd_chat.py` initializes session with `ACS_GROUP_CONTEXT` as user message when session does not exist.
- [ ] `hermes_agent_cmd_chat.py` passes `ACS_AGENT_PROMPT` as `--system`.
- [ ] `hermes_agent_cmd_chat.py` maps `ACS_AGENT_TIMEOUT` to `HERMES_AGENT_TIMEOUT`.
- [ ] `hermes_agent_cmd_chat.py` returns `1` when `ACS_GROUP_ID` or `ACS_AGENT_MESSAGE` is missing.
- [ ] All scripts correctly map `ACS_AGENT_API_BASE` → `HERMES_API_BASE` and `ACS_AGENT_API_KEY` → `HERMES_API_KEY`.
- [ ] All scripts prefer compiled binary (`cli/hermes_chat`) over Python script (`cli/hermes_chat.py`) when both exist.

---

*Plan version: 2026-06-16*
*Author: AI (km3-programmer)*
*Review target: Human.DawsonLin*
