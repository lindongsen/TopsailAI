"""Normalized runtime operations, exact fixture targets and delivery evidence."""

import importlib.util
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cli_topsailai import runtime_operations as operations
from cli_topsailai.runtime_target import ProcessState
from cli_topsailai.runtime_pipe import PipeDeliveryError, PipeDeliveryResult
from cli_topsailai.runtime_control import ControlDeliveryError, ControlDeliveryResult


@pytest.fixture
def target(tmp_path):
    """Create only fixture-owned session evidence and portable endpoints."""
    (tmp_path / "session.x.123.session.stdout").touch()
    return tmp_path


def execute(request, target, **kwargs):
    """Inject a harmless probe, never inspecting or messaging real sessions."""
    kwargs.setdefault("process_probe", lambda pid: ProcessState.ALIVE)
    kwargs.setdefault("session_id", "session.x")
    return operations.execute_runtime_request(request, target, **kwargs)


@pytest.mark.parametrize("runtime_request", [
    None, operations.RuntimeRequest("/send", "x"), operations.RuntimeRequest([]),
    operations.RuntimeRequest("send"), operations.RuntimeRequest("btw", " \n"),
    operations.RuntimeRequest("btw", 42), operations.RuntimeRequest("btw", "\ud800"),
    operations.RuntimeRequest("send", "a" * (operations.MESSAGE_LIMIT + 1)),
    operations.RuntimeRequest("btw", "中" * (operations.MESSAGE_LIMIT // 3 + 1)),
    operations.RuntimeRequest("send", "x\nEOF\nx"),
    operations.RuntimeRequest("send", "x", control_action="test"),
    operations.RuntimeRequest("btw", "x", payload={}),
    operations.RuntimeRequest("control", "x", "test"),
    operations.RuntimeRequest("control", control_action=42),
    operations.RuntimeRequest("control", control_action=""),
    operations.RuntimeRequest("control", control_action="unknown"),
    operations.RuntimeRequest("control", control_action="test", payload=[]),
    operations.RuntimeRequest("control", control_action="test", payload={"x": object()}),
    operations.RuntimeRequest("control", control_action="test", payload={"x": float("nan")}),
    operations.RuntimeRequest("control", control_action="test", payload={"x": "\ud800"}),
    operations.RuntimeRequest("control", control_action="call_instruction", payload={}),
    operations.RuntimeRequest("control", control_action="call_instruction", payload={"instruction": 1}),
    operations.RuntimeRequest("control", control_action="call_instruction", payload={"instruction": " "}),
])
def test_invalid_before_directory(runtime_request, tmp_path, monkeypatch):
    """Invalid content must never enumerate a target directory or deliver."""
    resolver = Mock(side_effect=AssertionError("must not enumerate"))
    monkeypatch.setattr(operations.runtime_target, "resolve_runtime_target", resolver)
    result = operations.execute_runtime_request(runtime_request, tmp_path,
                                               control_actions=lambda: ["test", "call_instruction"])
    assert not result.ok and result.exit_code == 2
    assert result.error_code == "usage_error" and not result.delivery_unknown
    resolver.assert_not_called()


@pytest.mark.parametrize("timeout", [0, -1, True, "1", None, float("inf"), float("nan")])
def test_invalid_timeout(timeout, target):
    """Every action requires a finite positive numeric budget."""
    result = execute(operations.RuntimeRequest("btw", "x", timeout=timeout), target)
    assert result.exit_code == 2



@pytest.mark.parametrize("action", ["send", "btw", "control"])
@pytest.mark.parametrize("timeout", [10**400, -(10**400)], ids=["positive-overflow", "negative-overflow"])
def test_oversized_timeout_before_any_side_effect(action, timeout, tmp_path, monkeypatch):
    """Unrepresentable budgets fail before resolution, registration or delivery."""
    resolver = Mock(side_effect=AssertionError("must not resolve"))
    actions = Mock(side_effect=AssertionError("must not register"))
    pipe_sender, control_sender, writer = Mock(), Mock(), Mock()
    monkeypatch.setattr(operations.runtime_target, "resolve_runtime_target", resolver)
    monkeypatch.setattr(operations.runtime_control, "get_control_actions", actions)
    runtime_request = operations.RuntimeRequest(
        action, "x" if action != "control" else None,
        "test" if action == "control" else None, timeout=timeout)
    result = operations.execute_runtime_request(
        runtime_request, tmp_path, pipe_sender=pipe_sender,
        control_sender=control_sender, injection_writer=writer)
    assert not result.ok and result.exit_code == 2 and result.error_code == "usage_error"
    assert not result.delivery_unknown and result.delivery_state == "not_delivered"
    for dependency in (resolver, actions, pipe_sender, control_sender, writer):
        dependency.assert_not_called()


@pytest.mark.parametrize("timeout", [1, 1.5])
def test_ordinary_timeout_supported(timeout, target):
    """Representable positive integer and float budgets still authorize dispatch."""
    writer = Mock(return_value=True)
    result = execute(operations.RuntimeRequest("btw", "x", timeout=timeout),
                     target, injection_writer=writer)
    assert result.ok and result.delivery_state == "injection_queued"
    assert writer.call_count == 1


def test_messages_and_lazy_control(target, monkeypatch, capsys):
    """Btw preserves text and never registers control or emits output."""
    actions = Mock(side_effect=AssertionError("control must stay lazy"))
    writer = Mock(return_value=True)
    monkeypatch.setattr(operations.runtime_control, "get_control_actions", actions)
    message = " \n中 '$HOME' EOF\n "
    result = execute(operations.RuntimeRequest("btw", message), target, injection_writer=writer)
    writer.assert_called_once_with(str(target / "session.x.123.session.agent2llm_inject_messages.jsonl"), message)
    assert result.ok and result.delivery_state == "injection_queued"
    assert result.session_id == "session.x" and result.pid == 123
    assert not (target / "session.x.123.session.agent2llm_inject_messages.jsonl").exists()
    actions.assert_not_called()
    assert capsys.readouterr() == ("", "")


def test_boundary_message(target):
    """The exact UTF-8 budget is accepted without normalizing content."""
    message = "a" * operations.MESSAGE_LIMIT
    writer = Mock(return_value=True)
    assert execute(operations.RuntimeRequest("btw", message), target, injection_writer=writer).ok
    assert writer.call_args.args[1] == message


def test_send_exact_once(target, monkeypatch):
    """FIFO operation preserves message and calls one exact sender."""
    import os
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO unsupported")
    path = target / "session.x.123.session.pipe"
    os.mkfifo(path)
    sender = Mock(return_value=PipeDeliveryResult(12))
    monkeypatch.setattr(operations.runtime_control, "get_control_actions",
                        Mock(side_effect=AssertionError("no control")))
    result = execute(operations.RuntimeRequest("send", " 你好\n", timeout=2), target, pipe_sender=sender)
    sender.assert_called_once_with(path, " 你好\n", timeout=2)
    assert result.ok and result.bytes_written == 12 and result.delivery_state == "pipe_written"


@pytest.fixture
def control_endpoint(target):
    """Bind a fixture UDS without a receiving session or background process."""
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("UDS unsupported")
    path = target / "fixture.sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    try:
        yield path
    finally:
        sock.close()


def control(request, target, endpoint, sender):
    """Inject a public path authority and one structured sender."""
    builder = Mock(return_value=str(endpoint))
    result = execute(request, target, control_actions=lambda: ["get_session_messages", "test", "call_instruction"],
                     socket_path_builder=builder, control_sender=sender)
    builder.assert_called_once_with(str(target), "session.x", "123")
    return result


@pytest.mark.parametrize("payload", [{}, {"session_id": ""}, {"session_id": None}, {"session_id": "other"}])
def test_control_payload_defaults(payload, target, control_endpoint):
    """Default only absent keys and detach nested mutable values."""
    payload = dict(payload, nested={"items": [1]})
    original = repr(payload)
    sender = Mock(return_value=ControlDeliveryResult("id", {"status": "ok"}))
    result = control(operations.RuntimeRequest("control", control_action="get_session_messages", payload=payload),
                     target, control_endpoint, sender)
    sent = sender.call_args.args[2]
    assert sent["session_id"] == payload.get("session_id", "session.x")
    sent["nested"]["items"].append(2)
    assert repr(payload) == original
    assert sender.call_count == 1 and result.ok
    assert result.request_id == "id" and result.response == {"status": "ok"}
    assert result.delivery_state == "control_acknowledged"


@pytest.mark.parametrize("action,payload", [("test", None), ("call_instruction", {"instruction": "go"})])
def test_control_valid(action, payload, target, control_endpoint):
    """Default payload and explicit instruction use the same structured dispatch."""
    sender = Mock(return_value=ControlDeliveryResult("r", {"status": "ok"}))
    assert control(operations.RuntimeRequest("control", control_action=action, payload=payload),
                   target, control_endpoint, sender).ok


@pytest.mark.parametrize("error", [
    ControlDeliveryError("secret", "timeout", 5, "r", True),
    ControlDeliveryError("secret", "control_rejected", 6, "r", True, {"status": "error"}),
    ControlDeliveryError("secret", "invalid_response", 6, "r", True),
    ControlDeliveryError("secret", "permission_denied", 4, "r", False),
])
def test_control_failure_evidence(error, target, control_endpoint, capsys):
    """Preserve errors and uncertainty without retry or leaking diagnostics."""
    sender = Mock(side_effect=error)
    result = control(operations.RuntimeRequest("control", control_action="test"), target, control_endpoint, sender)
    assert not result.ok and result.exit_code == error.exit_code
    assert result.request_id == "r" and result.response == error.response
    assert result.delivery_unknown == error.delivery_unknown and result.cause is error
    assert result.error_code == error.error_code and "secret" not in result.message
    assert sender.call_count == 1 and capsys.readouterr() == ("", "")


def test_partial_pipe(target, monkeypatch):
    """Partial writes retain evidence across the operation boundary."""
    monkeypatch.setattr(operations.runtime_target, "validate_runtime_endpoint", lambda t, **kw: kw["endpoint_path"])
    error = PipeDeliveryError("timeout", "secret", bytes_written=17)
    sender = Mock(side_effect=error)
    result = execute(operations.RuntimeRequest("send", "x"), target, pipe_sender=sender)
    assert result.bytes_written == 17 and result.delivery_unknown
    assert result.delivery_state == "delivery_unknown" and result.cause is error
    assert result.exit_code == 5 and sender.call_count == 1


@pytest.mark.parametrize("outcome", [False, RuntimeError("secret"),
    ControlDeliveryError("secret", "invalid_response", 6)])
def test_writer_failure(outcome, target):
    """Writer false and ordinary exceptions may already have appended data."""
    writer = Mock(side_effect=outcome) if isinstance(outcome, Exception) else Mock(return_value=outcome)
    result = execute(operations.RuntimeRequest("btw", "x"), target, injection_writer=writer)
    assert result.exit_code == 5 and result.error_code == "injection_failed"
    assert result.delivery_unknown and result.delivery_state == "delivery_unknown"
    assert "secret" not in result.message and writer.call_count == 1


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), SystemExit(9)])
@pytest.mark.parametrize("action", ["send", "btw", "control"])
def test_host_interrupt(interrupt, action, target, control_endpoint, monkeypatch):
    """Host cancellation is never converted to a regular failure result."""
    monkeypatch.setattr(operations.runtime_target, "validate_runtime_endpoint", lambda t, **kw: kw["endpoint_path"])
    sender = Mock(side_effect=interrupt)
    kwargs = {"pipe_sender": sender, "injection_writer": sender, "control_sender": sender,
              "socket_path_builder": lambda *args: str(control_endpoint), "control_actions": lambda: ["test"]}
    request = operations.RuntimeRequest(action, "x" if action != "control" else None,
                                        "test" if action == "control" else None)
    with pytest.raises(type(interrupt)) as caught:
        execute(request, target, **kwargs)
    assert caught.value is interrupt and sender.call_count == 1


@pytest.mark.parametrize("scenario,code", [("ambiguous", "ambiguous_target"), ("mismatch", "target_mismatch"),
                                          ("exited", "stale_target"), ("endpoint", "endpoint_invalid")])
def test_no_fallback(scenario, code, target):
    """Target changes and invalid endpoints never authorize a different target."""
    writer = Mock(return_value=True)
    probe = Mock(return_value=ProcessState.ALIVE)
    kwargs = {}
    if scenario == "ambiguous":
        (target / "session.x.124.session.stdout").touch()
    elif scenario == "mismatch":
        kwargs["session_id"] = "other"
        kwargs["pid"] = 123
    elif scenario == "exited":
        probe.side_effect = [ProcessState.ALIVE, ProcessState.DEAD]
    else:
        (target / "session.x.123.session.agent2llm_inject_messages.jsonl").symlink_to(target / "missing")
    result = execute(operations.RuntimeRequest("btw", "x"), target, injection_writer=writer,
                     process_probe=probe, **kwargs)
    assert result.error_code == code and result.exit_code in (3, 4)
    writer.assert_not_called()


def test_endpoint_change_after_resolution(target):
    """A replacement observed during revalidation is rejected without writing."""
    writer = Mock()
    path = target / "session.x.123.session.agent2llm_inject_messages.jsonl"
    def probe(pid):
        """Install an invalid destination on the revalidation observation."""
        if probe.calls:
            path.mkdir()
        probe.calls += 1
        return ProcessState.ALIVE
    probe.calls = 0
    result = execute(operations.RuntimeRequest("btw", "x"), target, process_probe=probe, injection_writer=writer)
    assert result.error_code == "endpoint_invalid" and probe.calls == 2
    writer.assert_not_called()


def test_lazy_import_and_writer(monkeypatch):
    """Module load does not import injection; adapter invokes only its public writer."""
    name = "topsailai.workspace.agent.runtime_message_sources.file"
    before = sys.modules.get(name)
    spec = importlib.util.spec_from_file_location("isolated_operations", operations.__file__)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert sys.modules.get(name) is before
    writer = Mock(return_value=True)
    monkeypatch.setitem(sys.modules, name, SimpleNamespace(write_message=writer))
    assert module.write_injection("/fixture/path", "x")
    writer.assert_called_once_with("/fixture/path", "x")
