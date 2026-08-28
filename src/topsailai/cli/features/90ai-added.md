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
