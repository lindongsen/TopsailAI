"""Bounded automatic eviction regressions (author: DawsonLin)."""

from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path

import pytest

from topsailai.context.session_activity import ActivityObservation, ActivityState, SessionActivityProbe
from topsailai.context.session_cleanup import SessionCleanupManager


def rows(count, home=""):
    """Build oldest-first storage rows without touching real session history."""
    return [SimpleNamespace(session_id=f"s{i}", topsailai_home=home) for i in range(count)]


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
