"""Fixtures for U08 artifact lease tests."""

from __future__ import annotations

from pathlib import Path

from tests.unit.test_topsailai_hooks.artifact_capacity_helpers import _fixture
from topsailai.hooks.artifact_contracts import ArtifactCapturePolicy
from topsailai.hooks.artifact_leases import ArtifactLeaseManager
from topsailai.hooks.artifact_publication import PublicationCell, PublicationImage


def lease_fixture(tmp_path: Path, *, clock=None):
    """Create one real-filesystem manager and one trusted capture request."""
    owner, requests, _ = _fixture(tmp_path, (1,))
    root, trust = str(owner._artifact_root), owner._trust
    owner.close()
    kwargs = {} if clock is None else {"_clock": clock}
    manager = ArtifactLeaseManager(artifact_root=root, trust=trust, **kwargs)
    policy = ArtifactCapturePolicy(max_entries=1, max_file_bytes=64, max_total_bytes=64)
    return manager, requests, policy


def captured_candidate(manager, requests, policy):
    """Capture one real artifact into a fresh candidate."""
    group = manager.begin_candidate().group
    assert group is not None
    result = manager.capture(group, requests, policy=policy)
    assert result.accepted and result.lease is not None
    return group, result.lease


def activate(manager, group, generation: int = 0):
    """Activate one candidate through the single-image publication protocol."""
    expected = PublicationImage(generation, object(), ())
    cell = PublicationCell(expected)
    replacement = PublicationImage(generation + 1, object(), (group,))
    staged = manager._stage_publication(
        cell, group, expected=expected, replacement=replacement,
        old_groups=(), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    assert manager._commit_publication(staged.stage).accepted
    return cell
