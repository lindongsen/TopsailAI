"""Focused tests for configured Hook names and mapping discovery."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from topsailai.hooks import ConfiguredHookPoint, ConfiguredHooks, EventDefinition

def test_configured_hooks_mapping_is_sorted_and_exactly_selectable() -> None:
    """Mapping keys define canonical hook identity and deterministic order."""
    value = {
        "hooks": {
            "hook_zeta": {"definition": {"name": "event.z", "major_version": 1}},
            "hook_alpha": {"definition": {"name": "event.a", "major_version": 1}},
        }
    }
    configured = ConfiguredHooks.from_mapping(value)
    assert [point.hook_name for point in configured.hook_points] == ["hook_alpha", "hook_zeta"]
    assert configured.get_hook("hook_alpha") is configured.hook_points[0]
    assert configured.get_hook("event.a") is None
    assert configured.get_hook("hook_missing") is None
    assert configured.get_hook("bad-name") is None


def test_configured_hooks_mapping_rejects_nested_name_and_invalid_names() -> None:
    """The mapping key is the sole identity and must use canonical grammar."""
    base = {"definition": {"name": "event.a", "major_version": 1}}
    with pytest.raises(ValueError, match="invalid configured hook name"):
        ConfiguredHooks.from_mapping({"hooks": {"event.a": base}})
    with pytest.raises(ValueError, match="invalid configured hooks mapping"):
        ConfiguredHooks.from_mapping({"hooks": {"hook_a": {**base, "hook_name": "hook_b"}}})


def test_configured_hooks_mapping_rejects_malformed_non_null_script() -> None:
    """Unsupported script payloads must fail closed rather than be silently dropped."""
    value = {
        "hooks": {
            "hook_script": {
                "definition": {"name": "event.script", "major_version": 1},
                "script": {"target": "/tmp/hook"},
            }
        }
    }
    with pytest.raises(ValueError, match="invalid configured hooks mapping"):
        ConfiguredHooks.from_mapping(value)


@pytest.mark.parametrize("hook_name", ["hook_" + "a" * 123])
def test_hook_name_accepts_maximum_length(hook_name: str) -> None:
    """The canonical name grammar accepts exactly the 128-character boundary."""
    point = ConfiguredHookPoint(hook_name, EventDefinition("event.boundary", 1))
    assert point.hook_name == hook_name


def test_hook_name_rejects_invalid_boundaries_and_types() -> None:
    """Case, Unicode, whitespace, newline, and non-string names fail consistently."""
    invalid = (
        "hook_" + "a" * 124,
        "Hook_valid",
        "hook_é",
        "hook_valid ",
        "hook_valid\n",
        None,
        1,
    )
    for hook_name in invalid:
        with pytest.raises(ValueError, match="^invalid configured hook name$"):
            ConfiguredHookPoint(hook_name, EventDefinition("event.invalid", 1))


def test_hook_name_alias_is_read_only_and_legacy_keyword_is_rejected() -> None:
    """The compatibility alias cannot create a second mutable identity."""
    point = ConfiguredHookPoint("hook_alias", EventDefinition("event.alias", 1))
    assert point.hook_point == point.hook_name
    with pytest.raises((AttributeError, FrozenInstanceError, TypeError)):
        point.hook_point = "hook_other"
    with pytest.raises(TypeError):
        ConfiguredHookPoint(hook_point="hook_alias", definition=EventDefinition("event.alias", 1))


def test_mapping_insertion_order_and_nested_values_are_deterministic_and_detached() -> None:
    """Equivalent mappings produce equal ordered snapshots independent of insertion order."""
    first = {
        "hooks": {
            "hook_zeta": {"definition": {"name": "event.z", "major_version": 1}},
            "hook_alpha": {"definition": {"name": "event.a", "major_version": 1}, "module_kwargs": {"nested": [1]}},
        }
    }
    second = {"hooks": dict(reversed(list(first["hooks"].items())))}
    left = ConfiguredHooks.from_mapping(first)
    right = ConfiguredHooks.from_mapping(second)
    assert left == right
    first["hooks"]["hook_alpha"]["module_kwargs"]["nested"][0] = 99
    assert left.get_hook("hook_alpha").module_kwargs["nested"][0] == 1


def test_mapping_rejects_unknown_fields_keys_and_shapes() -> None:
    """Every mapping boundary rejects unknown fields, wrong containers, and key types."""
    base = {"definition": {"name": "event.valid", "major_version": 1}}
    invalid = (
        {"hooks": {"hook_valid": {**base, "unknown": 1}}},
        {"hooks": {"hook_valid": {"definition": {**base["definition"], "unknown": 1}}}},
        {"hooks": {"hook_valid": {"definition": base["definition"], "module_args": "bad"}}},
        {"hooks": {"hook_valid": {"definition": base["definition"], "module_kwargs": []}}},
        {"hooks": {"hook_valid": []}},
        {"hooks": []},
        {"hooks": {1: base}},
    )
    for value in invalid:
        with pytest.raises(ValueError):
            ConfiguredHooks.from_mapping(value)


def test_configured_mapping_decodes_valid_script_and_detaches_nested_input(tmp_path: Path) -> None:
    """A valid script mapping uses authoritative constructors and owns its nested values."""
    script = {
        "target": str(tmp_path / "hook-script"),
        "platform_policy": {"platform": "posix", "allowed_interpreters": [], "native_suffixes": []},
        "options": {"argv": ["before"], "cwd": str(tmp_path), "environment": [["SAFE_NAME", "value"]]},
        "policy": {"entry_timeout_ms": 2000},
        "environment_allowlist": ["SAFE_NAME"],
        "environment_snapshot": [["SAFE_NAME", "snapshot"]],
    }
    value = {"hooks": {"hook_script": {"definition": {"name": "event.script", "major_version": 1}, "script": script}}}
    configured = ConfiguredHooks.from_mapping(value)
    script["options"]["argv"][0] = "changed"
    saved = configured.get_hook("hook_script").script
    assert saved is not None
    assert saved.options.argv == ("before",)
    assert saved.policy.entry_timeout_ms == 2000


def test_mapping_rejects_invalid_script_shapes_and_unknown_fields(tmp_path: Path) -> None:
    """Malformed script containers and nested unknown fields fail closed."""
    base = {"definition": {"name": "event.script", "major_version": 1}}
    cases = (
        {**base, "script": []},
        {**base, "script": {"target": str(tmp_path / "x")}},
        {**base, "script": {"target": str(tmp_path / "x"), "platform_policy": {"platform": "posix", "unknown": 1}}},
        {**base, "script": {"target": str(tmp_path / "x"), "platform_policy": {"platform": "posix"}, "options": {"unknown": 1}}},
    )
    for declaration in cases:
        with pytest.raises(ValueError):
            ConfiguredHooks.from_mapping({"hooks": {"hook_script": declaration}})


def _script_declaration(tmp_path: Path, **overrides: object) -> dict[str, object]:
    """Build a valid script declaration for decoder boundary tests."""
    value: dict[str, object] = {
        "target": str(tmp_path / "hook-script"),
        "platform_policy": {
            "platform": "posix",
            "allowed_interpreters": [],
            "native_suffixes": [],
        },
        "options": {
            "argv": ["before"],
            "cwd": str(tmp_path),
            "environment": [["SAFE_NAME", "value"]],
        },
        "environment_allowlist": ["SAFE_NAME"],
        "environment_snapshot": [["SAFE_NAME", "snapshot"]],
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize(
    ("path", "bad_value"),
    [
        (("options", "argv"), "bad"),
        (("options", "argv"), {"arg": "bad"}),
        (("options", "argv"), None),
        (("options", "environment"), "bad"),
        (("options", "environment"), {"NAME": "value"}),
        (("options", "environment"), None),
        (("platform_policy", "allowed_interpreters"), "bad"),
        (("platform_policy", "allowed_interpreters"), {"/bin/python": True}),
        (("platform_policy", "allowed_interpreters"), None),
        (("platform_policy", "native_suffixes"), "bad"),
        (("platform_policy", "native_suffixes"), {".so": True}),
        (("platform_policy", "native_suffixes"), None),
        (("environment_snapshot",), "bad"),
        (("environment_snapshot",), {"NAME": "value"}),
        (("environment_snapshot",), None),
    ],
)
def test_script_decoder_rejects_non_sequence_fields(
    tmp_path: Path, path: tuple[str, ...], bad_value: object
) -> None:
    """String, mapping, and null sequence values never get character-coerced."""
    script = _script_declaration(tmp_path)
    if len(path) == 1:
        script[path[0]] = bad_value
    else:
        nested = script[path[0]]
        assert isinstance(nested, dict)
        nested[path[1]] = bad_value
    with pytest.raises(ValueError, match="invalid configured hooks mapping"):
        ConfiguredHooks.from_mapping({"hooks": {"hook_script": {"definition": {"name": "event.script", "major_version": 1}, "script": script}}})


@pytest.mark.parametrize("bad_pair", [[], ["NAME"], ["NAME", "value", "extra"], [1, "value"], {"NAME": "value"}])
def test_script_decoder_rejects_malformed_environment_pairs(tmp_path: Path, bad_pair: object) -> None:
    """Every environment pair must be an exact two-string sequence."""
    for field in ("environment", "environment_snapshot"):
        script = _script_declaration(tmp_path)
        if field == "environment":
            options = script["options"]
            assert isinstance(options, dict)
            options[field] = [bad_pair]
        else:
            script[field] = [bad_pair]
        with pytest.raises(ValueError, match="invalid configured hooks mapping"):
            ConfiguredHooks.from_mapping({"hooks": {"hook_script": {"definition": {"name": "event.script", "major_version": 1}, "script": script}}})


def test_mapping_decoder_normalizes_missing_event_fields() -> None:
    """Missing required event fields fail as ValueError rather than constructor TypeError."""
    for definition in ({}, {"name": "event.only_name"}, {"major_version": 1}):
        with pytest.raises(ValueError, match="invalid configured hooks mapping"):
            ConfiguredHooks.from_mapping({"hooks": {"hook_missing": {"definition": definition}}})


def test_script_decoder_detaches_environment_and_platform_sequences(tmp_path: Path) -> None:
    """Mutating nested input after decoding cannot alter any script sequence."""
    script = _script_declaration(tmp_path)
    configured = ConfiguredHooks.from_mapping({"hooks": {"hook_script": {"definition": {"name": "event.script", "major_version": 1}, "script": script}}})
    script["options"]["environment"][0][1] = "changed"
    script["environment_snapshot"][0][1] = "changed"
    script["platform_policy"]["allowed_interpreters"].append("/bin/python")
    saved = configured.get_hook("hook_script").script
    assert saved is not None
    assert saved.options.environment == (("SAFE_NAME", "value"),)
    assert saved.environment_snapshot == (("SAFE_NAME", "snapshot"),)
    assert saved.platform_policy.allowed_interpreters == ()
