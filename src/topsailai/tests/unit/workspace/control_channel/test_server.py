"""
Unit tests for the control channel server.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-03
Purpose: Test control channel server lifecycle and request dispatch
"""

import json
import os
import socket
import tempfile
import threading
import time

import pytest

from topsailai.workspace.control_channel.handler import ControlHandler, ControlHandlerRegistry
from topsailai.workspace.control_channel.protocol import ControlContext, ControlRequest, ControlResponse
from topsailai.workspace.control_channel.server import ControlServer


class EchoHandler(ControlHandler):
    """Test handler that echoes the payload."""

    @property
    def action(self) -> str:
        return "echo"

    def handle(self, request: ControlRequest, context: ControlContext) -> ControlResponse:
        return ControlResponse(
            request_id=request.request_id,
            status="ok",
            result=request.payload,
        )


class StatusHandler(ControlHandler):
    """Test handler that returns a status object."""

    @property
    def action(self) -> str:
        return "status"

    def handle(self, request: ControlRequest, context: ControlContext) -> ControlResponse:
        return ControlResponse(
            request_id=request.request_id,
            status="ok",
            result={"running": True},
        )


class TestControlServer:
    """Tests for ControlServer."""

    @pytest.fixture
    def socket_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield os.path.join(tmpdir, "control.sock")

    @pytest.fixture
    def registry(self):
        reg = ControlHandlerRegistry()
        reg.register(EchoHandler())
        reg.register(StatusHandler())
        return reg

    @pytest.fixture
    def server(self, socket_path, registry):
        srv = ControlServer(
            socket_path=socket_path,
            registry=registry,
            context=ControlContext(),
            backlog=5,
            timeout=0.5,
        )
        yield srv
        srv.stop()

    def send_request(self, socket_path: str, request: dict) -> dict:
        """Connect to the server, send a request, and return the response."""
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(socket_path)
            sock.sendall(json.dumps(request).encode("utf-8") + b"\n")
            file_obj = sock.makefile("r")
            try:
                line = file_obj.readline()
            finally:
                file_obj.close()
        assert line
        return json.loads(line.strip())

    def test_start_creates_socket(self, server, socket_path):
        server.start()
        time.sleep(0.1)
        assert os.path.exists(socket_path)
        assert server.is_running()

    def test_stop_removes_socket(self, server, socket_path):
        server.start()
        time.sleep(0.1)
        server.stop()
        assert not server.is_running()
        assert not os.path.exists(socket_path)

    def test_stop_wakes_idle_accept_loop(self, socket_path, registry):
        """Stopping an idle server must not wait for its accept timeout."""
        server = ControlServer(
            socket_path=socket_path,
            registry=registry,
            context=ControlContext(),
            timeout=30,
        )
        server.start()
        time.sleep(0.1)

        start = time.perf_counter()
        server.stop()

        assert time.perf_counter() - start < 1
        assert not server.is_running()

    def test_echo_request(self, server, socket_path):
        server.start()
        time.sleep(0.1)
        response = self.send_request(
            socket_path,
            {"request_id": "r1", "action": "echo", "payload": {"msg": "hello"}},
        )
        assert response["request_id"] == "r1"
        assert response["status"] == "ok"
        assert response["result"] == {"msg": "hello"}

    def test_status_request(self, server, socket_path):
        server.start()
        time.sleep(0.1)
        response = self.send_request(
            socket_path,
            {"request_id": "r2", "action": "status"},
        )
        assert response["request_id"] == "r2"
        assert response["status"] == "ok"
        assert response["result"] == {"running": True}

    def test_unknown_action(self, server, socket_path):
        server.start()
        time.sleep(0.1)
        response = self.send_request(
            socket_path,
            {"request_id": "r3", "action": "missing"},
        )
        assert response["request_id"] == "r3"
        assert response["status"] == "error"
        assert "unknown action" in response["error"]

    def test_invalid_json(self, server, socket_path):
        server.start()
        time.sleep(0.1)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(socket_path)
            sock.sendall(b"not json\n")
            file_obj = sock.makefile("r")
            try:
                line = file_obj.readline()
            finally:
                file_obj.close()
        response = json.loads(line.strip())
        assert response["status"] == "error"
        assert "invalid json" in response["error"]

    def test_missing_request_id(self, server, socket_path):
        server.start()
        time.sleep(0.1)
        response = self.send_request(socket_path, {"action": "echo"})
        assert response["status"] == "error"
        assert "missing request_id" in response["error"]

    def test_concurrent_clients(self, server, socket_path):
        server.start()
        time.sleep(0.1)
        results = []
        errors = []

        def worker(index: int):
            try:
                response = self.send_request(
                    socket_path,
                    {"request_id": f"c{index}", "action": "echo", "payload": {"index": index}},
                )
                results.append(response)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 10
        request_ids = {r["request_id"] for r in results}
        assert request_ids == {f"c{i}" for i in range(10)}


from topsailai.workspace.control_channel.server import (
    ControlServer,
    get_or_start_control_server,
    release_control_server,
)
from topsailai.workspace.control_channel.transport import (
    create_unix_socket,
    is_socket_live,
)


class TestSocketLiveProbe:
    """Tests for socket liveness probing used by the singleton registry."""

    @pytest.fixture
    def socket_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield os.path.join(tmpdir, "probe.sock")

    def test_missing_socket_is_not_live(self, socket_path):
        assert is_socket_live(socket_path) is False

    def test_listening_socket_is_live(self, socket_path):
        sock = create_unix_socket(socket_path)
        try:
            assert is_socket_live(socket_path) is True
        finally:
            sock.close()
            if os.path.exists(socket_path):
                os.remove(socket_path)

    def test_stale_socket_file_is_not_live(self, socket_path):
        # Create a socket file without a listening server.
        with open(socket_path, "w") as f:
            f.write("")
        assert os.path.exists(socket_path)
        assert is_socket_live(socket_path) is False

    def test_create_unix_socket_removes_stale_file(self, socket_path):
        with open(socket_path, "w") as f:
            f.write("stale")
        sock = create_unix_socket(socket_path)
        try:
            assert is_socket_live(socket_path) is True
        finally:
            sock.close()
            if os.path.exists(socket_path):
                os.remove(socket_path)

    def test_create_unix_socket_refuses_live_socket(self, socket_path):
        sock = create_unix_socket(socket_path)
        try:
            with pytest.raises(OSError):
                create_unix_socket(socket_path)
        finally:
            sock.close()
            if os.path.exists(socket_path):
                os.remove(socket_path)


class TestSharedControlServer:
    """Tests for the per-(session_id, pid) singleton ControlServer registry."""

    @pytest.fixture
    def socket_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield os.path.join(tmpdir, "shared.sock")

    @pytest.fixture
    def registry(self):
        reg = ControlHandlerRegistry()
        reg.register(EchoHandler())
        return reg

    @pytest.fixture
    def context(self):
        return ControlContext(session_id="shared-session", pid=os.getpid())

    def test_get_or_start_creates_server(self, socket_path, registry, context):
        server = get_or_start_control_server(
            session_id="s1",
            pid=os.getpid(),
            registry=registry,
            context=context,
            socket_path=socket_path,
        )
        try:
            assert isinstance(server, ControlServer)
            assert server.is_running()
            assert is_socket_live(socket_path)
        finally:
            release_control_server("s1", os.getpid(), server)

    def test_get_or_start_reuses_existing_server(self, socket_path, registry, context):
        server1 = get_or_start_control_server(
            session_id="s2",
            pid=os.getpid(),
            registry=registry,
            context=context,
            socket_path=socket_path,
        )
        server2 = get_or_start_control_server(
            session_id="s2",
            pid=os.getpid(),
            registry=registry,
            context=context,
            socket_path=socket_path,
        )
        try:
            assert server1 is server2
            assert is_socket_live(socket_path)
        finally:
            release_control_server("s2", os.getpid(), server1)
            release_control_server("s2", os.getpid(), server2)

    def test_reference_counting_keeps_server_alive(self, socket_path, registry, context):
        server1 = get_or_start_control_server(
            session_id="s3",
            pid=os.getpid(),
            registry=registry,
            context=context,
            socket_path=socket_path,
        )
        server2 = get_or_start_control_server(
            session_id="s3",
            pid=os.getpid(),
            registry=registry,
            context=context,
            socket_path=socket_path,
        )
        try:
            release_control_server("s3", os.getpid(), server1)
            assert server1.is_running()
            assert is_socket_live(socket_path)
        finally:
            release_control_server("s3", os.getpid(), server2)

    def test_last_release_stops_server(self, socket_path, registry, context):
        server = get_or_start_control_server(
            session_id="s4",
            pid=os.getpid(),
            registry=registry,
            context=context,
            socket_path=socket_path,
        )
        release_control_server("s4", os.getpid(), server)
        time.sleep(0.1)
        assert not server.is_running()
        assert not os.path.exists(socket_path)

    def test_different_sessions_are_isolated(self, socket_path, registry, context):
        base_dir = os.path.dirname(socket_path)
        path_a = os.path.join(base_dir, "session_a.sock")
        path_b = os.path.join(base_dir, "session_b.sock")

        server_a = get_or_start_control_server(
            session_id="session-a",
            pid=os.getpid(),
            registry=registry,
            context=context,
            socket_path=path_a,
        )
        server_b = get_or_start_control_server(
            session_id="session-b",
            pid=os.getpid(),
            registry=registry,
            context=context,
            socket_path=path_b,
        )
        try:
            assert server_a is not server_b
            assert is_socket_live(path_a)
            assert is_socket_live(path_b)
        finally:
            release_control_server("session-a", os.getpid(), server_a)
            release_control_server("session-b", os.getpid(), server_b)

    def test_concurrent_get_or_start_returns_single_server(self, socket_path, registry, context):
        servers = []
        errors = []

        def worker():
            try:
                srv = get_or_start_control_server(
                    session_id="s5",
                    pid=os.getpid(),
                    registry=registry,
                    context=context,
                    socket_path=socket_path,
                )
                servers.append(srv)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        try:
            assert not errors
            assert len({id(s) for s in servers}) == 1
            assert servers[0].is_running()
        finally:
            for _ in range(len(servers)):
                release_control_server("s5", os.getpid(), servers[0])

    def test_reuse_after_server_stopped(self, socket_path, registry, context):
        server1 = get_or_start_control_server(
            session_id="s6",
            pid=os.getpid(),
            registry=registry,
            context=context,
            socket_path=socket_path,
        )
        release_control_server("s6", os.getpid(), server1)
        time.sleep(0.1)

        server2 = get_or_start_control_server(
            session_id="s6",
            pid=os.getpid(),
            registry=registry,
            context=context,
            socket_path=socket_path,
        )
        try:
            assert server1 is not server2
            assert server2.is_running()
        finally:
            release_control_server("s6", os.getpid(), server2)
