"""Boundary validation tests for selected-resource execution contracts."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from topsailai.hooks.configured_resource_contracts import (
    ConfiguredScriptSettings,
    ConfiguredSelectedResources,
    normalize_environment_snapshot,
    validate_script_settings,
)
from topsailai.hooks.hook_script_contracts import (
    HookScriptExecutionOptions,
    HookScriptExecutionPolicy,
)
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from topsailai.hooks.resource_selection_contracts import (
    HookPointResourceSelection,
    HookResourceSelection,
)


POLICY = ExecutablePlatformPolicy("posix", ("/usr/bin/python3",))
OPTIONS = HookScriptExecutionOptions()
EXECUTION = HookScriptExecutionPolicy()


def test_environment_pair_rejects_non_string_and_unencodable_values() -> None:
    """Environment validation rejects non-string names and unencodable values."""
    with pytest.raises(ValueError):
        validate_script_settings(
            POLICY, OPTIONS, EXECUTION, (123,), (), error="invalid"
        )
    with pytest.raises(ValueError):
        validate_script_settings(
            POLICY, OPTIONS, EXECUTION, ("SAFE",), (("SAFE", "\ud800"),), error="invalid"
        )


def test_environment_allowlist_rejects_duplicates_and_non_tuple() -> None:
    """Allowlist validation rejects duplicates and non-tuple containers."""
    with pytest.raises(ValueError):
        validate_script_settings(
            POLICY, OPTIONS, EXECUTION, ["SAFE"], (), error="invalid"
        )
    with pytest.raises(ValueError):
        validate_script_settings(
            POLICY, OPTIONS, EXECUTION, ("SAFE", "SAFE"), (), error="invalid"
        )


def test_environment_snapshot_rejects_malformed_pairs() -> None:
    """Snapshot validation rejects malformed pair shapes and unknown names."""
    with pytest.raises(ValueError):
        validate_script_settings(
            POLICY, OPTIONS, EXECUTION, ("SAFE",), (("SAFE",),), error="invalid"
        )
    with pytest.raises(ValueError):
        validate_script_settings(
            POLICY, OPTIONS, EXECUTION, ("SAFE",), (("OTHER", "x"),), error="invalid"
        )


def test_validate_script_settings_rejects_wrong_types_and_shapes() -> None:
    """Shared settings validation rejects wrong types before any I/O."""
    with pytest.raises(ValueError):
        validate_script_settings(object(), OPTIONS, EXECUTION, (), (), error="invalid")
    with pytest.raises(ValueError):
        validate_script_settings(POLICY, object(), EXECUTION, (), (), error="invalid")
    with pytest.raises(ValueError):
        validate_script_settings(POLICY, OPTIONS, object(), (), (), error="invalid")
    with pytest.raises(ValueError):
        validate_script_settings(
            POLICY, HookScriptExecutionOptions(argv="not-a-sequence"), EXECUTION,
            (), (), error="invalid",
        )
    with pytest.raises(ValueError):
        validate_script_settings(
            POLICY, HookScriptExecutionOptions(environment=(("A",),)), EXECUTION,
            (), (), error="invalid",
        )


def test_validate_script_settings_rejects_relative_interpreter_and_unsafe_environment() -> None:
    """Interpreter paths must be absolute and option environment pairs must be safe."""
    with pytest.raises(ValueError):
        validate_script_settings(
            ExecutablePlatformPolicy("posix", ("relative-python",)), OPTIONS,
            EXECUTION, (), (), error="invalid",
        )
    with pytest.raises(ValueError):
        validate_script_settings(
            POLICY, HookScriptExecutionOptions(environment=(("PYTHONPATH", "x"),)),
            EXECUTION, (), (), error="invalid",
        )


def test_normalize_environment_snapshot_rejects_non_mapping_and_bad_items() -> None:
    """Snapshot normalization accepts only mappings yielding two-tuples."""
    with pytest.raises(ValueError):
        normalize_environment_snapshot([], "invalid")

    class BrokenItems(Mapping):
        """Expose a mapping whose items() raises a TypeError."""

        def __getitem__(self, key):
            raise KeyError(key)

        def __iter__(self):
            return iter(())

        def __len__(self):
            return 0

        def items(self):
            raise TypeError("broken items")

    with pytest.raises(ValueError):
        normalize_environment_snapshot(BrokenItems(), "invalid")

    class BadShape(Mapping):
        """Expose a mapping whose items() yields non-pair values."""

        def __getitem__(self, key):
            raise KeyError(key)

        def __iter__(self):
            return iter(())

        def __len__(self):
            return 0

        def items(self):
            return (("only-one",),)

    with pytest.raises(ValueError):
        normalize_environment_snapshot(BadShape(), "invalid")


def test_selected_resources_reject_wrong_selection_and_settings_types() -> None:
    """Selected resources require exact contract types for both fields."""
    with pytest.raises(ValueError):
        ConfiguredSelectedResources(object())
    scripts = HookResourceSelection(files=("/tmp/run",))
    with pytest.raises(ValueError):
        ConfiguredSelectedResources(
            HookPointResourceSelection(scripts=scripts), script_settings=object()
        )


def test_script_settings_accepts_valid_policy_and_detaches_environment() -> None:
    """A valid settings record detaches its environment mapping."""
    settings = ConfiguredScriptSettings(
        POLICY,
        HookScriptExecutionOptions(argv=("--flag",)),
        environment_allowlist=("SAFE",),
        environment_snapshot={"SAFE": "value"},
    )
    assert settings.options.argv == ("--flag",)
    assert dict(settings.environment_snapshot) == {"SAFE": "value"}


def test_configured_script_rejects_relative_and_non_path_targets() -> None:
    """Configured scripts require an absolute pathlib.Path target."""
    from topsailai.hooks.configured_contracts import ConfiguredScript
    with pytest.raises(ValueError, match="invalid configured script"):
        ConfiguredScript("relative", POLICY)
    with pytest.raises(ValueError, match="invalid configured script"):
        ConfiguredScript(Path("relative"), POLICY)


def test_configured_hook_point_rejects_wrong_resources_type() -> None:
    """Hook points reject lookalike selected-resource values."""
    from topsailai.hooks.configured_contracts import ConfiguredHookPoint
    from topsailai.hooks.contracts import EventDefinition
    with pytest.raises(ValueError, match="invalid configured hook point"):
        ConfiguredHookPoint("hook_alpha", EventDefinition("test.alpha", 1), resources=object())


def test_configured_hook_point_rejects_selected_resources_with_legacy_sources() -> None:
    """Selected resources cannot be combined with legacy Module or Script sources."""
    from topsailai.hooks.configured_contracts import ConfiguredHookPoint, ConfiguredScript
    from topsailai.hooks.contracts import EventDefinition
    selected = ConfiguredSelectedResources(
        HookPointResourceSelection(modules=HookResourceSelection(files=("/tmp/module.py",)))
    )
    with pytest.raises(ValueError, match="invalid configured hook point"):
        ConfiguredHookPoint("hook_alpha", EventDefinition("test.alpha", 1), module_folder=Path("/tmp"), resources=selected)
    with pytest.raises(ValueError, match="invalid configured hook point"):
        ConfiguredHookPoint("hook_alpha", EventDefinition("test.alpha", 1), script=ConfiguredScript(Path("/tmp/run"), POLICY), resources=selected)


def test_configured_hook_point_rejects_caller_owned_hook_context() -> None:
    """Context injection rejects a caller-owned hook_context keyword."""
    from topsailai.hooks.configured_contracts import ConfiguredHookPoint
    from topsailai.hooks.contracts import EventDefinition

    with pytest.raises(ValueError, match="invalid configured context injection"):
        ConfiguredHookPoint(
            "hook_alpha",
            EventDefinition("test.alpha", 1),
            module_kwargs={"hook_context": "caller-owned"},
            inject_hook_context=True,
        )
