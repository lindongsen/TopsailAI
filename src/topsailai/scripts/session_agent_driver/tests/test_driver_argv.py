"""Regression tests for driver argument isolation.

Author: DawsonLin
"""
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session_agent_driver as sad


@pytest.mark.parametrize("failure", [None, "factory", "run"])
def test_analysis_restores_driver_arguments(failure):
    """Keep CLI arguments out of agent input and restore them on every exit."""
    original = ["driver", "-s", "target", "--poll-interval", "5"]

    def run(**kwargs):
        """Observe isolated arguments at the execution boundary."""
        assert sys.argv == ["driver"]
        if failure == "run":
            raise RuntimeError("run failed")

    def factory(**kwargs):
        """Observe isolated arguments and the explicit rendered prompt."""
        assert sys.argv == ["driver"]
        assert kwargs["message"] == "rendered prompt"
        if failure == "factory":
            raise RuntimeError("factory failed")
        return mock.Mock(run=run)

    with mock.patch.object(sys, "argv", original), \
            mock.patch.object(sad, "check_session_status", return_value="input"), \
            mock.patch.object(sad, "get_session_info", return_value={"status": "input"}), \
            mock.patch.object(sad, "render_analysis_prompt", return_value="rendered prompt"), \
            mock.patch.object(sad, "get_agent_chat", side_effect=factory), \
            mock.patch.object(sad, "cleanup_analysis_session"), \
            mock.patch.object(sad.signal, "signal"), \
            mock.patch.object(sad.signal, "alarm"):
        sad.run_analysis_agent("target")
        assert sys.argv is original
