"""Author: DawsonLin. Session-name metadata compatibility and transactions."""

import json
import threading
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from topsailai.workspace import session_meta as meta


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    """Keep metadata and exit registrations owned by the test."""
    monkeypatch.setattr(meta, "FOLDER_WORKSPACE_TASK", str(tmp_path))
    monkeypatch.setattr(meta, "atexit", SimpleNamespace(register=Mock()))


def read(session_id="names"):
    """Read the current process's published JSON."""
    return json.loads(Path(meta.get_session_meta_path(session_id)).read_text())


@pytest.mark.parametrize("name", ["", "existing name", "中文会话"])
def test_creation_name(name):
    """Names are additive JSON strings, not filename components."""
    meta.create_session_meta("names", None, name)
    assert read()["session_name"] == name
    assert read()["version"] == 1


def test_old_positional_call():
    """Existing two-argument creation retains its empty-name default."""
    meta.create_session_meta("names", None)
    assert read()["session_name"] == ""


def test_legacy_and_pid_isolation(tmp_path):
    """Add a name to legacy JSON without changing another PID or extensions."""
    path = Path(meta.get_session_meta_path("names"))
    old = {"status": "completed", "end_ts": "old-end", "extension": {"kept": True}}
    path.write_text(json.dumps(old))
    other = tmp_path / "names.99999999.session.meta"
    other.write_text(json.dumps(old))
    meta.update_session_meta_field("session_name", "renamed", "names")
    assert read() == dict(old, session_name="renamed")
    assert json.loads(other.read_text()) == old
    meta.update_session_meta_field("session_name", "absent", "missing")
    assert not Path(meta.get_session_meta_path("missing")).exists()


@pytest.mark.parametrize("first_name", [True, False])
@pytest.mark.parametrize("terminal", ["completed", "exit"])
def test_interleaving_preserves_name_and_terminal(monkeypatch, first_name, terminal):
    """Force contention before the second transaction reads the shared record."""
    meta.create_session_meta("names")
    original_read = meta._read_meta
    original_lock = meta._META_LOCK
    first_read = threading.Event()
    second_attempt = threading.Event()
    release = threading.Event()
    second_read = threading.Event()
    errors = []

    class ObservedLock:
        """Observe lock admission without changing its authority."""
        def __enter__(self):
            """Publish contender intent before acquiring the actual lock."""
            if threading.current_thread().name == "second":
                second_attempt.set()
            original_lock.acquire()
            return self

        def __exit__(self, *args):
            """Release exactly this nested acquisition."""
            original_lock.release()

    def paused_read(path):
        """Freeze the first transaction after reading but before mutation."""
        result = original_read(path)
        if threading.current_thread().name == "first":
            first_read.set()
            assert release.wait(5)
        else:
            second_read.set()
        return result

    def name_update():
        """Write the name through the existing entry point."""
        meta.update_session_meta_field("session_name", "late name", "names")

    def end_update():
        """Exercise either normal completion or the exit handler."""
        if terminal == "exit":
            meta._finalize_on_exit(meta.get_session_meta_path("names"))
        else:
            meta.update_session_meta_status(terminal, "names")

    def execute(operation):
        """Retain worker exceptions for the owning test."""
        try:
            operation()
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(meta, "_META_LOCK", ObservedLock())
    monkeypatch.setattr(meta, "_read_meta", paused_read)
    operations = [name_update, end_update] if first_name else [end_update, name_update]
    workers = [threading.Thread(target=execute, args=(op,), name=label)
               for op, label in zip(operations, ["first", "second"])]
    workers[0].start()
    try:
        assert first_read.wait(5)
        workers[1].start()
        assert second_attempt.wait(5)
        assert not second_read.is_set()
    finally:
        release.set()
        for worker in workers:
            if worker.ident is not None:
                worker.join(5)
    assert not any(worker.is_alive() for worker in workers)
    assert not errors
    assert second_read.is_set()
    result = read()
    assert result["session_name"] == "late name"
    assert result["status"] == ("interrupted" if terminal == "exit" else terminal)
    assert result["end_ts"]


def test_replace_failure_preserves_json(monkeypatch, caplog):
    """A failed publication logs the error and leaves the old complete record."""
    path = meta.create_session_meta("names", session_name="before")
    before = Path(path).read_bytes()
    real_os = meta.os
    monkeypatch.setattr(meta, "os", SimpleNamespace(
        path=real_os.path, getpid=real_os.getpid, makedirs=real_os.makedirs, fsync=real_os.fsync,
        replace=Mock(side_effect=OSError("replace denied")), remove=real_os.remove,
    ))
    meta.update_session_meta_field("session_name", "after", "names")
    assert Path(path).read_bytes() == before
    assert not Path(path + ".tmp").exists()
    assert "replace denied" in caplog.text


def test_missing_terminal_updates(tmp_path):
    """Absent legacy records remain absent on status and exit updates."""
    session_id = "absent"
    path = meta.get_session_meta_path(session_id)
    meta.update_session_meta_status("completed", session_id)
    meta._finalize_on_exit(path)
    assert not Path(path).exists()


def test_pipe_related_path(monkeypatch):
    """The additive field does not remove enabled related-file entries."""
    monkeypatch.setenv("TOPSAILAI_INPUT_PIPE_ENABLED", "1")
    meta.create_session_meta("names")
    assert read()["files"]["pipe"].endswith(".session.pipe")


@pytest.mark.parametrize("kind", ["old", "count", "temporary"])
def test_cleanup_failure_preserves_owned_files(monkeypatch, tmp_path, kind):
    """Failed retirement is tolerated without damaging unrelated metadata."""
    import os
    import time
    from types import SimpleNamespace

    path = Path(meta.create_session_meta("names", session_name="retained"))
    unrelated = Path(meta.create_session_meta("unrelated", session_name="other"))
    old_time = time.time() - 10 * 86400
    os.utime(path, (old_time, old_time))
    if kind == "temporary":
        path = Path(str(path) + ".tmp")
        path.write_text("partial")
        os.utime(path, (old_time, old_time))
    monkeypatch.setenv("TOPSAILAI_SESSION_META_RETENTION_DAYS", "0" if kind == "count" else "7")
    monkeypatch.setenv("TOPSAILAI_SESSION_META_MAX_COUNT", "1" if kind == "count" else "0")
    failed = []

    def fail_remove(candidate):
        """Record failed deletion attempts without deleting any test file."""
        failed.append(candidate)
        raise OSError("retirement denied")

    monkeypatch.setattr(meta, "os", SimpleNamespace(
        path=os.path, remove=fail_remove,
    ))
    probe = Mock()
    probe.can_clean.return_value = True
    meta.cleanup_session_meta_files(activity_probe=probe)
    if kind == "temporary":
        assert str(path) not in failed
    else:
        assert str(path) in failed
    assert path.exists()
    assert json.loads(unrelated.read_text())["session_name"] == "other"


def test_cleanup_ignores_nonmetadata_and_probe_failure(monkeypatch, tmp_path):
    """Cleanup skips directories, unrelated matches and inaccessible entries."""
    import os
    from types import SimpleNamespace

    directory = tmp_path / "directory.session.meta"
    directory.mkdir()
    unrelated = tmp_path / "unrelated.meta"
    unrelated.write_text("untouched")
    inaccessible = Path(meta.create_session_meta("names"))
    original_getmtime = os.path.getmtime

    def getmtime(path):
        """Inject an observation failure only for the owned test record."""
        if path == str(inaccessible):
            raise OSError("stat denied")
        return original_getmtime(path)

    monkeypatch.setattr(meta, "os", SimpleNamespace(path=SimpleNamespace(
        join=os.path.join, isfile=os.path.isfile, basename=os.path.basename,
        getmtime=getmtime,
    )))
    meta.cleanup_session_meta_files()
    assert directory.exists()
    assert unrelated.read_text() == "untouched"
    assert inaccessible.exists()
