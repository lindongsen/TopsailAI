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
