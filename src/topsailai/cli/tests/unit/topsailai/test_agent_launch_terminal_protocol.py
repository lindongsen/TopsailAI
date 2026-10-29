"""Tests for the selectable background terminal mechanisms."""

import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import time
import uuid
from pathlib import Path
from unittest.mock import patch
import pytest
from cli_topsailai import agent_launch_terminal as terminal

from test_agent_launch_terminal_helpers import *

def test_socket_eof_is_cancellation_only_before_submission():
    """A closed control socket cancels before submission but not after it."""
    from cli_topsailai import agent_launch_background as bg

    parent, child = socket.socketpair()
    try:
        parent.close()
        assert bg._cancel_requested(child, None, submitted=False) is True
        assert bg._cancel_requested(child, None, submitted=True) is False
        assert bg._control_lost(child) is True
    finally:
        child.close()


def test_socket_open_channel_is_not_cancellation():
    """An idle but open control channel is never mistaken for a cancellation."""
    from cli_topsailai import agent_launch_background as bg

    parent, child = socket.socketpair()
    try:
        parent.setblocking(False)
        child.setblocking(False)
        assert bg._cancel_requested(child, None, submitted=False) is False
        assert bg._control_lost(child) is False
        parent.sendall(b"1")
        assert bg._cancel_requested(child, None, submitted=False) is True
    finally:
        parent.close()
        child.close()


def test_supervisor_exit_is_proven_from_the_process_table(home):
    """reap() proves process exit instead of trusting a closed connection."""
    transport, peer = _real_transport(home, os.getpid())
    try:
        transport.eof = True
        stopped = []
        with patch.object(terminal, "_stop_container",
                          lambda a, pid, identity=None: stopped.append(pid) or True):
            assert transport.reap() is False
        assert stopped == [os.getpid()]
    finally:
        transport.conn.close()
        peer.close()


def test_supervisor_exited_uses_process_absence_not_socket_state(home):
    """A live supervisor is not reported exited merely because the socket closed."""
    transport, peer = _real_transport(home, os.getpid())
    try:
        transport.eof = True
        assert transport.supervisor_exited() is False
    finally:
        transport.conn.close()
        peer.close()


def test_dtach_stop_refuses_unverified_historical_pid(home, capsys):
    """A reused historical PID is never signalled without identity re-verification."""
    attempt = terminal.prepare_attempt("dtach", "session-1")
    live = os.getpid()
    stopped = terminal._stop_container(attempt, live, (live, -1))
    assert stopped is False
    assert "could not be re-verified" in capsys.readouterr().out


def test_dtach_stop_signals_verified_identity(home, capsys):
    """A verified supervisor identity authorizes exactly one SIGTERM."""
    attempt = terminal.prepare_attempt("dtach", "session-1")
    child = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        identity = terminal._process_identity(child.pid)
        assert identity is not None
        assert terminal._stop_container(attempt, child.pid, identity) is True
        child.wait(timeout=10)
        assert terminal._process_dead(child.pid) is True
        print(f"[INFO] Verified dtach stop killed pid={child.pid}")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
            print(f"[INFO] Cleaned up probe pid={child.pid}")


def test_pre_handshake_failure_establishes_and_discharges_custody(home, capsys):
    """A handshake failure still stops the supervisor published in its record."""
    attempt = terminal.prepare_attempt("dtach", "session-1")
    child = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        identity = terminal._process_identity(child.pid)
        assert identity is not None
        record = {"pid": child.pid, "start": identity[1]}
        attempt.record_path.write_text(json.dumps(record), encoding="utf-8")
        assert terminal._recover_pre_handshake(
            attempt, None, clock=time.monotonic, sleeper=time.sleep) is True
        child.wait(timeout=10)
        assert terminal._process_dead(child.pid) is True
        print(f"[INFO] Pre-handshake custody stopped pid={child.pid}")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
            print(f"[INFO] Cleaned up probe pid={child.pid}")


def test_pre_handshake_without_record_reports_no_custody(home, capsys):
    """No published record means no supervisor identity can be trusted.

    Absence of a record is not proof of custody: nothing identifies the
    supervisor, so the result must be unproven (fail closed) rather than True.
    """
    attempt = terminal.prepare_attempt("tmux", "session-1")
    assert terminal.read_recovery_record(attempt.record_path) is None
    assert terminal._recover_pre_handshake(
        attempt, None, clock=time.monotonic, sleeper=time.sleep) is False
    assert "custody is unproven" in capsys.readouterr().out


def test_pre_handshake_without_record_keeps_live_client_unproven(home, capsys):
    """A live client with no record is reported unproven and its material kept."""
    attempt = terminal.prepare_attempt("dtach", "session-1")
    child = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        assert terminal.read_recovery_record(attempt.record_path) is None
        result = terminal._recover_pre_handshake(
            attempt, child, clock=time.monotonic, sleeper=time.sleep)
        # Sampled before any fallback termination: the client is still alive and
        # custody must therefore be unproven.
        assert child.poll() is None
        assert result is False
        assert attempt.directory.exists() is True
        assert "custody is unproven" in capsys.readouterr().out
        print(f"[INFO] Unproven custody observed with live client pid={child.pid}")
    finally:
        if child.poll() is None:
            os.kill(child.pid, 15)
            print(f"[INFO] Cleaned up probe pid={child.pid} with SIGTERM")
            child.wait(timeout=10)


def test_reap_client_timeout_is_an_explicit_failure():
    """A client that never exits yields an explicit failure, not a warning only."""

    class _Stuck:
        pid = 4242

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="tmux", timeout=timeout)

    assert terminal._reap_client(_Stuck(), wait_timeout=0.01) is False


def test_reap_client_reports_success_for_exited_client():
    """A client that exits is reported as successfully reaped."""
    child = subprocess.Popen(["true"])
    try:
        assert terminal._reap_client(child, wait_timeout=10) is True
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


def test_write_recovery_record_publishes_private_identity(home):
    """The supervisor publishes a 0600 identity record before connecting."""
    attempt = terminal.prepare_attempt("dtach", "session-1")
    terminal.write_recovery_record(attempt.record_path)
    record = terminal.read_recovery_record(attempt.record_path)
    assert record is not None
    assert record["pid"] == os.getpid()
    assert stat.S_IMODE(attempt.record_path.stat().st_mode) == 0o600


def test_cleanup_ack_without_ownership_is_rejected_not_crashing():
    """An unobserved owner rejects cleanup proof instead of raising AttributeError.

    A pre-submission interruption can arrive before any ownership frame is read.
    Validation must then reject the acknowledgement, otherwise the AttributeError
    would replace the interruption and change its semantics.
    """
    from cli_topsailai import agent_launch_background as bg

    ack = {"kind": "cleanup", "session": "s", "launcher_pid": 41,
           "launcher_identity": "owned", "cleanup_confirmed": True}
    assert bg._validate_launcher_cleanup_ack(ack, None) is False


def test_reconcile_records_late_ownership_before_cleanup_ack(home):
    """A started frame that arrives after an interruption still proves ownership.

    The interruption can land before the first frame is read, so reconciliation
    must record non-cleanup frames. Otherwise the cleanup acknowledgement can
    never be correlated and launcher death cannot be proven from its PID.
    """
    attempt = terminal.prepare_attempt("tmux", "session-1")
    parent, peer = socket.socketpair()
    transport = terminal.TerminalTransport(
        attempt, parent, {"pid": os.getpid()}, clock=time.monotonic,
        sleeper=lambda _: None, client=None,
        supervisor_identity=terminal._process_identity(os.getpid()))
    started = {"kind": "started", "state": "initialized", "session": "session-1",
               "launcher_pid": 4242, "launcher_identity": "owned",
               "log_path": "/tmp/log"}
    cleanup = {"kind": "cleanup", "session": "session-1", "launcher_pid": 4242,
               "launcher_identity": "owned", "cleanup_confirmed": True}
    try:
        peer.sendall(json.dumps(started).encode() + b"\n"
                     + json.dumps(cleanup).encode() + b"\n")
        ack = terminal._reconcile(transport, clock=time.monotonic,
                                  sleeper=lambda _: None)
        assert transport.ownership is not None
        assert transport.ownership.launcher_pid == 4242
        assert ack is not None
        assert ack["cleanup_confirmed"] is True
    finally:
        peer.close()
        transport.close()


def test_signal_owned_refuses_unverifiable_identity(capsys):
    """An identity that cannot be re-verified is never signalled."""
    live = os.getpid()
    assert terminal._signal_owned(live, None) is False
    assert terminal._signal_owned(live, (live, -1)) is False
    output = capsys.readouterr().out
    assert "could not be re-verified" in output


def test_signal_owned_reverifies_identity_immediately_before_signalling(
        monkeypatch, capsys):
    """Identity is re-checked at signal time, not only when it was recorded."""
    live = os.getpid()
    identity = terminal._process_identity(live)
    assert identity is not None
    checks = []
    monkeypatch.setattr(terminal, "_identity_matches",
                        lambda pid, recorded: checks.append((pid, recorded)) or False)
    assert terminal._signal_owned(live, identity) is False
    assert checks == [(live, identity)]
    assert "could not be re-verified" in capsys.readouterr().out


def test_signal_owned_uses_pidfd_when_available(monkeypatch, capsys):
    """Where pidfd exists the signal is delivered through the bound descriptor."""
    live = os.getpid()
    identity = terminal._process_identity(live)
    assert identity is not None
    sent = []
    monkeypatch.setattr(os, "pidfd_open", lambda pid: 77, raising=False)
    monkeypatch.setattr(signal, "pidfd_send_signal",
                        lambda fd, sig: sent.append((fd, sig)), raising=False)
    monkeypatch.setattr(os, "close", lambda fd: sent.append(("close", fd)))
    assert terminal._signal_owned(live, identity) is True
    assert sent == [(77, signal.SIGTERM), ("close", 77)]
    assert "through pidfd" in capsys.readouterr().out


def test_process_absence_fails_closed_without_proc(monkeypatch, capsys):
    """A host without /proc must not report a process as authoritatively absent."""
    monkeypatch.setattr(terminal, "_proc_available", lambda: False)
    assert terminal._process_absent(os.getpid()) is False
    assert terminal._process_dead(os.getpid()) is False
    assert terminal._process_identity(os.getpid()) is None
    assert terminal._process_state(os.getpid()) is None


def test_dtach_stop_without_supervisor_identity_is_unproven(home, capsys):
    """A dtach attempt with no supervisor identity is never reported clean."""
    attempt = terminal.prepare_attempt("dtach", "session-1")
    assert terminal._stop_container(attempt, None, None) is False
    assert "container state is unproven" in capsys.readouterr().out
