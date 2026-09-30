"""Tests for hook contracts, validation and explicit configuration."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from topsailai.hooks import (
    EventDefinition,
    HookEvent,
    HookLimits,
    HookOutcome,
    HookSettings,
    HookStatus,
    ValidationError,
    freeze_json,
    validate_payload,
)


def test_freeze_json_detaches_nested_data_and_preserves_empty_values() -> None:
    """Detached values must not share mutable containers with their publisher."""
    source = {"items": [None, False, 0, "", [], {}]}
    frozen = freeze_json(source)
    source["items"].append("later")
    assert frozen == {"items": [None, False, 0, "", [], {}]}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), ("tuple",), {1: "bad"}])
def test_freeze_json_rejects_non_json_values(value: object) -> None:
    """The boundary must reject values that require permissive serializers."""
    with pytest.raises(ValidationError):
        freeze_json(value)


def test_freeze_json_normalizes_cycles_encoding_and_integer_errors() -> None:
    """Cycle and encoding failures must use the public validation error."""
    cyclic: list[object] = []
    cyclic.append(cyclic)
    with pytest.raises(ValidationError, match="cyclic"):
        freeze_json(cyclic)
    with pytest.raises(ValidationError, match="encoded size"):
        freeze_json("12345", max_bytes=3)
    with pytest.raises(ValidationError, match="encoded safely"):
        freeze_json("\ud800")
    with pytest.raises(ValidationError, match="encoded safely"):
        freeze_json(10**5000)


def test_event_definition_schema_is_bounded_deeply_immutable_and_detached() -> None:
    """Schema aliases must not mutate an accepted definition."""
    child = {"type": "string"}
    schema = {"type": "object", "required": ["owner"], "properties": {"owner": child}}
    definition = EventDefinition("conversation.started", 1, schema)
    child["type"] = "integer"
    schema["required"].append("later")
    assert definition.payload_schema["required"] == ("owner",)
    assert definition.payload_schema["properties"]["owner"]["type"] == "string"
    with pytest.raises(TypeError):
        definition.payload_schema["properties"]["owner"]["type"] = "number"


def test_event_definition_rejects_cycles_depth_custom_containers_and_bad_keywords() -> None:
    """Schema construction and validation must fail closed at bounded boundaries."""
    cyclic: dict[str, object] = {"type": "object"}
    cyclic["properties"] = {"self": cyclic}
    with pytest.raises(ValidationError, match="cyclic"):
        EventDefinition("conversation.started", 1, cyclic)

    nested: dict[str, object] = {"type": "string"}
    for _ in range(18):
        nested = {"type": "array", "items": nested}
    with pytest.raises(ValidationError, match="depth"):
        EventDefinition("conversation.started", 1, nested)

    with pytest.raises(ValidationError, match="exact dictionary"):
        EventDefinition("conversation.started", 1, {"type": "object"}.keys())

    incompatible = EventDefinition(
        "conversation.started", 1, {"type": "object", "properties": {}, "items": {}}
    )
    with pytest.raises(ValidationError, match="incompatible"):
        validate_payload(incompatible, {})


def test_hook_event_and_outcome_take_deeply_immutable_snapshots() -> None:
    """Published payloads and outcomes must not retain mutable caller aliases."""
    payload = {"items": ["first"]}
    event = HookEvent("e", "conversation.started", 1, "o", "s", "op", None, 1, "t", "l", "p", payload)
    payload["items"].append("later")
    assert event.payload["items"] == ("first",)
    with pytest.raises(TypeError):
        event.payload["new"] = True

    value = {"items": [1]}
    outcome = HookOutcome("d", "b", HookStatus.SUCCESS, value=value)
    value["items"].append(2)
    assert outcome.value["items"] == (1,)
    with pytest.raises(FrozenInstanceError):
        outcome.value = None


def test_validate_payload_applies_required_allowed_and_array_rules() -> None:
    """The supported schema subset must reject missing and unknown fields."""
    definition = EventDefinition(
        "conversation.started",
        1,
        {
            "type": "object",
            "required": ["owner", "tags"],
            "properties": {
                "owner": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}, "max_items": 2},
            },
        },
    )
    assert validate_payload(definition, {"owner": "a", "tags": ["x"]}) == {
        "owner": "a",
        "tags": ["x"],
    }
    with pytest.raises(ValidationError, match="missing required"):
        validate_payload(definition, {"owner": "a"})
    with pytest.raises(ValidationError, match="unknown fields"):
        validate_payload(definition, {"owner": "a", "tags": [], "extra": True})
    with pytest.raises(ValidationError, match="maximum array"):
        validate_payload(definition, {"owner": "a", "tags": ["x", "y", "z"]})


def test_frozen_snapshots_compose_with_validation_and_reconstruction() -> None:
    """Framework snapshots must remain valid inputs without admitting arbitrary containers."""
    from dataclasses import replace

    definition = EventDefinition(
        "conversation.started",
        1,
        {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "integer"}}}},
    )
    event = HookEvent(
        "e", "conversation.started", 1, "o", "s", "op", None, 1, "t", "l", "p", {"items": [1]}
    )
    assert validate_payload(definition, event.payload) == {"items": [1]}
    assert replace(event, sequence=2).payload == event.payload
    assert replace(definition, payload_limit_bytes=1_024).payload_schema == definition.payload_schema
    assert HookOutcome("d2", "b", HookStatus.SUCCESS, value=HookOutcome("d1", "b", HookStatus.SUCCESS, value={"items": [1]}).value).value["items"] == (1,)

    class CustomDict(dict):
        """Represent an untrusted custom mapping."""

    with pytest.raises(ValidationError, match="exact built-in"):
        validate_payload(definition, CustomDict(items=[1]))


def test_proxy_wrapped_custom_containers_are_rejected_without_method_calls() -> None:
    """A built-in proxy must not confer framework snapshot provenance."""
    from collections.abc import Iterator, Mapping
    from types import MappingProxyType

    calls: list[str] = []

    class CustomDict(dict):
        """Record any attempted access to an untrusted dictionary subclass."""

        def __len__(self) -> int:
            calls.append("dict_len")
            return super().__len__()

        def items(self):
            calls.append("dict_items")
            return super().items()

    class CustomMapping(Mapping[str, object]):
        """Record any attempted access to an untrusted mapping implementation."""

        def __getitem__(self, key: str) -> object:
            calls.append("mapping_getitem")
            return {"items": [1]}[key]

        def __iter__(self) -> Iterator[str]:
            calls.append("mapping_iter")
            return iter(("items",))

        def __len__(self) -> int:
            calls.append("mapping_len")
            return 1

    definition = EventDefinition(
        "conversation.started",
        1,
        {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "integer"}}}},
    )
    wrapped_dict = MappingProxyType(CustomDict(items=[1]))
    wrapped_mapping = MappingProxyType(CustomMapping())

    for wrapped in (wrapped_dict, wrapped_mapping):
        with pytest.raises(ValidationError, match="framework snapshot"):
            validate_payload(definition, wrapped)
        with pytest.raises(ValidationError, match="framework snapshot"):
            HookOutcome("d", "b", HookStatus.SUCCESS, value=wrapped)
        with pytest.raises(ValidationError, match="framework snapshot"):
            EventDefinition("conversation.started", 1, wrapped)
    assert calls == []


def test_schema_resource_limits_and_invalid_max_items_are_rejected() -> None:
    """Schema snapshots must enforce direct node, string, byte and array-limit boundaries."""
    with pytest.raises(ValidationError, match="item count"):
        EventDefinition(
            "conversation.started",
            1,
            {"type": "object", "properties": {str(i): {} for i in range(1_025)}},
        )
    with pytest.raises(ValidationError, match="string exceeds"):
        EventDefinition("conversation.started", 1, {"type": "x" * 32_769})
    with pytest.raises(ValidationError, match="encoded size"):
        EventDefinition("conversation.started", 1, {"type": "界" * 22_000})

    for invalid in (None, True, "2", -1):
        definition = EventDefinition(
            "conversation.started",
            1,
            {"type": "array", "items": {"type": "integer"}, "max_items": invalid},
        )
        with pytest.raises(ValidationError, match="non-negative integer"):
            validate_payload(definition, [])


def test_settings_decode_strict_mapping_without_environment_reads() -> None:
    """Settings reject unknown, invalid, and non-string-key configuration."""
    settings = HookSettings.from_mapping(
        {"enabled": False, "limits": {"workers": 2, "bindings_per_event": 8}}
    )
    assert settings.enabled is False
    assert settings.limits.workers == 2
    assert settings.limits.queue_items == HookLimits().queue_items
    with pytest.raises(ValueError, match="unknown hook settings"):
        HookSettings.from_mapping({"unexpected": True})
    with pytest.raises(ValueError, match="positive integer"):
        HookSettings.from_mapping({"limits": {"workers": 0}})
    with pytest.raises(ValueError, match="keys must be strings"):
        HookSettings.from_mapping({1: True})
    with pytest.raises(ValueError, match="keys must be strings"):
        HookSettings.from_mapping({"limits": {1: 2}})
