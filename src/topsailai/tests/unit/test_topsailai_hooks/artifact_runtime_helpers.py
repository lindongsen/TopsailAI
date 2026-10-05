"""Runtime-isolation assertions for immutable artifact capture tests."""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

from topsailai.hooks import Binding, EventDefinition, HookRuntime, HookSettings


def assert_capture_preserves_active_runtime(
    monkeypatch, tmp_path: Path, owner, request
) -> None:
    """Keep exact Runtime state unchanged across accepted and rejected captures."""
    runtime = HookRuntime(HookSettings(), temp_root=str(tmp_path / "runtime"))
    scope = runtime.open_scope(metadata={"owner_id": "artifact-control"})
    definition = EventDefinition(
        "artifact.control", 1, {"type": "object", "properties": {}}
    )
    binding = Binding(
        "artifact-control", "artifact.control", 1,
        "topsailai.tests.unit.test_topsailai_hooks.fixture_handlers:sync_success",
    )
    registration = runtime.register(definition, binding, scope)
    assert registration.accepted and registration.handle is not None
    baseline = (
        runtime._registry.generation,
        runtime._registry.snapshot(scope.scope_id, definition.name, 1),
        runtime._settings,
        runtime._state,
        tuple(runtime._scopes),
    )
    launches: list[str] = []
    imports: list[str] = []
    real_import = importlib.import_module
    real_popen = subprocess.Popen

    def observed_import(name, *args, **kwargs):
        imports.append(name)
        return real_import(name, *args, **kwargs)

    def observed_popen(*args, **kwargs):
        launches.append("popen")
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", observed_import)
    monkeypatch.setattr(subprocess, "Popen", observed_popen)
    accepted = owner.capture((request,))
    after_success = (
        runtime._registry.generation,
        runtime._registry.snapshot(scope.scope_id, definition.name, 1),
        runtime._settings,
        runtime._state,
        tuple(runtime._scopes),
    )
    assert accepted.accepted and accepted.artifact is not None
    assert owner.dispose(accepted.artifact).accepted
    malformed = owner.capture((request, object()))
    after_malformed = (
        runtime._registry.generation,
        runtime._registry.snapshot(scope.scope_id, definition.name, 1),
        runtime._settings,
        runtime._state,
        tuple(runtime._scopes),
    )
    request.source_path.write_bytes(request.source_path.read_bytes() + b"changed")
    valid_rejected = owner.capture((request,))
    after_admission_rejection = (
        runtime._registry.generation,
        runtime._registry.snapshot(scope.scope_id, definition.name, 1),
        runtime._settings,
        runtime._state,
        tuple(runtime._scopes),
    )
    assert malformed.errors == ("invalid_artifact_request",)
    assert valid_rejected.errors == ("unsupported_artifact_closure",)
    assert baseline == after_success == after_malformed == after_admission_rejection
    assert launches == [] and imports == []
    removed = runtime.unregister(registration.handle)
    assert removed.accepted and removed.generation > baseline[0]
    runtime.close()
