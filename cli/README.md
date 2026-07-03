# CLI Tools

This directory contains the command-line interface (CLI) tools for the project.

## Structure

```
.
├── <cli-name>.py          # CLI entry point
├── tests/
│   └── unit/
│       └── <cli-name>/    # Unit tests for the corresponding CLI
│           └── test_*.py
```

## Testing

Unit tests for each CLI tool are organized under `tests/unit/{cli-name}/`.

For example:

- `topsailai.py` → `tests/unit/topsailai/`

When adding a new CLI tool, create a matching folder under `tests/unit/` and place its tests there.

## Naming Conventions

### CLI Scripts

All CLI script names should start with `topsailai` to keep the command namespace consistent and easy to discover.

For example:

- `topsailai.py`
- `topsailai_launch_agent.py`
- `topsailai_session_status.py`

When adding a new CLI tool, prefix its entry-point script with `topsailai` (e.g. `topsailai_<feature>.py`).

## Available CLI Tools

### `topsailai_launch_agent.py`

Launch an AI agent driver based on a local `.topsailai/settings.yaml` configuration.

**What it does:**

- Reads `.topsailai/settings.yaml` from the current working directory.
- Selects a configured item via `--item` (default is `default`).
- Merges environment variables in the order: system environment → `_default` → item-specific values.
- Reads the configured context files ( `_default` first, then item-specific files) and appends a workspace folder tree to `TOPSAILAI_CONTEXT_USER_MESSAGE`.
- Writes the assembled context message to a temporary file under `{workspace}/.tmp/` to avoid exceeding environment-variable size limits.
- Launches the configured `ai_agent_driver` using `os.system` by default, or `subprocess.run` when `--subprocess` is passed.
- Cleans up the temporary context file on exit, uncaught exceptions, and `SIGINT`/`SIGTERM`.

**Common options:**

- `--item <name>` — Select a context/environment item defined in `settings.yaml`.
- `--driver <command>` — Override the `ai_agent_driver` value.
- `--dry-run` — Print the resolved command, working directory, and merged environment variables without executing.
- `--subprocess` — Use `subprocess.run()` instead of `os.system()`.

**Driver resolution priority:**

1. `--driver` CLI argument
2. `TOPSAILAI_AGENT_DRIVER` from the selected item or `_default` environment section
3. `ai_agent_driver` field in `settings.yaml`
4. `TOPSAILAI_AGENT_DRIVER` from the OS environment

If `.topsailai/settings.yaml` is missing, the script prints a configuration template and exits.
