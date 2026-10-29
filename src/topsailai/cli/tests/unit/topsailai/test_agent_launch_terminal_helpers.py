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

@pytest.fixture()
def home(monkeypatch):
    """Point the attempt root at a short isolated home directory.

    AF_UNIX control socket paths are limited to 100 bytes, so the attempt root
    must stay short; pytest's default temporary directory is too long.
    """
    root = Path(__file__).resolve().parents[3] / ".tmp"
    root.mkdir(parents=True, exist_ok=True)
    directory = root / f"t-{uuid.uuid4().hex[:8]}"
    directory.mkdir()
    monkeypatch.setenv("TOPSAILAI_HOME", str(directory))
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)
        print(f"[INFO] Removed test home directory: {directory}")

class _FakeTransport:
    """Minimal terminal transport double that records lifecycle ordering."""

    def __init__(self, order, *, launcher_pid=4242, supervisor_pid=4243,
                 ownership=True):
        from types import SimpleNamespace

        self.order = order
        self.submitted = False
        self.supervisor_pid = supervisor_pid
        self.supervisor_identity = (supervisor_pid, 99)
        self.ownership = (SimpleNamespace(launcher_pid=launcher_pid)
                          if ownership else None)
        self.cleanup_ack = None
        self.closed = False

    def request_cancel(self):
        self.order.append("cancel")

    def reap(self):
        self.order.append("reap")
        return True

    def close(self):
        self.closed = True

def _install_submit_doubles(monkeypatch, transport, *, protocol_error):
    """Install the submit_terminal collaborators and record lifecycle order."""
    from types import SimpleNamespace

    from cli_topsailai import agent_launch_background as bg

    order = transport.order
    attempt = SimpleNamespace(directory=Path("/nonexistent-attempt"),
                              control_path=Path("/nonexistent-attempt/c"),
                              request_path=Path("/nonexistent-attempt/r.json"),
                              record_path=Path("/nonexistent-attempt/s.json"),
                              token="token", session_id="session-1",
                              mechanism="tmux")
    monkeypatch.setattr(terminal, "prepare_attempt", lambda m, s: attempt)
    monkeypatch.setattr(terminal, "write_request", lambda p, r: None)
    monkeypatch.setattr(terminal, "open_listener", lambda a: SimpleNamespace(
        close=lambda: None))
    monkeypatch.setattr(terminal, "build_command", lambda a, e, f, env: ["cmd"])
    monkeypatch.setattr(terminal, "accept_control",
                        lambda listener, a, **k: (SimpleNamespace(), {"pid": 4243}, b""))
    monkeypatch.setattr(terminal, "TerminalTransport",
                        lambda *a, **k: transport)
    monkeypatch.setattr(terminal, "_reconcile",
                        lambda t, **k: order.append("reconcile") or {"kind": "cleanup"})
    monkeypatch.setattr(terminal, "_launcher_gone",
                        lambda t, **k: order.append("launcher_gone") or True)
    monkeypatch.setattr(terminal, "cleanup_attempt",
                        lambda a, pid=None, identity=None: order.append("cleanup") or True)
    monkeypatch.setattr(terminal, "_remove_tree", lambda d: order.append("remove_tree"))
    monkeypatch.setattr(bg, "_entrypoint_command", lambda base=None: ["entry"])
    monkeypatch.setattr(bg, "_default_popen", lambda *a, **k: SimpleNamespace(pid=1))

    def protocol(*args, **kwargs):
        raise protocol_error

    monkeypatch.setattr(terminal, "_protocol", protocol)
    return attempt

def _real_transport(home, supervisor_pid):
    """Build a real TerminalTransport over a socketpair for lifecycle proofs."""
    attempt = terminal.prepare_attempt("tmux", "session-1")
    parent, peer = socket.socketpair()
    transport = terminal.TerminalTransport(
        attempt, parent, {"pid": supervisor_pid}, clock=time.monotonic,
        sleeper=lambda _: None, client=None,
        supervisor_identity=terminal._process_identity(supervisor_pid))
    return transport, peer

__all__ = ["home", "terminal", "_FakeTransport", "_install_submit_doubles", "_real_transport"]
