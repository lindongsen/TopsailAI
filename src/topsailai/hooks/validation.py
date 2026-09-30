"""Bounded validation helpers for unified hook contracts."""

from __future__ import annotations

import re
from typing import Any, Mapping

from topsailai.hooks.contracts import (
    Binding,
    EventDefinition,
    JsonValue,
    ValidationError,
    _FrozenJsonArray,
    _FrozenJsonObject,
    _is_frozen_json_object,
    _snapshot_json,
)

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_HANDLER_PATTERN = re.compile(
    r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$"
)
_SCHEMA_TYPES = frozenset({"null", "boolean", "integer", "number", "string", "array", "object"})
_SCHEMA_KEYS_BY_TYPE = {
    "null": frozenset({"type"}),
    "boolean": frozenset({"type"}),
    "integer": frozenset({"type"}),
    "number": frozenset({"type"}),
    "string": frozenset({"type"}),
    "array": frozenset({"type", "items", "max_items"}),
    "object": frozenset({"type", "required", "properties"}),
}


def freeze_json(
    value: Any,
    *,
    max_bytes: int = 65_536,
    max_depth: int = 16,
    max_items: int = 1_024,
    max_string_length: int = 32_768,
) -> JsonValue:
    """Return a detached mutable JSON copy after strict bounded validation."""
    return _snapshot_json(
        value,
        immutable=False,
        max_bytes=max_bytes,
        max_depth=max_depth,
        max_items=max_items,
        max_string_length=max_string_length,
    )


def validate_event_definition(definition: Any) -> tuple[str, ...]:
    """Return all validation errors for an event definition."""
    if type(definition) is not EventDefinition:
        return ("definition must be EventDefinition",)
    errors: list[str] = []
    if type(definition.name) is not str or not _NAME_PATTERN.fullmatch(definition.name):
        errors.append("event name must be a lowercase dot-separated namespace")
    if type(definition.major_version) is not int or definition.major_version <= 0:
        errors.append("event major_version must be a positive integer")
    if type(definition.payload_limit_bytes) is not int or definition.payload_limit_bytes <= 0:
        errors.append("payload_limit_bytes must be a positive integer")
    errors.extend(_validate_schema(definition.payload_schema, "payload_schema"))
    return tuple(errors)


def validate_binding(binding: Any) -> tuple[str, ...]:
    """Return all validation errors for a binding without unsafe operations."""
    if type(binding) is not Binding:
        return ("binding must be Binding",)
    errors: list[str] = []
    binding_id_valid = type(binding.binding_id) is str and bool(
        _ID_PATTERN.fullmatch(binding.binding_id)
    )
    if not binding_id_valid:
        errors.append("binding_id has an invalid format")
    if type(binding.event_name) is not str or not _NAME_PATTERN.fullmatch(binding.event_name):
        errors.append("binding event_name has an invalid format")
    if type(binding.event_version) is not int or binding.event_version <= 0:
        errors.append("binding event_version must be a positive integer")
    if type(binding.handler_ref) is not str or not _HANDLER_PATTERN.fullmatch(binding.handler_ref):
        errors.append("handler_ref must use module:callable format")
    if type(binding.priority) is not int:
        errors.append("priority must be an integer")
    if type(binding.timeout_ms) is not int or binding.timeout_ms <= 0:
        errors.append("timeout_ms must be a positive integer")
    if type(binding.max_concurrency) is not int or binding.max_concurrency <= 0:
        errors.append("max_concurrency must be a positive integer")
    if type(binding.enabled) is not bool:
        errors.append("enabled must be a boolean")

    after_errors = _validate_string_tuple(binding.after, "after")
    success_errors = _validate_string_tuple(binding.requires_success, "requires_success")
    errors.extend(after_errors)
    errors.extend(success_errors)
    if binding_id_valid and not after_errors and binding.binding_id in binding.after:
        errors.append("binding cannot depend on itself")
    if binding_id_valid and not success_errors and binding.binding_id in binding.requires_success:
        errors.append("binding cannot depend on itself")
    if binding.allowed_payload_fields is not None:
        errors.extend(_validate_string_tuple(binding.allowed_payload_fields, "allowed_payload_fields"))
    return tuple(errors)


def validate_payload(definition: EventDefinition, payload: Any) -> JsonValue:
    """Validate raw JSON or an exact framework snapshot and return mutable JSON."""
    errors = validate_event_definition(definition)
    if errors:
        raise ValidationError("; ".join(errors))
    detached = _snapshot_json(
        payload,
        immutable=False,
        allow_frozen=True,
        max_bytes=definition.payload_limit_bytes,
    )
    _validate_value_against_schema(detached, definition.payload_schema, "payload")
    return detached


def _validate_string_tuple(value: Any, field_name: str) -> list[str]:
    """Validate an exact tuple containing unique non-empty identifiers."""
    if type(value) is not tuple:
        return [f"{field_name} must be a tuple"]
    errors: list[str] = []
    seen: set[str] = set()
    for item in value:
        if type(item) is not str or not _ID_PATTERN.fullmatch(item):
            errors.append(f"{field_name} contains an invalid identifier")
            continue
        if item in seen:
            errors.append(f"{field_name} contains duplicate identifiers")
        seen.add(item)
    return errors


def _is_schema_mapping(value: Any) -> bool:
    """Return whether a value is a framework-owned immutable schema object."""
    return _is_frozen_json_object(value)


def _validate_schema(schema: Any, path: str) -> list[str]:
    """Validate the intentionally small declarative payload schema subset."""
    if not _is_schema_mapping(schema):
        return [f"{path} must be an immutable schema object"]
    errors: list[str] = []
    schema_type = schema.get("type", "object" if not schema else None)
    if type(schema_type) is not str or schema_type not in _SCHEMA_TYPES:
        return [f"{path}.type is unsupported"]

    unknown = set(schema) - _SCHEMA_KEYS_BY_TYPE[schema_type]
    if unknown:
        errors.append(
            f"{path} has keys incompatible with type {schema_type}: {', '.join(sorted(unknown))}"
        )
    if schema_type == "object":
        has_properties = "properties" in schema
        properties = schema["properties"] if has_properties else {}
        has_required = "required" in schema
        required = schema["required"] if has_required else ()
        properties_valid = not has_properties or _is_schema_mapping(properties)
        if not properties_valid:
            errors.append(f"{path}.properties must be an object")
        elif has_properties:
            for key, child in properties.items():
                if type(key) is not str:
                    errors.append(f"{path}.properties keys must be strings")
                else:
                    errors.extend(_validate_schema(child, f"{path}.properties.{key}"))

        required_valid = not has_required or type(required) is _FrozenJsonArray
        if not required_valid:
            errors.append(f"{path}.required must be an array")
        elif any(type(item) is not str for item in required):
            required_valid = False
            errors.append(f"{path}.required must contain strings")
        elif len(set(required)) != len(required):
            required_valid = False
            errors.append(f"{path}.required must not contain duplicates")

        if properties_valid and required_valid and not set(required).issubset(properties):
            errors.append(f"{path}.required references unknown properties")
    elif schema_type == "array":
        if "items" not in schema:
            errors.append(f"{path}.items is required for arrays")
        else:
            errors.extend(_validate_schema(schema["items"], f"{path}.items"))
        if "max_items" in schema:
            max_items = schema["max_items"]
            if type(max_items) is not int or max_items < 0:
                errors.append(f"{path}.max_items must be a non-negative integer")
    return errors


def _validate_value_against_schema(value: JsonValue, schema: Mapping[str, Any], path: str) -> None:
    """Validate a detached JSON value against a previously validated schema."""
    expected = schema.get("type", "object" if not schema else None)
    type_matches = {
        "null": value is None,
        "boolean": type(value) is bool,
        "integer": type(value) is int,
        "number": type(value) in (int, float),
        "string": type(value) is str,
        "array": type(value) is list,
        "object": type(value) is dict,
    }
    if not type_matches[expected]:
        raise ValidationError(f"{path} must be {expected}")
    if expected == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", ())
        missing = [key for key in required if key not in value]
        if missing:
            raise ValidationError(f"{path} is missing required fields: {', '.join(missing)}")
        unknown = set(value) - set(properties)
        if unknown:
            raise ValidationError(f"{path} has unknown fields: {', '.join(sorted(unknown))}")
        for key, item in value.items():
            _validate_value_against_schema(item, properties[key], f"{path}.{key}")
    elif expected == "array":
        max_items = schema.get("max_items")
        if max_items is not None and len(value) > max_items:
            raise ValidationError(f"{path} exceeds maximum array length")
        for index, item in enumerate(value):
            _validate_value_against_schema(item, schema["items"], f"{path}[{index}]")
