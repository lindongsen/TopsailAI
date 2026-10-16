"""Regression tests for exact active-response socket interruption."""

import socket
import threading
from types import SimpleNamespace

import httpx
import pytest

from topsailai.ai_base.llm_pool.openai_client_pool import OpenAIResponseAdapter


class SocketStream:
    """Expose one exact response socket and record once-only closure."""

    def __init__(self, sock, version=b"HTTP/1.1"):
        """Retain a real socket through the HTTPX network extension."""
        self.sock = sock
        self.entered = threading.Event()
        self.closed = 0
        network = SimpleNamespace(get_extra_info=lambda key: sock if key == "socket" else None)
        self.response = httpx.Response(200, request=httpx.Request("GET", "http://loopback.invalid"), extensions={"network_stream": network, "http_version": version})

    def __iter__(self):
        """Return the single transport iterator."""
        return self

    def __next__(self):
        """Block in a real read until the exact peer or response is interrupted."""
        trace = self.response.request.extensions["trace"]
        trace("http11.receive_response_body.started", {})
        try:
            self.entered.set()
            value = self.sock.recv(1)
            if not value:
                raise StopIteration
            return value
        finally:
            trace("http11.receive_response_body.complete", {})

    def close(self):
        """Record the physical response closure."""
        self.closed += 1
        self.sock.close()


@pytest.mark.parametrize("version", [b"HTTP/1.0", b"HTTP/1.1"])
def test_active_http1_read_settles_without_peer_release(version):
    """Shutdown wakes a blocked read while an independent control stays usable."""
    left, right = socket.socketpair()
    control, peer = socket.socketpair()
    raw = SocketStream(left, version)
    stream = OpenAIResponseAdapter.iter_response(raw)
    result = []

    def read():
        """Retain the exact read result without hiding worker errors."""
        try:
            result.append(next(stream, None))
        except OSError as error:
            result.append(error)

    worker = threading.Thread(target=read)
    try:
        worker.start()
        assert raw.entered.wait(2)
        stream.close()
        worker.join(2)
        assert not worker.is_alive()
        assert len(result) == 1
        stream.close()
        assert raw.closed == 1
        peer.sendall(b"C")
        assert control.recv(1) == b"C"
        assert next(stream, None) is None
    finally:
        right.close()
        worker.join(2)
        for sock in (left, control, peer):
            sock.close()
        assert not worker.is_alive()


@pytest.mark.parametrize("version,reading", [(b"HTTP/1.1", False), (b"HTTP/2", True)])
def test_idle_and_multiplexed_transport_not_interrupted(version, reading):
    """Excluded streams retain their transport state until ordinary SDK close."""
    left, right = socket.socketpair()
    raw = SocketStream(left, version)
    stream = OpenAIResponseAdapter.iter_response(raw)
    stream._reading = reading
    try:
        stream._interrupt_read()
        right.sendall(b"X")
        assert left.recv(1) == b"X"
        stream.close()
        assert raw.closed == 1
    finally:
        left.close()
        right.close()


def test_shutdown_oserror_still_closes_sdk_response(caplog):
    """An already closed socket cannot prevent the original close obligation."""
    left, right = socket.socketpair()
    raw = SocketStream(left)
    stream = OpenAIResponseAdapter.iter_response(raw)
    stream._reading = True
    raw.response.request.extensions["trace"]("http11.receive_response_body.started", {})
    left.close()
    try:
        stream.close()
        assert raw.closed == 1
        assert "continuing SDK close" in caplog.text
    finally:
        right.close()


def test_completed_read_revokes_shutdown_before_socket_lookup():
    """Completion revocation wins even if the adapter read flag has not cleared."""
    left, right = socket.socketpair()
    raw = SocketStream(left)
    previous_events = []
    raw.response.request.extensions["trace"] = lambda event, info: previous_events.append(event)
    stream = OpenAIResponseAdapter.iter_response(raw)
    trace = raw.response.request.extensions["trace"]
    try:
        stream._reading = True
        trace("http11.receive_response_body.started", {})
        trace("http11.receive_response_body.complete", {})
        raw.response.extensions["network_stream"] = SimpleNamespace(
            get_extra_info=lambda key: pytest.fail("expired response looked up a pooled socket"))
        stream._interrupt_read()
        right.sendall(b"X")
        assert left.recv(1) == b"X"
        assert previous_events == ["http11.receive_response_body.started", "http11.receive_response_body.complete"]
    finally:
        left.close()
        right.close()


def test_lookup_shutdown_holds_authority_until_completion_can_revoke():
    """The response cannot publish pool-release authority during socket interruption."""
    left, right = socket.socketpair()
    raw = SocketStream(left)
    stream = OpenAIResponseAdapter.iter_response(raw)
    lookup, resume, completing, completed = (threading.Event() for _ in range(4))
    trace = raw.response.request.extensions["trace"]
    stream._reading = True
    trace("http11.receive_response_body.started", {})

    def info(key):
        """Pause at the exact formerly unsafe socket lookup boundary."""
        lookup.set()
        assert resume.wait(3)
        assert not completed.is_set()
        return left

    def complete():
        """Revoke before a real transport would release or reassign the socket."""
        completing.set()
        trace("http11.response_closed.started", {})
        completed.set()

    raw.response.extensions["network_stream"] = SimpleNamespace(get_extra_info=info)
    closer = threading.Thread(target=stream._interrupt_read)
    reader = threading.Thread(target=complete)
    try:
        closer.start()
        assert lookup.wait(2)
        reader.start()
        assert completing.wait(2)
        assert not completed.wait(0.05)
        resume.set()
        closer.join(3)
        reader.join(3)
        assert not closer.is_alive() and not reader.is_alive()
        assert completed.is_set() and not stream._body_owned
        assert right.recv(1) == b""
    finally:
        resume.set()
        for worker in (closer, reader):
            if worker.ident is not None:
                worker.join(3)
                assert not worker.is_alive()
        left.close()
        right.close()


def test_completed_response_cleanup_preserves_real_keepalive_reuse():
    """A sibling reuses the identical HTTP/1 connection before old cleanup resumes."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    accepted, release = threading.Event(), threading.Event()
    connections = []

    class Handler(BaseHTTPRequestHandler):
        """Serve two bounded responses on one persistent loopback connection."""
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            """Keep successful fixture traffic out of test output."""

        def do_GET(self):
            """Hold the sibling after headers while old response cleanup executes."""
            connections.append(self.connection)
            self.send_response(200)
            self.send_header("Content-Length", "1")
            self.end_headers()
            if self.path == "/sibling":
                accepted.set()
                assert release.wait(3)
            self.wfile.write(b"X")
            self.wfile.flush()

    class Raw:
        """Expose an actual HTTPX body iterator through the SDK adapter seam."""
        def __init__(self, response):
            """Retain the exact response."""
            self.response = response

        def __iter__(self):
            """Use real HTTPcore body completion and response release."""
            return self.response.iter_bytes()

        def close(self):
            """Delegate idempotent response closure."""
            self.response.close()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    client = httpx.Client(limits=httpx.Limits(max_connections=1), timeout=3, trust_env=False)
    base = f"http://127.0.0.1:{server.server_port}"
    sibling = None
    try:
        first = client.send(client.build_request("GET", base + "/first"), stream=True)
        stream = OpenAIResponseAdapter.iter_response(Raw(first))
        first_socket = first.extensions["network_stream"].get_extra_info("socket")
        assert list(stream) == [b"X"]
        assert first.is_closed and not stream._body_owned
        sibling = client.send(client.build_request("GET", base + "/sibling"), stream=True)
        assert accepted.wait(2)
        assert sibling.extensions["network_stream"].get_extra_info("socket") is first_socket
        assert len(connections) == 2 and connections[0] is connections[1]
        stream._reading = True  # Reproduce the stale adapter flag after transport completion.
        stream.close()
        release.set()
        assert sibling.read() == b"X"
        assert not stream._body_owned
    finally:
        release.set()
        if sibling is not None:
            sibling.close()
        client.close()
        server.shutdown()
        server.server_close()
        worker.join(3)
        assert not worker.is_alive()
