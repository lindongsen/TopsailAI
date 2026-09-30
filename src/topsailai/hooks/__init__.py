"""Public foundational contracts for the standalone unified hooks framework."""

from topsailai.hooks.configuration import HookLimits, HookSettings
from topsailai.hooks.contracts import (
    Binding,
    DeliveryReceipt,
    DispatchReport,
    EventDefinition,
    HookContext,
    HookEvent,
    HookOutcome,
    HookStatus,
    JsonValue,
    RegistrationHandle,
    RegistrationResult,
    RegistrySnapshot,
)
from topsailai.hooks.registry import HookRegistry
from topsailai.hooks.validation import ValidationError, freeze_json, validate_payload

__all__ = [
    "Binding",
    "DeliveryReceipt",
    "DispatchReport",
    "EventDefinition",
    "HookContext",
    "HookEvent",
    "HookLimits",
    "HookOutcome",
    "HookRegistry",
    "HookSettings",
    "HookStatus",
    "JsonValue",
    "RegistrationHandle",
    "RegistrationResult",
    "RegistrySnapshot",
    "ValidationError",
    "freeze_json",
    "validate_payload",
]
