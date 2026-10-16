"""Integration evidence for prepared application-owned Hook resources."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from topsailai.hooks import (
    ArtifactPythonRuntimeAuthority,
    ConfiguredHookPoint,
    ConfiguredHooks,
    ConfiguredTrustPolicy,
    EventDefinition,
    HookSettings,
)
from topsailai.hooks.application_access import get_hook_executor
from topsailai.hooks.configured_contracts import ArtifactClosureAssertion, SummaryPreparationRequest
from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration
from topsailai.hooks.configured_executor import HookOperation
from topsailai.hooks.artifact_identity import python_runtime_fingerprint
from tests.legacy_prepared_support import prepared_graph
from topsailai.hooks.application_access import HookApplicationAccess, bind_hook_application


_POINT_NAMES = (
    "hook__inventory__before__refresh",
    "hook__inventory__before__broken",
    "hook__inventory__before__disabled",
)


def _point(name: str) -> HookPointDeclaration:
    """Build one metadata-only non-Summary declaration."""
    return HookPointDeclaration(
        name,
        EventDefinition(name, 1, {"type": "object", "properties": {"count": {"type": "integer"}}}),
        "before",
        "sync",
        "inventory",
    )


def _runtime_authority() -> ArtifactPythonRuntimeAuthority:
    """Capture the exact interpreter identity accepted by prepared workers."""
    executable = Path(sys.executable).resolve(strict=True)
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    return ArtifactPythonRuntimeAuthority(executable, digest)


def _source_assertion(source: Path, logical_name: str, authority: ArtifactPythonRuntimeAuthority) -> ArtifactClosureAssertion:
    """Create deployment-owned source and interpreter closure evidence."""
    executable = authority.executable
    status = executable.stat()
    runtime_digest = python_runtime_fingerprint(
        executable,
        authority.content_sha256,
        device=status.st_dev,
        inode=status.st_ino,
    )
    return ArtifactClosureAssertion(
        source,
        "python_source",
        logical_name,
        hashlib.sha256(source.read_bytes()).hexdigest(),
        runtime_digest,
        "0" * 64,
    )


def _prepared_inputs(root: Path) -> tuple[SummaryPreparationRequest, ConfiguredTrustPolicy, HookPointDeclaration]:
    """Create a complete typed prepared request and explicit deployment authority."""
    sources = root / "sources"
    runtime_root = root / "runtime"
    sources.mkdir(mode=0o700, parents=True)
    runtime_root.mkdir(mode=0o700)
    authority = _runtime_authority()
    points = tuple(_point(name) for name in _POINT_NAMES)
    catalog = HookPointCatalog(points)
    folders = {}
    assertions = []
    for name in _POINT_NAMES:
        folder = sources / name
        folder.mkdir(mode=0o700)
        folders[name] = folder
        source = folder / "worker.py"
        source.write_text(
            "def main(*, hook_context):\n"
            "    return {'operation_id': hook_context['operation_id'],\n"
            "            'payload': dict(hook_context['payload'])}\n",
            encoding="utf-8",
        )
        if name != _POINT_NAMES[1]:
            assertions.append(_source_assertion(source, "worker", authority))
    configuration = ConfiguredHooks(
        tuple(
            ConfiguredHookPoint(
                name,
                catalog.require(name).definition,
                module_folder=folders[name],
                inject_hook_context=True,
            )
            for name in _POINT_NAMES
        ),
        HookSettings(),
    )
    request = SummaryPreparationRequest(
        configuration,
        catalog,
        frozenset({_POINT_NAMES[2]}),
    )
    trust = ConfiguredTrustPolicy(
        (sources,),
        closure_assertions=tuple(assertions),
        python_runtime=authority,
    )
    return request, trust, catalog.require(_POINT_NAMES[0])


def test_real_prepared_application_executes_and_reports_sibling_dispositions(tmp_path):
    """Eagerly prepare a real Module, retain valid siblings, and report failures safely."""
    request, trust, valid_point = _prepared_inputs(tmp_path / "owned")
    app = prepared_graph(request=request, trust_policy=trust, temp_root=str(tmp_path / "owned" / "runtime"))
    report = app.startup_report
    assert report.ready
    dispositions = {item.hook_name: item for item in report.dispositions}
    assert dispositions[_POINT_NAMES[0]].kind == "registered"
    assert dispositions[_POINT_NAMES[1]].kind == "unavailable_preparation_failure"
    assert dispositions[_POINT_NAMES[1]].reason in {"artifact_rejected", "discovery_rejected"}
    assert dispositions[_POINT_NAMES[2]].kind == "disabled_by_configuration"

    with bind_hook_application(HookApplicationAccess(app.executor)):
        access = get_hook_executor()
        result = access.dispatch(valid_point, payload={"count": 3}, operation=HookOperation("prepared-1"))
        assert result.rejection_reason is None
        handlers = result.unified_result.handlers
        assert [item.handler.kind for item in handlers] == ["module", "default_script_hook"]
        assert all(item.status == "success" and item.cleanup.state == "safe" for item in handlers)
        assert handlers[0].returned.value == {
            "operation_id": "prepared-1",
            "payload": {"count": 3},
        }
        assert app.registrar.state(_POINT_NAMES[0]).value == "ready"
    assert app.close().fully_closed
    assert get_hook_executor()._binding is None


def test_separate_prepared_applications_do_not_share_resources(tmp_path):
    """Independent typed applications own distinct Runtime and Scope graphs."""
    first_request, first_trust, _ = _prepared_inputs(tmp_path / "first")
    second_request, second_trust, _ = _prepared_inputs(tmp_path / "second")
    first = prepared_graph(request=first_request, trust_policy=first_trust, temp_root=str(tmp_path / "first" / "runtime"))
    second = prepared_graph(request=second_request, trust_policy=second_trust, temp_root=str(tmp_path / "second" / "runtime"))
    try:
        assert first.runtime is not second.runtime
        assert first.scope is not second.scope
        assert first.executor is not second.executor
        assert sum(d.kind == "registered" for d in first.startup_report.dispositions) == sum(d.kind == "registered" for d in second.startup_report.dispositions) == 1
    finally:
        assert first.close().fully_closed
        assert second.close().fully_closed



def test_prepared_application_shares_graph_and_cached_access_stops_without_forwarding(tmp_path, monkeypatch):
    """Two operations share one graph; cached access rejects after admission stops."""
    request, trust, valid_point = _prepared_inputs(tmp_path / "shared")
    app = prepared_graph(request=request, trust_policy=trust, temp_root=str(tmp_path / "shared" / "runtime"))
    forwarded = []
    original_dispatch = app.executor.dispatch
    monkeypatch.setattr(app.executor, "dispatch", lambda *args, **kwargs: (
        forwarded.append(kwargs["operation"].operation_id), original_dispatch(*args, **kwargs)
    )[1])
    access_binding = HookApplicationAccess(app.executor)
    try:
        with bind_hook_application(access_binding):
            cached_access = get_hook_executor()
            first = cached_access.dispatch(valid_point, payload={"count": 1}, operation=HookOperation("session-1"))
            second = cached_access.dispatch(valid_point, payload={"count": 2}, operation=HookOperation("session-2"))
            assert first.rejection_reason is None and second.rejection_reason is None
            assert forwarded == ["session-1", "session-2"]
            assert app.executor._runtime is app.runtime
            assert app.executor._scope is app.scope
            assert app.executor._registrar is app.registrar
            access_binding.stop_admission()
            stopped = cached_access.dispatch(valid_point, payload={"count": 3}, operation=HookOperation("session-3"))
            assert stopped.rejection_reason == "application_closed"
            assert forwarded == ["session-1", "session-2"]
    finally:
        app.close()
