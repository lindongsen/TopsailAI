"""Focused tests for absent-only completed metadata cache admission."""

import threading
from unittest.mock import Mock

from cli_topsailai import session_info


def _row(session_id="s1", pid=101, name="Completed", path="/meta"):
    return {
        "session_id": session_id,
        "pid": pid,
        "is_task": False,
        "_completed_session_meta": (session_id, pid, name, path),
    }


def test_meta_admission_does_not_replace_existing_entries(monkeypatch):
    """Metadata never replaces or merges any existing cache value."""
    cache = session_info._SessionInfoCache()
    monkeypatch.setattr(session_info, "_SESSION_INFO_CACHE", cache)
    monkeypatch.setattr(session_info, "load_project_workspace_lookup", Mock(return_value={}))
    query = Mock(side_effect=AssertionError("unexpected query"))
    monkeypatch.setattr(session_info, "_get_session_info", query)

    existing = {
        "full": ("Existing", "/existing"),
        "name-only": ("Existing", None),
        "path-only": (None, "/existing"),
        "empty": (None, None),
    }
    for session_id, value in existing.items():
        cache.set(session_id, value)

    rows = [_row(session_id, pid=100 + index) for index, session_id in enumerate(existing)]
    session_info.enrich_files_with_session_names(rows)

    for session_id, value in existing.items():
        assert cache.get(session_id) == value
    query.assert_not_called()


def test_meta_seeds_before_query_planning_when_ordinary_row_precedes_snapshot(monkeypatch):
    """A snapshot later in the batch satisfies an earlier ordinary row."""
    cache = session_info._SessionInfoCache()
    monkeypatch.setattr(session_info, "_SESSION_INFO_CACHE", cache)
    monkeypatch.setattr(session_info, "load_project_workspace_lookup", Mock(return_value={}))
    query = Mock(side_effect=AssertionError("unexpected query"))
    monkeypatch.setattr(session_info, "_get_session_info", query)

    ordinary = {"session_id": "s1", "pid": 202, "is_task": False}
    snapshot = _row()
    session_info.enrich_files_with_session_names([ordinary, snapshot])

    assert ordinary["session_name"] == "Completed"
    assert ordinary["project_workspace"] == "/meta"
    query.assert_not_called()


def test_invalid_snapshot_does_not_seed_but_can_use_existing_cache(monkeypatch):
    """Invalid metadata is rejected while a valid same-ID cache remains usable."""
    cache = session_info._SessionInfoCache()
    monkeypatch.setattr(session_info, "_SESSION_INFO_CACHE", cache)
    monkeypatch.setattr(session_info, "load_project_workspace_lookup", Mock(return_value={}))
    cache.set("s1", ("Cached", "/cached"))
    query = Mock(side_effect=AssertionError("cache should satisfy fallback"))
    monkeypatch.setattr(session_info, "_get_session_info", query)

    invalid = _row()
    invalid["_completed_session_meta"] = ("other", 101, "Wrong", "/wrong")
    session_info.enrich_files_with_session_names([invalid])

    assert invalid["session_name"] == "Cached"
    assert invalid["project_workspace"] == "/cached"
    assert cache.get("s1") == ("Cached", "/cached")
    query.assert_not_called()


def test_set_if_absent_is_atomic_for_concurrent_writers():
    """Concurrent admissions have one stored winner and no overwritten value."""
    cache = session_info._SessionInfoCache()
    barrier = threading.Barrier(2)
    results = []

    def writer(value):
        barrier.wait()
        results.append(cache.set_if_absent("s1", (value, "/" + value)))

    threads = [threading.Thread(target=writer, args=(value,)) for value in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 2
    assert cache.get("s1") in (("a", "/a"), ("b", "/b"))
    assert all(result == cache.get("s1") for result in results)
