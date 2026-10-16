"""Behavioral tests for selected-resource execution contracts."""

from pathlib import Path

import pytest

from topsailai.hooks.configured_resource_contracts import (
    ConfiguredScriptSettings,
    ConfiguredSelectedResources,
    normalize_environment_snapshot,
    validate_script_settings,
)
from topsailai.hooks.hook_script_contracts import HookScriptExecutionOptions
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from topsailai.hooks.resource_selection_contracts import (
    HookPointResourceSelection,
    HookResourceSelection,
)


POLICY = ExecutablePlatformPolicy("posix", ("/usr/bin/python3",))


def test_script_settings_detach_mapping_and_nested_options() -> None:
    """Selected Script settings own detached immutable values."""
    environment = {"SAFE_NAME": "before"}
    argv = ["--safe"]
    settings = ConfiguredScriptSettings(
        POLICY,
        HookScriptExecutionOptions(argv=argv),
        environment_allowlist=("SAFE_NAME",),
        environment_snapshot=environment,
    )
    environment["SAFE_NAME"] = "after"
    argv.append("changed")
    assert settings.environment_snapshot["SAFE_NAME"] == "before"
    assert settings.options.argv == ("--safe",)
    with pytest.raises(TypeError):
        settings.environment_snapshot["NEW"] = "value"


def test_script_settings_require_script_selection_and_valid_environment() -> None:
    """Selected resources enforce Script-settings pairing and safe environment names."""
    modules = HookResourceSelection(files=("/tmp/module.py",))
    scripts = HookResourceSelection(files=("/tmp/run",))
    with pytest.raises(ValueError):
        ConfiguredSelectedResources(HookPointResourceSelection(modules=modules), settings := ConfiguredScriptSettings(POLICY))
    with pytest.raises(ValueError):
        ConfiguredSelectedResources(HookPointResourceSelection(scripts=scripts))
    with pytest.raises(ValueError):
        ConfiguredScriptSettings(POLICY, environment_allowlist=("PYTHONPATH",))
    with pytest.raises(ValueError):
        ConfiguredScriptSettings(POLICY, environment_snapshot={"SAFE": "x"})
    assert settings is not None
    selected = ConfiguredSelectedResources(
        HookPointResourceSelection(modules=modules, scripts=scripts),
        ConfiguredScriptSettings(POLICY),
    )
    assert selected.selection.modules is modules


def test_validate_settings_and_snapshot_reject_shapes() -> None:
    """Validation rejects malformed boundary collections before I/O."""
    with pytest.raises(ValueError):
        normalize_environment_snapshot([], "invalid")
    with pytest.raises(ValueError):
        validate_script_settings(POLICY, HookScriptExecutionOptions(), object(), (), (), error="invalid")
    with pytest.raises(ValueError):
        validate_script_settings(POLICY, HookScriptExecutionOptions(environment=(("BAD=NAME", "x"),)),
                                 __import__("topsailai.hooks.hook_script_contracts", fromlist=["HookScriptExecutionPolicy"]).HookScriptExecutionPolicy(),
                                 (), (), error="invalid")


def test_selected_resource_paths_require_absolute_values() -> None:
    """Selected resource contracts reject relative source roots."""
    with pytest.raises(ValueError):
        ConfiguredSelectedResources(
            HookPointResourceSelection(modules=HookResourceSelection(folder="relative"))
        )
    with pytest.raises(ValueError):
        ConfiguredSelectedResources(
            HookPointResourceSelection(modules=HookResourceSelection(files=("relative.py",)))
        )


def test_settings_accept_valid_mapping_snapshot() -> None:
    """A valid mapping snapshot is normalized into a detached proxy."""
    settings = ConfiguredScriptSettings(
        POLICY,
        environment_allowlist=("SAFE",),
        environment_snapshot={"SAFE": "value"},
    )
    assert dict(settings.environment_snapshot) == {"SAFE": "value"}
    assert Path(settings.platform_policy.allowed_interpreters[0]).is_absolute()
