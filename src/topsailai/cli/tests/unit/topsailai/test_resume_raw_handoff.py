"""U1: real raw workspace resume identity and normal detachment."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import cli_topsailai.agent_launch_background as background
from resume_raw_handoff_helpers import Custody, identity_from_frame, launch

pytest_plugins = ["resume_raw_handoff_fixture"]


def _heartbeat(path):
    """Read the integer heartbeat, treating pre-first-write as zero."""
    try:
        return int(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return 0


def _proc_identity(pid: int) -> tuple[int, str, int, str]:
    """Read PID, state, start token and parent PID independently from procfs."""
    raw = open(f"/proc/{pid}/stat", encoding="utf-8").read()
    rest = raw[raw.rindex(")") + 2 :].split()
    return pid, rest[0], int(rest[19]), int(rest[1])


def test_submitted_identity_and_detach(raw_custody):
    """The public resume route submits a live driver and then detaches."""
    session = "c2-u1-session"
    result = launch(raw_custody, session)
    telemetry = raw_custody.wait_for(raw_custody.telemetry)
    started = [frame for frame in raw_custody.observed_frames if frame.get("kind") == "started"]
    assert result == 0
    assert len(started) == 1
    pid, token, source = identity_from_frame(started[0])
    proc_pid, state, proc_token, parent = _proc_identity(pid)
    assert source == "authoritative"
    assert state != "Z"
    assert proc_pid == pid and proc_token == token
    assert (int(telemetry["pid"]), int(telemetry["token"])) in raw_custody.drivers
    assert raw_custody.live(int(telemetry["pid"]), int(telemetry["token"]))
    assert telemetry["pid"] == pid
    assert telemetry["token"] == token
    assert telemetry["session"] == telemetry["top_session"] == session
    assert telemetry["cwd"] == str(raw_custody.workspace)
    assert telemetry["parent"] == parent
    assert telemetry["parent"] in {child.pid for child in raw_custody.supervisors}
    assert os.readlink(f"/proc/{pid}/cwd") == str(raw_custody.workspace)
    assert telemetry["model"] == "c2-model"

    before = _heartbeat(raw_custody.heartbeat)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and _heartbeat(raw_custody.heartbeat) <= before:
        time.sleep(0.02)
    assert _heartbeat(raw_custody.heartbeat) > before
    assert raw_custody.return_state is not None
    assert raw_custody.return_state["cwd"] == raw_custody.return_state["expected_cwd"]
    assert raw_custody.return_state["environment"] == raw_custody.return_state["expected_environment"]

    raw_custody.release_child()
    raw_custody.finish()
    report = json.loads((raw_custody.root / "custody-report.json").read_text(encoding="utf-8"))
    assert any(event.startswith("registered supervisor") for event in report["events"])
    assert any(event.startswith("registered driver") for event in report["events"])
    assert any(event.startswith("reaped supervisor") for event in report["events"])
    assert "verified driver kernel absence" in report["events"]


def test_exception_telemetry_registers_driver_and_rejects_vacuous_absence(
    raw_custody, monkeypatch
):
    """The real launch wrapper recovers telemetry when its reader fails once."""
    real_read = background._read_frames
    injection = {"fired": False, "disarmed": False}

    def fail_once_after_telemetry(fd, buffer):
        """Raise once after real driver telemetry is observable, then delegate."""
        if not injection["fired"]:
            raw_custody.wait_for(raw_custody.telemetry)
            injection["fired"] = True
            injection["disarmed"] = True
            raw_custody.events.append("injected one-shot reader failure")
            raise ValueError("injected reader failure")
        return real_read(fd, buffer)

    monkeypatch.setattr(background, "_read_frames", fail_once_after_telemetry)
    result = launch(raw_custody, "c2-u1-exception")
    telemetry = raw_custody.wait_for(raw_custody.telemetry)
    identity = (int(telemetry["pid"]), int(telemetry["token"]))

    assert injection == {"fired": True, "disarmed": True}
    assert result in {5, 6}
    assert identity in raw_custody.drivers
    assert any(
        event == "registered driver from telemetry fallback"
        for event in raw_custody.events
    )
    assert "verified driver kernel absence" not in raw_custody.events
    assert raw_custody.release.exists() is False
    raw_custody.release_child()
    raw_custody.finish()
    report = json.loads(
        (raw_custody.root / "custody-report.json").read_text(encoding="utf-8")
    )
    assert identity in [tuple(driver) for driver in report["drivers"]]
    assert "verified driver kernel absence" in report["events"]

def test_process_state_unknown_and_reconfirmation_signal_gate():
    """A real process proves alive; replacement, absence, and read failure never signal."""
    def denied(_pid):
        raise PermissionError("injected proc read failure")

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    pid = child.pid
    try:
        token = Custody.identity_token(pid)
        assert token is not None
        read_real_stat = lambda value: Path(f"/proc/{value}/stat").read_text(encoding="utf-8")
        calls: list[int] = []
        Custody.signal_if_alive(pid, token, read_real_stat, calls.append)
        assert calls == [pid]
        alive_calls = list(calls)

        calls.clear()
        Custody.signal_if_alive(pid, token + 1, read_real_stat, calls.append)
        replaced_calls = list(calls)
        assert Custody.process_state(pid, token + 1, read_real_stat) == "replaced"

        absent_pid = pid + 1000000
        calls.clear()
        Custody.signal_if_alive(absent_pid, token, read_real_stat, calls.append)
        absent_calls = list(calls)
        assert Custody.process_state(absent_pid, token, read_real_stat) == "absent"

        calls.clear()
        Custody.signal_if_alive(pid, token, denied, calls.append)
        unknown_calls = list(calls)
        assert Custody.process_state(pid, token, denied) == "unknown"

        assert alive_calls == [pid]
        assert replaced_calls == []
        assert absent_calls == []
        assert unknown_calls == []
    finally:
        os.kill(pid, signal.SIGTERM)
        print(f"exact-PID cleanup kill pid={pid}")
        child.wait(timeout=5)
        assert Custody.process_state(pid, token, read_real_stat) == "absent"



def test_cancel_owned_before_submit(raw_custody):
    """Cancel exactly once after verified ownership and before submission."""
    session = "c2-u2-cancel"
    callback_calls = []
    trigger_evidence = {}
    submitted_gate = {"triggered": False, "bound": 256}

    def cancel_requested():
        """Trigger cancellation through a finite, non-consuming submitted gate."""
        callback_calls.append("called")
        assert len(callback_calls) <= submitted_gate["bound"]
        started = [
            frame for frame in raw_custody.observed_frames
            if frame.get("kind") == "started"
        ]
        assert not any(frame.get("kind") == "submitted" for frame in raw_custody.frames)
        if not started or trigger_evidence:
            return False
        telemetry = raw_custody.wait_for(raw_custody.telemetry)
        assert len(started) == 1
        pid, token, source = identity_from_frame(started[0])
        assert source == "authoritative"
        assert raw_custody.ownership is not None
        assert raw_custody.ownership.identity == started[0]["launcher_identity"]
        assert raw_custody.live(pid, token)
        assert (pid, token) in raw_custody.drivers
        proc_pid, state, proc_token, parent = _proc_identity(pid)
        assert proc_pid == pid
        assert state != "Z"
        assert proc_token == token
        assert telemetry["session"] == telemetry["top_session"] == session
        assert int(telemetry["pid"]) == pid
        assert int(telemetry["token"]) == token
        assert int(telemetry["parent"]) == parent
        assert parent in {child.pid for child in raw_custody.supervisors}
        assert telemetry["cwd"] == str(raw_custody.workspace)
        assert telemetry["mutation"] is None
        assert telemetry["marker"] is None
        assert os.readlink(f"/proc/{pid}/cwd") == str(raw_custody.workspace)
        trigger_evidence.update(
            pid=pid, token=token, source=source,
            telemetry_pid=int(telemetry["pid"]),
            telemetry_token=int(telemetry["token"]), parent=parent,
            cwd=telemetry["cwd"],
        )
        raw_custody.events.append("triggered owned cancellation before submitted")
        submitted_gate["triggered"] = True
        return True

    result = launch(
        raw_custody, session, cancel_requested=cancel_requested,
        submitted_gate=submitted_gate,
    )
    assert result == 130
    assert callback_calls
    assert len(callback_calls) <= submitted_gate["bound"]
    assert submitted_gate["triggered"] is True
    assert trigger_evidence["pid"] == trigger_evidence["telemetry_pid"]
    assert trigger_evidence["token"] == trigger_evidence["telemetry_token"]
    assert not any(frame.get("kind") == "submitted" for frame in raw_custody.frames)
    cleanup = [frame for frame in raw_custody.frames if frame.get("kind") == "cleanup"]
    assert len(cleanup) == 1
    assert cleanup[0]["class"] == "cancellation"
    assert cleanup[0]["cleanup_confirmed"] is True
    assert cleanup[0]["session"] == session
    assert cleanup[0]["launcher_pid"] == trigger_evidence["pid"]
    assert cleanup[0]["launcher_identity"] == repr(
        (trigger_evidence["pid"], trigger_evidence["token"], trigger_evidence["source"])
    )
    marker = raw_custody.root / "u2-hook-marker.log"
    if os.environ.get("C2_U2_MUTATION") == "disable-owned-cleanup":
        records = [json.loads(line) for line in marker.read_text(encoding="utf-8").splitlines()]
        assert records[0]["event"] == "supervisor_environment"
        assert records[0]["mutation"] == "disable-owned-cleanup"
        assert records[0]["marker"] == str(marker)
        invocations = [record for record in records if record["event"] == "invocation"]
        assert len(invocations) == 1
        assert invocations[0]["pid"] == trigger_evidence["pid"]
        assert invocations[0]["token"] == trigger_evidence["token"]
        assert invocations[0]["boundary"]
        assert invocations[0]["boundary"] != "supervisor_exception_cleanup"
    assert raw_custody.absent(*raw_custody.drivers[0])
    assert raw_custody.supervisors[0].poll() is not None
    assert raw_custody.return_state is not None
    assert raw_custody.return_state["cwd"] == raw_custody.return_state["expected_cwd"]
    assert raw_custody.return_state["environment"] == raw_custody.return_state["expected_environment"]
    raw_custody.release_child()
    raw_custody.finish()
