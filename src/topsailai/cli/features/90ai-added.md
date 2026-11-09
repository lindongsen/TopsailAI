---
maintainer: AI
---

# AI-Added Features

## Context Auto-Selection for `topsailai_launch_agent`

`topsailai_launch_agent` now automatically selects a context item from `.topsailai/settings.yaml` when `--item` is not provided. If the `context` section is empty, an interactive setup guides the user to configure context files before launching. When multiple context items exist, the launcher presents each item's full configuration (context files and environment variables) and lets the user choose, defaulting to the `default` item if it exists.

## Command Context Sources for `topsailai_launch_agent`

`topsailai_launch_agent` now supports command-based context sources in addition to file paths. A context source can be a dictionary with `type: command` whose stdout is captured and included in `TOPSAILAI_CONTEXT_USER_MESSAGE`. This allows dynamic context such as `git log`, `git status`, or project-specific generator scripts to be injected into the agent context without writing intermediate files. Existing string file paths remain fully supported, and command sources support options for shell mode, timeout, custom labels, error handling, working directory, and per-command environment variables.


## Persistent Model Selection

The CLI now reads non-secret OpenAI-compatible model definitions from `{TOPSAILAI_HOME}/.models.jsonl`, lets workspace and project scopes select them with `/models`, and automatically applies the effective persistent selection to subsequent agent and resume launches.


## Runtime Session Control

The CLI now provides `/control` in session and runtime scopes to send validated UDS control actions with optional JSON payloads, shares stdout filename parsing through `cli_topsailai.log_files`, and documents direct `topsailai_send_control` usage in `docs/usage/topsailai_send_control.md`.

## Self Environs Initial Settings for `topsailai_launch_agent`

`topsailai_launch_agent` now reads the optional top-level `self_environs` section from `.topsailai/settings.yaml` at startup and loads its flat name-to-value mapping into the launcher's own process environment (`os.environ`) as initial settings. Unlike the per-item `environment` section, these variables are not merged into the launched driver's environment; they only seed the launcher process itself (for example `TOPSAILAI_HOME`, proxy settings, or `PYTHONPATH`). A non-mapping value triggers a warning and is ignored.

## Scan Exclusion Option for `topsailai_launch_agent`

`topsailai_launch_agent` now accepts a repeatable `--exclude <names>` option that ignores the given file or folder names while scanning the workspace. It accepts comma-separated names with fnmatch wildcards (for example `build,dist,*.log`), matches either files or directories, and is merged with the `TOPSAILAI_SCAN_EXCLUDE` environment filter instead of replacing it. The option applies both to the folder tree appended to `TOPSAILAI_CONTEXT_USER_MESSAGE` and to the tree printed by `--scan`, so operators can drop noisy directories from agent context for a single run without changing environment configuration.

## Folder Tree Token Budget for `topsailai_launch_agent`

`topsailai_launch_agent` now bounds the scanned workspace folder tree with `TOPSAILAI_SCAN_MAX_TOKENS` (default `20000`, `0` or a negative value disables the limit) so a large repository can no longer inject an unbounded tree into the agent's first-turn context. The budget is charged one complete line at a time using the project tokenizer (`cl100k_base`, with a four-characters-per-token estimate when unavailable), which guarantees every listed folder and file name stays whole; as soon as the next entry would exceed the ceiling, scanning stops there without descending into that folder or listing further siblings, so the emitted tree is a prefix of the full scan rather than a sparse sample. The budget is shared across the workspace tree and an external project-folder tree, while the `> <root>` header and `.` root marker are always retained to keep the tree attributable. Truncation is observable twice, through a `[TopsailAI-Launcher] Warning: ...` line on stderr and a trailing `[... folder tree truncated at N tokens ...]` notice inside the tree, and it applies to both the context tree and the `--scan` preview.

## Folders-Only Scan Mode for `topsailai_launch_agent`

`topsailai_launch_agent` now scans folders only by default, so both the tree printed by `--scan` and the folder tree appended to `TOPSAILAI_CONTEXT_USER_MESSAGE` list directories without any file entries, which keeps the agent's first-turn context small on large repositories. Files can be requested explicitly with the mutually exclusive `--include-files` / `--folders-only` flags or with `TOPSAILAI_SCAN_INCLUDE_FILES` (boolean-like string, read from the merged environment including `self_environs`); the command-line flags take precedence over the variable, and an invalid value prints a warning and falls back to the folders-only default. Hidden names, `.gitignore` rules, the `TOPSAILAI_SCAN_EXCLUDE*` filters, `--exclude`, and the `TOPSAILAI_SCAN_MAX_TOKENS` budget behave unchanged in both modes, and a symlinked folder still appears as a leaf entry while a symlinked file stays hidden.

## Stdin Input for `topsailai_count_tokens`

`topsailai_count_tokens` now counts tokens from standard input, so it can be used directly in a pipeline: `--text -` and `--file -` both read the text from stdin, and when neither `--text`, `--file`, nor any positional file is given the command falls back to reading stdin. The implicit fallback is guarded by a `sys.stdin.isatty()` check that prints a usage error and exits with code 2 instead of blocking when stdin is an interactive terminal, and the explicit `-` forms still reject combination with positional file arguments before consuming stdin. Output stays a single integer for these single-source modes, while the existing positional `-` path keeps printing `<count> -`.

## Runtime Agent Instruction Shortcut

The CLI now provides `/agent.<instruction> [args...]` in runtime scope as a shortcut for `/control.call_instruction`. Typing `/agent.models` or `/agent.models 1` forwards the registered agent instruction `agent.models` (with optional whitespace-split positional args) through the existing control channel, so operators can invoke agent instructions without writing the full JSON payload. The shortcut requires a resolvable watched session PID, matching `/control`, and fails closed when no PID can be resolved.

## Settings-Driven Scan Controls for `topsailai_launch_agent`

`topsailai_launch_agent` now reads an optional top-level `scan` section from `.topsailai/settings.yaml`. `scan.include_files` (boolean, default `false`) lists files as well as folders in both the `--scan` preview and the workspace folder tree appended to `TOPSAILAI_CONTEXT_USER_MESSAGE`, and it participates in the existing precedence chain after the `--include-files`/`--folders-only` flags and `TOPSAILAI_SCAN_INCLUDE_FILES`. `scan.preferred_extensions` (list of strings, leading dot optional, matched case-insensitively) keeps only the matching files in folders-only mode, giving a compact middle ground between folders-only and every-file scans; it is ignored when files are already listed. Hidden names, `.gitignore` rules, `TOPSAILAI_SCAN_EXCLUDE*`, `--exclude`, and the `TOPSAILAI_SCAN_MAX_TOKENS` budget apply unchanged, and malformed `scan` values warn and fall back to the folders-only default.

## Aggregated `.tmp/` Cleanup Report for `topsailai_launch_agent`

`topsailai_launch_agent` now reports stale `.tmp/` cleanup aggregated to the first level of the directory instead of printing one absolute path per removed entry. Cleanup still walks every depth and keeps the age threshold, symlink safety, and empty-directory pruning unchanged, but each depth-1 file is printed once by relative name and each depth-1 directory is printed once with the number of entries removed beneath it, so repeated names no longer flood the launch output.

## Base Context Opt-Out for `topsailai_launch_agent`

`topsailai_launch_agent` now accepts `--no-base-context`, which drops the shared base context sources configured under `context._` (and the legacy `context._default`) for a single run so only the selected item's own sources are injected into `TOPSAILAI_CONTEXT_USER_MESSAGE`. Base environment variables from `environment._` / `environment._default` are still merged, so driver resolution and runtime settings are unchanged; the interactive item-selection summary and the `--dry-run` header describe the effective sources, and the launcher prints how many base sources were skipped.

## Environment Variable Search

The workspace CLI provides `/env.search <term> [term...]` to fuzzy-search configurable environment variables with case-insensitive OR matching, display layered `NAME=VALUE` results from `.env.local`, `.env`, and `env_template` while suppressing lower-priority duplicate names, and retain displayed names for TAB completion.

## Non-Interactive Mode for `topsailai_launch_agent`

`topsailai_launch_agent` now accepts `--non-interactive`, which guarantees the launcher itself performs no interactive action and always proceeds to launch an agent. A missing `.topsailai/settings.yaml` uses the built-in default configuration without creating a file, an existing configuration uses the `default` context item when present, a single non-base item is used directly, and multiple items without `default` fall back to the base item `_` with a warning on stderr. The empty-context setup prompt and the item-selection page are skipped, `--setup` and `--select-driver` are rejected as contradictory (exit code 2), and the flag is independent of terminal type. It affects only the launcher's own prompting and does not change the launched agent's `TOPSAILAI_INTERACTIVE_MODE`.

## Optional Folder for `topsailai workspace agent`

`topsailai workspace agent` now accepts an omitted `folder` positional and launches in the caller's working directory, so `topsailai workspace agent`, `topsailai workspace agent -b`, and `topsailai workspace agent -m raw` all work without a path. An explicit folder keeps the previous behaviour: relative paths resolve against the caller's startup directory, absolute and `~` paths stay literal, and a missing folder still exits `3` with an `invalid_folder` receipt. Help text, `README.md`, `topsailai.md`, and `docs/usage/topsailai.md` advertise the optional `[<folder>]` form and state the default.

## Non-Interactive Flag for `topsailai workspace agent`

`topsailai workspace agent` now accepts `--non-interactive`, which is forwarded to the launcher in every mechanism: foreground, detached raw background, and the tmux/dtach terminal supervisors. A launch that would otherwise prompt for a missing `.topsailai/settings.yaml` or for a context-item choice therefore proceeds without asking, so an automated caller cannot block on a prompt. The flag governs the launch only; the launched agent's own interactive mode remains controlled by `TOPSAILAI_INTERACTIVE_MODE` and is not modified. The launcher argv is built in one place (`cli_topsailai/agent_launch_command.py`) so the foreground and detached paths cannot diverge, and a resume driver never receives launcher flags.

## Default Agent Driver for `topsailai_launch_agent`

`topsailai_launch_agent` now defaults to `topsailai_agent_chats` instead of `topsailai_agent_plan_tasks`. The built-in default in `DEFAULT_CONFIG["ai_agent_driver"]` and the generated `CONFIG_TEMPLATE` were changed together so a settings file created by the launcher cannot disagree with the constant. The resolution chain is unchanged (driver menu choice, then `--driver`, then `TOPSAILAI_AGENT_DRIVER` from the selected item or base environment, then `ai_agent_driver`, then the OS environment), so only the final degrade-to-default fallback and the no-settings-file path change behaviour. Because the interactive driver menu lists the current driver first, `topsailai_agent_chats` is now option 1 and `topsailai_agent_plan_tasks` is option 2. Two unit tests pin the new literal and assert the template stays consistent with the constant.

## Automatic Session Identity for `topsailai_agent_chats`

`topsailai_agent_chats` now generates a session identifier when neither `TOPSAILAI_SESSION_ID` nor `SESSION_ID` carries a non-blank value, so a chat started without configuration still owns a session record, a session stdout file, and resumable history instead of running without an identity. Resolution follows the launcher's precedence (`TOPSAILAI_SESSION_ID`, then `SESSION_ID`, then generate), the effective value is exported through both aliases so the library, the session record, and child processes agree, and the generated value is the compact local timestamp `YYYYMMDDHHMMSS` (for example `20261105172015`), the same format the launcher already uses, so chat sessions sort by creation time. The generated identifier is announced once as `session_id: <id>` only when the agent library does not print that line itself, which keeps the `bin/` wrapper (which sets `DEBUG=1`) informative without duplicating output.

## Readable Output for `topsailai_send_control`

`topsailai_send_control` now prints control responses as readable text by default instead of escaped JSON, so a multi-line `result` such as `call_instruction` help output keeps its real newlines, indentation and separator widths. A string result is printed verbatim, an object or array result is printed as indented JSON, and a non-empty result is always printed whatever the status is; only an empty result (`null`, a blank string, or an empty container) is omitted. Terminal escape sequences and control characters other than newline and tab are stripped because responses originate from the agent process, and color is applied only on a terminal with `NO_COLOR` unset. `--json` now selects the raw `json.dumps(..., ensure_ascii=False, indent=2)` output and is the machine-readable contract, which also makes the previously unused flag effective. Multi-target runs prefix each block with a `=== <socket path> ===` header in readable mode.

## Workspace Session History Through the Control Channel

`/session <number>` in the ordinary workspace task list now shows history for a row that has no session id. A temporary session is displayed as `(temp)` and stored under the reserved `topsailai` prefix, so the database lookup keyed by a real session id cannot serve it. When that row's Unix-domain control socket exists, the CLI sends exactly one `call_instruction` request with the payload `{"instruction": "ctx.history"}` and prints the returned history text, translating the display marker to the reserved file prefix before composing `{TOPSAILAI_HOME}/workspace/task/topsailai.{pid}.session.sock`. A row with a real session id keeps the unchanged `topsailai_retrieve_messages --max-chars 1000` path. The socket must be a socket inode (a regular file or symlink is not a channel) and its owner PID must be provably alive, because a socket file outlives its owner and a stale file cannot answer; a task row is served only through its unambiguous parent session PID, a literal `/session (temp)` argument resolves the single live matching socket and reports several live matches as ambiguous, and unsafe identifiers are rejected before any path is composed. When no channel exists the previous message is kept; a rejected request or transport failure prints one classified `[ERROR]` line and is never retried. Returned text is sanitized of ANSI escapes and control characters while preserving newlines and tabs.

## Batch Session Detail Command `topsailai_sessions_info`

`topsailai_sessions_info` shows detailed information for many sessions in one invocation. It reuses `topsailai_session_info`'s formatters, so each card and each JSON record is identical to the single-session command, and it resolves every requested identifier with one `list_sessions(sessions=[...])` query instead of one lookup per session. Sessions are printed in command-line order, duplicates are collapsed, and missing identifiers are reported on stderr so stdout stays machine-parseable; the exit code is `1` when any requested session is missing or on a storage error.

## Follow Mode for `topsailai runtime logs`

`topsailai runtime logs` accepts `-f/--follow`, so `-n 100 -f` behaves like `tail -n 100 -f`: the initial tail is printed exactly as in snapshot mode, then appended records are printed as they are written until the host interrupts. The target is resolved once and its descriptor is opened once, so a later poll can never select another session log and rotation keeps reading the original file. Only complete LF-delimited records are printed; an unterminated remainder is held in a 1 MiB bounded buffer and printed once when the follow ends, and appended bytes are read in bounded chunks under the existing 8 MiB per-poll budget with a 0.5 second wait between polls. Shrinkage restarts at the new beginning of the file while a detected identity change fails with `log_changed`. An interrupt is the normal end of a follow and exits `0`; other failures keep the snapshot exit codes. Follow prints only records, so `-f` with `--json` and `-f` for `send`, `btw`, `control` and the instruction form are rejected with exit `2`.

## JSON Output for `topsailai session history`

`topsailai session history` accepts `--json`, so a script can read one session's stored context messages without parsing the human-readable report. The backing retrieval script gained its own `--json` that prints the stored message objects as one JSON array, and the session subcommand wraps that array in the same structured envelope the other session actions already use (`ok`, `exit_code`, `action`, `session_id`, `message_count`, `messages`, `error_code`, `message`). `--max-chars` keeps one meaning in both modes because the limit is applied to the message objects before serialization. A child failure, a missing child command, or an unusable document is reported as a classified result with `messages` and `message_count` set to `null`, so stdout always stays a single parseable object and a diagnostic never mixes into it. Without `--json` the previous streaming path is unchanged.

## JSON Output for `topsailai session status`

`topsailai session status` accepts `--json`, so a script can read one session's running state without parsing a bare status word. The structured result carries `session_id`, `status`, `error_code` and `message`, where `error_code` is `null` on success and a classified value such as `missing_session_id` or `status_unavailable` on failure. The exit code is `0` when a status was resolved and `1` when it was not, and plain mode keeps printing the bare word while sending diagnostics to stderr so stdout stays clean.

## JSON Output for `topsailai_count_tokens`

`topsailai_count_tokens` accepts `--json`, so a caller can read token counts without parsing bare numbers. Every input path is covered: `--text` reports `source: "text"`, `--file` reports `source: "file"`, the implicit stdin fallback reports `source: "stdin"`, and a multi-file run reports `source: "files"` with a `results` array carrying a per-path `count` and `error`. `--text -` reads stdin and therefore reports the same `stdin` label as `--file -`, so "read from stdin" has exactly one name. A missing file in a multi-file run is reported as `file_not_found` for that entry instead of aborting the whole run.

## JSON Output for `topsailai docs list` and `topsailai docs read`

`topsailai docs list` and `topsailai docs read` accept `--json`, so documentation discovery and retrieval are machine-readable. `docs list` emits the full record array with `row_number`, `filename`, `folder`, `rel_path`, `path`, `title`, `size_bytes` and `created`. `docs read` emits one result object carrying `status`, `content`, `path`, `rel_path` and `options`, and returns exit code `1` when the status is not `ok`, so a caller can distinguish a resolved document from a missing or ambiguous name without parsing text.

## One Shared `--json` Help Sentence

Every `topsailai session` subcommand that accepts `--json` now reuses one shared help sentence instead of repeating a slightly different wording per subcommand, and the parent command states the contract once in its epilog. The flag keeps identical behaviour; only the help text changed, so the contract is stated once and the per-subcommand output is no longer noisy.
