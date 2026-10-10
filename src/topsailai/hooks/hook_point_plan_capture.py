"""One bounded sealed inventory to complete unpublished candidate. Author: DawsonLin."""
from __future__ import annotations

import time
from dataclasses import fields

from topsailai.hooks.artifact_contracts import ArtifactCapturePolicy, ArtifactCaptureRequest
from topsailai.hooks.artifact_store import ArtifactCaptureOwner
from topsailai.hooks.artifact_structure import validate_capture_call, validate_capture_trust_structure, valid_root_spelling
from topsailai.hooks.contracts import ValidationError
from topsailai.hooks.hook_script_contracts import HookScriptExecutionOptions, HookScriptExecutionPolicy
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy, HookScriptDiscoveryResult, HookScriptEntry
from topsailai.hooks.hook_point_plan_contracts import (
    ModuleSource, CapturedModule, CapturedScript, DefaultScriptHook, HookPointPlan, _text, _execution, _preflight_configuration,
)
from topsailai.hooks.hook_point_plan_ownership import HookPointCandidate, CandidateBuildError
from topsailai.hooks.module_discovery_probe import probe_candidate
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.result_contracts import HandlerIdentity


def _inputs(hook_name, modules, discovery, platform, trust, artifact_root, backend, policy, deadline, options, execution_policy):
    """Admit and detach all inputs before any capture or child side effects."""
    _text(hook_name)
    if type(modules) not in (list, tuple) or len(modules) > 128:
        raise ValidationError("invalid module source collection")
    if discovery is not None and (type(discovery) is not HookScriptDiscoveryResult or discovery.accepted is not True or discovery.errors):
        raise ValidationError("invalid script discovery")
    _preflight_configuration(hook_name, modules, () if discovery is None else discovery.entries,
        discovery is not None, options, execution_policy, policy, platform)
    owned = []
    for item in modules:
        owned.append(ModuleSource(**{f.name: getattr(item, f.name) for f in fields(ModuleSource)}))
    owned.sort(key=lambda item: item.registered_name)
    raw = () if discovery is None else discovery.entries
    scripts = []
    for item in raw:
        _text(item.final_registered_name, empty=True)
        scripts.append(HookScriptEntry(item.source_path, item.basename, item.registered_name))
    scripts.sort(key=lambda item: item.final_registered_name)
    for names in (tuple(item.registered_name for item in owned), tuple(item.final_registered_name for item in scripts)):
        if len(set(names)) != len(names):
            raise ValidationError("duplicate registered name")
    requests = tuple(ArtifactCaptureRequest(item.source_path, item.kind, item.logical_name) for item in owned)
    requests += tuple(ArtifactCaptureRequest(item.source_path, "script", item.basename, platform) for item in scripts)
    token = validate_capture_call(requests, policy, None, deadline)
    if token is not None or len(requests) > policy.max_entries or len({r.source_path for r in requests}) != len(requests):
        raise ValidationError(token or "invalid candidate inventory")
    if not validate_capture_trust_structure(trust) or not valid_root_spelling(artifact_root):
        raise ValidationError("invalid candidate authority")
    if type(backend) is not IsolatedProcessBackend:
        raise ValidationError("invalid candidate backend")
    backend = IsolatedProcessBackend(
        temp_root=backend.script_temp_root, protocol_limits=backend._limits,
        output_limit_bytes=backend._output_limit,
        cleanup_grace_ms=round(backend._cleanup_grace * 1000),
        interpreter=backend._interpreter, worker_module=backend._worker_module)
    if owned and (trust.python_runtime is None
            or backend._resolve_interpreter() != str(trust.python_runtime.executable)
            or backend._worker_module != "topsailai.hooks.worker"):
        raise ValidationError("untrusted probe runtime")
    options, execution_policy = _execution(options, execution_policy)
    return tuple(owned), tuple(scripts), requests, options, execution_policy, backend


def _checkpoint(deadline):
    """Check the same absolute deadline on each side of blocking work."""
    if time.monotonic() >= deadline:
        raise ValueError("candidate_deadline")


def _probe(candidate, item, path, hook_name, deadline):
    """Probe only captured bytes while journaling exact newly-created debts."""
    backend = candidate._backend
    _checkpoint(deadline)
    try:
        entry, result = probe_candidate(backend, path.parent, hook_name, item.logical_name, path,
            max(1, min(5000, int((deadline - time.monotonic()) * 1000))))
    finally:
        candidate._probe_debts.update(d.debt_id for d in backend.cleanup_debts())
    _checkpoint(deadline)
    if not result.cleanup_confirmed or candidate._probe_debts:
        raise ValueError("probe_cleanup_pending")
    if (result.status != "success" or type(result.value) is not dict
            or set(result.value) != {"load_status", "entry_valid"}
            or result.value["load_status"] != "ready" or result.value["entry_valid"] is not True
            or entry.load_status != "ready" or entry.entry_valid is not True):
        raise ValueError("module_probe_rejected")
    if entry.source_path != path or entry.logical_name != item.logical_name or entry.entry_name != "main":
        raise ValueError("uncorrelated_probe_manifest")


def build_hook_point_candidate(hook_name, *, modules=(), script_discovery=None,
        platform_policy, trust, artifact_root, probe_backend, policy=ArtifactCapturePolicy(),
        deadline=None, options=HookScriptExecutionOptions(), execution_policy=HookScriptExecutionPolicy()):
    """Return one complete unpublished candidate or raise with exact recovery owner."""
    modules, scripts, requests, options, execution_policy, backend = _inputs(hook_name, modules, script_discovery,
        platform_policy, trust, artifact_root, probe_backend, policy, deadline, options, execution_policy)
    absolute = time.monotonic() + policy.timeout_ms / 1000
    if deadline is not None:
        absolute = min(absolute, deadline)
    candidate = HookPointCandidate(backend)
    try:
        _checkpoint(absolute)
        if not requests:
            candidate._plan = HookPointPlan(hook_name, (), DefaultScriptHook((), script_discovery is not None),
                options, execution_policy, policy, platform_policy=platform_policy)
            return candidate
        candidate._capture_owner = ArtifactCaptureOwner(artifact_root=artifact_root, trust=trust)
        captured = candidate._capture_owner.capture(requests, policy=policy, deadline=absolute)
        _checkpoint(absolute)
        if not captured.accepted or captured.artifact is None:
            raise ValueError(captured.errors[0] if captured.errors else "capture_rejected")
        artifact = captured.artifact
        if len(artifact.entries) != len(requests):
            raise ValueError("uncorrelated_capture_inventory")
        module_records, script_records = [], []
        for index, (request, entry) in enumerate(zip(requests, artifact.entries, strict=True)):
            _checkpoint(absolute)
            if (entry.index, entry.kind, entry.logical_name, entry.validation.source_path) != (
                    index, request.kind, request.logical_name, request.source_path):
                raise ValueError("uncorrelated_capture_inventory")
            path = artifact.directory / entry.relative_path
            if index < len(modules):
                item = modules[index]
                _probe(candidate, item, path, hook_name, absolute)
                module_records.append(CapturedModule(HandlerIdentity(f"module-{index}", item.registered_name, "module"),
                    item, artifact.identity, index, entry.relative_path, path, entry.content_sha256, entry.validation.deployment_sha256))
            else:
                item = scripts[index - len(modules)]
                script_records.append(CapturedScript(HandlerIdentity(f"script-{index}", item.final_registered_name, "script"),
                    artifact.identity, index, item.source_path, item.basename, entry.relative_path, path,
                    entry.content_sha256, entry.validation.deployment_sha256))
        plan = HookPointPlan(hook_name, tuple(module_records),
            DefaultScriptHook(tuple(script_records), script_discovery is not None), options, execution_policy, policy,
            platform_policy=platform_policy)
        _checkpoint(absolute)
        candidate._plan = plan
        return candidate
    except BaseException as primary:
        try:
            candidate.close()
        except BaseException as cleanup:
            if not isinstance(cleanup, Exception) and isinstance(primary, Exception):
                cleanup.recovery_owner = candidate
                raise
            primary.add_note("candidate cleanup failed: " + type(cleanup).__name__)
        if not isinstance(primary, Exception):
            primary.recovery_owner = candidate
            raise
        raise CandidateBuildError(str(primary), candidate) from primary
