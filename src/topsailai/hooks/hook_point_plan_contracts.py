"""Detached semantic records for unpublished complete Hook Points. Author: DawsonLin."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields
from pathlib import Path

from topsailai.hooks.artifact_contracts import ArtifactCapturePolicy, ArtifactCaptureRequest
from topsailai.hooks.artifact_structure import validate_request_structure, _valid_policy
from topsailai.hooks.contracts import ValidationError, _thaw_frozen_json
from topsailai.hooks.hook_script_contracts import HookScriptExecutionOptions, HookScriptExecutionPolicy
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from topsailai.hooks.module_invocation_protocol import ModuleInvocation, _main
from topsailai.hooks.result_contracts import HandlerIdentity


def _text(value, *, empty=False):
    """Validate exact UTF-8 metadata under a fixed aggregate component bound."""
    if type(value) is not str or (not empty and not value) or len(value) > 32768:
        raise ValidationError("invalid candidate metadata")
    try:
        if len(value.encode("utf-8")) > 32768:
            raise ValidationError("candidate metadata limit")
    except UnicodeEncodeError as exc:
        raise ValidationError("invalid candidate encoding") from exc


def _identity(value, kind):
    """Reconstruct identities without trusting frozen outer-record contents."""
    if type(value) is not HandlerIdentity or value.kind != kind:
        raise ValidationError("invalid candidate identity")
    _text(value.id)
    _text(value.name, empty=True)
    return HandlerIdentity(value.id, value.name, kind)


def _invocation(value):
    """Deeply reconstruct already-frozen invocation arguments."""
    if type(value) is not ModuleInvocation:
        raise ValidationError("invalid candidate invocation")
    return ModuleInvocation(_thaw_frozen_json(value.args), _thaw_frozen_json(value.kwargs))


@dataclass(frozen=True, slots=True)
class ModuleSource:
    """Keep explicit identity distinct from source and importable main reference."""
    registered_name: str
    source_path: Path = field(repr=False)
    logical_name: str
    kind: str
    handler_ref: str
    invocation: ModuleInvocation = field(default_factory=lambda: ModuleInvocation((), {}))
    enabled: bool = True

    def __post_init__(self):
        """Validate resource-free structure and reconstruct nested invocation."""
        _text(self.registered_name, empty=True)
        if self.registered_name == "hook_script" or self.kind not in ("python_source", "python_extension"):
            raise ValidationError("invalid module candidate kind or reserved name")
        if not validate_request_structure(ArtifactCaptureRequest(self.source_path, self.kind, self.logical_name)):
            raise ValidationError("invalid module candidate source")
        _main(self.handler_ref)
        if self.handler_ref.split(":")[0].split(".")[-1] != self.logical_name:
            raise ValidationError("uncorrelated module reference")
        if type(self.enabled) is not bool:
            raise ValidationError("invalid module enabled flag")
        object.__setattr__(self, "invocation", _invocation(self.invocation))


@dataclass(frozen=True, slots=True)
class CapturedScript:
    """Associate one explicit Script identity with an exact sealed inventory item."""
    identity: HandlerIdentity
    artifact_identity: str
    inventory_index: int
    source_path: Path = field(repr=False)
    logical_name: str
    relative_path: str
    captured_path: Path = field(repr=False)
    content_sha256: str
    deployment_sha256: str

    def __post_init__(self):
        """Validate host locator correlation without granting new source authority."""
        object.__setattr__(self, "identity", _identity(self.identity, "script"))
        _locator(self)
        if not validate_request_structure(ArtifactCaptureRequest(
            self.source_path, "script", self.logical_name,
            _SCRIPT_STRUCTURE_POLICY,
        )):
            raise ValidationError("invalid captured script source")


_SCRIPT_STRUCTURE_POLICY = ExecutablePlatformPolicy("posix")


def _locator(value):
    """Reject traversal, fabricated index spelling and malformed digest metadata."""
    if type(value.inventory_index) is not int or not 0 <= value.inventory_index < 128:
        raise ValidationError("invalid inventory index")
    for digest in (value.artifact_identity, value.content_sha256, value.deployment_sha256):
        if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValidationError("invalid candidate digest")
    if type(value.source_path) is not type(Path()) or type(value.captured_path) is not type(Path()):
        raise ValidationError("invalid candidate locator type")
    relative = Path(value.relative_path) if type(value.relative_path) is str else Path()
    expected = f"entry-{value.inventory_index:06d}/{value.source_path.name}"
    if value.relative_path != expected or relative.is_absolute() or ".." in relative.parts:
        raise ValidationError("invalid indexed locator")
    if not value.captured_path.is_absolute() or tuple(value.captured_path.parts[-2:]) != relative.parts:
        raise ValidationError("uncorrelated candidate locator")


@dataclass(frozen=True, slots=True)
class CapturedModule:
    """Retain sealed Module address and detached invocation, never a path:main ref."""
    identity: HandlerIdentity
    source: ModuleSource
    artifact_identity: str
    inventory_index: int
    relative_path: str
    captured_path: Path = field(repr=False)
    content_sha256: str
    deployment_sha256: str

    @property
    def source_path(self):
        """Expose original host-only source identity without reopening it."""
        return self.source.source_path

    @property
    def invocation(self):
        """Return the immutable semantic invocation."""
        return self.source.invocation

    def __post_init__(self):
        """Reconstruct source and require alias correlation."""
        identity = _identity(self.identity, "module")
        if type(self.source) is not ModuleSource:
            raise ValidationError("invalid captured module source")
        source = ModuleSource(**{f.name: getattr(self.source, f.name) for f in fields(ModuleSource)})
        if identity.name != source.registered_name:
            raise ValidationError("uncorrelated registered alias")
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "source", source)
        _locator(self)


def _members(values, record):
    """Bound, reconstruct and validate deterministic same-kind identity order."""
    if type(values) not in (list, tuple) or len(values) > 128:
        raise ValidationError("invalid candidate collection")
    result = []
    for value in values:
        if type(value) is not record:
            raise ValidationError("invalid candidate member")
        result.append(record(**{f.name: getattr(value, f.name) for f in fields(record)}))
    names = tuple(value.identity.name for value in result)
    if names != tuple(sorted(names)) or len(set(names)) != len(names):
        raise ValidationError("duplicate or unordered registered names")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class DefaultScriptHook:
    """Describe the mandatory unique terminal, including an empty Script batch."""
    scripts: tuple[CapturedScript, ...]
    configured: bool = False
    identity: HandlerIdentity = field(default_factory=lambda: HandlerIdentity("hook_script", "hook_script", "default_script_hook"))

    def __post_init__(self):
        """Detach Scripts and forbid replacement of reserved terminal identity."""
        identity = _identity(self.identity, "default_script_hook")
        if (identity.id, identity.name) != ("hook_script", "hook_script") or type(self.configured) is not bool:
            raise ValidationError("invalid default terminal")
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "scripts", _members(self.scripts, CapturedScript))


def _execution(options, policy):
    """Detach execution configuration without changing the legacy adapter limits."""
    if type(options) is not HookScriptExecutionOptions or type(policy) is not HookScriptExecutionPolicy:
        raise ValidationError("invalid candidate execution configuration")
    if type(options.argv) not in (tuple, list) or len(options.argv) > 1024:
        raise ValidationError("invalid candidate argv")
    for item in options.argv:
        _text(item, empty=True)
    if options.cwd is not None and (type(options.cwd) is not type(Path()) or not options.cwd.is_absolute()):
        raise ValidationError("invalid candidate cwd")
    if type(options.environment) not in (tuple, list) or len(options.environment) > 1024:
        raise ValidationError("invalid candidate environment")
    pairs = []
    for pair in options.environment:
        if type(pair) not in (tuple, list) or len(pair) != 2:
            raise ValidationError("invalid environment pair")
        _text(pair[0])
        _text(pair[1], empty=True)
        if "=" in pair[0] or "\x00" in pair[0] + pair[1]:
            raise ValidationError("invalid environment content")
        pairs.append(tuple(pair))
    if len({pair[0] for pair in pairs}) != len(pairs):
        raise ValidationError("duplicate environment key")
    for f in fields(policy):
        value = getattr(policy, f.name)
        if type(value) is not int or not 1 <= value <= 67_108_864:
            raise ValidationError("invalid candidate execution policy")
    return HookScriptExecutionOptions(tuple(options.argv), options.cwd, tuple(pairs)), HookScriptExecutionPolicy(**{f.name: getattr(policy, f.name) for f in fields(policy)})


@dataclass(frozen=True, slots=True)
class HookPointPlan:
    """Hold one complete detached unpublished semantic snapshot."""
    hook_point_name: str
    modules: tuple[CapturedModule, ...]
    default_script_hook: DefaultScriptHook
    options: HookScriptExecutionOptions = field(default_factory=HookScriptExecutionOptions)
    execution_policy: HookScriptExecutionPolicy = field(default_factory=HookScriptExecutionPolicy)
    capture_policy: ArtifactCapturePolicy = field(default_factory=ArtifactCapturePolicy)
    schema_version: int = 1
    platform_policy: ExecutablePlatformPolicy = field(default_factory=lambda: ExecutablePlatformPolicy("posix"))
    fingerprint: str = field(init=False)

    @property
    def handlers(self):
        """Return Modules first and exactly one terminal default Hook."""
        return self.modules + (self.default_script_hook,)

    def __post_init__(self):
        """Deeply detach all records and correlate one complete indexed inventory."""
        _text(self.hook_point_name)
        if type(self.schema_version) is not int or self.schema_version != 1 or not _valid_policy(self.capture_policy):
            raise ValidationError("invalid candidate schema or capture policy")
        if type(self.platform_policy) is not ExecutablePlatformPolicy:
            raise ValidationError("invalid candidate platform policy")
        modules = _members(self.modules, CapturedModule)
        if type(self.default_script_hook) is not DefaultScriptHook:
            raise ValidationError("invalid candidate terminal")
        terminal = DefaultScriptHook(self.default_script_hook.scripts, self.default_script_hook.configured, self.default_script_hook.identity)
        options, policy = _execution(self.options, self.execution_policy)
        items = modules + terminal.scripts
        ids = tuple(item.identity.id for item in items) + (terminal.identity.id,)
        if len(items) > self.capture_policy.max_entries or len(set(ids)) != len(ids):
            raise ValidationError("candidate inventory or identity limit")
        if tuple(item.inventory_index for item in items) != tuple(range(len(items))):
            raise ValidationError("uncorrelated candidate indexes")
        if len({item.artifact_identity for item in items}) > 1 or len({item.source_path for item in items}) != len(items):
            raise ValidationError("uncorrelated candidate inventory")
        if len({item.captured_path.parent.parent for item in items}) > 1:
            raise ValidationError("uncorrelated capture root")
        object.__setattr__(self, "modules", modules)
        object.__setattr__(self, "default_script_hook", terminal)
        object.__setattr__(self, "options", options)
        object.__setattr__(self, "execution_policy", policy)
        semantic = _semantic(self)
        encoded = json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 2_097_152:
            raise ValidationError("candidate aggregate semantic budget")
        object.__setattr__(self, "fingerprint", hashlib.sha256(b"hook-point-plan-v1\x00" + encoded).hexdigest())


def _semantic(plan):
    """Frame canonical values, excluding randomized physical capture roots."""
    records = []
    for item in plan.modules + plan.default_script_hook.scripts:
        value = [item.identity.id, item.identity.kind, item.identity.name, item.artifact_identity,
                 item.inventory_index, str(item.source_path), item.relative_path, item.content_sha256, item.deployment_sha256]
        if type(item) is CapturedModule:
            source = item.source
            value += [source.kind, source.logical_name, source.handler_ref, source.enabled,
                      _thaw_frozen_json(source.invocation.args), _thaw_frozen_json(source.invocation.kwargs)]
        else:
            value += [item.logical_name]
        records.append(value)
    return [plan.schema_version, plan.hook_point_name, records, plan.default_script_hook.configured,
            [list(plan.options.argv), str(plan.options.cwd) if plan.options.cwd is not None else None,
             list(plan.options.environment)],
            [getattr(plan.execution_policy, f.name) for f in fields(plan.execution_policy)],
            [getattr(plan.capture_policy, f.name) for f in fields(plan.capture_policy)],
            [plan.platform_policy.platform, list(plan.platform_policy.allowed_interpreters), list(plan.platform_policy.native_suffixes)]]
