"""Non-interactive ``topsailai models`` subcommand implementation.

Author: DawsonLin
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict, List, Optional

from cli_topsailai.colors import Colors
from cli_topsailai.models import (
    ModelConfigurationError,
    ModelConfig,
    clear_selected_model,
    find_model,
    format_model_summary,
    get_model_selection_path,
    get_models_path,
    load_models,
    normalize_project_workspace,
    resolve_effective_model,
    set_selected_model,
    validate_model_record,
    validate_selectable_model,
)


_CONFIG_HELP = """Set a model configuration key/value pair (repeatable).

Common keys:
  name                  Unique display name for the model (required for add).
  model                 Actual model ID sent to the API (required).
  provider              Provider name, e.g. openai, azure, local (required).
  protocol              Must be "openai-compatible" (required).
  base_url              OpenAI-compatible endpoint URL.
  api_key_env           Name of the environment variable that holds the API key.
  organization_env      Name of the environment variable for the organization ID.
  project_env           Name of the environment variable for the project ID.
  description           Short human-readable description.
  tags                  List of tags, e.g. ["prod","vision"].
  enabled               true or false.
  metadata              Arbitrary JSON object for extra settings.

Security note:
  Never pass api_key, organization, or project directly. Always use the
  *_env variants so secrets are read from environment variables.

Values are parsed as JSON when possible, so numbers, booleans, arrays, and
objects work without extra shell quoting. Plain strings are kept as strings.
"""

_ADD_EPILOG = """Example:
  topsailai models add GPT-4o \\
    --config provider=openai \\
    --config protocol=openai-compatible \\
    --config model=gpt-4o \\
    --config base_url=https://api.openai.com/v1 \\
    --config api_key_env=OPENAI_API_KEY \\
    --config description="OpenAI GPT-4o"
"""

_UPDATE_EPILOG = """Example:
  topsailai models update GPT-4o \\
    --config base_url=https://api.example.test/v1 \\
    --config enabled=true
"""


def _slugify_id(name: str) -> str:
    """Derive a stable model id from a display name.

    The result contains only lowercase letters, digits, '_', '-', and ':' so
    it satisfies the model id validation pattern.
    """
    normalized = name.strip().lower()
    characters: list[str] = []
    for char in normalized:
        if char.isalnum() or char in ("_", "-", ":"):
            characters.append(char)
        elif characters and characters[-1] != "-":
            characters.append("-")
    slug = "".join(characters).strip("-")
    return slug or "model"


def _print_error(message: str) -> None:
    print(f"{Colors.RED}[ERROR] {message}{Colors.RESET}")


def _print_warn(message: str, to_stderr: bool = False) -> None:
    """Print a warning, optionally to stderr to keep stdout parseable.

    ``--json`` promises one parseable document on stdout, so a diagnostic must
    not be interleaved with it. Text mode keeps writing to stdout so existing
    human-facing output is unchanged.
    """
    stream = sys.stderr if to_stderr else sys.stdout
    print(f"{Colors.YELLOW}[WARN] {message}{Colors.RESET}", file=stream)


def _print_info(message: str) -> None:
    print(f"{Colors.GREEN}[INFO] {message}{Colors.RESET}")


def _load_registry(path: Optional[str] = None) -> tuple[List[ModelConfig], List[str]]:
    """Load the model registry and return (models, errors)."""
    registry = load_models(path or get_models_path())
    return list(registry.models), list(registry.errors)


def _find_model_by_name(models: List[ModelConfig], name: str) -> Optional[ModelConfig]:
    """Find a model by its unique display name."""
    for model in models:
        if model.name == name:
            return model
    return None


def resolve_model_argument(
    models: List[ModelConfig],
    argument: str,
) -> Optional[ModelConfig]:
    """Resolve a model selector to one registry entry.

    Identity beats position: an exact display name wins, then an exact model
    id, and only then a 1-based row number. A model literally named ``"1"``
    therefore still resolves by name instead of by position, so a selector can
    never silently address a different entry than the one it spells.
    """
    selector = argument.strip()
    if not selector:
        return None
    by_name = _find_model_by_name(models, selector)
    if by_name is not None:
        return by_name
    by_id = find_model(models, selector)
    if by_id is not None:
        return by_id
    if selector.isdigit():
        index = int(selector)
        if 1 <= index <= len(models):
            return models[index - 1]
    return None


def _selection_scope(project_workspace: Optional[str]) -> str:
    """Return the human-readable scope name for a selection target."""
    return "project" if project_workspace else "workspace"


def _selected_model_id(
    models: List[ModelConfig],
    project_workspace: Optional[str],
    to_stderr: bool = False,
) -> Optional[str]:
    """Return the effective model id for one scope, or ``None``.

    An unusable selection is reported as a warning and treated as "nothing
    selected", so a listing still prints every entry instead of failing.
    """
    try:
        effective = resolve_effective_model(
            models,
            project_workspace=project_workspace,
        )
    except ModelConfigurationError as error:
        _print_warn(str(error), to_stderr=to_stderr)
        return None
    return effective.model_id


def _parse_config_pairs(config_pairs: List[str]) -> Dict[str, Any]:
    """Parse ``--config KEY=VALUE`` pairs into a dictionary.

    Values are parsed as JSON when possible so numbers, booleans, and arrays
    can be supplied without extra quoting. Plain strings are preserved.
    """
    record: Dict[str, Any] = {}
    for pair in config_pairs:
        if "=" not in pair:
            raise ModelConfigurationError(
                f"Config must be KEY=VALUE, got: {pair!r}"
            )
        key, value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise ModelConfigurationError("Empty key in KEY=VALUE config")
        record[key] = _parse_config_value(value)
    return record


def _parse_config_value(value: str) -> Any:
    """Parse a config value, falling back to a plain string."""
    stripped = value.strip()
    if not stripped:
        return ""
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return stripped


def _expand_environment_entries(record: Dict[str, Any]) -> Dict[str, Any]:
    """Expand ``environment.KEY`` config entries into the environment mapping.

    An empty value removes the key from the mapping. Existing environment
    entries are merged so individual variables can be set or removed without
    losing the rest of the model's environment configuration.
    """
    environment = record.get("environment")
    if not isinstance(environment, dict):
        environment = {}
    keys_to_remove = [key for key in record if key.startswith("environment.")]
    for key in keys_to_remove:
        env_name = key[len("environment."):]
        if not env_name:
            raise ModelConfigurationError(
                "environment key name is required after 'environment.'"
            )
        value = record.pop(key)
        if value == "":
            environment.pop(env_name, None)
        else:
            environment[env_name] = str(value)
    if environment:
        record["environment"] = environment
    return record


def _model_to_record(model: ModelConfig) -> Dict[str, Any]:
    """Convert a ModelConfig back to a plain dictionary."""
    record: Dict[str, Any] = {
        "id": model.id,
        "name": model.name,
        "provider": model.provider,
        "protocol": model.protocol,
        "model": model.model,
    }
    if model.base_url is not None:
        record["base_url"] = model.base_url
    if model.api_key_env is not None:
        record["api_key_env"] = model.api_key_env
    if model.organization_env is not None:
        record["organization_env"] = model.organization_env
    if model.project_env is not None:
        record["project_env"] = model.project_env
    if model.environment:
        record["environment"] = dict(model.environment)
    if model.description:
        record["description"] = model.description
    if model.tags:
        record["tags"] = list(model.tags)
    if not model.enabled:
        record["enabled"] = False
    if model.metadata:
        record["metadata"] = dict(model.metadata)
    return record


def _write_models_atomic(
    models: List[ModelConfig],
    path: Optional[str] = None,
) -> None:
    """Persist the model registry atomically."""
    registry_path = path or get_models_path()
    directory = os.path.dirname(registry_path)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        dir=directory,
        prefix=".models.jsonl.tmp",
        suffix=".jsonl",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as registry_file:
            for model in models:
                record = _model_to_record(model)
                registry_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(temporary_path, registry_path)
    except Exception:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def _print_json(data: Any, compact: bool) -> None:
    """Print data as JSON, either pretty or compact."""
    if compact:
        print(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def _confirm_deletion(name: str) -> bool:
    """Prompt the user for confirmation before deleting a model."""
    if not sys.stdin.isatty():
        return False
    print(
        f"{Colors.YELLOW}[WARN] Delete model '{name}'? [y/N]{Colors.RESET}"
    )
    try:
        answer = input().strip().lower()
    except EOFError:
        answer = "n"
    return answer in ("y", "yes")


def _build_add_record(name: str, config_pairs: List[str]) -> Dict[str, Any]:
    """Build and validate a raw record for ``add``."""
    if not isinstance(name, str) or not name.strip():
        raise ModelConfigurationError("model name is required")
    record = _parse_config_pairs(config_pairs)
    record["name"] = name.strip()
    if not record.get("id"):
        record["id"] = _slugify_id(name)
    return _expand_environment_entries(record)


def _build_update_record(
    existing: ModelConfig,
    config_pairs: List[str],
) -> Dict[str, Any]:
    """Merge config pairs into an existing record."""
    record = _model_to_record(existing)
    updates = _parse_config_pairs(config_pairs)
    for key, value in updates.items():
        if key == "tags" and isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]
        if key == "environment" and isinstance(value, str):
            env: Dict[str, str] = {}
            for item in value.split(","):
                if "=" not in item:
                    raise ModelConfigurationError(
                        f"environment value must be key=value pairs: {item!r}"
                    )
                k, v = item.split("=", 1)
                env[k.strip()] = v.strip()
            value = env
        record[key] = value
    return _expand_environment_entries(record)


def handle_models_list(args: Any) -> int:
    """Handle ``topsailai models list``.

    The effective model for the requested scope is marked, so a caller can see
    which entry an agent launch would actually use without running a second
    command. Text output uses a ``*`` marker column because each entry is
    printed as multi-line JSON, where colouring a value would corrupt the
    document; ``--json`` adds a ``selected`` boolean to each record instead.
    """
    compact = getattr(args, "json", False)
    models, errors = _load_registry()
    for error in errors:
        _print_warn(error, to_stderr=compact)

    project_workspace = getattr(args, "project", None)
    selected_model_id = _selected_model_id(
        models,
        project_workspace,
        to_stderr=compact,
    )

    if compact:
        records = []
        for model in models:
            record = _model_to_record(model)
            record["selected"] = model.id == selected_model_id
            records.append(record)
        _print_json(records, compact=True)
        return 0

    if not models:
        _print_warn("No model configurations found.")
        return 0

    print(f"\n{Colors.BOLD}Available model configurations:{Colors.RESET}")
    for index, model in enumerate(models, start=1):
        marker = "*" if model.id == selected_model_id else " "
        print(f" {marker} {index}. ", end="")
        _print_json(_model_to_record(model), compact=False)

    if selected_model_id is None:
        print(
            f"{Colors.YELLOW}[INFO] No {_selection_scope(project_workspace)} "
            f"model selection; agent launches inherit the current environment."
            f"{Colors.RESET}"
        )
        return 0
    selected_model = find_model(models, selected_model_id)
    if selected_model is not None:
        print(
            f"{Colors.GREEN}[INFO] Current model "
            f"({_selection_scope(project_workspace)}): "
            f"{format_model_summary(selected_model)}{Colors.RESET}"
        )
    return 0


def handle_models_add(args: Any) -> int:
    """Handle ``topsailai models add <name> --config KEY=VALUE ...``."""
    compact = getattr(args, "json", False)
    models, errors = _load_registry()
    for error in errors:
        _print_warn(error, to_stderr=compact)
    try:
        raw_record = _build_add_record(args.name, args.config or [])
    except ModelConfigurationError as error:
        _print_error(str(error))
        return 1

    if _find_model_by_name(models, raw_record["name"]):
        _print_error(f"Model with name {raw_record['name']!r} already exists")
        return 1

    try:
        new_model = validate_model_record(raw_record)
    except ModelConfigurationError as error:
        _print_error(str(error))
        return 1

    models.append(new_model)
    try:
        _write_models_atomic(models)
    except (OSError, ModelConfigurationError) as error:
        _print_error(f"Cannot save model registry: {error}")
        return 1

    if compact:
        _print_json({"status": "ok", "action": "add", "model": _model_to_record(new_model)}, compact=True)
    else:
        _print_info(f"Added model: {new_model.name}")
    return 0


def handle_models_update(args: Any) -> int:
    """Handle ``topsailai models update <name> --config KEY=VALUE ...``."""
    compact = getattr(args, "json", False)
    models, errors = _load_registry()
    for error in errors:
        _print_warn(error, to_stderr=compact)

    name = args.name.strip()
    target = _find_model_by_name(models, name)
    if target is None:
        _print_error(f"Model not found: {name!r}")
        return 1

    try:
        merged_record = _build_update_record(target, args.config or [])
    except ModelConfigurationError as error:
        _print_error(str(error))
        return 1

    # Prevent renaming to a name that already belongs to another model.
    new_name = merged_record.get("name", "").strip()
    if new_name and new_name != target.name:
        if _find_model_by_name(models, new_name) is not None:
            _print_error(f"Model with name {new_name!r} already exists")
            return 1

    try:
        updated_model = validate_model_record(merged_record)
    except ModelConfigurationError as error:
        _print_error(str(error))
        return 1

    for index, model in enumerate(models):
        if model.name == name:
            models[index] = updated_model
            break

    try:
        _write_models_atomic(models)
    except (OSError, ModelConfigurationError) as error:
        _print_error(f"Cannot save model registry: {error}")
        return 1

    if compact:
        _print_json({"status": "ok", "action": "update", "model": _model_to_record(updated_model)}, compact=True)
    else:
        _print_info(f"Updated model: {updated_model.name}")
    return 0


def handle_models_delete(args: Any) -> int:
    """Handle ``topsailai models delete <name>``."""
    compact = getattr(args, "json", False)
    models, errors = _load_registry()
    for error in errors:
        _print_warn(error, to_stderr=compact)

    name = args.name.strip()
    target = _find_model_by_name(models, name)
    if target is None:
        _print_error(f"Model not found: {name!r}")
        return 1

    if not args.yes and not _confirm_deletion(target.name):
        print(f"{Colors.DIM}[INFO] Deletion cancelled.{Colors.RESET}")
        return 0

    remaining = [model for model in models if model.name != name]
    try:
        _write_models_atomic(remaining)
    except (OSError, ModelConfigurationError) as error:
        _print_error(f"Cannot save model registry: {error}")
        return 1

    # Clear selection if the deleted model is currently selected.
    try:
        clear_selected_model_for_id(target.id)
    except OSError as error:
        _print_warn(f"Deleted model but could not update selection: {error}")

    if compact:
        _print_json({"status": "ok", "action": "delete", "name": target.name}, compact=True)
    else:
        _print_info(f"Deleted model: {target.name}")
    return 0


def clear_selected_model_for_id(model_id: str) -> bool:
    """Clear the workspace selection when it points to ``model_id``."""
    from cli_topsailai.models import load_selection, save_selection

    selection_path = get_model_selection_path()
    state = load_selection(selection_path)
    changed = False
    if state.get("workspace") == model_id:
        state["workspace"] = None
        changed = True
    projects = state.get("projects", {})
    keys_to_remove = [key for key, value in projects.items() if value == model_id]
    for key in keys_to_remove:
        del projects[key]
        changed = True
    if changed:
        save_selection(state, selection_path)
    return changed


def handle_models_get(args: Any) -> int:
    """Handle ``topsailai models get <name>``."""
    compact = getattr(args, "json", False)
    models, errors = _load_registry()
    for error in errors:
        _print_warn(error, to_stderr=compact)

    name = args.name.strip()
    target = _find_model_by_name(models, name)
    if target is None:
        _print_error(f"Model not found: {name!r}")
        return 1

    _print_json(_model_to_record(target), compact=compact)
    return 0


def handle_models_set(args: Any) -> int:
    """Handle ``topsailai models set <name|id|number> [--project PATH]``.

    The selection is persisted through the same helper the interactive
    ``/models`` command uses, so both paths write one record shape. The current
    process environment is deliberately not modified: this command exits
    immediately, and the persisted selection is what later launches read.
    """
    compact = getattr(args, "json", False)
    models, errors = _load_registry()
    for error in errors:
        _print_warn(error, to_stderr=compact)

    selector = args.name.strip()
    target = resolve_model_argument(models, selector)
    if target is None:
        _print_error(f"Model not found: {selector!r}")
        return 1

    try:
        validate_selectable_model(target)
    except ModelConfigurationError as error:
        _print_error(str(error))
        return 1

    project_workspace = getattr(args, "project", None)
    try:
        set_selected_model(target.id, project_workspace=project_workspace)
    except (OSError, ModelConfigurationError) as error:
        _print_error(f"Cannot save model selection: {error}")
        return 1

    scope_name = _selection_scope(project_workspace)
    if compact:
        _print_json(
            {
                "status": "ok",
                "action": "set",
                "scope": scope_name,
                "project_workspace": (
                    normalize_project_workspace(project_workspace)
                    if project_workspace
                    else None
                ),
                "model": _model_to_record(target),
            },
            compact=True,
        )
    else:
        _print_info(
            f"Selected {scope_name} model: {format_model_summary(target)}"
        )
    return 0


def handle_models_current(args: Any) -> int:
    """Handle ``topsailai models current [--project PATH]``."""
    compact = getattr(args, "json", False)
    models, errors = _load_registry()
    for error in errors:
        _print_warn(error, to_stderr=compact)

    project_workspace = getattr(args, "project", None)
    scope_name = _selection_scope(project_workspace)
    try:
        effective = resolve_effective_model(
            models,
            project_workspace=project_workspace,
        )
    except ModelConfigurationError as error:
        if compact:
            _print_json(
                {
                    "status": "error",
                    "scope": scope_name,
                    "error_code": "selection_invalid",
                    "message": str(error),
                },
                compact=True,
            )
        else:
            _print_error(str(error))
        return 1

    if compact:
        _print_json(
            {
                "status": "ok",
                "scope": scope_name,
                "source": effective.source,
                "model_id": effective.model_id,
                "model": (
                    _model_to_record(effective.model)
                    if effective.model is not None
                    else None
                ),
            },
            compact=True,
        )
        return 0

    if effective.model is None:
        print(
            f"{Colors.YELLOW}[INFO] No persisted model selection; "
            f"agent launches inherit the current environment.{Colors.RESET}"
        )
        return 0
    print(
        f"{Colors.GREEN}[INFO] Effective model ({effective.source}): "
        f"{format_model_summary(effective.model)}{Colors.RESET}"
    )
    return 0


def handle_models_clear(args: Any) -> int:
    """Handle ``topsailai models clear [--project PATH]``."""
    project_workspace = getattr(args, "project", None)
    scope_name = _selection_scope(project_workspace)
    try:
        changed = clear_selected_model(project_workspace)
    except (OSError, ModelConfigurationError) as error:
        _print_error(f"Cannot clear model selection: {error}")
        return 1

    compact = getattr(args, "json", False)
    if compact:
        _print_json(
            {
                "status": "ok",
                "action": "clear",
                "scope": scope_name,
                "cleared": changed,
            },
            compact=True,
        )
        return 0

    if changed:
        _print_info(f"Cleared {scope_name} model selection.")
    else:
        print(
            f"{Colors.YELLOW}[INFO] No {scope_name} model selection was set."
            f"{Colors.RESET}"
        )
    return 0


def _register_models_subcommands(
    subparsers: Any,
    parent_parser: argparse.ArgumentParser,
) -> None:
    """Register the ``models`` subcommands directly under the parent parser."""
    common_defaults = {"parser": parent_parser}

    def _add_json_flag(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--json",
            action="store_true",
            dest="json",
            help="output compact JSON instead of pretty-printed JSON",
        )

    def _add_project_option(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--project",
            dest="project",
            metavar="PATH",
            default=None,
            help=(
                "target the project override for PATH instead of the "
                "workspace default"
            ),
        )

    models_list_parser = subparsers.add_parser(
        "list",
        help="list model registry entries and mark the current model",
    )
    _add_project_option(models_list_parser)
    _add_json_flag(models_list_parser)
    models_list_parser.set_defaults(func=handle_models_list, **common_defaults)

    models_add_parser = subparsers.add_parser(
        "add",
        help="add a model to the registry",
        description="Add a new model configuration to the registry.",
        epilog=_ADD_EPILOG,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    models_add_parser.add_argument(
        "name",
        help="unique display name for the model",
    )
    models_add_parser.add_argument(
        "--config",
        action="append",
        dest="config",
        metavar="KEY=VALUE",
        help=_CONFIG_HELP,
    )
    _add_json_flag(models_add_parser)
    models_add_parser.set_defaults(func=handle_models_add, **common_defaults)

    models_update_parser = subparsers.add_parser(
        "update",
        help="update an existing model entry",
        description="Update an existing model configuration by merging key/value pairs.",
        epilog=_UPDATE_EPILOG,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    models_update_parser.add_argument(
        "name",
        help="display name of the model to update",
    )
    models_update_parser.add_argument(
        "--config",
        action="append",
        dest="config",
        metavar="KEY=VALUE",
        help=_CONFIG_HELP,
    )
    _add_json_flag(models_update_parser)
    models_update_parser.set_defaults(func=handle_models_update, **common_defaults)

    models_get_parser = subparsers.add_parser(
        "get",
        help="show a model entry as JSON",
    )
    models_get_parser.add_argument(
        "name",
        help="display name of the model",
    )
    _add_json_flag(models_get_parser)
    models_get_parser.set_defaults(func=handle_models_get, **common_defaults)

    models_delete_parser = subparsers.add_parser(
        "delete",
        help="delete a model from the registry",
    )
    models_delete_parser.add_argument(
        "name",
        help="display name of the model to delete",
    )
    models_delete_parser.add_argument(
        "--yes",
        action="store_true",
        dest="yes",
        help="skip confirmation prompt",
    )
    _add_json_flag(models_delete_parser)
    models_delete_parser.set_defaults(func=handle_models_delete, **common_defaults)

    models_set_parser = subparsers.add_parser(
        "set",
        help="set the model used by subsequent agent launches",
        description=(
            "Persist the model selection used by subsequent agent launches "
            "and resumes. Without --project the workspace default is written."
        ),
    )
    models_set_parser.add_argument(
        "name",
        help="model display name, model id, or 1-based row number",
    )
    _add_project_option(models_set_parser)
    _add_json_flag(models_set_parser)
    models_set_parser.set_defaults(func=handle_models_set, **common_defaults)

    models_current_parser = subparsers.add_parser(
        "current",
        help="show the effective model selection",
    )
    _add_project_option(models_current_parser)
    _add_json_flag(models_current_parser)
    models_current_parser.set_defaults(
        func=handle_models_current, **common_defaults
    )

    models_clear_parser = subparsers.add_parser(
        "clear",
        help="clear the model selection for one scope",
    )
    _add_project_option(models_clear_parser)
    _add_json_flag(models_clear_parser)
    models_clear_parser.set_defaults(func=handle_models_clear, **common_defaults)


def try_handle_models_subcommand(argv: Optional[List[str]] = None) -> Optional[int]:
    """Handle non-interactive ``topsailai models`` invocations.

    Returns an exit code when the subcommand is recognized, otherwise ``None``.
    """
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) < 1 or argv[0].lower() != "models":
        return None

    parser = argparse.ArgumentParser(
        prog="topsailai models",
        description="Manage the TopsailAI model registry",
    )
    subparsers = parser.add_subparsers(dest="models_command")
    _register_models_subcommands(subparsers, parser)

    try:
        args = parser.parse_args(argv[1:])
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    if args.models_command is None:
        parser.print_help()
        return 1
    if getattr(args, "func", None) is None:
        parser.print_help()
        return 1

    return args.func(args)
