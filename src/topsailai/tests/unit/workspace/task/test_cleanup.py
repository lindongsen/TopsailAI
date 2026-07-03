"""Unit tests for workspace/task/cleanup.py."""

import os
import signal
import tempfile
from unittest.mock import patch

import pytest

from topsailai.workspace.task import cleanup as cleanup_module
from topsailai.workspace.task.cleanup import (
    cleanup_task_folder,
    register_cleanup_file,
    unregister_cleanup_file,
)


@pytest.fixture(autouse=True)
def isolated_cleanup_state(monkeypatch):
    """Use a temporary task folder and a clean registry for each test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(cleanup_module, "FOLDER_WORKSPACE_TASK", tmpdir)
        with cleanup_module._CLEANUP_LOCK:
            cleanup_module._CLEANUP_FILES.clear()
        yield tmpdir
        with cleanup_module._CLEANUP_LOCK:
            cleanup_module._CLEANUP_FILES.clear()


@pytest.fixture
def restore_signal_handlers():
    """Save and restore SIGINT/SIGTERM handlers around tests."""
    original = {
        signal.SIGINT: signal.getsignal(signal.SIGINT),
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
    }
    yield
    for signum, handler in original.items():
        try:
            signal.signal(signum, handler)
        except (ValueError, OSError):
            pass


def _make_file(path: str) -> str:
    """Create an empty file and return its absolute path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("")
    return os.path.abspath(path)


def test_register_and_unregister():
    path = "/tmp/test_cleanup_register.txt"
    abs_path = os.path.abspath(path)

    register_cleanup_file(path)
    with cleanup_module._CLEANUP_LOCK:
        assert abs_path in cleanup_module._CLEANUP_FILES

    unregister_cleanup_file(path)
    with cleanup_module._CLEANUP_LOCK:
        assert abs_path not in cleanup_module._CLEANUP_FILES


def test_register_ignores_empty_path():
    register_cleanup_file("")
    with cleanup_module._CLEANUP_LOCK:
        assert "" not in cleanup_module._CLEANUP_FILES


def test_cleanup_deletes_registered_files(isolated_cleanup_state):
    tmpdir = isolated_cleanup_state
    file1 = _make_file(os.path.join(tmpdir, "a.task"))
    file2 = _make_file(os.path.join(tmpdir, "b.stdout"))

    register_cleanup_file(file1)
    register_cleanup_file(file2)
    cleanup_task_folder()

    assert not os.path.exists(file1)
    assert not os.path.exists(file2)
    with cleanup_module._CLEANUP_LOCK:
        assert cleanup_module._CLEANUP_FILES == set()


def test_cleanup_deletes_pid_scoped_pipes(isolated_cleanup_state):
    tmpdir = isolated_cleanup_state
    current_pid = os.getpid()
    pipe = _make_file(os.path.join(tmpdir, f"session.{current_pid}.session.pipe"))
    other_pipe = _make_file(os.path.join(tmpdir, f"session.{current_pid + 99999}.session.pipe"))

    cleanup_task_folder()

    assert not os.path.exists(pipe)
    assert os.path.exists(other_pipe)


def test_cleanup_does_not_delete_unrelated_files(isolated_cleanup_state):
    tmpdir = isolated_cleanup_state
    unrelated = _make_file(os.path.join(tmpdir, "important.log"))

    cleanup_task_folder()

    assert os.path.exists(unrelated)


def test_cleanup_is_idempotent(isolated_cleanup_state):
    tmpdir = isolated_cleanup_state
    file1 = _make_file(os.path.join(tmpdir, "a.task"))

    register_cleanup_file(file1)
    cleanup_task_folder()
    cleanup_task_folder()

    assert not os.path.exists(file1)


def test_signal_handlers_installed_and_preserve_originals(restore_signal_handlers):
    # Force re-installation by resetting the installation flag.
    cleanup_module._SIGNALS_INSTALLED = False
    cleanup_module._ORIGINAL_SIGNAL_HANDLERS.clear()

    # Set a deterministic original handler so we can verify it is preserved.
    def original_handler(signum, frame):
        pass

    signal.signal(signal.SIGINT, original_handler)

    cleanup_module._ensure_signal_handlers_installed()

    assert cleanup_module._SIGNALS_INSTALLED is True
    assert cleanup_module._ORIGINAL_SIGNAL_HANDLERS[signal.SIGINT] is original_handler
    current = signal.getsignal(signal.SIGINT)
    assert current is cleanup_module._signal_handler


def test_signal_handler_chains_to_custom_handler_without_cleanup(restore_signal_handlers, isolated_cleanup_state):
    tmpdir = isolated_cleanup_state
    cleanup_module._SIGNALS_INSTALLED = False
    cleanup_module._ORIGINAL_SIGNAL_HANDLERS.clear()

    calls = []

    def original_handler(signum, frame):
        calls.append(("original", signum))

    signal.signal(signal.SIGINT, original_handler)
    cleanup_module._ensure_signal_handlers_installed()

    file1 = _make_file(os.path.join(tmpdir, "signal.task"))
    register_cleanup_file(file1)

    handler = signal.getsignal(signal.SIGINT)
    handler(signal.SIGINT, None)

    # Custom handler returned without exiting, so files must be preserved.
    assert os.path.exists(file1)
    assert ("original", signal.SIGINT) in calls


def test_signal_handler_ignores_signal_when_original_is_sig_ign(restore_signal_handlers, isolated_cleanup_state):
    tmpdir = isolated_cleanup_state
    cleanup_module._SIGNALS_INSTALLED = False
    cleanup_module._ORIGINAL_SIGNAL_HANDLERS.clear()

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    cleanup_module._ensure_signal_handlers_installed()

    file1 = _make_file(os.path.join(tmpdir, "ignored.task"))
    register_cleanup_file(file1)

    handler = signal.getsignal(signal.SIGINT)
    handler(signal.SIGINT, None)

    # Signal is ignored; files must be preserved.
    assert os.path.exists(file1)


def test_signal_handler_restores_default_for_uncaught_signal(restore_signal_handlers, isolated_cleanup_state):
    tmpdir = isolated_cleanup_state
    cleanup_module._SIGNALS_INSTALLED = False
    cleanup_module._ORIGINAL_SIGNAL_HANDLERS.clear()

    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    cleanup_module._ensure_signal_handlers_installed()

    file1 = _make_file(os.path.join(tmpdir, "default.task"))
    register_cleanup_file(file1)

    handler = signal.getsignal(signal.SIGTERM)
    # When original is SIG_DFL, the handler restores default and raises the signal.
    # Patch signal-raising helpers so the test process is not terminated.
    killed = []

    def fake_kill(pid, signum):
        killed.append((pid, signum))

    def fake_raise_signal(signum):
        killed.append((os.getpid(), signum))

    with patch("os.kill", fake_kill), patch("signal.raise_signal", fake_raise_signal):
        handler(signal.SIGTERM, None)

    assert not os.path.exists(file1)
    assert killed == [(os.getpid(), signal.SIGTERM)]
