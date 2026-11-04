"""Lifecycle tests for detached background launch supervision."""

from __future__ import annotations

import errno
import json
import os
import signal
from pathlib import Path
from types import SimpleNamespace

import pytest

import cli_topsailai.agent_launch_background as bg


def _fake_close(allowed):
    """Close only the fake descriptors a test owns and reject any real descriptor."""
    allowed = set(allowed)

    def close(fd):
        if fd not in allowed:
            raise AssertionError(f"unexpected descriptor close: {fd}")
        return None

    return close


class FakeClock:
    """Advance deterministic time with a finite call budget."""

    def __init__(self, step=0.05, max_calls=300):
        self.now = 0.0
        self.step = step
        self.max_calls = max_calls
        self.calls = 0
        self.sleeps = []

    def __call__(self):
        self.calls += 1
        if self.calls > self.max_calls:
            raise AssertionError("fake clock budget exhausted")
        self.sleeps.append(self.step)
        self.now += self.step
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeChild:
    """Process double with an explicit finite poll script."""

    def __init__(self, pid=7001, polls=None, wait_status=0):
        self.pid = pid
        self.polls = list([None, wait_status] if polls is None else polls)
        self.wait_status = wait_status
        self.calls = []
        self.stdout = None
        self.stderr = None

    def poll(self):
        self.calls.append("poll")
        if not self.polls:
            raise AssertionError("fake child script exhausted")
        return self.polls.pop(0)

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        return self.wait_status

    def terminate(self):
        self.calls.append("terminate")

    def kill(self):
        self.calls.append("kill")


class FakeStream:
    """Non-blocking stream with explicit EOF and close evidence."""

    def __init__(self, fd, chunks):
        self._fd = fd
        self.chunks = list(chunks)
        self.closed = False

    def fileno(self):
        return self._fd

    def read(self, size=-1):
        if self.chunks:
            return self.chunks.pop(0)
        return b""

    def close(self):
        self.closed = True


class FakeSelector:
    """Selector double with a finite selection budget."""

    def __init__(self, streams, max_calls=300):
        self.streams = streams
        self.closed = False
        self.max_calls = max_calls
        self.calls = 0

    def register(self, stream, event):
        return None

    def unregister(self, stream):
        self.streams.pop(stream.fileno(), None)

    def select(self, timeout=0):
        self.calls += 1
        if self.calls > self.max_calls:
            raise AssertionError("fake selector script exhausted")
        return [(SimpleNamespace(fileobj=s, fd=s.fileno()), 1)
                for s in list(self.streams.values()) if s.chunks]

    def close(self):
        self.closed = True


@pytest.fixture
def fake_clock():
    return FakeClock()


def test_b01_background_parser_forwards_terminal_mode_before_side_effects(monkeypatch, tmp_path):
    """A background terminal mechanism is forwarded, not rejected, before any spawn."""
    from cli_topsailai import agent_launch as al
    from cli_topsailai.workspace_agent_cli import run_workspace_agent_cli

    delegated = []

    def launch(folder, **kwargs):
        delegated.append((folder, kwargs))
        return 0

    monkeypatch.setattr(bg, "get_topsailai_home", lambda: str(tmp_path))
    monkeypatch.setattr(bg._subprocess, "Popen", lambda *a, **k: pytest.fail("spawned"))
    monkeypatch.setattr(al, "launch_configured_agent", launch)
    assert run_workspace_agent_cli([str(tmp_path), "-b", "-m", "tmux"]) == 0
    assert delegated[0][1]["mode"] == "tmux"
    assert delegated[0][1]["background"] is True


def test_b02_and_b16_ack_payload_is_exact_and_bounded(monkeypatch):
    writes = []
    monkeypatch.setattr(bg._os, "write", lambda fd, data: writes.append(bytes(data)) or len(data))
    bg._send_frame(4, {"kind": "submitted", "session": "s", "launcher_pid": 7})
    assert json.loads(writes[0]) == {"kind": "submitted", "session": "s", "launcher_pid": 7}
    monkeypatch.setattr(bg._os, "write", lambda fd, data: 0)
    with pytest.raises(OSError, match="acknowledgement pipe closed"):
        bg._send_frame(4, {"kind": "x"})


def test_b03_deployed_entrypoint_and_platform_flags(monkeypatch):
    monkeypatch.setenv("TOPSAILAI_CLI_ENTRY", "topsailai")
    assert bg._entrypoint_command() == ["topsailai"]
    monkeypatch.delenv("TOPSAILAI_CLI_ENTRY")
    monkeypatch.setattr(bg._sys, "argv", ["/bin/topsailai"])
    assert bg._entrypoint_command() == ["/bin/topsailai"]


def test_b04_request_is_private_and_contains_no_environment(tmp_path):
    path, unused = bg._request_file(tmp_path, {"kind": "workspace-agent-supervisor", "session_id": "s"})
    try:
        assert path.read_text(encoding="utf-8") == '{"kind":"workspace-agent-supervisor","session_id":"s"}'
        assert path.stat().st_mode & 0o077 == 0
    finally:
        path.unlink()


def test_b05_supervisor_spawn_failure_closes_transport(monkeypatch, tmp_path):
    class Lease:
        def touch(self, **kwargs):
            pass
        def unlink(self):
            pass
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg._RotatingLog, "open", lambda self: (_ for _ in ()).throw(OSError("open")))
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    sent = []
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    request = {"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s.log")}
    bg._supervise(request, 9, popen=lambda *a, **k: pytest.fail("launcher spawned"))
    assert [frame["kind"] for frame in sent] == ["cleanup", "failure"]
    assert sent[0]["cleanup_confirmed"] is True
    assert sent[1]["class"] == "startup_failure"


def test_b06_b08_b09_supervisor_deadlines_and_early_exit(monkeypatch, tmp_path, fake_clock):
    child = FakeChild(pid=71, polls=[None, 0], wait_status=0)
    child.stdout = FakeStream(11, [b"out"])
    child.stderr = FakeStream(12, [b"err"])
    sent = []
    class Lease:
        def touch(self, **kwargs): pass
        def unlink(self): pass
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    original_log = bg._RotatingLog
    monkeypatch.setattr(bg, "_RotatingLog", lambda path: original_log(path, max_bytes=32, backups=2))
    monkeypatch.setattr(bg._selectors, "DefaultSelector", lambda: FakeSelector({11: child.stdout, 12: child.stderr}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *a: None)
    reads = {11: [b"out", b""], 12: [b"err", b""]}
    monkeypatch.setattr(bg._os, "read", lambda fd, n: reads[fd].pop(0))
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    request = {"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s.log")}
    bg._supervise(request, 9, popen=lambda *a, **k: child, clock=fake_clock, sleeper=fake_clock.sleep)
    assert sent[0]["kind"] == "started"
    assert sent[-1] == {"kind": "early_exit", "code": 0, "launcher_pid": 71}
    assert fake_clock.sleeps


def test_b07_launcher_argv_stdin_and_actual_pid(monkeypatch, tmp_path):
    child = FakeChild(pid=7123, polls=[None])
    child.stdout = FakeStream(11, [])
    child.stderr = FakeStream(12, [])
    calls = []
    class Lease:
        def touch(self, **kwargs): pass
        def unlink(self): pass
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    sent = []
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    monkeypatch.setattr(bg._selectors, "DefaultSelector", lambda: FakeSelector({11: child.stdout, 12: child.stderr}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *a: None)
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    def popen(*args, **kwargs):
        calls.append((args, kwargs)); return child
    clock = FakeClock()
    request = {"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s.log")}
    original_log = bg._RotatingLog
    monkeypatch.setattr(bg, "_RotatingLog", lambda path: original_log(path, max_bytes=2, backups=2))
    child.polls = [None, 0]
    child.stdout.chunks = [b"out", b""]
    child.stderr.chunks = [b"err", b""]
    monkeypatch.setattr(bg._os, "read", lambda fd, n: b"out" if fd == 11 and child.stdout.chunks.pop(0) else (b"err" if fd == 12 and child.stderr.chunks.pop(0) else b""))
    bg._supervise(request, 9, popen=popen, clock=clock, sleeper=clock.sleep)
    assert calls[0][0][0] == ["topsailai_launch_agent", "--subprocess", "--session-id", "s"]
    assert calls[0][1]["stdin"] is bg._subprocess.DEVNULL
    assert calls[0][1]["start_new_session"] is True
    started = next(frame for frame in sent if frame["kind"] == "started")
    ownership = bg.LauncherOwnership(
        started["launcher_pid"], started["launcher_identity"], request["session_id"]
    )
    assert started["launcher_pid"] == ownership.launcher_pid
    # The reported PID is the launcher, never the supervisor that spawned it.
    assert ownership.launcher_pid == child.pid
    assert ownership.launcher_pid != bg._os.getpid()


def test_b10_b11_pipe_eof_truncated_and_wrong_identity(monkeypatch):
    buffer = bytearray()
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"{\"kind\":\"started\"")
    assert bg._read_frames(4, buffer) == []
    assert buffer
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"")
    with pytest.raises(EOFError, match="truncated acknowledgement frame"):
        bg._read_frames(4, buffer)
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"{bad}\n")
    with pytest.raises(json.JSONDecodeError):
        bg._read_frames(4, bytearray())


def test_b12_read_would_block_and_partial_frame(monkeypatch):
    monkeypatch.setattr(bg._os, "read", lambda fd, size: (_ for _ in ()).throw(BlockingIOError(errno.EAGAIN, "again")))
    assert bg._read_frames(4, bytearray()) == []
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b'{"kind":"started"}\n')
    assert bg._read_frames(4, bytearray()) == [{"kind": "started"}]


def test_b13_b14_owned_cleanup_and_unresolved_custody(monkeypatch):
    """The nt path terminates exactly the owned child with bounded waits."""
    child = FakeChild(pid=91, polls=[None, None, 0], wait_status=0)
    monkeypatch.setattr(bg, "_os", SimpleNamespace(
        name="nt", killpg=lambda *a: pytest.fail("wrong signal"),
        kill=lambda *a: None, environ=os.environ))
    probe = lambda pid: (pid, 1)
    assert bg._cleanup_owned(
        child, identity=(91, 1, "authoritative"), identity_probe=probe) is True
    assert child.calls.count("terminate") == 1
    assert [call for call in child.calls if call == ("wait", 0.25)] == [("wait", 0.25)]
    assert "kill" not in child.calls

    # Unresolved custody: a mismatched identity is never signalled.
    foreign = FakeChild(pid=92, polls=[None], wait_status=0)
    assert bg._cleanup_owned(
        foreign, identity=(92, 2, "authoritative"), identity_probe=probe) is False
    assert "terminate" not in foreign.calls
    assert "kill" not in foreign.calls


def test_b14_supervisor_exit_is_not_launcher_cleanup_proof(monkeypatch, tmp_path):
    """Bounded escalation signals only the owned launcher and supervisor cleanup is not launcher proof."""
    signals = []
    monkeypatch.setattr(bg._os, "killpg", lambda pid, sig: signals.append((pid, sig)))

    class StuckChild(FakeChild):
        """Child that never reports a terminal status within the bounded waits."""

        def wait(self, timeout=None):
            self.calls.append(("wait", timeout))
            raise bg._subprocess.TimeoutExpired("launcher", timeout)

    child = StuckChild(pid=4242, polls=[None, None])
    identity = (4242, 77, "authoritative")
    probe = lambda pid: (pid, 77)
    assert bg._cleanup_owned(child, identity=identity, identity_probe=probe) is False
    assert signals == [(4242, signal.SIGTERM)]
    assert child.calls.count("kill") == 1
    assert [call for call in child.calls if call == ("wait", 0.25)] == [("wait", 0.25), ("wait", 0.25)]

    frames = [[{"kind": "started", "session": "s", "launcher_pid": 4242,
                "launcher_identity": "identity:4242"}]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    supervisor.polls = [None, 0]
    reconciled = []
    monkeypatch.setattr(bg, "_reconcile_launcher",
                        lambda *a, **k: reconciled.append(True) or None)
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *a, **k: True)
    with pytest.raises(bg.BackgroundUnconfirmed):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=clock, sleeper=clock.sleep)
    assert reconciled == [True]


def test_b15_bounded_drain_distinguishes_eof(monkeypatch, tmp_path):
    stream = FakeStream(4, [b"x"])
    selector = FakeSelector({4: stream})
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"chunk")
    log = bg._RotatingLog(Path(tmp_path) / "x", max_bytes=20)
    log.open()
    assert bg._drain(selector, {4: stream}, log) is True
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"")
    assert bg._drain(selector, {4: stream}, log) is False
    log.close()


def test_b17_b18_b19_rotation_boundaries_and_private_mode(tmp_path):
    path = Path(tmp_path) / "s.agent-launch.log"
    log = bg._RotatingLog(path, max_bytes=4, backups=2)
    log.open(); log.write(b"abcd"); log.write(b"efgh"); log.write(b"ijkl"); log.close()
    assert path.read_bytes() == b"ijkl"
    assert path.with_name(path.name + ".1").read_bytes() == b"efgh"
    assert path.with_name(path.name + ".2").read_bytes() == b"abcd"
    assert path.stat().st_mode & 0o077 == 0
    assert not path.with_name(path.name + ".3").exists()


def test_b20_submitted_is_not_ready_and_final_status_logged(monkeypatch, tmp_path, fake_clock):
    child = FakeChild(pid=333, polls=[None] * 30 + [42], wait_status=42)
    child.stdout = FakeStream(1, [b"out", b""])
    child.stderr = FakeStream(2, [b"err", b""])
    sent = []
    class Lease:
        def touch(self, **kwargs): pass
        def unlink(self): pass
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    monkeypatch.setattr(bg._selectors, "DefaultSelector", lambda: FakeSelector({1: child.stdout, 2: child.stderr}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *a: None)
    monkeypatch.setattr(bg._os, "read", lambda fd, n: (child.stdout.chunks if fd == 1 else child.stderr.chunks).pop(0))
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    request = {"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s.log")}
    bg._supervise(request, 3, popen=lambda *a, **k: child, clock=fake_clock, sleeper=fake_clock.sleep)
    assert any(item["kind"] == "submitted" for item in sent)
    assert (tmp_path / "s.log").read_bytes().endswith(b"launcher exit status=42\n")


def test_b21_request_cleanup_and_lease_paths(monkeypatch, tmp_path):
    path = tmp_path / "request.json"
    path.write_text("x")
    bg._cleanup_request(path)
    assert not path.exists()
    log = tmp_path / "x.agent-launch.log"
    assert bg.active_launch_lease(log) == tmp_path / "x.agent-launch.log.lease"
    assert bg._is_active_launch_log(log) is False


def test_b22_b23_launch_log_active_detection(tmp_path):
    log = tmp_path / "s.agent-launch.log"
    log.write_bytes(b"x")
    lease = bg.active_launch_lease(log)
    lease.write_bytes(b"")
    assert bg._is_active_launch_log(log) is True
    lease.unlink()
    assert bg._is_active_launch_log(log) is False


def test_b24_invalid_supervisor_request_is_rejected(monkeypatch, tmp_path):
    request = tmp_path / "bad.json"
    request.write_text(json.dumps({"kind": "wrong"}))
    monkeypatch.setattr(bg, "_supervise", lambda *a, **k: pytest.fail("invalid request executed"))
    with pytest.raises(ValueError, match="invalid supervisor"):
        bg._supervisor_entry(str(request), 3)
    assert not request.exists()


def test_rotating_log_requires_open(tmp_path):
    with pytest.raises(OSError, match="not open"):
        bg._RotatingLog(Path(tmp_path) / "x", max_bytes=2).write(b"x")


# UNIT 1B-1 focused lifecycle branch proofs.
def test_ack_frame_size_and_short_write(monkeypatch):
    monkeypatch.setattr(bg, "_MAX_FRAME_BYTES", 8)
    with pytest.raises(ValueError, match="too large"):
        bg._send_frame(4, {"payload": "large"})
    monkeypatch.setattr(bg, "_MAX_FRAME_BYTES", 16384)
    writes = []
    def short_write(fd, data):
        writes.append(bytes(data))
        return 1 if len(data) > 1 else len(data)
    monkeypatch.setattr(bg._os, "write", short_write)
    bg._send_frame(4, {"kind": "x"})
    assert b"\n" in b"".join(writes)


def test_read_frames_all_protocol_errors(monkeypatch):
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"\n")
    with pytest.raises(ValueError, match="empty"):
        bg._read_frames(4, bytearray())
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"[]\n")
    with pytest.raises(ValueError, match="object"):
        bg._read_frames(4, bytearray())
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"x" * 20)
    monkeypatch.setattr(bg, "_MAX_FRAME_BYTES", 8)
    with pytest.raises(ValueError, match="too large"):
        bg._read_frames(4, bytearray())
    monkeypatch.setattr(bg, "_MAX_FRAME_BYTES", 16384)


def test_rotating_log_write_failure_and_rotation(tmp_path, monkeypatch):
    log = bg._RotatingLog(Path(tmp_path) / "active", max_bytes=2, backups=1)
    log.open()
    try:
        log.write(b"abcd")
        assert (Path(tmp_path) / "active.1").read_bytes() == b"ab"
        assert (Path(tmp_path) / "active").read_bytes() == b"cd"
    finally:
        log.close()
    broken = bg._RotatingLog(Path(tmp_path) / "broken", max_bytes=10)
    broken.open()
    monkeypatch.setattr(bg._os, "write", lambda fd, data: 0)
    try:
        with pytest.raises(OSError, match="no progress"):
            broken.write(b"x")
    finally:
        monkeypatch.undo()
        broken.close()


def test_drain_would_block_and_stream_close_errors(monkeypatch):
    stream = FakeStream(11, [b"x"])
    selector = FakeSelector({11: stream})
    log = SimpleNamespace(write=lambda data: None)
    monkeypatch.setattr(bg._os, "read", lambda fd, size: (_ for _ in ()).throw(BlockingIOError()))
    assert bg._drain(selector, {11: stream}, log) is False
    class BadStream(FakeStream):
        def close(self):
            raise OSError("close")
    bad = BadStream(12, [])
    selector2 = SimpleNamespace(close=lambda: None)
    bg._close_streams(selector2, {12: bad})


def test_cleanup_owned_all_outcomes(monkeypatch):
    class Child(FakeChild):
        start_time = 1
    child = Child(pid=1, polls=[None, 0, 0], wait_status=0)
    monkeypatch.setattr(bg._os, "killpg", lambda pid, sig: child.calls.append(("killpg", pid, sig)))
    assert bg._cleanup_owned(child, identity=(1, 1), identity_probe=lambda pid: (pid, 1)) is True
    mismatch = Child(pid=2, polls=[None, 0], wait_status=0)
    assert bg._cleanup_owned(mismatch, identity=(99, 1), identity_probe=lambda pid: (pid, 1)) is False
    class TimeoutChild(Child):
        def wait(self, timeout=None):
            self.calls.append(("wait", timeout))
            raise bg._subprocess.TimeoutExpired("x", timeout)
    timed = TimeoutChild(pid=3, polls=[None, None, 0], wait_status=0)
    assert bg._cleanup_owned(timed, identity=(3, 1), identity_probe=lambda pid: (pid, 1)) is False
    absent_error = Child(pid=4, polls=[0], wait_status=0)
    monkeypatch.setattr(absent_error, "poll", lambda: (_ for _ in ()).throw(OSError("poll")))
    assert bg._cleanup_owned(absent_error, identity=(4, 1), identity_probe=lambda pid: (pid, 1)) is False


def test_identity_and_signal_guards(monkeypatch):
    child = FakeChild(pid=8, polls=[None], wait_status=0)
    child.start_time = 3
    probe = lambda pid: (pid, 3)
    assert bg._child_identity(child, probe) == (8, 3, "authoritative")
    assert bg._identity_matches(child, (8, 3), probe)
    assert not bg._identity_matches(child, (8, 4), probe)
    calls = []
    monkeypatch.setattr(bg._os, "killpg", lambda *args: calls.append(args))
    bg._signal_owned(child, (8, 4), probe)
    assert not calls
    bg._signal_owned(child, (8, 3), probe)
    assert calls


def test_failure_class_precedence():
    child = FakeChild()
    assert bg._failure_class(KeyboardInterrupt(), child, False) == "unresolved_custody"
    assert bg._failure_class(KeyboardInterrupt(), child, True) == "cancellation"
    assert bg._failure_class(TimeoutError(), child, True) == "cleanup_timeout"
    assert bg._failure_class(OSError("relay"), child, True) == "relay_failure"
    assert bg._failure_class(OSError("startup"), None, True) == "startup_failure"


def test_cancel_requested_callback_fd_and_errors(monkeypatch):
    assert bg._cancel_requested(None, lambda: True)
    assert not bg._cancel_requested(None, lambda: False)
    monkeypatch.setattr(bg._os, "read", lambda fd, size: (_ for _ in ()).throw(BlockingIOError()))
    assert not bg._cancel_requested(3, None)
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"1")
    assert bg._cancel_requested(3, None)
    monkeypatch.setattr(bg._os, "read", lambda fd, size: (_ for _ in ()).throw(OSError("closed")))
    assert bg._cancel_requested(3, None)


def test_remove_lease_and_cleanup_request_errors(monkeypatch, tmp_path):
    class Lease:
        def unlink(self):
            raise OSError("busy")
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    bg._remove_lease(Path(tmp_path) / "log")
    missing = Path(tmp_path) / "missing"
    bg._cleanup_request(None)
    bg._cleanup_request(missing)
    monkeypatch.setattr(Path, "unlink", lambda self: (_ for _ in ()).throw(OSError("busy")))
    bg._cleanup_request(missing)


def test_supervisor_entry_valid_request(monkeypatch, tmp_path):
    request = Path(tmp_path) / "request.json"
    request.write_text(json.dumps({"kind": "workspace-agent-supervisor"}), encoding="utf-8")
    calls = []
    monkeypatch.setattr(bg, "_supervise", lambda req, fd, **kwargs: calls.append((req, fd, kwargs)))
    bg._supervisor_entry(str(request), 7)
    assert calls == [({"kind": "workspace-agent-supervisor"}, 7, {"cancel_fd": None})]
    assert not request.exists()


def test_cancel_background_success_and_unconfirmed(monkeypatch):
    monkeypatch.setattr(bg, "_cleanup_owned", lambda child, wait_timeout=0.25, **kwargs: True)
    started = {"launcher_pid": 7, "launcher_identity": "id"}
    ack = {"kind": "cleanup", "session": "s", "launcher_pid": 7,
           "launcher_identity": "id", "cleanup_confirmed": True}
    assert bg.cancel_background(object(), started=started, cleanup_ack=ack,
                                session_id="s")["exit_code"] == 130
    monkeypatch.setattr(bg, "_cleanup_owned", lambda child, wait_timeout=0.25, **kwargs: False)
    with pytest.raises(bg.BackgroundUnconfirmed):
        bg.cancel_background(object(), started=started, cleanup_ack=ack, session_id="s")


def test_default_popen_is_call_time_seam(monkeypatch):
    called = []
    monkeypatch.setattr(bg._subprocess, "Popen", lambda *a, **k: called.append((a, k)) or "child")
    assert bg._default_popen("cmd") == "child"
    assert called


class _ImmediateSupervisor:
    def __init__(self, polls=None, max_polls=300):
        self.polls = list([None] * max_polls + [1] if polls is None else polls)
        if self.polls and all(status is None for status in self.polls):
            self.polls.append(1)
        self.calls = []
        self.pid = 9001
        self.start_time = 1

    def poll(self):
        self.calls.append("poll")
        if not self.polls:
            raise AssertionError("fake child script exhausted")
        return self.polls.pop(0)

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        return 0

    def terminate(self):
        self.calls.append("terminate")

    def kill(self):
        self.calls.append("kill")


def _patch_launch_background_common(monkeypatch, tmp_path, frames, *, supervisor=None):
    clock = FakeClock()
    supervisor = supervisor or _ImmediateSupervisor()
    request_path = Path(tmp_path) / "request.json"
    monkeypatch.setattr(bg, "get_topsailai_home", lambda: str(tmp_path))
    monkeypatch.setattr(bg, "_request_file", lambda folder, request: (request_path, 0))
    monkeypatch.setattr(bg, "_cleanup_request", lambda path: None)
    monkeypatch.setattr(bg._os, "pipe", lambda: (10, 11))
    monkeypatch.setattr(bg._os, "close", _fake_close({10, 11}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda fd, flag: None)
    monkeypatch.setattr(bg, "_entrypoint_command", lambda base_dir=None: ["fake-cli"])
    monkeypatch.setattr(bg, "_cleanup_owned", lambda child, wait_timeout=0.25, identity=None, **kwargs: True)
    def read_frames(fd, buffer):
        batch = frames.pop(0) if frames else []
        normalized = []
        for frame in batch:
            if frame.get("kind") == "started":
                frame = dict(frame)
                frame.setdefault("session", "s")
                frame.setdefault("launcher_identity", f"identity:{frame.get('launcher_pid')}")
            normalized.append(frame)
        return normalized
    monkeypatch.setattr(bg, "_read_frames", read_frames)
    return clock, supervisor

def test_launch_background_success_consumes_started_and_submitted(monkeypatch, tmp_path):
    log_path = str(tmp_path / "workspace" / "task" / "s.agent-launch.log")
    frames = [[{"kind": "started", "launcher_pid": 77}],
              [{"kind": "submitted", "session": "s", "launcher_pid": 77,
                "log_path": log_path}]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    calls = []
    result = bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: calls.append((a, k)) or supervisor,
                                  clock=clock, sleeper=clock.sleep)
    assert result["outcome"] == "submitted"
    assert result["launcher_pid"] == 77
    assert calls[0][1]["stdin"] is bg._subprocess.DEVNULL


def test_launch_background_spawn_and_request_failure_cleanup(monkeypatch, tmp_path):
    monkeypatch.setattr(bg, "get_topsailai_home", lambda: str(tmp_path))
    monkeypatch.setattr(bg, "_request_file", lambda *a: (_ for _ in ()).throw(OSError("request")))
    with pytest.raises(OSError, match="request"):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: pytest.fail("spawn"))
    frames = []
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    with pytest.raises(bg.BackgroundUnconfirmed, match="initialization"):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=clock, sleeper=clock.sleep)


def test_launch_background_failure_and_unconfirmed_ack(monkeypatch, tmp_path):
    failure = {"kind": "failure", "error": "relay", "cleanup_confirmed": True}
    started = {"kind": "started", "launcher_pid": 701}
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path,
                                                         [[started], [failure]])
    with pytest.raises(bg.BackgroundUnconfirmed, match="custody|timed out"):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=clock, sleeper=clock.sleep)
    failure["cleanup_confirmed"] = False
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path,
                                                         [[started], [failure]])
    with pytest.raises(bg.BackgroundUnconfirmed):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=clock, sleeper=clock.sleep)


def test_launch_background_early_exit_and_observation_timeout(monkeypatch, tmp_path):
    early = {"kind": "early_exit", "code": 7}
    started = {"kind": "started", "launcher_pid": 702}
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path,
                                                         [[started], [early]])
    with pytest.raises(bg.BackgroundUnconfirmed, match="custody|timed out"):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=clock, sleeper=clock.sleep)
    clock, supervisor = _patch_launch_background_common(
        monkeypatch, tmp_path, [[started]])
    with pytest.raises(bg.BackgroundUnconfirmed, match="timed out"):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=clock, sleeper=clock.sleep)


def test_launch_background_supervisor_exit_and_cleanup_unconfirmed(monkeypatch, tmp_path):
    clock, supervisor = _patch_launch_background_common(
        monkeypatch, tmp_path, [[]], supervisor=_ImmediateSupervisor([1]))
    with pytest.raises(RuntimeError, match="initialization"):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=clock, sleeper=clock.sleep)
    clock, supervisor = _patch_launch_background_common(
        monkeypatch, tmp_path, [[{"kind": "started", "launcher_pid": 1}]],
        supervisor=_ImmediateSupervisor([None] * 300 + [1]))
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *a, **k: False)
    with pytest.raises(bg.BackgroundUnconfirmed):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=clock, sleeper=clock.sleep)


def test_supervise_cancellation_and_missing_pipes(monkeypatch, tmp_path):
    sent = []
    class Lease:
        def touch(self, **kwargs): pass
        def unlink(self): pass
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    monkeypatch.setattr(bg, "_close_streams", lambda selector, streams: None)
    monkeypatch.setattr(bg, "_remove_lease", lambda path: None)
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *a, **k: True)
    monkeypatch.setattr(bg, "_RotatingLog", lambda path: SimpleNamespace(open=lambda: None, close=lambda: None))
    monkeypatch.setattr(bg._os, "close", _fake_close({3}))
    child = FakeChild(pid=55)
    child.stdout = None
    child.stderr = None
    request = {"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s.log")}
    bg._supervise(request, 3, popen=lambda *a, **k: child)
    assert sent[0]["kind"] == "cleanup"
    sent.clear()
    child.stdout = FakeStream(11, [])
    child.stderr = FakeStream(12, [])
    monkeypatch.setattr(bg._selectors, "DefaultSelector", lambda: FakeSelector({11: child.stdout, 12: child.stderr}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *a: None)
    monkeypatch.setattr(bg._os, "read", lambda *a: b"")
    clock = FakeClock()
    bg._supervise(request, 3, popen=lambda *a, **k: child, clock=clock, sleeper=clock.sleep,
                   cancel_requested=lambda: True)
    assert any(frame.get("class") == "cancellation" for frame in sent)


def test_supervise_submitted_lifecycle_and_drain_deadline(monkeypatch, tmp_path):
    sent = []
    class Lease:
        def touch(self, **kwargs): pass
        def unlink(self): pass
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    monkeypatch.setattr(bg, "_close_streams", lambda selector, streams: None)
    monkeypatch.setattr(bg, "_remove_lease", lambda path: None)
    close_calls = []
    log = SimpleNamespace(
        open=lambda: None,
        close=lambda: close_calls.append("close"),
        write=lambda data: None,
    )
    monkeypatch.setattr(bg, "_RotatingLog", lambda path: log)
    child = FakeChild(pid=56, polls=[None] * 100 + [0], wait_status=0)
    child.stdout = FakeStream(11, [b"x"])
    child.stderr = FakeStream(12, [b"y"])
    monkeypatch.setattr(bg._selectors, "DefaultSelector", lambda: FakeSelector({11: child.stdout, 12: child.stderr}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *a: None)
    reads = {11: [b"x", b""], 12: [b"y", b""]}
    monkeypatch.setattr(bg._os, "read", lambda fd, size: reads[fd].pop(0))
    monkeypatch.setattr(bg._os, "close", _fake_close({3}))
    clock = FakeClock()
    bg._supervise({"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s.log")}, 3,
                   popen=lambda *a, **k: child, clock=clock, sleeper=clock.sleep)
    assert [frame["kind"] for frame in sent] == ["started", "submitted"]
    assert close_calls == ["close"]


# UNIT 1B-1 round 4 proofs for the remaining lifecycle contracts.
def test_authoritative_identity_probe_and_signal_refusal(monkeypatch):
    child = FakeChild(pid=901, polls=[None], wait_status=0)
    monkeypatch.setattr(bg, "_authoritative_child_identity", lambda pid: (pid, 77))
    assert bg._authoritative_child_identity(child.pid) == (901, 77)
    child.start_time = 77
    assert bg._identity_matches(child, (901, 77))
    child.start_time = 78
    calls = []
    monkeypatch.setattr(bg, "_signal_owned", lambda *args, **kwargs: calls.append(args))
    assert bg._child_absent(child, (901, 77)) is False
    assert calls == []


def test_identity_unverifiable_returns_unconfirmed(monkeypatch):
    child = FakeChild(pid=902, polls=[None], wait_status=0)
    monkeypatch.setattr(bg, "_authoritative_child_identity", lambda pid: None)
    assert bg._authoritative_child_identity(child.pid) is None
    signals = []
    monkeypatch.setattr(bg._os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    assert bg._cleanup_owned(child, identity=(902, 1)) is False
    assert signals == []


def test_consumer_local_spawn_guard_fires_without_injection(monkeypatch):
    calls = []
    monkeypatch.setattr(bg, "_default_popen", lambda *args, **kwargs: calls.append(args) or pytest.fail("unguarded spawn"))
    with pytest.raises(AssertionError, match="injected"):
        bg._require_injected_spawn(None)
    assert calls == []


def test_cleanup_acknowledgement_order_and_parent_cancel_transport():
    written = []

    def fake_write(fd, payload):
        written.append((fd, bytes(payload)))
        return len(payload)

    def fake_cleanup(supervisor):
        return {
            "outcome": "cancelled",
            "cleanup_confirmed": True,
            "exit_code": 130,
        }

    result = bg._cancel_supervisor_transport(
        object(), 4, write=fake_write, cleanup=fake_cleanup
    )
    assert written == [(4, b"1")]
    assert result == {
        "outcome": "cancelled",
        "cleanup_confirmed": True,
        "exit_code": 130,
    }

def test_cancel_transport_supervisor_gone_is_exit_six(monkeypatch):
    child = FakeChild(pid=904, polls=[0], wait_status=0)
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *args, **kwargs: False)
    with pytest.raises(bg.BackgroundUnconfirmed):
        bg._cancel_supervisor_transport(child, 4)


def _public_cancel_fixture(monkeypatch, tmp_path, frames):
    """Build an all-local public cancellation launch fixture."""
    monkeypatch.setattr(bg, "get_topsailai_home", lambda: str(tmp_path))
    request_path = tmp_path / "request.json"
    monkeypatch.setattr(bg, "_request_file", lambda folder, request: (request_path, 0))
    monkeypatch.setattr(bg, "_cleanup_request", lambda path: None)
    monkeypatch.setattr(bg._os, "pipe", lambda: (10, 11) if not hasattr(_public_cancel_fixture, "used") else (12, 13))
    _public_cancel_fixture.used = True
    monkeypatch.setattr(bg._os, "close", _fake_close({10, 11, 12, 13}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda fd, flag: None)
    monkeypatch.setattr(bg, "_entrypoint_command", lambda base_dir=None: ["fake-cli"])
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *args, **kwargs: True)
    monkeypatch.setattr(bg, "_read_frames", lambda fd, buffer: frames.pop(0) if frames else [])

    supervisor = _ImmediateSupervisor([None] * 8)
    return supervisor


def test_public_cancel_before_submission(monkeypatch, tmp_path):
    supervisor = _public_cancel_fixture(monkeypatch, tmp_path, [[{"kind": "cleanup", "class": "cancellation",
        "launcher_pid": 7, "cleanup_confirmed": True, "launcher_identity": "x"}]])
    with pytest.raises(bg.BackgroundUnconfirmed):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=FakeClock(), sleeper=lambda _: None,
                             cancel_requested=lambda: True, cancel_write=lambda fd, payload: 1)


def test_public_cancel_after_submission_request(monkeypatch, tmp_path):
    supervisor = _public_cancel_fixture(monkeypatch, tmp_path,
        [[{"kind": "started", "session": "s", "launcher_pid": 7, "launcher_identity": "x"}],
         [{"kind": "cleanup", "class": "cancellation", "session": "s", "launcher_pid": 7,
           "cleanup_confirmed": True, "launcher_identity": "x"}]])
    writes = []
    calls = iter([False, True])
    result = bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                                  clock=FakeClock(), sleeper=lambda _: None,
                                  cancel_requested=lambda: next(calls),
                                  cancel_write=lambda fd, payload: writes.append((fd, payload)) or 1)
    assert result["exit_code"] == 130
    assert writes == [(13, b"1")]



def test_public_cancel_supervisor_gone_is_unconfirmed(monkeypatch, tmp_path):
    supervisor = _public_cancel_fixture(monkeypatch, tmp_path, [[]])
    supervisor.poll = lambda: 1
    with pytest.raises(bg.BackgroundUnconfirmed):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=FakeClock(), sleeper=lambda _: None,
                             cancel_requested=lambda: True,
                             cancel_write=lambda fd, payload: 1)

# UNIT 1B-1 round 9 line-specific behavior proofs.
def test_r9_read_frames_clean_eof_and_oversized(monkeypatch):
    class LocalOS:
        def __init__(self, result):
            self.result = result
        def read(self, fd, size):
            return self.result
    monkeypatch.setattr(bg, "_os", LocalOS(b""))
    assert bg._read_frames(4, bytearray()) == []
    monkeypatch.setattr(bg, "_os", LocalOS(b"x" * (bg._MAX_FRAME_BYTES + 1)))
    with pytest.raises(ValueError, match="too large"):
        bg._read_frames(4, bytearray())


def test_r9_cleanup_escalates_and_reports_final_reap_timeout(monkeypatch):
    signal_calls = []

    class Child(FakeChild):
        def __init__(self, waits):
            super().__init__(pid=1001, polls=[None, None, 0, 0])
            self.waits = iter(waits)

        def wait(self, timeout=None):
            self.calls.append(("wait", timeout))
            outcome = next(self.waits)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    monkeypatch.setattr(bg._os, "killpg", lambda pid, sig: signal_calls.append(("terminate", pid, sig)))
    child = Child([
        bg._subprocess.TimeoutExpired("term", 1),
        bg._subprocess.TimeoutExpired("kill", 1),
    ])
    assert bg._cleanup_owned(
        child,
        identity=(1001, 9, "authoritative"),
        identity_probe=lambda pid: (pid, 9),
    ) is False
    assert signal_calls == [("terminate", 1001, bg.signal.SIGTERM)]
    assert child.calls[:4] == ["poll", "poll", ("wait", 0.25), "kill"]
    assert "kill" in child.calls
    assert child.calls.count(("wait", 0.25)) == 2

    child2 = Child([OSError("reap")])
    assert bg._cleanup_owned(
        child2,
        identity=(1001, 9, "authoritative"),
        identity_probe=lambda pid: (pid, 9),
    ) is False
    assert child2.calls[:3] == ["poll", "poll", ("wait", 0.25)]


def test_r9_default_identity_probe_success_and_unavailable(monkeypatch):
    class FakeStat:
        def __init__(self, text):
            self.text = text
        def read_text(self, encoding=None):
            return self.text
    class LocalPath:
        def __init__(self, value):
            self.value = value
        def read_text(self, encoding=None):
            return FakeStat(LocalPath.text).read_text(encoding=encoding)
    LocalPath.text = "1 (name) S " + " ".join(str(i) for i in range(1, 22))
    monkeypatch.setattr(bg, "Path", LocalPath)
    assert bg._authoritative_child_identity(77) == (77, 19)
    class MissingPath(LocalPath):
        def read_text(self, encoding=None):
            raise OSError("missing")
    monkeypatch.setattr(bg, "Path", MissingPath)
    assert bg._authoritative_child_identity(77) is None


def test_r9_cancel_transport_write_failure():
    with pytest.raises(bg.BackgroundUnconfirmed, match="transport failed"):
        bg._cancel_supervisor_transport(object(), 4,
                                        write=lambda fd, payload: 0,
                                        cleanup=lambda supervisor: pytest.fail("cleanup called"))


def test_r9_identity_unverifiable_and_mismatch_paths():
    child = FakeChild(pid=1002, polls=[None])
    assert bg._child_identity(child, lambda pid: None) == (1002, None, "unverifiable")
    assert not bg._identity_matches(child, (1002, 3, "authoritative"),
                                    lambda pid: (pid, 4))
    assert not bg._child_absent(child, (1002, None, "unverifiable"),
                                lambda pid: None)
    child.polls = [None]
    assert bg._child_absent(child, (1002, 3, "authoritative"),
                            lambda pid: (pid, 3)) is False


def test_r9_supervise_initial_cancel_and_relay_errors(monkeypatch, tmp_path):
    sent = []
    class Lease:
        def touch(self, **kwargs): pass
        def unlink(self): pass
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *args, **kwargs: True)
    monkeypatch.setattr(bg, "_close_streams", lambda selector, streams: None)
    monkeypatch.setattr(bg, "_remove_lease", lambda path: None)
    monkeypatch.setattr(bg, "_RotatingLog", lambda path: SimpleNamespace(
        open=lambda: None, close=lambda: None, write=lambda data: None))
    child = FakeChild(pid=1003, polls=[None])
    child.stdout = FakeStream(11, [])
    child.stderr = FakeStream(12, [])
    monkeypatch.setattr(bg._selectors, "DefaultSelector",
                        lambda: FakeSelector({11: child.stdout, 12: child.stderr}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *args: None)
    monkeypatch.setattr(bg._os, "close", _fake_close({3}))
    bg._supervise({"folder": str(tmp_path), "session_id": "s",
                   "log_path": str(tmp_path / "s.log")}, 3,
                  popen=lambda *args, **kwargs: child,
                  cancel_requested=lambda: True)
    assert sent[-1]["class"] == "cancellation"


def test_r9_supervisor_entry_cleanup_unlink_errors(monkeypatch, tmp_path):
    request = Path(tmp_path) / "request.json"
    request.write_text(json.dumps({"kind": "wrong"}), encoding="utf-8")
    class LocalPath(type(request)):
        pass
    original_unlink = Path.unlink
    monkeypatch.setattr(Path, "unlink", lambda self: (_ for _ in ()).throw(OSError("busy")))
    try:
        with pytest.raises(ValueError, match="invalid supervisor"):
            bg._supervisor_entry(str(request), 3)
    finally:
        monkeypatch.setattr(Path, "unlink", original_unlink)


def test_r9_launch_cancel_ack_validation_paths(monkeypatch, tmp_path):
    frames = [[{"kind": "started", "launcher_pid": 1}],
              [{"kind": "cleanup", "class": "x", "cleanup_confirmed": False}]]
    supervisor = _public_cancel_fixture(monkeypatch, tmp_path, frames)
    with pytest.raises(bg.BackgroundUnconfirmed):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=FakeClock(), sleeper=lambda _: None,
                             cancel_requested=lambda: True,
                             cancel_write=lambda fd, payload: 1)

# UNIT 1B-1 round 11 terminal behavior proofs.
def test_r11_cleanup_reaps_already_exited_and_escalates_identity_loss(monkeypatch):
    class Child(FakeChild):
        def __init__(self, polls, waits):
            super().__init__(pid=1101, polls=polls)
            self.waits = iter(waits)

        def wait(self, timeout=None):
            self.calls.append(("wait", timeout))
            outcome = next(self.waits)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    probe = lambda pid: (pid, 11)
    exited = Child([0, 0], [0])
    assert bg._cleanup_owned(exited, identity=(1101, 11, "authoritative"), identity_probe=probe)
    assert ("wait", 0.25) in exited.calls

    signals = []
    monkeypatch.setattr(bg._os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    reused = Child([None, None, None], [bg._subprocess.TimeoutExpired("term", 1)])
    reused_probe = iter([(1101, 11), (1101, 11), (1101, 12)])
    assert not bg._cleanup_owned(reused, identity=(1101, 11, "authoritative"),
                                  identity_probe=lambda pid: next(reused_probe))
    assert signals == [(1101, bg.signal.SIGTERM)]

    reaped = Child([None, None, 0], [bg._subprocess.TimeoutExpired("term", 1), 0])
    assert bg._cleanup_owned(reaped, identity=(1101, 11, "authoritative"), identity_probe=probe)
    assert "kill" in reaped.calls


def test_b16_relay_faults_classify_and_close_owned_resources(monkeypatch, tmp_path):
    """Relay select/read/write faults are classified and every owned resource is closed."""
    sent = []

    class Lease:
        def touch(self, **kwargs): pass
        def unlink(self): pass

    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *a, **k: True)
    monkeypatch.setattr(bg, "_remove_lease", lambda path: None)
    monkeypatch.setattr(bg._os, "set_blocking", lambda *a: None)
    monkeypatch.setattr(bg._os, "close", lambda *a: None)

    class SilentLog:
        def open(self): pass
        def close(self): pass
        def write(self, data): pass

    monkeypatch.setattr(bg, "_RotatingLog", lambda path: SilentLog())

    # Select failure: the selector primitive itself faults.
    class BadSelector(FakeSelector):
        def select(self, timeout=0):
            raise OSError("select")

    child = FakeChild(pid=1102, polls=[None])
    child.stdout, child.stderr = FakeStream(11, [b"x"]), FakeStream(12, [])
    monkeypatch.setattr(bg._selectors, "DefaultSelector",
                        lambda: BadSelector({11: child.stdout, 12: child.stderr}))
    bg._supervise({"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s.log")}, 3,
                  popen=lambda *a, **k: child)
    assert sent[-1]["kind"] == "failure"
    assert child.stdout.closed and child.stderr.closed

    # Relay read failure: the real _drain body raises from the stream read primitive.
    sent.clear()
    child = FakeChild(pid=1103, polls=[None])
    child.stdout, child.stderr = FakeStream(13, [b"x"]), FakeStream(14, [])
    selector = FakeSelector({13: child.stdout, 14: child.stderr})
    monkeypatch.setattr(bg._selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(bg._os, "read",
                        lambda fd, size: (_ for _ in ()).throw(OSError("relay read")))
    bg._supervise({"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s2.log")}, 3,
                  popen=lambda *a, **k: child)
    assert sent[-1]["class"] == "relay_failure"
    assert child.stdout.closed and child.stderr.closed and selector.closed

    # Relay write failure: the real _drain body raises from the log write primitive.
    sent.clear()
    child = FakeChild(pid=1104, polls=[None])
    child.stdout, child.stderr = FakeStream(15, [b"x"]), FakeStream(16, [])
    selector = FakeSelector({15: child.stdout, 16: child.stderr})

    class FailingLog(SilentLog):
        def write(self, data):
            raise OSError("relay write")

    monkeypatch.setattr(bg, "_RotatingLog", lambda path: FailingLog())
    monkeypatch.setattr(bg._selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"data")
    bg._supervise({"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s3.log")}, 3,
                  popen=lambda *a, **k: child)
    assert sent[-1]["class"] == "relay_failure"
    assert child.stdout.closed and child.stderr.closed and selector.closed


def test_r11_supervisor_entry_unlink_oserror_is_tolerated(monkeypatch, tmp_path):
    request = Path(tmp_path) / "bad.json"
    request.write_text(json.dumps({"kind": "wrong"}), encoding="utf-8")
    monkeypatch.setattr(Path, "unlink", lambda self: (_ for _ in ()).throw(OSError("busy")))
    with pytest.raises(ValueError, match="invalid supervisor"):
        bg._supervisor_entry(str(request), 3)


def test_r11_launch_cleanup_ack_required_fields_and_outcomes(monkeypatch, tmp_path):
    for frame in [
        {"kind": "cleanup", "class": "x", "cleanup_confirmed": True},
        {"kind": "cleanup", "class": "x", "launcher_pid": 1, "cleanup_confirmed": True},
        {"kind": "cleanup", "class": "x", "launcher_pid": 1, "launcher_identity": "i", "cleanup_confirmed": False},
    ]:
        supervisor = _ImmediateSupervisor([None] * 4)
        clock, _ = _patch_launch_background_common(monkeypatch, tmp_path,
            [[{"kind": "started", "launcher_pid": 1}], [frame]], supervisor=supervisor)
        with pytest.raises(bg.BackgroundUnconfirmed):
            bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                                 clock=clock, sleeper=clock.sleep,
                                 cancel_requested=lambda: True, cancel_write=lambda fd, data: 1)


def test_r11_launch_transport_and_close_failures(monkeypatch, tmp_path):
    """A transport read failure plus teardown close failures still reports custody."""
    monkeypatch.setattr(bg, "get_topsailai_home", lambda: str(tmp_path))
    monkeypatch.setattr(bg, "_request_file", lambda folder, request: (tmp_path / "r", 0))
    monkeypatch.setattr(bg, "_cleanup_request", lambda path: None)
    calls = iter([(10, 11), (12, 13)])
    monkeypatch.setattr(bg._os, "pipe", lambda: next(calls))
    close_calls = []

    def close(fd):
        close_calls.append(fd)
        if fd in (10, 13):
            raise OSError("close")

    monkeypatch.setattr(bg._os, "close", close)
    monkeypatch.setattr(bg._os, "set_blocking", lambda *a: None)
    monkeypatch.setattr(bg._os, "read", lambda fd, size: (_ for _ in ()).throw(OSError("transport")))
    monkeypatch.setattr(bg, "_entrypoint_command", lambda base_dir=None: ["fake"])
    supervisor = _ImmediateSupervisor([None, None])
    with pytest.raises(bg.BackgroundUnconfirmed, match="custody unproven"):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=FakeClock(), sleeper=lambda _: None)
    assert close_calls == [11, 12, 10, 13]


def test_r11_agent_launch_background_dispatches_selected_mechanism(monkeypatch, tmp_path):
    """A background terminal mechanism reaches the terminal submit path."""
    from cli_topsailai import agent_launch as al
    from cli_topsailai import agent_launch_terminal as term

    submitted = []

    def submit(folder, session_id, **kwargs):
        submitted.append((folder, session_id, kwargs))
        return {"outcome": "submitted", "launcher_pid": 4242,
                "log_path": "/tmp/x.log", "session_id": session_id}

    monkeypatch.setattr(al, "_prepare_environment", lambda folder, session_id: ((), {}, {}, {}))
    monkeypatch.setattr(term, "submit_terminal", submit)
    monkeypatch.setattr(al, "submit_terminal", submit, raising=False)
    assert al._launch_configured_agent_impl(
        str(tmp_path), mode="tmux", background=True,
        spawn=lambda *a, **k: pytest.fail("foreground spawn")) == 0
    assert submitted[0][2]["mechanism"] == "tmux"


# UNIT 1B-1 round 12 targeted residual branch proofs.
def test_r12_child_absent_live_and_unverifiable(monkeypatch):
    child = FakeChild(pid=1201, polls=[None])
    assert bg._child_absent(child, (1201, 12, "authoritative"),
                            lambda pid: (pid, 12)) is False
    assert bg._child_identity(child, lambda pid: None) == (1201, None, "unverifiable")


def test_r12_supervise_initial_cancel_and_default_popen(monkeypatch, tmp_path):
    sent = []
    child = FakeChild(pid=1202, polls=[None])
    child.stdout = FakeStream(21, [])
    child.stderr = FakeStream(22, [])
    class Lease:
        def touch(self, **kwargs): pass
        def unlink(self): pass
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_RotatingLog", lambda path: SimpleNamespace(open=lambda: None, close=lambda: None, write=lambda data: None))
    spawned = []
    monkeypatch.setattr(bg, "_default_popen",
                        lambda *args, **kwargs: spawned.append(args) or child)
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *args, **kwargs: True)
    monkeypatch.setattr(bg, "_close_streams", lambda selector, streams: None)
    monkeypatch.setattr(bg, "_remove_lease", lambda path: None)
    monkeypatch.setattr(bg._selectors, "DefaultSelector", lambda: FakeSelector({21: child.stdout, 22: child.stderr}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *args: None)
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    bg._supervise({"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s.log")}, 3,
                  cancel_requested=lambda: True)
    # A cancellation that is already pending must abort BEFORE the launcher
    # exists, so no process is created that nobody owns.
    assert spawned == []
    assert sent[0]["kind"] == "cleanup"
    assert sent[0]["class"] == "cancellation"
    assert sent[-1]["class"] == "cancellation"


def test_r12_supervise_drain_close_postsubmission_and_relay_errors(monkeypatch, tmp_path):
    class Lease:
        def touch(self, **kwargs): pass
        def unlink(self): pass
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_RotatingLog", lambda path: SimpleNamespace(open=lambda: None, close=lambda: None, write=lambda data: None))
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *args, **kwargs: True)
    monkeypatch.setattr(bg, "_remove_lease", lambda path: None)
    monkeypatch.setattr(bg, "_close_streams", lambda selector, streams: None)
    monkeypatch.setattr(bg._os, "set_blocking", lambda *args: None)
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    sent = []
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    child = FakeChild(pid=1203, polls=[0])
    child.stdout, child.stderr = FakeStream(23, [b"pending"]), FakeStream(24, [])
    monkeypatch.setattr(bg._selectors, "DefaultSelector", lambda: FakeSelector({23: child.stdout, 24: child.stderr}))
    clock = FakeClock()
    # Execute the real _drain body: the relay read primitive reports EOF so the
    # pending stream is unregistered and closed by _drain itself.
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"")
    bg._supervise({"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s.log")}, 3,
                  popen=lambda *args, **kwargs: child, clock=clock, sleeper=clock.sleep)
    assert sent[-1]["kind"] == "early_exit"
    assert child.stdout.closed

    sent.clear()
    child = FakeChild(pid=1204, polls=[None, 0, 0], wait_status=0)
    # A ready chunk makes the selector report the stream so the real _drain body
    # reaches its read primitive and the injected read fault is exercised.
    child.stdout, child.stderr = FakeStream(25, [b"x"]), FakeStream(26, [])
    monkeypatch.setattr(bg._selectors, "DefaultSelector", lambda: FakeSelector({25: child.stdout, 26: child.stderr}))
    # Execute the real _drain body: the relay read primitive itself faults.
    monkeypatch.setattr(bg._os, "read", lambda fd, size: (_ for _ in ()).throw(OSError("relay read")))
    bg._supervise({"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s2.log")}, 3,
                  popen=lambda *args, **kwargs: child, clock=FakeClock(), sleeper=lambda _: None)
    assert sent[-1]["class"] == "relay_failure"


def test_r12_supervise_ack_and_selector_failures_are_bounded(monkeypatch, tmp_path):
    class Lease:
        def touch(self, **kwargs): pass
        def unlink(self): pass
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_RotatingLog", lambda path: SimpleNamespace(open=lambda: None, close=lambda: None, write=lambda data: None))
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *args, **kwargs: True)
    monkeypatch.setattr(bg, "_remove_lease", lambda path: None)
    monkeypatch.setattr(bg, "_close_streams", lambda selector, streams: None)
    monkeypatch.setattr(bg._os, "set_blocking", lambda *args: None)
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    sent = []
    def send(fd, payload):
        sent.append(payload)
        if payload.get("kind") in {"cleanup", "failure"}:
            raise OSError("ack closed")
    monkeypatch.setattr(bg, "_send_frame", send)
    child = FakeChild(pid=1205, polls=[None, 42])
    child.stdout, child.stderr = FakeStream(27, []), FakeStream(28, [])
    class Selector(FakeSelector):
        def select(self, timeout=0):
            raise OSError("selector")
    monkeypatch.setattr(bg._selectors, "DefaultSelector", lambda: Selector({27: child.stdout, 28: child.stderr}))
    bg._supervise({"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s.log")}, 3,
                  popen=lambda *args, **kwargs: child, clock=FakeClock(), sleeper=lambda _: None)
    assert sent[0]["kind"] == "started"
    assert sent[-1]["kind"] == "failure"
    assert sent[-1]["class"] == "relay_failure"
    assert not child.calls


def test_r12_launch_failure_frames_and_environment(monkeypatch, tmp_path):
    log_path = str(tmp_path / "workspace" / "task" / "s.agent-launch.log")
    frames = [[{"kind": "started", "launcher_pid": 1206}],
              [{"kind": "failure", "error": "relay", "cleanup_confirmed": True}]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    with pytest.raises(bg.BackgroundUnconfirmed, match="custody"):
        bg.launch_background(str(tmp_path), "s", environment={"X": "1"},
                             spawn=lambda *args, **kwargs: supervisor,
                             clock=clock, sleeper=clock.sleep)


def test_r12_launch_before_started_and_observation_failure(monkeypatch, tmp_path):
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, [[]],
                                                         supervisor=_ImmediateSupervisor([1]))
    with pytest.raises(RuntimeError, match="initialization"):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *args, **kwargs: supervisor,
                             clock=clock, sleeper=clock.sleep)
    clock, supervisor = _patch_launch_background_common(
        monkeypatch, tmp_path, [[{"kind": "started", "launcher_pid": 1207}]],
        supervisor=_ImmediateSupervisor([None] * 300 + [1]))
    with pytest.raises(bg.BackgroundUnconfirmed, match="custody|timed out"):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *args, **kwargs: supervisor,
                             clock=clock, sleeper=clock.sleep)


def test_r14_authoritative_identity_reads_current_process(monkeypatch):
    """The default identity probe returns a tuple for the current test process."""
    identity = bg._authoritative_child_identity(bg._os.getpid())
    assert identity is not None
    assert identity[0] == bg._os.getpid()


def test_r14_child_absent_matching_identity_reports_live(monkeypatch):
    """A matching identity plus a live poll cannot prove child absence."""
    child = FakeChild(pid=1401, polls=[None])
    assert bg._child_absent(child, (1401, 14, "authoritative"),
                            lambda pid: (pid, 14)) is False
    assert child.calls == ["poll"]


def test_r14_child_identity_unverifiable_is_explicit():
    """A missing authority token is exposed as unverifiable custody evidence."""
    child = FakeChild(pid=1402, polls=[0])
    assert bg._child_identity(child, lambda pid: None) == (
        1402, None, "unverifiable")


def test_r14_supervisor_entry_rejects_malformed_request(monkeypatch, tmp_path):
    """Malformed private requests are rejected after their file is consumed."""
    request = tmp_path / "request.json"
    request.write_text('{"kind":"wrong"}', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid supervisor request"):
        bg._supervisor_entry(str(request), 7)
    assert not request.exists()

# UNIT 1B-1 round 15: exercise real bodies with primitive-level failures.
def test_r15_child_absent_poll_oserror_is_unproven():
    class PollErrorChild:
        pid = 1501

        def poll(self):
            raise OSError("poll unavailable")

    child = PollErrorChild()
    assert bg._child_absent(child, (1501, 15, "authoritative"),
                            lambda pid: (pid, 15)) is False


def test_r15_child_identity_tuple_token_is_authoritative():
    child = FakeChild(pid=1502, polls=[0])
    assert bg._child_identity(child, lambda pid: (pid, 15)) == (
        1502, 15, "authoritative")


def test_r15_supervisor_entry_consumes_request_before_validation(monkeypatch, tmp_path):
    request = tmp_path / "request.json"
    request.write_text('{"kind":"wrong"}', encoding="utf-8")
    original_loads = bg._json.load

    def load_and_consume(handle):
        value = original_loads(handle)
        request.unlink()
        return value

    monkeypatch.setattr(bg._json, "load", load_and_consume)
    with pytest.raises(ValueError, match="invalid supervisor request"):
        bg._supervisor_entry(str(request), 7)
    assert not request.exists()


def test_r15_supervise_real_deadline_early_exit_path(monkeypatch, tmp_path):
    class Lease:
        def touch(self, **kwargs):
            pass

        def unlink(self):
            pass

    class StepClock:
        def __init__(self):
            self.calls = 0

        def __call__(self):
            self.calls += 1
            if self.calls > 20:
                raise AssertionError("fake clock budget exhausted")
            return float(self.calls - 1)

        def sleep(self, seconds):
            pass

    child = FakeChild(pid=1503, polls=[42], wait_status=42)
    child.stdout = FakeStream(31, [])
    child.stderr = FakeStream(32, [])
    sent = []
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_RotatingLog", lambda path: SimpleNamespace(
        open=lambda: None, close=lambda: None, write=lambda data: None))
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    monkeypatch.setattr(bg, "_close_streams", lambda selector, streams: None)
    monkeypatch.setattr(bg, "_remove_lease", lambda path: None)
    monkeypatch.setattr(bg._os, "set_blocking", lambda *args: None)
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"")
    child.stdout.chunks = [b""]
    child.stderr.chunks = [b""]
    monkeypatch.setattr(bg._selectors, "DefaultSelector",
                        lambda: FakeSelector({31: child.stdout, 32: child.stderr}))
    bg._supervise(
        {"folder": str(tmp_path), "session_id": "s",
         "log_path": str(tmp_path / "s.log")},
        3, popen=lambda *args, **kwargs: child,
        clock=StepClock(), sleeper=lambda seconds: None,
        identity_probe=lambda pid: (pid, 15),
    )
    assert sent[-1]["kind"] == "early_exit"
    assert sent[-1]["code"] == 42
    # The boundary-poll early exit must reap the launcher and publish correlated
    # cleanup proof, so custody is provable instead of merely assumed.
    assert [frame["kind"] for frame in sent] == ["started", "cleanup", "early_exit"]
    assert sent[1]["cleanup_confirmed"] is True
    assert child.calls == ["poll", ("wait", 1.0)]


@pytest.mark.parametrize("confirmed, expected", [(False, bg.BackgroundUnconfirmed),
                                                   (True, RuntimeError)])
def test_r15_launch_real_frame_validation(monkeypatch, tmp_path, confirmed, expected):
    request_path = tmp_path / "request.json"
    frames = iter([json.dumps({
        "kind": "failure", "error": "forced", "cleanup_confirmed": confirmed,
    }).encode() + b"\n", b""])
    supervisor = _ImmediateSupervisor([1])
    monkeypatch.setattr(bg, "get_topsailai_home", lambda: str(tmp_path))
    monkeypatch.setattr(bg, "_request_file", lambda folder, request: (request_path, 0))
    monkeypatch.setattr(bg, "_cleanup_request", lambda path: None)
    monkeypatch.setattr(bg._os, "pipe", lambda: (10, 11))
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    monkeypatch.setattr(bg._os, "set_blocking", lambda fd, flag: None)
    monkeypatch.setattr(bg, "_entrypoint_command", lambda base_dir=None: ["fake-cli"])
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *args, **kwargs: True)
    monkeypatch.setattr(bg._os, "read", lambda fd, size: next(frames))
    with pytest.raises(expected):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *args, **kwargs: supervisor,
                             clock=FakeClock(), sleeper=lambda seconds: None)

# UNIT 1B-1 round 17 custody reconciliation proofs.
def test_r17_supervisor_exit_unknown_launcher_custody_is_exit_six():
    started = {"launcher_pid": 41, "launcher_identity": "owned", "session": "s"}
    ownership = bg.LauncherOwnership(41, "owned", "s")
    assert not bg._validate_launcher_cleanup_ack(
        {"kind": "cleanup", "session": "s", "launcher_pid": 41,
         "launcher_identity": "owned", "cleanup_confirmed": False}, ownership
    )


def test_r17_correlated_launcher_cleanup_ack_proves_custody():
    started = {"launcher_pid": 41, "launcher_identity": "owned", "session": "s"}
    ack = {"kind": "cleanup", "session": "s", "launcher_pid": 41,
           "launcher_identity": "owned", "cleanup_confirmed": True}
    assert bg._validate_launcher_cleanup_ack(ack, bg.LauncherOwnership(41, "owned", "s"))


def test_r17_unrelated_cleanup_ack_is_exit_six():
    started = {"launcher_pid": 41, "launcher_identity": "owned", "session": "s"}
    ack = {"kind": "cleanup", "session": "other", "launcher_pid": 99,
           "launcher_identity": "other", "cleanup_confirmed": True}
    assert not bg._validate_launcher_cleanup_ack(ack, bg.LauncherOwnership(41, "owned", "s"))


def test_r17_control_channel_survives_until_reconciliation():
    writes = []
    result = bg._cancel_supervisor_transport(
        object(), 12, write=lambda fd, data: writes.append((fd, data)) or len(data),
        cleanup=lambda _: {"cleanup_confirmed": True},
    )
    assert writes == [(12, b"1")]
    assert result["cleanup_confirmed"] is True


def test_r17_cancellation_confirmed_but_launcher_unproven_is_exit_six(monkeypatch):
    monkeypatch.setattr(bg, "_cleanup_owned", lambda child, wait_timeout=0.25, **kwargs: True)
    with pytest.raises(bg.BackgroundUnconfirmed):
        bg.cancel_background(object(), started={"launcher_pid": 41, "launcher_identity": "owned"},
                             cleanup_ack=None, session_id="s")


def test_cancel_background_invalid_started_record_is_unresolved(monkeypatch):
    monkeypatch.setattr(bg, "_cleanup_owned", lambda child, wait_timeout=0.25, **kwargs: True)
    with pytest.raises(bg.BackgroundUnconfirmed, match="launcher custody unresolved"):
        bg.cancel_background(
            object(),
            started={"launcher_pid": 41, "launcher_identity": "owned", "session": "other"},
            cleanup_ack={
                "kind": "cleanup",
                "session": "s",
                "launcher_pid": 41,
                "launcher_identity": "owned",
                "cleanup_confirmed": True,
            },
            session_id="s",
        )


def test_r17_cancellation_and_launcher_cleanup_confirmed_is_exit_130(monkeypatch):
    monkeypatch.setattr(bg, "_cleanup_owned", lambda child, wait_timeout=0.25, **kwargs: True)
    started = {"launcher_pid": 41, "launcher_identity": "owned"}
    ack = {"kind": "cleanup", "session": "s", "launcher_pid": 41,
           "launcher_identity": "owned", "cleanup_confirmed": True}
    result = bg.cancel_background(object(), started=started, cleanup_ack=ack, session_id="s")
    assert result["exit_code"] == 130
    assert result["launcher_cleanup_confirmed"] is True

# UNIT 1B-1 round 18 integration proofs: exercise launch_background itself.
def _r18_launch(monkeypatch, tmp_path, frames, *, supervisor=None, cancel_requested=None):
    clock, supervisor = _patch_launch_background_common(
        monkeypatch, tmp_path, frames, supervisor=supervisor
    )
    return bg.launch_background(
        str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
        clock=clock, sleeper=clock.sleep, cancel_requested=cancel_requested,
        cancel_write=lambda fd, data: len(data),
    )


def test_r18_launch_supervisor_exit_unknown_custody_is_exit_six(monkeypatch, tmp_path):
    with pytest.raises(bg.BackgroundUnconfirmed, match="initialization"):
        _r18_launch(monkeypatch, tmp_path, [[]], supervisor=_ImmediateSupervisor([1]))


def test_r18_launch_correlated_cleanup_ack_proves_custody(monkeypatch, tmp_path):
    started = {"kind": "started", "launcher_pid": 1801,
               "launcher_identity": "(1801, 9, 'authoritative')"}
    cleanup = {"kind": "cleanup", "session": "s", "launcher_pid": 1801,
               "launcher_identity": started["launcher_identity"],
               "cleanup_confirmed": True}
    failure = {"kind": "failure", "error": "relay", "cleanup_confirmed": True}
    with pytest.raises(RuntimeError, match="relay"):
        _r18_launch(monkeypatch, tmp_path, [[started], [cleanup, failure]])


def test_r18_launch_unrelated_cleanup_ack_is_exit_six(monkeypatch, tmp_path):
    started = {"kind": "started", "launcher_pid": 1802,
               "launcher_identity": "(1802, 9, 'authoritative')"}
    cleanup = {"kind": "cleanup", "session": "other", "launcher_pid": 999,
               "launcher_identity": "other", "cleanup_confirmed": True}
    failure = {"kind": "failure", "error": "relay", "cleanup_confirmed": True}
    with pytest.raises(bg.BackgroundUnconfirmed, match="custody unproven"):
        _r18_launch(monkeypatch, tmp_path, [[started], [cleanup, failure]])


def test_r18_launch_channel_open_until_reconciliation(monkeypatch, tmp_path):
    started = {"kind": "started", "launcher_pid": 1803,
               "launcher_identity": "(1803, 9, 'authoritative')"}
    cleanup = {"kind": "cleanup", "session": "s", "launcher_pid": 1803,
               "launcher_identity": started["launcher_identity"],
               "cleanup_confirmed": True}
    failure = {"kind": "failure", "error": "relay", "cleanup_confirmed": True}
    events = []
    original = bg._reconcile_launcher
    def reconcile(*args, **kwargs):
        events.append("reconcile")
        return original(*args, **kwargs)
    monkeypatch.setattr(bg, "_reconcile_launcher", reconcile)
    with pytest.raises(RuntimeError, match="relay"):
        _r18_launch(monkeypatch, tmp_path, [[started], [cleanup, failure]])
    assert events == ["reconcile"]


def test_r18_launch_cancellation_confirmed_launcher_unproven_is_exit_six(monkeypatch, tmp_path):
    started = {"kind": "started", "launcher_pid": 1804,
               "launcher_identity": "(1804, 9, 'authoritative')"}
    calls = iter([False, True])
    with pytest.raises(bg.BackgroundUnconfirmed):
        _r18_launch(monkeypatch, tmp_path, [[started], []],
                    cancel_requested=lambda: next(calls))


def test_r18_launch_cancellation_and_cleanup_confirmed_is_exit_130(monkeypatch, tmp_path):
    started = {"kind": "started", "launcher_pid": 1805,
               "launcher_identity": "(1805, 9, 'authoritative')"}
    cleanup = {"kind": "cleanup", "session": "s", "launcher_pid": 1805,
               "launcher_identity": started["launcher_identity"],
               "cleanup_confirmed": True}
    calls = iter([False, True])
    result = _r18_launch(monkeypatch, tmp_path, [[started], [cleanup]],
                         cancel_requested=lambda: next(calls))
    assert result["exit_code"] == 130
    assert result["launcher_cleanup_confirmed"] is True


def test_r19_conflicting_started_frame_is_exit_six(monkeypatch, tmp_path):
    first = {"kind": "started", "session": "s", "launcher_pid": 1901,
             "launcher_identity": "identity-a"}
    second = {"kind": "started", "session": "s", "launcher_pid": 1902,
              "launcher_identity": "identity-b"}
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, [[first, second]])
    with pytest.raises(bg.BackgroundUnconfirmed, match="conflicting"):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=clock, sleeper=clock.sleep)


def test_r19_identity_and_protocol_fail_closed(monkeypatch):
    monkeypatch.setattr(bg._os, "name", "nt", raising=False)
    assert bg._authoritative_child_identity(1) is None
    with pytest.raises(bg.AssertionError if hasattr(bg, "AssertionError") else AssertionError):
        bg._require_injected_spawn(None)
    with pytest.raises(bg.BackgroundUnconfirmed, match="invalid"):
        bg._ownership_from_started({"launcher_pid": 1}, "s")
    with pytest.raises(bg.BackgroundUnconfirmed, match="session"):
        bg._ownership_from_started({"launcher_pid": 1, "launcher_identity": "x", "session": "other"}, "s")


def test_r19_reconciliation_existing_and_transport_failures(monkeypatch):
    ownership = bg.LauncherOwnership(1, "x", "s")
    ack = {"kind": "cleanup", "session": "s", "launcher_pid": 1,
           "launcher_identity": "x", "cleanup_confirmed": True}
    assert bg._reconcile_launcher(1, bytearray(), __import__("collections").deque(), ownership,
                                  object(), clock=lambda: 0, sleeper=lambda _: None,
                                  existing_ack=ack) == ack
    assert bg._reconcile_launcher(1, bytearray(), __import__("collections").deque(), ownership,
                                  SimpleNamespace(poll=lambda: 1), clock=lambda: 0,
                                  sleeper=lambda _: None) is None
    with pytest.raises(bg.BackgroundUnconfirmed):
        bg._cancel_supervisor_transport(object(), 1, write=lambda fd, data: 0)


def test_r19_cancel_background_rejects_invalid_and_accepts_valid(monkeypatch):
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *args, **kwargs: True)
    with pytest.raises(bg.BackgroundUnconfirmed):
        bg.cancel_background(object(), started={"launcher_pid": 1, "launcher_identity": "x"},
                             cleanup_ack={"kind": "cleanup", "cleanup_confirmed": True}, session_id="s")
    ownership = {"launcher_pid": 1, "launcher_identity": "x", "session": "s"}
    ack = {"kind": "cleanup", "session": "s", "launcher_pid": 1,
           "launcher_identity": "x", "cleanup_confirmed": True}
    assert bg.cancel_background(object(), started=ownership, cleanup_ack=ack,
                                session_id="s")["exit_code"] == 130

# UNIT 1B-1 round 20: close helper coverage through primitive seams.
class _R20Clock:
    def __init__(self, step=1.0, max_calls=8):
        self.value = 0.0
        self.step = step
        self.calls = 0
        self.max_calls = max_calls

    def __call__(self):
        self.calls += 1
        if self.calls > self.max_calls:
            raise AssertionError("fake clock budget exhausted")
        self.value += self.step
        return self.value

    def sleep(self, seconds):
        self.value += self.step


class _R20TerminalSupervisor:
    def __init__(self, status=1):
        self.status = status

    def poll(self):
        return self.status


def test_r20_ownership_rejects_invalid_started_frames():
    with pytest.raises(bg.BackgroundUnconfirmed):
        bg._ownership_from_started({"launcher_pid": "bad", "launcher_identity": "x"}, "s")
    with pytest.raises(bg.BackgroundUnconfirmed):
        bg._ownership_from_started({"launcher_pid": 1, "launcher_identity": ""}, "s")
    with pytest.raises(bg.BackgroundUnconfirmed):
        bg._ownership_from_started({"launcher_pid": 1, "launcher_identity": "x", "session": "other"}, "s")


def test_r20_cleanup_ack_rejects_false_and_mismatched_session():
    owner = bg.LauncherOwnership(1, "x", "s")
    base = {"kind": "cleanup", "session": "s", "launcher_pid": 1,
            "launcher_identity": "x", "cleanup_confirmed": True}
    assert not bg._validate_launcher_cleanup_ack(
        {**base, "cleanup_confirmed": False}, owner)
    assert not bg._validate_launcher_cleanup_ack(
        {**base, "session": "other"}, owner)


def test_r20_reconcile_no_frames_times_out_with_bounded_clock(monkeypatch):
    clock = _R20Clock(step=2.0, max_calls=8)
    monkeypatch.setattr(bg._os, "read",
                        lambda fd, size: (_ for _ in ()).throw(BlockingIOError()))
    assert bg._reconcile_launcher(
        1, bytearray(), __import__("collections").deque(),
        bg.LauncherOwnership(1, "x", "s"), _R20TerminalSupervisor(),
        clock=clock, sleeper=clock.sleep) is None
    assert clock.calls <= 8


def test_r20_reconcile_transport_oserror_is_reported(monkeypatch):
    monkeypatch.setattr(bg._os, "read",
                        lambda fd, size: (_ for _ in ()).throw(OSError("closed")))
    with pytest.raises(OSError, match="closed"):
        bg._reconcile_launcher(
            1, bytearray(), __import__("collections").deque(),
            bg.LauncherOwnership(1, "x", "s"), _R20TerminalSupervisor(),
            clock=_R20Clock(), sleeper=lambda seconds: None)


def test_r20_reconcile_eof_and_mismatched_ack_fail_closed(monkeypatch):
    owner = bg.LauncherOwnership(1, "x", "s")
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"")
    assert bg._reconcile_launcher(
        1, bytearray(), __import__("collections").deque(), owner,
        _R20TerminalSupervisor(), clock=_R20Clock(), sleeper=lambda seconds: None) is None
    wrong = json.dumps({"kind": "cleanup", "session": "s", "launcher_pid": 2,
                        "launcher_identity": "x", "cleanup_confirmed": True}).encode() + b"\n"
    monkeypatch.setattr(bg._os, "read", lambda fd, size: wrong)
    assert bg._reconcile_launcher(
        1, bytearray(), __import__("collections").deque(), owner,
        _R20TerminalSupervisor(), clock=_R20Clock(), sleeper=lambda seconds: None) is None


def test_r20_reconcile_preserves_noncleanup_then_accepts_correlated_ack(monkeypatch):
    owner = bg.LauncherOwnership(1, "x", "s")
    payload = (
        json.dumps({"kind": "started"}).encode() + b"\n" +
        json.dumps({"kind": "cleanup", "session": "s", "launcher_pid": 1,
                    "launcher_identity": "x", "cleanup_confirmed": True}).encode() + b"\n"
    )
    monkeypatch.setattr(bg._os, "read", lambda fd, size: payload)
    result = bg._reconcile_launcher(
        1, bytearray(), __import__("collections").deque(), owner,
        _R20TerminalSupervisor(), clock=_R20Clock(), sleeper=lambda seconds: None)
    assert result is not None
    assert result["launcher_pid"] == 1


def test_r20_spawn_guard_accepts_factory_and_rejects_none():
    factory = lambda *args, **kwargs: None
    assert bg._require_injected_spawn(factory) is factory
    with pytest.raises(AssertionError, match="injected spawn"):
        bg._require_injected_spawn(None)


def test_r20_authoritative_identity_probe_handles_error_and_token(monkeypatch):
    class FakePath:
        def __init__(self, value):
            self.value = value

        def read_text(self, encoding=None):
            if self.value.endswith("/1/stat"):
                raise OSError("unavailable")
            return "1 (name) S 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 77"

    monkeypatch.setattr(bg, "Path", FakePath)
    assert bg._authoritative_child_identity(1) is None
    assert bg._authoritative_child_identity(2) == (2, 77)


def test_r20_child_identity_none_probe_is_unverifiable():
    child = FakeChild(pid=20, polls=[0])
    assert bg._child_identity(child, lambda pid: None) == (20, None, "unverifiable")


def test_r20_remove_lease_missing_file_is_tolerated(monkeypatch, tmp_path):
    class MissingLease:
        def unlink(self):
            raise FileNotFoundError

    monkeypatch.setattr(bg, "active_launch_lease", lambda path: MissingLease())
    bg._remove_lease(tmp_path / "launch.log")


# UNIT 1B-1 round 21: close the measured launch control-flow deficit.
def test_r21_duplicate_started_and_initial_cleanup_frames_are_consumed(monkeypatch, tmp_path):
    started = {"kind": "started", "session": "s", "launcher_pid": 2101,
               "launcher_identity": "identity-2101"}
    submitted = {"kind": "submitted", "session": "s", "launcher_pid": 2101,
                 "log_path": str(tmp_path / "workspace" / "task" / "s.agent-launch.log")}
    clock, supervisor = _patch_launch_background_common(
        monkeypatch, tmp_path, [[started, dict(started)],
                                [{"kind": "cleanup"}, started], [submitted]]
    )
    result = bg.launch_background(
        str(tmp_path), "s", spawn=lambda *args, **kwargs: supervisor,
        clock=clock, sleeper=clock.sleep,
    )
    assert result["outcome"] == "submitted"
    assert result["launcher_pid"] == 2101





def test_r21_scalar_identity_probe_is_authoritative():
    child = FakeChild(pid=2103, polls=[0])
    assert bg._child_identity(child, lambda pid: 77) == (2103, 77, "authoritative")


def test_r21_real_request_cancellation_rejects_missing_transport(monkeypatch, tmp_path):
    started = {"kind": "started", "session": "s", "launcher_pid": 2104,
               "launcher_identity": "identity-2104"}
    clock, supervisor = _patch_launch_background_common(
        monkeypatch, tmp_path, [[started], []]
    )
    pipes = iter([(10, 11), (12, None)])
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    monkeypatch.setattr(bg._os, "pipe", lambda: next(pipes))
    with pytest.raises(bg.BackgroundUnconfirmed, match="transport unavailable"):
        bg.launch_background(
            str(tmp_path), "s", spawn=lambda *args, **kwargs: supervisor,
            clock=clock, sleeper=clock.sleep,
            cancel_requested=lambda: True,
        )



def test_r24_supervise_cancel_probe_would_block_continues_real_loop(monkeypatch, tmp_path):
    """A would-block cancellation read must continue supervision and submit."""
    child = FakeChild(pid=2401, polls=[None, 0], wait_status=0)
    child.stdout = FakeStream(41, [b"x"])
    child.stderr = FakeStream(42, [b""])
    sent = []

    class Lease:
        def touch(self, **kwargs):
            pass

        def unlink(self):
            pass

    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    monkeypatch.setattr(bg, "_close_streams", lambda selector, streams: None)
    monkeypatch.setattr(bg, "_remove_lease", lambda path: None)
    monkeypatch.setattr(
        bg, "_RotatingLog",
        lambda path: SimpleNamespace(open=lambda: None, close=lambda: None, write=lambda data: None),
    )
    monkeypatch.setattr(
        bg._selectors,
        "DefaultSelector",
        lambda: FakeSelector({41: child.stdout, 42: child.stderr}),
    )
    monkeypatch.setattr(bg._os, "set_blocking", lambda *args: None)
    monkeypatch.setattr(bg._os, "close", lambda *args: None)

    stream_reads = {41: [b"x", b"x", b""], 42: [b""]}

    def read(fd, size):
        if fd == 4:
            raise BlockingIOError()
        return stream_reads[fd].pop(0)

    monkeypatch.setattr(bg._os, "read", read)
    clock = FakeClock(step=0.2, max_calls=40)
    request = {
        "folder": str(tmp_path),
        "session_id": "s",
        "log_path": str(tmp_path / "s.log"),
    }

    bg._supervise(
        request,
        3,
        popen=lambda *args, **kwargs: child,
        clock=clock,
        sleeper=clock.sleep,
        cancel_fd=4,
    )

    assert [frame["kind"] for frame in sent] == ["started", "cleanup", "early_exit"]
    assert sent[1]["cleanup_confirmed"] is True
    assert sent[1]["launcher_pid"] == 2401
    assert sent[1]["launcher_identity"] == repr(bg._child_identity(child, None))
    assert sent[-1]["code"] == 0


# ---------------------------------------------------------------------------
# Round 26: custody ordering, exit-code contract, coalesced frames, facades.
# ---------------------------------------------------------------------------


def test_r26_cleanup_owned_already_exited_child_is_cleaned(monkeypatch):
    """An already-exited child is cleaned without any identity proof or signal."""
    signals = []
    monkeypatch.setattr(bg._os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    child = FakeChild(pid=556, polls=[0], wait_status=0)
    assert bg._cleanup_owned(child, wait_timeout=0.25) is True
    assert signals == []
    assert ("wait", 0.25) in child.calls


def test_r26_cleanup_owned_live_child_signals_then_reaps(monkeypatch):
    """A live owned child receives exactly one SIGTERM and is then reaped."""
    signals = []
    monkeypatch.setattr(bg._os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    child = FakeChild(pid=555, polls=[None, None, -15], wait_status=0)
    assert bg._cleanup_owned(child, wait_timeout=0.25,
                             identity_probe=lambda pid: (pid, 4242)) is True
    assert signals == [(555, bg.signal.SIGTERM)]
    assert ("wait", 0.25) in child.calls


def test_r26_cleanup_owned_identity_mismatch_never_signals(monkeypatch):
    """A live child whose identity no longer matches is never signalled."""
    signals = []
    monkeypatch.setattr(bg._os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    child = FakeChild(pid=557, polls=[None])
    assert bg._cleanup_owned(child, wait_timeout=0.25,
                             identity=(557, 4242, "authoritative"),
                             identity_probe=lambda pid: (pid, 999)) is False
    assert signals == []


def test_r26_child_absent_reaped_child_is_absent():
    """A reaped child is absent even though no identity token remains."""
    child = FakeChild(pid=558, polls=[0])
    assert bg._child_absent(child, (558, None, "unverifiable")) is True


def test_r26_child_absent_live_matching_child_is_not_absent():
    """A live child is never reported absent."""
    child = FakeChild(pid=559, polls=[None])
    assert bg._child_absent(child, (559, 4242, "authoritative")) is False


def test_r26_background_preparation_failure_is_exit_four(monkeypatch, tmp_path):
    """Background preparation failure returns the documented exit code 4."""
    from cli_topsailai import agent_launch as al

    def fail(folder, session_id):
        raise ValueError("preparation refused")

    monkeypatch.setattr(al, "_prepare_environment", fail)
    monkeypatch.setattr(bg, "launch_background", lambda *a, **k: pytest.fail("submitted"))
    assert al._launch_configured_agent_impl(str(tmp_path), mode=None, background=True,
                                            spawn=lambda *a, **k: None) == 4


def test_r26_background_unconfirmed_is_exit_six(monkeypatch, tmp_path):
    """Unproven custody is classified by type, not by class-name string."""
    from cli_topsailai import agent_launch as al

    monkeypatch.setattr(al, "_prepare_environment", lambda folder, session_id: ((), {}, {}, {}))
    monkeypatch.setattr(bg, "launch_background",
                        lambda *a, **k: (_ for _ in ()).throw(bg.BackgroundUnconfirmed("custody")))
    assert al._launch_configured_agent_impl(str(tmp_path), mode=None, background=True,
                                            spawn=lambda *a, **k: None) == 6


def test_r26_foreground_and_background_agree_on_preparation_failure(monkeypatch, tmp_path):
    """The same preparation failure yields the same exit code in both modes."""
    from cli_topsailai import agent_launch as al

    def fail(folder, session_id):
        raise OSError("preparation refused")

    monkeypatch.setattr(al, "_prepare_environment", fail)
    background = al._launch_configured_agent_impl(str(tmp_path), mode=None, background=True,
                                                  spawn=lambda *a, **k: None)
    foreground = al._launch_configured_agent_impl(str(tmp_path), mode="raw", background=False,
                                                  spawn=lambda *a, **k: None)
    assert background == foreground == 4


def test_r26_coalesced_started_and_submitted_succeeds(monkeypatch, tmp_path):
    """One transport read carrying started and submitted still submits."""
    log_path = str(tmp_path / "workspace" / "task" / "s.agent-launch.log")
    frames = [[{"kind": "started", "launcher_pid": 777},
               {"kind": "submitted", "session": "s", "launcher_pid": 777,
                "log_path": log_path}]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    result = bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                                  clock=clock, sleeper=clock.sleep)
    assert result["outcome"] == "submitted"
    assert result["launcher_pid"] == 777


def test_r26_coalesced_started_and_early_exit_is_classified(monkeypatch, tmp_path):
    """A coalesced early exit is classified as an early exit, not a timeout."""
    ack = {"kind": "cleanup", "class": "early_exit", "session": "s", "launcher_pid": 777,
           "launcher_identity": "identity:777", "cleanup_confirmed": True}
    # One transport read carries started, the terminal frame and the cleanup ack.
    frames = [[{"kind": "started", "launcher_pid": 777},
               {"kind": "early_exit", "code": 3, "launcher_pid": 777}, ack]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    with pytest.raises(RuntimeError, match="exited before submission: 3"):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=clock, sleeper=clock.sleep)


def test_r26_coalesced_started_and_failure_frame_is_classified(monkeypatch, tmp_path):
    """A coalesced supervisor failure is classified as that failure, not a timeout."""
    ack = {"kind": "cleanup", "class": "startup_failure", "session": "s", "launcher_pid": 777,
           "launcher_identity": "identity:777", "cleanup_confirmed": True}
    # One transport read carries started, the failure frame and the cleanup ack.
    frames = [[{"kind": "started", "launcher_pid": 777},
               {"kind": "failure", "class": "startup_failure", "cleanup_confirmed": True,
                "error": "boom"}, ack]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    with pytest.raises(RuntimeError, match="boom"):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=clock, sleeper=clock.sleep)


def _r26_cancel_setup(monkeypatch, tmp_path, frames, supervisor):
    """Install the bounded transport seams used by the cancellation proofs."""
    monkeypatch.setattr(bg, "get_topsailai_home", lambda: str(tmp_path))
    monkeypatch.setattr(bg, "_request_file", lambda folder, request: (tmp_path / "r.json", 0))
    monkeypatch.setattr(bg, "_cleanup_request", lambda path: None)
    monkeypatch.setattr(bg, "_entrypoint_command", lambda base_dir=None: ["fake"])
    monkeypatch.setattr(bg._os, "pipe", lambda: (10, 11))
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    monkeypatch.setattr(bg._os, "set_blocking", lambda fd, flag: None)
    batches = list(frames)

    def read_frames(fd, buffer):
        return batches.pop(0) if batches else []

    monkeypatch.setattr(bg, "_read_frames", read_frames)
    return supervisor


def test_r26_cancellation_reaps_supervisor_before_exit_130(monkeypatch, tmp_path):
    """Exit 130 requires a reaped supervisor, proven by one SIGTERM and one wait."""
    signals = []
    monkeypatch.setattr(bg._os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    ack = {"kind": "cleanup", "class": "cancellation", "session": "s", "launcher_pid": 7,
           "launcher_identity": "x", "cleanup_confirmed": True}
    supervisor = _ImmediateSupervisor([None, None, 0])
    _r26_cancel_setup(monkeypatch, tmp_path,
                      [[{"kind": "started", "session": "s", "launcher_pid": 7,
                         "launcher_identity": "x"}], [ack]], supervisor)
    sequence = iter([False, True])
    result = bg.launch_background(
        str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
        clock=FakeClock(), sleeper=lambda _: None,
        cancel_requested=lambda: next(sequence, True),
        cancel_write=lambda fd, payload: 1,
        identity_probe=lambda pid: (pid, 4242),
    )
    assert result["outcome"] == "cancelled"
    assert result["exit_code"] == 130
    assert signals == [(9001, bg.signal.SIGTERM)]
    assert [call for call in supervisor.calls if isinstance(call, tuple)] == [("wait", 0.25)]


def test_r26_cancellation_supervisor_reap_failure_is_exit_six(monkeypatch, tmp_path):
    """A supervisor that cannot be reaped downgrades cancellation to exit 6."""
    ack = {"kind": "cleanup", "class": "cancellation", "session": "s", "launcher_pid": 7,
           "launcher_identity": "x", "cleanup_confirmed": True}
    supervisor = _ImmediateSupervisor([None] * 8)
    _r26_cancel_setup(monkeypatch, tmp_path,
                      [[{"kind": "started", "session": "s", "launcher_pid": 7,
                         "launcher_identity": "x"}], [ack]], supervisor)
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *a, **k: False)
    sequence = iter([False, True])
    with pytest.raises(bg.BackgroundUnconfirmed, match="supervisor reap failed"):
        bg.launch_background(
            str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
            clock=FakeClock(), sleeper=lambda _: None,
            cancel_requested=lambda: next(sequence, True),
            cancel_write=lambda fd, payload: 1,
        )


def test_r26_facades_are_not_shared_singletons(monkeypatch):
    """Patching a facade attribute must never mutate the shared module."""
    assert bg._os is not os
    assert bg._selectors is not __import__("selectors")
    assert bg._subprocess is not __import__("subprocess")
    original_write = os.write
    monkeypatch.setattr(bg._os, "write", lambda fd, data: 0)
    assert os.write is original_write
    original_selector = __import__("selectors").DefaultSelector
    monkeypatch.setattr(bg._selectors, "DefaultSelector", lambda: None)
    assert __import__("selectors").DefaultSelector is original_selector
    original_popen = __import__("subprocess").Popen
    monkeypatch.setattr(bg._subprocess, "Popen", lambda *a, **k: None)
    assert __import__("subprocess").Popen is original_popen


def test_r26_stat_parsing_handles_space_containing_comm(monkeypatch):
    """Field 22 is indexed after the last ')' so a spaced comm cannot shift it."""
    stat_line = (
        "12345 (my proc name) S 1 12345 12345 0 -1 4194560 100 0 0 0 1 2 3 4 5 6 7 8 "
        "410603185 999 0\n"
    )

    class FakePath:
        def __init__(self, value):
            self.value = value

        def read_text(self, encoding=None):
            return stat_line

    monkeypatch.setattr(bg, "Path", FakePath)
    assert bg._authoritative_child_identity(12345) == (12345, 410603185)
    assert stat_line.split()[21] != "410603185"


def test_r26_conflicting_started_during_observation_is_exit_six(monkeypatch, tmp_path):
    """A second started frame that contradicts ownership is rejected."""
    frames = [[{"kind": "started", "launcher_pid": 7}],
              [{"kind": "started", "launcher_pid": 8}]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    with pytest.raises(bg.BackgroundUnconfirmed, match="conflicting started acknowledgement"):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=clock, sleeper=clock.sleep)


def test_b02_prepared_environment_delegates_once_and_restores(monkeypatch, tmp_path):
    """Background preparation delegates exactly once and forwards the prepared environment."""
    from cli_topsailai import agent_launch as al

    prepared = []
    delegated = []

    def prepare(folder, session_id):
        prepared.append((folder, session_id))
        return ("keys", {}, {}, {"FORWARDED": "1"})

    def launch(folder, session_id, **kwargs):
        delegated.append((folder, session_id, kwargs))
        return {"outcome": "submitted", "launcher_pid": 4242,
                "log_path": "/tmp/x.log", "session_id": session_id}

    monkeypatch.setattr(al, "_prepare_environment", prepare)
    monkeypatch.setattr(bg, "launch_background", launch)
    spawn = lambda *a, **k: pytest.fail("foreground spawn")
    assert al._launch_configured_agent_impl(str(tmp_path), mode=None, background=True,
                                            spawn=spawn) == 0
    assert len(prepared) == 1
    assert prepared[0][0] == str(tmp_path)
    assert len(delegated) == 1
    assert delegated[0][2]["environment"] == os.environ.copy()
    assert delegated[0][2]["spawn"] is spawn


def test_b02_parent_state_is_restored_after_launch(monkeypatch, tmp_path):
    """The launch boundary restores cwd and environment even when the impl mutates them."""
    from cli_topsailai import agent_launch as al

    original_cwd = os.getcwd()
    original_environment = os.environ.copy()

    def mutate(folder, *, mode, background=False, spawn=None, entrypoint_base=None):
        os.chdir(str(tmp_path))
        os.environ["TOPSAILAI_R26_PROBE"] = "1"
        return 0

    monkeypatch.setattr(al, "_launch_configured_agent_impl", mutate)
    try:
        assert al.launch_configured_agent(str(tmp_path), mode=None, background=True) == 0
        assert os.getcwd() == original_cwd
        assert "TOPSAILAI_R26_PROBE" not in os.environ
        assert os.environ == original_environment
    finally:
        os.chdir(original_cwd)
        os.environ.clear()
        os.environ.update(original_environment)


def test_b08_submission_has_exact_output_and_transfers_custody(monkeypatch, tmp_path, capsys):
    """Submission prints exactly five lines, never claims readiness and never waits."""
    from cli_topsailai import agent_launch as al

    monkeypatch.setattr(al, "_prepare_environment", lambda folder, session_id: ((), {}, {}, {}))
    monkeypatch.setattr(bg, "launch_background",
                        lambda folder, session_id, **kwargs: {
                            "outcome": "submitted", "launcher_pid": 4242,
                            "log_path": "/tmp/x.log", "session_id": session_id})
    spawn = lambda *a, **k: pytest.fail("foreground spawn")
    assert al._launch_configured_agent_impl(str(tmp_path), mode=None, background=True,
                                            spawn=spawn) == 0
    captured = capsys.readouterr()
    session_line = next(line for line in captured.out.splitlines()
                        if line.startswith("[INFO] Agent submitted: session="))
    session_id = session_line.split("session=")[1].split()[0]
    assert captured.out.splitlines() == [
        f"[INFO] Submitting agent: workspace={tmp_path} mode=raw background=yes session={session_id}",
        f"[INFO] Agent submitted: session={session_id} launcher_pid=4242 mode=raw background=yes",
        "[INFO] Launch log: /tmp/x.log",
        "[INFO] Startup is not confirmed; inspect the launch log and workspace task list",
        "[INFO] Watch: topsailai workspace",
        f"[INFO] Resume when idle: topsailai project resume {session_id}",
    ]
    assert "ready" not in captured.out.lower()
    assert captured.err == ""


def test_b09_early_exit_and_boundary_poll_are_reaped(monkeypatch, tmp_path):
    """An early exit is classified as failure 5 with custody proven, never submitted."""
    from cli_topsailai import agent_launch as al

    ack = {"kind": "cleanup", "class": "early_exit", "session": "s", "launcher_pid": 777,
           "launcher_identity": "identity:777", "cleanup_confirmed": True}
    frames = [[{"kind": "started", "session": "s", "launcher_pid": 777,
                "launcher_identity": "identity:777"}],
              [{"kind": "early_exit", "code": 0, "launcher_pid": 777}, ack]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    monkeypatch.setattr(al, "_prepare_environment", lambda folder, session_id: ((), {}, {}, {}))
    monkeypatch.setattr(al, "_session_id", lambda: "s")
    monkeypatch.setattr(bg, "get_topsailai_home", lambda: str(tmp_path))
    monkeypatch.setattr(bg, "_request_file", lambda folder, request: (tmp_path / "r.json", 0))
    monkeypatch.setattr(bg, "_cleanup_request", lambda path: None)
    monkeypatch.setattr(bg, "_entrypoint_command", lambda base_dir=None: ["fake"])
    monkeypatch.setattr(bg._os, "pipe", lambda: (10, 11))
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    monkeypatch.setattr(bg._os, "set_blocking", lambda fd, flag: None)
    batches = list(frames)
    monkeypatch.setattr(bg, "_read_frames",
                        lambda fd, buffer: batches.pop(0) if batches else [])
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *a, **k: True)
    assert al._launch_configured_agent_impl(str(tmp_path), mode=None, background=True,
                                            spawn=lambda *a, **k: supervisor) == 5


def test_b13_cancellation_requires_launcher_cleanup_ack(monkeypatch, tmp_path):
    """Cancellation returns 130 only for the exact launcher cleanup acknowledgement."""
    good = {"kind": "cleanup", "class": "cancellation", "session": "s", "launcher_pid": 7,
            "launcher_identity": "x", "cleanup_confirmed": True}
    wrong = dict(good, launcher_pid=8)
    for ack, expected in ((good, 130), (wrong, None)):
        supervisor = _ImmediateSupervisor([None] * 8)
        _r26_cancel_setup(monkeypatch, tmp_path,
                          [[{"kind": "started", "session": "s", "launcher_pid": 7,
                             "launcher_identity": "x"}], [ack]], supervisor)
        monkeypatch.setattr(bg, "_cleanup_owned", lambda *a, **k: True)
        sequence = iter([False, True])
        if expected is None:
            with pytest.raises(bg.BackgroundUnconfirmed,
                               match="unrelated or incomplete launcher cleanup"):
                bg.launch_background(
                    str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                    clock=FakeClock(), sleeper=lambda _: None,
                    cancel_requested=lambda: next(sequence, True),
                    cancel_write=lambda fd, payload: 1)
        else:
            result = bg.launch_background(
                str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                clock=FakeClock(), sleeper=lambda _: None,
                cancel_requested=lambda: next(sequence, True),
                cancel_write=lambda fd, payload: 1)
            assert result["exit_code"] == expected
            assert result["cleanup_confirmed"] is True


def test_r26_b09_real_supervisor_early_exit_protocol_yields_exit_five(monkeypatch, tmp_path):
    """B09 proven against the frames the real supervisor actually emits.

    The supervisor is executed for real so the acknowledgement protocol is not
    fabricated by the test: an early exit must publish correlated cleanup proof
    and the parent must then classify the failure as exit 5 with custody proven.
    """
    from cli_topsailai import agent_launch as al

    class Lease:
        def touch(self, **kwargs):
            pass

        def unlink(self):
            pass

    class Stream:
        def __init__(self, fd):
            self._fd = fd

        def fileno(self):
            return self._fd

        def close(self):
            pass

    class ExitingChild:
        pid = 777

        def __init__(self):
            self.stdout = Stream(21)
            self.stderr = Stream(22)
            self.calls = []

        def poll(self):
            self.calls.append("poll")
            return 0

        def wait(self, timeout=None):
            self.calls.append(("wait", timeout))
            return 0

        def terminate(self):
            self.calls.append("terminate")

        def kill(self):
            self.calls.append("kill")

    class EmptySelector:
        def __init__(self, streams):
            self.streams = streams

        def register(self, stream, event):
            return None

        def unregister(self, stream):
            return None

        def select(self, timeout=0):
            return []

        def close(self):
            return None

    child = ExitingChild()
    emitted = []
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_remove_lease", lambda path: None)
    monkeypatch.setattr(bg, "_RotatingLog", lambda path: SimpleNamespace(
        open=lambda: None, close=lambda: None, write=lambda data: None))
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: emitted.append(payload))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *args: None)
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"")
    monkeypatch.setattr(bg._selectors, "DefaultSelector",
                        lambda: EmptySelector({21: child.stdout, 22: child.stderr}))

    bg._supervise(
        {"folder": str(tmp_path), "session_id": "s",
         "log_path": str(tmp_path / "s.log")},
        3, popen=lambda *args, **kwargs: child,
        clock=FakeClock(), sleeper=lambda seconds: None,
        identity_probe=lambda pid: (pid, 15),
    )

    # The real protocol must carry correlated cleanup proof before the exit frame.
    assert [frame["kind"] for frame in emitted] == ["started", "cleanup", "early_exit"]
    assert emitted[1]["cleanup_confirmed"] is True
    assert emitted[1]["launcher_identity"] == emitted[0]["launcher_identity"]
    assert emitted[1]["launcher_pid"] == emitted[0]["launcher_pid"]

    # Replaying exactly those frames must classify the failure as exit 5.
    frames = [[emitted[0]], emitted[1:]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    monkeypatch.setattr(al, "_prepare_environment", lambda folder, session_id: ((), {}, {}, {}))
    monkeypatch.setattr(al, "_session_id", lambda: "s")
    assert al._launch_configured_agent_impl(
        str(tmp_path), mode=None, background=True,
        spawn=lambda *args, **kwargs: supervisor) == 5

def test_r26_unreapable_early_exit_launcher_fails_closed(monkeypatch, tmp_path):
    """An early exit that cannot be reaped must not claim cleanup proof.

    The supervisor must publish cleanup_confirmed=False, and the parent must then
    refuse to treat the launcher as cleaned, so the outcome is exit 6 rather than
    a false exit 5.
    """
    from cli_topsailai import agent_launch as al

    class Lease:
        def touch(self, **kwargs):
            pass

        def unlink(self):
            pass

    class Stream:
        def __init__(self, fd):
            self._fd = fd

        def fileno(self):
            return self._fd

        def close(self):
            pass

    class UnreapableChild:
        pid = 888

        def __init__(self):
            self.stdout = Stream(31)
            self.stderr = Stream(32)

        def poll(self):
            return 0

        def wait(self, timeout=None):
            raise bg._subprocess.TimeoutExpired("launcher", timeout)

        def terminate(self):
            pass

        def kill(self):
            pass

    class EmptySelector:
        def __init__(self, streams):
            self.streams = streams

        def register(self, stream, event):
            return None

        def unregister(self, stream):
            return None

        def select(self, timeout=0):
            return []

        def close(self):
            return None

    child = UnreapableChild()
    emitted = []
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_remove_lease", lambda path: None)
    monkeypatch.setattr(bg, "_RotatingLog", lambda path: SimpleNamespace(
        open=lambda: None, close=lambda: None, write=lambda data: None))
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: emitted.append(payload))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *args: None)
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"")
    monkeypatch.setattr(bg._selectors, "DefaultSelector",
                        lambda: EmptySelector({31: child.stdout, 32: child.stderr}))

    bg._supervise(
        {"folder": str(tmp_path), "session_id": "s",
         "log_path": str(tmp_path / "s.log")},
        3, popen=lambda *args, **kwargs: child,
        clock=FakeClock(), sleeper=lambda seconds: None,
        identity_probe=lambda pid: (pid, 15),
    )

    assert [frame["kind"] for frame in emitted] == ["started", "cleanup", "early_exit"]
    assert emitted[1]["cleanup_confirmed"] is False

    frames = [[emitted[0]], emitted[1:]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    monkeypatch.setattr(al, "_prepare_environment", lambda folder, session_id: ((), {}, {}, {}))
    monkeypatch.setattr(al, "_session_id", lambda: "s")
    assert al._launch_configured_agent_impl(
        str(tmp_path), mode=None, background=True,
        spawn=lambda *args, **kwargs: supervisor) == 6


def _r27_cancel_setup(monkeypatch, tmp_path, frames):
    """Install bounded seams for cancellation proofs and count pipe reads."""
    reads = []
    monkeypatch.setattr(bg, "get_topsailai_home", lambda: str(tmp_path))
    monkeypatch.setattr(bg, "_request_file", lambda folder, request: (tmp_path / "r.json", 0))
    monkeypatch.setattr(bg, "_cleanup_request", lambda path: None)
    monkeypatch.setattr(bg, "_entrypoint_command", lambda base_dir=None: ["fake"])
    monkeypatch.setattr(bg._os, "pipe", lambda: (10, 11))
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    monkeypatch.setattr(bg._os, "set_blocking", lambda fd, flag: None)
    monkeypatch.setattr(bg._os, "killpg", lambda pid, sig: None)
    batches = list(frames)

    def read_frames(fd, buffer):
        reads.append(len(reads))
        return batches.pop(0) if batches else []

    monkeypatch.setattr(bg, "_read_frames", read_frames)
    return reads


def test_r27_cancellation_with_pending_submitted_frame_reaches_130(monkeypatch, tmp_path):
    """A retained submission frame must never starve the cancellation proof."""
    log_path = str(tmp_path / "workspace" / "task" / "s.agent-launch.log")
    started = {"kind": "started", "session": "s", "launcher_pid": 7, "launcher_identity": "x"}
    submitted = {"kind": "submitted", "session": "s", "launcher_pid": 7, "log_path": log_path}
    cleanup = {"kind": "cleanup", "class": "cancellation", "session": "s", "launcher_pid": 7,
               "launcher_identity": "x", "cleanup_confirmed": True}
    reads = _r27_cancel_setup(monkeypatch, tmp_path, [[started, submitted], [cleanup]])
    supervisor = _ImmediateSupervisor([None, None, 0])
    sequence = iter([False, True])
    result = bg.launch_background(
        str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
        clock=FakeClock(), sleeper=lambda _: None,
        cancel_requested=lambda: next(sequence, True),
        cancel_write=lambda fd, payload: 1,
        identity_probe=lambda pid: (pid, 4242),
    )
    assert result["outcome"] == "cancelled"
    assert result["exit_code"] == 130
    assert result["cleanup_confirmed"] is True
    # The retained submission frame must not prevent reading the cleanup proof.
    assert len(reads) >= 2


def test_r27_cancellation_during_initialization_reaches_130(monkeypatch, tmp_path):
    """Cancellation before the initialization loop consumed started still proves custody."""
    started = {"kind": "started", "session": "s", "launcher_pid": 7, "launcher_identity": "x"}
    cleanup = {"kind": "cleanup", "class": "cancellation", "session": "s", "launcher_pid": 7,
               "launcher_identity": "x", "cleanup_confirmed": True}
    reads = _r27_cancel_setup(monkeypatch, tmp_path, [[started, cleanup]])
    supervisor = _ImmediateSupervisor([None, None, 0])
    result = bg.launch_background(
        str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
        clock=FakeClock(), sleeper=lambda _: None,
        cancel_requested=lambda: True,
        cancel_write=lambda fd, payload: 1,
        identity_probe=lambda pid: (pid, 4242),
    )
    assert result["outcome"] == "cancelled"
    assert result["exit_code"] == 130
    assert result["cleanup_confirmed"] is True
    assert len(reads) == 1


def test_r27_cancellation_rejects_unrelated_cleanup_after_pending_frame(monkeypatch, tmp_path):
    """A pending frame must not make an unrelated cleanup acknowledgement acceptable."""
    started = {"kind": "started", "session": "s", "launcher_pid": 7, "launcher_identity": "x"}
    submitted = {"kind": "submitted", "session": "s", "launcher_pid": 7, "log_path": "/x.log"}
    foreign = {"kind": "cleanup", "class": "cancellation", "session": "s", "launcher_pid": 8,
               "launcher_identity": "y", "cleanup_confirmed": True}
    _r27_cancel_setup(monkeypatch, tmp_path, [[started, submitted], [foreign]])
    # The finally-block reconciliation polls until its deadline, so the double
    # needs a finite but sufficient poll budget.
    supervisor = _ImmediateSupervisor([None] * 400)
    sequence = iter([False, True])
    with pytest.raises(bg.BackgroundUnconfirmed, match="unrelated or incomplete"):
        bg.launch_background(
            str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
            clock=FakeClock(), sleeper=lambda _: None,
            cancel_requested=lambda: next(sequence, True),
            cancel_write=lambda fd, payload: 1,
            identity_probe=lambda pid: (pid, 4242),
        )


def test_r28_parent_submission_window_exceeds_supervisor_observation_window():
    """The parent must wait strictly longer than the supervisor's own window.

    The supervisor observes the launcher for ``_OBSERVATION_TIMEOUT`` before it
    can publish a submission, so an equal parent window can never acknowledge a
    genuine launch.
    """
    assert bg._SUBMISSION_TIMEOUT > bg._OBSERVATION_TIMEOUT
    assert bg._SUBMISSION_TIMEOUT >= bg._OBSERVATION_TIMEOUT + bg._INIT_TIMEOUT


def test_r28_late_submission_after_observation_window_is_accepted(monkeypatch, tmp_path):
    """A submission arriving after the supervisor window is still acknowledged."""
    log_path = str(tmp_path / "workspace" / "task" / "s.agent-launch.log")
    started = {"kind": "started", "session": "s", "launcher_pid": 7, "launcher_identity": "x"}
    submitted = {"kind": "submitted", "session": "s", "launcher_pid": 7, "log_path": log_path}
    reads = _r27_cancel_setup(monkeypatch, tmp_path, [[started], [submitted]])
    # The finally-block reconciliation polls until its deadline, so the double
    # needs a finite but sufficient poll budget.
    supervisor = _ImmediateSupervisor([None] * 400)
    # Advance past the supervisor observation window but stay inside the parent
    # submission window, which is what a real launch requires.
    clock = FakeClock(step=bg._OBSERVATION_TIMEOUT + 0.1)
    result = bg.launch_background(
        str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
        clock=clock, sleeper=lambda _: None,
        cancel_requested=lambda: False,
        cancel_write=lambda fd, payload: 1,
        identity_probe=lambda pid: (pid, 4242),
    )
    assert result["outcome"] == "submitted"
    assert result["launcher_pid"] == 7
    # The observation loop must have advanced beyond one supervisor window.
    assert clock.calls >= 2
    assert len(reads) >= 2


# UNIT 1B-2 log and lease lifecycle proofs.
def test_b17_log_creation_is_private_exclusive_and_no_follow(tmp_path):
    """Creation is exclusive, private, regular-file-only and never follows links."""
    path = Path(tmp_path) / "s.agent-launch.log"
    log = bg._RotatingLog(path)
    log.open()
    try:
        assert path.stat().st_mode & 0o077 == 0
        # A second open must refuse the existing path instead of truncating it.
        with pytest.raises(FileExistsError):
            bg._RotatingLog(path).open()
        log.write(b"kept")
    finally:
        log.close()
    assert path.read_bytes() == b"kept"

    # A symlink at the log path must be refused, and its target untouched.
    link = Path(tmp_path) / "link.agent-launch.log"
    target = Path(tmp_path) / "target.txt"
    target.write_bytes(b"original")
    link.symlink_to(target)
    with pytest.raises(OSError):
        bg._RotatingLog(link).open()
    assert target.read_bytes() == b"original"


def test_b18_rotation_byte_boundaries_and_retained_content(tmp_path):
    """Rotation triggers exactly at the limit and retains exact byte suffixes."""
    path = Path(tmp_path) / "s.agent-launch.log"
    log = bg._RotatingLog(path, max_bytes=4, backups=2)
    log.open()
    try:
        log.write(b"abc")          # below the limit: no rotation
        assert path.read_bytes() == b"abc"
        assert not path.with_name(path.name + ".1").exists()
        log.write(b"d")            # exactly at the limit: still no rotation
        assert path.read_bytes() == b"abcd"
        assert not path.with_name(path.name + ".1").exists()
        log.write(b"e")            # one byte over: rotate, keep the suffix
        assert path.read_bytes() == b"e"
        assert path.with_name(path.name + ".1").read_bytes() == b"abcd"
    finally:
        log.close()

    # Multibyte encoded bytes are counted as bytes, not characters. A byte
    # bounded log may split one character across a rotation, so the contract is
    # that no byte is lost: backups plus the active file reproduce the input.
    multi = Path(tmp_path) / "m.agent-launch.log"
    payload = "é".encode("utf-8") + "ü".encode("utf-8")
    log = bg._RotatingLog(multi, max_bytes=3, backups=2)
    log.open()
    try:
        log.write("é".encode("utf-8"))   # two bytes
        log.write("ü".encode("utf-8"))   # two bytes: crosses the limit
    finally:
        log.close()
    retained = b"".join(
        multi.with_name(multi.name + suffix).read_bytes()
        for suffix in (".2", ".1", "")
        if multi.with_name(multi.name + suffix).exists()
    )
    assert retained == payload
    assert multi.stat().st_size <= 3


def test_b19_repeated_rotation_keeps_exact_two_backups(tmp_path):
    """Repeated rotation retains exactly two backups and bounded disk usage."""
    path = Path(tmp_path) / "s.agent-launch.log"
    log = bg._RotatingLog(path, max_bytes=2, backups=2)
    log.open()
    try:
        for chunk in (b"aa", b"bb", b"cc", b"dd", b"ee"):
            log.write(chunk)
    finally:
        log.close()
    assert path.read_bytes() == b"ee"
    assert path.with_name(path.name + ".1").read_bytes() == b"dd"
    assert path.with_name(path.name + ".2").read_bytes() == b"cc"
    assert not path.with_name(path.name + ".3").exists()
    total = sum(p.stat().st_size for p in Path(tmp_path).iterdir())
    assert total == 6


def test_b21_lease_lifetime_closes_on_every_terminal_path(monkeypatch, tmp_path):
    """The lease exists for the whole supervisor lifetime and is released after."""
    observed = []
    log_path = tmp_path / "s.agent-launch.log"
    lease = bg.active_launch_lease(log_path)

    def record_lease(*args, **kwargs):
        observed.append("lease")

    child = FakeChild(pid=4242, polls=[None] * 40 + [0], wait_status=0)
    child.stdout = FakeStream(11, [b"out", b""])
    child.stderr = FakeStream(12, [b"err", b""])
    sent = []
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    monkeypatch.setattr(bg._selectors, "DefaultSelector", lambda: FakeSelector({11: child.stdout, 12: child.stderr}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *a: None)
    reads = {11: [b"out", b""], 12: [b"err", b""]}
    monkeypatch.setattr(bg._os, "read", lambda fd, n: reads[fd].pop(0))
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    monkeypatch.setattr(bg, "_write_lease", record_lease)

    def record_spawn(*args, **kwargs):
        observed.append("spawn")
        return child

    request = {"folder": str(tmp_path), "session_id": "s", "log_path": str(log_path)}
    bg._supervise(request, 3, popen=record_spawn, clock=FakeClock(), sleeper=lambda _: None)
    # The lease is acquired before the launcher is spawned and released after.
    assert observed == ["lease", "spawn"]
    assert not lease.exists()
    assert any(frame["kind"] == "submitted" for frame in sent)


def test_b20_submitted_is_not_ready_and_final_status_logged(monkeypatch, tmp_path):
    """A live-through-submit launcher logs its exact final status and is reaped."""
    child = FakeChild(pid=5150, polls=[None] * 40 + [42], wait_status=42)
    child.stdout = FakeStream(11, [b"out", b""])
    child.stderr = FakeStream(12, [b"err", b""])
    sent = []
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    monkeypatch.setattr(bg._selectors, "DefaultSelector", lambda: FakeSelector({11: child.stdout, 12: child.stderr}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *a: None)
    reads = {11: [b"out", b""], 12: [b"err", b""]}
    monkeypatch.setattr(bg._os, "read", lambda fd, n: reads[fd].pop(0))
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    request = {"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s.log")}
    bg._supervise(request, 3, popen=lambda *a, **k: child, clock=FakeClock(), sleeper=lambda _: None)
    kinds = [frame["kind"] for frame in sent]
    assert kinds[0] == "started"
    assert "submitted" in kinds
    # Submission is not readiness: no frame may claim readiness.
    assert all("ready" not in json.dumps(frame).lower() for frame in sent)
    assert (tmp_path / "s.log").read_bytes().endswith(b"launcher exit status=42\n")
    assert ("wait", bg._OBSERVATION_TIMEOUT) in child.calls


# UNIT 1B-2 focused lifecycle proofs for log, lease and cancellation authority.
def test_b17_log_open_refuses_non_regular_file(monkeypatch, tmp_path):
    """A substituted special file must never receive log bytes."""
    closed = []
    monkeypatch.setattr(bg._os, "open", lambda path, flags, mode: 91)
    monkeypatch.setattr(bg._os, "fstat", lambda fd: SimpleNamespace(st_mode=0))
    monkeypatch.setattr(bg._os, "close", lambda fd: closed.append(fd))
    log = bg._RotatingLog(Path(tmp_path) / "s.agent-launch.log")
    with pytest.raises(OSError, match="not a regular file"):
        log.open()
    assert closed == [91]
    assert log._fd is None


def test_b20_post_submission_cancellation_is_classified(monkeypatch, tmp_path, fake_clock):
    """Cancellation after submission raises KeyboardInterrupt and reports it."""
    child = FakeChild(pid=444, polls=[None] * 200 + [0], wait_status=0)
    child.stdout = FakeStream(1, [b"out", b""])
    child.stderr = FakeStream(2, [b"err", b""])
    sent = []
    state = {"cancel": False}

    def send(fd, payload):
        sent.append(payload)
        if payload.get("kind") == "submitted":
            state["cancel"] = True

    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_send_frame", send)
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *a, **k: True)
    monkeypatch.setattr(bg._selectors, "DefaultSelector",
                        lambda: FakeSelector({1: child.stdout, 2: child.stderr}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *a: None)
    monkeypatch.setattr(bg._os, "read",
                        lambda fd, n: (child.stdout.chunks if fd == 1 else child.stderr.chunks).pop(0))
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    request = {"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s.log")}
    bg._supervise(request, 3, popen=lambda *a, **k: child, clock=fake_clock,
                  sleeper=fake_clock.sleep, cancel_requested=lambda: state["cancel"])
    cleanup = [item for item in sent if item.get("kind") == "cleanup"]
    assert cleanup and cleanup[0]["class"] == "cancellation"
    assert cleanup[0]["cleanup_confirmed"] is True


def test_b20_post_submission_drain_deadline_and_close_errors(monkeypatch, tmp_path, fake_clock):
    """A launcher that exits with open streams is drained for a bounded time."""
    class StubbornStream(FakeStream):
        def close(self):
            raise OSError("close failed")

    child = FakeChild(pid=445, polls=[None] * 200 + [0] * 200, wait_status=0)
    child.stdout = StubbornStream(1, [b"out"])
    child.stderr = StubbornStream(2, [b"err"])
    sent = []
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *a, **k: True)
    monkeypatch.setattr(bg._selectors, "DefaultSelector",
                        lambda: FakeSelector({1: child.stdout, 2: child.stderr}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *a: None)
    monkeypatch.setattr(bg._os, "read", lambda fd, n: b"")
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    request = {"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s.log")}
    bg._supervise(request, 3, popen=lambda *a, **k: child, clock=fake_clock, sleeper=fake_clock.sleep)
    assert any(item["kind"] == "submitted" for item in sent)
    assert (tmp_path / "s.log").read_bytes().endswith(b"launcher exit status=0\n")


def test_supervisor_finally_tolerates_ack_close_and_lease_remove_errors(monkeypatch, tmp_path, fake_clock):
    """Descriptor and lease release failures must not mask the outcome."""
    child = FakeChild(pid=446, polls=[None] * 200 + [0], wait_status=0)
    child.stdout = FakeStream(1, [b"out", b""])
    child.stderr = FakeStream(2, [b"err", b""])
    sent = []
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: sent.append(payload))
    monkeypatch.setattr(bg, "_cleanup_owned", lambda *a, **k: True)
    monkeypatch.setattr(bg._selectors, "DefaultSelector",
                        lambda: FakeSelector({1: child.stdout, 2: child.stderr}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *a: None)
    monkeypatch.setattr(bg._os, "read",
                        lambda fd, n: (child.stdout.chunks if fd == 1 else child.stderr.chunks).pop(0))
    real_close = bg._os.close

    def close(fd):
        if fd == 3:
            raise OSError("closed")
        return real_close(fd)

    monkeypatch.setattr(bg._os, "close", close)
    monkeypatch.setattr(Path, "unlink", lambda self: (_ for _ in ()).throw(OSError("busy")))
    request = {"folder": str(tmp_path), "session_id": "s", "log_path": str(tmp_path / "s.log")}
    bg._supervise(request, 3, popen=lambda *a, **k: child, clock=fake_clock, sleeper=fake_clock.sleep)
    assert any(item["kind"] == "submitted" for item in sent)


def test_supervisor_entry_sets_nonblocking_and_closes_cancel_fd(monkeypatch, tmp_path):
    """The supervisor owns the inherited cancellation descriptor."""
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"kind": "workspace-agent-supervisor", "cancel_fd": 5}))
    blocking, closed, calls = [], [], []
    monkeypatch.setattr(bg._os, "set_blocking", lambda fd, flag: blocking.append((fd, flag)))
    monkeypatch.setattr(bg._os, "close", lambda fd: closed.append(fd))
    monkeypatch.setattr(bg, "_supervise", lambda req, fd, **kwargs: calls.append(kwargs))
    bg._supervisor_entry(str(request), 7)
    assert blocking == [(5, False)]
    assert closed == [5]
    assert calls == [{"cancel_fd": 5}]


def test_entrypoint_command_anchors_relative_entry(monkeypatch):
    """A relative entry point is anchored so the detached process can resolve it."""
    monkeypatch.delenv("TOPSAILAI_CLI_ENTRY", raising=False)
    monkeypatch.setattr(bg._sys, "argv", ["cli/topsailai_cli.py"])
    monkeypatch.setattr(bg._os, "getcwd", lambda: "/base")
    assert bg._entrypoint_command() == ["/base/cli/topsailai_cli.py"]
    assert bg._entrypoint_command("/other") == ["/other/cli/topsailai_cli.py"]
    monkeypatch.setattr(bg._sys, "argv", ["/abs/topsailai_cli.py"])
    assert bg._entrypoint_command() == ["/abs/topsailai_cli.py"]
    monkeypatch.setenv("TOPSAILAI_CLI_ENTRY", "topsailai")
    assert bg._entrypoint_command() == ["topsailai"]


def test_launch_background_nt_platform_flags(monkeypatch, tmp_path):
    """Windows uses creation flags instead of POSIX session options."""
    frames = [[{"kind": "started", "launcher_pid": 78}],
              [{"kind": "submitted", "session": "s", "launcher_pid": 78,
                "log_path": str(tmp_path / "workspace" / "task" / "s.agent-launch.log")}]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    monkeypatch.setattr(bg._os, "name", "nt")
    calls = []
    result = bg.launch_background(str(tmp_path), "s",
                                  spawn=lambda *a, **k: calls.append(k) or supervisor,
                                  clock=clock, sleeper=clock.sleep)
    assert result["outcome"] == "submitted"
    assert "start_new_session" not in calls[0]
    assert "pass_fds" not in calls[0]
    assert calls[0]["creationflags"] == (bg._subprocess.CREATE_NEW_PROCESS_GROUP
                                         | bg._subprocess.DETACHED_PROCESS)


def test_r27_conflicting_started_during_cancellation_is_rejected(monkeypatch, tmp_path):
    """A second, different started frame during cancellation fails closed."""
    started = {"kind": "started", "launcher_pid": 1901,
               "launcher_identity": "(1901, 9, 'authoritative')"}
    other = {"kind": "started", "launcher_pid": 1902,
             "launcher_identity": "(1902, 9, 'authoritative')"}
    clock, supervisor = _patch_launch_background_common(
        monkeypatch, tmp_path, [[started], [other]], supervisor=_ImmediateSupervisor([None] * 50))
    with pytest.raises(bg.BackgroundUnconfirmed, match="conflicting started"):
        bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                             clock=clock, sleeper=clock.sleep,
                             cancel_requested=lambda: True,
                             cancel_write=lambda fd, data: len(data))


def test_launch_background_keyboard_interrupt_routes_to_cancellation(monkeypatch, tmp_path):
    """An interrupt during initialization is handled by the cancellation protocol."""
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, [[]])
    monkeypatch.setattr(bg, "_read_frames",
                        lambda fd, buffer: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(bg, "_cancel_supervisor_transport",
                        lambda *a, **k: {"outcome": "cancelled", "exit_code": 130})
    result = bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                                  clock=clock, sleeper=clock.sleep,
                                  cancel_write=lambda fd, data: len(data))
    assert result["exit_code"] == 130


def test_launch_background_write_fd_close_errors_tolerated(monkeypatch, tmp_path):
    """A failing descriptor release must not break a successful submission."""
    frames = [[{"kind": "started", "launcher_pid": 79}],
              [{"kind": "submitted", "session": "s", "launcher_pid": 79,
                "log_path": str(tmp_path / "workspace" / "task" / "s.agent-launch.log")}]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    real_close = bg._os.close

    def close(fd):
        if fd == 11:
            raise OSError("closed")
        return real_close(fd)

    monkeypatch.setattr(bg._os, "close", close)
    result = bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                                  clock=clock, sleeper=clock.sleep)
    assert result["outcome"] == "submitted"


def test_write_lease_no_progress_raises(monkeypatch, tmp_path):
    """A lease write that makes no progress must fail instead of looping."""
    monkeypatch.setattr(bg._os, "write", lambda fd, view: 0)
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    with pytest.raises(OSError, match="no progress"):
        bg._write_lease(tmp_path / "x.lease", pid=1, identity=(1, 2))


def test_read_lease_rejects_malformed_records(tmp_path):
    """Only a positive integer pid makes a lease record usable."""
    lease = tmp_path / "x.lease"
    lease.write_text("[]")
    assert bg._read_lease(lease) is None
    lease.write_text('{"pid": 0}')
    assert bg._read_lease(lease) is None
    lease.write_text('{"pid": "x"}')
    assert bg._read_lease(lease) is None
    lease.write_text('{"pid": 5, "start": 9}')
    assert bg._read_lease(lease) == {"pid": 5, "start": 9}


def test_process_absent_requires_authoritative_evidence(monkeypatch):
    """Only a missing /proc entry proves absence."""
    monkeypatch.setattr(bg._os, "name", "nt")
    assert bg._process_absent(1) is False
    monkeypatch.setattr(bg._os, "name", "posix")
    monkeypatch.setattr(bg._os, "stat",
                        lambda path: (_ for _ in ()).throw(FileNotFoundError()))
    assert bg._process_absent(1) is True
    monkeypatch.setattr(bg._os, "stat", lambda path: (_ for _ in ()).throw(OSError("denied")))
    assert bg._process_absent(1) is False
    monkeypatch.setattr(bg._os, "stat", lambda path: SimpleNamespace())
    assert bg._process_absent(1) is False


def test_lease_owner_alive_missing_start_and_tuple_identity(tmp_path):
    """A lease without a start token protects; a tuple identity is unwrapped."""
    lease = tmp_path / "x.lease"
    lease.write_text('{"pid": 5}')
    assert bg._lease_owner_alive(lease) is True
    lease.write_text('{"pid": 5, "start": 9}')
    assert bg._lease_owner_alive(lease, identity_probe=lambda pid: (pid, 9)) is True
    assert bg._lease_owner_alive(lease, identity_probe=lambda pid: (pid, 8)) is False


# Non-interactive launch flag: the request is the only channel between the
# foreground caller and the detached supervisor, so the flag must survive it.
def _capture_requests(monkeypatch, tmp_path):
    """Record every private request the public launcher writes."""
    requests = []
    request_path = Path(tmp_path) / "request.json"

    def request_file(folder, request):
        requests.append(dict(request))
        return request_path, 0

    monkeypatch.setattr(bg, "_request_file", request_file)
    return requests


def test_non_interactive_flag_is_persisted_in_the_supervisor_request(monkeypatch, tmp_path):
    """A requested non-interactive launch is recorded for the supervisor."""
    log_path = str(tmp_path / "workspace" / "task" / "s.agent-launch.log")
    frames = [[{"kind": "started", "launcher_pid": 77}],
              [{"kind": "submitted", "session": "s", "launcher_pid": 77,
                "log_path": log_path}]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    requests = _capture_requests(monkeypatch, tmp_path)
    bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                         clock=clock, sleeper=clock.sleep, non_interactive=True)
    assert requests
    assert all(request.get("non_interactive") is True for request in requests)


def test_supervisor_request_omits_non_interactive_when_not_requested(monkeypatch, tmp_path):
    """An ordinary launch keeps the historical request shape exactly."""
    log_path = str(tmp_path / "workspace" / "task" / "s.agent-launch.log")
    frames = [[{"kind": "started", "launcher_pid": 77}],
              [{"kind": "submitted", "session": "s", "launcher_pid": 77,
                "log_path": log_path}]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    requests = _capture_requests(monkeypatch, tmp_path)
    bg.launch_background(str(tmp_path), "s", spawn=lambda *a, **k: supervisor,
                         clock=clock, sleeper=clock.sleep)
    assert requests
    assert all("non_interactive" not in request for request in requests)


def test_supervisor_spawns_launcher_with_non_interactive_flag(monkeypatch, tmp_path):
    """The detached supervisor forwards the flag to the launcher it spawns."""
    child = FakeChild(pid=7124, polls=[None, 0])
    child.stdout = FakeStream(11, [])
    child.stderr = FakeStream(12, [])
    calls = []
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: None)
    monkeypatch.setattr(bg._selectors, "DefaultSelector",
                        lambda: FakeSelector({11: child.stdout, 12: child.stderr}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *a: None)
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"")
    original_log = bg._RotatingLog
    monkeypatch.setattr(bg, "_RotatingLog",
                        lambda path: original_log(path, max_bytes=2, backups=2))
    request = {"folder": str(tmp_path), "session_id": "s",
               "log_path": str(tmp_path / "s.log"), "non_interactive": True}
    bg._supervise(request, 9, popen=lambda *a, **k: calls.append((a, k)) or child,
                  clock=FakeClock(), sleeper=lambda seconds: None)
    assert calls[0][0][0] == ["topsailai_launch_agent", "--subprocess",
                              "--session-id", "s", "--non-interactive"]


def test_supervisor_launcher_argv_is_unchanged_without_the_flag(monkeypatch, tmp_path):
    """A request without the flag spawns the historical launcher argv."""
    child = FakeChild(pid=7125, polls=[None, 0])
    child.stdout = FakeStream(11, [])
    child.stderr = FakeStream(12, [])
    calls = []
    monkeypatch.setattr(bg, "_write_lease", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: None)
    monkeypatch.setattr(bg._selectors, "DefaultSelector",
                        lambda: FakeSelector({11: child.stdout, 12: child.stderr}))
    monkeypatch.setattr(bg._os, "set_blocking", lambda *a: None)
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"")
    original_log = bg._RotatingLog
    monkeypatch.setattr(bg, "_RotatingLog",
                        lambda path: original_log(path, max_bytes=2, backups=2))
    request = {"folder": str(tmp_path), "session_id": "s",
               "log_path": str(tmp_path / "s.log")}
    bg._supervise(request, 9, popen=lambda *a, **k: calls.append((a, k)) or child,
                  clock=FakeClock(), sleeper=lambda seconds: None)
    assert calls[0][0][0] == ["topsailai_launch_agent", "--subprocess",
                              "--session-id", "s"]


# Initial task forwarding through the detached raw supervisor.
def test_initial_task_is_persisted_in_private_supervisor_request(monkeypatch, tmp_path):
    """The raw background boundary records the exact task for its supervisor."""
    log_path = str(tmp_path / "workspace" / "task" / "s.agent-launch.log")
    frames = [[{"kind": "started", "launcher_pid": 77}],
              [{"kind": "submitted", "session": "s", "launcher_pid": 77,
                "log_path": log_path}]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    requests = _capture_requests(monkeypatch, tmp_path)
    task = "检查后台任务\n第二行"
    bg.launch_background(
        str(tmp_path), "s", task=task,
        spawn=lambda *args, **kwargs: supervisor,
        clock=clock, sleeper=clock.sleep,
    )
    assert requests
    assert all(request.get("task") == task for request in requests)


def test_supervisor_request_omits_task_when_not_requested(monkeypatch, tmp_path):
    """An ordinary raw background launch keeps its historical request shape."""
    log_path = str(tmp_path / "workspace" / "task" / "s.agent-launch.log")
    frames = [[{"kind": "started", "launcher_pid": 77}],
              [{"kind": "submitted", "session": "s", "launcher_pid": 77,
                "log_path": log_path}]]
    clock, supervisor = _patch_launch_background_common(monkeypatch, tmp_path, frames)
    requests = _capture_requests(monkeypatch, tmp_path)
    bg.launch_background(
        str(tmp_path), "s", spawn=lambda *args, **kwargs: supervisor,
        clock=clock, sleeper=clock.sleep,
    )
    assert requests
    assert all("task" not in request for request in requests)


def test_supervisor_spawns_launcher_with_exact_initial_task(monkeypatch, tmp_path):
    """The raw supervisor restores the task as one launcher argv value."""
    child = FakeChild(pid=7126, polls=[None, 0])
    child.stdout = FakeStream(11, [])
    child.stderr = FakeStream(12, [])
    calls = []
    monkeypatch.setattr(bg, "_write_lease", lambda *args, **kwargs: None)
    monkeypatch.setattr(bg, "_send_frame", lambda fd, payload: None)
    monkeypatch.setattr(
        bg._selectors, "DefaultSelector",
        lambda: FakeSelector({11: child.stdout, 12: child.stderr}),
    )
    monkeypatch.setattr(bg._os, "set_blocking", lambda *args: None)
    monkeypatch.setattr(bg._os, "close", lambda fd: None)
    monkeypatch.setattr(bg._os, "read", lambda fd, size: b"")
    original_log = bg._RotatingLog
    monkeypatch.setattr(
        bg, "_RotatingLog",
        lambda path: original_log(path, max_bytes=2, backups=2),
    )
    task = "background task\n第二行"
    request = {
        "folder": str(tmp_path), "session_id": "s",
        "log_path": str(tmp_path / "s.log"), "task": task,
    }
    bg._supervise(
        request, 9,
        popen=lambda *args, **kwargs: calls.append((args, kwargs)) or child,
        clock=FakeClock(), sleeper=lambda seconds: None,
    )
    assert calls[0][0][0] == [
        "topsailai_launch_agent", "--subprocess", "--session-id", "s",
        "--task", task,
    ]
