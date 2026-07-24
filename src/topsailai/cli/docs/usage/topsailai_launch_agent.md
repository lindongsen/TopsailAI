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

If `TOPSAILAI_PROJECT_FOLDER` points to a directory inside the workspace, only that directory is scanned. If it points outside the workspace, the launcher falls back to scanning the whole workspace.

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
| `--scan <folder>` | Scan the specified folder and print its tree structure, then exit. Reuses the same ignore rules and formatting as the workspace scan. |

## Scanning a Folder

Use `--scan <folder>` to preview the folder tree that would be generated for a given directory. This option does not launch an agent driver; it only prints the tree and exits.

```bash
./topsailai_launch_agent.py --scan ./src/topsailai/cli
topsailai_launch_agent --scan ./src/topsailai/cli
```

The output uses the same ignore rules and tree formatting as the workspace scan appended to `TOPSAILAI_CONTEXT_USER_MESSAGE`. Hidden files and directories are excluded, and `.gitignore` patterns are respected.

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
ai_agent_driver: "ai-team-flow-dev"
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
| `on_error` | string | `include` | Behavior when the command fails or times out: `include` (include error message), `skip` (skip the block), or `abort` (raise an error). |
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
- The launcher changes to the configured `workspace` before running the driver.
- In `--dry-run` mode, command context sources are listed but not executed.
