"""Verify standard DEB staging selection. Author: DawsonLin."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.bdd.steps import compiled_module_discovery_steps as steps


@pytest.mark.parametrize("configured", [True, False])
def test_staging_root_is_not_built_or_removed(monkeypatch, tmp_path, configured):
    """Resolve supplied or standard staging roots without changing their files."""
    monkeypatch.setattr(steps, "DEFAULT_PACKAGED_ROOT", tmp_path)
    if configured:
        monkeypatch.setenv("TOPSAILAI_PACKAGED_ROOT", str(tmp_path))
    else:
        monkeypatch.delenv("TOPSAILAI_PACKAGED_ROOT", raising=False)
    marker = tmp_path / "artifact"
    marker.write_text("unchanged")
    assert steps.compiled_package_root.__wrapped__() == tmp_path
    assert marker.read_text() == "unchanged"


def test_source_context_does_not_request_compiler():
    """Keep the source-only gate independent of build tooling."""
    request = Mock()
    request.node.get_closest_marker.return_value = None
    fixture = steps.compiled_discovery_ctx.__wrapped__(request)
    next(fixture)
    request.getfixturevalue.assert_not_called()
    with pytest.raises(StopIteration):
        next(fixture)


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
