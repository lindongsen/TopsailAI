"""Verify explicit output permission without enabling interactive input.

Author: DawsonLin
"""

import pytest

from topsailai.utils import env_tool, print_tool
from topsailai.workspace.print_tool import TeeOutput


@pytest.mark.parametrize("value", [None, "0", "false", "", "invalid", "1", "TRUE", "yes", "on", " enabled "])
@pytest.mark.parametrize("interactive", ["0", "1"])
@pytest.mark.parametrize("debug", ["0", "1"])
def test_output_permission_matrix(monkeypatch, value, interactive, debug):
    """Preserve legacy decisions unless the explicit output override is true."""
    monkeypatch.setenv("TOPSAILAI_INTERACTIVE_MODE", interactive)
    monkeypatch.setenv("DEBUG", debug)
    if value is None:
        monkeypatch.delenv("TOPSAILAI_PRINT_ENABLED", raising=False)
    else:
        monkeypatch.setenv("TOPSAILAI_PRINT_ENABLED", value)
    permitted = interactive == "1" or value in ("1", "TRUE", "yes", "on", " enabled ")
    assert env_tool.is_print_enabled() is permitted
    assert env_tool.is_need_print() is (permitted or debug == "1")
    assert env_tool.is_interactive_mode() is (interactive == "1")


@pytest.mark.parametrize("enabled", ["0", "1"])
def test_noninteractive_steps_reach_tee(monkeypatch, tmp_path, enabled):
    """Capture actual framework steps while leaving input interaction disabled."""
    monkeypatch.setenv("TOPSAILAI_INTERACTIVE_MODE", "0")
    monkeypatch.setenv("TOPSAILAI_PRINT_ENABLED", enabled)
    monkeypatch.setenv("DEBUG", "0")
    monkeypatch.setenv("TOPSAILAI_PRINT_STEP_MODE", "normal")
    monkeypatch.setattr(print_tool, "g_flag_print_step", True)
    from topsailai.utils import thread_local_tool
    monkeypatch.setattr(thread_local_tool, "get_thread_var", lambda key: None)
    path = tmp_path / "session.stdout"
    with TeeOutput(str(path)):
        print_tool.print_step("noninteractive-step", need_format=False)
        print_tool.print_info("noninteractive-info")
        assert env_tool.is_interactive_mode() is False
    text = path.read_text()
    if enabled == "1":
        assert "noninteractive-step" in text
        assert "noninteractive-info" in text
    else:
        assert text == ""
