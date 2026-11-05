---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
references:
  - topsailai_cli.py
  - cli_topsailai/
  - topsailai.yaml
---

# topsailai

Interactive task watcher and session manager for TopsailAI.

## Purpose

`topsailai_cli.py` is the main interactive CLI. It scans `{TOPSAILAI_HOME}/workspace/task/` for session and task stdout/stderr files, displays them as a numbered list, and lets you watch logs, send messages to running sessions, retrieve session context, launch agents, and switch between workspace, project, and session scopes.

## Invocation

```bash
./topsailai_cli.py
./topsailai_cli.py -t
./topsailai_cli.py --tui
./topsailai_cli.py -n 200
./topsailai_cli.py --tail-lines 200
./topsailai_cli.py -m raw
./topsailai_cli.py --agent-mode raw
```

Because the script is registered in `../bin/` as `topsailai`, you can also run it from anywhere in the project as:

```bash
topsailai
```

## Environment File

At startup, `topsailai_cli.py` loads CLI-specific environment variables from `.topsailai_cli.env`. It checks the process startup directory first and then `{TOPSAILAI_HOME}/.topsailai_cli.env`; when `TOPSAILAI_HOME` is unset, the standard `~/.topsailai` default (or `/topsailai` without `HOME`) is used. Existing process environment variables have highest priority, and values loaded from the startup directory take priority over values in the TopsailAI home file. Missing files are ignored.

## Options

These options apply only to the default interactive mode (no subcommand). They control the runtime/watch behavior when you start the CLI interactively.

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show help message and exit. |
| `--version` | Show program version and exit. |
| `-t`, `--tui`, `--runtime-tui` | Use the two-pane curses UI when watching a log. |
| `-n N`, `--tail-lines N` | Number of recent log lines to echo on startup in runtime mode (default: 300). |
| `-m [MODE]`, `--agent-mode [MODE]` | raw \| dtach \| tmux. When omitted, auto-detect: tmux if available, else dtach if available, else raw. |

## Scopes

The CLI has five scopes, derived from the original design notes in `../../topsailai.md`. Run `scopes` from workspace scope to display these introductions and each scope's available actions:

- **`[workspace]`** — the default task-watcher scope. It lists discovered session and task logs and provides actions to watch logs, retrieve context, clean or refresh files, launch agents, and enter other scopes.
- **`[runtime:<id>]`** — the live log-streaming scope entered after selecting a workspace log. It provides `/send`, `/ctx.btw` for the watched PID, `/ctx.btw-all` for all discoverable live PIDs in a named session, `/control`, `/agent.<instruction>`, `/meta`, help, and commands for leaving the stream.
- **`[project]`** — a navigation scope listing recent sessions with recorded project workspaces and running status. It provides session selection, context retrieval, refresh, agent launch and resume actions, and return to workspace scope.
- **`[session:<id>]`** — a focused scope for one session. It provides context retrieval and streaming, runtime messaging, agent2llm and persistent context injection, configured session commands, and return to workspace scope.
- **`[doc]`** — a browser for Markdown documentation grouped under `docs/`. It provides numbered document reading, list refresh, help, and return to workspace scope.

## Session Output Files

The stream watcher discovers session and task stdout/stderr files in the task directory (`{TOPSAILAI_HOME}/workspace/task/`).

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

- **Agent2LLM inject messages**: runtime messages consumed by a running agent before its next LLM call.
  - Filename format: `{session_id}.{pid}.session.agent2llm_inject_messages.jsonl`
  - Written by `topsailai_session_add_agent2llm_message.py` and the `/ctx.btw` command.
- **Named pipes**: used for process-level messaging (`/send`).
  - Filename format: `{session_id}.{pid}.session.pipe`

Legacy filename formats are still accepted for backward compatibility:

- Generic `{name}.{pid}.stdout` / `{name}.{pid}.stderr`

### Sending messages to a running session

When you use `/send` in the stream watcher, the target session PID is resolved in this order:

1. **Task-list PID** — if the selected entry in the discovered file list already records a session PID, use it directly.
2. **Filename PID** — parse the PID from the stdout filename (works for `session.stdout`; for `task.stdout` the filename PID is the task child PID, so it is only used when it already points to a valid session pipe).
3. **`lsof` / `fuser` fallback** — scan the filesystem to find the process currently holding the stdout file and derive the session PID from there.

This prioritizes the authoritative PID recorded by the watcher and only falls back to heuristic methods when necessary.

## Commands Available in All Scopes

| Command | Description |
|---------|-------------|
| `!<command>` | Execute an arbitrary command line and remain in the current scope. Example: `!git status`. |

The command uses the same parsing and execution mechanism as `/git`: `shlex.split`, the shared `run_external_command` helper, and `os.system`. Their working-directory behavior differs: `/git` resolves the active session's project workspace and runs `git -C <project_workspace> ...`, while `!` runs in the CLI process's current working directory and inherits its environment. The command writes its standard output and standard error directly to the terminal. In the curses runtime UI, child-process output is not captured into the output pane; only the helper's `Executing ...` and `Execution completed.` messages are captured there. A non-zero shell status is reported as `Command exited with code N.`; parsing or execution-boundary failures are also reported. Entering `!` without a command prints `Usage: !<command>` and does not execute a command.

## Workspace / Project Commands

Workspace discovery reads exact session metadata for each parent session row and hides every row whose metadata status is `completed` by default, regardless of whether it has a session name. Run `r all` or `/refresh all` in ordinary workspace scope to include those rows; the mode persists across later refreshes until a plain `r` or `/refresh` restores the default. Included completed rows keep their derived process status but render `DONE` in the status cell, and the non-interactive `workspace -a/--all` flag and the `completed` JSON field expose the same evidence. Task rows are never marked `DONE` because completion evidence requires the row PID to equal the session PID. Session-info display caching must not bypass this completion check, so cached names and project workspaces do not cause completed sessions to reappear after refresh. Missing, invalid, mismatched, or non-completed metadata follows the existing fallback behavior. Metadata admission remains absent-only, while successful session-info queries retain their existing updates. Explicit `/meta` and `/driver meta` commands continue to read their own metadata.

| Command | Description |
|---------|-------------|
| `<number>` | Watch the selected log file (workspace) or enter the selected session (project). |
| `/driver <number>` | Start a driver for an eligible RUN/INPUT session (ordinary workspace only). |
| `/meta <number>` | Read exact session metadata in the ordinary workspace task list. |
| `/driver status <number>` | Read current driver evidence (ordinary workspace only). |
| `/driver stop <number>` | Gracefully stop one verified driver, not its session (ordinary workspace only). |
| `/driver log <number>` | Read the bounded driver log snapshot. |
| `/driver meta <number>` | Read the driver metadata snapshot; distinct from `/meta`. |
| `/kill <number>` | Send SIGTERM to exactly the displayed row PID after y/N confirmation (ordinary workspace only). |
| `/refresh` | Re-scan the task directory and refresh the list. `r all` or `/refresh all` also includes rows whose metadata status is `completed`; a plain `r` or `/refresh` restores the default hidden view. |
| `/session <number\|session_id>` | Retrieve full context messages for a session. A row without a session id (a temporary session displayed as `(temp)`) is served through its control channel when one exists; see [Workspace session history](#workspace-session-history). |
| `/agent [<number\|folder>]` | Launch an agent. With no argument, run the YAML-configured agent command. With an argument, change to the selected folder and run `topsailai_launch_agent`. The effective model selection is applied to the child process. |
| `/resume <number>` | Resume the selected running session with the effective model selection. |
| `/models` | List registry entries and select the workspace default or active-project override. |
| `/models current` | Show the effective model and whether it comes from project or workspace selection. |
| `/models clear` | Clear the model selection for the current workspace or project scope. |
| `/env.search <term> [term...]` | Fuzzy-search configurable environment variables case-insensitively. Multiple terms use OR semantics. The command checks `{TOPSAILAI_HOME}/.env.local`, then `{TOPSAILAI_HOME}/.env`, then the TopsailAI project `env_template`. It displays matching `NAME=VALUE` assignments from every source while suppressing names already found in a higher-priority source. Within one source, an uncommented assignment takes precedence over a commented assignment of the same name regardless of line order; equal-status duplicates retain the first assignment. Each group starts with `> Source: PATH`, and groups are separated by a blank line. Displayed names become TAB-completion candidates for subsequent `/env.get`, `/env.set`, and `/env.search` input in the current CLI process. Values can contain secrets and are intentionally shown by this command. |
| `/send <number> [message]` | Project scope only: send a message to the running session associated with the selected entry. Not available in workspace scope. |
| `/clean` | Remove expired files from the task directory. |
| `cd doc` | Enter doc scope and list usage documentation files under `docs/usage/`. |
| `scopes` | Display detailed introductions and available actions for each scope. |
| `/help` | Show available commands. |
| `q` | Quit the CLI. |

Workspace scope rejects `/send` and its `send` alias. Select a numbered log to enter runtime scope, then use `/send [message]` for the watched session. Session-scope messaging remains available.

### Workspace task list columns

When the CLI starts, it prints the workspace task list built by scanning `{TOPSAILAI_HOME}/workspace/task/` for `.stdout` and `.stderr` log files produced by running sessions and their tasks. Each row represents a discovered log file and shows:

| Column | Description |
|---|---|
| `No` | Row number used to select the file |
| `Session` | Session ID, or `(temp)` for temporary sessions |
| `PID` | Process ID embedded in the filename |
| `Modified` | Last modification time |
| `Created` | Creation time |

The prompt `[workspace]>` indicates workspace scope (the task list). Choosing a session switches to `[session:<session_id>]>` scope.

For non-interactive task-list output, `topsailai workspace list` defaults to the human-readable table. Scope-level `-f json` / `--format json` selects JSON, and `topsailai workspace list --json` explicitly selects JSON, overriding the scope format.

The legacy `--list-docs` and `--read-doc` options are deprecated and print a warning; use `topsailai docs list` and `topsailai docs read <name>` instead.

### Doc scope commands

When the CLI is showing the documentation list (`[doc]>`), the following commands are available:

| Command | Description |
|---|---|
| `<number>` | Read the selected usage documentation file. |
| `/refresh` | Re-scan the `docs/usage/` directory and refresh the list. |
| `/help` | Show available commands. |
| `q`, `quit`, or `cd` | Return to workspace scope. |

### Project scope commands

When the CLI is showing the project scope (`[project]>`), the following commands are available:

| Command | Description |
|---|---|
| `<number>` | Watch the selected session log file. |
| `/session <number>` | Retrieve the full session context for the selected entry. |
| `/refresh` | Reload the project session list. |
| `/agent <number\|folder>` | Launch an agent in the selected project workspace. |
| `/resume <number> [-d DRIVER]` | Resume the selected idle session; chats is the default driver. |
| `r [limit]` or `recent [limit]` | Refresh the recent project session list. If `[limit]` is provided, update the maximum number of records shown (default 30). |
| `p` or `projects` | Switch to the managed project list. |
| `p add [path] [name]` | Add a project to the managed project list. |
| `p del <number>` | Delete the managed project at the displayed row number. |
| `/help` | Show available commands. |
| `q`, `quit`, or `cd` | Return to workspace scope. |

### Managed project list

The managed project list is stored independently from session history in `{TOPSAILAI_HOME}/.projects.jsonl`. Each line is a JSON object:

```json
{"name": "my-project", "path": "/work/my-project", "created_at": "2026-07-25T08:09:58", "updated_at": "2026-07-25T08:09:58"}
```

- `r` / `recent` displays the recent session/project list, which is the default view when entering project scope.
- `p` / `projects` displays the managed list sorted oldest-first by creation time.
- `p add` resolves the path to an absolute path and rejects non-existent directories or duplicate paths.
- `p del <number>` asks for `y/N` confirmation and only removes the registry entry; it does not delete the project folder on disk.
- When the managed project list is active, `agent <number>` launches an agent in the selected project's folder.

### Interactive message commands

When watching a session, you can inject messages through three different paths. They differ in target layer, delivery mechanism, and when they take effect.

| Command | Target layer | Mechanism | When it takes effect |
|---|---|---|---|
| `/send` | Running agent process | Writes to the session's named pipe | Immediately; the running process receives it right now |
| `/ctx.btw` | `agent2llm` context | Calls `topsailai_session_add_agent2llm_message` to append to `*.session.agent2llm_inject_messages.jsonl` | Immediately; the running agent reads the JSONL before its next LLM call |
| `/ctx.add_msg` | `user2agent` context | Calls `topsailai_session_add_message` to append to the session message store | Only after the agent restarts; not visible to a running agent |

Use `/send` for urgent process-level messages, `/ctx.btw` for extra instructions you want the current agent to pick up on the fly, and `/ctx.add_msg` for context that should persist until the next agent run.

### Runtime scope dual-pane UI

When you choose to watch a session, the CLI enters **runtime scope** and streams the selected log file. If the terminal supports it, a two-pane curses UI is used:

```text
┌─────────────────────────────────────────────┐
│  Log pane                                   │
│  - streams the session/task stdout          │
│  - scrolls automatically to the latest line │
├─────────────────────────────────────────────┤
│  [runtime:<session_id>]> /send hello        │
│  Input pane (fixed at the bottom)           │
└─────────────────────────────────────────────┘
```

The top pane shows the streaming log. The bottom pane is a fixed input bar where you can type commands without the log output pushing your input off-screen.

#### Multi-line input

When `/send`, `/ctx.btw`, or `/ctx.btw-all` is used without a message argument, the input pane temporarily expands to about one third of the terminal height so you can type or paste multiple lines. Finish with `Ctrl+D` (EOF). Cancel with `Esc`.

#### Resizing the terminal

The UI handles terminal resizes automatically. If the terminal becomes too small to render both panes, drawing is skipped until the window is large enough again.

#### Fallback mode

If `curses` is unavailable or stdout is not a TTY (for example in a pipe or CI environment), the CLI automatically falls back to the legacy single-pane mode. In that mode the log and input share the same screen area and you press `q` then `Enter` to quit.

#### Windows support

The dual-pane UI relies on the Python `curses` module. On Windows install the `windows-curses` package to enable it:

```bash
pip install windows-curses
```

Without `windows-curses` the CLI still works, but it uses the legacy single-pane fallback.

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
| `/ctx.btw-all [message]` | Queue the message for all discoverable live PIDs in the current named session. The command takes one evidence snapshot after message acquisition, matches the exact session, deduplicates PIDs with session evidence preferred, and revalidates each original evidence path before one append attempt. The temporary ids `topsailai` and `(temp)` are rejected. Results are reported incrementally with queued, skipped, failed, and uncertain categories; no retry or rollback occurs, and queue success does not prove receiver consumption. New processes after the snapshot are excluded; missing evidence, liveness uncertainty, PID reuse, and receiver consumption remain limitations. |
| `/control <command> [args_json]` or `/control.<subcommand>` | Send a control request through `topsailai_send_control`. Runtime scope passes `--pid` for the PID identified from the watched log entry or filename and reports an error if no PID can be resolved. |
| `/control.heartbeat` | Check the watched process control channel with an empty payload. Returns `alive`, `pid`, `hostname` and nullable `session_id`; does not prove Agent or LLM progress. Also available in session scope. |
| `/agent.<instruction> [args...]` | Runtime shortcut that forwards a registered agent instruction through the control channel as `call_instruction` with instruction `agent.<name>`. Positional args are split on whitespace; kwargs are not supported. Requires a resolvable watched session PID, matching `/control`. |
| `/meta` | Print `{task_dir}/{session_id}.{session_pid}.session.meta` for the watched parent session. When watching a task log, the parent session PID is used instead of the task PID. |
| `/help` | Show the list of available streaming commands. |
| `q` or `quit` | Leave runtime scope and return to the file list. |

## Non-interactive Runtime

`topsailai runtime` executes one operation and exits, without entering a scope, following logs, initializing interactive input, or executing shell commands. Its entry point is `topsailai_cli.py`. The following commands are illustrative; replace selectors with the intended session (delivery operations require it to be running). They are not evidence of live-session delivery.

### Syntax and actions

```bash
# Instruction form: slash command and literal body in one argument
topsailai runtime -s SESSION -p PID -i '/send hello'
topsailai runtime -s SESSION -i '/ctx.btw remember this detail'
topsailai runtime -s SESSION -i '/control get_session_messages {}'
topsailai runtime -s SESSION -i '/control.get_session_messages {}'

# Structured form: same operations, without slash parsing
topsailai runtime send -s SESSION -p PID -m 'hello'
topsailai runtime btw -s SESSION --message 'remember this detail'
topsailai runtime control get_session_messages -s SESSION -a '{}' --json

# Explicit stdin: files or pipes, never an interactive terminal
topsailai runtime btw -s SESSION --stdin < message.txt
topsailai runtime -s SESSION -i '/send' --stdin < message.txt

# A body beginning with -- requires an explicit assignment
topsailai runtime send -s SESSION --message='--literal text'
```

`send` writes session input to its FIFO. `btw` queues an agent2llm injection through the existing writer. `control ACTION` sends a JSON-object payload, default `{}`, and requires a valid successful acknowledgement. Available control actions come from the existing dynamic registry, including plugins; this document intentionally does not duplicate its complete action list. ACTION is positional, not `-c`. `-a/--args` must be a JSON object, not an array or scalar. `get_session_messages` fills a missing `session_id` key from the selected target, without replacing an explicitly supplied value. `call_instruction` requires a nonempty `instruction` field; there is no interactive wizard.

### Selectors and options

| Option | Meaning |
|---|---|
| `-s`, `--session-id`, `--session_id` | Exact session identifier. |
| `-p`, `--pid` | Positive session PID, not a task child PID. |
| `--timeout` | Positive finite transport budget in seconds; default 5. |
| `--json` | Emit one public result document on stdout, including failures. |
| `-i`, `--instruction` | One allowed slash instruction; mutually exclusive with structured action syntax. |
| `-m`, `--message` | Literal send/btw body, not the global interactive agent-mode option. |
| `--stdin` | Explicit bounded non-TTY UTF-8 body source for send/btw only. |
| `-a`, `--args` | Control JSON object; default `{}`. |

At least session or PID is required. Providing both means strict intersection: neither may be relaxed. Discovery considers session stdout records under `{TOPSAILAI_HOME}/workspace/task/`, not task stdout as parent identities. For send/btw/control, no match, stale target, mismatch or multiple live candidates fails; the CLI never chooses the newest, falls back to another target, filters ambiguity by endpoint availability, or broadcasts.

Common options may appear before or after the structured action. Identical repeated value options are permitted; conflicting repeated values are rejected. Unknown options, leftover arguments and option abbreviations are rejected. Runtime `-m raw` and `-m tmux` are literal messages. Use `--message=VALUE` (or `-m=VALUE`) when a body starts with `--`. Help is offline: `runtime --help`, `runtime send --help`, `runtime btw --help`, `runtime control --help`, and `runtime logs --help` do not resolve a target, read stdin, or load control handlers/injection writers.

### Recent session logs

```bash
topsailai runtime logs -s SESSION -p PID
topsailai runtime logs -s SESSION -p PID -n 100 --json
```

`logs` reads recent physical LF-delimited records once and exits; it does not follow a stream or contact the agent. `-n/--lines` defaults to 20, accepts integers 1–10000, and applies only to `logs`, not slash instructions. At least one exact session/PID selector is required; both mean strict intersection. Idle and exited sessions are supported without process probes. Multiple historical matches are ambiguous: supply PID, rather than choosing the newest. Discovery considers only immediate regular, non-symlink session stdout files. Task stdout is never a fallback or merged stream. A runtime command without an action remains invalid.

Reject message, stdin, payload, instruction, explicit timeout and extra positional arguments for logs. Identical repeated counts are accepted; conflicting counts fail before filesystem access. The interactive top-level `-n/--tail-lines` option remains separate.

Tail scanning uses portable binary reads in 64 KiB blocks, with an 8 MiB scan budget and a captured initial EOF. It never loads an unbounded file or counts the entire file in an extra pass. Blank records and unterminated final records count as lines; terminal LF creates no phantom line. LF and preceding CR are removed, lone CR is preserved, and malformed UTF-8 is decoded with replacement. Unicode separators are not line boundaries. If the byte budget cuts a leading record, that fragment is dropped: a huge single line can return zero records with `scan_limited=true`, which does not mean the file is empty.

Plain output contains only chronological log records, one output newline each; empty logs emit nothing. Scan-limited plain output warns on stderr. JSON uses the existing envelope with `action="logs"`, `delivery_state="log_read"`, null `bytes_written`/`request_id`, and `delivery_unknown=false`. Its `response` contains:

| Field | Meaning |
|---|---|
| `filename` | Absolute selected session stdout path. |
| `lines` | Chronological decoded records without LF/CRLF terminators. |
| `requested_lines`, `returned_lines` | Requested count and number actually returned. |
| `total_lines` | Exact count only when scanning reaches file start; otherwise null. |
| `truncated` | Earlier records or content were omitted. |
| `scan_limited` | Byte budget prevented satisfying the count or proving file start. |
| `bytes_read`, `snapshot_size_bytes` | Bounded bytes scanned and initial descriptor size. |

Empty files return zero counts and false flags. Requests larger than available records return all records if the budget permits. Scan-limited results succeed with explicit partial flags, without a separate JSON warning. Exit 2 is invalid arguments, 3 is missing/mismatched/ambiguous target, 4 is permission or missing/invalid file endpoint, and 5 is `log_read_failed` or `log_changed`. Failed reads emit no partial log content. Missing task directories are target errors; a selected file disappearing before open is an endpoint error.

Appends after snapshot capture are excluded. Rotation keeps reading the opened descriptor where supported. Short reads, shrinkage and detected identity changes fail without retries. Same-size in-place rewrites cannot always be detected: this is a best-effort snapshot, not a transactional guarantee. Filesystem I/O has no hard timeout. Portable checks require trusted per-user storage and cannot guarantee resistance to hostile replacement races. Log content may contain secrets or terminal escape sequences; handle raw output accordingly. Windows uses ordinary Python file I/O without shell tail or POSIX transports; real Windows validation is separate from portable-path unit tests.

### Literal input and bounds

Send/btw require exactly one body source: structured message, instruction body, or explicit stdin. With instruction plus stdin, the instruction must be only `/send` or `/ctx.btw`, without an inline body. Control does not support stdin or message arguments; there is no message-file option.

The instruction starts immediately with its command token, without leading whitespace. Parsing consumes exactly one whitespace character between command and body (and between `/control` and ACTION); remaining body whitespace, quotes, Unicode and newlines are retained. Control payloads retain normal JSON whitespace. No `shlex` reconstruction or whole-body trimming occurs. Whitespace-only bodies are invalid. Shell operators and slash commands inside a send body are inert data, not recursively executed.

Messages have a 1 MiB UTF-8 byte limit. Explicit stdin is checked only after syntax validation; TTY stdin is rejected. Reading is bounded to 1 MiB + 1 bytes, then decoded strictly as UTF-8. Malformed encoding, excess size and empty/blank content are usage errors. Ordinary stdin device failures, including `isatty()` and reads failing after partial input, instead produce `input_read_failed` with exit code 5 before target resolution or delivery.

Send rejects a standalone `EOF` line (including CRLF framing equivalents) because it collides with the receiver terminator. An ordinary substring containing `EOF` is allowed. This FIFO restriction is not an injection-message terminator rule.

### Output and exit codes

Ordinary mode writes success to stdout and failure diagnostics to stderr, without echoing submitted bodies. `--json` produces exactly one JSON document on stdout on success or failure, including recognized parameter errors; help remains ordinary help. A body whose value is `--json` does not enable JSON output. Internal exceptions (`cause`) are never serialized.

Public result fields are `ok`, `exit_code`, `action`, `session_id`, `pid`, `delivery_state`, `error_code`, `message`, `bytes_written`, `request_id`, `response`, and `delivery_unknown`. Syntax errors can have empty action and absent selectors because normalization did not finish. Control responses may include receiver-provided application data; handle them according to that application's confidentiality requirements. Routine local diagnostics do not echo input bodies or raw stdin-device exceptions.

| Exit | Meaning |
|---|---|
| 0 | Success at the stated delivery boundary. |
| 2 | `usage_error`: invalid syntax, selectors, timeout, input, JSON, action, size or forbidden EOF line. |
| 3 | Target not found, mismatch, stale target or ambiguity. |
| 4 | Missing/invalid endpoint, permission denial or unsupported transport. |
| 5 | Transport error, timeout, injection failure or `input_read_failed` device failure. |
| 6 | Control rejected or invalid/oversized/uncorrelated response. |

### Delivery guarantees and limitations

- `pipe_written` means FIFO bytes were written, not that the agent processed them.
- `injection_queued` means the writer queued the message, not that the next LLM call consumed it.
- `control_acknowledged` means a correlated valid response reported `status=ok`, not that asynchronous business work finished.
- Failed writes/sends/appends may carry partial evidence or `delivery_unknown=true`. Do not blindly retry: a duplicate operation can have real effects. The CLI never automatically retries the whole operation.
- The default 5-second timeout bounds FIFO open/write or control connect/send/response operations. It does not cover stdin acquisition or the external writer's blocking injection append. No hard cancellation guarantee is provided for those boundaries.
- FIFO requires platform FIFO support; control uses Unix-domain sockets and fails on unsupported platforms. No cross-platform fallback transport is silently selected.
- The task directory is assumed to be trusted local per-user storage. Endpoint/type/path checks and PID liveness are not authenticated receiver identity. PID reuse and filesystem replacement races remain possible, especially between injection validation and the external writer opening the file. This interface is not a security boundary against a hostile task directory or other local users.
- Non-interactive runtime supports only `/send`, `/ctx.btw`, `/control`, `/control.ACTION`. It does not support arbitrary shell/YAML dispatch, multiple commands, broadcast, log following, or runtime `/ctx.add_msg`. Existing interactive scope commands remain separate.

## Subcommands

| Command | Description |
|---------|-------------|
| `runtime` | Execute one exact send, btw, control or logs operation; see the contract above. |
| `workspace [-f json] [list [--json]]` | Display the workspace task list and exit. The default is the human-readable table; `-f/--format json` sets the workspace-scope format, while `list --json` explicitly selects JSON and takes precedence. |
| `workspace kill <session_id> -g GENERATION [--json]` | Send SIGTERM without confirmation only when the exact session process generation is still verified. Obtain `GENERATION` from `workspace list --json` or `workspace -f json`; success means the OS accepted the signal, not that process exit was confirmed. |
| `workspace agent [<folder>] [-m MODE] [-b/--background] [--task MESSAGE] [--non-interactive] [--json]` | Launch a configured agent in the foreground; the folder defaults to the caller's working directory. `--task` supplies the initial user task so a fresh agent starts without manual input. Background defaults to raw and honors an explicit `-m raw|tmux|dtach`, failing closed with exit code 4 when that mechanism is unavailable. `--non-interactive` suppresses launcher prompts for this launch only. |
| `workspace resume -s SESSION [-d DRIVER] [-m MODE] [-b/--background] [--json]` | Resume one exact persisted idle session; background success means submission rather than readiness. |
| `workspace driver <start/status/stop> -s SESSION [-p PID] [--json]` | Start, inspect or stop one exact session driver; see below. |
| `docs list` | List all usage documentation files and exit. |
| `docs read <name>` | Read a specific usage documentation file and exit. |
| `project add <path> [name]` | Add a project to the managed project list. |
| `project del <path>` | Remove a project from the managed project list. |
| `project list [--json]` | Display all managed projects; `--json` outputs a JSON array instead of a table. |
| `project list_sessions [--json]` | Display recent sessions with project workspaces (default limit: 30); `--json` outputs JSON instead of a table. |
| `project launch <folder>` | Launch an agent in `<folder>` using the same behavior as the project-scope `/agent <folder>` command. |
| `project resume <session> [-d DRIVER]` | Resume an idle session; the default driver is `topsailai_agent_chats`. |
| `models list` | Display all model registry entries. |
| `models add <json-or-key=value...>` | Add a model entry to `.models.jsonl`. |
| `models update <number-or-name> <json-or-key=value...>` | Update an existing model entry. |
| `models delete <number-or-name>` | Delete a model entry. Use `--yes` to skip confirmation. |
| `models get <number-or-name>` | Print one model entry as formatted JSON. |
| `models current` | Show the workspace model selection. |
| `models select <number-or-name>` | Set the workspace default model selection. |
| `models clear` | Clear the workspace model selection. |

The JSON workspace document contains `host`, `pwd`, `home`, `task_dir`, `items`, and `total`. Each item contains `no`, `filename`, `session_name`, `session_id`, `is_task`, `pid`, `process_generation`, `status`, `completed`, `driver`, `created_at`, and `project_workspace`. `process_generation` is the positive operating-system process generation required by non-interactive `workspace kill`; it is present only when an ordinary session process is currently verified to hold that exact session stdout file, and otherwise is `null`. Callers must not substitute a PID, timestamp, row number, or older generation. `created_at` is the local creation time in ISO 8601 format with a timezone offset (`YYYY-MM-DDTHH:MM:SS+/-HHMM`), or `null` when the creation time is unavailable. Items retain the default oldest-first order. An empty workspace returns `"items": []` and `"total": 0`.

The `project list --json` document is a JSON array of managed project records, ordered oldest-first by `created_at`. Each record contains the stored fields `name`, `path`, `created_at`, and `updated_at`, plus the 1-based `no` row number that matches the table row. An empty registry returns `[]` and exit code `0`, so callers never have to parse a warning message. The public parser tolerates unknown arguments, so an unrecognized option is ignored and the default table is printed; the usage error with exit code `2` applies only when the internal handler receives an option other than `--json`.

## Workspace agent

```text
topsailai workspace agent [<folder>] [-m raw|dtach|tmux] [-b|--background] [--task MESSAGE] [--non-interactive] [--json]
```

The folder is optional and defaults to the caller's working directory, so `topsailai workspace agent` launches in the directory the command was invoked from. An explicit folder is resolved relative to the caller's startup directory. `--task MESSAGE` supplies the first user task to a fresh launcher, which starts the selected agent without waiting for manual task input; multiline and Unicode text are preserved, while an empty or whitespace-only value is rejected with exit code `2`. The task is passed as launcher argv rather than through the process environment and is not copied into JSON receipts, status output, or ordinary launch messages. `--non-interactive` is forwarded to the launcher in every mechanism, so a launch that would otherwise prompt for a missing `.topsailai/settings.yaml` or for a context-item choice proceeds without asking. It governs the launch only: the launched agent's own interactive mode remains controlled by `TOPSAILAI_INTERACTIVE_MODE` and is not modified. Foreground mode attaches to the launcher, prints `[INFO] Launching agent: ...`, restores the caller's environment and working directory, and returns its observed exit code. Background mode closes stdin and defaults to `raw`, an independent new process; an explicit `-m raw|tmux|dtach` selects that mechanism and fails with `4` when it is unavailable, with no silent fallback. In every mechanism the detached supervisor spawns the launcher itself, so the reported PID is the actual launcher, and it writes a private rotating `.agent-launch.log` under `TOPSAILAI_HOME/workspace/task/`. Submission is not readiness, there is no terminal reattachment, and active launch leases protect logs from expiry cleanup. Exit code `2` means generic usage failure; `3` means the folder is missing or not a directory; `4` means preparation failure, including an unavailable background mechanism; `5` means spawn or launcher wait failure; `6` means startup acknowledgement or owned custody cannot be confirmed; `130` means cancellation; otherwise observed child statuses `0..255` are preserved and a signal maps to `128 + signal`. A dtach/tmux wrapper client exit is not agent completion. With `--json`, stdout contains exactly one receipt and ordinary launcher output is redirected to stderr; without it, foreground stdin and standard streams retain their existing behavior. Background success reports `submitted`, not readiness, while foreground execution reports the observed launcher outcome.

`workspace agent`, `workspace kill`, and `workspace resume` use the same stable receipt fields when `--json` is selected: `ok`, `exit_code`, `action`, `session_id`, `pid`, `delivery_state`, `error_code`, `message`, `bytes_written`, `request_id`, `response`, and `delivery_unknown`. Command-specific established facts are placed in `response`. For kill, `signal_sent` means the OS accepted `SIGTERM`, not that the process exited. For background agent or resume, `submitted` means a launcher was submitted, not that it is ready. For foreground agent or resume, `launcher_exited` reports the observed launcher outcome and does not promote a wrapper exit into agent completion.

## Examples

```bash
# Start the interactive CLI
./topsailai_cli.py

# Display the workspace task list without entering interactive mode
./topsailai_cli.py workspace

# Display the workspace task list as JSON
topsailai workspace list --json

# List all usage documentation files
./topsailai_cli.py docs list

# Read a specific usage documentation file
./topsailai_cli.py docs read topsailai.md

# Add the current directory to the managed project list
./topsailai_cli.py project add .

# List managed projects
./topsailai_cli.py project list

# List managed projects as JSON
./topsailai_cli.py project list --json

# List model registry entries
./topsailai_cli.py models list

# Add a model with key=value pairs
./topsailai_cli.py models add name="My Model" provider=openai protocol=openai-compatible model=gpt-4o api_key_env=OPENAI_API_KEY

# Add a model with a JSON object
./topsailai_cli.py models add '{"id":"my-model","name":"My Model","provider":"openai","protocol":"openai-compatible","model":"gpt-4o","api_key_env":"OPENAI_API_KEY"}'

# Update the first model's base URL
./topsailai_cli.py models update 1 base_url=https://api.example.com/v1

# Select the first model as the workspace default
./topsailai_cli.py models select 1

# Show the current workspace selection
./topsailai_cli.py models current

# Clear the workspace selection
./topsailai_cli.py models clear
```

## Design Reference

The design notes, rules, caveats and index for this CLI live in `../../topsailai.md`. That file records no usage; this document is the single source of truth for usage.

The original high-level scope outline is preserved there as a scope index:

- workspace — task list
- runtime — stream log of one session
- project — project workspace
- session — enter one session
- doc — usage documentation list and read usage documentation

## Command Design Convention

- Interactive parameters use option flags, for example `--agent-mode`.
- Non-interactive parameters use subcommands, for example `project list`.


## Workspace session drivers

Use `/driver <number>` to start the driver for a currently running (`RUN`) or waiting-for-input (`INPUT`) session row. Use `/driver status <number>` to read state, reason, driver PID, run ID and verification. The driver commands are restricted to the ordinary workspace task list; project, session, runtime, doc and managed-project views reject them. Task rows, temporary sessions, malformed or legacy identities, changed targets and multiple live PIDs for one session are not eligible; select the session stdout row, not a task or temporary row. Status and stop can select an exited authoritative session row. Use `/driver stop <number>` to stop only its verified driver.

`/driver log <number>` reads the active session-level record at `{TOPSAILAI_HOME}/workspace/task/session_agent_driver/{session_id}.log` once and prints at most the last 20 physical lines in chronological order. The reader scans at most 8 MiB, does not follow or select rotated backups, and does not start, follow, or mutate a driver. `/driver meta <number>` reads the active session-level record at the same directory with the `.meta` suffix, at most 65,536 bytes and 64 JSON nesting levels, and prints the complete validated JSON; its embedded `pid` is the driver PID, not the selected session PID. Both records may be absent because normal driver cleanup removes them; historical rows for the same session share the same active record, which represents only the latest run and may already be cleaned up. No fallback record is selected. These two read-only commands return to the current workspace list without reloading, resorting or redrawing it, including handled read failures; use `/refresh` when a new list is needed.

### Non-interactive driver operations

```bash
topsailai workspace driver start -s SESSION -p PID --json
topsailai workspace driver status -s SESSION -p PID --json
topsailai workspace driver stop -s SESSION -p PID --json
```

Replace SESSION/PID with the intended session. All three commands exit without entering the interactive watcher. `-s/--session` is required and exact (no wildcards); optional `-p/--pid` is a positive integer and intersects the session selector. Conflicting repeated selectors are rejected. Help performs no discovery or launch. Existing `topsailai workspace [-f json]` list behavior is unchanged; `workspace list --json` overrides the scope-level format.

Start requires a live RUN/INPUT authoritative session stdout row. Task, temporary, legacy, changed and ambiguous identities are rejected. Multiple live PIDs for the session remain rejected even with `-p`. Status can inspect exited rows; multiple historical rows require PID rather than choosing newest. All three commands reuse default authority resolution and driver identity observations. Invalid configuration fails closed. Start reuses the interactive launcher's fresh target checks and driver-owned duplicate exclusion; a verified existing owner returns `already_running` without spawning another driver. Status is read-only and never retries or repairs evidence.

Plain successes go to stdout and failures to stderr. `--json` emits exactly one JSON document, including recognized syntax failures; help is ordinary text. The envelope uses the runtime fields `ok`, `exit_code`, `action`, `session_id`, `pid`, `delivery_state`, `error_code`, `message`, `bytes_written`, `request_id`, `response`, `delivery_unknown`. Action is `start`, `status` or `stop`; PID is the session PID, not the driver PID. `bytes_written` and `request_id` are null. Response is nullable driver evidence containing `state`, `reason`, `driver_pid`, `run_id`, `metadata_status`, `verification`, with semantic states rather than emoticons. Start delivery state is the launch outcome; status uses `status_read`. Unknown status evidence (`?`) returns exit 4 while retaining its observation.

The following table covers start/status; stop outcomes are specified in the graceful stop contract below.

| Exit | Meaning |
|---|---|
| 0 | Verified fresh publication (`launched`), verified existing owner (`already_running`), or a readable known status. |
| 2 | Invalid syntax or selector (`usage_error`). |
| 3 | Missing, ineligible, changed or ambiguous target. |
| 4 | Invalid configuration, unavailable inspection, rejected launch/preflight, or unknown status evidence. |
| 5 | Spawn failure or child exit before confirmation. |
| 6 | Startup unconfirmed before the existing bounded deadline; `delivery_unknown=true`. |

Publication proves driver liveness, not model readiness or analysis completion. An unconfirmed child may still run: do not blindly retry. Non-interactive commands do not terminate detached drivers when the CLI exits unless an explicit stop is requested.

### Graceful stop contract

Stop re-discovers the selected session row and verifies metadata session, driver PID, run ID, exact entry/command and process creation time before control. `-p` selects the session PID, never the driver PID. Ambiguous or changed targets and unclear owner identity are rejected without signaling. Stop can select exited session rows; multiple historical rows require `-p`, and multiple live session PIDs remain rejected even with it.

On supported POSIX systems, stop sends exactly one SIGTERM to the verified driver and waits up to 3 seconds for the original process to exit. It does not stop the session, broadcast, signal descendants, retry or escalate to SIGKILL. Unsupported graceful-stop platforms explicitly reject. The CLI never deletes metadata, logs or locks.

Stop delivery state is `stopped`, `already_stopped`, `rejected`, `failed` or `unconfirmed`. `stopped` proves original-process absence, not business completion or descendant cleanup. `already_stopped / no_recorded_driver` proves only missing recorded ownership, not absence of all untracked drivers. Stop exit codes are 0 for stopped/already_stopped, 2 for invalid arguments, 3 for target selection failure, 4 for validation rejection, 5 for definite signal submission failure and 6 for unconfirmed exit. Exit 6 sets `delivery_unknown=true`; never blindly retry uncertain delivery. Owner replacement is not reported as stopping the replacement.

Metadata v1 has no authoritative birth baseline or binding to a specific historical session PID. Command/birth rechecks provide best-effort PID-reuse protection only; a verification/signaling race remains. This is not a guarantee of full cleanup or cross-platform graceful shutdown.

### Default deployment paths and optional overrides

No additional configuration is needed in the standard installation layout. The CLI resolves the driver entry from its own package location (not the current working directory), preferring the sibling compiled executable `scripts/session_agent_driver/session_agent_driver` and otherwise using `scripts/session_agent_driver/session_agent_driver.py`. Compiled entries run directly without a Python interpreter; an existing but invalid compiled entry is rejected rather than silently replaced with source. For a `.py` entry, it prefers its current Python interpreter (`sys.executable`), falling back to a validated `sys._base_executable` when necessary. A packaged non-Python executable is not accepted, and arbitrary `PATH` entries are not searched.

Each CLI-specific environment variable independently overrides its default when set before starting the CLI:

| Variable | Meaning |
|---|---|
| `TOPSAILAI_SESSION_DRIVER_ENTRY` | Optional absolute path to a driver entry file; `.py` requires read access, compiled entries require execute access; defaults to the standard sibling scripts layout. |
| `TOPSAILAI_SESSION_DRIVER_PYTHON` | Optional absolute path to a compatible executable Python interpreter whose filename starts with `python`; defaults to the validated CLI runtime for `.py` entries and is unused for compiled entries. |

The CLI validates these files once at its configuration boundary. An invalid explicit override is rejected rather than silently replaced with a default. Missing default files or an invalid interpreter print an `[ERROR]` with correction guidance and safely block launch. The chosen interpreter must have the driver dependencies installed; file validation alone does not prove import compatibility. Read-only metadata remains available, but unverifiable running evidence shows `?`. Configuration changes require restarting the CLI. The driver receives the resolved `TOPSAILAI_HOME` explicitly, with noninteractive detached standard streams. Environment contents and process command lines are not printed.

### Driver column and outcomes

The Driver column follows Status and is independent of the target session status. It uses one read-only observation per valid session ID, so every associated row for that session shares the same display. This table-level sharing does not make every row eligible for driver commands; start/status/stop retain their existing target-selection rules. Its legend is part of the `/driver <number>` command description in workspace `/help` and `/help driver`, not a separate help footer or a line beneath the task list:

| Driver display | Semantic state | Meaning |
|---|---|---|
| `-` | `-` | Metadata absent, normally also after clean exit. |
| numeric driver PID | `ON` | Running metadata with verified driver process identity; the number is the driver PID, not the session-row PID. |
| `:(` | `STALE` | Running metadata whose recorded driver PID is confirmed absent. |
| `x(` | `EXIT` | Residual stopped metadata without a contradictory live process. |
| `x(` | `FAIL` | Residual failed metadata without a contradictory live process. |
| `?` | `?` | Invalid, inaccessible, conflicting or unverifiable evidence, including an ON observation without a valid PID. |

Workspace JSON adds nullable `driver` with `state`, `reason`, `driver_pid`, `run_id`, `metadata_status` and `verification`. Ineligible rows have `driver: null`. Table display uses a session-level observation, while JSON and status retain their existing operational eligibility and shared read-only observation rules. JSON `driver.state` and `/driver status` retain semantic values (`ON`, `STALE`, `EXIT`, `FAIL`, `-`, `?`); the PID is not written into that state. Driver start/status/stop commands refresh the table afterward; the log/meta readers do not; there is no automatic refresh polling.

The external driver alone owns duplicate-start exclusion, its lock, metadata and log cleanup. The CLI never writes, acquires or deletes these records. Lock-file presence does not prove a running owner. Clean finalization normally removes metadata and logs, so EXIT/FAIL are residual observations, not durable exit history. Stop also leaves record cleanup to the external driver.

Launch reports `launched` only for fresh verified publication matching the new child. `already_running` identifies verified existing ownership; `failed` means spawn failure or exit before confirmation; `rejected` means validation/preflight did not authorize startup. `unconfirmed` means a live child did not publish matching evidence before the bounded confirmation deadline: do not blindly retry. Publication proves liveness, not model readiness or analysis completion. The CLI retains live child handles in memory and reaps exits on later interactions without terminating resident drivers when leaving the CLI.

Process identity checks are conservative and cannot prove complete PID-reuse protection without an authoritative stored birth baseline. Target checks occur before launch; the external driver selects by session ID, not a strictly bound target PID. A preflight/spawn race is possible and driver-owned exclusion is the final authority. This does not promise exactly one spawned process or full descendant supervision.


## Workspace Session Metadata

Use `/meta 3` in the ordinary workspace task list to read row 3 of the currently displayed list. Exactly one positive row number is required; bare `/meta`, extra arguments and `--json` produce usage errors. The command remains in workspace scope without refreshing or sorting the list.

Only standard session stdout/stderr rows are supported, including exited sessions. The raw session ID and integer PID must agree with the filename and any recorded session PID. Task rows must be replaced with the corresponding session row; legacy and incomplete identities are rejected. Temporary rows are supported: they are displayed as `(temp)` and stored under the reserved `topsailai` prefix, and their record carries an empty `session_id`, which denotes the same absent identity. No parent PID is guessed and no newest-file fallback is used.

The fixed target is `{TOPSAILAI_HOME}/workspace/task/{session_id}.{pid}.session.meta`, not driver metadata; a temporary row substitutes the reserved `topsailai` prefix for its display marker. Success prints an identity line followed by the original UTF-8 JSON text, preserving all fields and adding a final newline if needed. The JSON must be an object with a matching integer PID and a session ID that matches exactly, except that a temporary record's empty `session_id` is accepted. Unknown status values are displayed unchanged.

Reads are limited to 65,536 bytes and 64 nesting levels. Missing, unreadable, oversized, malformed, excessively nested or identity-mismatched metadata produces an `[ERROR]` category without its body or a traceback. Path traversal, nonregular files and symlinks beneath the trusted home are rejected. Platforms without safe no-follow directory reads fail closed. On those platforms, the workspace list also cannot apply the metadata-based completed-to-idle override and retains its original derived process status. Reads are bounded snapshots, not transactions; incomplete concurrent writes report an error without automatic retries.

Runtime `/meta` remains unchanged: it reads the watched parent session metadata without a row argument. This increment adds no non-interactive workspace meta subcommand.

## Workspace session history

`/session <number>` in the ordinary workspace task list prints the selected row's context messages. A row with a real session id keeps the database retrieval path (`topsailai_retrieve_messages <session_id> --max-chars 1000`).

A row without a session id — a temporary session displayed as `(temp)` and stored under the reserved `topsailai` prefix — cannot be served by that database lookup. When such a row's control channel exists, the CLI instead sends exactly one `call_instruction` request with the payload `{"instruction": "ctx.history"}` over the row's Unix-domain control socket and prints the returned history text. The display marker is translated to the reserved `topsailai` file prefix before the socket path is composed, so the socket is `{TOPSAILAI_HOME}/workspace/task/topsailai.{pid}.session.sock`.

Preconditions and limits:

- The socket must already exist as a socket inode. A missing path, a regular file or a symlink at that path is not a channel.
- A socket file outlives its owner process, so a socket whose owner PID is not provably alive is not a channel either. A stale socket therefore never hides the single live owner of the same identity.
- A task row is served only through its parent session PID. A task row whose parent session PID is ambiguous is rejected instead of guessed.
- A literal `/session (temp)` argument resolves the single live `topsailai.{pid}.session.sock` in the task directory. Several live matching sockets are reported as ambiguous rather than guessed.
- An identifier that could escape the task directory (containing `/`, `\`, a NUL byte, `..`, or equal to `.`/`..`) is rejected before any path is composed.
- The control path returns the instruction's own formatted text, so `--max-chars` truncation does not apply to it.
- Returned text is printed with ANSI escape sequences and control characters stripped, so a remote process cannot recolor or clear the local terminal. Real newlines, tabs and indentation are preserved.

When no control channel exists, the previous message is kept unchanged: `[ERROR] No session ID available for this file.` for a selected row, and `[ERROR] No session ID available for session '(temp)'.` for the literal form. A rejected request, an invalid response and a transport failure each print one `[ERROR]` line carrying the classified error code. The request is never retried, because a duplicate instruction call can have real effects.

## Workspace process termination

Interactive `/kill 3` targets row 3 of the currently displayed ordinary workspace task list. Exactly one positive row number is required. Project, runtime, session, doc and managed-project views reject this command. Rows whose PID column is `-` are not eligible; PID 1 and the CLI's own PID are also rejected.

The interactive confirmation identifies the row, session and exact PID and warns that unsaved work may be lost. Enter `y` or `yes` to send SIGTERM; Enter, other answers, EOF or Ctrl+C cancel without signaling. The target is only the PID column, including a task child PID when selecting a task row, never the Driver column or an inferred parent session PID. No process group or descendant traversal is performed. This interactive legacy path does not verify process-instance identity, so refresh stale lists before use.

Non-interactive termination uses a stricter contract:

```text
topsailai workspace kill SESSION -g GENERATION [--json]
```

Obtain `SESSION` and its non-null `process_generation` from the same recent `topsailai workspace -f json` snapshot. The command examines every exact ordinary session stdout row for that session, ignores rows whose original process is authoritatively absent, and requires exactly one live process that still holds its matching stdout file. Its immutable process generation must equal `GENERATION`; a bare session or PID never authorizes termination. Stale generations, PID reuse, unavailable identity evidence, changed file ownership and multiple live instances fail without sending a signal.

On supported Linux systems, the command opens a pidfd for the verified PID, revalidates its process identity, and submits exactly one SIGTERM through that bound handle. If pidfd support or authoritative identity evidence is unavailable, it fails closed rather than falling back to `os.kill`. Success means the OS accepted the signal for that verified process instance; it does not confirm exit, stop descendants, retry, escalate to SIGKILL, or delete logs. JSON success reports `delivery_state="signal_sent"` and returns the verified generation in `response.generation`. Exit `2` is invalid syntax or selector, `3` is target/identity/generation rejection, and `4` is signal submission failure.


## Current-request first-byte control shortcuts

Interactive runtime and session scopes accept these exact no-argument commands:

| Command | Current-request operation |
|---------|---------------------------|
| `/control.fbt.hard_interrupt` | Abandon the current turn |
| `/control.fbt.force_retry` | Retry within the existing retry budget and backoff |

Both send `llm_control` with only the corresponding `operation`, omitting `target`
and `command_id`. The backend freezes the current target at admission; it may
reject an idle, completed or otherwise ineligible request. The first decoded
stream record closes the first-byte window, including a metadata-only record.
These commands do not queue control for future requests. Runtime targets the
watched PID and refuses to send if that PID is unavailable; session retains its
existing session-selector behavior. `/control.hard_interrupt` remains the
separate legacy interrupt and is not an alias for either FBT operation.

Extra arguments are not accepted. For stable-ID retransmission or explicit
targets, use the generic `/control llm_control` JSON form instead.

These interactive aliases are not supported by non-interactive runtime instruction
parsing. Use the existing structured equivalent (replace selectors as needed):

```text
topsailai runtime control llm_control -s SESSION -p PID -a '{"operation":"hard_interrupt"}'
topsailai runtime control llm_control -s SESSION -p PID -a '{"operation":"force_retry"}'
```

## Workspace resume

```text
topsailai workspace resume -s SESSION [-d DRIVER] [-m raw|dtach|tmux] [-b|--background] [--json]
```

`-s` / `--session` identifies one literal persisted session, never a row number,
prefix, newest session, or process PID. The command uses the recorded absolute
workspace and defaults to `topsailai_agent_chats`, preserving the session identity.
Use `-d` / `--driver` to select one of `topsailai_agent_chats`,
`topsailai_agent_plan_tasks`, or `ai-team-flow-dev`; an explicit driver overrides
the default. Resume driver selection does not use `ai_agent_driver` or
`TOPSAILAI_AGENT_DRIVER`.
Missing records fail with 3; unavailable or ambiguous lookup, invalid workspace,
and live or unverifiable processes fail with 4. No directory is created and
there is no fallback to the current directory.

Foreground is the default, with `dtach` as the default mode. `-m raw` waits for
the driver and propagates its exit status; terminal wrappers can detach before
the agent finishes. `-b` defaults to headless raw, closes stdin, and reuses the
workspace-agent supervisor, rotating log, active lease, and expiry cleanup.
An explicit `-m raw|tmux|dtach` with `-b` selects that mechanism and fails with
4 when it is unavailable; there is no silent fallback. Repeated identical
options are accepted; conflicting options, extra positionals, abbreviations, PID and confirmation options are rejected.

Background success means submitted, not ready or completed. Plain output includes
the actual launcher PID and a private per-attempt log path; repeated resumes do
not overwrite earlier diagnostics. With `--json`, stdout contains exactly one
receipt and ordinary resume and child output is redirected to stderr; the
receipt's `response` contains the established workspace, mode, driver, background
flag, launcher PID, log path, startup-confirmation state, and observed child status.
Inspect the printed or reported log path or workspace task list; there is no
terminal reattachment promise. Spawn or early-exit failure is 5, unresolved
process custody is 6, and confirmed cancellation is 130.

Session lookup runs once. All relevant session stdout candidates are checked,
and workspace/liveness are checked again before launch. These local checks do
not provide a runtime lock: concurrent external starts and PID reuse remain
possible. Task storage must be trusted and available; permission and I/O errors
are not interpreted as an idle session. Interactive `/resume` and `project resume` use chats by default, accept the same built-in `-d/--driver` choices, and retain their boolean/refusal behavior.
