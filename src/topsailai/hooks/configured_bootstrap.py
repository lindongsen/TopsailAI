"""Versioned application-boundary bootstrap for configured Hooks."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from topsailai.hooks.artifact_contracts import (
    ArtifactClosureAssertion,
    ArtifactPythonRuntimeAuthority,
)
from topsailai.hooks.configured_contracts import ConfiguredTrustPolicy, is_valid_hook_name

_MAX_DOCUMENT_BYTES = 1_048_576
_BOOTSTRAP_ERROR = "invalid configured Hook bootstrap"
_MANIFEST_ERROR = "invalid configured trust manifest"
_CONFIG_ERROR = "invalid configured Hook configuration"


@dataclass(frozen=True, slots=True)
class ConfiguredHookBinding:
    """Describe one immutable configured Hook source selection."""

    hook_name: str
    enabled: bool = True
    scripts: tuple[Path, ...] = ()
    folder: Path | None = None

    def __post_init__(self) -> None:
        """Validate one exact scripts-or-folder selection."""
        if not is_valid_hook_name(self.hook_name) or type(self.enabled) is not bool:
            raise ValueError(_CONFIG_ERROR)
        if type(self.scripts) is not tuple or any(not _absolute_path(path) for path in self.scripts):
            raise ValueError(_CONFIG_ERROR)
        if self.folder is not None and not _absolute_path(self.folder):
            raise ValueError(_CONFIG_ERROR)
        if bool(self.scripts) == (self.folder is not None):
            raise ValueError(_CONFIG_ERROR)
        if len(self.scripts) > 1_024 or len(set(self.scripts)) != len(self.scripts):
            raise ValueError(_CONFIG_ERROR)


@dataclass(frozen=True, slots=True)
class ConfiguredHookBootstrap:
    """Hold one detached bootstrap generation loaded at the application boundary."""

    enabled: bool
    registration_mode: Literal["startup", "lazy"] = "startup"
    startup_policy: Literal["fail", "disable"] = "fail"
    configuration_generation: int = 1
    hooks: tuple[ConfiguredHookBinding, ...] = ()
    trust: ConfiguredTrustPolicy | None = None
    trust_identity: str = ""

    def __post_init__(self) -> None:
        """Validate the complete immutable bootstrap snapshot."""
        if type(self.enabled) is not bool:
            raise ValueError(_BOOTSTRAP_ERROR)
        if self.registration_mode not in ("startup", "lazy"):
            raise ValueError(_BOOTSTRAP_ERROR)
        if self.startup_policy not in ("fail", "disable"):
            raise ValueError(_BOOTSTRAP_ERROR)
        if type(self.configuration_generation) is not int or self.configuration_generation <= 0:
            raise ValueError(_BOOTSTRAP_ERROR)
        if type(self.hooks) is not tuple or any(type(item) is not ConfiguredHookBinding for item in self.hooks):
            raise ValueError(_BOOTSTRAP_ERROR)
        if len({item.hook_name for item in self.hooks}) != len(self.hooks):
            raise ValueError(_BOOTSTRAP_ERROR)
        if self.enabled:
            if type(self.trust) is not ConfiguredTrustPolicy or not _digest(self.trust_identity):
                raise ValueError(_BOOTSTRAP_ERROR)
        elif self.hooks or self.trust is not None or self.trust_identity:
            raise ValueError(_BOOTSTRAP_ERROR)

    @classmethod
    def disabled(cls) -> "ConfiguredHookBootstrap":
        """Return the canonical disabled snapshot without filesystem access."""
        return cls(False)


def load_configured_hook_bootstrap(environ: Mapping[str, str]) -> ConfiguredHookBootstrap:
    """Read configured files once from an explicit environment snapshot."""
    if not isinstance(environ, Mapping) or any(type(key) is not str or type(value) is not str for key, value in environ.items()):
        raise ValueError(_BOOTSTRAP_ERROR)
    enabled = _boolean(environ.get("TOPSAILAI_CONFIGURED_HOOKS_ENABLED", "0"))
    if not enabled:
        return ConfiguredHookBootstrap.disabled()
    mode = environ.get("TOPSAILAI_CONFIGURED_HOOKS_REGISTRATION_MODE", "startup")
    startup_policy = environ.get("TOPSAILAI_CONFIGURED_HOOKS_STARTUP_POLICY", "fail")
    config_path = _path(environ.get("TOPSAILAI_CONFIGURED_HOOKS_CONFIG", ""), _BOOTSTRAP_ERROR)
    manifest_path = _path(environ.get("TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST", ""), _BOOTSTRAP_ERROR)
    expected_digest = environ.get("TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST_SHA256", "")
    if mode not in ("startup", "lazy") or startup_policy not in ("fail", "disable") or not _digest(expected_digest):
        raise ValueError(_BOOTSTRAP_ERROR)
    config = _read_document(config_path, _CONFIG_ERROR)
    trust, actual_digest = load_configured_trust_manifest(
        manifest_path,
        expected_digest,
    )
    hooks = _decode_configuration(config, trust)
    return ConfiguredHookBootstrap(
        True,
        registration_mode=mode,
        startup_policy=startup_policy,
        hooks=hooks,
        trust=trust,
        trust_identity=actual_digest,
    )


def load_configured_trust_manifest(
    manifest_path: Path,
    expected_sha256: str,
) -> tuple[ConfiguredTrustPolicy, str]:
    """Load one pinned versioned trust manifest without authorizing discovered files."""
    if not _absolute_path(manifest_path) or not _digest(expected_sha256):
        raise ValueError(_MANIFEST_ERROR)
    manifest_data = _read_bytes(manifest_path, _MANIFEST_ERROR)
    actual_digest = hashlib.sha256(manifest_data).hexdigest()
    if not hmac.compare_digest(actual_digest, expected_sha256):
        raise ValueError("configured trust manifest digest mismatch")
    manifest = _decode_json(manifest_data, _MANIFEST_ERROR)
    return _decode_manifest(manifest), actual_digest


def _decode_configuration(value: dict[str, Any], trust: ConfiguredTrustPolicy) -> tuple[ConfiguredHookBinding, ...]:
    """Decode one strict versioned Hook source map."""
    _fields(value, {"schema_version", "hooks"}, _CONFIG_ERROR)
    if value.get("schema_version") != 1 or type(value.get("hooks")) is not dict:
        raise ValueError(_CONFIG_ERROR)
    roots = trust.source_roots
    if value["hooks"] and len(roots) != 1:
        raise ValueError(_CONFIG_ERROR)
    bindings: list[ConfiguredHookBinding] = []
    for name in sorted(value["hooks"]):
        raw = value["hooks"][name]
        if type(raw) is not dict:
            raise ValueError(_CONFIG_ERROR)
        _fields(raw, {"enabled", "scripts", "folder"}, _CONFIG_ERROR)
        enabled = raw.get("enabled", True)
        scripts_raw = raw.get("scripts")
        folder_raw = raw.get("folder")
        if type(enabled) is not bool or (scripts_raw is None) == (folder_raw is None):
            raise ValueError(_CONFIG_ERROR)
        scripts: tuple[Path, ...] = ()
        folder = None
        if scripts_raw is not None:
            if type(scripts_raw) is not list or not scripts_raw or any(type(item) is not str for item in scripts_raw):
                raise ValueError(_CONFIG_ERROR)
            scripts = tuple(_trusted_source(item, roots) for item in scripts_raw)
        else:
            if type(folder_raw) is not str:
                raise ValueError(_CONFIG_ERROR)
            folder = _trusted_source(folder_raw, roots)
        bindings.append(ConfiguredHookBinding(name, enabled, scripts, folder))
    return tuple(bindings)


def _decode_manifest(value: dict[str, Any]) -> ConfiguredTrustPolicy:
    """Decode one strict versioned trust manifest through existing contracts."""
    allowed = {
        "schema_version", "source_roots", "allowed_interpreters",
        "allow_native_scripts", "closure_assertions", "python_runtime",
    }
    _fields(value, allowed, _MANIFEST_ERROR)
    if value.get("schema_version") != 1:
        raise ValueError(_MANIFEST_ERROR)
    try:
        roots = _path_list(value.get("source_roots"))
        interpreters = _path_list(value.get("allowed_interpreters", []), allow_empty=True)
        native = value.get("allow_native_scripts", False)
        assertions_raw = value.get("closure_assertions", [])
        if type(native) is not bool or type(assertions_raw) is not list:
            raise ValueError
        assertions = tuple(_assertion(item) for item in assertions_raw)
        runtime_raw = value.get("python_runtime")
        runtime = None if runtime_raw is None else _python_runtime(runtime_raw)
        return ConfiguredTrustPolicy(roots, interpreters, native, assertions, runtime)
    except (TypeError, ValueError, KeyError):
        raise ValueError(_MANIFEST_ERROR) from None


def _assertion(value: object) -> ArtifactClosureAssertion:
    """Decode one exact closure assertion."""
    if type(value) is not dict:
        raise ValueError
    fields = {"source_path", "kind", "logical_name", "content_sha256", "runtime_sha256", "deployment_sha256", "closure"}
    _fields(value, fields, _MANIFEST_ERROR)
    if set(value) != fields or any(type(value[name]) is not str for name in fields):
        raise ValueError
    return ArtifactClosureAssertion(
        source_path=Path(value["source_path"]), kind=value["kind"],
        logical_name=value["logical_name"], content_sha256=value["content_sha256"],
        runtime_sha256=value["runtime_sha256"], deployment_sha256=value["deployment_sha256"],
        closure=value["closure"],
    )


def _python_runtime(value: object) -> ArtifactPythonRuntimeAuthority:
    """Decode the optional exact Python runtime assertion."""
    if type(value) is not dict:
        raise ValueError
    _fields(value, {"executable", "content_sha256", "bootstrap"}, _MANIFEST_ERROR)
    if set(value) != {"executable", "content_sha256", "bootstrap"} or any(type(item) is not str for item in value.values()):
        raise ValueError
    return ArtifactPythonRuntimeAuthority(Path(value["executable"]), value["content_sha256"], value["bootstrap"])


def _read_document(path: Path, error: str) -> dict[str, Any]:
    """Read and decode one bounded JSON object."""
    return _decode_json(_read_bytes(path, error), error)


def _read_bytes(path: Path, error: str) -> bytes:
    """Read at most one bounded document plus overflow evidence."""
    try:
        with path.open("rb") as stream:
            data = stream.read(_MAX_DOCUMENT_BYTES + 1)
    except OSError:
        raise ValueError(error) from None
    if not data or len(data) > _MAX_DOCUMENT_BYTES:
        raise ValueError(error)
    return data


def _decode_json(data: bytes, error: str) -> dict[str, Any]:
    """Decode one exact UTF-8 JSON object."""
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError(error) from None
    if type(value) is not dict:
        raise ValueError(error)
    return value


def _trusted_source(value: str, roots: tuple[Path, ...]) -> Path:
    """Resolve a relative source below exactly one authorized root."""
    if not value or "\x00" in value:
        raise ValueError(_CONFIG_ERROR)
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
        raise ValueError(_CONFIG_ERROR)
    path = roots[0] / relative
    if not _absolute_path(path):
        raise ValueError(_CONFIG_ERROR)
    return path


def _path_list(value: object, *, allow_empty: bool = False) -> tuple[Path, ...]:
    """Decode a bounded exact path list."""
    if type(value) is not list or (not allow_empty and not value) or len(value) > 32:
        raise ValueError
    paths = tuple(_path(item, _MANIFEST_ERROR) for item in value)
    if len(set(paths)) != len(paths):
        raise ValueError
    return paths


def _path(value: str, error: str) -> Path:
    """Decode one normalized absolute path without filesystem resolution."""
    if type(value) is not str:
        raise ValueError(error)
    path = Path(value)
    if not _absolute_path(path):
        raise ValueError(error)
    return path


def _absolute_path(path: object) -> bool:
    """Return whether a path is normalized, absolute, and bounded."""
    return isinstance(path, Path) and path.is_absolute() and ".." not in path.parts and "\x00" not in str(path) and len(str(path).encode()) <= 4096


def _boolean(value: str) -> bool:
    """Decode the bootstrap master switch strictly."""
    if value in ("0", ""):
        return False
    if value == "1":
        return True
    raise ValueError(_BOOTSTRAP_ERROR)


def _digest(value: object) -> bool:
    """Return whether a value is a lowercase SHA-256 digest."""
    return type(value) is str and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _fields(value: dict[str, Any], allowed: set[str], error: str) -> None:
    """Reject unknown mapping fields."""
    if set(value) - allowed:
        raise ValueError(error)
