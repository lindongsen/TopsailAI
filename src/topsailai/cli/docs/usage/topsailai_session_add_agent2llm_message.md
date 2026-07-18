---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_session_add_agent2llm_message

Add a runtime message to the Agent2LLM message source JSONL files.

## Purpose

This command appends a message to the file-based `agent2llm` runtime message source so that a running agent can inject it into the Agent2LLM context before its next LLM call. This is the same mechanism used by the `/ctx.btw` command in `topsailai.py`.

TopsailAI separates conversation into two layers:

- **User2Agent** — persisted human-to-agent conversation.
- **Agent2LLM** — ephemeral agent-to-LLM ReAct context.

Use this command when you want to send a message to a running agent without restarting it, broadcast the same message to all active sessions, or feed observations into the agent loop from another script or automation.

## Invocation

```bash
./topsailai_session_add_agent2llm_message.py -s <session_id> -m "message"
./topsailai_session_add_agent2llm_message.py -s <session_id> -p <pid>
```

Because the script is registered in `../bin/` as `topsailai_session_add_agent2llm_message`, you can also run it as:

```bash
topsailai_session_add_agent2llm_message -s <session_id> -m "message"
```

## Options

| Option | Description |
|--------|-------------|
| `-s`, `--session_id <id>` | Target session ID. If omitted, all sessions are scanned. |
| `-p`, `--pid <pid>` | Target process ID. If omitted, all PIDs are scanned. |
| `-m`, `--message <text>` | Single-line message to inject. If omitted, interactive multi-line input is used (finish with `EOF`). |
| `--file-path <path>` | Override the JSONL file path. When set, `--session_id` and `--pid` are ignored. |

## Target Discovery

When `--file-path` is not set, the script scans `{TOPSAILAI_HOME}/workspace/task/` for stdout files matching:

- `{session_id}.{pid}.session.stdout`
- `{session_id}.{pid}[.{extra}].task.stdout`

It derives the JSONL path as `{session_id}.{pid}.session.agent2llm_inject_messages.jsonl` for each match and writes the message to all discovered targets.

## Design Logic

### Session Discovery

Active sessions leave stdout tee files in `{TOPSAILAI_HOME}/workspace/task/`. The script recognizes two filename conventions:

- Session stdout: `{session_id}.{pid}.session.stdout`
- Task stdout: `{session_id}.{pid}[.{other}].task.stdout`

The task form includes an optional extra identifier (e.g. the task name) after the PID. In both cases the second dot-separated segment is the target PID.

When `--session_id` or `--pid` is omitted, the script scans that directory, matches files against either pattern, and derives one target JSONL file per match:

```
{session_id}.{pid}.session.agent2llm_inject_messages.jsonl
```

This mirrors the convention used by the session stdout tee and input pipe.

### File-Based Message Source

The actual read/write implementation lives in `../../src/topsailai/workspace/agent/runtime_message_sources/file.py`. Key behaviors:

- `FileAgent2LLMMessageSource` reads from a JSONL file.
- `consume_messages()` reads the file, parses each line, then **clears the file** so messages are injected exactly once.
- `write_message()` appends a JSON line and adds a top-level `ts` ISO 8601 UTC timestamp. The timestamp is for logging/representation only; `apply_agent2llm_message_source()` strips it before injection.
- The file is removed on process exit via `atexit`.

### Pre-Run Hook Registration

The source is installed before each agent run by `../../src/topsailai/workspace/agent/hooks/pre_run_agent2llm_source.py`. It reads environment variables (`TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED`, `TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_SOURCE`, `TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_FILE`), creates the source, and stores it in thread-local storage via `set_agent2llm_message_source()`. `ai_base` later retrieves it with `get_agent2llm_message_source()`.

### Input Modes

The script supports two input styles, consistent with `/send` in `topsailai.py`:

- **Single-line**: `--message "your message"`
- **Interactive multi-line**: if `--message` is omitted, the script prompts the user to type lines and finish with `EOF` on its own line.

### Abstraction

The `Agent2LLMMessageSource` base class in `../../src/topsailai/ai_base/agent2llm_message_source.py` keeps `ai_base/` free of `workspace/` imports. Future sources (e.g. Redis, socket, shared memory) can be added by implementing `produce_message()` and `consume_messages()` and registering them via the same pre-run hook.

## File Naming Conventions

| Resource | Path |
|---|---|
| Session stdout tee | `{TOPSAILAI_HOME}/workspace/task/{session_id}.{pid}.session.stdout` |
| Inject message source | `{TOPSAILAI_HOME}/workspace/task/{session_id}.{pid}.session.agent2llm_inject_messages.jsonl` |

`{TOPSAILAI_HOME}` defaults to `~/.topsailai` if not set. See `../../src/topsailai/workspace/folder_constants.py` for exact resolution logic.

## Examples

```bash
# Inject a single-line message into a specific session
topsailai_session_add_agent2llm_message -s my-session -m "check the logs again"

# Inject into a specific PID
topsailai_session_add_agent2llm_message -s my-session -p 1234 -m "hello"

# Interactive multi-line input
topsailai_session_add_agent2llm_message -s my-session
# type message, then EOF on its own line

# Write to an explicit file
topsailai_session_add_agent2llm_message --file-path /path/to/messages.jsonl -m "hello"

# Specific session and PID
python ./topsailai_session_add_agent2llm_message.py \
  -s abc-001 -p 12345 -m "Please also check the database logs"

# Auto-discover all active sessions (broadcast)
python ./topsailai_session_add_agent2llm_message.py \
  -m "Broadcast: system maintenance in 5 minutes"
```

## Notes

- Messages take effect immediately; the running agent reads the JSONL before its next LLM call.
- This is different from `topsailai_session_add_message`, which writes to the persistent `user2agent` context and only takes effect after the agent restarts.

## References

- `../../topsailai_session_add_agent2llm_message.md` — original historical design document.
- `../../src/topsailai/ai_base/agent2llm_message_source.py` — abstract source and `apply_agent2llm_message_source()`.
- `../../src/topsailai/workspace/agent/runtime_message_sources/file.py` — file-based implementation.
- `../../src/topsailai/workspace/agent/hooks/pre_run_agent2llm_source.py` — pre-run hook that installs the source.
- `./topsailai.py` — main CLI watcher; see `/send` for the interactive EOF-terminated input style.
- `./topsailai_session_add_message.py` — existing session message CLI pattern.
