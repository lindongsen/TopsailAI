"""Immutable contracts for the standalone unified hooks framework."""

from __future__ import annotations

import json
import math
from collections.abc import Iterator, Mapping as MappingABC, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, TypeAlias, Union, overload

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
FrozenJsonValue: TypeAlias = Union[JsonScalar, "_FrozenJsonArray", "_FrozenJsonObject"]
_SNAPSHOT_TOKEN = object()


class ValidationError(ValueError):
    """Report a contract validation failure at a safe boundary."""


class _FrozenJsonObject(MappingABC[str, FrozenJsonValue]):
    """Store a framework-owned immutable JSON object over an exact dictionary."""

    __slots__ = ("__values",)

    def __init__(self, values: dict[str, FrozenJsonValue], token: object) -> None:
        """Build an object only through the framework snapshot boundary."""
        if token is not _SNAPSHOT_TOKEN or type(values) is not dict:
            raise TypeError("frozen JSON objects are framework-owned")
        self.__values = values

    def __getitem__(self, key: str) -> FrozenJsonValue:
        """Return one frozen member."""
        return self.__values[key]

    def __iter__(self) -> Iterator[str]:
        """Iterate member names in insertion order."""
        return iter(self.__values)

    def __len__(self) -> int:
        """Return the number of members."""
        return len(self.__values)


class _FrozenJsonArray(Sequence[FrozenJsonValue]):
    """Store a framework-owned immutable JSON array over an exact tuple."""

    __slots__ = ("__values",)

    def __init__(self, values: tuple[FrozenJsonValue, ...], token: object) -> None:
        """Build an array only through the framework snapshot boundary."""
        if token is not _SNAPSHOT_TOKEN or type(values) is not tuple:
            raise TypeError("frozen JSON arrays are framework-owned")
        self.__values = values

    @overload
    def __getitem__(self, index: int) -> FrozenJsonValue: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[FrozenJsonValue, ...]: ...

    def __getitem__(self, index: int | slice) -> FrozenJsonValue | tuple[FrozenJsonValue, ...]:
        """Return one member or an immutable slice."""
        return self.__values[index]

    def __len__(self) -> int:
        """Return the number of members."""
        return len(self.__values)

    def __eq__(self, other: object) -> bool:
        """Compare arrays by immutable sequence content."""
        if type(other) is _FrozenJsonArray:
            return self.__values == other.__values
        if type(other) is tuple:
            return self.__values == other
        return False



def _snapshot_json(
    value: Any,
    *,
    immutable: bool,
    allow_frozen: bool = False,
    max_bytes: int = 65_536,
    max_depth: int = 16,
    max_items: int = 1_024,
    max_string_length: int = 32_768,
) -> JsonValue | FrozenJsonValue:
    """Validate, bound, and detach raw JSON or a framework-owned snapshot."""
    limits = (max_bytes, max_depth, max_items, max_string_length)
    if any(type(limit) is not int or limit < 0 for limit in limits):
        raise ValidationError("JSON limits must be non-negative integers")
    item_count = 0

    def snapshot(current: Any, depth: int, ancestors: set[int]) -> Any:
        nonlocal item_count
        if depth > max_depth:
            raise ValidationError("JSON value exceeds maximum depth")
        if current is None or type(current) in (bool, int, str):
            if type(current) is str and len(current) > max_string_length:
                raise ValidationError("JSON string exceeds maximum length")
            return current
        if type(current) is float:
            if not math.isfinite(current):
                raise ValidationError("JSON numbers must be finite")
            return current
        is_raw_array = type(current) is list
        is_raw_object = type(current) is dict
        is_frozen_array = allow_frozen and type(current) is _FrozenJsonArray
        is_frozen_object = allow_frozen and type(current) is _FrozenJsonObject
        if not (is_raw_array or is_raw_object or is_frozen_array or is_frozen_object):
            raise ValidationError("value must use exact built-in JSON types or a framework snapshot")

        identity = id(current)
        if identity in ancestors:
            raise ValidationError("cyclic JSON value is not allowed")
        ancestors.add(identity)
        try:
            item_count += len(current)
            if item_count > max_items:
                raise ValidationError("JSON value exceeds maximum item count")
            if is_raw_array or is_frozen_array:
                values = [snapshot(item, depth + 1, ancestors) for item in current]
                return _FrozenJsonArray(tuple(values), _SNAPSHOT_TOKEN) if immutable else values

            values: dict[str, Any] = {}
            for key, item in current.items():
                if type(key) is not str:
                    raise ValidationError("JSON object keys must be exact strings")
                if len(key) > max_string_length:
                    raise ValidationError("JSON object key exceeds maximum length")
                values[key] = snapshot(item, depth + 1, ancestors)
            return _FrozenJsonObject(values, _SNAPSHOT_TOKEN) if immutable else values
        finally:
            ancestors.remove(identity)

    plain = snapshot(value, 0, set())
    encoded_value = _thaw_frozen_json(plain)
    try:
        encoded = json.dumps(
            encoded_value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (UnicodeEncodeError, ValueError, OverflowError) as exc:
        raise ValidationError("JSON value cannot be encoded safely") from exc
    if len(encoded) > max_bytes:
        raise ValidationError("JSON value exceeds maximum encoded size")
    return plain


def _thaw_frozen_json(value: Any) -> JsonValue:
    """Convert only framework-owned frozen containers to mutable JSON."""
    if type(value) is _FrozenJsonObject:
        return {key: _thaw_frozen_json(item) for key, item in value.items()}
    if type(value) is _FrozenJsonArray:
        return [_thaw_frozen_json(item) for item in value]
    return value


def _is_frozen_json_object(value: Any) -> bool:
    """Return whether a value is the framework-owned object snapshot type."""
    return type(value) is _FrozenJsonObject


def _freeze_schema(value: Any) -> Mapping[str, Any]:
    """Return a bounded, deeply immutable schema snapshot."""
    if type(value) is not dict and type(value) is not _FrozenJsonObject:
        raise ValidationError("payload_schema must be an exact dictionary or framework snapshot")
    frozen = _snapshot_json(value, immutable=True, allow_frozen=True)
    if type(frozen) is not _FrozenJsonObject:
        raise ValidationError("payload_schema must be an object")
    return frozen


class HookStatus(str, Enum):
    """Terminal status for one hook delivery."""

    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    INVALID_OUTPUT = "invalid_output"
    WORKER_LOST = "worker_lost"
    CANCELLED = "cancelled"
    SKIPPED_DEPENDENCY = "skipped_dependency"
    SKIPPED_DISABLED = "skipped_disabled"
    SKIPPED_DEADLINE = "skipped_deadline"
    REJECTED_CAPACITY = "rejected_capacity"


@dataclass(frozen=True, slots=True)
class EventDefinition:
    """Declare one exact event contract and its bounded payload schema."""

    name: str
    major_version: int
    payload_schema: Mapping[str, Any] = field(default_factory=dict)
    payload_limit_bytes: int = 65_536

    def __post_init__(self) -> None:
        """Validate and detach the complete schema tree from caller state."""
        object.__setattr__(self, "payload_schema", _freeze_schema(self.payload_schema))


@dataclass(frozen=True, slots=True)
class HookEvent:
    """Represent one deeply immutable event occurrence at the dispatch boundary."""

    event_id: str
    name: str
    major_version: int
    owner_id: str
    scope_id: str
    operation_id: str
    parent_operation_id: str | None
    sequence: int
    timestamp: str
    layer: str
    purpose: str
    payload: FrozenJsonValue

    def __post_init__(self) -> None:
        """Detach raw JSON or preserve a detached framework snapshot."""
        object.__setattr__(
            self,
            "payload",
            _snapshot_json(self.payload, immutable=True, allow_frozen=True),
        )


@dataclass(frozen=True, slots=True)
class Binding:
    """Bind an importable handler to one exact event contract."""

    binding_id: str
    event_name: str
    event_version: int
    handler_ref: str
    priority: int = 100
    after: tuple[str, ...] = ()
    requires_success: tuple[str, ...] = ()
    timeout_ms: int = 1_000
    max_concurrency: int = 1
    enabled: bool = True
    allowed_payload_fields: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class HookContext:
    """Provide a detached event snapshot and delivery metadata to a handler."""

    event: HookEvent
    delivery_id: str
    binding_id: str
    registry_generation: int
    remaining_budget_ms: int
    origin: str = "host"
    depth: int = 0


@dataclass(frozen=True, slots=True)
class HookOutcome:
    """Describe the terminal result of one binding delivery."""

    delivery_id: str
    binding_id: str
    status: HookStatus
    value: FrozenJsonValue = None
    duration_ms: int = 0
    error_category: str | None = None
    started: bool = False

    def __post_init__(self) -> None:
        """Detach raw JSON or preserve a detached framework snapshot."""
        object.__setattr__(
            self,
            "value",
            _snapshot_json(self.value, immutable=True, allow_frozen=True),
        )


@dataclass(frozen=True, slots=True)
class DispatchReport:
    """Collect bounded outcomes for one event in stable plan order."""

    event_id: str
    generation: int
    outcomes: tuple[HookOutcome, ...] = ()
    elapsed_ms: int = 0
    deadline_exhausted: bool = False
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """Report whether an event was admitted without implying execution success."""

    admitted: bool
    event_id: str
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RegistrationHandle:
    """Identify one exact registry-owned scope-local registration."""

    scope_id: str
    binding_id: str
    generation: int
    registry_id: str = ""


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    """Return registration validation details without raising into business flow."""

    accepted: bool
    generation: int
    handle: RegistrationHandle | None = None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    """Freeze one registry generation and its deterministic binding plan."""

    generation: int
    definition: EventDefinition | None
    bindings: tuple[Binding, ...]
