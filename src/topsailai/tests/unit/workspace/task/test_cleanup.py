"""Unit tests for workspace/task/cleanup.py."""

import json
import os
import signal
import tempfile
from unittest.mock import patch

import pytest

from topsailai.workspace import session_meta as session_meta_module
from topsailai.workspace.task import cleanup as cleanup_module
from topsailai.workspace.task.cleanup import (
    cleanup_task_folder,
    register_cleanup_file,
    unregister_cleanup_file,
)


@pytest.fixture(autouse=True)
def isolated_cleanup_state(monkeypatch):
    """Use a temporary task folder and a clean registry for each test.

    ``session_meta`` resolves the metadata path from its own module constant, so
    both modules must point at the same temporary folder. Otherwise the exit
    cleanup would read the real task folder and decide on unrelated sessions.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(cleanup_module, "FOLDER_WORKSPACE_TASK", tmpdir)
        monkeypatch.setattr(session_meta_module, "FOLDER_WORKSPACE_TASK", tmpdir)
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


def _write_session_stdout(tmpdir: str, pid: int, lines: list[str], session_id: str = "session") -> str:
    """Create a session stdout file for *pid* holding *lines*."""
    path = os.path.join(tmpdir, f"{session_id}.{pid}.session.stdout")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("".join(lines))
    return path


def _prompt_line(pid: int) -> str:
    """Return the prompt line an immediately-exiting session writes."""
    return f">>> Your Turn: (pid={pid})  Press 'CTRL D' or Enter 'EOF' for end\n"


@pytest.fixture
def counters(monkeypatch):
    """Patch the session-counter lookup so no test touches a real database."""
    state = {"empty": True, "seen": []}

    def fake(session_id: str):
        state["seen"].append(session_id)
        return state["empty"]

    monkeypatch.setattr(cleanup_module, "_session_is_empty_by_counters", fake)
    return state


def test_empty_session_stdout_is_removed_on_exit(isolated_cleanup_state, counters):
    """A session with no recorded activity leaves no diagnostic value."""
    counters["empty"] = True
    path = _write_session_stdout(isolated_cleanup_state, os.getpid(), [_prompt_line(os.getpid())])

    cleanup_task_folder()

    assert not os.path.exists(path)


def test_session_stdout_with_real_output_is_preserved(isolated_cleanup_state, counters):
    """A stdout holding real output is the transcript and must survive."""
    counters["empty"] = False
    path = _write_session_stdout(isolated_cleanup_state, os.getpid(), [
        _prompt_line(os.getpid()),
        "user asked something\n",
        "agent answered with real content\n",
    ])

    cleanup_task_folder()

    assert os.path.exists(path)


def test_blank_session_stdout_is_removed_on_exit(isolated_cleanup_state, counters):
    """A completely empty stdout is also a shell with no diagnostic value."""
    counters["empty"] = True
    path = _write_session_stdout(isolated_cleanup_state, os.getpid(), [])

    cleanup_task_folder()

    assert not os.path.exists(path)


def test_other_process_session_stdout_is_untouched(isolated_cleanup_state, counters):
    """Cleanup is PID-scoped, so another process's stdout is never removed."""
    counters["empty"] = True
    foreign_pid = os.getpid() + 1
    path = _write_session_stdout(isolated_cleanup_state, foreign_pid, [_prompt_line(foreign_pid)])

    cleanup_task_folder()

    assert os.path.exists(path)
    assert counters["seen"] == []


def _write_task_artifact(tmpdir, session_id, pid, suffix):
    """Create one task artifact named ``{session_id}.{pid}.{task_id}{suffix}``."""
    path = os.path.join(tmpdir, f"{session_id}.{pid}.topsailai.1700000000.123456{suffix}")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("")
    return path


def _write_meta(tmpdir, session_id, pid, status):
    """Write a session metadata file recording *status* for the given owner."""
    path = os.path.join(tmpdir, f"{session_id}.{pid}.session.meta")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump({"session_id": session_id, "pid": pid, "status": status}, fp)
    return path


def test_task_artifacts_are_preserved_when_the_session_did_not_complete(
    isolated_cleanup_state, counters, monkeypatch
):
    """An abnormal exit must keep the task scene for diagnosis."""
    counters["empty"] = True
    session_id = "sess-abnormal"
    pid = os.getpid()
    monkeypatch.setattr(cleanup_module.env_tool, "get_session_id", lambda: session_id)
    _write_meta(isolated_cleanup_state, session_id, pid, "interrupted")
    task_path = _write_task_artifact(isolated_cleanup_state, session_id, pid, ".task")
    stdout_path = _write_task_artifact(isolated_cleanup_state, session_id, pid, ".task.stdout")

    cleanup_task_folder()

    assert os.path.exists(task_path)
    assert os.path.exists(stdout_path)


def test_task_artifacts_are_removed_after_a_normal_exit(
    isolated_cleanup_state, counters, monkeypatch
):
    """A completed session removes both task artifacts on exit."""
    counters["empty"] = True
    session_id = "sess-completed"
    pid = os.getpid()
    monkeypatch.setattr(cleanup_module.env_tool, "get_session_id", lambda: session_id)
    _write_meta(isolated_cleanup_state, session_id, pid, "completed")
    task_path = _write_task_artifact(isolated_cleanup_state, session_id, pid, ".task")
    stdout_path = _write_task_artifact(isolated_cleanup_state, session_id, pid, ".task.stdout")

    cleanup_task_folder()

    assert not os.path.exists(task_path)
    assert not os.path.exists(stdout_path)


def test_task_artifacts_are_preserved_without_metadata(
    isolated_cleanup_state, counters, monkeypatch
):
    """Missing metadata cannot prove a normal exit, so the artifacts survive."""
    counters["empty"] = True
    session_id = "sess-no-meta"
    pid = os.getpid()
    monkeypatch.setattr(cleanup_module.env_tool, "get_session_id", lambda: session_id)
    stdout_path = _write_task_artifact(isolated_cleanup_state, session_id, pid, ".task.stdout")

    cleanup_task_folder()

    assert os.path.exists(stdout_path)


def test_task_artifacts_of_another_pid_are_never_removed(
    isolated_cleanup_state, counters, monkeypatch
):
    """Cleanup is PID-scoped, so a foreign process's task artifacts survive."""
    counters["empty"] = True
    session_id = "sess-shared"
    foreign_pid = os.getpid() + 1
    monkeypatch.setattr(cleanup_module.env_tool, "get_session_id", lambda: session_id)
    _write_meta(isolated_cleanup_state, session_id, os.getpid(), "completed")
    foreign_path = _write_task_artifact(isolated_cleanup_state, session_id, foreign_pid, ".task.stdout")

    cleanup_task_folder()

    assert os.path.exists(foreign_path)


def test_active_session_stdout_survives_regardless_of_content(isolated_cleanup_state, counters):
    """Counters are authoritative: content never decides whether a file is removed."""
    counters["empty"] = False
    path = _write_session_stdout(isolated_cleanup_state, os.getpid(), [_prompt_line(os.getpid())])

    cleanup_task_folder()

    assert os.path.exists(path)


def test_unknown_counters_preserve_session_stdout(isolated_cleanup_state, monkeypatch):
    """An unreadable session table must preserve the file instead of guessing."""
    monkeypatch.setattr(cleanup_module, "_session_is_empty_by_counters", lambda _sid: None)
    path = _write_session_stdout(isolated_cleanup_state, os.getpid(), [_prompt_line(os.getpid())])

    cleanup_task_folder()

    assert os.path.exists(path)


def test_session_id_is_parsed_from_filename(isolated_cleanup_state, counters):
    """The counter lookup must receive the session id, not the whole filename."""
    counters["empty"] = True
    _write_session_stdout(isolated_cleanup_state, os.getpid(), [_prompt_line(os.getpid())], session_id="20261116135951")

    cleanup_task_folder()

    assert counters["seen"] == ["20261116135951"]
