"""Explicit loading and registration-source regression tests; author: DawsonLin."""

from types import SimpleNamespace

import pytest

from plugin_harness import inspect_plugin


@pytest.mark.parametrize("configured,enabled,disabled,present", [
    (False, "*", "", False),
    (True, "*", "", True),
    (True, "agent_tool", "", True),
    (True, "*", "agent_tool", False),
    (True, "", "", False),
])
def test_explicit_loading(tmp_path, configured, enabled, disabled, present):
    """Configuration and existing enable/disable rules both govern availability."""
    result = inspect_plugin(tmp_path, configured, enabled, disabled)
    expected = sorted("agent_tool-" + name for name in
                      ("WritingAssistant", "ProgrammingAssistant", "WritingAssistantMultiTasks"))
    assert result["names"] == (expected if present else [])
    assert result["story_callable"]
    assert result["bigfile_present"] == (configured and enabled == "*")
    if present:
        assert result["source"] == "plugins.tools.agent_tool"
        assert "Unless the user explicitly" in result["prompt"]
    else:
        assert not result["prompt"]
        assert result["source"] is None


def test_registration_source_prompt_observation_reload(monkeypatch):
    """A plugin importing a core function still owns its prompt and reload hook."""
    from topsailai.utils import module_tool
    from topsailai.tools.base import init
    from topsailai.prompt_hub import prompt_tool
    from topsailai.tools.agent_tool_utils.writer import agent_writer

    calls = []
    plugin = SimpleNamespace(TOOLS={"Write": agent_writer}, PROMPT="plugin prompt",
                             OBSERVATION="plugin observation", reload=lambda: calls.append(1))
    monkeypatch.setattr(module_tool, "list_sub_mods_name", lambda path: ["agent_tool"])
    monkeypatch.setattr(module_tool, "get_mod", lambda path: plugin)
    monkeypatch.setattr(module_tool, "get_var", lambda *args, **kwargs: plugin.TOOLS)
    sources = {}
    tools = module_tool.get_external_function_map("example.tools", conn_char="-",
                                                   module_sources=sources)
    assert tools["agent_tool-Write"] is agent_writer
    assert sources == {"agent_tool": "example.tools.agent_tool"}
    monkeypatch.setattr(init, "TOOL_MODULES", sources)
    monkeypatch.setitem(__import__("sys").modules, "example.tools.agent_tool", plugin)
    assert prompt_tool.get_prompt_from_module("agent_tool") == "plugin prompt"
    assert "plugin observation" in prompt_tool.get_observation_by_tools(list(tools))
    prompt_tool.reload_prompt_on_module("agent_tool")
    assert calls == [1]
    assert prompt_tool._get_tool_module_path("cmd_tool") == "topsailai.tools.cmd_tool"


def test_workspace_has_no_package_initializers():
    """Keep plugin discovery independent of package marker files."""
    from pathlib import Path

    workspace = Path(__file__).resolve().parents[1]
    assert not (workspace / "__init__.py").exists()
    assert not (workspace / "tools" / "__init__.py").exists()
