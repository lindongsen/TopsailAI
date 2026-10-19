"""CLI-only FBT routing through live YAML and the real local socket client.

Author: DawsonLin
"""

import json
from pathlib import Path
import socket
import sys
import threading
import tempfile

import pytest
from pytest_bdd import given, when, then, parsers, scenarios

from cli_topsailai import state, yaml_commands
from cli_topsailai.streaming import _handle_stream_command
import topsailai_send_control as client

scenarios("features/fbt_control_shortcuts.feature")


@pytest.fixture
def control_endpoint(monkeypatch, capsys):
    """Own a socket server and close/join every resource at scenario teardown."""
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("Local Unix control sockets are unavailable")
    temporary = tempfile.TemporaryDirectory(prefix="fbt-", dir=Path(__file__).resolve().parents[3] / ".tmp")
    folder = Path(temporary.name)
    path = folder / "fbt.2468.session.sock"
    (folder / "fbt.2468.session.stdout").write_text("")
    (folder / "other.9753.session.stdout").write_text("")
    unrelated = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    unrelated_path = folder / "other.9753.session.sock"
    unrelated.bind(str(unrelated_path))
    unrelated.listen()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen()
    server.settimeout(0.05)
    data = {"requests": [], "launches": [], "errors": [], "status": "ok", "folder": str(folder)}
    stop = threading.Event()

    def serve():
        """Acknowledge each correlated request and retain thread failures."""
        try:
            while not stop.is_set():
                try:
                    connection, _ = server.accept()
                except socket.timeout:
                    continue
                with connection:
                    connection.settimeout(2)
                    frame = bytearray()
                    while b"\n" not in frame:
                        chunk = connection.recv(4096)
                        if not chunk:
                            raise AssertionError("Client closed before a complete request")
                        frame.extend(chunk)
                    request = json.loads(frame)
                    data["requests"].append(request)
                    response = {"request_id": request["request_id"], "status": data["status"]}
                    if data["status"] == "ok":
                        response["result"] = {"status": "accepted"}
                    else:
                        response["error"] = "no_active_target"
                    connection.sendall(json.dumps(response).encode() + b"\n")
        except Exception as exc:
            data["errors"].append(exc)

    thread = threading.Thread(target=serve, name="fbt-cli-control")
    thread.start()
    monkeypatch.setattr(client, "FOLDER_WORKSPACE_TASK", str(folder))
    monkeypatch.setattr(state, "yaml_commands", yaml_commands.load_yaml_commands(
        str(Path(__file__).resolve().parents[2] / "topsailai.yaml")))
    monkeypatch.setattr(state, "current_scope", "runtime")
    monkeypatch.setattr(state, "current_session_id", "fbt")

    def execute(argv, *args):
        """Replace only process launching, running the actual CLI main/client."""
        data["launches"].append(argv)
        with monkeypatch.context() as local:
            local.setattr(sys, "argv", argv)
            data["exit_code"] = client.main()

    monkeypatch.setattr("cli_topsailai.process.run_external_command", execute)
    try:
        yield data
    finally:
        stop.set()
        thread.join(3)
        server.close()
        unrelated.settimeout(0.05)
        try:
            unexpected, _ = unrelated.accept()
        except socket.timeout:
            unexpected = None
        if unexpected is not None:
            unexpected.close()
        unrelated.close()
        for owned in (path, unrelated_path):
            owned.unlink(missing_ok=True)
            print(f"Deleted test socket: {owned}")
        temporary.cleanup()
        print(f"Deleted test directory: {folder}")
        assert not thread.is_alive(), "Control fixture thread failed to stop"
        assert not data["errors"], data["errors"]
        assert unexpected is None, "An unrelated socket received control"


@given(parsers.parse('a local control socket that returns "{status}"'))
def endpoint_status(control_endpoint, status):
    """Select the backend response without stubbing the client."""
    control_endpoint["status"] = status


@when(parsers.parse('I enter "{command}" with a watched PID'))
def enter_command(control_endpoint, command):
    """Drive the interactive runtime command entry using live YAML."""
    folder = control_endpoint["folder"]
    _handle_stream_command(command, folder, [], "fbt", folder + "/fbt.2468.session.stdout", default_pid=2468)


@when("I enter a first-byte shortcut without a watched PID")
def enter_without_pid(control_endpoint):
    """An absent watched identity must not fall back to discovery."""
    _handle_stream_command("/control.fbt.force_retry", control_endpoint["folder"], [], "fbt", None, default_pid=None)


@then(parsers.parse('one request carries "{action}" and operation "{operation}"'))
def exact_request(control_endpoint, action, operation):
    """Assert one exact wire payload and one exact watched PID selection."""
    assert len(control_endpoint["requests"]) == len(control_endpoint["launches"]) == 1
    request = control_endpoint["requests"][0]
    assert request["action"] == action
    assert request["payload"] == ({} if operation == "none" else {"operation": operation})
    argv = control_endpoint["launches"][0]
    assert argv[argv.index("-p") + 1] == "2468"
    assert argv[argv.index("-s") + 1] == "fbt"
    assert control_endpoint["exit_code"] == (0 if control_endpoint["status"] == "ok" else 1)


@then("no control request is sent")
def no_request(control_endpoint):
    """Verify no launcher invocation or request when PID selection fails."""
    assert control_endpoint["requests"] == control_endpoint["launches"] == []


@then(parsers.parse('the control response contains "{text}"'))
def response_text(capsys, text):
    """Keep the backend response visible rather than inventing success."""
    assert text in capsys.readouterr().out
