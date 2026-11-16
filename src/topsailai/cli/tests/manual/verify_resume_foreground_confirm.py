#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Manually verify a foreground resume reports success after a normal exit.

Drives the real ``resume_session_result`` boundary in foreground ``dtach`` mode
with a stub driver that publishes a control socket, stays alive briefly, then
removes the socket and exits. That is exactly what a real agent does when the
operator ends the session, so this script proves the resume no longer reports a
healthy run as unreachable.

The run is started inside tmux because the resume path is interactive.

Author: DawsonLin
"""

import os
import socket
import sys
import tempfile
import threading
import time

CLI_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_ROOT = os.path.dirname(CLI_DIR)
sys.path.insert(0, CLI_DIR)
sys.path.insert(0, SRC_ROOT)

import json

from cli_topsailai import project_scope
from cli_topsailai.driver_ownership import DriverOwnership
from cli_topsailai.project_scope import resume_session_result

SESSION_ID = "manual-resume-foreground"
CHILD_PID = 987654


def _serve_heartbeat(socket_path, stop_event):
    """Answer heartbeats on a real unix socket, like the control server.

    The client requires a complete JSONL frame whose ``request_id`` matches the
    request and whose ``status`` is ``ok``, so the stub echoes the received
    identifier instead of inventing a response shape.
    """
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(socket_path)
        server.listen(4)
        server.settimeout(0.2)
        while not stop_event.is_set():
            try:
                connection, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                raw = connection.recv(4096)
                request = json.loads(raw.decode("utf-8").splitlines()[0])
                reply = {
                    "request_id": request.get("request_id"),
                    "status": "ok",
                    "data": {},
                }
                connection.sendall(json.dumps(reply).encode("utf-8") + b"\n")
            except (OSError, ValueError, IndexError):
                pass
            finally:
                connection.close()
    finally:
        server.close()


def main():
    """Run one foreground resume and assert the reported status."""
    home = tempfile.mkdtemp(prefix="manual-resume-home-")
    workspace = os.path.join(home, "project")
    os.makedirs(workspace, exist_ok=True)
    os.makedirs(os.path.join(home, "workspace", "task"), exist_ok=True)
    socket_path = os.path.join(
        home, "workspace", "task", f"{SESSION_ID}.{CHILD_PID}.session.sock"
    )

    class Child:
        """Child double that publishes a channel, then removes it on exit."""

        pid = CHILD_PID
        returncode = 0

        def wait(self, timeout=None):
            """Simulate the agent run and its own socket cleanup."""
            stop_event = threading.Event()
            server = threading.Thread(
                target=_serve_heartbeat, args=(socket_path, stop_event),
                daemon=True,
            )
            server.start()
            deadline = time.time() + 3.0
            while time.time() < deadline:
                time.sleep(0.05)
            stop_event.set()
            server.join(timeout=2.0)
            if os.path.exists(socket_path):
                os.remove(socket_path)
            print("[manual] agent exited and removed its control socket")
            return self.returncode

        def poll(self):
            """Report the exit status without blocking."""
            return self.returncode

        def terminate(self):
            """Accept a termination request without effect."""

        def kill(self):
            """Accept a kill request without effect."""

    record = {"project_workspace": workspace}
    receipt = {}
    original = {
        "lookup_persisted_session": project_scope.lookup_persisted_session,
        "session_liveness": project_scope.session_liveness,
        "_apply_selected_model_environment": project_scope._apply_selected_model_environment,
        "_driver_argv": project_scope._driver_argv,
        "_driver_is_resolvable": project_scope._driver_is_resolvable,
        "_build_driver_pidfile": project_scope._build_driver_pidfile,
        "_build_owned_command": project_scope._build_owned_command,
        "_delete_invalid_session_stdout": project_scope._delete_invalid_session_stdout,
    }
    project_scope.lookup_persisted_session = lambda *a, **k: record
    project_scope.session_liveness = lambda *a, **k: "idle"
    project_scope._apply_selected_model_environment = lambda *a, **k: ({}, set())
    project_scope._driver_argv = lambda driver: ["python3"]
    project_scope._driver_is_resolvable = lambda argv: True
    project_scope._build_driver_pidfile = lambda: None
    project_scope._build_owned_command = lambda *a, **k: (
        ["python3"], DriverOwnership(kind="dtach")
    )
    project_scope._delete_invalid_session_stdout = lambda *a, **k: []
    try:
        code = resume_session_result(
            SESSION_ID, home=home, emit_status=True,
            spawn=lambda argv, **kwargs: Child(), receipt=receipt,
        )
    finally:
        for name, value in original.items():
            setattr(project_scope, name, value)

    print(f"[manual] resume exit code: {code}")
    print(f"[manual] receipt: {receipt}")
    if code != 0:
        print("[manual] FAIL: a normal foreground exit was reported as a failure")
        return 1
    if receipt.get("startup_reason") != "heartbeat_answered":
        print("[manual] FAIL: the channel was never observed while running")
        return 1
    print("[manual] PASS: foreground resume confirmed the live channel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
