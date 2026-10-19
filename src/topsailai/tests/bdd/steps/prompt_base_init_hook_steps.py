"""BDD steps for the PromptBase initialization Hook Point. Author: DawsonLin."""

import json
import os
from types import SimpleNamespace

import pytest
from pytest_bdd import given, then, when

import topsailai.hooks as hooks
from topsailai.hooks.points.aibase.after_prompt_base_init import NAME


@pytest.fixture
def prompt_base_init_context(tmp_path, monkeypatch):
    """Own a real Module fixture and isolate PromptBase dependencies."""
    from topsailai.ai_base import prompt_base as prompt_module

    monkeypatch.setattr(prompt_module, "get_managers_by_env", lambda: [])
    monkeypatch.setattr(prompt_module, "generate_prompt_for_env", lambda: "")
    hooks.initialize_hook_points({})
    context = SimpleNamespace(root=tmp_path, prompt_module=prompt_module, instance=None)
    yield context
    hooks.initialize_hook_points({})


@given("a real PromptBase initialization Module")
def configure_real_module(prompt_base_init_context):
    """Configure a real Module that records identity and process ownership."""
    marker = prompt_base_init_context.root / "result.jsonl"
    module = prompt_base_init_context.root / "observer.py"
    module.write_text(
        "import json\nimport os\n"
        f"def main(*, prompt_base):\n"
        f"    with open({str(marker)!r}, 'a', encoding='utf-8') as output:\n"
        "        json.dump({'object_id': id(prompt_base), 'pid': os.getpid()}, output)\n"
        "        output.write('\\n')\n",
        encoding="utf-8",
    )
    prompt_base_init_context.marker = marker
    hooks.initialize_hook_points({NAME: {"modules": str(module)}})


@given("a failing PromptBase initialization Module")
def configure_failing_module(prompt_base_init_context):
    """Configure a real Module that records execution before failing."""
    marker = prompt_base_init_context.root / "failure-marker"
    module = prompt_base_init_context.root / "failing_observer.py"
    module.write_text(
        "def main(*, prompt_base):\n"
        f"    open({str(marker)!r}, 'w', encoding='utf-8').write('executed')\n"
        "    raise RuntimeError('expected ordinary failure')\n",
        encoding="utf-8",
    )
    prompt_base_init_context.marker = marker
    hooks.initialize_hook_points({NAME: {"modules": str(module)}})


@when("PromptBase is constructed for the Hook scenario")
def construct_prompt_base(prompt_base_init_context):
    """Construct through the real PromptBase constructor and named point."""
    prompt_base_init_context.instance = prompt_base_init_context.prompt_module.PromptBase("system")


@then("the Module ran exactly once with the same PromptBase instance")
def assert_real_delivery(prompt_base_init_context):
    """Assert real Module identity, cardinality and same-process delivery."""
    records = [
        json.loads(line)
        for line in prompt_base_init_context.marker.read_text(encoding="utf-8").splitlines()
    ]
    instance = prompt_base_init_context.instance
    assert len(records) == 1
    assert records[0] == {"object_id": id(instance), "pid": os.getpid()}


@then("PromptBase construction succeeds and the Module failure was executed")
def assert_failure_isolated(prompt_base_init_context):
    """Assert ordinary Module failure was executed and isolated."""
    assert prompt_base_init_context.marker.read_text(encoding="utf-8") == "executed"
    assert prompt_base_init_context.instance.system_prompt == "system"
