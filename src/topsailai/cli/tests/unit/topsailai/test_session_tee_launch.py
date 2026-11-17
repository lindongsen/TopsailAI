"""Tests for session tee output enabled at the CLI launch boundary.

A resumed worker that dies before it can report anything must still leave a
stdout file behind. The tee switch is therefore exported by the launch
boundary, which is the only layer that knows a launch is happening. Core
defaults stay untouched so unrelated agent entry points are unaffected.
"""

import os

import pytest
from unittest.mock import patch

import cli_topsailai.agent_launch_background
from cli_topsailai import agent_launch as agent_launch_module
from cli_topsailai import project_scope
from cli_topsailai.agent_launch import (
    _enable_session_tee,
    _prepare_environment,
    launch_configured_agent,
)

TEE_KEY = "TOPSAILAI_ENABLE_SESSION_TEE_OUT"


@pytest.fixture(autouse=True)
def _isolate_tee_variable():
    """Remove the tee variable around every test and restore the original."""
    original = os.environ.get(TEE_KEY)
    os.environ.pop(TEE_KEY, None)
    try:
        yield
    finally:
        if original is None:
            os.environ.pop(TEE_KEY, None)
        else:
            os.environ[TEE_KEY] = original


@pytest.fixture(autouse=True)
def _fail_fast_on_uninjected_spawn(monkeypatch):
    """Never permit a launch test to fall through to a real process."""
    def fail_fast(*args, **kwargs):
        raise AssertionError("consumer-local fail-fast guard: real process spawn attempted")
    monkeypatch.setattr(agent_launch_module, "_spawn_process", fail_fast)


class FakeChild:
    """Finite child double that records ownership operations."""

    def __init__(self, returncode=0):
        self.returncode = returncode
        self.calls = []

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        return self.returncode

    def poll(self):
        self.calls.append(("poll", None))
        return self.returncode

    def terminate(self):
        self.calls.append(("terminate", None))

    def kill(self):
        self.calls.append(("kill", None))


def _no_model_environment(_folder):
    """Return a model result with no additional environment values."""
    return ({}, set())


def test_enable_session_tee_exports_switch():
    """The launch boundary exports the tee switch without being asked."""
    _enable_session_tee()
    assert os.environ.get(TEE_KEY) == "1"


def test_enable_session_tee_respects_operator_override():
    """An operator who already exported the variable keeps that value."""
    os.environ[TEE_KEY] = "0"
    _enable_session_tee()
    assert os.environ.get(TEE_KEY) == "0"


def test_prepare_environment_does_not_touch_tee_switch(tmp_path):
    """Identity preparation alone must not export the tee switch."""
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment",
               side_effect=_no_model_environment):
        _prepare_environment(str(tmp_path), "wa-fixed")
    assert TEE_KEY not in os.environ


def test_foreground_child_receives_tee_switch(tmp_path):
    """The foreground child environment carries the tee switch."""
    child = FakeChild(returncode=0)
    captured = []
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment",
               return_value=({}, set())):
        result = launch_configured_agent(
            str(tmp_path), mode="raw",
            spawn=lambda argv, **kwargs: (captured.append((argv, kwargs)) or child),
        )
    assert result == 0
    assert captured[0][1]["env"][TEE_KEY] == "1"


def test_foreground_parent_environment_is_restored(tmp_path):
    """The tee switch must not leak into the caller's process."""
    child = FakeChild(returncode=0)
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment",
               return_value=({}, set())):
        result = launch_configured_agent(
            str(tmp_path), mode="raw",
            spawn=lambda argv, **kwargs: child,
        )
    assert result == 0
    assert TEE_KEY not in os.environ


def test_foreground_opt_out_reaches_child(tmp_path):
    """An explicit opt-out must not reach the child environment."""
    child = FakeChild(returncode=0)
    captured = []
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment",
               return_value=({}, set())):
        result = launch_configured_agent(
            str(tmp_path), mode="raw", enable_session_tee=False,
            spawn=lambda argv, **kwargs: (captured.append((argv, kwargs)) or child),
        )
    assert result == 0
    assert TEE_KEY not in captured[0][1]["env"]


def test_background_submission_receives_tee_switch(tmp_path):
    """The background supervisor environment carries the tee switch."""
    captured = []

    def submit(folder, session_id, **kwargs):
        captured.append(kwargs)
        return {"launcher_pid": 1234, "log_path": str(tmp_path / "x.log")}

    with patch("cli_topsailai.agent_launch._session_id", return_value="fixed"), \
         patch("cli_topsailai.agent_launch._apply_selected_model_environment",
               return_value=({}, set())), \
         patch("cli_topsailai.agent_launch_background.launch_background",
               side_effect=submit):
        result = launch_configured_agent(str(tmp_path), mode="raw", background=True)
    assert result == 0
    assert captured[0]["environment"][TEE_KEY] == "1"


def test_launch_env_keys_covers_tee_switch():
    """Snapshot and restore must cover the tee switch."""
    assert TEE_KEY in project_scope._LAUNCH_ENV_KEYS


def test_driver_child_receives_tee_switch():
    """The resume driver child environment carries the tee switch."""
    captured = []

    def spawn(argv, **kwargs):
        captured.append(kwargs)
        return FakeChild(returncode=0)

    with patch.object(project_scope, "_apply_selected_model_environment",
                      return_value=({}, set())), \
         patch.object(project_scope.shutil, "which",
                      side_effect=lambda name: f"/usr/bin/{name}"), \
         patch.object(project_scope.os, "getcwd", return_value="/TopsailAI/cli"), \
         patch.object(project_scope.os, "chdir"):
        code = project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123",
            agent_mode="raw", spawn=spawn,
        )
    assert code == 0
    assert captured[0]["env"][TEE_KEY] == "1"


def test_driver_parent_environment_is_restored():
    """The resume driver must not leak the tee switch into the caller."""
    def spawn(argv, **kwargs):
        return FakeChild(returncode=0)

    with patch.object(project_scope, "_apply_selected_model_environment",
                      return_value=({}, set())), \
         patch.object(project_scope.shutil, "which",
                      side_effect=lambda name: f"/usr/bin/{name}"), \
         patch.object(project_scope.os, "getcwd", return_value="/TopsailAI/cli"), \
         patch.object(project_scope.os, "chdir"):
        code = project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123",
            agent_mode="raw", spawn=spawn,
        )
    assert code == 0
    assert TEE_KEY not in os.environ


def test_driver_opt_out_leaves_variable_unset():
    """An explicit driver opt-out must not export the tee switch."""
    captured = []

    def spawn(argv, **kwargs):
        captured.append(kwargs)
        return FakeChild(returncode=0)

    with patch.object(project_scope, "_apply_selected_model_environment",
                      return_value=({}, set())), \
         patch.object(project_scope.shutil, "which",
                      side_effect=lambda name: f"/usr/bin/{name}"), \
         patch.object(project_scope.os, "getcwd", return_value="/TopsailAI/cli"), \
         patch.object(project_scope.os, "chdir"):
        code = project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123",
            agent_mode="raw", spawn=spawn, enable_session_tee=False,
        )
    assert code == 0
    assert TEE_KEY not in captured[0]["env"]
