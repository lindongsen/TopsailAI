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
