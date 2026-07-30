---
references:
  - topsailai_models.py
  - cli_topsailai/models_cli.py
  - cli_topsailai/models.py
---

# CLI: topsailai models

Manage the per-workspace model registry stored in `{TOPSAILAI_HOME}/.models.jsonl`.

## Synopsis

```text
topsailai models list [--json]
topsailai models add <name> --config KEY=VALUE ... [--json]
topsailai models get <name> [--json]
topsailai models update <name> --config KEY=VALUE ... [--json]
topsailai models delete <name> [--yes] [--json]
```

## Description

The `models` subcommand provides non-interactive CRUD operations for the model registry. Each registry entry is a JSON object on its own line in `{TOPSAILAI_HOME}/.models.jsonl` and must contain a unique `name` field.

Credential secrets must never be stored directly. Use `api_key_env`, `organization_env`, and `project_env` to reference environment-variable names instead.

## Subcommands

### list

Print all model entries with row numbers and pretty-printed JSON.

```bash
topsailai models list
```

Use `--json` for compact machine-readable output.

### add

Append a new model entry. Duplicate `name` values are rejected.

```bash
topsailai models add "GPT-4o" \
  --config provider=openai \
  --config protocol=openai-compatible \
  --config model=gpt-4o \
  --config api_key_env=OPENAI_API_KEY
```

If `id` is omitted, it is derived from `<name>` by lowercasing and replacing whitespace with `-`.

### get

Print the full JSON for the model identified by `<name>`.

```bash
topsailai models get "GPT-4o"
```

### update

Merge `--config` key/value pairs into an existing entry identified by `<name>`.

```bash
topsailai models update "GPT-4o" \
  --config base_url=https://api.example.test/v1 \
  --config enabled=true
```

Renaming is not required. If `name` is changed, the new name must not already exist.

### delete

Remove the model identified by `<name>`.

```bash
topsailai models delete "GPT-4o"
```

When running interactively, a confirmation prompt is shown. Use `--yes` to skip it.

If the deleted model is currently selected in `.model_selection.json`, the matching workspace and project selections are cleared automatically.

## Validation rules

- `name` is required and must be unique.
- Literal secret fields (`api_key`, `organization`, `project`) are rejected.
- Credential references must use `api_key_env`, `organization_env`, or `project_env`.
- Unknown fields are rejected.

## Output

Pretty-printed JSON is used by default. Pass `--json` to emit compact JSON suitable for piping to other tools.

## Files

- `{TOPSAILAI_HOME}/.models.jsonl` — model registry.
- `{TOPSAILAI_HOME}/.model_selection.json` — workspace and project model selections.
