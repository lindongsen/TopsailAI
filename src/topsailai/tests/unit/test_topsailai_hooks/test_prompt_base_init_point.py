"""Tests for the PromptBase initialization completion Hook Point."""

import asyncio
import json
from pathlib import Path
import os

import pytest

import topsailai.hooks as hooks
from topsailai.hooks.points.aibase.after_prompt_base_init import NAME


@pytest.fixture(autouse=True)
def reset_hook_points():
    """Keep the process-local Hook Point configuration isolated per test."""
    hooks.initialize_hook_points({})
    yield
    hooks.initialize_hook_points({})


def _prompt_base(monkeypatch):
    """Construct PromptBase with deterministic local dependencies."""
    from topsailai.ai_base import prompt_base as prompt_module

    monkeypatch.setattr(prompt_module, "get_managers_by_env", lambda: [])
    monkeypatch.setattr(prompt_module, "generate_prompt_for_env", lambda: "")
    return prompt_module


def _write_module(path: Path, body: str) -> Path:
    """Write one executable Hook Module fixture."""
    path.write_text(body, encoding="utf-8")
    return path


def test_prompt_base_point_runs_once_at_constructor_end(monkeypatch):
    """The point runs once after all PromptBase initialization state exists."""
    prompt_module = _prompt_base(monkeypatch)
    calls = []

    def observe(*, prompt_base):
        calls.append(prompt_base)
        assert prompt_base.hooks_after_init_prompt == []
        assert prompt_base.hooks_after_new_session == []
        assert prompt_base.hooks_pre_chat == []
        assert prompt_base.messages
        return object()

    monkeypatch.setattr(prompt_module, "hook__aibase__after__prompt_base_init", observe)
    instance = prompt_module.PromptBase("system")

    assert calls == [instance]
    assert calls[0] is instance


def test_prompt_base_point_is_safe_noop_without_resources(monkeypatch):
    """Empty point configuration preserves ordinary PromptBase construction."""
    prompt_module = _prompt_base(monkeypatch)
    instance = prompt_module.PromptBase("system", tool_prompt="tools")

    assert instance.system_prompt == "system"
    assert instance.tool_prompt == "tools"
    assert instance.hooks_after_init_prompt == []
    assert instance.hooks_after_new_session == []
    assert instance.hooks_pre_chat == []


def test_real_module_receives_same_instance_once_in_same_process(monkeypatch, tmp_path):
    """The real named entry delivers the live instance exactly once in-process."""
    prompt_module = _prompt_base(monkeypatch)
    marker = tmp_path / "module-result.jsonl"
    module = _write_module(
        tmp_path / "real_module.py",
        "import json\n"
        "import os\n"
        f"MARKER = {str(marker)!r}\n"
        "def main(*, prompt_base):\n"
        "    prompt_base._hook_test_marker = 'set-by-module'\n"
        "    with open(MARKER, 'a', encoding='utf-8') as output:\n"
        "        json.dump({'object_id': id(prompt_base), 'pid': os.getpid()}, output)\n"
        "        output.write('\\n')\n",
    )
    hooks.initialize_hook_points({NAME: {"modules": str(module)}})

    instance = prompt_module.PromptBase("system")

    records = [json.loads(line) for line in marker.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0] == {"object_id": id(instance), "pid": os.getpid()}
    assert instance._hook_test_marker == "set-by-module"


def test_real_module_recorder_detects_double_invocation(tmp_path):
    """The invocation recorder preserves separate entries for repeated calls."""
    marker = tmp_path / "module-result.jsonl"
    module = _write_module(
        tmp_path / "real_module.py",
        "import json\n"
        f"MARKER = {str(marker)!r}\n"
        "def main(*, prompt_base):\n"
        "    with open(MARKER, 'a', encoding='utf-8') as output:\n"
        "        json.dump({'object_id': id(prompt_base)}, output)\n"
        "        output.write('\\n')\n",
    )
    import importlib.util

    spec = importlib.util.spec_from_file_location("double_invocation_module", module)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    prompt_base = object()

    loaded.main(prompt_base=prompt_base)
    loaded.main(prompt_base=prompt_base)

    records = [json.loads(line) for line in marker.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert records[0] == records[1] == {"object_id": id(prompt_base)}


def test_ordinary_module_failure_executes_and_does_not_break_constructor(monkeypatch, tmp_path):
    """An ordinary Module failure is reported and construction continues."""
    prompt_module = _prompt_base(monkeypatch)
    marker = tmp_path / "failure-executed"
    module = _write_module(
        tmp_path / "ordinary_failure.py",
        "def main(*, prompt_base):\n"
        f"    open({str(marker)!r}, 'w', encoding='utf-8').write('executed')\n"
        "    raise RuntimeError('ordinary hook failure')\n",
    )
    hooks.initialize_hook_points({NAME: {"modules": str(module)}})

    instance = prompt_module.PromptBase("system")

    assert marker.read_text(encoding="utf-8") == "executed"
    assert instance.system_prompt == "system"
    assert instance.hooks_pre_chat == []


@pytest.mark.parametrize(
    "exception_type",
    (KeyboardInterrupt, SystemExit, asyncio.CancelledError),
)
def test_host_control_flow_exceptions_are_not_swallowed(monkeypatch, tmp_path, exception_type):
    """Host control-flow exceptions from a Module retain propagation semantics."""
    prompt_module = _prompt_base(monkeypatch)
    exception_name = {
        KeyboardInterrupt: "KeyboardInterrupt",
        SystemExit: "SystemExit",
        asyncio.CancelledError: "asyncio.CancelledError",
    }[exception_type]
    module = _write_module(
        tmp_path / "interrupt.py",
        "import asyncio\n"
        f"def main(*, prompt_base):\n    raise {exception_name}('stop')\n",
    )
    hooks.initialize_hook_points({NAME: {"modules": str(module)}})

    with pytest.raises(exception_type, match="stop"):
        prompt_module.PromptBase("system")
