"""Deterministic transport timing and lifecycle tests for the mock LLM server."""

import http.client
import json
import os
import subprocess
import sys
from pathlib import Path
import threading
import time
from contextlib import contextmanager
from urllib.request import Request, urlopen

import pytest

from topsailai.utils.env_tool import resolve_python_interpreter
from topsailai.tests.mock.llm_mock_server import MockServerConfig, create_server

def _message(role, content):
    """Build one chat message."""
    return {"role": role, "content": content}

def _stop_server(server, serving_thread):
    """Attempt every cleanup stage and prioritize host interruptions."""
    failures = []
    cleanups = (
        server.shutdown,
        lambda: server.stop_handlers(timeout=5),
        server.server_close,
        lambda: serving_thread.join(timeout=5),
        lambda: _assert_thread_stopped(serving_thread),
    )
    for cleanup in cleanups:
        try:
            cleanup()
        except BaseException as error:
            failures.append(error)
    interruptions = [error for error in failures if isinstance(error, (KeyboardInterrupt, SystemExit))]
    primary = interruptions[0] if interruptions else (failures[0] if failures else None)
    if primary is not None:
        for extra in failures:
            if extra is not primary:
                _attach_cleanup_diagnostic(primary, extra)
        raise primary

def _assert_thread_stopped(thread):
    """Raise explicitly if a serving thread remains alive after join."""
    if thread.is_alive():
        raise RuntimeError("mock server serving thread did not exit")

def _attach_cleanup_diagnostic(primary, extra):
    """Preserve cleanup diagnostics as notes without creating context cycles."""
    note = f"additional cleanup failure: {type(extra).__name__}: {extra}"
    if hasattr(primary, "add_note"):
        primary.add_note(note)


@contextmanager
def running_server(**kwargs):
    """Start an owned loopback server and preserve failures through teardown."""
    server = create_server(MockServerConfig(port=0, **kwargs))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    except BaseException as scenario_error:
        try:
            _stop_server(server, thread)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as cleanup_error:
            _attach_cleanup_diagnostic(scenario_error, cleanup_error)
        raise
    else:
        _stop_server(server, thread)

def _request(base_url, messages, *, stream=True, timeout=5):
    """Send a completion request and consume its response."""
    connection = http.client.HTTPConnection("127.0.0.1", int(base_url.rsplit(":", 1)[1]), timeout=timeout)
    body = json.dumps({"model": "test-model", "messages": messages, "stream": stream})
    try:
        connection.request("POST", "/v1/chat/completions", body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        header_time = time.monotonic()
        first_line = response.readline() if stream else response.read()
        first_time = time.monotonic()
        while stream and response.readline():
            pass
        return response.status, header_time, first_time, first_line
    finally:
        connection.close()

def _get_state(base_url):
    """Read server lifecycle state."""
    with urlopen(base_url + "/debug/state", timeout=3) as response:
        return json.loads(response.read())


@pytest.mark.parametrize("kwargs", [
    {"lifecycle_capacity": True}, {"lifecycle_capacity": 1.5}, {"lifecycle_capacity": 0},
    {"response_header_delays": (-1,)}, {"first_chunk_delays": (float("nan"),)},
    {"first_chunk_delays": (float("inf"),)}, {"response_header_delays": ("1",)},
    {"response_header_delays": (10**10000,)},
])
def test_config_rejects_invalid_lifecycle_and_delay_values(kwargs):
    """Invalid capacity and delay values fail before the server binds."""
    with pytest.raises(ValueError):
        MockServerConfig(**kwargs)

def test_config_preserves_all_legacy_positional_arguments():
    """All legacy positional fields retain the same binding as keyword fields."""
    values = ("127.0.0.1", 0, "model", "reply", 4, 9, 8, ("legacy",),
              (("response",),), (None,), ((429, "busy"),), False, False,
              (({"id": "call", "type": "function", "function": {"name": "f", "arguments": "{}"}},),), "tool content")
    names = ("host", "port", "model", "reply", "chars_per_token", "cache_capacity",
             "request_body_capacity", "stream_chunks", "stream_response_chunks", "stream_error_messages",
             "stream_http_error_responses", "report_cache_usage", "report_usage", "tool_call_responses",
             "tool_call_response_content")
    positional = MockServerConfig(*values)
    keyword = MockServerConfig(**dict(zip(names, values)))
    assert positional == keyword
    assert positional.response_header_delays is None

def test_unequal_delay_arrays_are_safe():
    """Missing per-request delay entries are treated as zero."""
    server = create_server(MockServerConfig(response_header_delays=(0.0, 0.0), first_chunk_delays=(0.0,)))
    try:
        assert server._delay_seconds(server.config.response_header_delays, 1) == 0.0
        assert server._delay_seconds(server.config.first_chunk_delays, 1) == 0.0
    finally:
        server.server_close()


@pytest.mark.parametrize(("phase", "config"), [
    ("headers", {"response_header_delays": (30.0,)}),
    ("first_item", {"first_chunk_delays": (30.0,)}),
])
def test_scenario_can_release_and_join_delayed_request(phase, config):
    """The request owner releases its sticky event and joins the exact worker."""
    with running_server(stream_chunks=("hello",), **config) as (server, base_url):
        errors = []
        client_done = threading.Event()
        def client():
            """Run one client without hiding exceptions from the test owner."""
            try:
                _request(base_url, [_message("user", "held")])
            except BaseException as error:
                errors.append(error)
            finally:
                client_done.set()
        worker = threading.Thread(target=client)
        worker.start()
        handle = None
        try:
            assert server.lifecycle_capture.wait_for_request(1, 3)
            handle = server.lifecycle_capture.request_handle(1)
            assert handle.wait_for_phase(phase, 3)
        finally:
            try:
                if handle is not None:
                    handle.release_delay()
            finally:
                worker.join(5)
                if handle is not None:
                    handle.wait_for_thread_exit(5)
        assert not worker.is_alive()
        assert client_done.is_set()
        assert errors == []
        record = _get_state(base_url)["lifecycle_records"][0]
        assert record["handler_exit"] and record["connection_closed"] and record["thread_exited"]

def test_concurrent_request_admission_needs_no_sleep_race():
    """A second request completes while first is held in its header phase."""
    with running_server(stream_chunks=("ok",), response_header_delays=(30.0,)) as (server, base_url):
        errors = []
        first = threading.Thread(target=lambda: _capture(errors, _request, base_url, [_message("user", "first")]))
        first.start()
        handle = None
        try:
            assert server.lifecycle_capture.wait_for_request(1, 3)
            handle = server.lifecycle_capture.request_handle(1)
            assert handle.wait_for_phase("headers", 3)
            status, *_ = _request(base_url, [_message("user", "second")])
            assert status == 200
            assert not handle.record["response_finished"]
        finally:
            try:
                if handle is not None:
                    handle.release_delay()
            finally:
                first.join(5)
                if handle is not None:
                    handle.wait_for_thread_exit(5)
        assert errors == []

def _capture(errors, function, *args):
    """Capture a worker exception for assertion by the owner thread."""
    try:
        function(*args)
    except BaseException as error:
        errors.append(error)

def _assert_expected_disconnect_errors(errors):
    """Allow only transport failures from intentionally broken peers."""
    assert all(isinstance(error, (ConnectionError, OSError)) for error in errors)

def test_empty_stream_marks_first_successful_terminal_sse():
    """The final chunk is first item for empty content and is marked after write."""
    with running_server(stream_chunks=()) as (server, base_url):
        _request(base_url, [_message("user", "empty")])
        assert server.lifecycle_capture.wait_for_thread_exit(1, 3)
        record = _get_state(base_url)["lifecycle_records"][0]
    assert record["first_item_sent"] is True

def test_failed_empty_stream_terminal_write_does_not_mark_first_item():
    """A failed final SSE write leaves first_item_sent false and finalizes handler."""
    from unittest.mock import patch
    with running_server(stream_chunks=()) as (server, base_url):
        original = server.RequestHandlerClass._write_sse
        def fail_terminal(handler, payload):
            """Fail only the terminal chunk after successful headers."""
            if isinstance(payload, dict) and payload.get("choices", [{}])[0].get("finish_reason") == "stop":
                raise BrokenPipeError("injected terminal write failure")
            return original(handler, payload)
        with patch.object(server.RequestHandlerClass, "_write_sse", fail_terminal):
            errors = []
            client = threading.Thread(target=lambda: _capture(errors, _request, base_url, [_message("user", "empty")]))
            client.start()
            try:
                assert server.lifecycle_capture.wait_for_request(1, 3)
                assert server.lifecycle_capture.wait_for_thread_exit(1, 3)
            finally:
                client.join(3)
        record = _get_state(base_url)["lifecycle_records"][0]
    _assert_expected_disconnect_errors(errors)
    assert not client.is_alive()
    assert record["first_item_sent"] is False
    assert record["disconnected"] is True
    assert record["handler_exit"] is True

def test_header_write_failure_finalizes_real_handler():
    """A header write exception on a real request still closes and joins worker."""
    from unittest.mock import patch
    with running_server(stream_chunks=("ok",)) as (server, base_url):
        with patch.object(server.RequestHandlerClass, "end_headers", side_effect=BrokenPipeError("header")):
            errors = []
            client = threading.Thread(target=lambda: _capture(errors, _request, base_url, [_message("user", "x")]))
            client.start()
            try:
                assert server.lifecycle_capture.wait_for_request(1, 3)
                assert server.lifecycle_capture.wait_for_thread_exit(1, 3)
            finally:
                client.join(3)
        record = _get_state(base_url)["lifecycle_records"][0]
    _assert_expected_disconnect_errors(errors)
    assert record["disconnected"] is True and record["handler_exit"] is True
    assert record["connection_closed"] and record["thread_exited"]

def test_disconnect_during_delayed_header_is_finalized_and_joined():
    """Closing a peer during a held header does not leak its handler thread."""
    with running_server(stream_chunks=("ok",), response_header_delays=(30.0,)) as (server, base_url):
        connection = http.client.HTTPConnection("127.0.0.1", int(base_url.rsplit(":", 1)[1]), timeout=3)
        connection.request("POST", "/v1/chat/completions", body=json.dumps({"messages": [_message("user", "x")], "stream": True}), headers={"Content-Type": "application/json"})
        assert server.lifecycle_capture.wait_for_request(1, 3)
        handle = server.lifecycle_capture.request_handle(1)
        try:
            assert handle.wait_for_phase("headers", 3)
        finally:
            try:
                connection.close()
            finally:
                try:
                    server.release_delay(1)
                finally:
                    assert handle.wait_for_thread_exit(5)
        record = _get_state(base_url)["lifecycle_records"][0]
    assert record["handler_exit"] and record["connection_closed"] and record["thread_exited"]

def test_lifecycle_records_are_bounded_and_snapshot_safe():
    """Lifecycle records retain a bounded JSON-safe history."""
    with running_server(stream_chunks=("ok",), lifecycle_capacity=2) as (server, base_url):
        for i in range(3):
            _request(base_url, [_message("user", str(i))])
            assert server.lifecycle_capture.wait_for_thread_exit(i + 1, 3)
        state = _get_state(base_url)
        assert state["dropped_lifecycle_count"] == 1
        assert [r["request_number"] for r in state["lifecycle_records"]] == [2, 3]

def test_error_sse_write_failure_finalizes_real_handler():
    """A failed scripted error SSE finalizes response and socket ownership."""
    from unittest.mock import patch
    with running_server(stream_chunks=("ok",), stream_error_messages=("scripted",)) as (server, base_url):
        with patch.object(server.RequestHandlerClass, "_write_sse", side_effect=BrokenPipeError("error event")):
            errors = []
            client = threading.Thread(target=lambda: _capture(errors, _request, base_url, [_message("user", "error")]))
            client.start()
            try:
                assert server.lifecycle_capture.wait_for_request(1, 3)
                assert server.lifecycle_capture.wait_for_thread_exit(1, 3)
            finally:
                client.join(3)
        record = _get_state(base_url)["lifecycle_records"][0]
    _assert_expected_disconnect_errors(errors)
    assert not client.is_alive()
    assert record["disconnected"] and record["handler_exit"] and record["response_finished"]
    assert record["connection_closed"] and record["thread_exited"]

@pytest.mark.parametrize("mode", ["script", "module"])
def test_cli_help_supports_both_entry_points(mode, tmp_path):
    """CLI help works in script and package execution modes."""
    script = Path(__file__).parents[1] / "mock" / "llm_mock_server.py"
    env = dict(os.environ)
    if mode == "script":
        command = [resolve_python_interpreter(), str(script), "--help"]
        env.pop("PYTHONPATH", None)
    else:
        command = [resolve_python_interpreter(), "-m", "topsailai.tests.mock.llm_mock_server", "--help"]
        env["PYTHONPATH"] = str(Path(__file__).parents[2])
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "--host" in result.stdout and "--port" in result.stdout and "--cache-capacity" in result.stdout


def test_owned_handle_phase_survives_eviction():
    """Owned handle remains observable independently of bounded history."""
    from topsailai.tests.mock.llm_mock_lifecycle import LifecycleCapture
    capture = LifecycleCapture(1)
    first = capture.start(1)
    capture.mark(first, "waiting_phase", "headers")
    capture.start(2)
    assert first.wait_for_phase("headers", 0)
    assert capture.wait_for_request(1, 0) and capture.wait_for_request(2, 0)
    assert not capture.wait_for_request(3, 0)
    first.release_delay()
    capture.clear()
    assert not capture.wait_for_request(1, 0)
    assert first.record["waiting_phase"] == "headers"


def test_debug_reset_rejected_for_active_completion_and_ordinal_is_not_reused():
    """Reset returns 409 and retains cache/body/identity while worker lives."""
    from urllib.error import HTTPError
    with running_server(stream_chunks=("ok",), response_header_delays=(30.0, 30.0)) as (server, base_url):
        errors = []
        client = threading.Thread(target=lambda: _capture(errors, _request, base_url, [_message("user", "held")]))
        client.start()
        handle = None
        try:
            assert server.lifecycle_capture.wait_for_request(1, 3)
            handle = server.lifecycle_capture.request_handle(1)
            assert handle.wait_for_phase("headers", 3)
            before = _get_state(base_url)
            request = Request(base_url + "/debug/state", method="DELETE")
            with pytest.raises(HTTPError) as rejected:
                urlopen(request, timeout=3)
            assert rejected.value.code == 409
            after = _get_state(base_url)
            assert after["total_requests"] == before["total_requests"] == 1
            assert after["request_bodies"] == before["request_bodies"]
            assert not handle.release.is_set()
            second_errors = []
            second = threading.Thread(target=lambda: _capture(second_errors, _request, base_url, [_message("user", "second")]))
            second.start()
            try:
                assert server.lifecycle_capture.wait_for_request(2, 3)
                second_handle = server.lifecycle_capture.request_handle(2)
                assert second_handle.wait_for_phase("headers", 3)
            finally:
                try:
                    server.release_delay(2)
                finally:
                    second.join(5)
            assert not second.is_alive() and not second_errors
            assert second_handle.wait_for_thread_exit(5)
            assert server.prompt_cache.state()["total_requests"] == 2
        finally:
            try:
                server.release_delay(1)
            finally:
                client.join(5)
                if handle is not None:
                    assert handle.wait_for_thread_exit(5)
        assert not client.is_alive()
        with urlopen(Request(base_url + "/debug/state", method="DELETE"), timeout=3) as response:
            assert response.status == 200
        assert server.prompt_cache.state()["total_requests"] == 0


def test_wait_for_request_acceptance_survives_eviction_and_clear():
    """Acceptance wait uses ordinal, not bounded history membership."""
    from topsailai.tests.mock.llm_mock_lifecycle import LifecycleCapture
    capture = LifecycleCapture(1)
    capture.start(1)
    capture.start(2)
    assert capture.wait_for_request(1, 0) and capture.wait_for_request(2, 0)
    assert not capture.wait_for_request(3, 0)
    capture.clear()
    assert not capture.wait_for_request(1, 0)


@pytest.mark.parametrize("phase", ["headers", "first_item"])
def test_stop_while_delay_is_held_releases_and_joins(phase):
    """Server shutdown releases a held request and joins client/handler threads."""
    setting = {"response_header_delays": (30.0,)} if phase == "headers" else {"first_chunk_delays": (30.0,)}
    with running_server(stream_chunks=("ok",), **setting) as (server, base_url):
        errors = []
        client = threading.Thread(target=lambda: _capture(errors, _request, base_url, [_message("user", phase)]))
        client.start()
        handle = None
        try:
            assert server.lifecycle_capture.wait_for_request(1, 3)
            handle = server.lifecycle_capture.request_handle(1)
            assert handle.wait_for_phase(phase, 3)
            server.shutdown()
            server.stop_handlers(5)
        finally:
            client.join(5)
        assert handle is not None
        assert not client.is_alive() and not handle.thread.is_alive()
        assert handle.release.is_set() and handle.response_finished.is_set()
        assert handle.connection_closed.is_set()
        _assert_expected_disconnect_errors(errors)

@pytest.mark.parametrize("phase", ["headers", "first_item"])
def test_stop_while_delay_rejects_unexpected_client_error(monkeypatch, phase):
    """Unexpected client failures must fail the stop cleanup scenario."""
    setting = {"response_header_delays": (30.0,)} if phase == "headers" else {"first_chunk_delays": (30.0,)}
    original_request = _request
    def failing_request(*args, **kwargs):
        """Raise an unexpected client failure after the real request completes."""
        original_request(*args, **kwargs)
        raise RuntimeError("unexpected client programming failure")
    monkeypatch.setattr(sys.modules[__name__], "_request", failing_request)
    with running_server(stream_chunks=("ok",), **setting) as (server, base_url):
        errors = []
        client = threading.Thread(target=lambda: _capture(errors, _request, base_url, [_message("user", phase)]))
        client.start()
        handle = None
        try:
            assert server.lifecycle_capture.wait_for_request(1, 3)
            handle = server.lifecycle_capture.request_handle(1)
            assert handle.wait_for_phase(phase, 3)
        finally:
            try:
                if handle is not None:
                    handle.release_delay()
            finally:
                client.join(5)
                if handle is not None:
                    handle.wait_for_thread_exit(5)
        assert not client.is_alive()
        with pytest.raises(AssertionError):
            _assert_expected_disconnect_errors(errors)






@pytest.mark.parametrize("stage", ["request", "getresponse", "read"])
def test_request_closes_connection_on_each_failure(monkeypatch, stage):
    """Client closure is unconditional across request, response, and read failures."""
    from unittest.mock import patch
    failure = ValueError(stage)
    class Response:
        status = 200
        def readline(self):
            raise failure
    clients = []
    class Client:
        def __init__(self, *args, **kwargs):
            self.closed = 0
            clients.append(self)
        def request(self, *args, **kwargs):
            if stage == "request": raise failure
        def getresponse(self):
            if stage == "getresponse": raise failure
            return Response()
        def close(self): self.closed += 1
    with patch("http.client.HTTPConnection", Client):
        with pytest.raises(ValueError) as raised:
            _request("http://127.0.0.1:1", [_message("user", "x")])
    assert raised.value is failure
    assert clients[0].closed == 1


def test_one_release_bypasses_both_delays():
    """One sticky release allows a request past both configured phases."""
    with running_server(stream_chunks=("ok",), response_header_delays=(30,), first_chunk_delays=(30,)) as (server, base):
        errors = []
        client = threading.Thread(target=lambda: _capture(errors, _request, base, [_message("user", "both")]))
        client.start()
        handle = None
        try:
            assert server.lifecycle_capture.wait_for_request(1, 3)
            handle = server.lifecycle_capture.request_handle(1)
            assert handle.wait_for_phase("headers", 3)
            handle.release_delay()
            client.join(5)
            assert not client.is_alive() and not errors
            assert handle.wait_for_thread_exit(5)
        finally:
            try:
                if handle:
                    handle.release_delay()
            finally:
                client.join(5)


def test_non_stream_and_programming_error_completion_events():
    """Non-stream response and unexpected response errors finalize completion."""
    from unittest.mock import patch
    with running_server(stream_chunks=("ok",)) as (server, base):
        status, *_ = _request(base, [_message("user", "plain")], stream=False)
        assert status == 200
        first = server.lifecycle_capture.request_handle(1)
        assert first.response_finished.wait(3)
        with patch.object(server.RequestHandlerClass, "_respond_completion", side_effect=RuntimeError("injected")):
            errors = []
            client = threading.Thread(target=lambda: _capture(errors, _request, base, [_message("user", "bug")]))
            client.start()
            second = None
            try:
                assert server.lifecycle_capture.wait_for_request(2, 3)
                second = server.lifecycle_capture.request_handle(2)
                assert second.response_finished.wait(3)
                assert second.record["handler_exit"]
            finally:
                client.join(5)
            assert not client.is_alive()
            assert len(errors) <= 1
            if errors:
                assert isinstance(errors[0], (ConnectionError, OSError))


def test_controlled_admission_and_reset_interleaving():
    """Reset cannot split ordinal allocation from publishing its handle."""
    entered, release = threading.Event(), threading.Event()
    with running_server(stream_chunks=("ok",), response_header_delays=(30,)) as (server, base):
        original = server.bind_handle
        def gated(number):
            entered.set()
            assert release.wait(3)
            return original(number)
        server.bind_handle = gated
        errors = []
        client = threading.Thread(target=lambda: _capture(errors, _request, base, [_message("user", "gate")]))
        client.start()
        handle = None
        reset_result = []
        reset = threading.Thread(target=lambda: reset_result.append(server.reset_debug_state()))
        try:
            assert entered.wait(3)
            reset.start()
            time.sleep(0.05)
            assert reset.is_alive()
            assert not server._ownership_lock.acquire(blocking=False)
            release.set()
            assert server.lifecycle_capture.wait_for_request(1, 3)
            handle = server.lifecycle_capture.request_handle(1)
            assert handle.wait_for_phase("headers", 3)
        finally:
            release.set()
            try:
                if handle is not None:
                    handle.release_delay()
            finally:
                client.join(5)
                if handle is not None:
                    handle.wait_for_thread_exit(5)
                if reset.ident is not None: reset.join(5)
        assert reset_result == [False]
        assert not client.is_alive() and not errors


def test_response_finished_precedes_transport_close():
    """Response completion is observable while local transport shutdown is gated."""
    from unittest.mock import patch
    entered, release = threading.Event(), threading.Event()
    with running_server(stream_chunks=("ok",)) as (server, base):
        original = server.shutdown_request
        def gated(request):
            entered.set()
            assert release.wait(3)
            return original(request)
        with patch.object(server, "shutdown_request", gated):
            errors = []
            client = threading.Thread(target=lambda: _capture(errors, _request, base, [_message("user", "boundary")]))
            client.start()
            try:
                assert server.lifecycle_capture.wait_for_request(1, 3)
                handle = server.lifecycle_capture.request_handle(1)
                assert handle.response_finished.wait(3)
                assert entered.wait(3)
                assert not handle.connection_closed.is_set()
                assert handle.thread.is_alive()
            finally:
                release.set()
                client.join(5)
            assert handle.connection_closed.wait(3)
            assert handle.wait_for_thread_exit(5)
            assert errors == []


