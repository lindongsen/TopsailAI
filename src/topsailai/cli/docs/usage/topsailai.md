---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
references:
  - topsailai.py
  - cli_topsailai/
  - topsailai.yaml
---

# topsailai

Interactive task watcher and session manager for TopsailAI.

## Purpose

`topsailai.py` is the main interactive CLI. It scans `{TOPSAILAI_HOME}/workspace/task/` for session and task stdout/stderr files, displays them as a numbered list, and lets you watch logs, send messages to running sessions, retrieve session context, launch agents, and switch between workspace, project, and session scopes.

## Invocation

```bash
./topsailai.py
./topsailai.py --tui
./topsailai.py --tail-lines 200
```

Because the script is registered in `../bin/` as `topsailai`, you can also run it from anywhere in the project as:

```bash
topsailai
```

## Options

These options apply only to the default interactive mode (no subcommand). They control the runtime/watch behavior when you start the CLI interactively.

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show help message and exit. |
| `--version` | Show program version and exit. |
| `--tui`, `--runtime-tui` | Use the two-pane curses UI when watching a log. |
| `--tail-lines N` | Number of recent log lines to echo on startup in runtime mode (default: 100). |
| `--agent-mode [MODE]` | raw \| dtach \| tmux. When omitted, auto-detect: tmux if available, else dtach if available, else raw. |

## Scopes

The CLI has five scopes, derived from the original design notes in `../../topsailai.md`. Run `scopes` from workspace scope to display these introductions and each scope's available actions:

- **`[workspace]`** — the default task-watcher scope. It lists discovered session and task logs and provides actions to watch logs, retrieve context, clean or refresh files, send messages, launch agents, and enter other scopes.
- **`[runtime:<id>]`** — the live log-streaming scope entered after selecting a workspace log. It provides `/send`, `/ctx.btw`, help, and commands for leaving the stream.
- **`[project]`** — a navigation scope listing recent sessions with recorded project workspaces and running status. It provides session selection, context retrieval, refresh, agent launch and resume actions, and return to workspace scope.
- **`[session:<id>]`** — a focused scope for one session. It provides context retrieval and streaming, runtime messaging, agent2llm and persistent context injection, configured session commands, and return to workspace scope.
- **`[doc]`** — a browser for Markdown documentation grouped under `docs/`. It provides numbered document reading, list refresh, help, and return to workspace scope.

## Workspace / Project Commands

| Command | Description |
|---------|-------------|
| `<number>` | Watch the selected log file (workspace) or enter the selected session (project). |
| `/refresh` | Re-scan the task directory and refresh the list. |
| `/session <number\|session_id>` | Retrieve full context messages for a session. |
| `/agent [<number\|folder>]` | Launch an agent. With no argument, run the YAML-configured agent command. With an argument, change to the selected folder and run `topsailai_launch_agent`. |
| `/resume <number>` | Resume the selected running session. |
| `/send <number> [message]` | Send a message to the running session associated with the selected entry. |
| `/clean` | Remove expired files from the task directory. |
| `cd doc` | Enter doc scope and list usage documentation files under `docs/usage/`. |
| `scopes` | Display detailed introductions and available actions for each scope. |
| `/help` | Show available commands. |
| `q` | Quit the CLI. |

## Runtime Commands

| Command | Description |
|---------|-------------|
| `/send [message]` | Send a message to the running session through its named pipe. If no message is given, the input pane expands for multi-line input. |
| `/ctx.btw [message]` | Inject a by-the-way message into the `agent2llm` context of the watched session. If no message is given, the input pane expands for multi-line input. |
| `/help` | Show the list of available streaming commands. |
| `q` or `quit` | Leave runtime scope and return to the file list. |

## Subcommands

| Command | Description |
|---------|-------------|
| `workspace` | Display the workspace task list and exit without entering interactive mode. |
| `docs list` | List all usage documentation files and exit. |
| `docs read <name>` | Read a specific usage documentation file and exit. |
| `project add <path> [name]` | Add a project to the managed project list. |
| `project del <path>` | Remove a project from the managed project list. |
| `project list` | Display all managed projects. |

## Examples

```bash
# Start the interactive CLI
./topsailai.py

# Display the workspace task list without entering interactive mode
./topsailai.py workspace

# List all usage documentation files
./topsailai.py docs list

# Read a specific usage documentation file
./topsailai.py docs read topsailai.md

# Add the current directory to the managed project list
./topsailai.py project add .

# List managed projects
./topsailai.py project list
```

## Historical Reference

The original high-level scope outline is preserved in `../../topsailai.md`:

- workspace — task list
- runtime — stream log of one session
- project — project workspace
- session — enter one session
- doc — usage documentation list and read usage documentation

## Command Design Convention

- Interactive parameters use option flags, for example `--agent-mode`.
- Non-interactive parameters use subcommands, for example `project list`.
