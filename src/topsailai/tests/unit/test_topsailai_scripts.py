"""Scripts launcher contracts. Author: DawsonLin."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import os
import subprocess

import pytest

import topsailai.scripts as scripts


@pytest.fixture
def target(tmp_path):
    """Create an executable Python fixture within the configured basetemp."""
    path = tmp_path / "example.py"
    path.write_text("pass\n")
    path.chmod(0o755)
    return path


@pytest.fixture
def child(monkeypatch):
    """Replace process creation without altering shared subprocess globals."""
    process = MagicMock(pid=123)
    process.poll.return_value = 0
    factory = MagicMock(return_value=process)
    monkeypatch.setattr(scripts, "subprocess", SimpleNamespace(
        Popen=factory, TimeoutExpired=subprocess.TimeoutExpired))
    return process, factory


def test_absolute_arguments_and_overrides(target, child, tmp_path):
    """Keep arguments literal and parent environment and cwd unchanged."""
    process, factory = child
    before = dict(os.environ)
    original_cwd = Path.cwd()
    arguments = ["space value", "中文", "$(echo nope);*", ""]
    with scripts.start_script(target, arguments, cwd=tmp_path, env={"CUSTOM": "value"}) as result:
        assert result is process
    argv = factory.call_args.args[0]
    assert argv[1:] == [str(target), *arguments]
    assert factory.call_args.kwargs["shell"] is False
    assert factory.call_args.kwargs["cwd"] == str(tmp_path)
    assert factory.call_args.kwargs["env"] == {**before, "CUSTOM": "value"}
    assert dict(os.environ) == before
    assert Path.cwd() == original_cwd
    process.wait.assert_called_once_with(timeout=5.0)
    process.terminate.assert_not_called()


def test_relative_root_and_symlinks(target, child, monkeypatch):
    """Resolve relative paths against the package, including safe symlinks."""
    monkeypatch.setattr(scripts, "__file__", str(target.parent / "__init__.py"))
    with scripts.start_script("example.py"):
        pass
    link = target.parent / "link.py"
    link.symlink_to(target)
    with scripts.start_script("link.py"):
        pass
    assert child[1].call_args.args[0][1] == str(target)


def test_relative_escape(target, child, monkeypatch, tmp_path):
    """Reject both traversal and symlink escapes before starting a process."""
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(scripts, "__file__", str(root / "__init__.py"))
    (root / "escape.py").symlink_to(target)
    for path in ("../example.py", "escape.py"):
        with pytest.raises(ValueError, match="escapes"):
            with scripts.start_script(path):
                pass
    child[1].assert_not_called()


@pytest.mark.parametrize("kind,error", [("missing", FileNotFoundError), ("directory", IsADirectoryError), ("nonexec", PermissionError)])
def test_invalid_targets(target, child, kind, error):
    """Reject missing, directory and nonexecutable files."""
    path = target
    if kind == "missing":
        path = target.parent / "absent"
    elif kind == "directory":
        path = target.parent
    else:
        target.chmod(0o644)
    with pytest.raises(error):
        with scripts.start_script(path):
            pass
    child[1].assert_not_called()


@pytest.mark.parametrize("kwargs,error", [
    ({"script_path": ""}, ValueError),
    ({"args": "text"}, TypeError),
    ({"args": [1]}, TypeError),
    ({"args": iter(["a"])}, TypeError),
    ({"shutdown_timeout": 0}, ValueError),
    ({"shutdown_timeout": float("nan")}, ValueError),
    ({"shutdown_timeout": float("inf")}, ValueError),
    ({"shutdown_timeout": "5"}, TypeError),
    ({"shutdown_timeout": True}, TypeError),
])
def test_invalid_inputs(target, child, kwargs, error):
    """Reject malformed input without child creation."""
    values = {"script_path": target, **kwargs}
    with pytest.raises(error):
        with scripts.start_script(**values):
            pass
    child[1].assert_not_called()


def test_permissions_and_native_dispatch(target, child, monkeypatch):
    """Verify readable Python, interpreter access, native and Windows checks."""
    real_access = os.access
    fake_os = SimpleNamespace(name="posix", X_OK=os.X_OK, R_OK=os.R_OK,
                              fspath=os.fspath, environ=os.environ,
                              access=lambda path, mode: mode != os.R_OK)
    monkeypatch.setattr(scripts, "os", fake_os)
    with pytest.raises(PermissionError, match="readable"):
        with scripts.start_script(target):
            pass
    fake_os.access = real_access
    monkeypatch.setattr(scripts, "resolve_python_interpreter", lambda: str(target.parent / "absent"))
    with pytest.raises(PermissionError, match="interpreter"):
        with scripts.start_script(target):
            pass
    native = target.with_suffix("")
    native.write_text("native fixture")
    native.chmod(0o755)
    with scripts.start_script(native):
        pass
    assert child[1].call_args.args[0] == [str(native)]
    shell = native.with_suffix(".cmd")
    shell.write_text("echo no")
    shell.chmod(0o755)
    fake_os.name = "nt"
    with pytest.raises(ValueError, match="Windows"):
        with scripts.start_script(shell):
            pass


def test_nonregular_target(target, child, monkeypatch):
    """Reject existing targets that are neither directories nor regular files."""
    real_path = Path
    fake_target = SimpleNamespace(
        exists=lambda: True, is_dir=lambda: False, is_file=lambda: False)
    monkeypatch.setattr(scripts, "Path", lambda value: (
        SimpleNamespace(suffix=".py", is_absolute=lambda: True, resolve=lambda: fake_target)
        if value == target else real_path(value)))
    with pytest.raises(ValueError, match="regular"):
        with scripts.start_script(target):
            pass


@pytest.mark.parametrize("timeout", [False, True])
def test_live_child_cleanup(target, child, timeout):
    """Terminate a live child and force-kill after grace timeout."""
    process, _ = child
    process.poll.return_value = None
    if timeout:
        process.wait.side_effect = [subprocess.TimeoutExpired("fixture", 1), 0]
    with scripts.start_script(target, shutdown_timeout=0.1):
        pass
    process.terminate.assert_called_once()
    assert process.kill.call_count == int(timeout)
    assert process.wait.call_count == (2 if timeout else 1)


def test_exception_and_cleanup_failure(target, child):
    """Preserve caller exception identity while retaining cleanup diagnostics."""
    process, _ = child
    process.poll.return_value = None
    failure = RuntimeError("terminate failed")
    process.terminate.side_effect = failure
    primary = ValueError("caller failed")
    with pytest.raises(ValueError) as caught:
        with scripts.start_script(target):
            raise primary
    assert caught.value is primary
    assert primary.script_cleanup_error is failure
    process.kill.assert_called_once()
    process.wait.assert_called_once_with()


def test_cleanup_interruption(target, child):
    """Reap after an interrupted graceful wait and propagate the interruption."""
    process, _ = child
    process.poll.return_value = None
    process.wait.side_effect = [KeyboardInterrupt(), 0]
    with pytest.raises(KeyboardInterrupt):
        with scripts.start_script(target):
            pass
    process.kill.assert_called_once()
    assert process.wait.call_count == 2


def test_emergency_cleanup_failure(target, child):
    """Surface failed emergency cleanup instead of silently reporting success."""
    process, _ = child
    process.poll.return_value = None
    process.terminate.side_effect = OSError("terminate")
    process.kill.side_effect = OSError("kill")
    with pytest.raises(OSError, match="kill"):
        with scripts.start_script(target):
            pass


def test_spawn_failure(target, child):
    """Propagate actual operating-system launch errors."""
    child[1].side_effect = OSError("exec format")
    with pytest.raises(OSError, match="exec format"):
        with scripts.start_script(target):
            pass



def test_escalation_wait_interrupted_once(target, child):
    """Recover the forced wait after a single interruption and preserve identity."""
    process, _ = child
    process.poll.return_value = None
    interrupt = KeyboardInterrupt("forced wait")
    process.wait.side_effect = [subprocess.TimeoutExpired("fixture", 1), interrupt, 0]
    with pytest.raises(KeyboardInterrupt) as caught:
        with scripts.start_script(target):
            pass
    assert caught.value is interrupt
    assert process.wait.call_count == 3
    assert process.kill.call_count == 2


def test_escalation_kill_failure(target, child):
    """Retry a failed escalation kill and reap while retaining the failure."""
    process, _ = child
    process.poll.return_value = None
    failure = OSError("escalation kill")
    process.wait.side_effect = [subprocess.TimeoutExpired("fixture", 1), 0]
    process.kill.side_effect = [failure, None]
    with pytest.raises(OSError) as caught:
        with scripts.start_script(target):
            pass
    assert caught.value is failure
    assert process.kill.call_count == 2
    assert process.wait.call_count == 2


@pytest.mark.parametrize("host_type", [KeyboardInterrupt, SystemExit])
def test_caller_failure_and_host_interrupt(target, child, host_type):
    """Host interruption wins over caller failure after successful recovery."""
    process, _ = child
    process.poll.return_value = None
    caller = ValueError("caller")
    interrupt = host_type("cleanup")
    process.wait.side_effect = [interrupt, 0]
    with pytest.raises(host_type) as caught:
        with scripts.start_script(target):
            raise caller
    assert caught.value is interrupt
    assert interrupt.__cause__ is caller
    assert process.wait.call_count == 2
    process.kill.assert_called_once()


def test_recovery_kill_failure_still_waits(target, child):
    """Retain the initial host interrupt and reap despite a recovery kill error."""
    process, _ = child
    process.poll.return_value = None
    interrupt = KeyboardInterrupt("cleanup")
    failure = OSError("recovery kill")
    process.wait.side_effect = [interrupt, 0]
    process.kill.side_effect = failure
    with pytest.raises(KeyboardInterrupt) as caught:
        with scripts.start_script(target):
            pass
    assert caught.value is interrupt
    assert interrupt.script_cleanup_error is failure
    assert process.wait.call_count == 2
    process.wait.assert_called_with(timeout=5.0)


@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("suffix", [".py", ".sh"])
def test_extensionless_unique_candidate(target, child, monkeypatch, relative, suffix):
    """Resolve one explicit candidate for absolute and package-rooted paths."""
    candidate = target.parent / ("detected" + suffix)
    candidate.write_text("pass\n")
    candidate.chmod(0o755)
    monkeypatch.setattr(scripts, "__file__", str(target.parent / "__init__.py"))
    path = "detected" if relative else target.parent / "detected"
    with scripts.start_script(path):
        pass
    argv = child[1].call_args.args[0]
    assert str(candidate) in argv
    assert argv[-1] == str(candidate)


@pytest.mark.parametrize("relative", [False, True])
def test_extensionless_original_wins(target, child, monkeypatch, relative):
    """Prefer the original entry even when both extension candidates exist."""
    original = target.with_suffix("")
    original.write_text("native fixture")
    original.chmod(0o755)
    shell = original.with_suffix(".sh")
    shell.write_text("fixture")
    shell.chmod(0o755)
    monkeypatch.setattr(scripts, "__file__", str(target.parent / "__init__.py"))
    path = original.name if relative else original
    with scripts.start_script(path):
        pass
    assert child[1].call_args.args[0] == [str(original)]
    original.chmod(0o644)
    child[1].reset_mock()
    with pytest.raises(PermissionError):
        with scripts.start_script(path):
            pass
    child[1].assert_not_called()


@pytest.mark.parametrize("relative", [False, True])
def test_extensionless_ambiguity(target, child, monkeypatch, relative):
    """List all existing extension candidates rather than picking silently."""
    shell = target.with_suffix(".sh")
    shell.write_text("fixture")
    shell.chmod(0o755)
    monkeypatch.setattr(scripts, "__file__", str(target.parent / "__init__.py"))
    path = target.stem if relative else target.with_suffix("")
    with pytest.raises(ValueError, match="Ambiguous") as caught:
        with scripts.start_script(path):
            pass
    assert str(target) in str(caught.value)
    assert str(shell) in str(caught.value)
    child[1].assert_not_called()


@pytest.mark.parametrize("relative", [False, True])
def test_extensionless_absent(target, child, monkeypatch, relative):
    """Report missing extensionless scripts when no candidate exists."""
    monkeypatch.setattr(scripts, "__file__", str(target.parent / "__init__.py"))
    path = "missing" if relative else target.parent / "missing"
    with pytest.raises(FileNotFoundError, match="Script does not exist"):
        with scripts.start_script(path):
            pass
    child[1].assert_not_called()


def test_detected_candidate_permission_and_escape(target, child, monkeypatch):
    """Extension probing preserves permission and resolved containment checks."""
    target.chmod(0o644)
    with pytest.raises(PermissionError):
        with scripts.start_script(target.with_suffix("")):
            pass
    root = target.parent / "root"
    root.mkdir()
    (root / "escape.py").symlink_to(target)
    monkeypatch.setattr(scripts, "__file__", str(root / "__init__.py"))
    with pytest.raises(ValueError, match="escapes"):
        with scripts.start_script("escape"):
            pass
    child[1].assert_not_called()



@pytest.mark.parametrize("initial_host", [False, True])
def test_recovery_wait_failure(target, child, initial_host):
    """Preserve host interruption whether it precedes or occurs during recovery."""
    process, _ = child
    process.poll.return_value = None
    primary = KeyboardInterrupt("initial") if initial_host else OSError("initial")
    recovery = OSError("recovery wait") if initial_host else SystemExit("recovery wait")
    process.wait.side_effect = [primary, recovery]
    expected = primary if initial_host else recovery
    with pytest.raises(type(expected)) as caught:
        with scripts.start_script(target):
            pass
    assert caught.value is expected
    if initial_host:
        assert primary.script_cleanup_error is recovery
    else:
        assert recovery.__cause__ is primary
    assert process.wait.call_count == 2


def test_recovery_kill_host_interrupt(target, child):
    """A recovery kill interruption survives a subsequent ordinary wait failure."""
    process, _ = child
    process.poll.return_value = None
    initial = OSError("terminate")
    interrupt = KeyboardInterrupt("kill")
    process.terminate.side_effect = initial
    process.kill.side_effect = interrupt
    process.wait.side_effect = OSError("wait")
    with pytest.raises(KeyboardInterrupt) as caught:
        with scripts.start_script(target):
            pass
    assert caught.value is interrupt
    assert interrupt.__cause__ is initial
    process.wait.assert_called_once_with(timeout=5.0)
