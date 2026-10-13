"""Verify session completion overrides workspace display status only.

Author: DawsonLin
"""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cli_topsailai import formatting, session_driver
from cli_topsailai.colors import Colors
from cli_topsailai.core import _workspace_json_item


@pytest.fixture
def session_row(tmp_path, monkeypatch):
    """Isolate process probes and driver observations from the real host."""
    monkeypatch.setattr(formatting, "os", SimpleNamespace(kill=Mock()))
    monkeypatch.setattr(formatting, "is_session_pipe_open", Mock(return_value=False))
    monkeypatch.setattr(session_driver, "observe_driver", Mock(return_value=None))
    return {
        "filename": "sample.1234.session.stdout",
        "session_id": "sample",
        "pid": 1234,
        "session_pid": 1234,
        "is_task": False,
        "ctime": 1700000000.0,
    }


def write_meta(home, content, pid=1234):
    """Create only test-owned metadata under the pytest temporary root."""
    directory = home / "workspace" / "task"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"sample.{pid}.session.meta"
    path.write_text(content)
    return path


def completed(**overrides):
    """Return the valid completion record with optional invalid fields."""
    return json.dumps(dict(session_id="sample", pid=1234, status="completed") | overrides)


@pytest.mark.parametrize("suffix", ["stdout", "stderr"])
def test_completed_is_idle_and_outputs_agree(session_row, tmp_path, capsys, suffix):
    """Retain the live PID while presenting completion consistently."""
    session_row["filename"] = f"sample.1234.session.{suffix}"
    write_meta(tmp_path, completed())
    formatting.enrich_workspace_rows([session_row], str(tmp_path))
    assert session_row["workspace_status"] == "idle"
    assert session_row["workspace_pid"] == 1234
    result = _workspace_json_item(session_row, 1)
    assert result["status"] == "idle"
    assert result["pid"] == 1234
    formatting.print_table([session_row])
    line = next(line for line in capsys.readouterr().out.splitlines() if "sample" in line)
    assert Colors.GRAY in line
    assert Colors.GREEN not in line
    assert line.split("|")[4].strip() == "-"


@pytest.mark.parametrize("content", [
    completed(pid=4321), completed(session_id="other"), completed(pid="1234"),
    completed(pid=True), completed(status="interrupted"), completed(status="running"),
    completed(status="unknown"), "{}", "[]", "null", '"completed"',
    "{broken", " " * 65537,
])
def test_invalid_or_noncompleted_meta_falls_back(session_row, tmp_path, content):
    """Invalid identity, status, structure or encoding cannot override liveness."""
    write_meta(tmp_path, content)
    formatting.enrich_workspace_rows([session_row], str(tmp_path))
    assert session_row["workspace_status"] == "running"


@pytest.mark.parametrize("other_pid", [None, 4321])
def test_missing_or_other_pid_file_falls_back(session_row, tmp_path, other_pid):
    """Never search for a latest metadata file belonging to another PID."""
    if other_pid is not None:
        write_meta(tmp_path, completed(pid=other_pid), other_pid)
    formatting.enrich_workspace_rows([session_row], str(tmp_path))
    assert session_row["workspace_status"] == "running"


def test_unreadable_meta_falls_back_with_diagnostic(session_row, tmp_path, monkeypatch, caplog):
    """Permission errors do not abort rendering and have a modest diagnostic."""
    monkeypatch.setattr(formatting, "open", Mock(side_effect=PermissionError("denied")), raising=False)
    formatting.enrich_workspace_rows([session_row], str(tmp_path))
    assert session_row["workspace_status"] == "running"
    assert "PermissionError" in caplog.text
    assert "denied" in caplog.text


def test_invalid_encoding_falls_back(session_row, tmp_path, caplog):
    """Malformed text is diagnosed without aborting the list."""
    write_meta(tmp_path, completed()).write_bytes(b"\xff")
    formatting.enrich_workspace_rows([session_row], str(tmp_path))
    assert session_row["workspace_status"] == "running"
    assert "UnicodeDecodeError" in caplog.text


def test_dead_process_is_not_revived(session_row, tmp_path):
    """A stale running record cannot override a failed process probe."""
    write_meta(tmp_path, completed(status="running"))
    formatting.os.kill.side_effect = ProcessLookupError()
    formatting.enrich_workspace_rows([session_row], str(tmp_path))
    assert session_row["workspace_status"] == "idle"
    assert session_row["workspace_pid"] is None


def test_input_remains_input(session_row, tmp_path):
    """Completion does not change the approved input-state boundary."""
    write_meta(tmp_path, completed())
    formatting.is_session_pipe_open.return_value = True
    formatting.enrich_workspace_rows([session_row], str(tmp_path))
    assert session_row["workspace_status"] == "input"


@pytest.mark.parametrize("changes", [
    {"filename": "sample.5678.child.task.stdout", "pid": 5678, "is_task": True},
    {"filename": "sample.1234.child.task.stdout", "is_task": True},
    {"filename": "sample.1234.stdout"},
    {"session_pid": 4321},
])
def test_task_generic_or_mismatched_row_not_overridden(session_row, tmp_path, changes):
    """Do not apply parent evidence to tasks or ambiguous log rows."""
    write_meta(tmp_path, completed())
    session_row.update(changes)
    formatting.enrich_workspace_rows([session_row], str(tmp_path))
    assert session_row["workspace_status"] == "running"


@pytest.mark.parametrize("session_id", [None, "../unsafe", "(temp)"])
def test_invalid_session_identity_falls_back(session_row, tmp_path, session_id):
    """Unsafe or temporary identities cannot authorize a metadata read."""
    session_row["session_id"] = session_id
    formatting.enrich_workspace_rows([session_row], str(tmp_path))
    assert session_row["workspace_status"] == "running"


def test_live_pid_mismatch_skips_driver_association(session_row, tmp_path):
    """A live row cannot claim driver association for a different source PID."""
    observation = object()
    session_driver.observe_driver.return_value = observation
    session_row.update(session_pid=4321, filename="sample.4321.session.stdout")
    formatting.enrich_workspace_rows([session_row], str(tmp_path))
    assert session_row["workspace_pid"] == 1234
    assert session_row["workspace_status"] == "running"
    assert session_row["driver_observation"] is None
    assert session_row["driver_display_observation"] is observation
    session_driver.observe_driver.assert_called_once_with(str(tmp_path), "sample")


def test_custom_driver_entry_is_forwarded_to_probe(session_row, tmp_path, monkeypatch):
    """Custom entry injection reaches the probe and preserves row observations."""
    driver_entry = str(tmp_path / "custom_driver.py")
    observation = object()
    probe = Mock(return_value="probe-result")
    monkeypatch.setattr(session_driver, "probe_driver_process", probe)
    session_driver.observe_driver.return_value = observation
    formatting.enrich_workspace_rows([session_row], str(tmp_path), driver_entry=driver_entry)
    session_driver.observe_driver.assert_called_once()
    args, kwargs = session_driver.observe_driver.call_args
    assert args == (str(tmp_path), "sample")
    assert set(kwargs) == {"process_probe"}
    assert kwargs["process_probe"](1234) == "probe-result"
    probe.assert_called_once_with(1234, driver_entry=driver_entry)
    assert session_row["workspace_status"] == "running"
    assert session_row["workspace_pid"] == 1234
    assert session_row["driver_observation"] is observation
    assert session_row["driver_display_observation"] is observation
