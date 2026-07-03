# `topsailai_session_add_agent2llm_message.py`

Inject runtime messages into the **Agent2LLM** context of a running TopsailAI session.

---

## Background and Purpose

TopsailAI separates conversation into two layers:

- **User2Agent** — persisted human-to-agent conversation.
- **Agent2LLM** — ephemeral agent-to-LLM ReAct context.

Sometimes it is useful to push external messages into the Agent2LLM context while a session is already running — for example, to provide an observation, reminder, or injected instruction from another process or automation. The Agent2LLM runtime message injection feature supports this by maintaining a pluggable `Agent2LLMMessageSource` in thread-local storage. Before each LLM call, `ai_base` consumes messages from this source and appends them to the agent's working context.

This CLI script is the external writer side of that mechanism: it discovers running sessions and appends messages to the file-based message source so the running agent will pick them up on its next LLM turn.

### When to Use It

- You want to send a message to a running agent without restarting it.
- You want to broadcast the same message to all active sessions.
- You want another script or cron job to feed observations into the agent loop.

---

## Design Logic

### 1. Session Discovery

Active sessions leave a stdout tee file in `{TOPSAILAI_HOME}/workspace/task/` with the naming convention:

```
{session_id}.{pid}.session.stdout
```

When `--session_id` or `--pid` is omitted, the script scans that directory, matches files against the pattern, and derives one target JSONL file per match:

```
{session_id}.{pid}.session.agent2llm_inject_messages.jsonl
```

This mirrors the convention used by the session stdout tee and input pipe (see `MEMO.AgentWorkers.md` and `workspace/folder_constants.py`).

### 2. File-Based Message Source

The actual read/write implementation lives in:

- `/TopsailAI/src/topsailai/workspace/agent/runtime_message_sources/file.py`

Key behaviors:

- `FileAgent2LLMMessageSource` reads from a JSONL file.
- `consume_messages()` reads the file, parses each line, then **clears the file** so messages are injected exactly once.
- `write_message()` appends a JSON line and adds a top-level `ts` ISO 8601 UTC timestamp. The timestamp is for logging/representation only; `apply_agent2llm_message_source()` strips it before injection.
- The file is removed on process exit via `atexit`.

### 3. Pre-Run Hook Registration

The source is installed before each agent run by:

- `/TopsailAI/src/topsailai/workspace/agent/hooks/pre_run_agent2llm_source.py`

It reads environment variables (`TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED`, `TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_SOURCE`, `TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_FILE`), creates the source, and stores it in thread-local storage via `set_agent2llm_message_source()`. `ai_base` later retrieves it with `get_agent2llm_message_source()`.

### 4. Input Modes

The script supports two input styles, consistent with `/send` in `cli/topsailai.py`:

- **Single-line**: `--message "your message"`
- **Interactive multi-line**: if `--message` is omitted, the script prompts the user to type lines and finish with `EOF` on its own line.

### 5. Abstraction

The `Agent2LLMMessageSource` base class in:

- `/TopsailAI/src/topsailai/ai_base/agent2llm_message_source.py`

keeps `ai_base/` free of `workspace/` imports. Future sources (e.g. Redis, socket, shared memory) can be added by implementing `produce_message()` and `consume_messages()` and registering them via the same pre-run hook.

---

## Usage Examples

### Specific session and PID

```bash
python /TopsailAI/cli/topsailai_session_add_agent2llm_message.py \
  -s abc-001 -p 12345 -m "Please also check the database logs"
```

### Interactive multi-line input

```bash
python /TopsailAI/cli/topsailai_session_add_agent2llm_message.py \
  -s abc-001 -p 12345
[INFO] Enter message (type EOF on its own line to finish):
Check the database logs
Then summarize the recent errors
EOF
```

### Auto-discover all active sessions (broadcast)

```bash
python /TopsailAI/cli/topsailai_session_add_agent2llm_message.py \
  -m "Broadcast: system maintenance in 5 minutes"
```

### Direct JSONL file override

```bash
python /TopsailAI/cli/topsailai_session_add_agent2llm_message.py \
  --file-path /path/to/messages.jsonl -m "direct write"
```

---

## File Naming Conventions

| Resource | Path |
|---|---|
| Session stdout tee | `{TOPSAILAI_HOME}/workspace/task/{session_id}.{pid}.session.stdout` |
| Inject message source | `{TOPSAILAI_HOME}/workspace/task/{session_id}.{pid}.session.agent2llm_inject_messages.jsonl` |

`{TOPSAILAI_HOME}` defaults to `~/.topsailai` if not set. See `workspace/folder_constants.py` for exact resolution logic.

---

## References

- `/TopsailAI/src/topsailai/ai_base/agent2llm_message_source.py` — abstract source and `apply_agent2llm_message_source()`.
- `/TopsailAI/src/topsailai/workspace/agent/runtime_message_sources/file.py` — file-based implementation.
- `/TopsailAI/src/topsailai/workspace/agent/hooks/pre_run_agent2llm_source.py` — pre-run hook that installs the source.
- `/TopsailAI/cli/topsailai.py` — main CLI watcher; see `/send` for the interactive EOF-terminated input style.
- `/TopsailAI/cli/topsailai_session_add_message.py` — existing session message CLI pattern.
