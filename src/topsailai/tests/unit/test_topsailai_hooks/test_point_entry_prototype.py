"""Real child execution for the self-contained Hook Point prototype.

Author: DawsonLin
"""

import importlib.machinery
import json
import os
import shutil
from pathlib import Path
import sysconfig
from unittest.mock import Mock

import pytest

import topsailai.hooks as hooks
from topsailai.hooks.point_entry import decode_points, execute_point
from topsailai.hooks.points.workspace.before_input_message import NAME
from topsailai.tests.unit.test_topsailai_hooks.module_discovery_helpers import compile_extension


@pytest.fixture(autouse=True)
def configuration(monkeypatch):
    """Restore package bootstrap state between tests without global switches."""
    monkeypatch.setattr(hooks, "_point_configuration", None)
    from topsailai.hooks import point_entry
    monkeypatch.setattr(point_entry, "_cleanup_records", {})


def module(path, output, text, extra=""):
    """Create a real child Module writing one ordered execution marker."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"from pathlib import Path\ndef main():\n    Path({str(output)!r}).open('a').write({text!r})\n{extra}")
    return path


def script(path, output, text, executable=True):
    """Create a direct executable Script without manifest or interpreter admission."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\nprintf '{text}' >> '{output}'\n")
    path.chmod(0o755 if executable else 0o644)
    return path


def test_internal_external_order(tmp_path):
    """Merge both sources, sort each kind, and execute Modules before Scripts."""
    output = tmp_path / "trace"
    root = tmp_path / "points"
    local = root / "workspace" / "before_input_message"
    module(local / "modules" / "b.py", output, "b")
    script(local / "scripts" / "b", output, "B")
    external = tmp_path / "external"
    module(external / "z.py", output, "z")
    module(external / "a.py", output, "a")
    scripts = tmp_path / "scripts"
    script(scripts / "a", output, "A")
    script(scripts / "ignore", output, "NO", executable=False)
    points = decode_points({NAME: {"modules": str(external), "scripts": str(scripts)}})
    result = execute_point(NAME, points, payload={}, internal_root=root)
    assert output.read_text() == "abzAB"
    assert [item.status for item in result] == ["success"] * 5


def test_env_bootstrap_real_input(tmp_path, monkeypatch):
    """Environment-only setup drives the actual native input checkpoint."""
    from topsailai.workspace import input_tool

    output = tmp_path / "trace"
    file = script(tmp_path / "bell", output, "before")
    monkeypatch.setenv("TOPSAILAI_HOOK_POINTS", json.dumps({NAME: {"scripts": [str(file)]}}))
    monkeypatch.setattr(input_tool.env_tool, "is_chat_multi_line", lambda: False)
    reader = Mock(side_effect=lambda *args: output.read_text())
    monkeypatch.setattr(input_tool, "input_one_line", reader)
    assert input_tool.input_message() == "before"
    reader.assert_called_once_with("", None)
    monkeypatch.setenv("TOPSAILAI_HOOK_POINTS", "invalid-after-snapshot")
    assert input_tool.input_message() == "beforebefore"


def test_file_lists_failure_and_bad_executable(tmp_path):
    """Reverse file lists sort and a settled failure does not suppress successors."""
    output = tmp_path / "trace"
    bad = tmp_path / "a"
    bad.write_text("not an executable format")
    bad.chmod(0o755)
    good = script(tmp_path / "z", output, "ok")
    hooks.initialize_hook_points({NAME: {"scripts": [str(good), str(bad)]}})
    result = hooks.invoke_hook_point(NAME)
    assert [item.status for item in result] == ["error", "success"]
    assert output.read_text() == "ok"


def test_duplicate_rejects_whole_point(tmp_path):
    """Same-kind duplicate names reject before any Module side effect."""
    output = tmp_path / "trace"
    left = module(tmp_path / "a" / "same.py", output, "a")
    right = module(tmp_path / "b" / "same.py", output, "b")
    hooks.initialize_hook_points({NAME: {"modules": [str(left), str(right)]}})
    assert hooks.invoke_hook_point(NAME) == ()
    assert not output.exists()


def test_expired_deadline_skips_successor_after_inprocess_module(tmp_path):
    """An in-process Module cannot be killed; the expired deadline skips successors."""
    output = tmp_path / "pid"
    slow = tmp_path / "a.py"
    slow.write_text(f"import os,time\nfrom pathlib import Path\ndef main():\n    Path({str(output)!r}).write_text(str(os.getpid()))\n    time.sleep(0.6)\n")
    marker = tmp_path / "marker"
    later = script(tmp_path / "z", marker, "NO")
    points = decode_points({NAME: {"modules": str(slow), "scripts": str(later)}})
    result = execute_point(NAME, points, payload={}, timeout_seconds=0.5)
    assert [item.status for item in result] == ["success", "timeout"]
    assert not marker.exists()
    assert int(output.read_text()) == os.getpid()


@pytest.mark.parametrize("config", [[], {"bad": {}}, {NAME: {"unknown": []}},
                                    {NAME: {"scripts": ["relative"]}},
                                    {NAME: {"modules": 1}}])
def test_invalid_configuration(config):
    """Reject malformed snapshots before resource discovery."""
    with pytest.raises(ValueError):
        hooks.initialize_hook_points(config)


def test_no_resources_and_bad_environment(monkeypatch, caplog):
    """Unconfigured points are no-ops and malformed environment preserves flow."""
    assert hooks.invoke_hook_point(NAME) == ()
    monkeypatch.setattr(hooks, "_point_configuration", None)
    monkeypatch.setenv("TOPSAILAI_HOOK_POINTS", "bad json")
    assert hooks.invoke_hook_point(NAME) == ()
    assert "initialization failed" in caplog.text


def test_missing_resource_and_async_module(tmp_path):
    """Report missing selection and execute async main without host event loops."""
    hooks.initialize_hook_points({NAME: {"scripts": str(tmp_path / "absent")}})
    assert hooks.invoke_hook_point(NAME) == ()
    path = tmp_path / "async.py"
    path.write_text("async def main():\n    return False\n")
    hooks.initialize_hook_points({NAME: {"modules": str(path)}})
    assert hooks.invoke_hook_point(NAME)[0].status == "success"


def test_module_failure_and_skipped_directory(tmp_path):
    """Worker exceptions do not suppress later Modules; nested files stay excluded."""
    bad = tmp_path / "a.py"
    bad.write_text("def main():\n    raise RuntimeError('failure')\n")
    output = tmp_path / "trace"
    module(tmp_path / "z.py", output, "ok")
    module(tmp_path / "nested" / "no.py", output, "NO")
    (tmp_path / "__init__.py").write_text("raise RuntimeError('not a member')")
    hooks.initialize_hook_points({NAME: {"modules": str(tmp_path)}})
    assert [r.status for r in hooks.invoke_hook_point(NAME)] == ["error", "success"]
    assert output.read_text() == "ok"


def test_host_interrupt_cleans_child(monkeypatch, tmp_path):
    """Retain host exception identity and execute exact-group cleanup."""
    from topsailai.hooks import point_entry

    error = KeyboardInterrupt()
    child = Mock(pid=123456, wait=Mock(return_value=0))
    launch = Mock(return_value=child)
    cleanup = Mock()
    monkeypatch.setattr(point_entry.subprocess, "Popen", launch)
    monkeypatch.setattr(point_entry, "_wait_owned", Mock(side_effect=error))
    monkeypatch.setattr(point_entry.os, "killpg", cleanup)
    with pytest.raises(KeyboardInterrupt) as caught:
        point_entry._execute("script", tmp_path / "fixture", {}, float("inf"))
    assert caught.value is error
    cleanup.assert_called_once_with(child.pid, point_entry.signal.SIGKILL)
    assert child.wait.call_count == 1


def test_cleanup_failure_stops_successors(tmp_path, monkeypatch):
    """Unconfirmed cleanup prevents another resource from starting."""
    from topsailai.hooks import point_entry

    output = tmp_path / "trace"
    first = script(tmp_path / "a", output, "a")
    later = script(tmp_path / "z", output, "z")
    original = point_entry._cleanup

    def settled_but_failed(process):
        """Clean the real fixture child before injecting a failed result."""
        assert original(process)
        return False

    monkeypatch.setattr(point_entry, "_cleanup", settled_but_failed)
    points = decode_points({NAME: {"scripts": [str(later), str(first)]}})
    assert [r.status for r in execute_point(NAME, points, payload={})] == ["cleanup_failed"]
    assert output.read_text() == "a"


def test_cleanup_diagnostics(monkeypatch, caplog):
    """Report kill and reap failures rather than declaring successful cleanup."""
    from topsailai.hooks import point_entry

    child = Mock(pid=123456)
    monkeypatch.setattr(point_entry.os, "killpg", Mock(side_effect=OSError("fixture")))
    assert point_entry._cleanup(child) is False
    monkeypatch.setattr(point_entry.os, "killpg", Mock(side_effect=ProcessLookupError))
    child = Mock(pid=123457, wait=Mock(side_effect=point_entry.subprocess.TimeoutExpired("fixture", 1)))
    assert point_entry._cleanup(child) is False
    assert "cleanup failed" in caplog.text
    assert "reap timeout" in caplog.text


def test_invalid_name_platform_and_budget(tmp_path, monkeypatch):
    """Reject invalid selectors, unsupported containment, and expired execution."""
    from types import SimpleNamespace
    from topsailai.hooks import point_entry

    with pytest.raises(ValueError):
        execute_point("bad", (), payload={})
    monkeypatch.setattr(point_entry, "os", SimpleNamespace(name="nt"))
    assert execute_point(NAME, (), payload={}) == ()
    assert point_entry._execute("script", tmp_path / "unused", {}, 0) == "timeout"


def test_configuration_limits(tmp_path):
    """Bound raw selection and complete candidate sizes."""
    with pytest.raises(ValueError):
        decode_points({f"point{i}": {} for i in range(129)})
    with pytest.raises(ValueError):
        decode_points({NAME: {"scripts": [str(tmp_path)] * 129}})
    for index in range(129):
        (tmp_path / str(index)).write_text("")
    hooks.initialize_hook_points({NAME: {"scripts": str(tmp_path)}})
    assert hooks.invoke_hook_point(NAME) == ()


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit, __import__("asyncio").CancelledError])
def test_public_interrupt_with_reap_failure(tmp_path, monkeypatch, error_type):
    """Preserve exact host control flow through public entry plus failing cleanup."""
    from topsailai.hooks import point_entry

    file = script(tmp_path / "a", tmp_path / "trace", "NO")
    primary = error_type("primary")
    child = Mock(pid=123456, wait=Mock(side_effect=ChildProcessError("reap failure")))
    monkeypatch.setattr(point_entry.subprocess, "Popen", Mock(return_value=child))
    monkeypatch.setattr(point_entry, "_wait_owned", Mock(side_effect=primary))
    monkeypatch.setattr(point_entry.os, "killpg", Mock())
    hooks.initialize_hook_points({NAME: {"scripts": str(file)}})
    with pytest.raises(error_type) as caught:
        hooks.invoke_hook_point(NAME)
    assert caught.value is primary
    record, = point_entry.pending_cleanup()
    assert record.process is child
    assert record.group_settled and not record.child_reaped
    child.wait.side_effect = None
    assert point_entry.retry_cleanup(record)
    assert point_entry.pending_cleanup() == ()
    assert point_entry.retry_cleanup(record) is False


def test_group_failure_reaps_retains_and_blocks(tmp_path, monkeypatch):
    """Reap independently, retain group uncertainty, and forbid reused-PGID signals."""
    from topsailai.hooks import point_entry

    child = Mock(pid=123456, wait=Mock(return_value=0))
    launch = Mock(return_value=child)
    kill = Mock(side_effect=PermissionError("denied"))
    monkeypatch.setattr(point_entry.subprocess, "Popen", launch)
    monkeypatch.setattr(point_entry, "_wait_owned", Mock(return_value=0))
    monkeypatch.setattr(point_entry.os, "killpg", kill)
    assert point_entry._execute("script", tmp_path / "fixture", {}, float("inf")) == "cleanup_failed"
    child.wait.assert_called_once_with(timeout=1)
    record, = point_entry.pending_cleanup()
    assert record.process is child and record.child_reaped
    assert not record.group_settled and not record.group_retry_safe
    assert point_entry._execute("script", tmp_path / "next", {}, float("inf")) == "cleanup_failed"
    assert launch.call_count == 1
    assert point_entry.retry_cleanup(record) is False
    assert kill.call_count == 1
    assert child.wait.call_count == 1
    assert point_entry.pending_cleanup() == (record,)


@pytest.mark.parametrize("primary_present", [False, True])
def test_cleanup_host_interrupt_retains_owner(tmp_path, monkeypatch, primary_present):
    """Retain cleanup ownership if cleanup itself receives a host interruption."""
    from topsailai.hooks import point_entry

    primary = KeyboardInterrupt("primary")
    cleanup_interrupt = SystemExit("cleanup")
    child = Mock(pid=123456, wait=Mock(side_effect=cleanup_interrupt))
    monkeypatch.setattr(point_entry.subprocess, "Popen", Mock(return_value=child))
    monkeypatch.setattr(point_entry, "_wait_owned", Mock(side_effect=primary) if primary_present else Mock(return_value=0))
    monkeypatch.setattr(point_entry.os, "killpg", Mock())
    expected = primary if primary_present else cleanup_interrupt
    with pytest.raises(type(expected)) as caught:
        point_entry._execute("script", tmp_path / "fixture", {}, float("inf"))
    assert caught.value is expected
    record, = point_entry.pending_cleanup()
    assert record.process is child
    child.wait.side_effect = None
    assert point_entry.retry_cleanup(record)


def require_compiler():
    """Skip compiled-extension cases when no C compiler or headers are available."""
    if not shutil.which("cc") or not sysconfig.get_paths().get("include"):
        pytest.skip("compiled-extension fixture requires a C compiler and Python headers")


def test_compiled_extension_module_executes(tmp_path):
    """A real platform extension is admitted and its main entry runs to success."""
    require_compiler()
    external = tmp_path / "external"
    external.mkdir()
    extension = compile_extension(external, "compiled_plugin")
    assert extension.name.endswith(importlib.machinery.EXTENSION_SUFFIXES[0])
    points = decode_points({NAME: {"modules": str(external)}})
    result = execute_point(NAME, points, payload={}, internal_root=tmp_path / "empty")
    assert [(item.kind, item.name, item.status) for item in result] == [
        ("module", extension.name, "success")]


def test_duplicate_logical_name_rejects_compiled_and_source(tmp_path):
    """A source and extension sharing one logical name reject the whole point."""
    require_compiler()
    external = tmp_path / "external"
    external.mkdir()
    module(external / "same.py", tmp_path / "trace", "NO")
    compile_extension(external, "same")
    points = decode_points({NAME: {"modules": str(external)}})
    result = execute_point(NAME, points, payload={}, internal_root=tmp_path / "empty")
    assert result == ()
    assert not (tmp_path / "trace").exists()


def test_source_module_and_init_exclusion_unchanged(tmp_path):
    """Plain source Modules still run while __init__.py stays excluded."""
    external = tmp_path / "external"
    external.mkdir()
    output = tmp_path / "trace"
    module(external / "plain.py", output, "ok")
    (external / "__init__.py").write_text("raise RuntimeError('not a member')")
    points = decode_points({NAME: {"modules": str(external)}})
    result = execute_point(NAME, points, payload={}, internal_root=tmp_path / "empty")
    assert [(item.kind, item.name, item.status) for item in result] == [
        ("module", "plain.py", "success")]
    assert output.read_text() == "ok"


def test_symlink_child_is_admitted_and_escape_is_not_rejected(tmp_path):
    """Characterize current admission: symlink children are followed, including escapes."""
    from topsailai.hooks.point_entry import _eligible

    inside = tmp_path / "inside"
    inside.mkdir()
    target_inside = module(inside / "real.py", tmp_path / "trace", "NO")
    link_inside = inside / "link_inside.py"
    link_inside.symlink_to(target_inside)
    outside = tmp_path / "outside"
    outside.mkdir()
    target_outside = module(outside / "escaped.py", tmp_path / "trace", "NO")
    escape = tmp_path / "escape"
    escape.mkdir()
    link_escape = escape / "link_escape.py"
    link_escape.symlink_to(target_outside)
    assert _eligible(link_inside, "module") is True
    assert _eligible(link_escape, "module") is True
    points = decode_points({NAME: {"modules": str(escape)}})
    result = execute_point(NAME, points, payload={}, internal_root=tmp_path / "empty")
    assert [(item.kind, item.name) for item in result] == [("module", "link_escape.py")]


def test_symlink_to_directory_is_skipped(tmp_path):
    """Characterize current admission: a symlink to a directory is not eligible."""
    from topsailai.hooks.point_entry import _eligible

    parent = tmp_path / "dirlink"
    parent.mkdir()
    (parent / "sub").mkdir()
    link = parent / "link_dir"
    link.symlink_to(parent / "sub")
    assert _eligible(link, "module") is False


def test_broken_symlink_reports_discovery_failure(tmp_path, caplog):
    """Characterize current admission: a dangling symlink fails the whole point."""
    parent = tmp_path / "broken"
    parent.mkdir()
    (parent / "dangling.py").symlink_to(parent / "missing.py")
    points = decode_points({NAME: {"modules": str(parent)}})
    assert execute_point(NAME, points, payload={}, internal_root=tmp_path / "empty") == ()
    assert "discovery failed" in caplog.text


def test_module_ordering_uses_filename_not_logical_name(tmp_path):
    """Characterize current ordering: the sort key is the filename, not the logical name."""
    from topsailai.hooks.point_entry import _logical_name

    folder = tmp_path / "order"
    folder.mkdir()
    module(folder / "a-b.py", tmp_path / "trace", "NO")
    (folder / "a.so").write_bytes(b"\x7fELF")
    points = decode_points({NAME: {"modules": str(folder)}})
    result = execute_point(NAME, points, payload={}, internal_root=tmp_path / "empty")
    assert [item.name for item in result] == ["a-b.py", "a.so"]
    assert [_logical_name(Path(item.name), "module") for item in result] == ["a-b", "a"]
