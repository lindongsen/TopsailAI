"""Bounded automatic eviction regressions (author: DawsonLin)."""

from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path

import pytest

from topsailai.context.session_activity import ActivityObservation, ActivityState, SessionActivityProbe
from topsailai.context.session_cleanup import SessionCleanupManager


def rows(count, home="", category=""):
    """Build oldest-first storage rows without touching real session history."""
    return [
        SimpleNamespace(session_id=f"s{i}", topsailai_home=home, category=category)
        for i in range(count)
    ]


@pytest.mark.parametrize("count", [0, 99, 100])
def test_at_limit_does_not_observe(count):
    """No ownership work is needed without excess sessions."""
    storage, probe = Mock(), Mock()
    storage.list_sessions.return_value = rows(count)
    SessionCleanupManager(storage, probe).evict_sessions("new")
    probe.observe_many.assert_not_called()
    storage.delete_session.assert_not_called()


@pytest.mark.parametrize("state", [ActivityState.RUNNING, ActivityState.UNKNOWN])
def test_only_excess_candidates_are_observed(state):
    """Protected old rows do not bring retained newer rows into cleanup."""
    storage, probe = Mock(), Mock()
    storage.list_sessions.return_value = rows(103)
    probe.observe_many.return_value = {
        sid: ActivityObservation(state, "protected") for sid in ("s0", "s1", "s2")
    }
    SessionCleanupManager(storage, probe).evict_sessions("s102")
    probe.observe_many.assert_called_once_with(["s0", "s1", "s2"], "")
    probe.can_clean.assert_not_called()
    storage.delete_session.assert_not_called()


def test_new_session_excluded_and_home_groups_preserved():
    """A new session cannot be evicted even when its timestamp sorts first."""
    storage, probe = Mock(), Mock()
    sessions = rows(103)
    sessions[1].topsailai_home = "home-a"
    sessions[2].topsailai_home = "home-b"
    storage.list_sessions.return_value = sessions
    probe.observe_many.side_effect = lambda ids, home: {
        sid: ActivityObservation(ActivityState.UNKNOWN, "unverified") for sid in ids
    }
    SessionCleanupManager(storage, probe).evict_sessions("s0")
    assert probe.observe_many.call_args_list == [
        ((["s1"], "home-a"),), ((["s2"], "home-b"),), ((["s3"], ""),),
    ]
    storage.delete_session.assert_not_called()


@pytest.mark.parametrize("checks, deleted", [([True, True], True), ([True, False], False), ([False], False)])
def test_batch_screening_requires_fresh_rechecks(checks, deleted):
    """A STOPPED snapshot never bypasses fresh provenance and owner checks."""
    storage, probe = Mock(), Mock()
    sessions = rows(101)
    storage.list_sessions.side_effect = [sessions] + [[sessions[0]]] * len(checks)
    probe.observe_many.return_value = {"s0": ActivityObservation(ActivityState.STOPPED, "stopped")}
    probe.can_clean.side_effect = checks
    storage.delete_session.return_value = True
    SessionCleanupManager(storage, probe).evict_sessions("s100")
    assert probe.can_clean.call_count == len(checks)
    assert storage.delete_session.called is deleted
    assert storage.list_sessions.call_count == 1 + len(checks)


def test_failed_delete_does_not_expand_candidates():
    """Storage refusal never admits a newer session to automatic eviction."""
    storage, probe = Mock(), Mock()
    sessions = rows(101)
    storage.list_sessions.side_effect = [sessions, [sessions[0]], [sessions[0]]]
    probe.observe_many.return_value = {"s0": ActivityObservation(ActivityState.STOPPED, "stopped")}
    probe.can_clean.return_value = True
    storage.delete_session.return_value = False
    SessionCleanupManager(storage, probe).evict_sessions("s100")
    storage.delete_session.assert_called_once_with("s0")


def test_protected_backlog_uses_one_inventory(tmp_path, monkeypatch):
    """A large protected backlog incurs two listings total, not per session."""
    task = tmp_path / "workspace" / "task"
    task.mkdir(parents=True)
    for i in range(110):
        (task / f"s{i}.123.session.stdout").touch()
    for i in range(1000):
        (task / f"unrelated-{i}").touch()
    process = Mock(return_value=ActivityState.RUNNING)
    probe = SessionActivityProbe((task,), process)
    listings = []
    original = Path.iterdir

    def counted(path):
        """Record inventories without changing the real filesystem probe."""
        listings.append(path)
        return original(path)

    monkeypatch.setattr(Path, "iterdir", counted)
    storage = Mock()
    storage.list_sessions.return_value = rows(110, str(tmp_path))
    SessionCleanupManager(storage, probe).evict_sessions("s109")
    assert listings == [task, task]
    assert process.call_count == 10
    storage.delete_session.assert_not_called()


def _mixed_rows(driver_count, counted_count, home=""):
    """Build oldest-first rows where the driver backlog sorts before counted rows."""
    driver = rows(driver_count, home, category="agent_driver")
    counted = rows(counted_count, home)
    for index, row in enumerate(counted):
        row.session_id = f"c{index}"
    return driver + counted


@pytest.mark.parametrize("driver_count,counted_count", [(50, 70), (5, 100), (10, 100)])
def test_excluded_category_does_not_consume_the_threshold(driver_count, counted_count):
    """A driver backlog never counts toward the retention limit."""
    storage, probe = Mock(), Mock()
    storage.list_sessions.return_value = _mixed_rows(driver_count, counted_count)
    SessionCleanupManager(storage, probe).evict_sessions("c0")
    probe.observe_many.assert_not_called()
    storage.delete_session.assert_not_called()


def test_excluded_category_is_never_an_eviction_candidate():
    """Older excluded rows are skipped while counted excess is still evicted."""
    storage, probe = Mock(), Mock()
    storage.list_sessions.return_value = _mixed_rows(3, 102)
    probe.observe_many.return_value = {
        sid: ActivityObservation(ActivityState.STOPPED, "stopped") for sid in ("c0", "c1")
    }
    probe.can_clean.return_value = True
    storage.delete_session.return_value = True
    SessionCleanupManager(storage, probe).evict_sessions("c101")
    probe.observe_many.assert_called_once_with(["c0", "c1"], "")
    assert [call.args[0] for call in storage.delete_session.call_args_list] == ["c0", "c1"]


def test_large_driver_backlog_does_not_inflate_excess():
    """A driver backlog must not widen the counted excess beyond its own size."""
    storage, probe = Mock(), Mock()
    storage.list_sessions.return_value = _mixed_rows(100, 103)
    probe.observe_many.return_value = {
        sid: ActivityObservation(ActivityState.STOPPED, "stopped") for sid in ("c0", "c1", "c2")
    }
    probe.can_clean.return_value = True
    storage.delete_session.return_value = True
    SessionCleanupManager(storage, probe).evict_sessions("c102")
    probe.observe_many.assert_called_once_with(["c0", "c1", "c2"], "")
    assert [call.args[0] for call in storage.delete_session.call_args_list] == ["c0", "c1", "c2"]


def test_driver_only_backlog_keeps_ordinary_sessions_untouched():
    """A large driver backlog must not evict ordinary sessions below the limit."""
    storage, probe = Mock(), Mock()
    storage.list_sessions.return_value = _mixed_rows(50, 70)
    SessionCleanupManager(storage, probe).evict_sessions("c69")
    probe.observe_many.assert_not_called()
    probe.can_clean.assert_not_called()
    storage.delete_session.assert_not_called()


def _real_manager(probe):
    """Compose a real SQLite manager so the threshold is exercised end to end."""
    from topsailai.context.session_manager.manager import DefaultSessionManager
    from topsailai.context.session_manager.sql import SessionSQLAlchemy

    return DefaultSessionManager(SessionSQLAlchemy("sqlite:///:memory:"), probe)


def _stopped_probe():
    """Return a probe that authorizes every observed owner as stopped."""
    probe = Mock()
    probe.observe_many.side_effect = lambda ids, home: {
        sid: ActivityObservation(ActivityState.STOPPED, "stopped") for sid in ids
    }
    probe.can_clean.return_value = True
    return probe


def _create(manager, session_id, category, offset):
    """Create one session with an explicit increasing creation time."""
    from datetime import datetime, timedelta
    from topsailai.context.session_manager.__base import SessionData

    data = SessionData(session_id, category=category)
    data.create_time = datetime(2026, 1, 1) + timedelta(seconds=offset)
    manager.create_session(data)


def test_real_storage_keeps_counted_sessions_behind_a_driver_backlog():
    """120 sessions with 50 driver sessions leave all 70 counted sessions intact."""
    probe = _stopped_probe()
    manager = _real_manager(probe)
    for index in range(50):
        _create(manager, f"d{index}", "agent_driver", index)
    for index in range(70):
        _create(manager, f"c{index}", "", 100 + index)
    _create(manager, "new", "", 1000)
    remaining = {row.session_id for row in manager.list_sessions()}
    assert len(remaining) == 121
    probe.observe_many.assert_not_called()


def test_real_storage_evicts_only_oldest_counted_excess():
    """A driver backlog never becomes the evicted row when counted rows exceed."""
    probe = _stopped_probe()
    manager = _real_manager(probe)
    for index in range(50):
        _create(manager, f"d{index}", "agent_driver", index)
    for index in range(101):
        _create(manager, f"c{index}", "", 100 + index)
    _create(manager, "new", "", 1000)
    remaining = {row.session_id for row in manager.list_sessions()}
    assert "c0" not in remaining
    assert "c1" not in remaining
    assert "c2" in remaining
    assert all(f"d{index}" in remaining for index in range(50))
    assert len(remaining) == 150
