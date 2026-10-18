"""Public direct-entry result contract regressions. Author: DawsonLin."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import topsailai.hooks as hooks
from topsailai.hooks import HookPointResult
from topsailai.hooks import point_entry
from topsailai.hooks.point_entry_results import unavailable_result
from topsailai.hooks.points.workspace.before_input_message import (
    NAME, hook__workspace__before__input_message,
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Restore configuration and isolate debt observations without global switches."""
    monkeypatch.setattr(hooks, "_point_configuration", ())
    monkeypatch.setattr(point_entry, "_cleanup_records", {})


def run(tmp_path, modules=(), scripts=(), **kwargs):
    """Execute only the fixture resources, excluding bundled observers."""
    points = point_entry.decode_points({NAME: {
        "modules": [str(path) for path in modules],
        "scripts": [str(path) for path in scripts],
    }})
    return point_entry.execute_point(NAME, points, payload={}, internal_root=tmp_path / "empty", **kwargs)


@pytest.mark.parametrize("value", [None, False, 0, "", [], {}, {"error": 1}, object()])
def test_opaque_normal_values(tmp_path, monkeypatch, value):
    """Normal values retain identity and presence without serialization or truth tests."""
    path = tmp_path / "value.py"
    path.touch()
    monkeypatch.setattr(point_entry, "_import_module", lambda _: SimpleNamespace(main=lambda: value))
    result = run(tmp_path, [path])
    assert type(result) is HookPointResult
    assert result.status == "success"
    handler, terminal = result.handlers
    assert handler.returned.present and handler.returned.representation == "direct"
    assert handler.returned.value is value
    assert handler.cleanup.state == result.cleanup.state == "safe"
    assert handler.execution_id == terminal.execution_id == result.execution_id
    assert handler.plan_version == result.plan_version == 0
    assert handler.hook_point_name == result.hook_point_name == NAME
    assert terminal.handler.kind == "default_script_hook" and terminal.children == ()
    assert result.decision.action == "continue" and result.decision.authority is None
    assert result.timing.elapsed_ms >= handler.timing.elapsed_ms >= 0
    assert run(tmp_path).execution_id != result.execution_id


def test_awaited_value(tmp_path):
    """Preserve the actual async result rather than the coroutine object."""
    path = tmp_path / "async_value.py"
    path.write_text("async def main():\n    return {'answer': 42}\n")
    handler = run(tmp_path, [path]).handlers[0]
    assert handler.returned.present and handler.returned.value == {"answer": 42}


def test_custom_awaitable(tmp_path, monkeypatch):
    """Non-coroutine awaitables retain their resolved value."""
    class Awaitable:
        """Provide the supported generic awaitable protocol."""
        def __await__(self):
            """Return a value without a coroutine-only assumption."""
            yield from ()
            return False
    path = tmp_path / "custom.py"
    path.touch()
    monkeypatch.setattr(point_entry, "_import_module", lambda _: SimpleNamespace(main=Awaitable))
    assert run(tmp_path, [path]).handlers[0].returned.value is False


def test_error_continuation_and_no_raw_diagnostic(tmp_path):
    """An ordinary exception has no return; later resources still execute."""
    bad = tmp_path / "a.py"
    bad.write_text("def main():\n    raise RuntimeError('private sentinel')\n")
    good = tmp_path / "z.py"
    good.write_text("def main():\n    return None\n")
    result = run(tmp_path, [good, bad])
    assert result.status == "completed_with_errors"
    assert [item.handler.name for item in result.handlers] == ["a.py", "z.py", "hook_script"]
    failed, success, _ = result.handlers
    assert failed.status == "error" and not failed.returned.present
    assert failed.error.category == "error" and "private sentinel" not in failed.error.message
    assert success.returned.present and success.returned.value is None


def test_script_group_and_exit_facts(tmp_path):
    """Direct Scripts have ordered child outcomes and no captured output payload."""
    bad, good = tmp_path / "a", tmp_path / "z"
    bad.write_text("#!/bin/sh\nexit 7\n")
    good.write_text("#!/bin/sh\nprintf 'discarded'\n")
    for path in (bad, good):
        path.chmod(0o755)
    result = run(tmp_path, scripts=[good, bad])
    terminal, = result.handlers
    assert terminal.status == result.status == "completed_with_errors"
    assert [item.handler.name for item in terminal.children] == ["a", "z"]
    failed, success = terminal.children
    assert failed.status == "error" and not failed.returned.present
    assert success.returned.value == {"exit_code": 0}
    assert terminal.cleanup.state == result.cleanup.state == "safe"
    assert point_entry.pending_cleanup() == ()


def test_empty_and_unavailable(tmp_path, monkeypatch):
    """Empty success and failed discovery/bootstrap are observably different."""
    result = run(tmp_path)
    assert result.status == "success" and len(result.handlers) == 1
    result = run(tmp_path, [tmp_path / "missing.py"])
    assert result.status == "unavailable" and result.handlers == ()
    assert result.cleanup.diagnostic.category == "discovery_failed"
    monkeypatch.setattr(hooks, "_point_configuration", None)
    monkeypatch.setenv("TOPSAILAI_HOOK_POINTS", "invalid")
    assert hook__workspace__before__input_message().status == "unavailable"
    assert unavailable_result(NAME, "fixture").cleanup.state == "safe"


def test_deadline_reports_all_unrun_resources(tmp_path):
    """Expired admission lists every selected successor without executing it."""
    paths = [tmp_path / name for name in ("a.py", "z.py")]
    for path in paths:
        path.write_text("raise RuntimeError('must not import')")
    result = run(tmp_path, paths, timeout_seconds=0)
    assert result.status == "timeout"
    assert all(item.status == "not_run" for item in result.handlers)
    assert all(item.not_run_reason == "timeout" for item in result.handlers)
    assert all(not item.returned.present for item in result.handlers)


def test_pending_cleanup_blocks_module_and_reports_successors(tmp_path, monkeypatch):
    """Foreign debt blocks starts and is not misreported as successful settlement."""
    path = tmp_path / "a.py"
    path.write_text("raise RuntimeError('must not import')")
    monkeypatch.setattr(point_entry, "_cleanup_records", {1: object()})
    result = run(tmp_path, [path])
    assert result.status == "completed_with_errors" and result.cleanup.state == "pending"
    assert all(item.status == "not_run" for item in result.handlers)
    assert result.handlers[0].not_run_reason == "cleanup_failed"


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit, asyncio.CancelledError])
def test_module_interrupt_identity(tmp_path, monkeypatch, error_type):
    """Result wrapping does not swallow genuine host control flow."""
    path = tmp_path / "interrupt.py"
    path.touch()
    primary = error_type()
    def interrupt():
        """Raise the exact host control-flow object."""
        raise primary
    monkeypatch.setattr(point_entry, "_import_module", lambda _: SimpleNamespace(main=interrupt))
    with pytest.raises(error_type) as caught:
        run(tmp_path, [path])
    assert caught.value is primary


def test_public_named_point_returns_envelope(tmp_path):
    """The business-facing named entry returns Module data through the real bootstrap."""
    path = tmp_path / "business.py"
    path.write_text("def main():\n    return {'answer': 42}\n")
    hooks.initialize_hook_points({NAME: {"modules": str(path)}})
    result = hook__workspace__before__input_message()
    assert isinstance(result, HookPointResult)
    assert result.handlers[0].returned.value == {"answer": 42}


def test_script_timeout_and_skipped_successor(tmp_path, monkeypatch):
    """A started child timeout is distinct from its unstarted successor."""
    from unittest.mock import Mock
    paths = [tmp_path / name for name in ("a", "z")]
    for path in paths:
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    child = Mock(pid=123456, wait=Mock(return_value=0))
    monkeypatch.setattr(point_entry.subprocess, "Popen", Mock(return_value=child))
    monkeypatch.setattr(point_entry, "_wait_owned", Mock(side_effect=point_entry.subprocess.TimeoutExpired("fixture", 0)))
    monkeypatch.setattr(point_entry.os, "killpg", Mock())
    result = run(tmp_path, scripts=paths)
    first, second = result.handlers[-1].children
    assert result.status == result.handlers[-1].status == first.status == "timeout"
    assert second.status == "not_run" and second.not_run_reason == "timeout"
    assert result.cleanup.state == "safe" and point_entry.pending_cleanup() == ()


def test_missing_main_and_import_error(tmp_path):
    """Import and entry resolution failures both yield safe absent-return errors."""
    missing, broken = tmp_path / "missing.py", tmp_path / "broken.py"
    missing.write_text("value = 1\n")
    broken.write_text("raise RuntimeError('private import text')\n")
    result = run(tmp_path, [missing, broken])
    assert result.status == "completed_with_errors"
    assert all(item.status == "error" and not item.returned.present for item in result.handlers[:-1])
