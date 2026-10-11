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
topsailai workspace                  # show the human-readable task list and exit
topsailai workspace --format json     # output task details as JSON
topsailai docs list                   # list usage docs
topsailai docs read topsailai.md      # read a usage doc
topsailai project list                # list managed projects
topsailai project add <path>          # add a project
topsailai models list                 # list model registry entries
```

`topsailai workspace --format json` is recommended for scripts and operational
queries. The output includes task/session details such as `session_name`,
`session_id`, `pid`, `status`, `filename`, `created_at`, `project_workspace`,
`is_task`, and `total`.

## Controlling and observing a running agent

The non-interactive `topsailai runtime` command controls or queries one
specific session without entering the interactive runtime watcher. Use the
`session_id` and `pid` reported by `topsailai workspace --format json` when
available:

```bash
# Send input to a running session
topsailai runtime send -s SESSION_ID -p PID -m 'message'

# Inject a by-the-way message into the agent2llm context
topsailai runtime btw -s SESSION_ID -m 'message'

# Query session messages
topsailai runtime control get_session_messages \
  -s SESSION_ID -p PID -a '{}' --json

# Invoke an instruction in the running session
topsailai runtime control call_instruction \
  -s SESSION_ID -p PID -a '{"instruction": "agent.models"}' --json
```

The `-i` form accepts the same interactive runtime instructions directly:

```bash
topsailai runtime -s SESSION_ID -p PID -i '/send hello'
topsailai runtime -s SESSION_ID -p PID -i '/ctx.btw remember this'
topsailai runtime -s SESSION_ID -p PID -i '/control get_session_messages {}'
```

Delivery success means that the operation was sent or queued; it does not
necessarily mean that the running agent has already consumed it. Use `--json`
for machine-readable results and `--stdin` for bounded non-interactive input.

Query recent session stdout without entering the watcher or contacting the
agent:

```bash
# Query the latest 20 lines (default)
topsailai runtime logs -s SESSION_ID -p PID

# Query the latest 100 lines
topsailai runtime logs -s SESSION_ID -p PID -n 100

# Return machine-readable results
topsailai runtime logs -s SESSION_ID -p PID -n 100 --json
```

The `logs` action supports running, idle, and exited sessions. Session ID and
PID must both match when supplied together; ambiguous history requires an
explicit PID. It reads only session stdout under
`{TOPSAILAI_HOME}/workspace/task/`, with no fallback to task stdout.

The default is 20 lines, with a maximum of 10,000. Reverse chunked reading has
an 8 MiB scan budget; exceeding it marks the result as partial. JSON results
use status `log_read` and put log data in `response`; `total_lines` is accurate
only when reading reaches the beginning of the file, otherwise it is `null`.
Plain output contains only log content, with partial-result warnings on stderr.
Exit codes are `2` for invalid arguments, `3` for target errors, `4` for
permission or endpoint errors, and `5` for read failures or detected file
changes.

The lower-level `topsailai_send_control` command remains available for
compatibility, but `topsailai runtime control` is the preferred interface:

```bash
topsailai_send_control --session_id my-session --command call_instruction \
  --args '{"instruction":"ctx.history","args":[],"kwargs":{}}'
```

Supported runtime actions include `send`, `btw`, `control`, and `logs`; control
operations include `call_instruction`, `hard_interrupt`, `soft_interrupt`,
`clear_interrupt`, and runtime message queries.

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
