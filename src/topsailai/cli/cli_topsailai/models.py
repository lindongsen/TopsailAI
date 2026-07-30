"""Model registry, selection persistence, and launch environment helpers.

Author: DawsonLin
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from cli_topsailai.paths import get_topsailai_home

_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SUPPORTED_PROTOCOLS = frozenset({"openai-compatible"})
_PROTECTED_ENVIRONMENT = frozenset(
    {
        "TOPSAILAI_HOME",
        "TOPSAILAI_PWD",
        "TOPSAILAI_PROJECT_WORKSPACE",
        "TOPSAILAI_PROJECT_FOLDER",
        "TOPSAILAI_SESSION_ID",
        "TOPSAILAI_CONTEXT_USER_MESSAGE",
        "PWD",
    }
)
_SECRET_ENV_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
_SECRET_FIELD_NAMES = frozenset(
    {"api_key", "token", "secret", "password", "organization", "project"}
)
_ALLOWED_FIELDS = frozenset(
    {
        "id",
        "name",
        "provider",
        "protocol",
        "model",
        "base_url",
        "api_key_env",
        "organization_env",
        "project_env",
        "environment",
        "description",
        "tags",
        "enabled",
        "metadata",
    }
)


class ModelConfigurationError(ValueError):
    """Report an invalid model registry, selection, or environment mapping."""


@dataclass(frozen=True)
class ModelConfig:
    """Represent one validated model configuration from ``.models.jsonl``."""

    id: str
    name: str
    provider: str
    protocol: str
    model: str
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    organization_env: Optional[str] = None
    project_env: Optional[str] = None
    environment: Mapping[str, str] = field(default_factory=dict)
    description: str = ""
    tags: tuple[str, ...] = ()
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelRegistry:
    """Contain valid model entries and non-fatal line validation errors."""

    models: tuple[ModelConfig, ...]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class EffectiveModel:
    """Describe the effective selected model and the scope that selected it."""

    model: Optional[ModelConfig]
    source: str
    model_id: Optional[str] = None


def get_models_path() -> str:
    """Return the model registry path under ``TOPSAILAI_HOME``."""
    return os.path.join(get_topsailai_home(), ".models.jsonl")


def get_model_selection_path() -> str:
    """Return the model selection state path under ``TOPSAILAI_HOME``."""
    return os.path.join(get_topsailai_home(), ".model_selection.json")


def normalize_project_workspace(project_workspace: str) -> str:
    """Return a normalized absolute project workspace path."""
    if not isinstance(project_workspace, str) or not project_workspace.strip():
        raise ModelConfigurationError("Project workspace must be a non-empty path")
    return os.path.normcase(
        os.path.abspath(os.path.expanduser(project_workspace.strip()))
    )


def _require_non_empty_string(record: Mapping[str, Any], field_name: str) -> str:
    """Read one required non-empty string field from a registry record."""
    value = record.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ModelConfigurationError(
            f"field {field_name!r} must be a non-empty string"
        )
    return value.strip()


def _optional_string(record: Mapping[str, Any], field_name: str) -> Optional[str]:
    """Read one optional non-empty string field from a registry record."""
    value = record.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ModelConfigurationError(
            f"field {field_name!r} must be a non-empty string when present"
        )
    return value.strip()


def _validate_environment_name(name: str, field_name: str) -> str:
    """Validate one source or target environment variable name."""
    if not _ENV_NAME_PATTERN.fullmatch(name):
        raise ModelConfigurationError(
            f"field {field_name!r} contains invalid environment name {name!r}"
        )
    return name


def _normalize_environment(value: Any) -> dict[str, str]:
    """Validate and stringify non-sensitive additional environment values."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ModelConfigurationError("field 'environment' must be an object")

    environment: dict[str, str] = {}
    for key, raw_value in value.items():
        if not isinstance(key, str) or not _ENV_NAME_PATTERN.fullmatch(key):
            raise ModelConfigurationError(
                f"field 'environment' contains invalid name {key!r}"
            )
        if key in _PROTECTED_ENVIRONMENT:
            raise ModelConfigurationError(
                f"field 'environment' cannot override protected variable {key!r}"
            )
        if key.upper().endswith(_SECRET_ENV_SUFFIXES):
            raise ModelConfigurationError(
                f"field 'environment' cannot store secret variable {key!r}"
            )
        if not isinstance(raw_value, (str, int, float, bool)):
            raise ModelConfigurationError(
                f"environment value for {key!r} must be a scalar"
            )
        if isinstance(raw_value, bool):
            environment[key] = "true" if raw_value else "false"
        else:
            environment[key] = str(raw_value)
    return environment


def _normalize_tags(value: Any) -> tuple[str, ...]:
    """Validate optional model display tags."""
    if value is None:
        return ()
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ModelConfigurationError("field 'tags' must be a list of strings")
    return tuple(item.strip() for item in value)


def validate_model_record(record: Any) -> ModelConfig:
    """Validate and normalize one parsed JSON model registry object."""
    if not isinstance(record, dict):
        raise ModelConfigurationError("record must be a JSON object")

    secret_fields = _SECRET_FIELD_NAMES.intersection(record)
    if secret_fields:
        names = ", ".join(sorted(secret_fields))
        raise ModelConfigurationError(f"raw secret fields are prohibited: {names}")

    unknown_fields = set(record).difference(_ALLOWED_FIELDS)
    if unknown_fields:
        names = ", ".join(sorted(str(name) for name in unknown_fields))
        raise ModelConfigurationError(f"unknown fields: {names}")

    model_id = _require_non_empty_string(record, "id")
    if not _MODEL_ID_PATTERN.fullmatch(model_id):
        raise ModelConfigurationError(
            "field 'id' may contain only letters, digits, '.', '_', '-', or ':'"
        )

    enabled = record.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ModelConfigurationError("field 'enabled' must be a boolean")

    description = record.get("description", "")
    if not isinstance(description, str):
        raise ModelConfigurationError("field 'description' must be a string")

    metadata = record.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ModelConfigurationError("field 'metadata' must be an object")

    source_fields: dict[str, Optional[str]] = {}
    for field_name in ("api_key_env", "organization_env", "project_env"):
        value = _optional_string(record, field_name)
        source_fields[field_name] = (
            _validate_environment_name(value, field_name) if value else None
        )

    return ModelConfig(
        id=model_id,
        name=_require_non_empty_string(record, "name"),
        provider=_require_non_empty_string(record, "provider"),
        protocol=_require_non_empty_string(record, "protocol"),
        model=_require_non_empty_string(record, "model"),
        base_url=_optional_string(record, "base_url"),
        api_key_env=source_fields["api_key_env"],
        organization_env=source_fields["organization_env"],
        project_env=source_fields["project_env"],
        environment=_normalize_environment(record.get("environment")),
        description=description.strip(),
        tags=_normalize_tags(record.get("tags")),
        enabled=enabled,
        metadata=dict(metadata),
    )


def load_models(path: Optional[str] = None) -> ModelRegistry:
    """Load valid model configurations while retaining line-specific errors."""
    registry_path = path or get_models_path()
    if not os.path.exists(registry_path):
        return ModelRegistry((), (f"Model registry not found: {registry_path}",))

    models: list[ModelConfig] = []
    errors: list[str] = []
    model_ids: set[str] = set()
    try:
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            for line_number, raw_line in enumerate(registry_file, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    model = validate_model_record(json.loads(line))
                    if model.id in model_ids:
                        raise ModelConfigurationError(
                            f"duplicate model id {model.id!r}"
                        )
                except (json.JSONDecodeError, ModelConfigurationError) as error:
                    errors.append(f"Line {line_number}: {error}")
                    continue
                model_ids.add(model.id)
                models.append(model)
    except OSError as error:
        return ModelRegistry((), (f"Cannot read model registry: {error}",))
    return ModelRegistry(tuple(models), tuple(errors))


def find_model(models: Sequence[ModelConfig], model_id: str) -> Optional[ModelConfig]:
    """Find a model by its stable unique ID."""
    return next((model for model in models if model.id == model_id), None)


def format_model_summary(model: ModelConfig) -> str:
    """Return a concise model summary that never contains secret values."""
    status = "enabled" if model.enabled else "disabled"
    endpoint = f" | {model.base_url}" if model.base_url else ""
    return (
        f"{model.name} [{model.id}] | {model.provider} | "
        f"{model.protocol} | {model.model}{endpoint} | {status}"
    )


def load_selection(path: Optional[str] = None) -> dict[str, Any]:
    """Load normalized model selection state or return an empty state."""
    selection_path = path or get_model_selection_path()
    if not os.path.exists(selection_path):
        return {"workspace": None, "projects": {}}
    try:
        with open(selection_path, "r", encoding="utf-8") as selection_file:
            raw_state = json.load(selection_file)
    except (OSError, json.JSONDecodeError):
        return {"workspace": None, "projects": {}}
    if not isinstance(raw_state, dict):
        return {"workspace": None, "projects": {}}

    workspace = raw_state.get("workspace")
    if not isinstance(workspace, str) or not workspace:
        workspace = None
    raw_projects = raw_state.get("projects", {})
    projects = {
        key: value
        for key, value in raw_projects.items()
        if isinstance(key, str)
        and key
        and isinstance(value, str)
        and value
    } if isinstance(raw_projects, dict) else {}
    return {"workspace": workspace, "projects": projects}


def save_selection(state: Mapping[str, Any], path: Optional[str] = None) -> None:
    """Persist model selection state atomically."""
    selection_path = path or get_model_selection_path()
    directory = os.path.dirname(selection_path)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        dir=directory,
        prefix=".model_selection.json.tmp",
        suffix=".json",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as selection_file:
            json.dump(state, selection_file, ensure_ascii=False, indent=2)
            selection_file.write("\n")
        os.replace(temporary_path, selection_path)
    except Exception:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def set_selected_model(
    model_id: str,
    project_workspace: Optional[str] = None,
    path: Optional[str] = None,
) -> None:
    """Persist a workspace default or project-specific model ID."""
    if not _MODEL_ID_PATTERN.fullmatch(model_id):
        raise ModelConfigurationError("Cannot persist an invalid model id")
    state = load_selection(path)
    if project_workspace is None:
        state["workspace"] = model_id
    else:
        project_key = normalize_project_workspace(project_workspace)
        state["projects"][project_key] = model_id
    save_selection(state, path)


def clear_selected_model(
    project_workspace: Optional[str] = None,
    path: Optional[str] = None,
) -> bool:
    """Clear a workspace default or project-specific model selection."""
    state = load_selection(path)
    if project_workspace is None:
        changed = state.get("workspace") is not None
        state["workspace"] = None
    else:
        project_key = normalize_project_workspace(project_workspace)
        changed = state["projects"].pop(project_key, None) is not None
    if changed:
        save_selection(state, path)
    return changed


def resolve_effective_model(
    models: Sequence[ModelConfig],
    project_workspace: Optional[str] = None,
    selection_path: Optional[str] = None,
) -> EffectiveModel:
    """Resolve project override then workspace default without silent fallback."""
    state = load_selection(selection_path)
    source = "workspace"
    model_id = state.get("workspace")
    if project_workspace is not None:
        project_key = normalize_project_workspace(project_workspace)
        project_model_id = state["projects"].get(project_key)
        if project_model_id:
            source = "project"
            model_id = project_model_id
    if not model_id:
        return EffectiveModel(None, "inherited", None)

    model = find_model(models, model_id)
    if model is None:
        raise ModelConfigurationError(
            f"Selected {source} model {model_id!r} is missing from .models.jsonl"
        )
    if not model.enabled:
        raise ModelConfigurationError(
            f"Selected {source} model {model_id!r} is disabled"
        )
    if model.protocol not in _SUPPORTED_PROTOCOLS:
        raise ModelConfigurationError(
            f"Selected model protocol {model.protocol!r} is not supported"
        )
    return EffectiveModel(model, source, model_id)


def build_model_environment(
    model: ModelConfig,
    inherited_environment: Mapping[str, str],
) -> dict[str, str]:
    """Build an OpenAI-compatible child environment without mutating input."""
    if not model.enabled:
        raise ModelConfigurationError(f"Model {model.id!r} is disabled")
    if model.protocol not in _SUPPORTED_PROTOCOLS:
        raise ModelConfigurationError(
            f"Model protocol {model.protocol!r} is not supported"
        )

    environment = dict(inherited_environment)
    environment.update(model.environment)
    environment["OPENAI_MODEL"] = model.model
    if model.base_url:
        environment["OPENAI_BASE_URL"] = model.base_url
        environment["OPENAI_API_BASE"] = model.base_url

    source_mappings = (
        (model.api_key_env, "OPENAI_API_KEY"),
        (model.organization_env, "OPENAI_ORG_ID"),
        (model.project_env, "OPENAI_PROJECT_ID"),
    )
    for source_name, target_name in source_mappings:
        if not source_name:
            continue
        source_value = inherited_environment.get(source_name)
        if source_value is None:
            raise ModelConfigurationError(
                f"Required source environment variable {source_name!r} is not set"
            )
        environment[target_name] = source_value
    return environment
