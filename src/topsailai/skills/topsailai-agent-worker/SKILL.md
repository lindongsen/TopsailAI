---
name: topsailai-agent-worker
author: DawsonLin
description: |
  Skill for operating the TopsailAI agent worker: how to launch, drive, monitor,
  and control an AI agent process on this node.

  Trigger this skill whenever the user wants to start or use a TopsailAI agent
  worker, configure a project launch, select an agent mode, manage sessions,
  send control instructions to a running agent, or inspect agent runtime state.

  Typical intents that should route here:
  - "launch an agent in this project" / "start the agent worker"
  - "configure .topsailai/settings.yaml context for a project"
  - "which agent mode should I use" (chats vs plan_tasks vs team)
  - "resume / watch / send a message to a running session"
  - "interrupt or control a running agent"
  - "inspect logs, sessions, or runtime state under ~/.topsailai"
---

# TopsailAI Agent Worker

## What is the agent worker

The TopsailAI agent worker is the process that runs an AI agent. It is launched
from a project directory through `topsailai_launch_agent`, which reads a local
`.topsailai/settings.yaml`, assembles the first-turn context, and starts the
configured agent driver (for example `topsailai_agent_chats` or
`topsailai_agent_plan_tasks`).

The agent runtime stores its generated data under `TOPSAILAI_HOME` (default
`~/.topsailai`): logs under `log/`, sessions and tasks under `workspace/task/`,
memory under `memory/`, skills under `skill/`, and global configuration in
`settings.yaml` plus `.env.local` / `.env`.

## The `topsailai` CLI is the unified entry point

The `topsailai` CLI is the **unified entry point** for the whole TopsailAI
project. It hosts all the usage documentation and detailed capability
introductions through its `doc` scope and the `topsailai docs list|read`
subcommands. Use it to discover, manage, and monitor agent tasks.

This skill is only a **supplementary explanation**. It does not try to
duplicate or become the authoritative source for detailed capability docs —
those live in the CLI's usage docs. For detailed capability documentation,
refer to the CLI usage docs (`topsailai docs list` / `topsailai docs read`).
## When to use

Use this skill when the user wants to:

- Launch an agent worker in a workspace + context project manner.
- Configure or inspect a project-level `.topsailai/settings.yaml`.
- Choose the right agent mode for a task.
- Watch, resume, message, or control a running session.
- Inspect agent runtime logs, sessions, or state.

## Launch workflow

1. Confirm the working directory is the project/workspace root that contains
   (or should contain) `.topsailai/settings.yaml`.
2. Optionally preview the resolved launch without executing:

   ```bash
   topsailai_launch_agent --dry-run
   ```

3. Launch the agent:

   ```bash
   topsailai_launch_agent
   # or select a specific context item
   topsailai_launch_agent --item memo
   ```

4. Observe startup (for example in a tmux session) and confirm the agent is
   running before interacting.

### Driver resolution priority

1. `--driver` CLI argument.
2. `TOPSAILAI_AGENT_DRIVER` from the selected item or `_` environment section.
3. `ai_agent_driver` field in `settings.yaml`.
4. `TOPSAILAI_AGENT_DRIVER` from the OS environment.

## Agent mode selection

| Mode | Use for |
|------|---------|
| `topsailai_agent_chats` | Simple tasks with frequent human-agent interaction; single-agent multi-turn chat. |
| `topsailai_agent_plan_tasks` | Complex tasks where the AI auto-schedules multiple members (subagents) to cooperate. |
| `topsailai_agent_chat` | Single-turn chat (times=1). |
| `topsailai_agent_plan_task` | Single-task planner (times=1). |

When the mode is unclear, let the user choose; do not default to a complex
mode. If a chat-mode task becomes complex, suggest switching modes but note
that the switch itself is not automatically performed.

## Project configuration (`.topsailai/settings.yaml`)

The settings file lives in the current working directory. Example:

```yaml
ai_agent_driver: "topsailai_agent_plan_tasks"
workspace: "."
context:
  _: []
  default: []
  memo: []
environment:
  _:
    TOPSAILAI_INTERACTIVE_MODE: "1"
  default: {}
  memo:
    TOPSAILAI_AGENT_DRIVER: "topsailai_agent_chats"
```

- `_` is the base configuration shared by all items (`_default` is kept for
  backward compatibility).
- Context sources are file paths (strings) or command sources (dicts).
- File paths are relative to `workspace` unless they start with `/`.

### Command context sources

A command source runs a shell command and captures its stdout as context:

```yaml
context:
  _:
    - "README.md"
    - type: command
      command: "git log --oneline -10"
      timeout: 5
      label: "recent-commits"
```

Supported fields: `type` (must be `command`), `command`, `shell` (default
`true`), `timeout` (default `30`), `label`, `on_error` (`include`/`skip`/
`abort`, default `abort`), `cwd` (default `workspace`), `environ`.

### Self environs

The optional top-level `self_environs` section seeds the launcher's own
process environment (for example `TOPSAILAI_HOME`, proxy settings, or
`PYTHONPATH`). These are NOT merged into the launched driver's environment.

```yaml
self_environs:
  TOPSAILAI_HOME: "/custom/home"
  HTTPS_PROXY: "http://proxy.example:3128"
```

## Session management

- List historical sessions with `topsailai_list_sessions`.
- View session details with `topsailai_session_info {session_id}`.
- Read session content with `topsailai_retrieve_messages {session_id}`.
- Resume a session and continue chatting:

  ```bash
  TOPSAILAI_SESSION_ID={session_id} topsailai_agent_chats
  ```

- The interactive watcher `topsailai` scans `{TOPSAILAI_HOME}/workspace/task/`
  for session/task stdout files and lets you watch logs, send messages, launch
  agents, and switch scopes (workspace / runtime / project / session / doc).

## Managing agent tasks with the `topsailai` CLI

`topsailai` is the interactive task watcher and session manager. It scans
`{TOPSAILAI_HOME}/workspace/task/` for session/task stdout files and shows them
as a numbered list, so you can see at a glance which agents are working and
what each session is doing.

```bash
topsailai            # start the interactive watcher
topsailai --tui      # use the two-pane curses UI when watching a log
topsailai --tail-lines 200
```

### Workspace task list (default scope)

On startup the CLI prints the workspace task list. Each row is one discovered
log file and shows `No`, `Session` (or `(temp)` for temporary sessions), `PID`,
`Modified`, and `Created`. From this list you can:

- Type a number and press `Enter` to watch that session's live log (runtime scope).
- `/session <number>` — retrieve the full session context.
- `/send <number> [message]` — send a message to a running session.
- `/resume <number>` — resume an idle session in its project workspace.
- `/agent [<number|folder>]` — launch an agent (no argument runs the YAML-configured command).
- `/refresh` — re-scan the task directory and refresh the list.
- `/clean` — remove expired files from the task directory.
- `cd doc` — enter doc scope to browse usage documentation.
- `scopes` — show introductions and available actions for each scope.
- `q` — quit.

### Scopes

The CLI has five scopes: `[workspace]` (default task list), `[runtime:<id>]`
(live log streaming after selecting a log), `[project]` (recent sessions with
recorded project workspaces and running status), `[session:<id>]` (focused view
of one session), and `[doc]` (Markdown documentation browser).

### Runtime scope (watching a working agent)

While watching a session's live log you can interact with the running agent:

- `/send [message]` — send a message to the running session through its named pipe.
- `/ctx.btw [message]` — inject a by-the-way message into the `agent2llm` context.
- `/meta` — print the session metadata file path.
- `q` or `quit` — leave runtime scope and return to the file list.

### Non-interactive subcommands

```bash
topsailai workspace              # show the task list and exit
topsailai docs list              # list usage docs
topsailai docs read topsailai.md # read a usage doc
topsailai project list           # list managed projects
topsailai project add <path>     # add a project
topsailai models list            # list model registry entries
```

## Controlling a running agent

Use `topsailai_send_control` to send JSONL control requests over the session's
Unix domain socket:

```bash
# Hard interrupt all running sessions
topsailai_send_control --command hard_interrupt

# Soft interrupt a specific session
topsailai_send_control --session_id my-session --command soft_interrupt

# Retrieve runtime messages from a specific process
topsailai_send_control --pid 12345 --command get_runtime_messages

# Invoke a registered / instruction
topsailai_send_control --session_id my-session --command call_instruction \
  --args '{"instruction":"ctx.history","args":[],"kwargs":{}}'
```

Supported actions: `call_instruction`, `hard_interrupt`, `soft_interrupt`,
`clear_interrupt`, `get_runtime_messages`.

## Environment variables

- Agent environment variables are stored in `~/.topsailai/.env.local` and
  `~/.topsailai/.env`. `.env.local` is loaded first and takes precedence.
- `.env` is a symlink to the project's `env_template`
  (`/TopsailAI/src/topsailai/env_template`), which documents every supported
  variable and its default.
- `.env.local` holds user-specific overrides and secrets.
- To change agent behavior: look up the variable in `env_template`, add the
  override to `.env.local`, then restart the agent.

## Log files

Runtime logs live under `{TOPSAILAI_HOME}/log/` (default
`~/.topsailai/log/`):

- `topsailai.log` — main runtime log.
- `chat.log` — chat interaction log.
- `topsailai.log.{session_id}` / `topsailai.log.{session_id}.simple` —
  per-session logs.
- `*.session.events` — session event logs.
- `topsailai.log.ec` — error/critical-only log for troubleshooting.

## File structure

- **SKILL.md**: this document.
- **scripts/**: none.
- **references/**: none.
- **assets/**: none.
