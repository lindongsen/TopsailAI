"""Verify automatic compiled fixture ownership. Author: DawsonLin."""

import importlib.machinery
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.bdd import compiled_package_builder as builder
from tests.bdd.steps import compiled_module_discovery_steps as steps


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    """Supply an isolated runtime tree and fake dependency launcher."""
    workspace = tmp_path / "source"
    workspace.mkdir()
    (workspace / "__init__.py").write_text("")
    (workspace / "handler.py").write_text("VALUE = 1")
    for name in (".tmp", "tests", "__pycache__"):
        (workspace / name).mkdir()
        (workspace / name / "ignored").write_text("not copied")
    root = tmp_path / "build"
    root.mkdir()
    monkeypatch.setattr(builder.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(builder, "resolve_python_interpreter", lambda: "/usr/bin/python3")
    return workspace, root, ["topsailai"], tmp_path / "build.log"


def test_success_build_removes_only_copied_sources(inputs, monkeypatch):
    """Require genuine extension inventory before publishing the copied tree."""
    workspace, root, packages, log = inputs

    def compile_copy(command, **kwargs):
        """Simulate a compiler result without mutating original source."""
        assert kwargs["cwd"] == root
        assert kwargs["env"]["TMPDIR"] == str(root / "tmp")
        assert "--no-project" in command
        assert not (root / "topsailai" / ".tmp").exists()
        assert not (root / "topsailai" / "tests").exists()
        (root / "topsailai" / ("handler" + importlib.machinery.EXTENSION_SUFFIXES[0])).touch()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(builder.subprocess, "run", compile_copy)
    assert builder.build_compiled_package(*inputs) == root
    assert (workspace / "handler.py").is_file()
    assert not (root / "topsailai" / "handler.py").exists()
    assert (root / "topsailai" / "__init__.py").is_file()
    assert "Command:" in log.read_text()


@pytest.mark.parametrize("returncode", [0, 1])
def test_failed_or_incomplete_build_keeps_source(inputs, monkeypatch, returncode):
    """Never silently publish a failed or source-only build."""
    monkeypatch.setattr(builder.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=returncode))
    with pytest.raises(RuntimeError, match="build"):
        builder.build_compiled_package(*inputs)
    assert (inputs[1] / "topsailai" / "handler.py").is_file()
    assert inputs[0].joinpath("handler.py").is_file()


def test_missing_uv_reports_build_prerequisite(inputs, monkeypatch):
    """Report a missing launcher instead of skipping acceptance."""
    monkeypatch.setattr(builder.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="uv is required"):
        builder.build_compiled_package(*inputs)


def test_explicit_root_does_not_build_or_remove(monkeypatch, tmp_path):
    """Keep externally supplied artifacts authoritative and untouched."""
    monkeypatch.setenv("TOPSAILAI_PACKAGED_ROOT", str(tmp_path))
    build = Mock(side_effect=AssertionError("unexpected build"))
    monkeypatch.setattr(steps, "build_compiled_package", build)
    fixture = steps.compiled_package_root.__wrapped__()
    assert next(fixture) == tmp_path
    with pytest.raises(StopIteration):
        next(fixture)
    build.assert_not_called()
    assert tmp_path.is_dir()


def test_build_failure_cleans_owned_directory(monkeypatch, tmp_path):
    """Ensure setup failures do not leak the session's copy or compiler cache."""
    monkeypatch.delenv("TOPSAILAI_PACKAGED_ROOT", raising=False)
    storage = steps.BDDTempStorage(tmp_path)
    monkeypatch.setattr(steps, "BDDTempStorage", lambda: storage)
    monkeypatch.setattr(steps, "build_compiled_package", Mock(side_effect=RuntimeError("compile failed")))
    fixture = steps.compiled_package_root.__wrapped__()
    with pytest.raises(RuntimeError, match="compile failed"):
        next(fixture)
    assert list(tmp_path.iterdir()) == []


def test_source_context_does_not_request_compiler():
    """Keep the source-only gate independent of build tooling."""
    request = Mock()
    request.node.get_closest_marker.return_value = None
    fixture = steps.compiled_discovery_ctx.__wrapped__(request)
    next(fixture)
    request.getfixturevalue.assert_not_called()
    with pytest.raises(StopIteration):
        next(fixture)


def test_copy_excludes_runtime_nodes_and_links(tmp_path):
    """Never follow links or copy live sockets from a developer runtime tree."""
    import socket
    node = socket.socket(socket.AF_UNIX)
    try:
        node.bind(str(tmp_path / "runtime.socket"))
        (tmp_path / "link").symlink_to(tmp_path / "absent")
        (tmp_path / "module.py").write_text("VALUE = 1")
        assert builder._ignored(str(tmp_path), ["runtime.socket", "link", "module.py"]) == {
            "runtime.socket", "link",
        }
    finally:
        node.close()


@pytest.mark.parametrize("leaked", [False, True])
def test_isolation_accepts_owned_artifacts_but_rejects_source(leaked):
    """Distinguish the required workspace temp tree from source-tree leakage."""
    root = steps.WORKSPACE / ".tmp" / "compiled-test"
    context = steps.CompiledDiscoveryContext(packaged_root=root)
    context.shared_result = {
        "package_origin": str(root / "topsailai" / "__init__.py"),
        "origins": {"handler": str(root / "handler.so")},
        "sys_path": [str(root), str(steps.WORKSPACE if leaked else Path("/usr/lib"))],
    }
    if leaked:
        with pytest.raises(AssertionError, match="source path leaked"):
            steps.then_shared_origins_are_packaged(context)
    else:
        steps.then_shared_origins_are_packaged(context)
