"""Explicit configuration records for the standalone hooks framework."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class HookLimits:
    """Define finite resource limits consumed by later runtime units."""

    workers: int = 4
    queue_items: int = 256
    queue_bytes: int = 4_194_304
    event_bytes: int = 65_536
    bindings_per_event: int = 32
    handler_timeout_ms: int = 1_000
    dispatch_timeout_ms: int = 1_000
    shutdown_timeout_ms: int = 1_000

    def validate(self) -> tuple[str, ...]:
        """Return configuration errors without mutating process state."""
        errors: list[str] = []
        for item in fields(self):
            value = getattr(self, item.name)
            if type(value) is not int or value <= 0:
                errors.append(f"limits.{item.name} must be a positive integer")
        return tuple(errors)


@dataclass(frozen=True, slots=True)
class HookSettings:
    """Configure one standalone hook runtime without reading environment state."""

    enabled: bool = True
    schema_version: int = 1
    limits: HookLimits = HookLimits()

    def validate(self) -> tuple[str, ...]:
        """Return all settings errors."""
        errors: list[str] = []
        if type(self.enabled) is not bool:
            errors.append("enabled must be a boolean")
        if type(self.schema_version) is not int or self.schema_version != 1:
            errors.append("schema_version must be 1")
        if not isinstance(self.limits, HookLimits):
            errors.append("limits must be HookLimits")
        else:
            errors.extend(self.limits.validate())
        return tuple(errors)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "HookSettings":
        """Decode a strict mapping into settings or raise a descriptive ValueError."""
        if type(value) is not dict:
            raise ValueError("hook settings must be an exact dictionary")
        _require_string_keys(value, "hook settings")
        allowed = {"enabled", "schema_version", "limits"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown hook settings fields: {', '.join(sorted(unknown))}")
        raw_limits = value.get("limits", {})
        if type(raw_limits) is not dict:
            raise ValueError("limits must be an exact dictionary")
        _require_string_keys(raw_limits, "hook limits")
        limit_names = {item.name for item in fields(HookLimits)}
        unknown_limits = set(raw_limits) - limit_names
        if unknown_limits:
            raise ValueError(f"unknown hook limit fields: {', '.join(sorted(unknown_limits))}")
        settings = cls(
            enabled=value.get("enabled", True),
            schema_version=value.get("schema_version", 1),
            limits=HookLimits(**raw_limits),
        )
        errors = settings.validate()
        if errors:
            raise ValueError("; ".join(errors))
        return settings


def _require_string_keys(value: dict[Any, Any], field_name: str) -> None:
    """Reject non-string configuration keys before set sorting or formatting."""
    if any(type(key) is not str for key in value):
        raise ValueError(f"{field_name} keys must be strings")
