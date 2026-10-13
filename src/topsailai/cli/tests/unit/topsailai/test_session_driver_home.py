"""Regressions for deployment HOME aliases and no-follow metadata custody.

Author: DawsonLin
All fixtures live under pytest's workspace-scoped temporary base.
"""

import json

import pytest

from cli_topsailai import session_driver as sd


def make_metadata(home):
    """Write valid evidence in a test-owned canonical HOME subtree."""
    path = home / "workspace" / "task" / "session_agent_driver" / "team.meta"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dict(version=1, session_id="team", pid=123,
                                   run_id="a" * 32, status="running")))
    return path


def observe(home):
    """Read filesystem evidence without probing or signaling real processes."""
    return sd.observe_driver(home, "team", process_probe=lambda _: sd.ProcessEvidence.VERIFIED)


def test_nested_home_aliases(tmp_path):
    """Resolve aliases both at HOME and in the link target's ancestors."""
    physical = tmp_path / "physical"
    physical.mkdir()
    make_metadata(physical / "hosts" / ".topsailai")
    work = tmp_path / "work"
    work.symlink_to(physical, target_is_directory=True)
    home = tmp_path / ".topsailai"
    home.symlink_to(work / "hosts" / ".topsailai", target_is_directory=True)
    result = observe(home)
    assert result.state == "ON"
    assert result.driver_pid == 123
    assert sd.metadata_path(home, "team") == physical / "hosts" / ".topsailai" / "workspace" / "task" / "session_agent_driver" / "team.meta"


@pytest.mark.parametrize("component", ["workspace", "task", "session_agent_driver"])
def test_untrusted_descendant_alias(tmp_path, component):
    """Never normalize a symlink within the metadata-owned subtree."""
    home = tmp_path / "home"
    path = make_metadata(home)
    subtree = next(parent for parent in path.parents if parent.name == component)
    relocated = tmp_path / "untrusted"
    subtree.rename(relocated)
    subtree.symlink_to(relocated, target_is_directory=True)
    assert observe(home).state == "?"


def test_metadata_alias_under_home_alias(tmp_path):
    """Accept the deployment alias without following a metadata-file alias."""
    physical = tmp_path / "physical"
    path = make_metadata(physical)
    original = path.with_suffix(".original")
    path.rename(original)
    path.symlink_to(original)
    home = tmp_path / "home"
    home.symlink_to(physical, target_is_directory=True)
    result = observe(home)
    assert result.state == "?"
    assert result.reason == "metadata_not_regular"


def test_canonical_root_substitution(tmp_path):
    """Reject a root symlink substituted after HOME normalization."""
    home = tmp_path / "home"
    make_metadata(home)
    path = sd.metadata_path(home, "team")
    other = tmp_path / "other"
    home.rename(other)
    home.symlink_to(other, target_is_directory=True)
    with pytest.raises(OSError):
        sd._read_metadata(path)


def test_physical_home_unchanged(tmp_path):
    """Preserve reads and exact paths for ordinary non-aliased installations."""
    home = tmp_path / "home"
    path = make_metadata(home)
    before = path.read_bytes(), path.stat().st_mtime_ns
    assert sd.metadata_path(home, "team") == path
    assert observe(home).state == "ON"
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
