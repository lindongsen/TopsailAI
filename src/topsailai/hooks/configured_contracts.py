"""Frozen public contracts for configured hook preparation."""

from __future__ import annotations

import re
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass, field, fields
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping, TYPE_CHECKING

from topsailai.hooks.artifact_contracts import (
    ArtifactCaptureTrust,
    ArtifactClosureAssertion,
    ArtifactPythonRuntimeAuthority,
)
from topsailai.hooks.artifact_structure import validate_capture_trust_structure
from topsailai.hooks.configuration import HookLimits, HookSettings
from topsailai.hooks.contracts import EventDefinition, JsonValue
from topsailai.hooks.hook_script import _valid_options, _valid_policy
from topsailai.hooks.hook_script_contracts import (
    HookScriptExecutionOptions,
    HookScriptExecutionPolicy,
)
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from topsailai.hooks.validation import freeze_json, validate_event_definition

if TYPE_CHECKING:
    from topsailai.hooks.runtime import HookRuntime

_INVALID_TRUST = "invalid configured trust policy"
_HOOK_NAME = re.compile(r"^hook_[a-z][a-z0-9_]*$")
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_ENVIRONMENT = frozenset(
    {
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "PYTHONDONTWRITEBYTECODE",
        "TOPSAILAI_HOOK_RESULT_FD",
        "TOPSAILAI_HOOK_RESULT_SOCKET",
    }
)
_PROHIBITED_ENVIRONMENT = frozenset({"BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS"})


def _plain_json(value: Any) -> Any:
    """Normalize supported collections within the configured JSON budgets."""
    item_count = 0

    def normalize(current: Any, depth: int, ancestors: set[int]) -> Any:
        """Detach one value while bounding recursive collection traversal."""
        nonlocal item_count
        if depth > 16:
            raise ValueError("JSON value exceeds maximum depth")
        if not isinstance(current, MappingABC) and type(current) not in (list, tuple):
            return current
        identity = id(current)
        if identity in ancestors:
            raise ValueError("cyclic JSON value is not allowed")
        ancestors.add(identity)
        try:
            item_count += len(current)
            if item_count > 1_024:
                raise ValueError("JSON value exceeds maximum item count")
            if isinstance(current, MappingABC):
                return {
                    key: normalize(item, depth + 1, ancestors)
                    for key, item in current.items()
                }
            return [normalize(item, depth + 1, ancestors) for item in current]
        finally:
            ancestors.remove(identity)

    return normalize(value, 0, set())


def _frozen_json(value: Any) -> JsonValue:
    """Validate, detach, and recursively freeze one bounded JSON value."""
    detached = freeze_json(_plain_json(value))
    if type(detached) is dict:
        return MappingProxyType({key: _frozen_json(item) for key, item in detached.items()})
    if type(detached) is list:
        return tuple(_frozen_json(item) for item in detached)
    return detached


def _safe_environment_pair(name: str, value: str) -> bool:
    """Return whether one caller environment pair satisfies C04."""
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


@dataclass(frozen=True, slots=True)
class ConfiguredPreparationPolicy:
    """Bound one complete configured preparation operation."""

    timeout_ms: int = 10_000
    max_hook_points: int = 32
    max_scanned_entries: int = 4_096
    max_candidates: int = 1_024
    max_artifact_bytes: int = 67_108_864

    def __post_init__(self) -> None:
        """Reject non-positive or out-of-contract preparation limits."""
        limits = (
            self.timeout_ms,
            self.max_hook_points,
            self.max_scanned_entries,
            self.max_candidates,
            self.max_artifact_bytes,
        )
        if any(type(value) is not int or value <= 0 for value in limits):
            raise ValueError("invalid configured preparation policy")
        if self.timeout_ms > 600_000 or self.max_hook_points > 32:
            raise ValueError("invalid configured preparation policy")
        if self.max_scanned_entries > 4_096 or self.max_candidates > 1_024:
            raise ValueError("invalid configured preparation policy")
        if self.max_artifact_bytes > 67_108_864:
            raise ValueError("invalid configured preparation policy")


@dataclass(frozen=True, slots=True)
class ConfiguredScript:
    """Describe one caller-restricted configured script source."""

    target: Path
    platform_policy: ExecutablePlatformPolicy
    options: HookScriptExecutionOptions = HookScriptExecutionOptions()
    policy: HookScriptExecutionPolicy = HookScriptExecutionPolicy()
    environment_allowlist: tuple[str, ...] = ()
    environment_snapshot: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        """Validate and detach exact script input without filesystem access."""
        if not isinstance(self.target, Path) or not self.target.is_absolute():
            raise ValueError("invalid configured script")
        if type(self.platform_policy) is not ExecutablePlatformPolicy:
            raise ValueError("invalid configured script")
        if type(self.platform_policy.platform) is not str:
            raise ValueError("invalid configured script")
        if type(self.options) is not HookScriptExecutionOptions:
            raise ValueError("invalid configured script")
        if type(self.policy) is not HookScriptExecutionPolicy:
            raise ValueError("invalid configured script")
        if type(self.options.argv) not in (list, tuple):
            raise ValueError("invalid configured script")
        if type(self.options.environment) not in (list, tuple) or any(
            type(item) not in (list, tuple) or len(item) != 2
            for item in self.options.environment
        ):
            raise ValueError("invalid configured script")
        try:
            platform_policy = ExecutablePlatformPolicy(
                platform=self.platform_policy.platform,
                allowed_interpreters=tuple(self.platform_policy.allowed_interpreters),
                native_suffixes=tuple(self.platform_policy.native_suffixes),
            )
            options = HookScriptExecutionOptions(
                argv=tuple(self.options.argv),
                cwd=self.options.cwd,
                environment=tuple(tuple(item) for item in self.options.environment),
            )
            policy = HookScriptExecutionPolicy(
                entry_timeout_ms=self.policy.entry_timeout_ms,
                hook_timeout_ms=self.policy.hook_timeout_ms,
                cleanup_timeout_ms=self.policy.cleanup_timeout_ms,
                terminate_grace_ms=self.policy.terminate_grace_ms,
                stdin_limit_bytes=self.policy.stdin_limit_bytes,
                stdout_limit_bytes=self.policy.stdout_limit_bytes,
                stderr_limit_bytes=self.policy.stderr_limit_bytes,
                output_total_limit_bytes=self.policy.output_total_limit_bytes,
                max_entries=self.policy.max_entries,
                argument_environment_limit_bytes=self.policy.argument_environment_limit_bytes,
                result_limit_bytes=self.policy.result_limit_bytes,
            )
        except (TypeError, ValueError):
            raise ValueError("invalid configured script") from None
        if any(not Path(value).is_absolute() for value in platform_policy.allowed_interpreters):
            raise ValueError("invalid configured script")
        if not _valid_policy(policy) or not _valid_options(options, policy):
            raise ValueError("invalid configured script")
        if any(not _safe_environment_pair(name, value) for name, value in options.environment):
            raise ValueError("invalid configured script")
        if type(self.environment_allowlist) is not tuple or any(
            type(name) is not str or not _safe_environment_pair(name, "")
            for name in self.environment_allowlist
        ):
            raise ValueError("invalid configured script")
        if len(set(self.environment_allowlist)) != len(self.environment_allowlist):
            raise ValueError("invalid configured script")
        if type(self.environment_snapshot) is not tuple or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not str
            or not _safe_environment_pair(item[0], item[1])
            for item in self.environment_snapshot
        ):
            raise ValueError("invalid configured script")
        names = tuple(name for name, _ in self.environment_snapshot)
        if len(set(names)) != len(names) or not set(names).issubset(self.environment_allowlist):
            raise ValueError("invalid configured script")
        object.__setattr__(self, "platform_policy", platform_policy)
        object.__setattr__(self, "options", options)
        object.__setattr__(self, "policy", policy)


@dataclass(frozen=True, slots=True)
class ConfiguredHookPoint:
    """Describe one complete configured hook-point replacement."""

    hook_name: str
    definition: EventDefinition
    module_folder: Path | None = None
    module_args: tuple[JsonValue, ...] = ()
    module_kwargs: Mapping[str, JsonValue] = field(default_factory=dict)
    script: ConfiguredScript | None = None
    max_concurrency: int = 1

    @property
    def hook_point(self) -> str:
        """Return the deprecated configured-name alias."""
        return self.hook_name

    def __post_init__(self) -> None:
        """Validate and deeply detach caller-owned configured values."""
        if not is_valid_hook_name(self.hook_name):
            raise ValueError("invalid configured hook name")
        if type(self.definition) is not EventDefinition:
            raise ValueError("invalid configured hook point")
        if validate_event_definition(self.definition):
            raise ValueError("invalid configured hook point")
        if self.definition.payload_limit_bytes > 65_536:
            raise ValueError("invalid configured hook point")
        try:
            definition = EventDefinition(
                name=self.definition.name,
                major_version=self.definition.major_version,
                payload_schema=self.definition.payload_schema,
                payload_limit_bytes=self.definition.payload_limit_bytes,
            )
        except (TypeError, ValueError):
            raise ValueError("invalid configured hook point") from None
        if validate_event_definition(definition):
            raise ValueError("invalid configured hook point")
        if self.module_folder is not None and (
            not isinstance(self.module_folder, Path) or not self.module_folder.is_absolute()
        ):
            raise ValueError("invalid configured hook point")
        if type(self.module_args) is not tuple or not isinstance(self.module_kwargs, MappingABC):
            raise ValueError("invalid configured hook point")
        if self.script is not None and type(self.script) is not ConfiguredScript:
            raise ValueError("invalid configured hook point")
        if type(self.max_concurrency) is not int or self.max_concurrency <= 0:
            raise ValueError("invalid configured hook point")
        try:
            envelope = _frozen_json([list(self.module_args), self.module_kwargs])
        except ValueError:
            raise ValueError("invalid configured hook point") from None
        object.__setattr__(self, "definition", definition)
        object.__setattr__(self, "module_args", envelope[0])
        object.__setattr__(self, "module_kwargs", envelope[1])


@dataclass(frozen=True, slots=True)
class ConfiguredHooks:
    """Describe the complete configured replacement for one scope."""

    hook_points: tuple[ConfiguredHookPoint, ...]
    settings: HookSettings
    policy: ConfiguredPreparationPolicy = ConfiguredPreparationPolicy()
    _hook_index: Mapping[str, ConfiguredHookPoint] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate exact immutable top-level configured inputs."""
        if type(self.hook_points) is not tuple or any(
            type(point) is not ConfiguredHookPoint for point in self.hook_points
        ):
            raise ValueError("invalid configured hooks")
        if type(self.settings) is not HookSettings or self.settings.validate():
            raise ValueError("invalid configured hooks")
        if type(self.settings.limits) is not HookLimits:
            raise ValueError("invalid configured hooks")
        limits = HookLimits(
            workers=self.settings.limits.workers,
            queue_items=self.settings.limits.queue_items,
            queue_bytes=self.settings.limits.queue_bytes,
            event_bytes=self.settings.limits.event_bytes,
            bindings_per_event=self.settings.limits.bindings_per_event,
            handler_timeout_ms=self.settings.limits.handler_timeout_ms,
            dispatch_timeout_ms=self.settings.limits.dispatch_timeout_ms,
            shutdown_timeout_ms=self.settings.limits.shutdown_timeout_ms,
        )
        settings = HookSettings(
            enabled=self.settings.enabled,
            schema_version=self.settings.schema_version,
            limits=limits,
        )
        if settings.validate():
            raise ValueError("invalid configured hooks")
        if type(self.policy) is not ConfiguredPreparationPolicy:
            raise ValueError("invalid configured hooks")
        if len(self.hook_points) > self.policy.max_hook_points:
            raise ValueError("invalid configured hooks")
        point_names = {point.hook_name for point in self.hook_points}
        event_keys = {
            (point.definition.name, point.definition.major_version)
            for point in self.hook_points
        }
        if len(point_names) != len(self.hook_points) or len(event_keys) != len(self.hook_points):
            raise ValueError("invalid configured hooks")
        object.__setattr__(self, "settings", settings)
        object.__setattr__(self, "hook_points", tuple(self.hook_points))
        object.__setattr__(self, "_hook_index", MappingProxyType({point.hook_name: point for point in self.hook_points}))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ConfiguredHooks":
        """Decode a strict deterministic mapping keyed by canonical hook name."""
        from topsailai.hooks.configured_mapping import decode_configured_hooks

        return decode_configured_hooks(value)

    def get_hook(self, hook_name: str) -> ConfiguredHookPoint | None:
        """Return the exact configured declaration for one canonical name."""
        if not is_valid_hook_name(hook_name):
            return None
        return self._hook_index.get(hook_name)


def is_valid_hook_name(value: object) -> bool:
    """Return whether a value is a canonical configured hook name."""
    return type(value) is str and len(value) <= 128 and _HOOK_NAME.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class ConfiguredTrustPolicy:
    """Hold immutable host authority for configured source admission."""

    source_roots: tuple[Path, ...]
    allowed_interpreters: tuple[Path, ...] = ()
    allow_native_scripts: bool = False
    closure_assertions: tuple[ArtifactClosureAssertion, ...] = ()
    python_runtime: ArtifactPythonRuntimeAuthority | None = None

    def __post_init__(self) -> None:
        """Validate and detach authority without touching the filesystem."""
        trust = ArtifactCaptureTrust(
            source_roots=self.source_roots,
            allowed_interpreters=self.allowed_interpreters,
            allow_native_scripts=self.allow_native_scripts,
            closure_assertions=self.closure_assertions,
            python_runtime=self.python_runtime,
        )
        if not validate_capture_trust_structure(trust):
            raise ValueError(_INVALID_TRUST)
        assertions = tuple(
            ArtifactClosureAssertion(
                source_path=item.source_path,
                kind=item.kind,
                logical_name=item.logical_name,
                content_sha256=item.content_sha256,
                runtime_sha256=item.runtime_sha256,
                deployment_sha256=item.deployment_sha256,
                closure=item.closure,
            )
            for item in self.closure_assertions
        )
        runtime = self.python_runtime
        if runtime is not None:
            runtime = ArtifactPythonRuntimeAuthority(
                executable=runtime.executable,
                content_sha256=runtime.content_sha256,
                bootstrap=runtime.bootstrap,
            )
        object.__setattr__(self, "source_roots", tuple(self.source_roots))
        object.__setattr__(self, "allowed_interpreters", tuple(self.allowed_interpreters))
        object.__setattr__(self, "closure_assertions", assertions)
        object.__setattr__(self, "python_runtime", runtime)


def _valid_paths(paths: object, *, minimum: int) -> bool:
    """Return whether paths are unique normalized absolute Path values."""
    if type(paths) is not tuple or not minimum <= len(paths) <= 32:
        return False
    if any(not isinstance(path, Path) or not path.is_absolute() or "\x00" in str(path) for path in paths):
        return False
    if any(".." in path.parts or path != Path(str(path)) for path in paths):
        return False
    return len(set(paths)) == len(paths)


@dataclass(frozen=True, slots=True)
class ConfiguredRegistrationResult:
    """Report atomic configured registration without exposing lifecycle internals."""

    accepted: bool
    changed: bool = False
    script_count: int = 0
    errors: tuple[str, ...] = ()
    active_revision: int | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        """Validate the small caller-facing registration result."""
        if type(self.accepted) is not bool or type(self.changed) is not bool:
            raise ValueError("invalid configured registration result")
        if type(self.script_count) is not int or self.script_count < 0:
            raise ValueError("invalid configured registration result")
        if type(self.errors) is not tuple or any(
            type(error) is not str or not error for error in self.errors
        ):
            raise ValueError("invalid configured registration result")
        if not self.accepted and (self.changed or self.script_count):
            raise ValueError("invalid configured registration result")
        if self.accepted and self.errors:
            raise ValueError("invalid configured registration result")
        if self.active_revision is not None and (not self.accepted or
                type(self.active_revision) is not int or self.active_revision <= 0):
            raise ValueError("invalid configured registration result")


class PreparedConfigured:
    """Represent one opaque Runtime-issued unpublished candidate."""

    __slots__ = ("_runtime", "_state")

    def __new__(cls, *args: object, **kwargs: object) -> PreparedConfigured:
        """Reject public construction; the Runtime owner allocates issued instances."""
        raise TypeError("PreparedConfigured is runtime-issued")


_CONFIGURED_ERROR_TOKENS = frozenset(
    {
        "activation_failed",
        "artifact_rejected",
        "binding_conflict",
        "cancelled",
        "candidate_consumed",
        "candidate_disposed",
        "candidate_expired",
        "capacity_exceeded",
        "cleanup_pending",
        "definition_conflict",
        "discovery_rejected",
        "foreign_candidate",
        "internal_error",
        "invalid_candidate",
        "invalid_configuration",
        "invalid_lease",
        "invalid_plan",
        "invalid_scope",
        "prepare_timeout",
        "runtime_closed",
        "scope_closed",
        "stale_generation",
        "trust_policy_missing",
        "trust_rejected",
        "unsupported_platform",
    }
)


def _passive_collection(value: object, error: str) -> tuple[object, ...]:
    """Detach one explicitly supported passive-record collection."""
    if type(value) not in (list, tuple):
        raise ValueError(error)
    return tuple(value)


def _passive_errors(value: object, error: str) -> tuple[str, ...]:
    """Validate and detach stable configured error tokens."""
    errors = _passive_collection(value, error)
    if any(type(token) is not str or token not in _CONFIGURED_ERROR_TOKENS for token in errors):
        raise ValueError(error)
    return errors


def _valid_result_header(accepted: object, generation: object) -> bool:
    """Return whether a passive result has valid scalar header fields."""
    return type(accepted) is bool and type(generation) is int and generation >= 0


def _valid_primary_errors(accepted: bool, errors: tuple[str, ...]) -> bool:
    """Return whether ordinary success or rejection has the C02 error shape."""
    return not errors if accepted else len(errors) == 1


@dataclass(frozen=True, slots=True)
class ConfiguredModuleFailure:
    """Describe one retained recognized module failure."""

    binding_id: str
    category: Literal["load_error", "invalid_entry"]

    def __post_init__(self) -> None:
        """Validate immutable module-failure scalar fields."""
        if type(self.binding_id) is not str or not self.binding_id:
            raise ValueError("invalid configured module failure")
        if type(self.category) is not str or self.category not in ("load_error", "invalid_entry"):
            raise ValueError("invalid configured module failure")


@dataclass(frozen=True, slots=True)
class ConfiguredPlanSummary:
    """Summarize one complete configured hook-point plan."""

    hook_point: str
    event_name: str
    event_version: int
    binding_ids: tuple[str, ...]
    artifact_identities: tuple[str, ...]
    module_failures: tuple[ConfiguredModuleFailure, ...] = ()

    def __post_init__(self) -> None:
        """Validate and detach one complete configured plan summary."""
        error = "invalid configured plan summary"
        binding_ids = _passive_collection(self.binding_ids, error)
        artifact_identities = _passive_collection(self.artifact_identities, error)
        failures = _passive_collection(self.module_failures, error)
        if type(self.hook_point) is not str or not self.hook_point:
            raise ValueError(error)
        if type(self.event_name) is not str or not self.event_name:
            raise ValueError(error)
        if type(self.event_version) is not int or self.event_version <= 0:
            raise ValueError(error)
        if any(type(binding_id) is not str or not binding_id for binding_id in binding_ids):
            raise ValueError(error)
        if any(
            type(identity) is not str
            or re.fullmatch(r"[0-9a-f]{64}", identity) is None
            for identity in artifact_identities
        ):
            raise ValueError(error)
        if tuple(sorted(set(artifact_identities))) != artifact_identities:
            raise ValueError(error)
        if any(type(failure) is not ConfiguredModuleFailure for failure in failures):
            raise ValueError(error)
        owned_failures = tuple(
            ConfiguredModuleFailure(failure.binding_id, failure.category)
            for failure in failures
        )
        object.__setattr__(self, "binding_ids", binding_ids)
        object.__setattr__(self, "artifact_identities", artifact_identities)
        object.__setattr__(self, "module_failures", owned_failures)


@dataclass(frozen=True, slots=True)
class PrepareConfiguredResult:
    """Report configured preparation without publishing it."""

    accepted: bool
    generation: int
    candidate: PreparedConfigured | None = None
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate and detach preparation result collections."""
        error = "invalid configured preparation result"
        if not _valid_result_header(self.accepted, self.generation):
            raise ValueError(error)
        if self.candidate is not None and type(self.candidate) is not PreparedConfigured:
            raise ValueError(error)
        errors = _passive_errors(self.errors, error)
        if not _valid_primary_errors(self.accepted, errors):
            raise ValueError(error)
        if self.accepted != (self.candidate is not None):
            raise ValueError(error)
        object.__setattr__(self, "errors", errors)


@dataclass(frozen=True, slots=True)
class PublishConfiguredResult:
    """Report configured candidate publication."""

    accepted: bool
    generation: int
    changed: bool = False
    plans: tuple[ConfiguredPlanSummary, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate and detach publication result collections."""
        error = "invalid configured publication result"
        plans = _passive_collection(self.plans, error)
        if not _valid_result_header(self.accepted, self.generation) or type(self.changed) is not bool:
            raise ValueError(error)
        if any(type(plan) is not ConfiguredPlanSummary for plan in plans):
            raise ValueError(error)
        owned_plans = tuple(
            ConfiguredPlanSummary(
                plan.hook_point,
                plan.event_name,
                plan.event_version,
                plan.binding_ids,
                plan.artifact_identities,
                plan.module_failures,
            )
            for plan in plans
        )
        point_names = tuple(plan.hook_point for plan in owned_plans)
        if point_names != tuple(sorted(set(point_names))):
            raise ValueError(error)
        errors = _passive_errors(self.errors, error)
        if not _valid_primary_errors(self.accepted, errors):
            raise ValueError(error)
        if not self.accepted and (self.changed or owned_plans):
            raise ValueError(error)
        object.__setattr__(self, "plans", owned_plans)
        object.__setattr__(self, "errors", errors)


@dataclass(frozen=True, slots=True)
class DisposeConfiguredResult:
    """Report configured candidate disposal and cleanup state."""

    accepted: bool
    generation: int
    already_disposed: bool = False
    cleanup_pending: bool = False
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate and detach disposal result collections."""
        error = "invalid configured disposal result"
        if not _valid_result_header(self.accepted, self.generation):
            raise ValueError(error)
        if type(self.already_disposed) is not bool or type(self.cleanup_pending) is not bool:
            raise ValueError(error)
        errors = _passive_errors(self.errors, error)
        if self.accepted:
            expected = ("cleanup_pending",) if self.cleanup_pending else ()
            if errors != expected:
                raise ValueError(error)
        elif len(errors) != 1 or self.already_disposed or self.cleanup_pending:
            raise ValueError(error)
        object.__setattr__(self, "errors", errors)
