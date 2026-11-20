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
topsailai models list [--project PATH] [--json]
topsailai models add <name> --config KEY=VALUE ... [--json]
topsailai models get <name> [--json]
topsailai models update <name> --config KEY=VALUE ... [--json]
topsailai models delete <name> [--yes] [--json]
topsailai models set <name|id|number> [--project PATH] [--json]
topsailai models current [--project PATH] [--json]
topsailai models clear [--project PATH] [--json]
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

### Setting environment variables

Use `--config environment.KEY=VALUE` to set an individual environment variable into the model's `environment` mapping. Existing entries are preserved (merge semantics).

```bash
# Set one environment variable
topsailai models update GPT-4o --config environment.TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT=300

# Set multiple environment variables
topsailai models update GPT-4o \
  --config environment.TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT=300 \
  --config environment.TOPSAILAI_LOG_LEVEL=debug

# Remove an environment variable (empty value)
topsailai models update GPT-4o --config environment.TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT=
```

This also works with `add`:

```bash
topsailai models add GPT-4o \
  --config provider=openai \
  --config protocol=openai-compatible \
  --config model=gpt-4o \
  --config environment.TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT=300
```

Values are stringified. The `environment` field is applied to the process environment when the model is selected (e.g. via `/models`) and when launching an agent with this model.

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

Print all model entries with row numbers and pretty-printed JSON. The entry that
an agent launch would actually use is marked with a `*` in the marker column, and
one `Current model (<scope>)` line names it.

```bash
topsailai models list
```

```text
Available model configurations:
   1. { ... }
 * 2. { ... }
[INFO] Current model (workspace): Qwen [qwen] | local | openai-compatible | qwen-7b | enabled
```

The marker column is used instead of colouring a value because each entry is
printed as multi-line JSON, where colouring would corrupt the document. When no
selection is persisted, the command prints a `No <scope> model selection` line
instead of a marker.

Use `--json` for compact machine-readable output. Each record then carries a
`selected` boolean, so a machine consumer gets the same fact without parsing the
marker column.

```bash
topsailai models list --json
```

Pass `--project PATH` to mark the entry effective for that project instead of the
workspace default.

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

### set

Persist the model that subsequent agent launches and resumes use.

```bash
topsailai models set "GPT-4o"
topsailai models set 2
topsailai models set gpt-4o --project /path/to/project
```

The selector is resolved in this order: exact display name, then exact model id,
then 1-based row number as printed by `list`. Identity beats position, so a model
literally named `1` still resolves by name.

Without `--project` the workspace default is written, which is the model a launch
uses when the project has no override. With `--project PATH` a project override is
written instead, and it takes precedence over the workspace default for that
project.

A disabled model or a model whose `protocol` is not `openai-compatible` is
rejected with exit code `1` and nothing is persisted. The interactive `/models`
command applies the same check, so a model one path refuses can never be persisted
by the other.

The command does not modify the current shell environment, because it exits
immediately; the persisted selection is what later launches read.

### current

Show the effective model and the scope that selected it.

```bash
topsailai models current
topsailai models current --project /path/to/project
```

The reported source is `project` when a project override applies, `workspace` when
the workspace default applies, and `inherited` when nothing is persisted, in which
case agent launches inherit the current environment.

Exit code is `1` when the persisted selection cannot be used, for example because
the selected model was deleted from the registry or has been disabled. With
`--json` the failure is reported as a parseable document with
`"status": "error"` and `"error_code": "selection_invalid"`.

### clear

Remove the selection for one scope.

```bash
topsailai models clear
topsailai models clear --project /path/to/project
```

Without `--project` the workspace default is removed; with `--project PATH` only
that project's override is removed, leaving the workspace default untouched. The
command reports whether anything was actually cleared, and `--json` exposes the
same fact as a `cleared` boolean.

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

## Model Selection

Create `{TOPSAILAI_HOME}/.models.jsonl` with one model configuration object per line. Use `/models` in workspace scope to set the default model or in project scope to set an override for the active project. `/models current` shows the effective model and `/models clear` removes the selection for the current scope.

The same selection can be managed from the shell with `topsailai models set`, `topsailai models current` and `topsailai models clear`, which write and read the same `.model_selection.json` record. `set` is the command to use when a script or a non-interactive session must choose the model that later agent launches use.

Selections are stored in `.model_selection.json` with project overrides taking precedence over the workspace default. When a model is selected through the interactive `/models` command, any `environment` entries defined in its registry record are applied to the current process environment (each variable is printed as an `[INFO] Set environment variable: name=value` message). The selected OpenAI-compatible configuration is otherwise applied only to subsequently launched or resumed agent processes.

Registry entries must reference credentials by environment-variable name through `api_key_env`, `organization_env`, or `project_env`. Do not store credentials directly in `.models.jsonl`.
