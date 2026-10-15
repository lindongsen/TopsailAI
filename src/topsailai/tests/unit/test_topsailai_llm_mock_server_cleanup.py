"""Cleanup and exception-priority tests for the mock LLM server."""

import inspect
import threading

import pytest

from topsailai.tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.tests.unit.test_topsailai_llm_mock_server_timing import (
    _stop_server,
    _assert_expected_disconnect_errors,
    _capture,
    _message,
    _request,
    running_server,
)

def test_server_cleanup_attempts_join_after_close_failure():
    """Serving thread join is attempted even if server_close fails."""
    calls = []
    sentinel = ValueError("close sentinel")
    class FakeServer:
        def shutdown(self): calls.append("shutdown")
        def stop_handlers(self, timeout): calls.append("stop")
        def server_close(self): calls.append("close"); raise sentinel
    class FakeThread:
        def join(self, timeout): calls.append("join")
        def is_alive(self): calls.append("is_alive"); return False
    with pytest.raises(ValueError) as raised:
        _stop_server(FakeServer(), FakeThread())
    assert raised.value is sentinel
    assert calls == ["shutdown", "stop", "close", "join", "is_alive"]


def test_scenario_failure_is_preserved_when_cleanup_fails(monkeypatch):
    """The real context manager preserves scenario identity and adds a note."""
    scenario = AssertionError("scenario")
    cleanup = ValueError("cleanup")
    real_stop = inspect.unwrap(running_server).__globals__["_stop_server"]
    captured = {}
    def failing_stop(server, thread):
        captured["server"] = server
        captured["thread"] = thread
        real_stop(server, thread)
        raise cleanup
    monkeypatch.setitem(inspect.unwrap(running_server).__globals__, "_stop_server", failing_stop)
    with pytest.raises(AssertionError) as raised:
        with running_server() as (server, _):
            captured["server"] = server
            raise scenario
    assert raised.value is scenario
    assert any("ValueError: cleanup" in note for note in getattr(scenario, "__notes__", ()))
    assert scenario.__context__ is not cleanup
    assert not captured["thread"].is_alive()
    assert captured["server"].socket.fileno() == -1


def test_host_interruption_takes_precedence_and_remaining_cleanup_runs():
    """Host interruption wins while each cleanup stage is attempted."""
    calls = []
    ordinary = ValueError("shutdown")
    interruption = KeyboardInterrupt("join")
    class FakeServer:
        def shutdown(self): calls.append("shutdown"); raise ordinary
        def stop_handlers(self, timeout): calls.append("stop"); raise RuntimeError("handler stop")
        def server_close(self): calls.append("close")
    class FakeThread:
        def join(self, timeout): calls.append("join"); raise interruption
        def is_alive(self): calls.append("is_alive"); return False
    with pytest.raises(KeyboardInterrupt) as raised:
        _stop_server(FakeServer(), FakeThread())
    assert raised.value is interruption
    assert calls == ["shutdown", "stop", "close", "join", "is_alive"]
    assert any("ValueError: shutdown" in note for note in getattr(interruption, "__notes__", ()))


def test_cleanup_preserves_scenario_failure_and_joins_resources():
    """Deliberate scenario failure remains primary after delay release and joins."""
    sentinel = AssertionError("deliberate scenario failure")
    errors = []
    with pytest.raises(AssertionError) as raised:
        with running_server(stream_chunks=("ok",), response_header_delays=(30.0,)) as (server, base_url):
            client = threading.Thread(target=lambda: _capture(errors, _request, base_url, [_message("user", "failure")]))
            client.start()
            handle = None
            try:
                assert server.lifecycle_capture.wait_for_request(1, 3)
                handle = server.lifecycle_capture.request_handle(1)
                assert handle.wait_for_phase("headers", 3)
                raise sentinel
            finally:
                try:
                    if handle is not None:
                        handle.release_delay()
                finally:
                    client.join(5)
                    if handle is not None:
                        assert handle.wait_for_thread_exit(5)
                assert not client.is_alive()
    assert raised.value is sentinel
    assert errors == []


def test_server_cleanup_reports_unjoined_daemon_worker():
    """A daemon worker that misses join is reported instead of hidden."""
    server = create_server(MockServerConfig(port=0))
    entered, release = threading.Event(), threading.Event()
    worker = threading.Thread(target=lambda: (entered.set(), release.wait()), daemon=True)
    worker.start()
    assert entered.wait(2)
    class Socket:
        def shutdown(self, how): pass
    server._workers[worker] = {"socket": Socket(), "handle": None}
    try:
        with pytest.raises(RuntimeError, match="did not exit"):
            server.stop_handlers(timeout=0)
    finally:
        release.set()
        worker.join(2)
        server._workers.clear()
        server.server_close()
    assert not worker.is_alive()


def test_running_server_cleanup_host_interruption_matrix(monkeypatch):
    """Real cleanup stages prefer interruption and still settle the server."""
    scenario, ordinary = AssertionError("scenario"), ValueError("ordinary cleanup")
    interruption = KeyboardInterrupt("host cleanup")
    captured = {}
    before_threads = set(threading.enumerate())
    with pytest.raises(KeyboardInterrupt) as raised:
        with running_server() as (server, _):
            captured["server"] = server
            original_shutdown = server.shutdown
            original_stop_handlers = server.stop_handlers
            def failing_shutdown():
                original_shutdown()
                raise ordinary
            def failing_stop_handlers(timeout):
                original_stop_handlers(timeout)
                raise interruption
            monkeypatch.setattr(server, "shutdown", failing_shutdown)
            monkeypatch.setattr(server, "stop_handlers", failing_stop_handlers)
            raise scenario
    assert raised.value is interruption
    assert any("ValueError: ordinary cleanup" in n for n in getattr(interruption, "__notes__", ()))
    assert scenario.__context__ is not ordinary
    assert captured["server"].socket.fileno() == -1
    after_threads = set(threading.enumerate())
    assert not any(thread.is_alive() for thread in after_threads - before_threads)

