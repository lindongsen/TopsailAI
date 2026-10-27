"""Behavioral tests for the explicit workspace-agent session identity."""

import os
import sys
from unittest.mock import patch

import pytest

import topsailai_launch_agent as launcher


def test_invalid_session_id_rejected_before_context_or_driver(tmp_path, monkeypatch):
    """Invalid identity is rejected before context commands or drivers run."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["topsailai_launch_agent.py", "--session-id", "bad/id"])
    with patch.object(launcher, "_read_context_blocks", side_effect=AssertionError("context ran")) as context, \
         patch.object(launcher.subprocess, "run", side_effect=AssertionError("driver ran")) as driver, \
         pytest.raises(SystemExit) as error:
        launcher.main()
    assert error.value.code == 2
    context.assert_not_called()
    driver.assert_not_called()


def test_valid_session_id_is_used_for_both_identity_environment_names(tmp_path, monkeypatch, capsys):
    """A valid explicit identity overrides configured identity in dry-run output."""
    settings = tmp_path / ".topsailai"
    settings.mkdir()
    (settings / "settings.yaml").write_text(
        "ai_agent_driver: 'topsailai_agent_plan_tasks'\n"
        "context: {}\n"
        "environment:\n  _default:\n    TOPSAILAI_SESSION_ID: configured\n    SESSION_ID: configured\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["topsailai_launch_agent.py", "--session-id", "explicit-id", "--dry-run"])
    with patch.object(launcher, "_driver_exists", return_value=True):
        with pytest.raises(SystemExit) as error:
            launcher.main()
    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "TOPSAILAI_SESSION_ID=explicit-id" in output
    assert "SESSION_ID=explicit-id" in output


def test_valid_session_id_reaches_real_fake_driver_environment(tmp_path, monkeypatch):
    """A finite fake driver observes both identity variables in its child environment."""
    settings = tmp_path / ".topsailai"
    settings.mkdir()
    record = tmp_path / "driver-env.json"
    driver = tmp_path / "fake-driver.py"
    driver.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        "with open(os.environ['OUTPUT_FILE'], 'w', encoding='utf-8') as handle:\n"
        "    json.dump({'TOPSAILAI_SESSION_ID': os.environ.get('TOPSAILAI_SESSION_ID'), "
        "'SESSION_ID': os.environ.get('SESSION_ID')}, handle)\n",
        encoding="utf-8",
    )
    driver.chmod(0o700)
    (settings / "settings.yaml").write_text(
        "ai_agent_driver: %r\n" % str(driver)
        + "context: {}\n"
        + "environment:\n  _default:\n"
        + "    OUTPUT_FILE: %r\n" % str(record)
        + "    TOPSAILAI_SESSION_ID: configured\n"
        + "    SESSION_ID: configured\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "topsailai_launch_agent.py", "--session-id", "explicit-id", "--subprocess"
    ])
    with open(os.devnull, "r", encoding="utf-8") as stdin:
        monkeypatch.setattr(launcher.sys, "stdin", stdin)
        with pytest.raises(SystemExit) as error:
            launcher.main()
    assert error.value.code == 0
    assert record.read_text(encoding="utf-8") == (
        '{"TOPSAILAI_SESSION_ID": "explicit-id", "SESSION_ID": "explicit-id"}'
    )
