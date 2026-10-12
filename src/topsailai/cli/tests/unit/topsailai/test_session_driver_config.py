"""Author: DawsonLin. Isolated configuration checks; never spawn a driver."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cli_topsailai import core, session_driver_config as config


@pytest.fixture
def installation(tmp_path):
    """Create only task-scoped readable/executable fixture files."""
    package = tmp_path / "cli" / "cli_topsailai"
    package.mkdir(parents=True)
    entry = tmp_path / "scripts" / "session_agent_driver" / "session_agent_driver.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("fixture only")
    interpreter = tmp_path / "python3"
    interpreter.write_text("fixture only")
    interpreter.chmod(0o700)
    return SimpleNamespace(package=package, entry=entry, interpreter=interpreter)


def resolve(installation, environment=None, **overrides):
    """Inject layout and runtime without changing process environment."""
    kwargs = dict(package_dir=installation.package,
                  executable=str(installation.interpreter), base_executable="")
    kwargs.update(overrides)
    return config.resolve_driver_authority(environment or {}, **kwargs)


def test_defaults(installation):
    """Use the package-relative entry and current interpreter."""
    authority = resolve(installation)
    assert authority.entry == installation.entry
    assert authority.interpreter == installation.interpreter


@pytest.mark.parametrize("which", ["entry", "python", "both"])
def test_overrides(installation, which):
    """Valid overrides independently replace defaults with highest precedence."""
    entry = installation.package / "alternate.py"
    entry.write_text("fixture only")
    interpreter = installation.package / "python-custom"
    interpreter.write_text("fixture only")
    interpreter.chmod(0o700)
    environment = {}
    if which in ("entry", "both"):
        environment[config.ENTRY_ENV] = str(entry)
    if which in ("python", "both"):
        environment[config.PYTHON_ENV] = str(interpreter)
    authority = resolve(installation, environment)
    assert authority.entry == (entry if config.ENTRY_ENV in environment else installation.entry)
    assert authority.interpreter == (interpreter if config.PYTHON_ENV in environment else installation.interpreter)


@pytest.mark.parametrize("variable", [config.ENTRY_ENV, config.PYTHON_ENV])
@pytest.mark.parametrize("value", ["", "relative", "/missing-driver-defaults-fixture"])
def test_invalid_overrides(installation, variable, value):
    """Invalid explicit values never silently fall back to working defaults."""
    with pytest.raises(ValueError, match=variable):
        resolve(installation, {variable: value})


def test_nonpython_override(installation):
    """Reject a packaged application even when it is executable."""
    with pytest.raises(ValueError, match=config.PYTHON_ENV):
        resolve(installation, {config.PYTHON_ENV: str(Path(__file__).absolute())})


def test_missing_default(installation):
    """Missing installation layout reports entry correction guidance."""
    with pytest.raises(ValueError, match="install scripts/session_agent_driver"):
        resolve(installation, package_dir=installation.package / "missing")


def test_runtime_fallback(installation):
    """Use a valid base Python only when the preferred runtime is unavailable."""
    authority = resolve(installation, executable="", base_executable=str(installation.interpreter))
    assert authority.interpreter == installation.interpreter
    with pytest.raises(ValueError, match="compatible Python interpreter"):
        resolve(installation, executable="", base_executable="")


def test_implicit_runtime(installation, monkeypatch):
    """The production defaults read the current interpreter and module layout."""
    monkeypatch.setattr(config, "__file__", str(installation.package / "session_driver_config.py"))
    monkeypatch.setattr(config, "sys", SimpleNamespace(executable=str(installation.interpreter)))
    authority = config.resolve_driver_authority({})
    assert authority.entry == installation.entry
    assert authority.interpreter == installation.interpreter


@pytest.mark.parametrize("entry_readable", [True, False])
def test_permission_failures(installation, monkeypatch, entry_readable):
    """Reject unreadable entries and nonexecutable interpreters even as root."""
    monkeypatch.setattr("cli_topsailai.session_driver_launcher.os", SimpleNamespace(
        X_OK=1, R_OK=4, access=lambda path, mode: mode == 4 and entry_readable))
    with pytest.raises(ValueError, match=config.PYTHON_ENV):
        resolve(installation)


def test_unreadable_entry(installation, monkeypatch):
    """Identify the entry rather than the interpreter when read access fails."""
    monkeypatch.setattr(config, "os", SimpleNamespace(R_OK=4, access=lambda path, mode: False))
    with pytest.raises(ValueError, match=config.ENTRY_ENV):
        resolve(installation)


def test_boundary_error(monkeypatch, capsys):
    """Configuration failures provide actionable error output at the boundary."""
    monkeypatch.setattr(config, "resolve_driver_authority", Mock(side_effect=ValueError(
        "TOPSAILAI_SESSION_DRIVER_ENTRY: set an absolute entry before restarting the CLI")))
    assert core._driver_authority({}) is None
    output = capsys.readouterr().out
    assert "[ERROR]" in output and config.ENTRY_ENV in output and "restarting" in output


def test_launch_config_error(capsys):
    """No authority means no discovery/spawn and a clear launch rejection."""
    discover = Mock(side_effect=AssertionError("must not discover"))
    assert core._handle_driver_action("driver_start", 1, [], "/home", None, {}, discover) is None
    discover.assert_not_called()
    assert "[ERROR] Driver launch blocked" in capsys.readouterr().out


@pytest.mark.parametrize("override", [False, True])
def test_compiled_entry(installation, override):
    """Compiled entries run directly even without a Python runtime."""
    binary = installation.entry.with_suffix("")
    binary.write_text("compiled fixture")
    binary.chmod(0o700)
    environment = {config.PYTHON_ENV: "invalid-but-unused"}
    if override:
        environment[config.ENTRY_ENV] = str(binary)
    authority = resolve(installation, environment, executable="", base_executable="")
    assert authority.entry == binary
    assert authority.interpreter is None


def test_invalid_compiled_entry(installation):
    """Do not silently substitute source for a broken compiled deployment."""
    binary = installation.entry.with_suffix("")
    binary.write_text("not executable")
    binary.chmod(0o600)
    with pytest.raises(ValueError, match="compiled entry must be executable"):
        resolve(installation)
