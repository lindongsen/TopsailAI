"""Optional summary Script source selection contracts. Author: DawsonLin."""

from pathlib import Path

import pytest

from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from topsailai.hooks.points.catalog import PHASE_ONE_DECLARATIONS, PHASE_TWO_DECLARATIONS
from topsailai.workspace.summary_hooks_owner import build_summary_preparation_request

POLICY = ExecutablePlatformPolicy("posix")


def script_path(root, point):
    """Return the fixed point-local path, not a discovered member inventory."""
    return root / point.name.removeprefix("hook__context__").replace("__", "_") / "scripts"


def test_default_never_probes_scripts(tmp_path, monkeypatch):
    """Existing Script paths cannot implicitly enable execution."""
    script_path(tmp_path, PHASE_ONE_DECLARATIONS[0]).mkdir(parents=True)
    monkeypatch.setattr(Path, "lstat", lambda *a: pytest.fail("Script probe"))
    request = build_summary_preparation_request(points_root=tmp_path)
    assert all(point.script is None for point in request.configuration.hook_points)


def test_opt_in_phase_mapping_and_disabled_no_probe(tmp_path, monkeypatch):
    """Exactly enabled phase-one paths are observed, with no member enumeration."""
    disabled = frozenset({PHASE_ONE_DECLARATIONS[0].name})
    observed = []
    def observe(path):
        """Record a named-path observation without reading sources."""
        observed.append(path)
        return object()
    monkeypatch.setattr(Path, "lstat", observe)
    monkeypatch.setattr(Path, "iterdir", lambda *a: pytest.fail("enumeration"))
    request = build_summary_preparation_request(points_root=tmp_path,
        script_platform_policy=POLICY, disabled_hook_names=disabled)
    assert request.disabled_hook_names == disabled
    assert len(request.configuration.hook_points) == 8
    assert observed == [script_path(tmp_path, p) for p in PHASE_ONE_DECLARATIONS if p.name not in disabled]
    assert not set(observed) & {script_path(tmp_path, p) for p in PHASE_TWO_DECLARATIONS}
    for point in request.configuration.hook_points:
        assert point.inject_hook_context and not point.module_args and not point.module_kwargs
        assert point.module_folder.name == "modules"
        if point.hook_name in disabled:
            assert point.script is None
        else:
            assert point.script.target == point.module_folder.parent / "scripts"
            assert point.script.platform_policy == POLICY


@pytest.mark.parametrize("kind", ["absent", "empty", "file", "dangling"])
def test_optional_path_states(tmp_path, kind):
    """Invalid present paths are retained for authoritative preparation validation."""
    target = script_path(tmp_path, PHASE_ONE_DECLARATIONS[0])
    target.parent.mkdir()
    if kind == "empty":
        target.mkdir()
    elif kind == "file":
        target.write_text("not executable")
    elif kind == "dangling":
        target.symlink_to(target.parent / "missing")
    request = build_summary_preparation_request(points_root=tmp_path, script_platform_policy=POLICY)
    selected = request.configuration.hook_points[0].script
    assert (selected is None) == (kind == "absent")
    if selected is not None:
        assert selected.target == target


@pytest.mark.parametrize("error", [PermissionError("denied"), OSError("observation"),
    KeyboardInterrupt("stop"), SystemExit("stop")])
def test_observation_failure_identity(tmp_path, monkeypatch, error):
    """Only named-path absence is optional; other failures propagate unchanged."""
    def fail(path):
        """Raise the exact injected observation failure."""
        raise error
    monkeypatch.setattr(Path, "lstat", fail)
    with pytest.raises(type(error)) as caught:
        build_summary_preparation_request(points_root=tmp_path, script_platform_policy=POLICY)
    assert caught.value is error


@pytest.mark.parametrize("policy", [False, "posix", object(),
    ExecutablePlatformPolicy("windows"), ExecutablePlatformPolicy("posix", native_suffixes=(".bin",))])
def test_unsupported_policy_rejected_before_io(tmp_path, monkeypatch, policy):
    """Policy opt-in never grants native or unsupported-platform authority."""
    monkeypatch.setattr(Path, "lstat", lambda *a: pytest.fail("policy I/O"))
    with pytest.raises(ValueError, match="POSIX shebang-only"):
        build_summary_preparation_request(points_root=tmp_path, script_platform_policy=policy)


def test_request_observation_is_not_membership_snapshot(tmp_path):
    """Absent selection changes only on request rebuild; selected disappearance stays configured."""
    first = build_summary_preparation_request(points_root=tmp_path, script_platform_policy=POLICY)
    target = script_path(tmp_path, PHASE_ONE_DECLARATIONS[0])
    target.mkdir(parents=True)
    second = build_summary_preparation_request(points_root=tmp_path, script_platform_policy=POLICY)
    print(f"Deleted test-owned directory: {target}")
    target.rmdir()
    assert first.configuration.hook_points[0].script is None
    assert second.configuration.hook_points[0].script.target == target
    assert build_summary_preparation_request(points_root=tmp_path,
        script_platform_policy=POLICY).configuration.hook_points[0].script is None
