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
- Context file paths are relative to `workspace` unless they start with `/`.

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
```

## Notes

- A temporary context message file is written under `{workspace}/.tmp/` and cleaned up on exit, uncaught exceptions, and `SIGINT`/`SIGTERM`.
- The launcher changes to the configured `workspace` before running the driver.
