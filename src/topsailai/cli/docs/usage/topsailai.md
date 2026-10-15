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

- **`[workspace]`** — the default task-watcher scope. It lists discovered session and task logs and provides actions to watch logs, retrieve context, clean or refresh files, send messages, launch agents, and enter other scopes.
- **`[runtime:<id>]`** — the live log-streaming scope entered after selecting a workspace log. It provides `/send`, `/ctx.btw`, `/control`, `/agent.<instruction>`, `/meta`, help, and commands for leaving the stream.
- **`[project]`** — a navigation scope listing recent sessions with recorded project workspaces and running status. It provides session selection, context retrieval, refresh, agent launch and resume actions, and return to workspace scope.
- **`[session:<id>]`** — a focused scope for one session. It provides context retrieval and streaming, runtime messaging, agent2llm and persistent context injection, configured session commands, and return to workspace scope.
- **`[doc]`** — a browser for Markdown documentation grouped under `docs/`. It provides numbered document reading, list refresh, help, and return to workspace scope.

## Commands Available in All Scopes

| Command | Description |
|---------|-------------|
| `!<command>` | Execute an arbitrary command line and remain in the current scope. Example: `!git status`. |

The command uses the same parsing and execution mechanism as `/git`: `shlex.split`, the shared `run_external_command` helper, and `os.system`. Their working-directory behavior differs: `/git` resolves the active session's project workspace and runs `git -C <project_workspace> ...`, while `!` runs in the CLI process's current working directory and inherits its environment. The command writes its standard output and standard error directly to the terminal. In the curses runtime UI, child-process output is not captured into the output pane; only the helper's `Executing ...` and `Execution completed.` messages are captured there. A non-zero shell status is reported as `Command exited with code N.`; parsing or execution-boundary failures are also reported. Entering `!` without a command prints `Usage: !<command>` and does not execute a command.

## Workspace / Project Commands

For workspace rows with an exact session metadata match whose status is `completed` and whose `session_name` is nonblank, the CLI reuses that completed-run name snapshot before querying session info. A usable session-info workspace path remains preferred; a valid completed metadata path can avoid the query, while a missing or invalid path still triggers lookup. Missing, invalid, mismatched, or non-completed metadata follows the existing fallback behavior, and completed unnamed rows remain filtered.

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
| `/control <command> [args_json]` or `/control.<subcommand>` | Send a control request through `topsailai_send_control`. Runtime scope passes `--pid` for the PID identified from the watched log entry or filename and reports an error if no PID can be resolved. |
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
| `workspace [-f json]` | Display the workspace task list and exit. The default is the human-readable table; `-f json` or `--format json` emits one JSON document. |
| `workspace driver <start/status/stop> -s SESSION [-p PID] [--json]` | Start, inspect or stop one exact session driver; see below. |
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

The JSON workspace document contains `host`, `pwd`, `home`, `task_dir`, `items`, and `total`. Each item contains `no`, `filename`, `session_name`, `session_id`, `is_task`, `pid`, `status`, `created_at`, and `project_workspace`. `created_at` is the local creation time in ISO 8601 format with a timezone offset (`YYYY-MM-DDTHH:MM:SS+/-HHMM`), or `null` when the creation time is unavailable. Items retain the default oldest-first order. An empty workspace returns `"items": []` and `"total": 0`.

## Examples

```bash
# Start the interactive CLI
./topsailai_cli.py

# Display the workspace task list without entering interactive mode
./topsailai_cli.py workspace

# Display the workspace task list as JSON
topsailai workspace -f json

# List all usage documentation files
./topsailai_cli.py docs list

# Read a specific usage documentation file
./topsailai_cli.py docs read topsailai.md

# Add the current directory to the managed project list
./topsailai_cli.py project add .

# List managed projects
./topsailai_cli.py project list

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


## Workspace session drivers

Use `/driver <number>` to start the driver for a currently running (`RUN`) or waiting-for-input (`INPUT`) session row. Use `/driver status <number>` to read state, reason, driver PID, run ID and verification. The driver commands are restricted to the ordinary workspace task list; project, session, runtime, doc and managed-project views reject them. Task rows, temporary sessions, malformed or legacy identities, changed targets and multiple live PIDs for one session are not eligible; select the session stdout row, not a task or temporary row. Status and stop can select an exited authoritative session row. Use `/driver stop <number>` to stop only its verified driver.

`/driver log <number>` reads the active session-level record at `{TOPSAILAI_HOME}/workspace/task/session_agent_driver/{session_id}.log` once and prints at most the last 20 physical lines in chronological order. The reader scans at most 8 MiB, does not follow or select rotated backups, and does not start, follow, or mutate a driver. `/driver meta <number>` reads the active session-level record at the same directory with the `.meta` suffix, at most 65,536 bytes and 64 JSON nesting levels, and prints the complete validated JSON; its embedded `pid` is the driver PID, not the selected session PID. Both records may be absent because normal driver cleanup removes them; historical rows for the same session share the same active record, which represents only the latest run and may already be cleaned up. No fallback record is selected. These two read-only commands return to the current workspace list without reloading, resorting or redrawing it, including handled read failures; use `/refresh` when a new list is needed.

### Non-interactive driver operations

```bash
topsailai workspace driver start -s SESSION -p PID --json
topsailai workspace driver status -s SESSION -p PID --json
topsailai workspace driver stop -s SESSION -p PID --json
```

Replace SESSION/PID with the intended session. All three commands exit without entering the interactive watcher. `-s/--session` is required and exact (no wildcards); optional `-p/--pid` is a positive integer and intersects the session selector. Conflicting repeated selectors are rejected. Help performs no discovery or launch. Existing `topsailai workspace [-f json]` list behavior is unchanged.

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

Only standard session stdout/stderr rows are supported, including exited sessions. The raw session ID and integer PID must agree with the filename and any recorded session PID. Task rows must be replaced with the corresponding session row; temporary, legacy and incomplete identities are rejected. No parent PID is guessed and no newest-file fallback is used.

The fixed target is `{TOPSAILAI_HOME}/workspace/task/{session_id}.{pid}.session.meta`, not driver metadata. Success prints an identity line followed by the original UTF-8 JSON text, preserving all fields and adding a final newline if needed. The JSON must be an object with exactly matching session ID and integer PID. Unknown status values are displayed unchanged.

Reads are limited to 65,536 bytes and 64 nesting levels. Missing, unreadable, oversized, malformed, excessively nested or identity-mismatched metadata produces an `[ERROR]` category without its body or a traceback. Path traversal, nonregular files and symlinks beneath the trusted home are rejected. Platforms without safe no-follow directory reads fail closed. On those platforms, the workspace list also cannot apply the metadata-based completed-to-idle override and retains its original derived process status. Reads are bounded snapshots, not transactions; incomplete concurrent writes report an error without automatic retries.

Runtime `/meta` remains unchanged: it reads the watched parent session metadata without a row argument. This increment adds no non-interactive workspace meta subcommand.

## Workspace process termination

Use `/kill 3` to target row 3 of the currently displayed ordinary workspace task list. Exactly one positive row number is required. Project, runtime, session, doc and managed-project views reject this command. Rows whose PID column is `-` are not eligible; PID 1 and the CLI's own PID are also rejected.

The confirmation identifies the row, session and exact PID and warns that unsaved work may be lost. Enter `y` or `yes` to send SIGTERM; Enter, other answers, EOF or Ctrl+C cancel without signaling. The target is only the PID column, including a task child PID when selecting a task row, never the Driver column or an inferred parent session PID. No process group or descendant traversal is performed.

Successful output means the OS accepted the signal, not that the process has exited. There is no automatic SIGKILL escalation. A successful submission refreshes the list; cancellation and errors leave it unchanged. An already-exited process or permission failure is reported with PID/session context. Logs are not deleted. Numeric PIDs can be reused between list discovery, confirmation and signaling; this command does not verify process-instance identity, so inspect the selected row carefully and refresh stale lists before use. On Windows, Python's SIGTERM behavior terminates the target rather than providing POSIX graceful-handler semantics.
