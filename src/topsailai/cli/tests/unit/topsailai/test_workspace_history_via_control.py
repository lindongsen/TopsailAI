#!/usr/bin/env python3
"""Workspace history retrieval through the session control channel.

These tests pin the fallback that lets a workspace row without a session id
(a temporary session displayed as ``(temp)``) show its history by invoking the
registered ``ctx.history`` instruction over its existing control socket.
"""

import json
import os
import shutil
import socket
import threading
import uuid
from pathlib import Path

import pytest

import cli_topsailai.core as cli_core
from cli_topsailai import retrieve as retrieve_module
from cli_topsailai.formatting import sanitize_terminal_text
from cli_topsailai.retrieve import (
    CONTROL_HISTORY_INSTRUCTION,
    ControlHistoryError,
    ControlHistoryTarget,
    _file_session_id,
    _is_socket,
    _render_history_result,
    _row_session_pid,
    resolve_control_history_target,
    retrieve_session_history_via_control,
)

TEMP_MARKER = "(temp)"
TEMP_ID = "topsailai"

# A Unix socket path is limited to about 108 bytes, so task directories used by
# these tests are short and live under the workspace temporary folder.
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = WORKSPACE_ROOT / ".tmp"


@pytest.fixture
def task_dir(monkeypatch):
    """Create a short task directory and remove it afterwards.

    Fixture sockets are owned by fake PIDs, so liveness is stubbed to "alive"
    by default; a test that needs a stale owner overrides it explicitly.
    """
    monkeypatch.setattr(retrieve_module, "_is_live_pid", lambda pid: True)
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TMP_ROOT / f"h{uuid.uuid4().hex[:6]}"
    path.mkdir()
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)
        print(f"Deleted fixture task directory: {path}")


def make_socket_file(path):
    """Create a real socket inode at ``path`` and release the descriptor."""
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(path))
    finally:
        server.close()
    return path


def socket_path(task_dir, session_id, pid):
    """Compose the documented control socket filename."""
    return os.path.join(str(task_dir), f"{session_id}.{pid}.session.sock")


class RecordingSender:
    """Delivery seam that records the single request it receives."""

    def __init__(self, result=None, error=None):
        """Store the canned outcome and the observed calls."""
        self.result = result
        self.error = error
        self.calls = []

    def __call__(self, socket_path, action, payload, *, timeout=5.0):
        """Record one request and return or raise the canned outcome."""
        self.calls.append((socket_path, action, payload, timeout))
        if self.error is not None:
            raise self.error
        return type("Result", (), {"response": {"status": "ok",
                                                "result": self.result}})()


class TestFileSessionId:
    """Display identity must be translated before path composition."""

    @pytest.mark.parametrize("value", [None, "", TEMP_MARKER, TEMP_ID])
    def test_absent_identity_maps_to_reserved_prefix(self, value):
        """Every absent-identity spelling becomes the reserved file prefix."""
        assert _file_session_id(value) == TEMP_ID

    def test_real_identity_is_preserved(self):
        """A real identifier is used verbatim."""
        assert _file_session_id("20261105213522") == "20261105213522"

    @pytest.mark.parametrize("value", ["../x", "a/b", "a\\b", ".", "..", "a..b"])
    def test_unsafe_identity_is_rejected(self, value):
        """An identifier that could escape the task directory is rejected."""
        with pytest.raises(ControlHistoryError) as caught:
            _file_session_id(value)
        assert caught.value.error_code == "usage_error"


class TestRowSessionPid:
    """A task row is owned by its parent session process, never by itself."""

    def test_task_row_uses_parent_session_pid(self):
        """The parent session PID owns the socket for a task row."""
        assert _row_session_pid({"is_task": True, "pid": 10, "session_pid": 20}) == 20

    def test_task_row_without_parent_fails_closed(self):
        """An ambiguous parent is rejected instead of guessed."""
        with pytest.raises(ControlHistoryError) as caught:
            _row_session_pid({"is_task": True, "pid": 10, "session_pid": None})
        assert caught.value.error_code == "unsupported_row"

    def test_session_row_prefers_session_pid(self):
        """A session row uses its own session PID."""
        assert _row_session_pid({"is_task": False, "pid": 10, "session_pid": 10}) == 10

    def test_session_row_falls_back_to_pid(self):
        """A session row without session_pid still uses its own PID."""
        assert _row_session_pid({"is_task": False, "pid": 11}) == 11

    @pytest.mark.parametrize("pid", [0, -1, "12", True, None])
    def test_unusable_pid_is_rejected(self, pid):
        """A non-positive or non-integer PID is rejected."""
        with pytest.raises(ControlHistoryError) as caught:
            _row_session_pid({"is_task": False, "pid": pid})
        assert caught.value.error_code == "unsupported_row"


class TestIsSocket:
    """Only a real socket inode counts as a control channel."""

    def test_socket_inode_is_accepted(self, task_dir):
        """A bound socket file is a channel."""
        assert _is_socket(make_socket_file(socket_path(task_dir, TEMP_ID, 1))) is True

    def test_regular_file_is_rejected(self, task_dir):
        """A regular file is not a channel."""
        path = socket_path(task_dir, TEMP_ID, 1)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not a socket")
        assert _is_socket(path) is False

    def test_symlink_to_socket_is_rejected(self, task_dir):
        """A symlink is not followed, so it cannot redirect the request."""
        target = make_socket_file(socket_path(task_dir, TEMP_ID, 1))
        link = socket_path(task_dir, TEMP_ID, 2)
        os.symlink(target, link)
        assert _is_socket(link) is False

    def test_missing_path_is_rejected(self, task_dir):
        """A missing path is not a channel."""
        assert _is_socket(socket_path(task_dir, TEMP_ID, 9)) is False


class TestResolveRowMode:
    """Row mode resolves the socket owned by the row's session process."""

    def test_temp_row_resolves_translated_socket(self, task_dir):
        """The display sentinel is translated before the path is composed."""
        make_socket_file(socket_path(task_dir, TEMP_ID, 4242))
        target = resolve_control_history_target(
            task_dir,
            row={"session_id": TEMP_MARKER, "is_task": False, "pid": 4242},
        )
        assert target == ControlHistoryTarget(
            socket_path(task_dir, TEMP_ID, 4242), TEMP_ID, 4242
        )

    def test_real_row_resolves_its_own_socket(self, task_dir):
        """A real session id composes its own socket path."""
        make_socket_file(socket_path(task_dir, "s1", 77))
        target = resolve_control_history_target(
            task_dir,
            row={"session_id": "s1", "is_task": False, "pid": 77},
        )
        assert target.session_id == "s1" and target.pid == 77

    def test_missing_socket_returns_none(self, task_dir):
        """No socket is the only "no channel" answer."""
        assert resolve_control_history_target(
            task_dir,
            row={"session_id": TEMP_MARKER, "is_task": False, "pid": 4242},
        ) is None

    def test_task_row_resolves_parent_socket(self, task_dir):
        """A task row resolves through its parent session PID."""
        make_socket_file(socket_path(task_dir, "s1", 20))
        target = resolve_control_history_target(
            task_dir,
            row={"session_id": "s1", "is_task": True, "pid": 10, "session_pid": 20},
        )
        assert target.pid == 20

    def test_unsafe_row_identity_is_rejected(self, task_dir):
        """An unsafe identifier is rejected before any path composition."""
        with pytest.raises(ControlHistoryError) as caught:
            resolve_control_history_target(
                task_dir,
                row={"session_id": "../x", "is_task": False, "pid": 1},
            )
        assert caught.value.error_code == "usage_error"


class TestResolveLiteralMode:
    """Literal mode resolves the single live socket of a temporary identity."""

    @pytest.fixture(autouse=True)
    def live_pids(self, monkeypatch):
        """Treat the fixture PIDs as live owners unless a test says otherwise."""
        live = {31, 32, 42, 7}
        monkeypatch.setattr(
            retrieve_module, "_is_live_pid", lambda pid: pid in live
        )
        return live

    def test_single_socket_resolves(self, task_dir):
        """Exactly one matching socket is used."""
        make_socket_file(socket_path(task_dir, TEMP_ID, 31))
        target = resolve_control_history_target(task_dir, session_id=TEMP_MARKER)
        assert target == ControlHistoryTarget(
            socket_path(task_dir, TEMP_ID, 31), TEMP_ID, 31
        )

    def test_no_socket_returns_none(self, task_dir):
        """No matching socket means no channel."""
        assert resolve_control_history_target(
            task_dir, session_id=TEMP_MARKER
        ) is None

    def test_multiple_live_sockets_are_ambiguous(self, task_dir):
        """Several live matching sockets are reported instead of guessed."""
        make_socket_file(socket_path(task_dir, TEMP_ID, 31))
        make_socket_file(socket_path(task_dir, TEMP_ID, 32))
        with pytest.raises(ControlHistoryError) as caught:
            resolve_control_history_target(task_dir, session_id=TEMP_MARKER)
        assert caught.value.error_code == "ambiguous_target"

    def test_stale_socket_is_not_a_channel(self, task_dir, monkeypatch):
        """A socket whose owner is gone cannot answer, so it is not a channel."""
        make_socket_file(socket_path(task_dir, TEMP_ID, 31))
        monkeypatch.setattr(retrieve_module, "_is_live_pid", lambda pid: False)
        assert resolve_control_history_target(
            task_dir, session_id=TEMP_MARKER
        ) is None

    def test_stale_socket_does_not_make_one_live_owner_ambiguous(
        self, task_dir, monkeypatch
    ):
        """A leftover socket must not hide the single live owner."""
        make_socket_file(socket_path(task_dir, TEMP_ID, 31))
        make_socket_file(socket_path(task_dir, TEMP_ID, 32))
        monkeypatch.setattr(retrieve_module, "_is_live_pid", lambda pid: pid == 32)
        target = resolve_control_history_target(task_dir, session_id=TEMP_MARKER)
        assert target == ControlHistoryTarget(
            socket_path(task_dir, TEMP_ID, 32), TEMP_ID, 32
        )

    def test_missing_task_dir_returns_none(self, task_dir):
        """A missing task directory is no channel, not an exception."""
        assert resolve_control_history_target(
            os.path.join(task_dir, "absent"), session_id=TEMP_MARKER
        ) is None

    def test_regular_file_is_not_a_channel(self, task_dir):
        """A regular file with the socket name is not a channel."""
        path = socket_path(task_dir, TEMP_ID, 31)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("x")
        assert resolve_control_history_target(
            task_dir, session_id=TEMP_MARKER
        ) is None


class TestRenderHistoryResult:
    """Instruction results are rendered without losing real newlines."""

    def test_none_renders_empty(self):
        """An absent result renders as nothing."""
        assert _render_history_result(None) == ""

    def test_string_is_verbatim(self):
        """A string keeps its newlines."""
        assert _render_history_result("a\nb") == "a\nb"

    def test_mapping_renders_json(self):
        """A structured result renders as indented JSON."""
        assert json.loads(_render_history_result({"k": 1})) == {"k": 1}


class TestSanitizeTerminalText:
    """Remote text cannot recolor or clear the local terminal."""

    def test_ansi_escape_is_stripped(self):
        """CSI sequences are removed."""
        assert sanitize_terminal_text("\x1b[31mred\x1b[0m") == "red"

    def test_newline_and_tab_are_preserved(self):
        """Real layout characters survive sanitizing."""
        assert sanitize_terminal_text("a\n\tb") == "a\n\tb"

    def test_control_characters_are_stripped(self):
        """Other control characters are removed."""
        assert sanitize_terminal_text("a\x07b") == "ab"


class TestRetrieveViaControl:
    """Exactly one request is sent and its outcome is reported honestly."""

    def test_single_request_with_exact_payload(self, capsys):
        """The payload names only the history instruction."""
        sender = RecordingSender(result="line1\nline2")
        target = ControlHistoryTarget("/tmp/x/topsailai.1.session.sock", TEMP_ID, 1)
        assert retrieve_session_history_via_control(target, sender=sender) is True
        assert len(sender.calls) == 1
        path, action, payload, _timeout = sender.calls[0]
        assert path == target.socket_path
        assert action == "call_instruction"
        assert payload == {"instruction": CONTROL_HISTORY_INSTRUCTION}
        out = capsys.readouterr().out
        assert "Session Content: (temp)" in out
        assert "line1\nline2" in out

    def test_delivery_error_is_reported_once(self, capsys):
        """A classified failure prints one line and is never retried."""
        from cli_topsailai.runtime_control import ControlDeliveryError

        sender = RecordingSender(
            error=ControlDeliveryError("rejected", "control_rejected", 6)
        )
        target = ControlHistoryTarget("/tmp/x/topsailai.1.session.sock", TEMP_ID, 1)
        assert retrieve_session_history_via_control(target, sender=sender) is False
        assert len(sender.calls) == 1
        assert "control_rejected" in capsys.readouterr().out

    def test_unexpected_error_is_reported_once(self, capsys):
        """An unexpected transport error is reported without a retry."""
        sender = RecordingSender(error=OSError("boom"))
        target = ControlHistoryTarget("/tmp/x/topsailai.1.session.sock", TEMP_ID, 1)
        assert retrieve_session_history_via_control(target, sender=sender) is False
        assert len(sender.calls) == 1
        assert "OSError" in capsys.readouterr().out

    def test_empty_result_prints_header_only(self, capsys):
        """An empty result does not crash."""
        sender = RecordingSender(result=None)
        target = ControlHistoryTarget("/tmp/x/topsailai.1.session.sock", TEMP_ID, 1)
        assert retrieve_session_history_via_control(target, sender=sender) is True
        assert "Session Content: (temp)" in capsys.readouterr().out


class TestCoreSelectedRow:
    """The workspace dispatch keeps the database path for real identifiers."""

    def test_real_id_uses_database_path(self, monkeypatch):
        """A real session id still calls the database retrieval path."""
        calls = []
        monkeypatch.setattr(
            retrieve_module, "retrieve_session",
            lambda session_id, max_chars=None: calls.append((session_id, max_chars)),
        )
        cli_core._show_selected_session_history(
            {"session_id": "s1", "is_task": False, "pid": 1}, "/tmp/task"
        )
        assert calls == [("s1", 1000)]

    def test_temp_row_with_socket_uses_control(self, task_dir, monkeypatch):
        """A temporary row with a socket is served through the control path."""
        make_socket_file(socket_path(task_dir, TEMP_ID, 4242))
        seen = []
        monkeypatch.setattr(
            retrieve_module, "retrieve_session_history_via_control",
            lambda target, **kwargs: seen.append(target),
        )
        cli_core._show_selected_session_history(
            {"session_id": TEMP_MARKER, "is_task": False, "pid": 4242}, task_dir
        )
        assert seen == [ControlHistoryTarget(
            socket_path(task_dir, TEMP_ID, 4242), TEMP_ID, 4242
        )]

    def test_temp_row_without_socket_keeps_message(self, task_dir, capsys):
        """No channel keeps the previous message unchanged."""
        cli_core._show_selected_session_history(
            {"session_id": TEMP_MARKER, "is_task": False, "pid": 4242}, task_dir
        )
        assert "No session ID available for this file." in capsys.readouterr().out

    def test_task_row_without_parent_reports_error_code(self, task_dir, capsys):
        """An ambiguous parent row reports its classified error."""
        cli_core._show_selected_session_history(
            {"session_id": TEMP_MARKER, "is_task": True, "pid": 1,
             "session_pid": None}, task_dir
        )
        assert "unsupported_row" in capsys.readouterr().out

    @pytest.mark.parametrize("stored_id", [TEMP_ID, ""])
    def test_reserved_or_empty_row_id_uses_control(self, task_dir, monkeypatch,
                                                   stored_id):
        """A stored reserved prefix or an empty id is the same absent identity."""
        make_socket_file(socket_path(task_dir, TEMP_ID, 4242))
        seen = []
        monkeypatch.setattr(
            retrieve_module, "retrieve_session_history_via_control",
            lambda target, **kwargs: seen.append(target),
        )
        cli_core._show_selected_session_history(
            {"session_id": stored_id, "is_task": False, "pid": 4242}, task_dir
        )
        assert seen == [ControlHistoryTarget(
            socket_path(task_dir, TEMP_ID, 4242), TEMP_ID, 4242
        )]


class TestCoreLiteralId:
    """A literal temporary argument resolves its single control socket."""

    def test_real_id_uses_database_path(self, monkeypatch):
        """A real literal id still calls the database retrieval path."""
        calls = []
        monkeypatch.setattr(
            retrieve_module, "retrieve_session",
            lambda session_id, max_chars=None: calls.append((session_id, max_chars)),
        )
        cli_core._show_literal_session_history("s1", "/tmp/task")
        assert calls == [("s1", 1000)]

    def test_temp_literal_with_socket_uses_control(self, task_dir, monkeypatch):
        """The literal temporary identity is served through its socket."""
        make_socket_file(socket_path(task_dir, TEMP_ID, 31))
        seen = []
        monkeypatch.setattr(
            retrieve_module, "retrieve_session_history_via_control",
            lambda target, **kwargs: seen.append(target),
        )
        cli_core._show_literal_session_history(TEMP_MARKER, task_dir)
        assert seen == [ControlHistoryTarget(
            socket_path(task_dir, TEMP_ID, 31), TEMP_ID, 31
        )]

    def test_temp_literal_without_socket_keeps_message(self, task_dir, capsys):
        """No channel keeps a clear message for the literal form."""
        cli_core._show_literal_session_history(TEMP_MARKER, task_dir)
        assert "No session ID available for session '(temp)'." in capsys.readouterr().out


class TestFixtureSocketEndToEnd:
    """Exchange one real request with a test-owned Unix socket."""

    def run_fixture(self, task_dir, status, result):
        """Serve exactly one request and return the observed evidence."""
        if not hasattr(socket, "AF_UNIX"):
            pytest.skip("Unix sockets unavailable")
        path = socket_path(task_dir, TEMP_ID, 31)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        server.settimeout(5)
        evidence = []

        def respond():
            """Answer one connection with a correlated frame."""
            try:
                with server.accept()[0] as client:
                    client.settimeout(5)
                    data = b""
                    while b"\n" not in data:
                        data += client.recv(4096)
                    request = json.loads(data)
                    evidence.append(request)
                    frame = {"request_id": request["request_id"], "status": status}
                    if status == "ok":
                        frame["result"] = result
                    else:
                        frame["error"] = "fixture rejection"
                    client.sendall(json.dumps(frame).encode() + b"\n")
            except BaseException as exc:  # pragma: no cover - fixture guard
                evidence.append(exc)

        thread = threading.Thread(target=respond)
        thread.start()
        try:
            target = resolve_control_history_target(task_dir, session_id=TEMP_MARKER)
            assert target is not None
            outcome = retrieve_session_history_via_control(target, timeout=5.0)
        finally:
            thread.join(6)
            server.close()
            os.unlink(path)
            print(f"Deleted fixture socket: {path}")
        assert not thread.is_alive()
        return outcome, evidence

    def test_ok_response_prints_history(self, task_dir, capsys):
        """A correlated ok response prints the returned history."""
        outcome, evidence = self.run_fixture(task_dir, "ok", "user: hi\nagent: hello")
        assert outcome is True
        assert len(evidence) == 1
        assert evidence[0]["action"] == "call_instruction"
        assert evidence[0]["payload"] == {"instruction": CONTROL_HISTORY_INSTRUCTION}
        out = capsys.readouterr().out
        assert "user: hi" in out and "agent: hello" in out

    def test_error_response_is_not_retried(self, task_dir, capsys):
        """A rejected request is reported once with no second connection."""
        outcome, evidence = self.run_fixture(task_dir, "error", None)
        assert outcome is False
        assert len(evidence) == 1
        assert "control_rejected" in capsys.readouterr().out

    def test_incomplete_frame_is_reported_once(self, task_dir, capsys):
        """A peer that closes without a frame is one classified failure."""
        if not hasattr(socket, "AF_UNIX"):
            pytest.skip("Unix sockets unavailable")
        path = socket_path(task_dir, TEMP_ID, 31)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        server.settimeout(5)
        connections = []

        def respond():
            """Read one request, then close without sending any frame."""
            try:
                with server.accept()[0] as client:
                    client.settimeout(5)
                    data = b""
                    while b"\n" not in data:
                        chunk = client.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    connections.append(data)
            except BaseException as exc:  # pragma: no cover - fixture guard
                connections.append(exc)

        thread = threading.Thread(target=respond)
        thread.start()
        try:
            target = resolve_control_history_target(task_dir, session_id=TEMP_MARKER)
            assert target is not None
            outcome = retrieve_session_history_via_control(target, timeout=5.0)
        finally:
            thread.join(6)
            server.close()
            os.unlink(path)
            print(f"Deleted fixture socket: {path}")
        assert not thread.is_alive()
        assert outcome is False
        assert len(connections) == 1
        assert "invalid_response" in capsys.readouterr().out


class TestScanFiltering:
    """Socket enumeration ignores entries that cannot belong to the identity."""

    def test_unrelated_entries_are_skipped(self, task_dir):
        """Names without the socket suffix or without a numeric PID are skipped."""
        from cli_topsailai.retrieve import _scan_session_sockets

        make_socket_file(socket_path(task_dir, TEMP_ID, 31))
        # A socket with an unrelated suffix, a socket without a PID, and a
        # socket whose PID is not numeric must all be ignored.
        make_socket_file(os.path.join(task_dir, f"{TEMP_ID}.31.session.stdout"))
        make_socket_file(os.path.join(task_dir, f"{TEMP_ID}.session.sock"))
        make_socket_file(os.path.join(task_dir, f"{TEMP_ID}.abc.session.sock"))
        found = _scan_session_sockets(task_dir, TEMP_ID)
        assert found == [(socket_path(task_dir, TEMP_ID, 31), 31)]

    def test_non_positive_and_foreign_pid_are_skipped(self, task_dir):
        """A zero PID and another session's socket are not candidates."""
        from cli_topsailai.retrieve import _scan_session_sockets

        make_socket_file(socket_path(task_dir, TEMP_ID, 0))
        make_socket_file(socket_path(task_dir, "other", 31))
        assert _scan_session_sockets(task_dir, TEMP_ID) == []

    def test_candidates_are_sorted_by_pid(self, task_dir):
        """Enumeration order is deterministic so ambiguity is stable."""
        from cli_topsailai.retrieve import _scan_session_sockets

        make_socket_file(socket_path(task_dir, TEMP_ID, 42))
        make_socket_file(socket_path(task_dir, TEMP_ID, 7))
        assert [pid for _, pid in _scan_session_sockets(task_dir, TEMP_ID)] == [7, 42]


class TestIsLivePid:
    """Only a provably alive owner counts as a channel."""

    def test_current_process_is_live(self):
        """The test process itself is provably alive."""
        from cli_topsailai.retrieve import _is_live_pid

        assert _is_live_pid(os.getpid()) is True

    def test_dead_pid_is_not_live(self):
        """A PID that cannot exist is not live."""
        from cli_topsailai.retrieve import _is_live_pid

        assert _is_live_pid(2 ** 22 + 12345) is False

    def test_unknown_state_is_not_live(self, monkeypatch):
        """An unverifiable state fails closed instead of claiming a channel."""
        from cli_topsailai import runtime_target
        from cli_topsailai.retrieve import _is_live_pid

        monkeypatch.setattr(
            runtime_target, "probe_process",
            lambda pid: runtime_target.ProcessState.UNKNOWN,
        )
        assert _is_live_pid(31) is False

    def test_probe_error_is_not_live(self, monkeypatch):
        """A probe failure fails closed instead of raising."""
        from cli_topsailai import runtime_target
        from cli_topsailai.retrieve import _is_live_pid

        def boom(pid):
            """Simulate an unreadable process state."""
            raise runtime_target.RuntimeTargetError("permission_denied", "denied")

        monkeypatch.setattr(runtime_target, "probe_process", boom)
        assert _is_live_pid(31) is False


class TestNonStringInputs:
    """Non-string inputs are classified instead of being coerced silently."""

    def test_non_string_identity_is_rejected(self):
        """A non-string identifier cannot be composed into a path."""
        with pytest.raises(ControlHistoryError) as caught:
            _file_session_id(12345)
        assert caught.value.error_code == "usage_error"

    def test_non_container_result_is_stringified(self):
        """A scalar result is rendered through its string form."""
        assert _render_history_result(7) == "7"

    def test_non_string_text_is_stringified(self):
        """Sanitizing accepts a non-string value by stringifying it first."""
        assert sanitize_terminal_text(7) == "7"
