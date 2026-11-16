"""Tests for the launch-log reclaim sweep that runs when a supervisor exits.

The launch log is a CLI artifact: the detached supervisor creates it and relays
the launcher console stream into it. Its lifecycle therefore belongs to the CLI
process that owns it, so the sweep runs in ``_supervise``'s ``finally`` block
instead of in the agent core.

Every fixture below builds a ``{home}/workspace/task`` layout so the sweep
resolves its own home from the directory instead of reading the environment,
and so no test can reach the real agent home.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import pytest

import cli_topsailai.agent_launch_background as bg
from cli_topsailai import cleaning

#: Age comfortably beyond the 72-hour retention window.
OLD_AGE_SECONDS = cleaning.EXPIRED_AGE_SECONDS + 3600


@pytest.fixture
def task_dir(tmp_path):
    """Create an isolated ``{home}/workspace/task`` directory."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    return directory


def _make_log(task_dir: Path, name: str, *, age_seconds: float = OLD_AGE_SECONDS) -> Path:
    """Create a launch log whose mtime is *age_seconds* in the past."""
    path = task_dir / name
    path.write_text("console output\n", encoding="utf-8")
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))
    return path


def _write_lease(log_path: Path, payload: dict) -> Path:
    """Write a lease sidecar next to *log_path*."""
    lease = bg.active_launch_lease(log_path)
    lease.write_text(json.dumps(payload), encoding="utf-8")
    return lease


@pytest.fixture(autouse=True)
def no_open_descriptor_scan(monkeypatch):
    """Answer the open-descriptor check locally instead of scanning ``/proc``."""
    monkeypatch.setattr(cleaning, "is_file_in_use", lambda path: False)


class TestReclaimExpiredLaunchLogs:
    """Behaviour of ``_reclaim_expired_launch_logs``."""

    def test_expired_unleased_log_is_removed(self, task_dir):
        path = _make_log(task_dir, "wa-old.agent-launch.log")

        removed = bg._reclaim_expired_launch_logs(task_dir)

        assert removed == [str(path)]
        assert not path.exists()

    def test_rotation_backup_is_removed(self, task_dir):
        path = _make_log(task_dir, "wa-old.agent-launch.log.1")

        removed = bg._reclaim_expired_launch_logs(task_dir)

        assert removed == [str(path)]
        assert not path.exists()

    def test_young_log_is_kept(self, task_dir):
        path = _make_log(task_dir, "wa-new.agent-launch.log", age_seconds=60)

        removed = bg._reclaim_expired_launch_logs(task_dir)

        assert removed == []
        assert path.exists()

    def test_lease_without_owner_evidence_keeps_the_log(self, task_dir):
        """An unverifiable lease fails closed, so the log survives."""
        path = _make_log(task_dir, "wa-live.agent-launch.log")
        _write_lease(path, {"pid": 12345})

        removed = bg._reclaim_expired_launch_logs(task_dir)

        assert removed == []
        assert path.exists()

    def test_stale_lease_does_not_protect_the_log(self, task_dir):
        """A lease whose recorded owner is provably gone no longer protects."""
        path = _make_log(task_dir, "wa-stale.agent-launch.log")
        _write_lease(path, {"pid": 999999, "start": "gone"})

        removed = bg._reclaim_expired_launch_logs(task_dir)

        assert removed == [str(path)]
        assert not path.exists()

    def test_session_records_are_not_touched(self, task_dir):
        """Session records belong to the session cleanup paths, not this sweep."""
        meta = _make_log(task_dir, "wa-abc.111.session.meta")
        stdout = _make_log(task_dir, "wa-abc.111.session.stdout")

        removed = bg._reclaim_expired_launch_logs(task_dir)

        assert removed == []
        assert meta.exists()
        assert stdout.exists()

    def test_lease_sidecar_is_never_a_record(self, task_dir):
        """A lease alone is ownership evidence, so it is never deleted here."""
        log_path = task_dir / "wa-gone.agent-launch.log"
        lease = _write_lease(log_path, {"pid": 12345})
        stamp = time.time() - OLD_AGE_SECONDS
        os.utime(lease, (stamp, stamp))

        removed = bg._reclaim_expired_launch_logs(task_dir)

        assert removed == []
        assert lease.exists()

    def test_held_open_log_is_kept(self, task_dir, monkeypatch):
        """A log still held open by a process is skipped."""
        monkeypatch.setattr(cleaning, "is_file_in_use", lambda path: True)
        path = _make_log(task_dir, "wa-held.agent-launch.log")

        removed = bg._reclaim_expired_launch_logs(task_dir)

        assert removed == []
        assert path.exists()

    def test_missing_directory_is_tolerated(self, tmp_path):
        removed = bg._reclaim_expired_launch_logs(tmp_path / "absent")

        assert removed == []

    def test_removal_is_logged(self, task_dir, caplog):
        path = _make_log(task_dir, "wa-old.agent-launch.log")

        with caplog.at_level(logging.INFO, logger=bg.__name__):
            bg._reclaim_expired_launch_logs(task_dir)

        messages = [record.getMessage() for record in caplog.records]
        assert f"DELETED: {path}" in messages
        assert any("Removed 1 expired launch log(s)" in message for message in messages)

    def test_explicit_now_controls_the_window(self, task_dir):
        """An injected reference time decides eligibility without touching mtime."""
        path = _make_log(task_dir, "wa-old.agent-launch.log")
        reference = time.time() + cleaning.EXPIRED_AGE_SECONDS + 1

        removed = bg._reclaim_expired_launch_logs(task_dir, now=reference)

        assert removed == [str(path)]


class TestSupervisorExitWiring:
    """The sweep must run from the supervisor's own exit path."""

    def test_sweep_is_called_from_the_supervisor_finally_block(self):
        """The call site lives in ``_supervise``, not in the agent core.

        A source-level assertion is used because driving the real ``_supervise``
        requires a live child, a selector and a channel. The property under test
        is placement: the sweep belongs to the process that owns the artifact.
        """
        import inspect

        source = inspect.getsource(bg._supervise)
        assert "_reclaim_expired_launch_logs(log_path.parent)" in source
        assert "finally:" in source

    def test_agent_core_does_not_reference_the_sweep(self):
        """The agent core must not import or call any CLI module."""
        import topsailai.workspace.agent_shell as agent_shell

        source = inspect_source(agent_shell)
        assert "launch_log" not in source
        assert "cli_topsailai" not in source


def inspect_source(module) -> str:
    """Return a module's source text."""
    import inspect

    return inspect.getsource(module)
