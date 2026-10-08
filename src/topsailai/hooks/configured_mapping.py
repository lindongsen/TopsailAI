"""Strict JSON-boundary decoding for configured hook declarations."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any, Mapping

from topsailai.hooks.configuration import HookSettings
from topsailai.hooks.contracts import EventDefinition
from topsailai.hooks.hook_script_contracts import (
    HookScriptExecutionOptions,
    HookScriptExecutionPolicy,
)
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy

_ERROR = "invalid configured hooks mapping"


def _dictionary(value: object, error: str = _ERROR) -> dict[str, Any]:
    """Require an exact dictionary with string keys."""
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValueError(error)
    return value


def _allowed(value: dict[str, Any], names: set[str], error: str = _ERROR) -> None:
    """Reject unknown fields at one strict mapping boundary."""
    if set(value) - names:
        raise ValueError(error)


def _strings(value: object, field: str) -> tuple[str, ...]:
    """Validate a string sequence before detaching it into a tuple."""
    if type(value) not in (list, tuple) or any(type(item) is not str for item in value):
        raise ValueError(_ERROR)
    return tuple(value)


def _pairs(value: object, field: str) -> tuple[tuple[str, str], ...]:
    """Validate exact string pairs before converting caller-owned containers."""
    if type(value) not in (list, tuple):
        raise ValueError(_ERROR)
    pairs: list[tuple[str, str]] = []
    for item in value:
        if type(item) not in (list, tuple) or len(item) != 2:
            raise ValueError(_ERROR)
        if any(type(part) is not str for part in item):
            raise ValueError(_ERROR)
        pairs.append((item[0], item[1]))
    return tuple(pairs)


def _script(value: object):
    """Decode one immutable configured script through authoritative contracts."""
    from topsailai.hooks.configured_contracts import ConfiguredScript

    raw = _dictionary(value)
    _allowed(raw, {
        "target", "platform_policy", "options", "policy",
        "environment_allowlist", "environment_snapshot",
    })
    target = raw.get("target")
    platform = _dictionary(raw.get("platform_policy"))
    _allowed(platform, {"platform", "allowed_interpreters", "native_suffixes"})
    if type(target) is not str or type(platform.get("platform")) is not str:
        raise ValueError(_ERROR)
    options_raw = _dictionary(raw.get("options", {}))
    _allowed(options_raw, {"argv", "cwd", "environment"})
    policy_raw = _dictionary(raw.get("policy", {}))
    _allowed(policy_raw, {item.name for item in fields(HookScriptExecutionPolicy)})
    cwd = options_raw.get("cwd")
    if cwd is not None and type(cwd) is not str:
        raise ValueError(_ERROR)
    try:
        options = HookScriptExecutionOptions(
            argv=_strings(options_raw.get("argv", ()), "argv"),
            cwd=None if cwd is None else Path(cwd),
            environment=_pairs(options_raw.get("environment", ()), "environment"),
        )
        platform_policy = ExecutablePlatformPolicy(
            platform=platform["platform"],
            allowed_interpreters=_strings(platform.get("allowed_interpreters", ()), "allowed_interpreters"),
            native_suffixes=_strings(platform.get("native_suffixes", ()), "native_suffixes"),
        )
        policy = HookScriptExecutionPolicy(**policy_raw)
        allowlist = _strings(raw.get("environment_allowlist", ()), "environment_allowlist")
        snapshot = _pairs(raw.get("environment_snapshot", ()), "environment_snapshot")
        return ConfiguredScript(
            target=Path(target),
            platform_policy=platform_policy,
            options=options,
            policy=policy,
            environment_allowlist=allowlist,
            environment_snapshot=snapshot,
        )
    except (TypeError, ValueError, KeyError):
        raise ValueError(_ERROR) from None


def decode_configured_hooks(value: Mapping[str, Any]):
    """Decode the complete configured-hooks mapping in canonical name order."""
    from topsailai.hooks.configured_contracts import (
        ConfiguredHookPoint,
        ConfiguredHooks,
        ConfiguredPreparationPolicy,
        is_valid_hook_name,
    )

    raw = _dictionary(value)
    _allowed(raw, {"hooks", "settings", "policy"})
    hooks = _dictionary(raw.get("hooks"))
    points = []
    point_fields = {"definition", "module_folder", "module_args", "module_kwargs", "script", "max_concurrency"}
    definition_fields = {"name", "major_version", "payload_schema", "payload_limit_bytes"}
    for hook_name in sorted(hooks):
        if not is_valid_hook_name(hook_name):
            raise ValueError("invalid configured hook name")
        declaration = _dictionary(hooks[hook_name])
        _allowed(declaration, point_fields)
        if "hook_name" in declaration:
            raise ValueError(_ERROR)
        definition_raw = _dictionary(declaration.get("definition"))
        _allowed(definition_raw, definition_fields)
        if not {"name", "major_version"}.issubset(definition_raw):
            raise ValueError(_ERROR)
        try:
            definition = EventDefinition(**definition_raw)
            folder = declaration.get("module_folder")
            if folder is not None and type(folder) is not str:
                raise ValueError(_ERROR)
            module_args = declaration.get("module_args", ())
            module_kwargs = declaration.get("module_kwargs", {})
            if type(module_args) not in (list, tuple) or type(module_kwargs) is not dict:
                raise ValueError(_ERROR)
            script_raw = declaration.get("script")
            script = None if script_raw is None else _script(script_raw)
            points.append(ConfiguredHookPoint(
                hook_name=hook_name, definition=definition,
                module_folder=None if folder is None else Path(folder),
                module_args=tuple(module_args), module_kwargs=module_kwargs,
                script=script, max_concurrency=declaration.get("max_concurrency", 1),
            ))
        except (TypeError, ValueError):
            raise ValueError(_ERROR) from None
    settings = HookSettings.from_mapping(raw.get("settings", {}))
    policy_raw = _dictionary(raw.get("policy", {}))
    _allowed(policy_raw, {item.name for item in fields(ConfiguredPreparationPolicy)})
    try:
        policy = ConfiguredPreparationPolicy(**policy_raw)
    except (TypeError, ValueError):
        raise ValueError(_ERROR) from None
    return ConfiguredHooks(tuple(points), settings, policy)
