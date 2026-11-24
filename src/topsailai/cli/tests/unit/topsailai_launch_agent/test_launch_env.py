"""Tests for the launcher's caller-supplied ``--env`` overrides.

Author: DawsonLin
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

import topsailai_launch_agent as launcher

ENV_HEADER = "Environment variables (merged from base, item and caller):"


def _write_settings(tmp_path, driver, base_env=None, item_env=None):
    """Write a minimal settings.yaml with base and item environment sections."""
    settings = tmp_path / ".topsailai"
    settings.mkdir(exist_ok=True)
    base = {"BASE_ONLY": "base"}
    base.update(base_env or {})
    item = {"ITEM_ONLY": "item"}
    item.update(item_env or {})
    lines = [
        f"ai_agent_driver: {driver!r}",
        "context:",
        "  _default: []",
        "  default: []",
        "environment:",
        "  _default:",
    ]
    for name, value in base.items():
        lines.append(f"    {name}: {value!r}")
    lines.append("  default:")
    for name, value in item.items():
        lines.append(f"    {name}: {value!r}")
    (settings / "settings.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_dry_run(tmp_path, monkeypatch, capsys, extra_argv):
    """Run the launcher in dry-run mode and return its stdout."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["topsailai_launch_agent.py", "--dry-run", *extra_argv]
    )
    with patch.object(launcher, "_driver_exists", return_value=True):
        with pytest.raises(SystemExit) as error:
            launcher.main()
    assert error.value.code == 0
    return capsys.readouterr().out


def _env_section(output):
    """Return only the dry-run environment section."""
    start = output.find(ENV_HEADER)
    assert start != -1, output
    return output[start:]


def test_env_option_is_listed_in_the_environment_section(tmp_path, monkeypatch, capsys):
    """A caller-supplied name appears in the merged environment preview."""
    _write_settings(tmp_path, "settings-driver")
    output = _run_dry_run(
        tmp_path, monkeypatch, capsys, ["--env", "CALLER_ONLY=caller"]
    )
    assert "CALLER_ONLY=" in _env_section(output)


def test_env_option_value_is_redacted_in_the_preview(tmp_path, monkeypatch, capsys):
    """The preview names the variable without disclosing its value."""
    _write_settings(tmp_path, "settings-driver")
    output = _run_dry_run(
        tmp_path, monkeypatch, capsys, ["--env", "SECRET_TOKEN=s3cr3t-value"]
    )
    section = _env_section(output)
    assert "SECRET_TOKEN=<configured>" in section
    assert "s3cr3t-value" not in output


def test_env_option_outranks_base_and_item_in_the_child(tmp_path, monkeypatch):
    """A caller value wins over both settings.yaml sections in the real child."""
    record = tmp_path / "child-env.json"
    driver = tmp_path / "fake-driver.py"
    driver.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        "with open(os.environ['OUTPUT_FILE'], 'w', encoding='utf-8') as handle:\n"
        "    json.dump({name: os.environ.get(name) for name in "
        "('SHARED', 'BASE_ONLY', 'ITEM_ONLY', 'EMPTY_VALUE')}, handle)\n",
        encoding="utf-8",
    )
    driver.chmod(0o700)
    _write_settings(
        tmp_path,
        str(driver),
        base_env={"SHARED": "from-base", "OUTPUT_FILE": str(record)},
        item_env={"SHARED": "from-item"},
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "topsailai_launch_agent.py",
            "--subprocess",
            "--env",
            "SHARED=from-caller",
            "--env",
            "EMPTY_VALUE=",
        ],
    )
    with open(os.devnull, "r", encoding="utf-8") as stdin:
        monkeypatch.setattr(launcher.sys, "stdin", stdin)
        with pytest.raises(SystemExit) as error:
            launcher.main()
    assert error.value.code == 0
    observed = json.loads(record.read_text(encoding="utf-8"))
    assert observed["SHARED"] == "from-caller"
    assert observed["BASE_ONLY"] == "base"
    assert observed["ITEM_ONLY"] == "item"
    assert observed["EMPTY_VALUE"] == ""


def test_driver_override_still_outranks_a_caller_env_value(tmp_path, monkeypatch):
    """The child must advertise the driver that is really running."""
    record = tmp_path / "child-env.json"
    driver = tmp_path / "fake-driver.py"
    driver.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        "with open(os.environ['OUTPUT_FILE'], 'w', encoding='utf-8') as handle:\n"
        "    json.dump({'TOPSAILAI_AGENT_DRIVER': "
        "os.environ.get('TOPSAILAI_AGENT_DRIVER')}, handle)\n",
        encoding="utf-8",
    )
    driver.chmod(0o700)
    _write_settings(
        tmp_path, str(driver), base_env={"OUTPUT_FILE": str(record)}
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "topsailai_launch_agent.py",
            "--subprocess",
            "--driver",
            str(driver),
            "--env",
            "TOPSAILAI_AGENT_DRIVER=not-the-real-driver",
        ],
    )
    with open(os.devnull, "r", encoding="utf-8") as stdin:
        monkeypatch.setattr(launcher.sys, "stdin", stdin)
        with pytest.raises(SystemExit) as error:
            launcher.main()
    assert error.value.code == 0
    observed = json.loads(record.read_text(encoding="utf-8"))
    assert observed["TOPSAILAI_AGENT_DRIVER"] == str(driver)


@pytest.mark.parametrize(
    "entry",
    ["NOEQUALS", "=value", "1BAD=x", "TOPSAILAI_SESSION_ID=other", "SESSION_ID=other"],
)
def test_malformed_or_identity_env_entry_is_a_usage_error(
    tmp_path, monkeypatch, capsys, entry
):
    """An unusable --env entry is refused before any driver runs."""
    _write_settings(tmp_path, "settings-driver")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["topsailai_launch_agent.py", "--env", entry, "--dry-run"]
    )
    with patch.object(launcher.subprocess, "run", side_effect=AssertionError("driver ran")):
        with pytest.raises(SystemExit) as error:
            launcher.main()
    assert error.value.code == 2
    assert "--env" in capsys.readouterr().err


def test_conflicting_env_repeat_is_a_usage_error(tmp_path, monkeypatch, capsys):
    """Two different values for one name cannot both be honored."""
    _write_settings(tmp_path, "settings-driver")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "topsailai_launch_agent.py",
            "--env",
            "A=1",
            "--env",
            "A=2",
            "--dry-run",
        ],
    )
    with pytest.raises(SystemExit) as error:
        launcher.main()
    assert error.value.code == 2
    assert "conflicting" in capsys.readouterr().err
