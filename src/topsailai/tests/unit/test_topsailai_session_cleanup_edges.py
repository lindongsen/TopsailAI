"""Cleanup entry boundary protection (author: DawsonLin)."""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from topsailai.context.session_activity import ActivityState as State, SessionActivityProbe
from topsailai.workspace import session_meta

CLI = Path(__file__).resolve().parents[2] / "cli"
sys.path.insert(0, str(CLI))
from cli_topsailai import session_cleanup


@pytest.mark.parametrize("state", [State.RUNNING, State.UNKNOWN, State.STOPPED])
def test_disk_and_orphan_guard(tmp_path, monkeypatch, state):
    """Files without stdout are not disposable when any owner is protected."""
    path = tmp_path / "s.123.session.stderr"
    path.write_text("keep")
    probe = SessionActivityProbe((tmp_path,), lambda pid: state)
    monkeypatch.setattr(session_cleanup, "is_file_in_use", lambda path: False)
    deleted, _ = session_cleanup.clean_orphaned_session_files(str(tmp_path), activity_probe=probe)
    assert bool(deleted) == (state == State.STOPPED)
    if not deleted:
        assert session_cleanup.delete_session_disk_files(str(tmp_path), "s", activity_probe=probe) == ([], [])
        assert path.exists()


@pytest.mark.parametrize("state", [State.RUNNING, State.UNKNOWN, State.STOPPED])
def test_meta_retention_guard(tmp_path, monkeypatch, state):
    """Both old and excess metadata remain when owner liveness is uncertain."""
    path = tmp_path / "s.123.session.meta"
    path.write_text(json.dumps({"session_id": "s", "pid": 123}))
    os.utime(path, (time.time() - 20 * 86400,) * 2)
    monkeypatch.setattr(session_meta, "FOLDER_WORKSPACE_TASK", str(tmp_path))
    monkeypatch.setenv("TOPSAILAI_SESSION_META_RETENTION_DAYS", "7")
    session_meta.cleanup_session_meta_files(SessionActivityProbe((tmp_path,), lambda pid: state))
    assert path.exists() == (state != State.STOPPED)


@pytest.mark.parametrize("name", ["ai_clean_sessions", "ai_delete_session"])
def test_cli_refusal_does_not_delete_disk(tmp_path, monkeypatch, capsys, name):
    """A refused database deletion never triggers disk cleanup or success."""
    spec = importlib.util.spec_from_file_location(name, CLI / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    mgr = Mock()
    mgr.delete_session.return_value = False
    mgr.exists_session.return_value = True
    from datetime import datetime, timedelta
    mgr.list_sessions.return_value = [Mock(session_id="s", create_time=datetime.now() - timedelta(days=90))]
    monkeypatch.setattr(module, "get_session_manager", lambda conn: mgr)
    disk = Mock()
    monkeypatch.setattr(module, "delete_session_disk_files", disk)
    if name == "ai_clean_sessions":
        monkeypatch.setattr(module, "clean_orphaned_session_files", lambda task: ([], []))
    monkeypatch.setattr(sys, "argv", [name, "1" if name == "ai_clean_sessions" else "s"])
    if name == "ai_delete_session":
        with pytest.raises(SystemExit):
            module.main()
    else:
        module.main()
    disk.assert_not_called()
    assert "successfully deleted" not in capsys.readouterr().out


def test_meta_count_preserves_live_owners(tmp_path, monkeypatch):
    """A count limit is soft when every record still belongs to a live PID."""
    for sid in ("s", "t"):
        (tmp_path / f"{sid}.123.session.meta").write_text(json.dumps({"session_id": sid, "pid": 123}))
    monkeypatch.setattr(session_meta, "FOLDER_WORKSPACE_TASK", str(tmp_path))
    monkeypatch.setenv("TOPSAILAI_SESSION_META_RETENTION_DAYS", "0")
    monkeypatch.setenv("TOPSAILAI_SESSION_META_MAX_COUNT", "1")
    session_meta.cleanup_session_meta_files(SessionActivityProbe((tmp_path,), lambda pid: State.RUNNING))
    assert len(list(tmp_path.iterdir())) == 2
