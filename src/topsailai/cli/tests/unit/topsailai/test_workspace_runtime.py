"""Verify per-row runtime collection for the workspace JSON document.

Author: DawsonLin
"""

import json
import os
import socket
import threading
import time
from unittest.mock import Mock

import pytest

from cli_topsailai import core, paths, workspace_runtime
from cli_topsailai.runtime_control import ControlDeliveryError


def make_socket(task_dir, session_id, pid):
    """Create a real socket file so the existence check passes."""
    path = os.path.join(task_dir, f"{session_id}.{pid}.session.sock")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(path)
    finally:
        sock.close()
    return path


def row(session_id="sample", pid=123, filename=None, is_task=False,
        session_pid=None):
    """Build a discovered row carrying only the fields the collector reads."""
    item = {
        "session_id": session_id,
        "pid": pid,
        "is_task": is_task,
        "filename": filename or f"{session_id}.{pid}.session.stdout",
    }
    if session_pid is not None:
        item["session_pid"] = session_pid
    return item


def static_payload(**overrides):
    """Build the payload ``/runtime.static-data`` returns, as a JSON string."""
    data = {
        "ok": True,
        "session": {"id": "sample", "ephemeral": False},
        "model": {"name": "example-model", "max_tokens": 400000},
        "agent2llm": {"messages": 17},
        "user2agent": {"messages": 2},
        "tools": {"available": 12},
        "tool_calls": {"total": 34},
    }
    data.update(overrides)
    return json.dumps(data)


def ok_sender(payload=None):
    """Return a sender that answers with a correlated ok response."""
    body = payload if payload is not None else static_payload()

    def send(socket_path, action, request_payload, *, timeout):
        assert action == "call_instruction"
        assert request_payload["instruction"] == "runtime.static-data"
        assert request_payload["args"] == ["json=1"]
        return Mock(response={"status": "ok", "result": body})

    return send


def test_ok_row_publishes_decoded_runtime_data(tmp_path):
    """A correlated ok response is decoded from its JSON string into data."""
    make_socket(str(tmp_path), "sample", 123)

    collected = workspace_runtime.collect_workspace_runtime(
        [row()], str(tmp_path), sender=ok_sender(),
    )

    record = collected["sample.123.session.stdout"]
    assert record["state"] == "ok"
    assert record["error_code"] is None
    assert record["pid"] == 123
    assert record["data"]["model"]["name"] == "example-model"
    assert record["data"]["model"]["max_tokens"] == 400000
    assert record["data"]["agent2llm"]["messages"] == 17
    assert record["data"]["tool_calls"]["total"] == 34


def test_instruction_uses_the_positional_argument_form(tmp_path):
    """The keyword form is rejected by the core, so only args may be sent."""
    make_socket(str(tmp_path), "sample", 123)
    seen = {}

    def send(socket_path, action, request_payload, *, timeout):
        seen.update(request_payload)
        return Mock(response={"status": "ok", "result": static_payload()})

    workspace_runtime.collect_workspace_runtime(
        [row()], str(tmp_path), sender=send,
    )

    assert seen["args"] == ["json=1"]
    assert "kwargs" not in seen


def test_missing_socket_reports_unavailable_without_a_request(tmp_path):
    """A row with no socket file is reported without contacting anything."""
    calls = []

    def send(socket_path, action, request_payload, *, timeout):
        calls.append(socket_path)
        return Mock(response={"status": "ok", "result": static_payload()})

    collected = workspace_runtime.collect_workspace_runtime(
        [row()], str(tmp_path), sender=send,
    )

    assert calls == []
    assert collected["sample.123.session.stdout"]["state"] == "unavailable"
    assert collected["sample.123.session.stdout"]["error_code"] == "endpoint_missing"


def test_rejected_row_keeps_its_own_state(tmp_path):
    """A process that predates the JSON output is reported, not dropped."""
    make_socket(str(tmp_path), "sample", 123)

    def send(socket_path, action, request_payload, *, timeout):
        raise ControlDeliveryError("control request rejected",
                                   "control_rejected", 6)

    collected = workspace_runtime.collect_workspace_runtime(
        [row()], str(tmp_path), sender=send,
    )

    record = collected["sample.123.session.stdout"]
    assert record["state"] == "rejected"
    assert record["error_code"] == "control_rejected"
    assert record["data"] is None


def test_timeout_row_is_reported_as_timeout(tmp_path):
    """A wedged agent costs one timeout and never aborts the document."""
    make_socket(str(tmp_path), "sample", 123)

    def send(socket_path, action, request_payload, *, timeout):
        raise ControlDeliveryError("control request timed out", "timeout", 5)

    collected = workspace_runtime.collect_workspace_runtime(
        [row()], str(tmp_path), sender=send,
    )

    assert collected["sample.123.session.stdout"]["state"] == "timeout"


def test_stale_socket_transport_error_is_unavailable(tmp_path):
    """A socket file that outlived its owner is not a channel."""
    make_socket(str(tmp_path), "sample", 123)

    def send(socket_path, action, request_payload, *, timeout):
        raise ControlDeliveryError("control transport failed",
                                   "transport_error", 5)

    collected = workspace_runtime.collect_workspace_runtime(
        [row()], str(tmp_path), sender=send,
    )

    assert collected["sample.123.session.stdout"]["state"] == "unavailable"


@pytest.mark.parametrize("body", ["not json", "[1, 2]", "null", 42])
def test_unparseable_result_is_invalid_payload(tmp_path, body):
    """A payload that is not a JSON object is a per-row state."""
    make_socket(str(tmp_path), "sample", 123)

    collected = workspace_runtime.collect_workspace_runtime(
        [row()], str(tmp_path), sender=ok_sender(body),
    )

    record = collected["sample.123.session.stdout"]
    assert record["state"] == "invalid_payload"
    assert record["error_code"] == "invalid_payload"


def test_instruction_self_reported_failure_is_not_ok(tmp_path):
    """``state == ok`` must mean usable data, so a self-reported failure is not."""
    make_socket(str(tmp_path), "sample", 123)

    collected = workspace_runtime.collect_workspace_runtime(
        [row()], str(tmp_path),
        sender=ok_sender(json.dumps({"ok": False, "error": "no_agent"})),
    )

    record = collected["sample.123.session.stdout"]
    assert record["state"] == "unavailable"
    assert record["error_code"] == "no_agent"


def test_task_row_queries_the_parent_session_pid(tmp_path):
    """A task row is owned by its parent session, never by its own PID."""
    make_socket(str(tmp_path), "sample", 900)
    probed = []

    def send(socket_path, action, request_payload, *, timeout):
        probed.append(socket_path)
        return Mock(response={"status": "ok", "result": static_payload()})

    collected = workspace_runtime.collect_workspace_runtime(
        [row(pid=901, filename="sample.901.task.stdout", is_task=True,
             session_pid=900)],
        str(tmp_path), sender=send,
    )

    assert probed == [os.path.join(str(tmp_path), "sample.900.session.sock")]
    assert collected["sample.901.task.stdout"]["state"] == "ok"


def test_task_row_without_a_parent_pid_is_not_probed(tmp_path):
    """An unresolvable parent must not fall back to the child's PID."""
    make_socket(str(tmp_path), "sample", 901)
    calls = []

    def send(socket_path, action, request_payload, *, timeout):
        calls.append(socket_path)
        return Mock(response={"status": "ok", "result": static_payload()})

    collected = workspace_runtime.collect_workspace_runtime(
        [row(pid=901, filename="sample.901.task.stdout", is_task=True)],
        str(tmp_path), sender=send,
    )

    assert calls == []
    assert collected["sample.901.task.stdout"]["error_code"] == "unsupported_row"


def test_temporary_session_maps_the_display_label_to_the_file_prefix(tmp_path):
    """The display sentinel and the on-disk prefix name the same socket."""
    make_socket(str(tmp_path), "topsailai", 123)
    probed = []

    def send(socket_path, action, request_payload, *, timeout):
        probed.append(socket_path)
        return Mock(response={"status": "ok", "result": static_payload()})

    collected = workspace_runtime.collect_workspace_runtime(
        [row(session_id="(temp)", filename="topsailai.123.session.stdout")],
        str(tmp_path), sender=send,
    )

    assert probed == [os.path.join(str(tmp_path), "topsailai.123.session.sock")]
    assert collected["topsailai.123.session.stdout"]["state"] == "ok"


def test_unsafe_session_id_is_not_composed_into_a_path(tmp_path):
    """A traversal attempt is reported instead of being probed."""
    calls = []

    def send(socket_path, action, request_payload, *, timeout):
        calls.append(socket_path)
        return Mock(response={"status": "ok", "result": static_payload()})

    collected = workspace_runtime.collect_workspace_runtime(
        [row(session_id="../escape")], str(tmp_path), sender=send,
    )

    assert calls == []
    assert collected["../escape.123.session.stdout"]["error_code"] == "unsupported_row"


def test_unexpected_sender_failure_is_contained(tmp_path):
    """An unexpected exception is one row's problem, never the document's."""
    make_socket(str(tmp_path), "sample", 123)

    def send(socket_path, action, request_payload, *, timeout):
        raise RuntimeError("boom")

    collected = workspace_runtime.collect_workspace_runtime(
        [row()], str(tmp_path), sender=send,
    )

    record = collected["sample.123.session.stdout"]
    assert record["state"] == "unavailable"
    assert record["error_code"] == "internal_error"


def test_one_failing_row_does_not_hide_the_others(tmp_path):
    """A mixed batch reports every row independently."""
    make_socket(str(tmp_path), "good", 1)
    make_socket(str(tmp_path), "bad", 2)

    def send(socket_path, action, request_payload, *, timeout):
        if "bad" in socket_path:
            raise ControlDeliveryError("control request timed out", "timeout", 5)
        return Mock(response={"status": "ok", "result": static_payload()})

    collected = workspace_runtime.collect_workspace_runtime(
        [row("good", 1), row("bad", 2)], str(tmp_path), sender=send,
    )

    assert collected["good.1.session.stdout"]["state"] == "ok"
    assert collected["bad.2.session.stdout"]["state"] == "timeout"


def test_collection_is_concurrent(tmp_path):
    """Requests must overlap, so a serial implementation fails this test."""
    rows = []
    for index in range(8):
        make_socket(str(tmp_path), f"s{index}", index + 1)
        rows.append(row(f"s{index}", index + 1))
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    def send(socket_path, action, request_payload, *, timeout):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.05)
        with lock:
            state["active"] -= 1
        return Mock(response={"status": "ok", "result": static_payload()})

    started = time.monotonic()
    collected = workspace_runtime.collect_workspace_runtime(
        rows, str(tmp_path), max_workers=4, sender=send,
    )
    elapsed = time.monotonic() - started

    assert len(collected) == 8
    assert all(record["state"] == "ok" for record in collected.values())
    assert state["peak"] > 1, "requests never overlapped, so collection is serial"
    assert elapsed < 8 * 0.05, "wall time matches a serial run"


def test_worker_pool_is_bounded(tmp_path):
    """The pool must never exceed the configured bound."""
    rows = []
    for index in range(10):
        make_socket(str(tmp_path), f"s{index}", index + 1)
        rows.append(row(f"s{index}", index + 1))
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    def send(socket_path, action, request_payload, *, timeout):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.02)
        with lock:
            state["active"] -= 1
        return Mock(response={"status": "ok", "result": static_payload()})

    workspace_runtime.collect_workspace_runtime(
        rows, str(tmp_path), max_workers=3, sender=send,
    )

    assert state["peak"] <= 3


def test_empty_rows_do_not_start_a_pool():
    """An empty list returns immediately without touching the transport."""
    assert workspace_runtime.collect_workspace_runtime([], "/nonexistent") == {}


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point the one-shot printer at an isolated task directory."""
    monkeypatch.setattr(paths, "get_topsailai_home", lambda: str(tmp_path))
    monkeypatch.setattr(core, "_driver_authority", Mock(return_value=None))
    monkeypatch.setattr(core.socket, "gethostname", lambda: "host-a")
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def test_json_without_the_flag_reports_null_runtime(isolated_home, capsys,
                                                    monkeypatch):
    """The default document must not collect anything and must keep the key."""
    (isolated_home / "sample.123.session.stdout").touch()
    collect = Mock(side_effect=AssertionError("collection must not run"))
    monkeypatch.setattr(workspace_runtime, "collect_workspace_runtime", collect)

    core._print_workspace_json()

    payload = json.loads(capsys.readouterr().out)
    assert payload["items"][0]["runtime"] is None
    assert collect.call_count == 0


def test_json_with_the_flag_reports_collected_runtime(isolated_home, capsys,
                                                      monkeypatch):
    """The flag must reach the collector and its result must reach the item."""
    (isolated_home / "sample.123.session.stdout").touch()
    record = {"state": "ok", "error_code": None, "pid": 123,
              "data": {"ok": True, "model": "example-model"}}
    collect = Mock(return_value={"sample.123.session.stdout": record})
    monkeypatch.setattr(workspace_runtime, "collect_workspace_runtime", collect)

    core._print_workspace_json(include_runtime=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["items"][0]["runtime"] == record
    assert collect.call_count == 1


def test_include_runtime_selects_json_output(isolated_home, capsys,
                                             monkeypatch):
    """The flag alone must produce the JSON document, not the table."""
    (isolated_home / "sample.123.session.stdout").touch()
    monkeypatch.setattr(
        workspace_runtime, "collect_workspace_runtime",
        Mock(return_value={"sample.123.session.stdout": {
            "state": "ok", "error_code": None, "pid": 123, "data": {"ok": True},
        }}),
    )
    table = Mock(side_effect=AssertionError("the table must not be printed"))
    monkeypatch.setattr(core, "_print_workspace_table", table)

    with pytest.raises(SystemExit) as raised:
        core.main(["workspace", "list", "--include-runtime"])

    out = capsys.readouterr().out
    assert raised.value.code == 0
    payload = json.loads(out)
    assert payload["items"][0]["runtime"]["state"] == "ok"
    assert table.call_count == 0


def test_include_runtime_is_absent_from_the_parser_by_default(monkeypatch):
    """The flag must be opt-in, so its default is false."""
    printer = Mock()
    monkeypatch.setattr(core, "_print_workspace_json", printer)

    with pytest.raises(SystemExit) as raised:
        core.main(["workspace", "list", "--json"])

    assert raised.value.code == 0
    printer.assert_called_once_with(
        include_completed=False, session_ids=None, local_only=False,
        include_runtime=False,
    )


def test_default_pool_is_twenty():
    """The default bound must be the wide pool the instruction cost allows."""
    assert workspace_runtime.DEFAULT_MAX_WORKERS == 20


def test_default_pool_is_used_when_the_caller_omits_it(tmp_path):
    """The collector must apply its own default instead of a narrow fallback."""
    rows = []
    for index in range(25):
        make_socket(str(tmp_path), f"s{index}", index + 1)
        rows.append(row(f"s{index}", index + 1))
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    def send(socket_path, action, request_payload, *, timeout):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.05)
        with lock:
            state["active"] -= 1
        return Mock(response={"status": "ok", "result": static_payload()})

    workspace_runtime.collect_workspace_runtime(rows, str(tmp_path), sender=send)

    assert state["peak"] > 4, "the default pool must be wider than the old bound"
    assert state["peak"] <= 20


def test_collection_failure_keeps_the_document(isolated_home, capsys,
                                               monkeypatch):
    """A collector that raises must leave runtime null, never break the JSON."""
    (isolated_home / "sample.123.session.stdout").touch()
    monkeypatch.setattr(
        workspace_runtime, "collect_workspace_runtime",
        Mock(side_effect=RuntimeError("collector exploded")),
    )

    core._print_workspace_json(include_runtime=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 1
    assert payload["items"][0]["runtime"] is None


def test_import_failure_keeps_the_document(isolated_home, capsys, monkeypatch):
    """An unimportable collector module must not break the document either."""
    (isolated_home / "sample.123.session.stdout").touch()
    import builtins

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "cli_topsailai.workspace_runtime":
            raise ImportError("module unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    core._print_workspace_json(include_runtime=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 1
    assert payload["items"][0]["runtime"] is None


def test_single_session_collector_publishes_the_same_record(tmp_path):
    """The single-session entry point must reuse the per-row contract."""
    make_socket(str(tmp_path), "sample", 123)

    record = workspace_runtime.collect_session_runtime(
        "sample", 123, str(tmp_path), sender=ok_sender(),
    )

    assert record["state"] == "ok"
    assert record["error_code"] is None
    assert record["pid"] == 123
    assert record["data"]["model"]["name"] == "example-model"


def test_single_session_collector_uses_the_positional_argument_form(tmp_path):
    """Both entry points must send one identical request."""
    make_socket(str(tmp_path), "sample", 123)
    seen = {}

    def send(socket_path, action, request_payload, *, timeout):
        seen.update(request_payload)
        return Mock(response={"status": "ok", "result": static_payload()})

    workspace_runtime.collect_session_runtime(
        "sample", 123, str(tmp_path), sender=send,
    )

    assert seen["instruction"] == "runtime.static-data"
    assert seen["args"] == ["json=1"]
    assert "kwargs" not in seen


def test_single_session_collector_without_a_pid_is_unsupported(tmp_path):
    """No resolved owner means nothing may be contacted."""
    calls = []

    def send(socket_path, action, request_payload, *, timeout):
        calls.append(socket_path)
        return Mock(response={"status": "ok", "result": static_payload()})

    record = workspace_runtime.collect_session_runtime(
        "sample", None, str(tmp_path), sender=send,
    )

    assert calls == []
    assert record["state"] == "unavailable"
    assert record["error_code"] == "unsupported_row"


def test_single_session_collector_reports_a_missing_endpoint(tmp_path):
    """A stale or absent socket is reported without a request."""
    calls = []

    def send(socket_path, action, request_payload, *, timeout):
        calls.append(socket_path)
        return Mock(response={"status": "ok", "result": static_payload()})

    record = workspace_runtime.collect_session_runtime(
        "sample", 123, str(tmp_path), sender=send,
    )

    assert calls == []
    assert record["state"] == "unavailable"
    assert record["error_code"] == "endpoint_missing"


def test_single_session_collector_reports_a_rejection(tmp_path):
    """A process that predates the instruction keeps its own state."""
    make_socket(str(tmp_path), "sample", 123)

    def send(socket_path, action, request_payload, *, timeout):
        raise ControlDeliveryError("control request rejected",
                                   "control_rejected", 6)

    record = workspace_runtime.collect_session_runtime(
        "sample", 123, str(tmp_path), sender=send,
    )

    assert record["state"] == "rejected"
    assert record["error_code"] == "control_rejected"


def test_single_session_collector_reports_an_unexpected_failure(tmp_path):
    """An unexpected transport failure is one record's problem, not a raise."""
    make_socket(str(tmp_path), "sample", 123)

    def send(socket_path, action, request_payload, *, timeout):
        raise RuntimeError("transport exploded")

    record = workspace_runtime.collect_session_runtime(
        "sample", 123, str(tmp_path), sender=send,
    )

    assert record["state"] == "unavailable"
    assert record["error_code"] == "internal_error"


def test_single_session_collector_reports_an_instruction_failure(tmp_path):
    """An instruction that answered with its own failure is unavailable."""
    make_socket(str(tmp_path), "sample", 123)

    def send(socket_path, action, request_payload, *, timeout):
        body = json.dumps({"ok": False, "error": "no_runtime_state"})
        return Mock(response={"status": "ok", "result": body})

    record = workspace_runtime.collect_session_runtime(
        "sample", 123, str(tmp_path), sender=send,
    )

    assert record["state"] == "unavailable"
    assert record["error_code"] == "no_runtime_state"


def test_single_session_collector_accepts_the_temp_sentinel(tmp_path):
    """The display sentinel must resolve the on-disk temporary identity."""
    make_socket(str(tmp_path), "topsailai", 123)

    record = workspace_runtime.collect_session_runtime(
        "(temp)", 123, str(tmp_path), sender=ok_sender(),
    )

    assert record["state"] == "ok"
    assert record["data"]["model"]["name"] == "example-model"
