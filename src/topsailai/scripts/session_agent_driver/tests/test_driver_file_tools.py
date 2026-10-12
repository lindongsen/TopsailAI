"""Regression tests for the driver file tool selection.

Author: DawsonLin
"""
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session_agent_driver as sad


@pytest.mark.parametrize("environment, enabled, disabled", [
    ({}, "+", ""),
    ({"TOPSAILAI_ENABLED_TOOLS": "", "ENABLED_TOOLS": ""}, "+", ""),
    ({"TOPSAILAI_ENABLED_TOOLS": "*"}, "*", ""),
    ({"TOPSAILAI_ENABLED_TOOLS": "+"}, "+", ""),
    ({"TOPSAILAI_ENABLED_TOOLS": "cmd_tool;skill_tool",
      "TOPSAILAI_DISABLED_TOOLS": "ssh_tool"}, "cmd_tool;skill_tool", "ssh_tool"),
    ({"ENABLED_TOOLS": "cmd_tool,skill_tool", "DISABLED_TOOLS": "ssh_tool"},
     "cmd_tool,skill_tool", "ssh_tool"),
])
def test_file_selection_preserves_other_tools(environment, enabled, disabled):
    """Keep existing selectors and only add readonly file tool selection."""
    with mock.patch.dict(os.environ, environment, clear=True):
        sad._configure_file_tools()
        assert os.environ["TOPSAILAI_ENABLED_TOOLS"] == enabled + ";file_readonly_tool;inject_input;exit_process"
        assert os.environ["TOPSAILAI_DISABLED_TOOLS"] == disabled + ";file_tool"


@pytest.mark.parametrize("selector", [None, "", "+", "*", "cmd_tool;skill_tool"])
@pytest.mark.parametrize("plugin_tools", [None, "", " \t ", "plugins.tools", "plugins.tools,plugins.tools"])
def test_fresh_process_registers_readonly_and_other_tools(plugin_tools, selector):
    """Verify registration and the actual agent runtime tool inventory."""
    environment = os.environ.copy()
    for name in ("TOPSAILAI_ENABLED_TOOLS", "ENABLED_TOOLS",
                 "TOPSAILAI_DISABLED_TOOLS", "DISABLED_TOOLS"):
        environment.pop(name, None)
    if selector is not None:
        environment["TOPSAILAI_ENABLED_TOOLS"] = selector
    environment.pop("PLUGIN_TOOLS", None)
    if plugin_tools is None:
        environment.pop("TOPSAILAI_PLUGIN_TOOLS", None)
    else:
        environment["TOPSAILAI_PLUGIN_TOOLS"] = plugin_tools
    code = """
import sys
import session_agent_driver
assert session_agent_driver.os.environ["TOPSAILAI_PLUGIN_TOOLS"] == "plugins.tools"
from topsailai.tools.base.common import TOOLS, get_tools_for_chat
names = set(TOOLS)
assert any(name.startswith('file_readonly_tool-') for name in names)
assert not any(name.startswith('file_tool-') for name in names)
for prefix in ('cmd_tool-', 'skill_tool-', 'inject_input-', 'exit_process-'):
    assert any(name.startswith(prefix) for name in names), prefix
from unittest import mock
from topsailai.workspace.agent_shell import get_ai_agent
with mock.patch('topsailai.ai_base.llm_base.LLMModel'):
    agent = get_ai_agent(disabled_tools=['agent_tool', 'human_tool', 'file_tool'])
    try:
        supported = set(agent.runtime.available_tools)
        for prefix in ('file_readonly_tool-', 'cmd_tool-', 'skill_tool-',
                       'inject_input-', 'exit_process-'):
            assert any(name.startswith(prefix) for name in supported), prefix
        for prefix in ('file_tool-', 'human_tool-', 'agent_tool-'):
            assert not any(name.startswith(prefix) for name in supported), prefix
        if '*' not in session_agent_driver.os.environ['TOPSAILAI_ENABLED_TOOLS'].replace(',', ';').split(';'):
            for module in tuple(sys.modules.values()):
                module_name = getattr(module, '__name__', '')
                if not module_name.startswith('topsailai.tools.'):
                    continue
                if getattr(module, 'FLAG_TOOL_ENABLED', None) is not False:
                    continue
                name = module_name.rsplit('.', 1)[-1]
                if name == 'file_readonly_tool':
                    continue
                assert not any(tool.startswith(name + '-') for tool in names), name
                assert not any(tool.startswith(name + '-') for tool in supported), name
        else:
            assert any(name.startswith('sandbox_tool-') for name in supported)
        assert all(callable(tool) for tool in agent.runtime.available_tools.values())
        schemas = get_tools_for_chat(agent.runtime.available_tools)
        for prefix, required in (('inject_input-', ['session_id', 'content']),
                                 ('exit_process-', [])):
            tool_name = next(name for name in supported if name.startswith(prefix))
            schema = schemas[tool_name]['function']
            assert schema['name'] == tool_name
            assert schema['parameters']['required'] == required
    finally:
        agent.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(sad.__file__).parent), env=environment,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("environment, expected", [
    ({"TOPSAILAI_PLUGIN_TOOLS": "custom.first,custom.second"},
     "custom.first;custom.second;plugins.tools"),
    ({"PLUGIN_TOOLS": "legacy.tools"}, "legacy.tools;plugins.tools"),
    ({"TOPSAILAI_PLUGIN_TOOLS": "custom.tools;plugins.tools",
      "PLUGIN_TOOLS": "custom.tools;legacy.tools"},
     "custom.tools;plugins.tools;legacy.tools"),
])
def test_plugin_configuration_is_incremental(environment, expected):
    """Preserve configured packages and append mandatory plugins exactly once."""
    with mock.patch.dict(os.environ, environment, clear=True):
        sad._configure_plugin_tools()
        assert os.environ["TOPSAILAI_PLUGIN_TOOLS"] == expected
        sad._configure_plugin_tools()
        assert os.environ["TOPSAILAI_PLUGIN_TOOLS"] == expected


@pytest.mark.parametrize("excluded", ["inject_input", "exit_process", "file_readonly_tool", "inject"])
def test_mandatory_tool_disable_conflict_is_explicit(excluded):
    """Reject conflicting exclusions rather than silently running without tools."""
    with mock.patch.dict(os.environ, {"TOPSAILAI_DISABLED_TOOLS": excluded}, clear=True):
        with pytest.raises(ValueError, match="Required driver tools are disabled"):
            sad._configure_file_tools()
