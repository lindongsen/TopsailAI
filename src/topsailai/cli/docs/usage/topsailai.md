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
| `--tail-lines N` | Number of recent log lines to echo on startup in runtime mode (default: 300). |
| `--agent-mode [MODE]` | raw \| dtach \| tmux. When omitted, auto-detect: tmux if available, else dtach if available, else raw. |

## Scopes

The CLI has five scopes, derived from the original design notes in `../../topsailai.md`. Run `scopes` from workspace scope to display these introductions and each scope's available actions:

- **`[workspace]`** — the default task-watcher scope. It lists discovered session and task logs and provides actions to watch logs, retrieve context, clean or refresh files, send messages, launch agents, and enter other scopes.
- **`[runtime:<id>]`** — the live log-streaming scope entered after selecting a workspace log. It provides `/send`, `/ctx.btw`, `/meta`, help, and commands for leaving the stream.
- **`[project]`** — a navigation scope listing recent sessions with recorded project workspaces and running status. It provides session selection, context retrieval, refresh, agent launch and resume actions, and return to workspace scope.
- **`[session:<id>]`** — a focused scope for one session. It provides context retrieval and streaming, runtime messaging, agent2llm and persistent context injection, configured session commands, and return to workspace scope.
- **`[doc]`** — a browser for Markdown documentation grouped under `docs/`. It provides numbered document reading, list refresh, help, and return to workspace scope.

## Commands Available in All Scopes

| Command | Description |
|---------|-------------|
| `!<command>` | Execute an arbitrary command line and remain in the current scope. Example: `!git status`. |

The command uses the same parsing and execution mechanism as `/git`: `shlex.split`, the shared `run_external_command` helper, and `os.system`. Their working-directory behavior differs: `/git` resolves the active session's project workspace and runs `git -C <project_workspace> ...`, while `!` runs in the CLI process's current working directory and inherits its environment. The command writes its standard output and standard error directly to the terminal. In the curses runtime UI, child-process output is not captured into the output pane; only the helper's `Executing ...` and `Execution completed.` messages are captured there. A non-zero shell status is reported as `Command exited with code N.`; parsing or execution-boundary failures are also reported. Entering `!` without a command prints `Usage: !<command>` and does not execute a command.

## Workspace / Project Commands

| Command | Description |
|---------|-------------|
| `<number>` | Watch the selected log file (workspace) or enter the selected session (project). |
| `/refresh` | Re-scan the task directory and refresh the list. |
| `/session <number\|session_id>` | Retrieve full context messages for a session. |
| `/agent [<number\|folder>]` | Launch an agent. With no argument, run the YAML-configured agent command. With an argument, change to the selected folder and run `topsailai_launch_agent`. The effective model selection is applied to the child process. |
| `/resume <number>` | Resume the selected running session with the effective model selection. |
| `/models` | List registry entries and select the workspace default or active-project override. |
| `/models current` | Show the effective model and whether it comes from project or workspace selection. |
| `/models clear` | Clear the model selection for the current workspace or project scope. |
| `/send <number> [message]` | Send a message to the running session associated with the selected entry. |
| `/clean` | Remove expired files from the task directory. |
| `cd doc` | Enter doc scope and list usage documentation files under `docs/usage/`. |
| `scopes` | Display detailed introductions and available actions for each scope. |
| `/help` | Show available commands. |
| `q` | Quit the CLI. |

## Model Registry and Selection

Model definitions are read from `{TOPSAILAI_HOME}/.models.jsonl`, with one JSON object per line. Each entry requires `id`, `name`, `provider`, `protocol`, and `model`; the initial implementation supports `openai-compatible`. Optional connection fields include `base_url`, `api_key_env`, `organization_env`, and `project_env`.

Credential fields name existing source environment variables. The registry must not contain raw API keys, tokens, passwords, or secrets. Additional non-secret variables may be supplied through `environment`, while protected TopsailAI runtime variables cannot be overridden.

Selections persist in `{TOPSAILAI_HOME}/.model_selection.json`. A project override takes precedence over the workspace default, which takes precedence over the inherited process environment. Invalid, missing, disabled, or unsupported selected entries stop the launch with an error instead of silently falling back.

The selected configuration is resolved immediately before `/agent` or `/resume`. It sets `OPENAI_MODEL`; when configured, it also sets identical `OPENAI_BASE_URL` and `OPENAI_API_BASE` values and maps referenced credentials to `OPENAI_API_KEY`, `OPENAI_ORG_ID`, and `OPENAI_PROJECT_ID`. These values apply only to the launched child process and do not alter the parent shell.

## Runtime Commands

| Command | Description |
|---------|-------------|
| `/send [message]` | Send a message to the running session through its named pipe. If no message is given, the input pane expands for multi-line input. |
| `/ctx.btw [message]` | Inject a by-the-way message into the `agent2llm` context of the watched session. If no message is given, the input pane expands for multi-line input. |
| `/meta` | Print `{task_dir}/{session_id}.{session_pid}.session.meta` for the watched parent session. When watching a task log, the parent session PID is used instead of the task PID. |
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
| `models list` | Display all model registry entries. |
| `models add <json-or-key=value...>` | Add a model entry to `.models.jsonl`. |
| `models update <number-or-name> <json-or-key=value...>` | Update an existing model entry. |
| `models delete <number-or-name>` | Delete a model entry. Use `--yes` to skip confirmation. |
| `models get <number-or-name>` | Print one model entry as formatted JSON. |
| `models current` | Show the workspace model selection. |
| `models select <number-or-name>` | Set the workspace default model selection. |
| `models clear` | Clear the workspace model selection. |

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

# List model registry entries
./topsailai.py models list

# Add a model with key=value pairs
./topsailai.py models add name="My Model" provider=openai protocol=openai-compatible model=gpt-4o api_key_env=OPENAI_API_KEY

# Add a model with a JSON object
./topsailai.py models add '{"id":"my-model","name":"My Model","provider":"openai","protocol":"openai-compatible","model":"gpt-4o","api_key_env":"OPENAI_API_KEY"}'

# Update the first model's base URL
./topsailai.py models update 1 base_url=https://api.example.com/v1

# Select the first model as the workspace default
./topsailai.py models select 1

# Show the current workspace selection
./topsailai.py models current

# Clear the workspace selection
./topsailai.py models clear
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
