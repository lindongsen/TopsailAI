"""
Unit tests for topsailai.events.backends.
"""

import json
import os
import time

import pytest

from topsailai.events.backends import (
    DBEventBackend,
    FileEventBackend,
    WebhookEventBackend,
)
from topsailai.events.models import Event


def test_file_backend_writes_jsonl(temp_events_file):
    backend = FileEventBackend(file_path=temp_events_file)
    events = [
        Event(event_type="a", payload={"i": 1}),
        Event(event_type="b", payload={"i": 2}),
    ]
    assert backend.write(events) is True
    backend.close()

    with open(temp_events_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    assert len(lines) == 2
    assert json.loads(lines[0])["event_type"] == "a"
    assert json.loads(lines[1])["payload"] == {"i": 2}


def test_file_backend_default_path_uses_session_and_pid(monkeypatch):
    monkeypatch.setenv("SESSION_ID", "abc-123")
    backend = FileEventBackend()
    path = backend.file_path
    assert path.endswith(".events")
    assert "abc-123" in path
    assert str(os.getpid()) in path


def test_file_backend_append_mode(temp_events_file):
    backend = FileEventBackend(file_path=temp_events_file)
    backend.write([Event(event_type="first", payload={})])
    backend.write([Event(event_type="second", payload={})])
    backend.close()

    with open(temp_events_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert [json.loads(line)["event_type"] for line in lines] == ["first", "second"]


def test_db_backend_stub():
    backend = DBEventBackend()
    with pytest.raises(NotImplementedError):
        backend.write([Event(event_type="x", payload={})])


def test_webhook_backend_stub():
    backend = WebhookEventBackend()
    with pytest.raises(NotImplementedError):
        backend.write([Event(event_type="x", payload={})])


def test_file_backend_serializes_non_json_payload(temp_events_file):
    backend = FileEventBackend(file_path=temp_events_file)
    events = [
        Event(event_type="with_set", payload={"items": {1, 2, 3}}),
        Event(event_type="with_bytes", payload={"raw": b"hello"}),
    ]
    assert backend.write(events) is True
    backend.close()

    with open(temp_events_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    assert len(lines) == 2
    assert json.loads(lines[0])["payload"]["items"] == [1, 2, 3]
    assert json.loads(lines[1])["payload"]["raw"] == "hello"


def test_file_backend_cleanup_by_retention_days(tmp_path):
    old_file = tmp_path / "old.session.events"
    new_file = tmp_path / "new.session.events"
    old_file.write_text("{}")
    new_file.write_text("{}")
    # Make old file appear 10 days old
    old_mtime = time.time() - 10 * 86400
    os.utime(old_file, (old_mtime, old_mtime))

    backend = FileEventBackend(
        file_path=str(new_file), retention_days=7, max_count=0
    )
    backend.cleanup()
    backend.close()

    assert not old_file.exists()
    assert new_file.exists()


def test_file_backend_cleanup_by_max_count(tmp_path):
    files = []
    for i in range(5):
        path = tmp_path / f"f{i}.session.events"
        path.write_text("{}")
        files.append(path)
        time.sleep(0.01)

    backend = FileEventBackend(
        file_path=str(files[-1]), retention_days=0, max_count=3
    )
    backend.cleanup()
    backend.close()

    assert not files[0].exists()
    assert not files[1].exists()
    assert files[2].exists()
    assert files[3].exists()
    assert files[4].exists()


def test_file_backend_delete_on_exit_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("TOPSAILAI_EVENTS_FILE_DELETE_ON_EXIT", "1")
    pid = os.getpid()
    path = str(tmp_path / f"delete_me.{pid}.session.events")
    backend = FileEventBackend(file_path=path)
    backend.write([Event(event_type="x", payload={})])
    backend.close()
    assert os.path.exists(path)

    # Simulate interpreter shutdown by invoking registered atexit handlers.
    import atexit
    atexit._run_exitfuncs()

    assert not os.path.exists(path)


def test_file_backend_delete_on_exit_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("TOPSAILAI_EVENTS_FILE_DELETE_ON_EXIT", "0")
    pid = os.getpid()
    path = str(tmp_path / f"keep_me.{pid}.session.events")
    backend = FileEventBackend(file_path=path)
    backend.write([Event(event_type="x", payload={})])
    backend.close()
    assert os.path.exists(path)

    import atexit
    atexit._run_exitfuncs()

    assert os.path.exists(path)


def test_file_backend_fsync_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("TOPSAILAI_EVENTS_FILE_FSYNC", "1")
    path = str(tmp_path / "fsync.session.events")
    backend = FileEventBackend(file_path=path)
    backend.write([Event(event_type="x", payload={})])
    backend.close()
    assert os.path.exists(path)


def test_file_backend_fsync_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("TOPSAILAI_EVENTS_FILE_FSYNC", "0")
    path = str(tmp_path / "no_fsync.session.events")
    backend = FileEventBackend(file_path=path)
    backend.write([Event(event_type="x", payload={})])
    backend.close()
    assert os.path.exists(path)
