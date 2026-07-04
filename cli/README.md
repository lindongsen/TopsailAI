# CLI Tools

This directory contains the command-line interface (CLI) tools for the project.

## Structure

```
.
├── cli_topsailai/         # Shared package used by CLI scripts
│   ├── __init__.py
│   └── ...
├── <cli-name>.py          # CLI entry point
├── tests/
│   └── unit/
│       └── <cli-name>/    # Unit tests for the corresponding CLI
│           └── test_*.py
```

The `cli_topsailai` package is a common library that can be imported by any CLI script under this directory.
## Testing

Unit tests for each CLI tool are organized under `tests/unit/{cli-name}/`.

For example:

- `topsailai.py` → `tests/unit/topsailai/`

When adding a new CLI tool, create a matching folder under `tests/unit/` and place its tests there.

## Naming Conventions

### CLI Scripts

All CLI script names should start with `topsailai` to keep the command namespace consistent and easy to discover.

For example:

- `topsailai.py`
- `topsailai_launch_agent.py`
- `topsailai_session_status.py`

When adding a new CLI tool, prefix its entry-point script with `topsailai` (e.g., `topsailai_<feature>.py`).

## Session Output Files

The `topsailai.py` stream watcher discovers session and task stdout/stderr files in the task directory.

- **Session stdout** is produced by a session's main process.
  - Filename format: `{session_id}.{pid}.session.stdout`
  - `{pid}` is the session (parent) process PID.
  - Example: `my-session.1234.session.stdout`

- **Task stdout** is produced by task processes or threads launched by the session.
  - Filename format: `{session_id}.{pid}.{extra}.task.stdout`
  - `{pid}` is the task (child) process PID.
  - `{extra}` is an optional extra identifier (task name, timestamp, etc.) and may itself contain dots, e.g., `abc.123`.
  - Example: `my-session.1235.step-1.task.stdout`

- **Temporary sessions**: when `{session_id}` is `topsailai`, the session id is undefined and is displayed as `(temp)` in the UI.
  - Example: `topsailai.1234.session.stdout` → displayed as `(temp)`.

Legacy filename formats are still accepted for backward compatibility:

- Generic `{name}.{pid}.stdout` / `{name}.{pid}.stderr`
### Sending messages to a running session

When you use `/send` in the stream watcher, the target session PID is resolved in this order:

1. **Task-list PID** — if the selected entry in the discovered file list already records a session PID, use it directly.
2. **Filename PID** — parse the PID from the stdout filename (works for `session.stdout`; for `task.stdout` the filename PID is the task child PID, so it is only used when it already points to a valid session pipe).
3. **`lsof` / `fuser` fallback** — scan the filesystem to find the process currently holding the stdout file and derive the session PID from there.

This prioritizes the authoritative PID recorded by the watcher and only falls back to heuristic methods when necessary.

## Available CLI Tools

### `topsailai_launch_agent.py`

Launch an AI agent driver based on a local `.topsailai/settings.yaml` configuration.

**What it does:**

- Reads `.topsailai/settings.yaml` from the current working directory.
- Selects a configured item via `--item` (default is `default`).
- Merges environment variables in the order: system environment → `_default` → item-specific values.
- Reads the configured context files ( `_default` first, then item-specific files) and appends a workspace folder tree to `TOPSAILAI_CONTEXT_USER_MESSAGE`.
- Writes the assembled context message to a temporary file under `{workspace}/.tmp/` to avoid exceeding environment-variable size limits.
- Launches the configured `ai_agent_driver` using `os.system` by default, or `subprocess.run` when `--subprocess` is passed.
- Cleans up the temporary context file on exit, uncaught exceptions, and `SIGINT`/`SIGTERM`.

**Common options:**

- `--item <name>` — Select a context/environment item defined in `settings.yaml`.
- `--driver <command>` — Override the `ai_agent_driver` value.
- `--dry-run` — Print the resolved command, working directory, and merged environment variables without executing.
- `--subprocess` — Use `subprocess.run()` instead of `os.system()`.

**Driver resolution priority:**

1. `--driver` CLI argument
2. `TOPSAILAI_AGENT_DRIVER` from the selected item or `_default` environment section
3. `ai_agent_driver` field in `settings.yaml`
4. `TOPSAILAI_AGENT_DRIVER` from the OS environment

If `.topsailai/settings.yaml` is missing:

- In an interactive terminal, the script launches a guided setup that asks for the driver command, workspace, default context files, and environment variables, then writes the configuration and continues launching.
- In a non-interactive terminal, the script writes a default configuration file, prints the template, and exits so you can fill in `context._default` before the next run.

### `topsailai_session_add_message` vs `topsailai_session_add_agent2llm_message`

These two commands append messages to a session, but they target different conversation layers and have different lifecycles.

| Command | Conversation layer | When it takes effect | Use case |
|---|---|---|---|
| `topsailai_session_add_message` | `user2agent` — user and agent conversation | Only after the agent restarts; not visible to a running agent | Record a user message or context for the next agent run |
| `topsailai_session_add_agent2llm_message` | `agent2llm` — agent and LLM conversation | Immediately; the running agent reads it on the fly | Leave a "by the way" note for the currently running agent |

In short: use `topsailai_session_add_message` for persistent user-to-agent context, and `topsailai_session_add_agent2llm_message` when you want a running agent to pick up extra instruction right now.

### Interactive message commands in `topsailai.py`

When watching a session in `topsailai.py`, you can inject messages through three different paths. They differ in target layer, delivery mechanism, and when they take effect.

| Command | Target layer | Mechanism | When it takes effect |
|---|---|---|---|
| `/send` | Running agent process | Writes to the session's named pipe | Immediately; the running process receives it right now |
| `/ctx.btw` | `agent2llm` context | Calls `topsailai_session_add_agent2llm_message` to append to `*.session.agent2llm_inject_messages.jsonl` | Immediately; the running agent reads the JSONL before its next LLM call |
| `/ctx.add_msg` | `user2agent` context | Calls `topsailai_session_add_message` to append to the session message store | Only after the agent restarts; not visible to a running agent |

Use `/send` for urgent process-level messages, `/ctx.btw` for extra instructions you want the current agent to pick up on the fly, and `/ctx.add_msg` for context that should persist until the next agent run.
