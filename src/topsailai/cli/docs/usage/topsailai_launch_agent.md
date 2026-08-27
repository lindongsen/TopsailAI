---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_launch_agent

Launch an AI agent driver based on a local `.topsailai/settings.yaml` configuration.

## Purpose

Reads `.topsailai/settings.yaml` from the current working directory, resolves the agent driver, merges environment variables, reads configured context files, appends a workspace folder tree to `TOPSAILAI_CONTEXT_USER_MESSAGE`, and launches the configured driver.

## Project Folder Scoping

When `TOPSAILAI_PROJECT_FOLDER` is set, the workspace folder tree appended to `TOPSAILAI_CONTEXT_USER_MESSAGE` is scoped to that folder instead of the entire workspace.

This variable is read from the merged environment with the following priority:

1. The selected item's environment section in `.topsailai/settings.yaml`.
2. The base `_` environment section in `.topsailai/settings.yaml`.
3. The OS environment (`os.environ`).

If `TOPSAILAI_PROJECT_FOLDER` points to a directory inside the workspace, only that directory is scanned. If it points outside the workspace, both the workspace and the external project folder are scanned so the agent sees the full workspace context alongside the external project.

Example configuration:

```yaml
environment:
  _:
    TOPSAILAI_PROJECT_FOLDER: "./src/my-service"
```

Or via the OS environment:

```bash
TOPSAILAI_PROJECT_FOLDER=./src/my-service topsailai_launch_agent
```

## Hidden Files

Files and directories whose names start with `.` are excluded from the generated folder tree by default. This includes entries such as `.git`, `.venv`, `.env`, and `.tmp`. Only non-hidden project content is included in `TOPSAILAI_CONTEXT_USER_MESSAGE`.

## Invocation

```bash
./topsailai_launch_agent.py
./topsailai_launch_agent.py --item memo
./topsailai_launch_agent.py --driver topsailai_agent_chats --dry-run
```

Because the script is registered in `../bin/` as `topsailai_launch_agent`, you can also run it as:

```bash
topsailai_launch_agent
```

## Options

| Option | Description |
|--------|-------------|
| `--item <name>` | Select a context/environment item defined in `settings.yaml`. |
| `--driver <command>` | Override the `ai_agent_driver` value. |
| `--dry-run` | Print the resolved command, working directory, and merged environment variables without executing. |
| `--subprocess` | Use `subprocess.run()` instead of `os.system()` (default). |
| `--setup` | Force the guided interactive setup to create `.topsailai/settings.yaml` when it is missing. |
| `--scan <folder>` | Scan the specified folder and print its tree structure, then exit. Reuses the same ignore rules and formatting as the workspace scan. Only folders are listed unless files are explicitly requested. |
| `--include-files` | Also list files in the scanned tree (both `--scan` output and the folder tree appended to `TOPSAILAI_CONTEXT_USER_MESSAGE`). Overrides `TOPSAILAI_SCAN_INCLUDE_FILES`. |
| `--folders-only` | List folders only, suppressing files. This is the default behavior; the flag is provided to override `TOPSAILAI_SCAN_INCLUDE_FILES`. Mutually exclusive with `--include-files`. |
| `--exclude <names>` | Ignore these file or folder names while scanning. Accepts comma-separated names with fnmatch wildcards (for example `build,dist,*.log`). May be repeated. Merged with `TOPSAILAI_SCAN_EXCLUDE`. |

## Scan Mode (Folders Only vs. Files)

The scan lists folders only by default, for both the `--scan` output and the workspace folder tree appended to
`TOPSAILAI_CONTEXT_USER_MESSAGE`. Files are omitted from the tree, which keeps the first-turn context small on large
repositories while still showing the directory layout the agent can navigate.

Pass `--include-files` to list files as well:

```bash
# Folders only (default)
topsailai_launch_agent --scan ./src/topsailai/cli

# Folders and files
topsailai_launch_agent --scan ./src/topsailai/cli --include-files
topsailai_launch_agent --include-files
```

`--folders-only` forces the folders-only mode and takes precedence over an enabling environment variable. The two flags
are mutually exclusive.

Precedence:

1. `--include-files` or `--folders-only` on the command line.
2. `TOPSAILAI_SCAN_INCLUDE_FILES` from the merged environment (selected item, then base `_`, then the OS environment).
3. Folders only.

A symlinked folder stays visible as a leaf entry in folders-only mode (it is not descended into); a symlinked file is
hidden like any other file. Hidden names, `.gitignore` rules, and the exclusion filters described below apply unchanged
in both modes.

## Scanning a Folder

Use `--scan <folder>` to preview the folder tree that would be generated for a given directory. This option does not launch an agent driver; it only prints the tree and exits.

```bash
./topsailai_launch_agent.py --scan ./src/topsailai/cli
topsailai_launch_agent --scan ./src/topsailai/cli
```

The output uses the same ignore rules and tree formatting as the workspace scan appended to `TOPSAILAI_CONTEXT_USER_MESSAGE`, including the folders-only default (see "Scan Mode (Folders Only vs. Files)"). Hidden files and directories are excluded, and `.gitignore` patterns are respected. Add `--include-files` to list files as well, and `--exclude <names>` to ignore extra file or folder names for a single run (see "Command-Line Exclusions"). The tree is also bounded by the same `TOPSAILAI_SCAN_MAX_TOKENS` budget (see "Folder Tree Token Budget").

## Environment Variables

The variables below are consumed only by `topsailai_launch_agent`. They are intentionally kept out of the global
`docs/usage/Environment_Variables.md`; this section is their single source of truth.

| Variable | Applies to | Accepted format | Default | Example |
|----------|------------|-----------------|---------|---------|
| `TOPSAILAI_SCAN_EXCLUDE` | both files and directories | comma-separated names, fnmatch wildcards | unset (filter disabled) | `node_modules,.cache,tmp` |
| `TOPSAILAI_SCAN_EXCLUDE_DIRS` | directory names only | comma-separated names, fnmatch wildcards | unset (filter disabled) | `vendor,build,dist` |
| `TOPSAILAI_SCAN_EXCLUDE_FILES` | file names only | comma-separated names, fnmatch wildcards | unset (filter disabled) | `*.log,*.tmp,Makefile` |
| `TOPSAILAI_SCAN_MAX_TOKENS` | size of the scanned folder tree | integer | `20000` | `5000` |
| `TOPSAILAI_SCAN_INCLUDE_FILES` | whether the scanned folder tree lists files | boolean-like string (`1`/`true`/`yes`/`on`, `0`/`false`/`no`/`off`) | unset (folders only) | `true` |
| `TOPSAILAI_TMP_CLEANUP_MAX_AGE_DAYS` | stale-file cleanup in `{workspace}/.tmp/` on launch | float greater than zero | `1` | `0.5` |

### Scan Exclusion Filters

`TOPSAILAI_SCAN_EXCLUDE`, `TOPSAILAI_SCAN_EXCLUDE_DIRS`, and `TOPSAILAI_SCAN_EXCLUDE_FILES` filter specific names out of
the scanned workspace folder tree — the tree appended to `TOPSAILAI_CONTEXT_USER_MESSAGE` and the tree printed by `--scan`.

- All three accept comma-separated names and support fnmatch wildcards (for example `*.log`, `build*`).
- Unset or empty values disable the corresponding filter.
- Names starting with `.` are already excluded by default and do not need to be listed here.

```bash
# Exclude names whether they are files or directories
export TOPSAILAI_SCAN_EXCLUDE="node_modules,.cache,tmp"

# Exclude only directories
export TOPSAILAI_SCAN_EXCLUDE_DIRS="vendor,build,dist"

# Exclude only files
export TOPSAILAI_SCAN_EXCLUDE_FILES="*.log,*.tmp,Makefile"
```

They can also be seeded from `.topsailai/settings.yaml`, because the launcher loads `self_environs` into its own process
environment before scanning:

```yaml
self_environs:
  TOPSAILAI_SCAN_EXCLUDE_DIRS: "vendor,dist"
```

### Scan File Inclusion

`TOPSAILAI_SCAN_INCLUDE_FILES` controls whether the scanned folder tree lists files or only folders. It applies to the
tree appended to `TOPSAILAI_CONTEXT_USER_MESSAGE` and to the tree printed by `--scan`.

- Unset, empty, or any falsy value (`0`, `false`, `no`, `n`, `off`) keeps the default folders-only tree.
- `1`, `true`, `yes`, `y`, `on` (case-insensitive) list files together with folders.
- Any other value prints a warning to stderr and falls back to the folders-only default.
- `--include-files` / `--folders-only` on the command line always take precedence over this variable.

```bash
# List files as well as folders
export TOPSAILAI_SCAN_INCLUDE_FILES=true
```

It can also be seeded from `.topsailai/settings.yaml` through `self_environs`:

```yaml
self_environs:
  TOPSAILAI_SCAN_INCLUDE_FILES: "true"
```

### Command-Line Exclusions

`--exclude <names>` is the command-line counterpart of `TOPSAILAI_SCAN_EXCLUDE`. It applies to both the workspace folder
tree appended to `TOPSAILAI_CONTEXT_USER_MESSAGE` and the tree printed by `--scan`.

- It accepts comma-separated names and supports the same fnmatch wildcards (for example `*.log`, `build*`).
- It can be repeated; every occurrence is merged.
- It is merged with (not replacing) `TOPSAILAI_SCAN_EXCLUDE`, so environment-based defaults stay in effect.
- Use `TOPSAILAI_SCAN_EXCLUDE_DIRS` / `TOPSAILAI_SCAN_EXCLUDE_FILES` when a name must be filtered only as a directory or
  only as a file; `--exclude` matches either kind.

```bash
# Ignore these names in addition to the environment-based filters
topsailai_launch_agent --exclude "build,dist,*.log"

# Repeat the option for readability
topsailai_launch_agent --exclude node_modules --exclude "*.tmp"

# Preview the resulting tree before launching
topsailai_launch_agent --scan ./src/topsailai/cli --exclude "tests,*.md"
```

### Folder Tree Token Budget

`TOPSAILAI_SCAN_MAX_TOKENS` bounds the size of the scanned workspace folder tree, which is the largest single contributor
to the agent's first-turn context. It applies to the tree appended to `TOPSAILAI_CONTEXT_USER_MESSAGE` and to the tree
printed by `--scan`.

- Default is `20000` tokens. Set it to `0` or a negative value to scan without any limit.
- When the value is unset, empty, or not an integer, the launcher prints a warning to stderr and uses the default.
- Tokens are counted with the project tokenizer (`cl100k_base`). If that tokenizer is unavailable, a character-based
  estimate of about four characters per token is used instead, so scanning never fails.
- The budget is charged one complete line at a time, so every listed folder and file name is always whole; a name is
  never cut in half.
- As soon as the next entry would exceed the budget, scanning stops there. No deeper folder is visited and no further
  sibling is listed, so the tree is a prefix of the full scan rather than a sparse sample.
- In the default folders-only mode, fewer lines are emitted, so the same budget reaches deeper into the tree. Raise the
  budget or use `--include-files` deliberately when the agent needs file names.
- When both the workspace and an external project folder are scanned, the two trees share one budget.
- The `> <root>` header and the `.` root marker are always kept so the tree stays attributable, even if they alone
  exceed a very small budget.
- Truncation is reported twice: a `[TopsailAI-Launcher] Warning: ...` line on stderr and a trailing
  `[... folder tree truncated at N tokens ...]` line inside the tree itself.

```bash
# Keep the folder tree small on a large repository
TOPSAILAI_SCAN_MAX_TOKENS=5000 topsailai_launch_agent

# Restore the previous unlimited behavior
TOPSAILAI_SCAN_MAX_TOKENS=0 topsailai_launch_agent

# Preview how much of the tree survives a budget
TOPSAILAI_SCAN_MAX_TOKENS=5000 topsailai_launch_agent --scan ./src/topsailai/cli
```

Prefer narrowing the scan with `TOPSAILAI_SCAN_EXCLUDE*`, `--exclude`, or `TOPSAILAI_PROJECT_FOLDER` over raising the
budget, so the retained entries stay the most relevant part of the tree.

### Stale `.tmp/` Cleanup Threshold

`TOPSAILAI_TMP_CLEANUP_MAX_AGE_DAYS` sets the age threshold (in days) used when the launcher clears stale files from
`{workspace}/.tmp/` on launch. Files older than this many days are removed; fresher files are kept. The value accepts a
float (for example `1` or `0.5`) and must be greater than zero. When it is unset, non-numeric, or not greater than zero,
the launcher prints a warning to stderr and falls back to the default of `1` day.

```bash
TOPSAILAI_TMP_CLEANUP_MAX_AGE_DAYS=0.5 topsailai_launch_agent
```

## Context Item Selection

When `--item` is omitted:

- If the `context` section is completely empty, the launcher enters an interactive setup in TTY mode.
- If only `_` is configured, `_` is used automatically.
- If exactly one non-base item is configured, that item is used automatically.
- If multiple non-base items are configured, a numbered list is shown; `default` is pre-selected if it exists.

## Driver Resolution Priority

1. `--driver` CLI argument
2. `TOPSAILAI_AGENT_DRIVER` from the selected item or `_` environment section
3. `ai_agent_driver` field in `settings.yaml`
4. `TOPSAILAI_AGENT_DRIVER` from the OS environment

## Configuration File

The settings file is `.topsailai/settings.yaml` in the current working directory. Example structure:

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

- `_` is the base configuration shared by all items.
- `_default` is still supported for backward compatibility.
- Context sources are either file paths (strings) or command sources (dicts).
- File paths are relative to `workspace` unless they start with `/`.

### Command Context Sources

A command context source runs a shell command and captures its stdout as context content.

```yaml
context:
  _:
    - "README.md"
    - type: command
      command: "git log --oneline -10"
      timeout: 5
      label: "recent-commits"
    - type: command
      command: "git status --short"
      shell: true
      label: "git-status"
```

Supported fields for command sources:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | required | Must be `command`. |
| `command` | string | required | The command to execute. |
| `shell` | bool | `true` | Whether to run the command through a shell. |
| `timeout` | number | `30` | Maximum execution time in seconds. |
| `label` | string | command string | Label used in the formatted context block. |
| `on_error` | string | `abort` | Behavior when the command fails or times out: `include` (include error message), `skip` (skip the block), or `abort` (raise an error). |
| `cwd` | string | `workspace` | Working directory for the command. |
| `environ` | dict | `{}` | Extra environment variables for this command only. |

Command output is formatted as:

```text
> Command: <label> > START
<stdout>
> Command: <label> > END
```

## Examples

```bash
# Launch with the default item
topsailai_launch_agent

# Launch a specific item
topsailai_launch_agent --item memo

# Preview what would be executed
topsailai_launch_agent --item default --dry-run

# Use subprocess.run instead of os.system
topsailai_launch_agent --subprocess

# Force interactive setup
topsailai_launch_agent --setup

# Scan a folder and print its tree structure
topsailai_launch_agent --scan ./src/topsailai/cli
```

## Notes

- A temporary context message file is written under `{workspace}/.tmp/` and cleaned up on exit, uncaught exceptions, and `SIGINT`/`SIGTERM`.
- On launch, the launcher clears stale files in `{workspace}/.tmp/`. Only files older than the configured age threshold are removed; fresher files are preserved so ongoing work is not lost on relaunch. Empty subdirectories left behind are pruned and the `.tmp/` directory is recreated if missing. See `TOPSAILAI_TMP_CLEANUP_MAX_AGE_DAYS` under "Environment Variables".
- The launcher changes to the configured `workspace` before running the driver.
- In `--dry-run` mode, command context sources are listed but not executed.
- In `--dry-run` mode, the launcher prints `[TopsailAI-Launcher] Context token count: N` for the assembled context message. The count is informational only; when it cannot be computed the launcher prints a warning and continues. Use it to check how much of the first-turn context the folder tree consumes before raising `TOPSAILAI_SCAN_MAX_TOKENS`.

### Self Environs (Initial Settings)

The optional top-level `self_environs` section is a flat mapping of
environment-variable name to value. Its variables are loaded into the
launcher's OWN process environment (`os.environ`) at startup as initial
settings. Unlike the `environment` section, these variables are NOT merged
into the launched driver's environment; they only seed the launcher process
itself (for example `TOPSAILAI_HOME`, proxy settings, or `PYTHONPATH`).

```yaml
self_environs:
  TOPSAILAI_HOME: "/custom/home"
  HTTPS_PROXY: "http://proxy.example:3128"
```

