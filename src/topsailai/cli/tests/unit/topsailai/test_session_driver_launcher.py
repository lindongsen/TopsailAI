"""Author: DawsonLin.

Execution checklist (before running): authority and row rejection; fresh target
revalidation; explicit argv/environment and detached DEVNULL; preflight states;
fresh publication, competing owner, exit and deadline; immutable driver records.
All spawning and process inspection use doubles; never run the external driver.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import subprocess
import sys

import psutil
import pytest

from cli_topsailai import session_driver_launcher as launcher
from cli_topsailai.session_driver import DriverMetadata, DriverObservation, ProcessEvidence


def observation(state="-", pid=900, run="new", reason="evidence"):
    """Create validated immutable observation doubles."""
    metadata = None if state == "-" else DriverMetadata(1, "session", pid, run, "running")
    evidence = ProcessEvidence.VERIFIED if state == "ON" else ProcessEvidence.UNKNOWN
    return DriverObservation(state, reason, metadata, evidence)


@pytest.fixture
def setup(tmp_path):
    """Supply explicit temporary installation authority and harmless child doubles."""
    entry = tmp_path / "installed driver"
    entry.write_text("unused fixture entry")
    interpreter = tmp_path / "python fixture"
    interpreter.write_text("unused fixture interpreter")
    interpreter.chmod(0o700)
    row = {"session_id": "session", "pid": 123, "session_pid": 123,
           "filename": "session.123.session.stdout", "is_task": False}
    child = Mock(pid=900)
    child.poll.return_value = None
    clock_value = [0.0]

    def sleep(delay):
        """Advance deterministic deadline without real waiting."""
        clock_value[0] += delay

    return SimpleNamespace(
        rows=[row], home=tmp_path, entry=entry, interpreter=interpreter,
        authority=launcher.DriverAuthority(entry, interpreter),
        discover=Mock(return_value=[dict(row)]), probe=Mock(return_value=True),
        observer=Mock(side_effect=[observation(), observation("ON")]),
        spawn=Mock(return_value=child), child=child,
        clock=lambda: clock_value[0], sleep=sleep,
    )


def launch(setup, **overrides):
    """Call the public service through explicit isolated dependencies."""
    kwargs = dict(topsailai_home=setup.home, authority=setup.authority,
                  environment={"KEEP": "value", "TOPSAILAI_HOME": "wrong"},
                  discover=setup.discover, target_probe=setup.probe,
                  observer=setup.observer, spawn=setup.spawn,
                  clock=setup.clock, sleep=setup.sleep, timeout=0.3, interval=0.1)
    kwargs.update(overrides)
    return launcher.launch_driver(setup.rows, 1, **kwargs)


def test_launch_success_read_only(setup):
    """Fresh child publication proves launch without changing any owner artifact."""
    directory = setup.home / "workspace" / "task" / "session_agent_driver"
    directory.mkdir(parents=True)
    paths = [directory / ("session." + suffix) for suffix in ("meta", "lock", "log")]
    for path in paths:
        path.write_text("driver owned evidence")
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    result = launch(setup)
    assert result.outcome == "launched"
    assert result.child is setup.child
    setup.child.wait.assert_not_called()
    argv, = setup.spawn.call_args.args
    assert argv == [str(setup.interpreter), str(setup.entry), "--session", "session"]
    kwargs = setup.spawn.call_args.kwargs
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == str(setup.home)
    assert kwargs["env"] == {"KEEP": "value", "TOPSAILAI_HOME": str(setup.home)}
    assert all(kwargs[name] == subprocess.DEVNULL for name in ("stdin", "stdout", "stderr"))
    if sys.platform != "win32":
        assert kwargs["start_new_session"] is True
    probe = setup.observer.call_args.kwargs["process_probe"]
    assert probe.keywords["driver_entry"] == setup.entry
    assert setup.discover.call_count == 2
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths] == before


@pytest.mark.parametrize("authority", [None, launcher.DriverAuthority(Path("relative"), Path("python"))])
def test_unavailable_authority(setup, authority):
    """Unavailable entry authority rejects without inspecting target processes."""
    assert launch(setup, authority=authority).outcome == "rejected"
    setup.probe.assert_not_called()
    setup.spawn.assert_not_called()


@pytest.mark.parametrize("change", [
    {"pid": "123"}, {"pid": True}, {"pid": 0}, {"pid": -1},
    {"session_pid": True}, {"session_pid": 456}, {"is_task": True},
    {"session_id": "topsailai"}, {"session_id": "../bad"},
    {"filename": "session.123.stdout"},
])
def test_invalid_selected_row(setup, change):
    """Malformed or nonauthoritative selections never reach process probes."""
    setup.rows[0].update(change)
    assert launch(setup).outcome == "rejected"
    setup.probe.assert_not_called()
    setup.spawn.assert_not_called()


@pytest.mark.parametrize("index", [True, 0, -1, 2, "1"])
def test_invalid_index(setup, index):
    """Row selection accepts only in-range one-based integer indices."""
    result = launcher.launch_driver(setup.rows, index, topsailai_home=setup.home,
                                   authority=setup.authority, environment={}, discover=setup.discover)
    assert result.reason == "invalid_row_index"


@pytest.mark.parametrize("bounds", [{"timeout": 0}, {"interval": -1}, {"timeout": float("inf")},
                                   {"interval": True}, {"timeout": "bad"}])
def test_invalid_bounds(setup, bounds):
    """Invalid confirmation controls cannot create a resident child."""
    assert launch(setup, **bounds).outcome == "rejected"
    setup.spawn.assert_not_called()


def test_dead_target(setup):
    """A displayed RUN snapshot is not trusted when the target has exited."""
    setup.rows[0]["workspace_status"] = "running"
    setup.probe.return_value = False
    assert launch(setup).reason == "target_not_current"
    setup.spawn.assert_not_called()


def test_changed_after_preflight(setup):
    """Fresh discovery is repeated after metadata observation before spawning."""
    setup.discover.side_effect = [[dict(setup.rows[0])], []]
    setup.observer.side_effect = [observation()]
    assert launch(setup).reason == "target_not_current"
    setup.spawn.assert_not_called()


def test_ambiguous_target(setup):
    """Multiple live PIDs for one identity block launch."""
    other = dict(setup.rows[0], pid=456, session_pid=456, filename="session.456.session.stdout")
    setup.discover.return_value.append(other)
    assert launch(setup).reason == "ambiguous_session"
    setup.spawn.assert_not_called()


def test_nonmatching_fresh_row(setup):
    """Legacy fresh identities cannot acknowledge the selected session row."""
    setup.discover.return_value[0]["filename"] = "session.123.stdout"
    assert launch(setup).outcome == "rejected"


def test_fresh_noise(setup):
    """Unrelated, task, non-dictionary and malformed PID rows do not authorize targets."""
    setup.discover.return_value.extend([None, {}, {"session_id": "session", "is_task": True},
                                       {"session_id": "session", "pid": True}])
    assert launch(setup).outcome == "launched"


@pytest.mark.parametrize("state,expected", [("ON", "already_running"), ("?", "rejected"),
                                            ("EXIT", "rejected"), ("FAIL", "rejected")])
def test_preflight_blocks(setup, state, expected):
    """Only absence or stale metadata admits spawn; verified ownership is reused."""
    setup.observer.side_effect = [observation(state)]
    assert launch(setup).outcome == expected
    setup.spawn.assert_not_called()


def test_stale_admission(setup):
    """The external driver, not CLI, owns stale-record recovery."""
    setup.observer.side_effect = [observation("STALE", run="old"), observation("ON")]
    assert launch(setup).outcome == "launched"


def test_spawn_error(setup):
    """Process creation failure returns failure rather than publication success."""
    setup.observer.side_effect = [observation()]
    setup.spawn.side_effect = OSError("spawn denied")
    result = launch(setup)
    assert result.outcome == "failed"
    assert result.reason == "OSError"


@pytest.mark.parametrize("state", ["-", "?", "STALE", "ON"])
def test_timeout_without_matching_owner(setup, state):
    """Missing, unverifiable, stale or competing publication is not child success."""
    setup.observer.side_effect = [observation()] + [observation(state, pid=901)] * 10
    result = launch(setup)
    assert result.outcome == "unconfirmed"
    assert result.child is setup.child
    setup.child.wait.assert_not_called()
    setup.child.kill.assert_not_called()
    setup.child.terminate.assert_not_called()


def test_old_run_not_acknowledged(setup):
    """A reused PID/run snapshot cannot confirm this newly spawned child."""
    setup.observer.side_effect = [observation("STALE", run="old")] + [observation("ON", run="old")] * 10
    assert launch(setup).outcome == "unconfirmed"


@pytest.mark.parametrize("owner,expected", [(900, "failed"), (901, "already_running")])
def test_exited_child(setup, owner, expected):
    """Reap exited children and accept another verified owner, not exit codes alone."""
    setup.child.poll.return_value = 7
    setup.observer.side_effect = [observation(), observation("ON", pid=owner)]
    result = launch(setup)
    assert result.outcome == expected
    assert result.exit_code == 7
    setup.child.wait.assert_called_once()
    assert result.child is None


def test_exit_without_owner(setup):
    """A zero exit code without running metadata does not prove launch."""
    setup.child.poll.return_value = 0
    setup.observer.side_effect = [observation(), observation()]
    assert launch(setup).outcome == "failed"


def test_exit_during_observation(setup):
    """Do not acknowledge a child that exited during fallible metadata reading."""
    setup.child.poll.side_effect = [None, 0]
    assert launch(setup).outcome == "failed"


def test_late_publication(setup):
    """Evidence received after the absolute deadline remains unconfirmed."""
    calls = [0]

    def observe(*args, **kwargs):
        """Make the confirmation observation consume the entire budget."""
        calls[0] += 1
        if calls[0] == 1:
            return observation()
        setup.sleep(1)
        return observation("ON")

    assert launch(setup, observer=observe).outcome == "unconfirmed"


@pytest.mark.parametrize("environment", [{"bad": 1}, {1: "bad"}])
def test_bad_environment(setup, environment):
    """Environment conversion is explicit and rejected before spawn."""
    assert launch(setup, environment=environment).reason == "invalid_environment"
    setup.spawn.assert_not_called()


def test_bad_interpreter(setup):
    """Do not relaunch a packaged application as a Python interpreter."""
    executable = setup.home / "application"
    executable.write_text("fixture")
    executable.chmod(0o700)
    assert launch(setup, authority=launcher.DriverAuthority(setup.entry, executable)).reason == "interpreter_unavailable"


@pytest.mark.parametrize("condition", ["dead", "zombie", "reused", "denied", "live"])
def test_target_process_evidence(monkeypatch, condition):
    """Stable liveness distinguishes RUN/INPUT from idle or inaccessible targets."""
    process = Mock()
    process.create_time.side_effect = [1, 2 if condition == "reused" else 1]
    process.is_running.return_value = condition != "dead"
    process.status.return_value = psutil.STATUS_ZOMBIE if condition == "zombie" else psutil.STATUS_RUNNING
    if condition == "denied":
        monkeypatch.setattr(launcher.psutil, "Process", Mock(side_effect=psutil.AccessDenied(123)))
    else:
        monkeypatch.setattr(launcher.psutil, "Process", Mock(return_value=process))
    assert launcher._target_alive(123) is (condition == "live")


def test_windows_detachment(setup, monkeypatch):
    """Use platform detachment without registering a terminate-on-exit child."""
    monkeypatch.setattr(launcher, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(launcher.subprocess, "DETACHED_PROCESS", 8, raising=False)
    monkeypatch.setattr(launcher.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
    assert launch(setup).outcome == "launched"
    assert setup.spawn.call_args.kwargs["creationflags"] == 520
    assert "start_new_session" not in setup.spawn.call_args.kwargs


def test_unreadable_entry(setup, monkeypatch):
    """Reject unreadable installation files without trying to spawn."""
    monkeypatch.setattr(launcher, "os", SimpleNamespace(X_OK=1, R_OK=4,
                        access=lambda path, mode: mode != 4))
    assert launch(setup).reason == "entry_unreadable"
    setup.spawn.assert_not_called()


def test_non_dict_selected_row(setup):
    """Malformed selected containers cannot be normalized into valid rows."""
    setup.rows[0] = None
    assert launch(setup).reason == "invalid_row"


def test_unverified_on_does_not_acknowledge(setup):
    """The ON label alone cannot bypass process verification."""
    unverified = DriverObservation("ON", "unverified", observation("ON").metadata)
    setup.observer.side_effect = [observation()] + [unverified] * 10
    assert launch(setup).outcome == "unconfirmed"


def test_compiled_launch(setup):
    """A validated compiled entry is launched without any interpreter argv."""
    setup.entry.chmod(0o700)
    result = launch(setup, authority=launcher.DriverAuthority(setup.entry, None))
    assert result.outcome == "launched"
    assert setup.spawn.call_args.args[0] == [str(setup.entry), "--session", "session"]


def test_compiled_launch_permission_rejection(setup):
    """A compiled entry without execute permission cannot launch."""
    setup.entry.chmod(0o600)
    assert launch(setup, authority=launcher.DriverAuthority(setup.entry, None)).reason == "entry_not_executable"
    setup.spawn.assert_not_called()
