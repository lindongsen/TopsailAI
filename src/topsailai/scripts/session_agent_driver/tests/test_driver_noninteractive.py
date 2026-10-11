"""Regression tests for noninteractive driver startup.

Author: DawsonLin
"""
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session_agent_driver as sad


@pytest.mark.parametrize("configured", [None, "", "cmd_tool; human_tool;cmd_tool"])
def test_startup_forces_noninteractive_before_framework_imports(configured):
    """Override inherited interaction without losing configured exclusions."""
    source = Path(sad.__file__).read_text().split("SRC_DIR =", 1)[0]
    environment = {"TOPSAILAI_INTERACTIVE_MODE": "1"}
    if configured is not None:
        environment["TOPSAILAI_CLI_AGENT_CHAT_DISABLED_TOOLS"] = configured
    with mock.patch.dict(os.environ, environment, clear=True):
        exec(compile(source, sad.__file__, "exec"), {"__file__": sad.__file__})
        assert os.environ["TOPSAILAI_INTERACTIVE_MODE"] == "0"
        excluded = os.environ["TOPSAILAI_CLI_AGENT_CHAT_DISABLED_TOOLS"].split(";")
        assert {"agent_tool", "human_tool"}.issubset(excluded)
        if configured:
            assert "cmd_tool" in excluded
        assert excluded.count("human_tool") == 1


def test_analysis_disables_input_and_interactive_run():
    """Keep the factory and runner noninteractive with human tools excluded."""
    agent = mock.Mock()
    with mock.patch.object(sad, "check_session_status", return_value="input"), \
            mock.patch.object(sad, "get_session_info", return_value={"status": "input"}), \
            mock.patch.object(sad, "render_analysis_prompt", return_value="prompt"), \
            mock.patch.object(sad, "get_agent_chat", return_value=agent) as factory, \
            mock.patch.object(sad, "cleanup_analysis_session"), \
            mock.patch.object(sad.signal, "signal"), \
            mock.patch.object(sad.signal, "alarm"):
        sad.run_analysis_agent("target")
    assert factory.call_args.kwargs["need_input_message"] is False
    assert factory.call_args.kwargs["disabled_tools"] == ["agent_tool", "human_tool"]
    agent.run.assert_called_once_with(times=1, need_interactive=False)
