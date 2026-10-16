"""Contracts for selected Hook resources and target-free Script settings."""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from topsailai.hooks.hook_script import _valid_options, _valid_policy
from topsailai.hooks.hook_script_contracts import (
    HookScriptExecutionOptions,
    HookScriptExecutionPolicy,
)
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from topsailai.hooks.resource_selection_contracts import HookPointResourceSelection


_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_ENVIRONMENT = frozenset(
    {
        "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "PYTHONDONTWRITEBYTECODE",
        "TOPSAILAI_HOOK_RESULT_FD", "TOPSAILAI_HOOK_RESULT_SOCKET",
    }
)
_PROHIBITED_ENVIRONMENT = frozenset({"BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS"})


def _safe_environment_pair(name: str, value: str) -> bool:
    """Validate one environment pair using the legacy ASCII contract."""
    if type(name) is not str or type(value) is not str:
        return False
    if not (
        _ENVIRONMENT_NAME.fullmatch(name)
        and name not in _RESERVED_ENVIRONMENT
        and name not in _PROHIBITED_ENVIRONMENT
        and not name.startswith(("PYTHON", "LD_", "DYLD_"))
        and "\x00" not in value
    ):
        return False
    try:
        name.encode("utf-8")
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _validate_environment_allowlist(value: object, error: str) -> tuple[str, ...]:
    """Validate the legacy tuple-only environment allowlist."""
    if type(value) is not tuple or any(
        type(name) is not str or not _safe_environment_pair(name, "")
        for name in value
    ):
        raise ValueError(error)
    if len(set(value)) != len(value):
        raise ValueError(error)
    return tuple(value)


def _validate_environment_snapshot(value: object, allowlist: tuple[str, ...], error: str) -> tuple[tuple[str, str], ...]:
    """Validate the legacy tuple-only environment snapshot."""
    if type(value) is not tuple or any(
        type(item) is not tuple
        or len(item) != 2
        or type(item[0]) is not str
        or type(item[1]) is not str
        or not _safe_environment_pair(item[0], item[1])
        for item in value
    ):
        raise ValueError(error)
    names = tuple(name for name, _ in value)
    if len(set(names)) != len(names) or not set(names).issubset(allowlist):
        raise ValueError(error)
    return tuple((name, content) for name, content in value)


def validate_script_settings(
    platform_policy: object,
    options: object,
    policy: object,
    environment_allowlist: object,
    environment_snapshot: object,
    *,
    error: str,
) -> tuple[ExecutablePlatformPolicy, HookScriptExecutionOptions, HookScriptExecutionPolicy, tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Validate and detach shared Script execution settings without target or I/O."""
    if type(platform_policy) is not ExecutablePlatformPolicy:
        raise ValueError(error)
    if type(platform_policy.platform) is not str:
        raise ValueError(error)
    if type(options) is not HookScriptExecutionOptions:
        raise ValueError(error)
    if type(policy) is not HookScriptExecutionPolicy:
        raise ValueError(error)
    if type(options.argv) not in (list, tuple):
        raise ValueError(error)
    if type(options.environment) not in (list, tuple) or any(
        type(item) not in (list, tuple) or len(item) != 2
        for item in options.environment
    ):
        raise ValueError(error)
    try:
        detached_platform = ExecutablePlatformPolicy(
            platform=platform_policy.platform,
            allowed_interpreters=tuple(platform_policy.allowed_interpreters),
            native_suffixes=tuple(platform_policy.native_suffixes),
        )
        detached_options = HookScriptExecutionOptions(
            argv=tuple(options.argv),
            cwd=options.cwd,
            environment=tuple(tuple(item) for item in options.environment),
        )
        detached_policy = HookScriptExecutionPolicy(
            entry_timeout_ms=policy.entry_timeout_ms,
            hook_timeout_ms=policy.hook_timeout_ms,
            cleanup_timeout_ms=policy.cleanup_timeout_ms,
            terminate_grace_ms=policy.terminate_grace_ms,
            stdin_limit_bytes=policy.stdin_limit_bytes,
            stdout_limit_bytes=policy.stdout_limit_bytes,
            stderr_limit_bytes=policy.stderr_limit_bytes,
            output_total_limit_bytes=policy.output_total_limit_bytes,
            max_entries=policy.max_entries,
            argument_environment_limit_bytes=policy.argument_environment_limit_bytes,
            result_limit_bytes=policy.result_limit_bytes,
        )
    except (TypeError, ValueError):
        raise ValueError(error) from None
    if any(not Path(value).is_absolute() for value in detached_platform.allowed_interpreters):
        raise ValueError(error)
    if not _valid_policy(detached_policy) or not _valid_options(detached_options, detached_policy):
        raise ValueError(error)
    if any(not _safe_environment_pair(name, value) for name, value in detached_options.environment):
        raise ValueError(error)
    allowlist = _validate_environment_allowlist(environment_allowlist, error)
    snapshot = _validate_environment_snapshot(environment_snapshot, allowlist, error)
    return detached_platform, detached_options, detached_policy, allowlist, snapshot


def normalize_environment_snapshot(value: object, error: str) -> tuple[tuple[str, str], ...]:
    """Convert only a mapping snapshot to the tuple form used by shared validation."""
    if not isinstance(value, Mapping):
        raise ValueError(error)
    try:
        items = tuple(value.items())
    except (AttributeError, TypeError):
        raise ValueError(error) from None
    if any(type(item) is not tuple or len(item) != 2 for item in items):
        raise ValueError(error)
    return items


@dataclass(frozen=True, slots=True)
class ConfiguredScriptSettings:
    """Describe target-free execution settings for selected Script sources."""

    platform_policy: ExecutablePlatformPolicy
    options: HookScriptExecutionOptions = HookScriptExecutionOptions()
    policy: HookScriptExecutionPolicy = HookScriptExecutionPolicy()
    environment_allowlist: tuple[str, ...] = ()
    environment_snapshot: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Validate and deeply detach settings without filesystem or environment access."""
        error = "invalid configured script"
        snapshot = normalize_environment_snapshot(self.environment_snapshot, error)
        values = validate_script_settings(
            self.platform_policy, self.options, self.policy,
            self.environment_allowlist, snapshot, error=error,
        )
        object.__setattr__(self, "platform_policy", values[0])
        object.__setattr__(self, "options", values[1])
        object.__setattr__(self, "policy", values[2])
        object.__setattr__(self, "environment_allowlist", values[3])
        object.__setattr__(self, "environment_snapshot", MappingProxyType(dict(values[4])))


@dataclass(frozen=True, slots=True)
class ConfiguredSelectedResources:
    """Describe a complete selected-resource replacement for one Hook Point."""

    selection: HookPointResourceSelection
    script_settings: ConfiguredScriptSettings | None = None

    def __post_init__(self) -> None:
        """Validate selected resources and require settings exactly for Script selections."""
        if type(self.selection) is not HookPointResourceSelection:
            raise ValueError("invalid configured selected resources")
        for selector in (self.selection.modules, self.selection.scripts):
            if selector is None:
                continue
            if selector.folder is not None and not Path(selector.folder).is_absolute():
                raise ValueError("invalid configured selected resources")
            if any(not Path(path).is_absolute() for path in selector.files):
                raise ValueError("invalid configured selected resources")
        if self.selection.scripts is not None and self.script_settings is None:
            raise ValueError("invalid configured selected resources")
        if self.selection.scripts is None and self.script_settings is not None:
            raise ValueError("invalid configured selected resources")
        if self.script_settings is not None and type(self.script_settings) is not ConfiguredScriptSettings:
            raise ValueError("invalid configured selected resources")
