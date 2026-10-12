"""Immutable declarations and catalog for application Hook points."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Mapping

from topsailai.hooks.configured_contracts import is_valid_hook_name
from topsailai.hooks.contracts import EventDefinition
from topsailai.hooks.validation import validate_event_definition


@dataclass(frozen=True, slots=True)
class HookPointDeclaration:
    """Declare one stable application publication checkpoint."""

    name: str
    definition: EventDefinition
    phase: Literal["before", "success", "error"]
    mode: Literal["sync", "async"]
    owner: str
    scope: Literal["application"] = "application"
    failure_policy: Literal["report", "block"] = "report"
    security_critical: bool = False
    allow_post_success_block: bool = False
    sensitive_fields: tuple[str, ...] = ()
    latency_budget_ms: int = 1_000
    ordering: str = "declaration"
    argument_fields: tuple[str, ...] = ()
    result_fields: tuple[str, ...] = ()
    error_fields: tuple[Literal["type", "message"], ...] = ()

    def __post_init__(self) -> None:
        """Validate and detach one declaration without external I/O."""
        field_sets = (
            self.sensitive_fields,
            self.argument_fields,
            self.result_fields,
            self.error_fields,
        )
        invalid = (
            not is_valid_hook_name(self.name)
            or type(self.definition) is not EventDefinition
            or bool(validate_event_definition(self.definition))
            or self.phase not in ("before", "success", "error")
            or self.mode not in ("sync", "async")
            or type(self.owner) is not str
            or not self.owner
            or self.scope != "application"
            or self.failure_policy not in ("report", "block")
            or type(self.security_critical) is not bool
            or type(self.allow_post_success_block) is not bool
            or type(self.latency_budget_ms) is not int
            or not 1 <= self.latency_budget_ms <= 600_000
            or type(self.ordering) is not str
            or not self.ordering
            or any(type(values) not in (list, tuple) for values in field_sets)
            or any(type(item) is not str or not item for values in field_sets for item in values)
        )
        if invalid:
            raise ValueError("invalid Hook-point declaration")
        if self.name.startswith("hook__"):
            name_phase = self.name.split("__")[2]
            expected_phase = {"before": "before", "after": "success", "error": "error"}[name_phase]
            if self.definition.name != self.name or self.phase != expected_phase:
                raise ValueError("invalid Hook-point declaration")
        if self.failure_policy == "block" and not self.security_critical:
            raise ValueError("invalid Hook-point declaration")
        if self.allow_post_success_block and self.phase != "success":
            raise ValueError("invalid Hook-point declaration")
        if self.phase == "success" and self.failure_policy == "block" and not self.allow_post_success_block:
            raise ValueError("invalid Hook-point declaration")
        if any(len(set(values)) != len(values) for values in field_sets):
            raise ValueError("invalid Hook-point declaration")
        if set(self.argument_fields) & set(self.sensitive_fields):
            raise ValueError("invalid Hook-point declaration")
        if self.phase != "success" and self.result_fields:
            raise ValueError("invalid Hook-point declaration")
        if self.phase != "error" and self.error_fields:
            raise ValueError("invalid Hook-point declaration")
        if set(self.error_fields) - {"type", "message"}:
            raise ValueError("invalid Hook-point declaration")
        definition = EventDefinition(
            self.definition.name,
            self.definition.major_version,
            self.definition.payload_schema,
            self.definition.payload_limit_bytes,
        )
        object.__setattr__(self, "definition", definition)
        object.__setattr__(self, "sensitive_fields", tuple(self.sensitive_fields))
        object.__setattr__(self, "argument_fields", tuple(self.argument_fields))
        object.__setattr__(self, "result_fields", tuple(self.result_fields))
        object.__setattr__(self, "error_fields", tuple(self.error_fields))


@dataclass(frozen=True, slots=True)
class HookPointCatalog:
    """Own the complete immutable set of application Hook-point declarations."""

    declarations: tuple[HookPointDeclaration, ...]
    _by_name: Mapping[str, HookPointDeclaration] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Reject duplicate stable names and event identities."""
        if type(self.declarations) is not tuple or any(type(item) is not HookPointDeclaration for item in self.declarations):
            raise ValueError("invalid Hook-point catalog")
        names = tuple(item.name for item in self.declarations)
        events = tuple((item.definition.name, item.definition.major_version) for item in self.declarations)
        if len(set(names)) != len(names) or len(set(events)) != len(events):
            raise ValueError("invalid Hook-point catalog")
        owned = tuple(
            HookPointDeclaration(
                item.name, item.definition, item.phase, item.mode, item.owner,
                item.scope, item.failure_policy, item.security_critical,
                item.allow_post_success_block, item.sensitive_fields,
                item.latency_budget_ms, item.ordering, item.argument_fields,
                item.result_fields, item.error_fields,
            )
            for item in self.declarations
        )
        object.__setattr__(self, "declarations", owned)
        object.__setattr__(self, "_by_name", MappingProxyType({item.name: item for item in owned}))

    def get(self, name: str) -> HookPointDeclaration | None:
        """Return one declaration without accepting arbitrary names."""
        return self._by_name.get(name) if type(name) is str else None

    def require(self, name: str) -> HookPointDeclaration:
        """Return one known declaration or reject the caller-created name."""
        declaration = self.get(name)
        if declaration is None:
            raise KeyError(name)
        return declaration
