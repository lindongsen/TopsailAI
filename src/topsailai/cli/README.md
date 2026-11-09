# CLI Tools

This directory contains the command-line interface (CLI) tools for the project.

> CLI NO NEED issues

## Workspace Scope

This directory (`./`, example: `/TopsailAI/src/topsailai/cli/`) is the current workspace. All development, fixes, and documentation updates must stay within this workspace.

> **Path portability:** Use relative paths in this document. `../bin/` refers to `src/topsailai/bin/` (the project's executable directory) and `../` refers to the project folder.

- Do not concern yourself with code under `../src/topsailai` (for example, `../src/topsailai/ai_base`).
- Do not modify any files outside this workspace unless explicitly asked.

If a change in the CLI requires a corresponding change in `../src/topsailai`, treat it as out of scope and report it instead of editing the source tree.

## Documentation Rules

Usage documentation lives in `docs/usage/`. Each CLI script has one usage document named after the script, and `docs/usage/README.md` is the index.

- **Usage content belongs in `docs/usage/{cli}.md`.** Whenever a CLI script's behavior, options, environment variables, output format, exit codes, or examples change, update the matching document under `docs/usage/` in the same change. Do not describe usage in this `README.md` or in a `{CLI}.md` file in this directory.
- **A `{CLI}.md` file in `cli/` records only design, rules, caveats, and index/reference information.** It must not record usage: no command tables, no option lists, no syntax, no examples, no exit codes. Link to the matching `docs/usage/{cli}.md` document instead.

| Document | Content |
|---|---|
| `docs/usage/README.md` | Usage index, `TOPSAILAI_HOME` layout, shared conventions. |
| `docs/usage/topsailai.md` | `topsailai_cli.py` usage: scopes, commands, runtime, subcommands, drivers, resume. |
| `docs/usage/topsailai_launch_agent.md` | Launcher usage: options, context sources, environment variables, driver selection. |
| `docs/usage/topsailai_models.md` | Model registry usage and model selection. |
| `docs/usage/topsailai_session_add_message.md` | Persistent user-to-agent message usage. |
| `docs/usage/topsailai_session_add_agent2llm_message.md` | Runtime agent2llm message injection usage. |
| `docs/usage/topsailai_project_history.md` | Project history listing usage. |

See `docs/usage/README.md` for the complete list of documented scripts.

## List Sorting

Lists that display discovered files or history entries are sorted by creation time by default, with older items appearing first and newer items appearing last.

## Structure

```
.
├── cli_topsailai/         # Shared package used by CLI scripts
│   ├── __init__.py
│   └── ...
├── <cli-name>.py          # CLI entry point
├── tests/
│   └── unit/
│       └── <cli-name>/    # Unit tests for the corresponding CLI
│           └── test_*.py
```

The `cli_topsailai` package is a common library that can be imported by any CLI script under this directory.
## Testing

Unit tests for each CLI tool are organized under `tests/unit/{cli-name}/`.

For example:

- `topsailai_cli.py` → `tests/unit/topsailai/`
- `topsailai_models.py` → `tests/unit/topsailai_models/`

When adding a new CLI tool, create a matching folder under `tests/unit/` and place its tests there.

## Naming Conventions

### CLI Scripts

All CLI script names should start with `topsailai` to keep the command namespace consistent and easy to discover.

For example:

- `topsailai_cli.py`
- `topsailai_launch_agent.py`
- `topsailai_session_status.py`
- `topsailai_models.py`

When adding a new CLI tool, prefix its entry-point script with `topsailai` (e.g., `topsailai_<feature>.py`).

### CLI-Specific Configuration and Documentation

An environment variable (or any other script-specific configuration detail) that is consumed only by a single CLI tool
should not be added to the global `docs/usage/Environment_Variables.md`. Instead, document it in the corresponding usage
document `docs/usage/{cli}.md` (for example `docs/usage/topsailai_launch_agent.md` for `topsailai_launch_agent.py`),
under an "Environment Variables" section.

The same rule applies to script-specific descriptions and notes: configuration meanings, accepted formats (for example
comma-separated names with wildcards), default and example values, and behavioral caveats all belong in the matching
usage document. Each usage document is the single source of truth for its script, so do not duplicate this information in
co-located side files or in the global environment-variable reference.

Files used exclusively by one CLI command must be prefixed with that CLI's name so they remain distinguishable from
other configuration or history files. For example, the `topsailai_cli` command uses `.topsailai_cli.history.jsonl`, not
a generic `.history.jsonl`, which distinguishes it from `.input_history.jsonl` and `.project_history.jsonl`.

### Environment Variable Naming

Every environment variable consumed only by a CLI script MUST use the `TOPSAILAI_CLI_` prefix, for example
`TOPSAILAI_CLI_HISTORY_MAX_ENTRIES` or `TOPSAILAI_CLI_RESUME_CONFIRM_SECONDS`. The prefix states that the variable is
owned by this workspace, so a reader can tell a CLI knob from a project-wide setting without searching the source tree.

A variable that the core code defines MUST NOT use that prefix, because the CLI only consumes it. Decide by checking
whether the core code defines the variable, whether the core environment-variable reference
`docs/Environment_Variables.md` lists it, or whether the core `env_template` declares it. When any of those is true,
keep the unprefixed name and read it as a core contract; the CLI must not rename a setting it does not own.

A variable that is also read by a component outside this workspace MUST NOT use that prefix either, because the prefix
would claim an ownership the CLI does not have. When the answer is yes, keep the unprefixed name and treat it as a
cross-component contract.

A variable that doubles as a configuration key in `.topsailai/settings.yaml` is a cross-component contract as well, even
when no code outside `cli/` reads the environment variable directly. Renaming it would break existing configuration
files, so the unprefixed name is kept.

When a CLI-only variable is renamed, update every reference in the same change: the source that reads it, the matching
usage document under `docs/usage/`, and the tests that set it.

A renamed variable MUST keep accepting its previous name. Read it through `cli_topsailai/env_compat.py` instead of
`os.getenv` directly: `get_env` consults the prefixed name first and the legacy name second, so an operator who still
exports the old name keeps working while the prefixed name always wins. The first use of a legacy name prints one
`[WARN]` deprecation notice. An empty value counts as configured and does not fall back, because at least one variable
assigns a meaning to the empty string. Add the new mapping to `LEGACY_NAMES` in the same change that renames a variable.

## Adding a New CLI Tool

When you create a new CLI script under this directory, you must also register it as a command in the parent project's `bin/` folder so it can be invoked directly by name.

### Step 1: Create the CLI script

Add a Python entry point named `topsailai_<feature>.py` in this directory (`./`). For example:

```bash
topsailai_session_info.py
topsailai_models.py
```

### Step 2: Create a matching symlink in `bin/`

Most CLI scripts are dispatched through `../bin/topsailai.cli`, which resolves the script name from `basename "$0"` and runs `cli/<name>.py`. Therefore, add a symlink pointing to `topsailai.cli`:

```bash
cd ../bin
ln -s topsailai.cli topsailai_<feature>
```

For example, for `topsailai_session_info.py`:

```bash
cd ../bin
ln -s topsailai.cli topsailai_session_info
```

### Step 3: Verify the symlink

```bash
ls -l ../bin/topsailai_<feature>
# should show: topsailai_<feature> -> topsailai.cli
```

Then test the command:

```bash
topsailai_<feature> --help
```

### Notes

- The symlink name must match the Python file name without the `.py` extension.
- Do not forget to add unit tests under `tests/unit/<cli-name>/` as described in the Testing section above.

## Modification Rule

When a user asks to modify a script but does not explicitly specify which script to change, do not guess. You must ask the user to clarify the exact script before making any edits.
