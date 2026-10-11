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
    ({}, "*", ""),
    ({"TOPSAILAI_ENABLED_TOOLS": "cmd_tool;skill_tool",
      "TOPSAILAI_DISABLED_TOOLS": "ssh_tool"}, "cmd_tool;skill_tool", "ssh_tool"),
    ({"ENABLED_TOOLS": "cmd_tool,skill_tool", "DISABLED_TOOLS": "ssh_tool"},
     "cmd_tool,skill_tool", "ssh_tool"),
])
def test_file_selection_preserves_other_tools(environment, enabled, disabled):
    """Keep existing selectors and only add readonly file tool selection."""
    with mock.patch.dict(os.environ, environment, clear=True):
        sad._configure_file_tools()
        assert os.environ["TOPSAILAI_ENABLED_TOOLS"] == enabled + ";file_readonly_tool"
        assert os.environ["TOPSAILAI_DISABLED_TOOLS"] == disabled + ";file_tool"


def test_fresh_process_registers_readonly_and_other_tools():
    """Verify real import-time registration, not just factory arguments."""
    environment = os.environ.copy()
    for name in ("TOPSAILAI_ENABLED_TOOLS", "ENABLED_TOOLS",
                 "TOPSAILAI_DISABLED_TOOLS", "DISABLED_TOOLS"):
        environment.pop(name, None)
    code = """
import session_agent_driver
from topsailai.tools.base.common import TOOLS
names = set(TOOLS)
assert any(name.startswith('file_readonly_tool-') for name in names)
assert not any(name.startswith('file_tool-') for name in names)
for prefix in ('cmd_tool-', 'skill_tool-', 'inject_input-', 'exit_process-'):
    assert any(name.startswith(prefix) for name in names), prefix
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(sad.__file__).parent), env=environment,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
