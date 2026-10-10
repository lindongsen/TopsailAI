"""Detached semantic records for unpublished complete Hook Points. Author: DawsonLin."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, fields
from pathlib import Path

from topsailai.hooks.artifact_contracts import ArtifactCapturePolicy, ArtifactCaptureRequest
from topsailai.hooks.artifact_structure import validate_request_structure, _valid_policy
from topsailai.hooks.contracts import ValidationError, _thaw_frozen_json, _FrozenJsonArray, _FrozenJsonObject
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


_SEMANTIC_BYTES = 2_097_152
_SEMANTIC_NODES = 131_072
_SEMANTIC_DEPTH = 24
_COLLECTION_ITEMS = 1024


def _platform(value):
    """Bound legacy platform metadata without changing its discovery API."""
    if type(value) is not ExecutablePlatformPolicy or value.platform not in ("posix", "windows"):
        raise ValidationError("invalid candidate platform policy")
    _text(value.platform)
    for values in (value.allowed_interpreters, value.native_suffixes):
        if type(values) is not tuple or len(values) > _COLLECTION_ITEMS:
            raise ValidationError("candidate platform collection limit")
        for item in values:
            _text(item)


def _canonical_digest(value, *, limit=_SEMANTIC_BYTES):
    """Hash canonical JSON incrementally with bounded tokens, depth and visits."""
    digest = hashlib.sha256(b"hook-point-plan-v1\x00")
    size, visits = 0, 0
    ancestors = set()

    def emit(token):
        """Reject before retaining a token that would exceed the aggregate budget."""
        nonlocal size
        encoded = token.encode("utf-8")
        size += len(encoded)
        if size > limit:
            raise ValidationError("candidate aggregate semantic budget")
        digest.update(encoded)

    def walk(current, depth):
        """Traverse only exact admitted JSON types, never thaw a complete tree."""
        nonlocal visits
        visits += 1
        if depth > _SEMANTIC_DEPTH or visits > _SEMANTIC_NODES:
            raise ValidationError("candidate semantic traversal limit")
        if type(current) is str:
            _text(current, empty=True)
            emit('"')
            for offset in range(0, len(current), 1024):
                emit(json.dumps(current[offset:offset + 1024], ensure_ascii=False)[1:-1])
            emit('"')
            return
        if current is None or type(current) in (bool, int, float):
            if type(current) is int and current.bit_length() > 4096:
                raise ValidationError("candidate integer limit")
            if type(current) is float and not math.isfinite(current):
                raise ValidationError("candidate nonfinite number")
            emit(json.dumps(current, ensure_ascii=False, allow_nan=False))
            return
        mapping = type(current) in (dict, _FrozenJsonObject)
        if not mapping and type(current) not in (list, tuple, _FrozenJsonArray):
            raise ValidationError("invalid candidate semantic value")
        if len(current) > _COLLECTION_ITEMS or id(current) in ancestors:
            raise ValidationError("candidate collection limit or cycle")
        ancestors.add(id(current))
        emit("{" if mapping else "[")
        values = current
        if mapping:
            for key in current:
                _text(key, empty=True)
            values = sorted(current)
        for index, item in enumerate(values):
            if index:
                emit(",")
            if mapping:
                walk(item, depth + 1)
                emit(":")
                item = current[item]
            walk(item, depth + 1)
        emit("}" if mapping else "]")
        ancestors.remove(id(current))

    walk(value, 0)
    return digest.hexdigest()


def _path_text(value):
    """Check path components before allocating their joined spelling."""
    if type(value) is not type(Path()) or len(value.parts) > _COLLECTION_ITEMS:
        raise ValidationError("invalid candidate path")
    if sum(len(part) + 1 for part in value.parts) > 32768:
        raise ValidationError("candidate path limit")
    for part in value.parts:
        _text(part, empty=True)
    result = str(value)
    _text(result)
    return result


def _configuration(name, records, configured, options, execution, capture, platform):
    """Frame bounded shallow configuration without copying nested arguments."""
    if type(options) is not HookScriptExecutionOptions or type(execution) is not HookScriptExecutionPolicy:
        raise ValidationError("invalid candidate execution configuration")
    return [1, name, records, configured,
            [options.argv, _path_text(options.cwd) if options.cwd is not None else None, options.environment],
            [getattr(execution, f.name) for f in fields(execution)],
            [getattr(capture, f.name) for f in fields(capture)],
            [platform.platform, platform.allowed_interpreters, platform.native_suffixes]]


def _preflight_configuration(name, modules, scripts, configured, options, execution, capture, platform):
    """Budget exact future inventory framing before backend/capture allocation."""
    _platform(platform)
    if type(modules) not in (list, tuple) or type(scripts) not in (list, tuple):
        raise ValidationError("invalid candidate collection")
    if len(scripts) > 128:
        raise ValidationError("invalid script source collection")
    if len(modules) + len(scripts) > 128:
        raise ValidationError("candidate inventory limit")
    if any(type(item) is not ModuleSource for item in modules):
        raise ValidationError("invalid module source record")
    from topsailai.hooks.hook_script_discovery import HookScriptEntry
    if any(type(item) is not HookScriptEntry for item in scripts):
        raise ValidationError("invalid script source record")
    for item in modules:
        _text(item.registered_name, empty=True)
    for item in scripts:
        _text(item.final_registered_name, empty=True)
    records = []
    ordered = sorted(modules, key=lambda item: item.registered_name)
    ordered += sorted(scripts, key=lambda item: item.final_registered_name)
    for index, item in enumerate(ordered):
        module = type(item) is ModuleSource
        kind = "module" if module else "script"
        alias = item.registered_name if module else item.final_registered_name
        source_path = _path_text(item.source_path)
        value = [f"{kind}-{index}", kind, alias, "0" * 64, index, source_path,
                 f"entry-{index:06d}/{item.source_path.name}", "0" * 64, "0" * 64]
        if module:
            if type(item.invocation) is not ModuleInvocation:
                raise ValidationError("invalid candidate invocation")
            value += [item.kind, item.logical_name, item.handler_ref, item.enabled,
                      item.invocation.args, item.invocation.kwargs]
        else:
            value += [item.basename]
        records.append(value)
    if type(options) is not HookScriptExecutionOptions or type(execution) is not HookScriptExecutionPolicy:
        raise ValidationError("invalid candidate execution configuration")
    if not _valid_policy(capture):
        raise ValidationError("invalid candidate capture policy")
    _canonical_digest(_configuration(name, records, configured, options, execution, capture, platform))


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
        _platform(self.platform_policy)
        if type(self.default_script_hook) is not DefaultScriptHook:
            raise ValidationError("invalid candidate terminal")
        for values, record in ((self.modules, CapturedModule), (self.default_script_hook.scripts, CapturedScript)):
            if type(values) not in (list, tuple) or len(values) > 128 or any(type(v) is not record for v in values):
                raise ValidationError("invalid candidate collection")
        _canonical_digest(_semantic(self))
        modules = _members(self.modules, CapturedModule)
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
        object.__setattr__(self, "fingerprint", _canonical_digest(_semantic(self)))


def _semantic(plan):
    """Frame canonical values, excluding randomized physical capture roots."""
    records = []
    for item in tuple(plan.modules) + tuple(plan.default_script_hook.scripts):
        value = [item.identity.id, item.identity.kind, item.identity.name, item.artifact_identity,
                 item.inventory_index, _path_text(item.source_path), item.relative_path, item.content_sha256, item.deployment_sha256]
        if type(item) is CapturedModule:
            source = item.source
            value += [source.kind, source.logical_name, source.handler_ref, source.enabled,
                      source.invocation.args, source.invocation.kwargs]
        else:
            value += [item.logical_name]
        records.append(value)
    return _configuration(plan.hook_point_name, records, plan.default_script_hook.configured,
                          plan.options, plan.execution_policy, plan.capture_policy, plan.platform_policy)
