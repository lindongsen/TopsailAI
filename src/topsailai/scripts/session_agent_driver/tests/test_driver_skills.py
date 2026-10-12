"""Regression tests for mandatory skill discovery. Author: DawsonLin."""

import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest
import session_agent_driver as sad


@pytest.mark.parametrize("configured", [None, "", " ", "/external/one,/external/two"])
def test_skills_configuration_is_incremental(configured):
    """Retain external directories and add local skills exactly once."""
    environment = {} if configured is None else {sad.PLUGIN_SKILLS_ENV: configured}
    with mock.patch.dict(os.environ, environment, clear=True):
        sad._configure_plugin_skills()
        expected = ["/external/one", "/external/two"] if configured and "/external" in configured else []
        expected.append(str(sad.SCRIPT_DIR / "plugins" / "skills"))
        assert os.environ[sad.PLUGIN_SKILLS_ENV].split(";") == expected
        sad._configure_plugin_skills()
        assert os.environ[sad.PLUGIN_SKILLS_ENV].split(";") == expected


def test_fresh_process_discovers_worker_skill_from_empty_configuration():
    """Discover the actual worker skill through the local directory symlink."""
    environment = os.environ.copy()
    environment["TOPSAILAI_PLUGIN_SKILLS"] = ""
    code = """
import session_agent_driver as sad
from topsailai.skill_hub.skill_tool import get_skill_markdown, g_skills
folder = str(sad.SCRIPT_DIR / 'plugins' / 'skills')
assert folder in sad.os.environ[sad.PLUGIN_SKILLS_ENV].split(';')
prompt = get_skill_markdown(skill_folders=[folder])
assert 'topsailai-agent-worker' in prompt
assert any(info.name == 'topsailai-agent-worker' for info in g_skills.values())
"""
    result = subprocess.run([sys.executable, "-c", code], env=environment,
                            cwd=str(Path(sad.__file__).parent), capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
