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
