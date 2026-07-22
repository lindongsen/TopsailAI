---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
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

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show help message and exit. |
| `--version` | Show program version and exit. |
| `-r`, `--runtime-raw` | Use the raw curses-free streaming mode (default). |
| `--tui`, `--runtime-tui` | Use the two-pane curses UI when watching a log. |
| `--tail-lines N` | Number of recent log lines to echo on startup in runtime mode (default: 100). |

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
| `/resume <number>` | Resume an idle session in its project workspace (project scope only). |
| `/clean [<number>...]` | Delete idle `.stdout` files older than 3 days, or delete specific files by number. |
| `/send <number> [message]` | Send a message to the running session associated with the selected entry. |
| `cd project` | Switch to project scope. |
| `scopes` | Display detailed introductions and available actions for all five scopes (workspace scope only). |
| `q`, `quit`, `exit`, `cd` | Exit current scope or quit the CLI. |
| `/help [<keyword>]` | Show available commands, optionally filtered by keyword. |

## Session / Runtime Commands

| Command | Description |
|---------|-------------|
| `/send [message]` | Send a message to the running session through its named pipe. Omit the message for multi-line input (finish with `Ctrl+D`). |
| `/ctx.btw [message]` | Inject a by-the-way message into the `agent2llm` runtime context of the watched session. |
| `/ctx.add_msg [message]` | Add a persistent message to the `user2agent` context (visible after the agent restarts). |
| `/help` | Show available commands. |
| `q`, `quit` | Leave runtime scope and return to the file list. |

## Notes

- Running sessions are highlighted in green in the file list.
- Temporary sessions (session id `topsailai`) are displayed as `(temp)`.
- The dual-pane UI requires the `curses` module; on Windows install `windows-curses`.
- `Ctrl+C` exits gracefully and cleans up child processes.

## Historical Reference

The original high-level scope outline is preserved in `../../topsailai.md`:

- workspace — task list
- runtime — stream log of one session
- project — project workspace
- session — enter one session
