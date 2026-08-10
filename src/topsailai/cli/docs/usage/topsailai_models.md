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

## Configuration fields

Use `--config KEY=VALUE` to set any of the following fields when calling `add` or `update`.

| Field | Required | Description |
|---|---|---|
| `name` | yes | Unique display name for the model. For `add` it is taken from the positional argument, but you can also override it with `--config name=...`. |
| `id` | no | Stable machine identifier. If omitted, it is derived from `name` by lowercasing and replacing whitespace with `-`. |
| `provider` | yes | Provider name, e.g. `openai`, `azure`, `local`. |
| `protocol` | yes | Must be `openai-compatible`. |
| `model` | yes | Actual model ID sent to the API, e.g. `gpt-4o`. |
| `base_url` | no | OpenAI-compatible endpoint URL, e.g. `https://api.openai.com/v1`. |
| `api_key_env` | no* | Name of the environment variable that holds the API key. **Required for most providers.** Do not pass `api_key`. |
| `organization_env` | no | Name of the environment variable for the organization ID. Do not pass `organization`. |
| `project_env` | no | Name of the environment variable for the project ID. Do not pass `project`. |
| `description` | no | Short human-readable description. |
| `tags` | no | List of tags, e.g. `["prod","vision"]`. |
| `enabled` | no | `true` or `false`. Defaults to `true`. |
| `metadata` | no | Arbitrary JSON object for extra settings. |
| `environment` | no | Extra environment variables to apply to the process environment when this model is selected (e.g. via `/models`), and when launching an agent with this model. Must be an object of scalar values. |

### Values are JSON-parsed

`--config` values are parsed as JSON when possible, so numbers, booleans, arrays, and objects work without extra shell quoting. Plain strings are kept as strings.

```bash
# Boolean
topsailai models update GPT-4o --config enabled=true

# Array
topsailai models update GPT-4o --config tags='["prod","vision"]'

# Object
topsailai models update GPT-4o --config metadata='{"temperature":0.7}'
```

### Security note

Never pass literal secrets such as `api_key`, `organization`, or `project`. The CLI rejects them. Always use the `*_env` variants so secrets are read from your shell environment at runtime.

```bash
# Correct
topsailai models add GPT-4o --config api_key_env=OPENAI_API_KEY

# Wrong - will be rejected
topsailai models add GPT-4o --config api_key=sk-...
```

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
  --config base_url=https://api.openai.com/v1 \
  --config api_key_env=OPENAI_API_KEY \
  --config description="OpenAI GPT-4o"
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
- `provider`, `protocol`, and `model` are required.
- `protocol` must be `openai-compatible`.
- Literal secret fields (`api_key`, `organization`, `project`) are rejected.
- Credential references must use `api_key_env`, `organization_env`, or `project_env`.
- Unknown fields are rejected.

## Output

Pretty-printed JSON is used by default. Pass `--json` to emit compact JSON suitable for piping to other tools.

## Files

- `{TOPSAILAI_HOME}/.models.jsonl` — model registry.
- `{TOPSAILAI_HOME}/.model_selection.json` — workspace and project model selections.
