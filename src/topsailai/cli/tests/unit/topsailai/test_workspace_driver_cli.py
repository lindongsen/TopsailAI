"""Author: DawsonLin. Verify finite driver dispatch without real spawning."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from cli_topsailai import core, workspace_driver_cli as cli
from cli_topsailai.session_driver import DriverMetadata, DriverObservation, ProcessEvidence
from cli_topsailai.session_driver_launcher import DriverAuthority, LaunchResult


def row(pid=123, **extra):
    """Build authoritative discovery evidence."""
    return dict(session_id="fixture", pid=pid, session_pid=pid,
                filename=f"fixture.{pid}.session.stdout", is_task=False, **extra)


@pytest.fixture
def dependencies(monkeypatch, tmp_path):
    """Isolate authority, discovery and process probes from host state."""
    authority = DriverAuthority(tmp_path / "entry", None)
    monkeypatch.setattr(cli, "resolve_driver_authority", Mock(return_value=authority))
    monkeypatch.setattr(cli, "discover_log_files", Mock(return_value=[row()]))
    monkeypatch.setattr(cli, "_target_alive", Mock(return_value=True))
    monkeypatch.setattr(cli, "launch_driver", Mock(return_value=LaunchResult("launched", "publication_verified")))
    observation = DriverObservation("ON", "verified", DriverMetadata(1, "fixture", 456, "run", "running"), ProcessEvidence.VERIFIED)

    def enrich(rows, home, **kwargs):
        """Attach evidence without consulting host processes."""
        for item in rows:
            item["driver_observation"] = observation

    monkeypatch.setattr(cli, "enrich_workspace_rows", Mock(side_effect=enrich))
    from cli_topsailai.session_driver_stopper import StopResult
    monkeypatch.setattr(cli, "stop_driver", Mock(return_value=StopResult("stopped", "original_process_absent", observation)))
    return tmp_path, observation


def invoke(dependencies, argv):
    """Provide explicit home and environment at the CLI boundary."""
    return cli.run_workspace_driver_cli(argv, home_resolver=lambda: str(dependencies[0]), environment={"KEEP": "value"})


@pytest.mark.parametrize("outcome,code", [("launched", 0), ("already_running", 0), ("rejected", 4), ("failed", 5), ("unconfirmed", 6)])
def test_launch_outcomes(dependencies, capsys, outcome, code):
    """Preserve publication and uncertain-delivery distinctions."""
    cli.launch_driver.return_value = LaunchResult(outcome, "reason", dependencies[1])
    assert invoke(dependencies, ["start", "-s", "fixture", "-p", "123", "--json"]) == code
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] == (code == 0)
    assert data["delivery_unknown"] == (code == 6)
    assert data["response"]["state"] == "ON"
    assert data["response"]["driver_pid"] == 456
    kwargs = cli.launch_driver.call_args.kwargs
    assert kwargs["environment"] == {"KEEP": "value"}
    assert kwargs["discover"]() == [row()]


@pytest.mark.parametrize("argv", [[], ["start"], ["bad", "-s", "fixture"], ["start", "-s", "../bad"], ["start", "-s", "topsailai"], ["start", "-s", "fixture", "-p", "0"], ["start", "-s", "fixture", "-p", "bad"], ["start", "-s", "fixture", "-s", "other"], ["start", "-s", "fixture", "--unknown"]])
def test_invalid_arguments(dependencies, capsys, argv):
    """Syntax failures produce one JSON result before discovery or spawning."""
    assert invoke(dependencies, argv + ["--json"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["error_code"] == "usage_error"
    cli.discover_log_files.assert_not_called()
    cli.launch_driver.assert_not_called()


@pytest.mark.parametrize("rows,pid", [([], None), ([dict(row(), is_task=True)], None), ([dict(row(), filename="fixture.123.stdout")], None), ([row(), row(124)], 123), ([row()], 124)])
def test_target_rejections(dependencies, capsys, rows, pid):
    """Missing, task, legacy, mismatched and ambiguous targets never spawn."""
    cli.discover_log_files.return_value = rows
    argv = ["start", "-s", "fixture", "--json"]
    if pid:
        argv += ["-p", str(pid)]
    assert invoke(dependencies, argv) == 3
    assert json.loads(capsys.readouterr().out)["exit_code"] == 3
    cli.launch_driver.assert_not_called()


def test_idle_start_rejected(dependencies):
    """Non RUN/INPUT sessions cannot start a driver."""
    cli._target_alive.return_value = False
    assert invoke(dependencies, ["start", "-s", "fixture"]) == 3
    cli.launch_driver.assert_not_called()


def test_status_offline(dependencies, capsys):
    """Status reads semantic state for exact exited authoritative rows."""
    cli._target_alive.return_value = False
    assert invoke(dependencies, ["status", "-s", "fixture", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["delivery_state"] == "status_read"
    assert data["response"]["verification"] == "verified"
    cli.launch_driver.assert_not_called()


@pytest.mark.parametrize("state,code", [("-", 0), ("STALE", 0), ("EXIT", 0), ("FAIL", 0), ("?", 4)])
def test_status_states(dependencies, capsys, state, code):
    """Unknown observations fail closed; known lifecycle states are query success."""
    def enrich(rows, *args, **kwargs):
        """Inject one semantic state."""
        rows[0]["driver_observation"] = DriverObservation(state, "evidence")
    cli.enrich_workspace_rows.side_effect = enrich
    assert invoke(dependencies, ["status", "-s", "fixture", "--json"]) == code
    assert json.loads(capsys.readouterr().out)["response"]["state"] == state


def test_status_changed(dependencies):
    """Fresh discovery cannot replace the selected identity."""
    cli.discover_log_files.side_effect = [[row()], [row(124)]]
    assert invoke(dependencies, ["status", "-s", "fixture"]) == 3


def test_status_ineligible(dependencies):
    """A missing shared observation is not status success."""
    cli.enrich_workspace_rows.side_effect = None
    assert invoke(dependencies, ["status", "-s", "fixture"]) == 3


def test_historical_ambiguity(dependencies):
    """Multiple historical rows require explicit PID even when none is live."""
    cli.discover_log_files.return_value = [row(), row(124)]
    cli._target_alive.return_value = False
    assert invoke(dependencies, ["status", "-s", "fixture"]) == 3
    assert invoke(dependencies, ["status", "-s", "fixture", "-p", "123"]) == 0


@pytest.mark.parametrize("target,error", [("resolve_driver_authority", ValueError("invalid")), ("discover_log_files", PermissionError("denied"))])
def test_configuration_or_inspection_failure(dependencies, capsys, target, error):
    """Configuration and OS failures have bounded public diagnostics."""
    getattr(cli, target).side_effect = error
    assert invoke(dependencies, ["start", "-s", "fixture", "--json"]) == 4
    assert json.loads(capsys.readouterr().out)["error_code"] == "configuration_or_inspection_failed"
    cli.launch_driver.assert_not_called()


def test_plain_output(dependencies, capsys):
    """Plain success goes to stdout; failures to stderr."""
    assert invoke(dependencies, ["start", "-s", "fixture"]) == 0
    assert "Driver start: launched" in capsys.readouterr().out
    assert invoke(dependencies, ["start"]) == 2
    assert "usage_error" in capsys.readouterr().err


@pytest.mark.parametrize("action", ["start", "status", "stop"])
def test_early_dispatch_and_help(dependencies, monkeypatch, action):
    """New subcommands bypass interactive setup and help probes nothing."""
    detect = Mock()
    monkeypatch.setattr(core, "_detect_agent_mode", detect)
    with pytest.raises(SystemExit) as result:
        core.main(["workspace", "driver", "--help"])
    assert result.value.code == 0
    detect.assert_not_called()
    cli.resolve_driver_authority.assert_not_called()
    runner = Mock(return_value=0)
    monkeypatch.setattr(cli, "run_workspace_driver_cli", runner)
    with pytest.raises(SystemExit) as result:
        core.main(["workspace", "driver", action, "-s", "fixture"])
    assert result.value.code == 0
    runner.assert_called_once_with([action, "-s", "fixture"])


def test_real_launcher_idle_revalidation(dependencies, monkeypatch):
    """The real launcher still refuses stale targets after initial selection."""
    from cli_topsailai import session_driver_launcher as launcher
    from functools import partial
    monkeypatch.setattr(cli, "launch_driver", partial(launcher.launch_driver, target_probe=lambda pid: False))
    monkeypatch.setattr(launcher.DriverAuthority, "validate", lambda self: None)
    assert invoke(dependencies, ["start", "-s", "fixture", "--json"]) == 4


@pytest.mark.parametrize("outcome,code", [("stopped", 0), ("already_stopped", 0),
                                         ("rejected", 4), ("failed", 5), ("unconfirmed", 6)])
def test_stop_outcomes(dependencies, capsys, outcome, code):
    """Keep session selector separate from the metadata driver PID and uncertainty."""
    from cli_topsailai.session_driver_stopper import StopResult
    cli.stop_driver.return_value = StopResult(outcome, "reason", dependencies[1])
    assert invoke(dependencies, ["stop", "-s", "fixture", "-p", "123", "--json"]) == code
    data = json.loads(capsys.readouterr().out)
    assert data["action"] == "stop" and data["pid"] == 123
    assert data["response"]["driver_pid"] == 456
    assert data["delivery_state"] == outcome
    assert data["ok"] == (code == 0)
    assert data["error_code"] == (None if code == 0 else "reason")
    assert data["delivery_unknown"] == (code == 6)
    assert data["bytes_written"] is None and data["request_id"] is None
    assert cli.stop_driver.call_args.args == ([row()], 1)
    assert cli.stop_driver.call_args.kwargs["discover"]() == [row()]
    cli.launch_driver.assert_not_called()


@pytest.mark.parametrize("argv,code", [(["stop"], 2),
    (["stop", "-s", "fixture", "-p", "0"], 2),
    (["stop", "-s", "fixture", "-p", "456"], 3),
    (["stop", "-s", "fixture", "-s", "other"], 2)])
def test_stop_invalid_selection(dependencies, capsys, argv, code):
    """Never authorize a stop from invalid arguments or a driver-PID selector."""
    assert invoke(dependencies, argv + ["--json"]) == code
    assert json.loads(capsys.readouterr().out)["exit_code"] == code
    cli.stop_driver.assert_not_called()


def test_stop_idle_and_ambiguous(dependencies):
    """Permit explicit historical selection but never choose newest or broadcast."""
    cli._target_alive.return_value = False
    cli.discover_log_files.return_value = [row(), row(124)]
    assert invoke(dependencies, ["stop", "-s", "fixture"]) == 3
    cli.stop_driver.assert_not_called()
    assert invoke(dependencies, ["stop", "-s", "fixture", "-p", "123"]) == 0
    cli.stop_driver.reset_mock()
    cli._target_alive.return_value = True
    assert invoke(dependencies, ["stop", "-s", "fixture", "-p", "123"]) == 3
    cli.stop_driver.assert_not_called()


def test_stop_plain_and_offline_help(dependencies, capsys):
    """Offline help never signals, and plain streams reflect definite failure."""
    from cli_topsailai.session_driver_stopper import StopResult
    with pytest.raises(SystemExit) as result:
        invoke(dependencies, ["stop", "--help"])
    assert result.value.code == 0
    assert "stop" in capsys.readouterr().out
    cli.discover_log_files.assert_not_called()
    cli.stop_driver.assert_not_called()
    assert invoke(dependencies, ["stop", "-s", "fixture"]) == 0
    assert "Driver stop: stopped" in capsys.readouterr().out
    cli.stop_driver.return_value = StopResult("failed", "AccessDenied")
    assert invoke(dependencies, ["stop", "-s", "fixture"]) == 5
    assert "AccessDenied" in capsys.readouterr().err
