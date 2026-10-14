"""Author: DawsonLin. Independent best-effort session name saves."""

import json
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from topsailai.context import ctx_manager
from topsailai.workspace import session_meta


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    """Redirect only the consumer module's metadata path and exit registration."""
    monkeypatch.setattr(session_meta, "FOLDER_WORKSPACE_TASK", str(tmp_path))
    monkeypatch.setattr(session_meta, "atexit", SimpleNamespace(register=Mock()))


def test_success_uses_explicit_id(monkeypatch):
    """The exact supplied ID wins over the process's ambient session."""
    session_meta.create_session_meta("target")
    session_meta.create_session_meta("ambient", session_name="unrelated")
    monkeypatch.setattr(session_meta, "env_tool", SimpleNamespace(get_session_id=lambda: "ambient"))
    storage = Mock(update_session_name=Mock(return_value=True))
    assert ctx_manager.update_session_name("target", "new name", storage) is True
    storage.update_session_name.assert_called_once_with("target", "new name")
    target = json.loads(Path(session_meta.get_session_meta_path("target")).read_text())
    ambient = json.loads(Path(session_meta.get_session_meta_path("ambient")).read_text())
    assert target["session_name"] == "new name"
    assert ambient["session_name"] == "unrelated"


@pytest.mark.parametrize("result", [False, None])
def test_db_failure_still_saves_metadata(monkeypatch, result):
    """False and None DB results do not prevent independent metadata saving."""
    sync = Mock()
    monkeypatch.setattr(session_meta, "update_session_meta_field", sync)
    storage = Mock(update_session_name=Mock(return_value=result))
    assert ctx_manager.update_session_name("target", "new", storage) is result
    sync.assert_called_once_with("session_name", "new", session_id="target")


@pytest.mark.parametrize("result", [True, False, None])
def test_sync_exception_keeps_db_result(monkeypatch, caplog, result):
    """Filesystem exceptions cannot change any DB return value."""
    monkeypatch.setattr(session_meta, "update_session_meta_field",
                        Mock(side_effect=OSError("metadata unavailable")))
    assert ctx_manager.update_session_name("target", "new", Mock(
        update_session_name=Mock(return_value=result))) is result
    assert "metadata unavailable" in caplog.text
    assert any(record.exc_info for record in caplog.records)


def test_db_exception_does_not_project(monkeypatch):
    """DB exceptions retain their existing public propagation contract."""
    sync = Mock()
    monkeypatch.setattr(session_meta, "update_session_meta_field", sync)
    with pytest.raises(RuntimeError, match="db failed"):
        ctx_manager.update_session_name("target", "new", Mock(
            update_session_name=Mock(side_effect=RuntimeError("db failed"))))
    sync.assert_not_called()


@pytest.mark.parametrize("result", [True, False, None])
def test_real_write_failure_keeps_db_result(monkeypatch, caplog, result):
    """A real metadata transaction tolerates failure for any DB return."""
    path = Path(session_meta.create_session_meta("target", session_name="before"))
    before = path.read_bytes()
    real_os = session_meta.os
    monkeypatch.setattr(session_meta, "os", SimpleNamespace(
        path=real_os.path, getpid=real_os.getpid, makedirs=real_os.makedirs,
        fsync=real_os.fsync, remove=real_os.remove,
        replace=Mock(side_effect=OSError("publication denied")),
    ))
    storage = Mock(update_session_name=Mock(return_value=result))
    assert ctx_manager.update_session_name("target", "after", storage) is result
    storage.update_session_name.assert_called_once_with("target", "after")
    assert path.read_bytes() == before
    assert not Path(str(path) + ".tmp").exists()
    assert "publication denied" in caplog.text
