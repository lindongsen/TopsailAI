"""Session exclusion tests, including real independent process contention.

Author: DawsonLin
"""
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest
from driver_mutex import DriverAlreadyRunning
from driver_runtime import DriverRuntime


def _runtime(directory, session="target"):
    """Create a test runtime using the explicitly supplied directory."""
    return DriverRuntime(directory, session, 5, logging.getLogger("mutex-test"))


def test_live_metadata_is_preserved(tmp_path):
    """Reject an existing PID before opening its log or rewriting metadata."""
    metadata = tmp_path / "target.meta"
    metadata.write_text(json.dumps({"pid": os.getpid()}))
    log = tmp_path / "target.log"
    log.write_text("owner log")
    before = metadata.read_bytes()
    with pytest.raises(DriverAlreadyRunning):
        with _runtime(tmp_path):
            pytest.fail("duplicate admitted")
    assert metadata.read_bytes() == before
    assert log.read_text() == "owner log"


@pytest.mark.parametrize("text", ["invalid", "[]", '{"pid": true}', '{"pid": -1}', "x" * 65537])
def test_bad_metadata_fails_closed(tmp_path, text):
    """Do not delete or reinterpret malformed owner evidence."""
    path = tmp_path / "target.meta"
    path.write_text(text)
    with pytest.raises(DriverAlreadyRunning):
        with _runtime(tmp_path):
            pass
    assert path.read_text() == text


def test_dead_metadata_allows_restart(tmp_path):
    """Replace metadata only after absence of its PID is verified."""
    (tmp_path / "target.meta").write_text('{"pid": 12345}')
    with mock.patch("driver_mutex.os.kill", side_effect=ProcessLookupError):
        with _runtime(tmp_path):
            assert json.loads((tmp_path / "target.meta").read_text())["pid"] == os.getpid()
    assert not (tmp_path / "target.meta").exists()


def test_permission_denied_pid_rejects(tmp_path):
    """A denied liveness probe must not authorize duplicate startup."""
    (tmp_path / "target.meta").write_text('{"pid": 12345}')
    with mock.patch("driver_mutex.os.kill", side_effect=PermissionError):
        with pytest.raises(DriverAlreadyRunning):
            with _runtime(tmp_path):
                pass


def test_lock_blocks_even_if_metadata_missing(tmp_path):
    """An active lock remains authoritative if metadata disappears."""
    with _runtime(tmp_path):
        (tmp_path / "target.meta").unlink()
        print("deleted test metadata to simulate missing snapshot")
        with pytest.raises(DriverAlreadyRunning):
            with _runtime(tmp_path):
                pass
        with _runtime(tmp_path, "other"):
            assert (tmp_path / "other.meta").exists()
    with _runtime(tmp_path):
        assert (tmp_path / "target.meta").exists()


def test_subprocess_cannot_enter_owner_session(tmp_path):
    """Exercise the actual OS lock with an independent Python process."""
    interpreter = Path(sys.executable)
    assert interpreter.exists() and interpreter.name.lower().startswith("python")
    code = '''
import logging, sys
from driver_runtime import DriverRuntime
from driver_mutex import DriverAlreadyRunning
try:
    with DriverRuntime(sys.argv[1], "target", 5, logging.getLogger("child")):
        raise AssertionError("duplicate admitted")
except DriverAlreadyRunning:
    print("duplicate rejected")
'''
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    with _runtime(tmp_path):
        before = (tmp_path / "target.meta").read_bytes()
        result = subprocess.run([str(interpreter), "-c", code, str(tmp_path)],
                                cwd=str(Path(__file__).resolve().parent.parent),
                                env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "duplicate rejected" in result.stdout
        assert (tmp_path / "target.meta").read_bytes() == before
        assert (tmp_path / "target.log").exists()


def test_initialization_failure_releases_lock(tmp_path):
    """A failed admitted startup relinquishes its exclusion authority."""
    failed = _runtime(tmp_path)
    with mock.patch.object(failed, "_publish", side_effect=OSError("failed")):
        with pytest.raises(OSError):
            with failed:
                pass
    with _runtime(tmp_path):
        assert (tmp_path / "target.meta").exists()


def test_metadata_replacement_preserves_exclusion(tmp_path):
    """Atomic snapshot replacement must not change the exclusion authority."""
    with _runtime(tmp_path) as owner:
        owner.update_target("running")
        before = (tmp_path / "target.meta").read_bytes()
        with pytest.raises(DriverAlreadyRunning):
            with _runtime(tmp_path):
                pytest.fail("duplicate admitted after snapshot replacement")
        assert (tmp_path / "target.meta").read_bytes() == before
    assert (tmp_path / "target.lock").exists()
    assert not (tmp_path / "target.meta").exists()
    assert not (tmp_path / "target.log").exists()


@pytest.mark.parametrize("failure", [RuntimeError("failed"), KeyboardInterrupt(), SystemExit(1)])
def test_exceptional_exit_releases_exclusion(tmp_path, failure):
    """Exceptions clean records and release the retained lock for restart."""
    with pytest.raises(type(failure)) as caught:
        with _runtime(tmp_path):
            raise failure
    assert caught.value is failure
    assert (tmp_path / "target.lock").exists()
    with _runtime(tmp_path):
        assert (tmp_path / "target.meta").exists()


@pytest.mark.parametrize("failure", [OSError("probe failed"), OverflowError("PID too large")])
def test_pid_probe_failure_preserves_owner(tmp_path, failure):
    """Unverifiable PIDs cannot authorize replacing owner metadata."""
    metadata = tmp_path / "target.meta"
    metadata.write_text('{"pid": 12345}')
    before = metadata.read_bytes()
    with mock.patch("driver_mutex.os.kill", side_effect=failure):
        with pytest.raises(DriverAlreadyRunning):
            with _runtime(tmp_path):
                pytest.fail("unverifiable owner admitted")
    assert metadata.read_bytes() == before


def test_windows_lock_branch_with_isolated_platform(tmp_path):
    """Verify byte-lock calls without mutating the shared os module."""
    from types import SimpleNamespace
    from driver_mutex import SessionMutex

    platform = SimpleNamespace(name="nt", SEEK_END=os.SEEK_END)
    locking = mock.Mock()
    windows = SimpleNamespace(locking=locking, LK_NBLCK=2)
    mutex = SessionMutex(tmp_path / "target.meta")
    with mock.patch("driver_mutex.os", platform), mock.patch.dict(sys.modules, {"msvcrt": windows}):
        mutex.acquire()
        descriptor = mutex.file.fileno()
        locking.assert_called_once_with(descriptor, windows.LK_NBLCK, 1)
        assert mutex.path.read_bytes() == b"\0"
        mutex.release()
        mutex.acquire()
        assert mutex.path.read_bytes() == b"\0"
        mutex.release()
        locking.side_effect = OSError("busy")
        with pytest.raises(DriverAlreadyRunning):
            mutex.acquire()
        assert mutex.file is None
    assert mutex.path.exists()
