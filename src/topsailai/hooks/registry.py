"""Thread-safe registry and deterministic dependency planning for hooks."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Any

from topsailai.hooks.contracts import (
    Binding,
    EventDefinition,
    RegistrationHandle,
    RegistrationResult,
    RegistrySnapshot,
)
from topsailai.hooks.validation import validate_binding, validate_event_definition


@dataclass(frozen=True, slots=True)
class _RegisteredBinding:
    """Associate a binding with its stable registration identity."""

    binding: Binding
    registration_generation: int


@dataclass(frozen=True, slots=True)
class _RegistryState:
    """Hold one immutable registry generation."""

    generation: int
    definitions: dict[tuple[str, int], EventDefinition]
    bindings: dict[tuple[str, str], _RegisteredBinding]


class HookRegistry:
    """Atomically register scope-local bindings and produce stable snapshots."""

    def __init__(self, *, bindings_per_event: int = 32) -> None:
        """Create an empty registry with a finite per-event binding cap."""
        if type(bindings_per_event) is not int or bindings_per_event <= 0:
            raise ValueError("bindings_per_event must be a positive integer")
        self._bindings_per_event = bindings_per_event
        self._registry_id = uuid.uuid4().hex
        self._state = _RegistryState(0, {}, {})
        self._lock = threading.Lock()

    @property
    def generation(self) -> int:
        """Return the currently active immutable generation number."""
        with self._lock:
            return self._state.generation

    def register(
        self,
        definition: Any,
        binding: Any,
        scope_id: Any,
    ) -> RegistrationResult:
        """Atomically activate a validated definition and binding."""
        errors = list(validate_event_definition(definition))
        errors.extend(validate_binding(binding))
        if type(scope_id) is not str or not scope_id:
            errors.append("scope_id must be a non-empty string")
        if not errors and (binding.event_name, binding.event_version) != (
            definition.name,
            definition.major_version,
        ):
            errors.append("binding event does not match its definition")
        if errors:
            return RegistrationResult(False, self.generation, errors=tuple(errors))

        with self._lock:
            state = self._state
            key = (scope_id, binding.binding_id)
            if key in state.bindings:
                return RegistrationResult(
                    False, state.generation, errors=("binding_id already exists in this scope",)
                )
            definition_key = (definition.name, definition.major_version)
            existing_definition = state.definitions.get(definition_key)
            if existing_definition is not None and existing_definition != definition:
                return RegistrationResult(
                    False,
                    state.generation,
                    errors=("event definition conflicts with the active definition",),
                )
            matching_count = sum(
                registered.binding.event_name == binding.event_name
                and registered.binding.event_version == binding.event_version
                and registered_scope == scope_id
                for (registered_scope, _), registered in state.bindings.items()
            )
            if matching_count >= self._bindings_per_event:
                return RegistrationResult(
                    False, state.generation, errors=("bindings_per_event limit exceeded",)
                )

            generation = state.generation + 1
            definitions = dict(state.definitions)
            definitions[definition_key] = definition
            bindings = dict(state.bindings)
            bindings[key] = _RegisteredBinding(binding, generation)
            plan_errors = _validate_and_plan(
                _event_bindings(bindings, scope_id, definition.name, definition.major_version)
            )[1]
            if plan_errors:
                return RegistrationResult(False, state.generation, errors=plan_errors)

            self._state = _RegistryState(generation, definitions, bindings)
            handle = RegistrationHandle(
                scope_id, binding.binding_id, generation, self._registry_id
            )
            return RegistrationResult(True, generation, handle=handle)

    def unregister(self, handle: Any) -> RegistrationResult:
        """Atomically remove the exact registration when its graph remains valid."""
        if type(handle) is not RegistrationHandle:
            return RegistrationResult(
                False, self.generation, errors=("handle must be RegistrationHandle",)
            )
        if type(handle.scope_id) is not str or type(handle.binding_id) is not str:
            return RegistrationResult(False, self.generation, errors=("handle is invalid",))
        if type(handle.generation) is not int or handle.generation <= 0:
            return RegistrationResult(False, self.generation, errors=("handle is invalid",))
        if type(handle.registry_id) is not str or handle.registry_id != self._registry_id:
            return RegistrationResult(
                False, self.generation, errors=("registration handle belongs to another registry",)
            )

        with self._lock:
            state = self._state
            key = (handle.scope_id, handle.binding_id)
            registered = state.bindings.get(key)
            if registered is None:
                return RegistrationResult(
                    False, state.generation, errors=("registration does not exist",)
                )
            if registered.registration_generation != handle.generation:
                return RegistrationResult(
                    False, state.generation, errors=("registration handle is stale",)
                )

            bindings = dict(state.bindings)
            del bindings[key]
            event_binding = registered.binding
            plan_errors = _validate_and_plan(
                _event_bindings(
                    bindings,
                    handle.scope_id,
                    event_binding.event_name,
                    event_binding.event_version,
                )
            )[1]
            if plan_errors:
                return RegistrationResult(False, state.generation, errors=plan_errors)

            generation = state.generation + 1
            self._state = _RegistryState(generation, dict(state.definitions), bindings)
            return RegistrationResult(True, generation)

    def snapshot(
        self,
        scope_id: str,
        event_name: str,
        event_version: int,
    ) -> RegistrySnapshot:
        """Capture a stable plan for one exact scope and event contract."""
        with self._lock:
            state = self._state
        candidates = _event_bindings(state.bindings, scope_id, event_name, event_version)
        ordered, errors = _validate_and_plan(candidates)
        if errors:
            raise RuntimeError("active registry contains an invalid dependency graph")
        return RegistrySnapshot(
            generation=state.generation,
            definition=state.definitions.get((event_name, event_version)),
            bindings=ordered,
        )


def _event_bindings(
    bindings: dict[tuple[str, str], _RegisteredBinding],
    scope_id: str,
    event_name: str,
    event_version: int,
) -> tuple[Binding, ...]:
    """Select exact scope-local bindings without parent inheritance."""
    return tuple(
        registered.binding
        for (registered_scope, _), registered in bindings.items()
        if registered_scope == scope_id
        and registered.binding.event_name == event_name
        and registered.binding.event_version == event_version
    )


def _validate_and_plan(bindings: tuple[Binding, ...]) -> tuple[tuple[Binding, ...], tuple[str, ...]]:
    """Validate dependencies and return a stable topological plan."""
    by_id = {binding.binding_id: binding for binding in bindings}
    known = set(by_id)
    errors: list[str] = []
    dependencies: dict[str, set[str]] = {}
    for binding in bindings:
        required = set(binding.after) | set(binding.requires_success)
        unknown = required - known
        if unknown:
            errors.append(
                f"binding {binding.binding_id} has unknown dependencies: {', '.join(sorted(unknown))}"
            )
        dependencies[binding.binding_id] = required
    if errors:
        return (), tuple(errors)

    remaining = {key: set(value) for key, value in dependencies.items()}
    ordered: list[Binding] = []
    while remaining:
        ready = [by_id[key] for key, required in remaining.items() if not required]
        if not ready:
            return (), ("binding dependency graph contains a cycle",)
        binding = min(ready, key=lambda item: (item.priority, item.binding_id))
        ordered.append(binding)
        del remaining[binding.binding_id]
        for required in remaining.values():
            required.discard(binding.binding_id)
    return tuple(ordered), ()
