'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-14
  Purpose: Unit tests for workspace/project_workspace.py, which resolves the
           project workspace from the environment with a fallback that reads the
           persisted session record through the topsailai_session_info command.
'''

import json
import os
import subprocess
import time
from collections import OrderedDict

import pytest

from topsailai.workspace import project_workspace


@pytest.fixture(autouse=True)
def _isolated_lookup(monkeypatch):
    """Clear cached lookups and every environment name the resolver reads."""
    monkeypatch.setattr(project_workspace, "_LOOKUP_CACHE", OrderedDict())
    for name in (
        "TOPSAILAI_PROJECT_WORKSPACE",
        "TOPSAILAI_PROJECT_FOLDER",
        "SESSION_ID",
        "TOPSAILAI_SESSION_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def _fake_lookup(monkeypatch, payload, calls=None):
    """Replace the subprocess boundary with a canned session-info response.

    The command is stubbed as well, so the tests never depend on whether the
    real CLI is installed on the host.
    """
    monkeypatch.setattr(
        project_workspace, "_resolve_lookup_command", lambda: "/fake/session_info",
    )

    def fake_run(cmd):
        """Record the invocation and return the canned payload."""
        if calls is not None:
            calls.append(cmd)
        stdout = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr(project_workspace, "_run_lookup_command", fake_run)


def test_explicit_argument_wins_over_environment(monkeypatch):
    """An explicit argument is returned unchanged."""
    monkeypatch.setenv("TOPSAILAI_PROJECT_WORKSPACE", "/env/wins")

    assert project_workspace.resolve_project_workspace("/explicit") == "/explicit"


def test_environment_variable_wins_without_invoking_the_command(monkeypatch):
    """The environment is preferred, so the command is never spawned."""
    monkeypatch.setenv("TOPSAILAI_PROJECT_WORKSPACE", "/env/wins")

    def explode(cmd):
        """Fail the test if the fallback is reached."""
        raise AssertionError(f"command must not run: {cmd}")

    monkeypatch.setattr(project_workspace, "_run_lookup_command", explode)

    assert project_workspace.resolve_project_workspace(session_id="s-env") == "/env/wins"


def test_project_folder_environment_is_the_second_choice(monkeypatch):
    """TOPSAILAI_PROJECT_FOLDER is used when the primary name is absent."""
    monkeypatch.setenv("TOPSAILAI_PROJECT_FOLDER", "/env/folder")

    def explode(cmd):
        """Fail the test if the fallback is reached."""
        raise AssertionError(f"command must not run: {cmd}")

    monkeypatch.setattr(project_workspace, "_run_lookup_command", explode)

    assert project_workspace.resolve_project_workspace(session_id="s-folder") == "/env/folder"


def test_persisted_record_is_the_fallback(monkeypatch):
    """With no environment value the persisted workspace is returned."""
    _fake_lookup(monkeypatch, {
        "session_id": "s-cli", "project_workspace": "/persisted/ws",
    })

    assert project_workspace.resolve_project_workspace(session_id="s-cli") == "/persisted/ws"


def test_command_receives_the_json_flag_and_session_id(monkeypatch):
    """The fallback must ask the command for JSON about the exact session."""
    calls = []
    _fake_lookup(monkeypatch, {"project_workspace": "/persisted/ws"}, calls)

    project_workspace.resolve_project_workspace(session_id="s-args")

    assert calls == [["/fake/session_info", "--json", "s-args"]]


def test_unknown_session_error_code_yields_none(monkeypatch):
    """An unknown session is reported as error_code with exit status zero."""
    _fake_lookup(monkeypatch, {
        "session_id": "s-unknown",
        "error_code": "session_not_found",
        "message": "Session not found: s-unknown",
    })

    assert project_workspace.resolve_project_workspace(session_id="s-unknown") is None


def test_error_code_wins_over_a_present_workspace(monkeypatch):
    """A failure document must not be read as a successful record."""
    _fake_lookup(monkeypatch, {
        "error_code": "lookup_failed",
        "project_workspace": "/should/not/be/used",
    })

    assert project_workspace.resolve_project_workspace(session_id="s-err") is None


def test_empty_workspace_yields_none(monkeypatch):
    """An empty or whitespace-only workspace is a miss."""
    _fake_lookup(monkeypatch, {"session_id": "s-empty", "project_workspace": "   "})

    assert project_workspace.resolve_project_workspace(session_id="s-empty") is None


def test_absent_workspace_yields_none(monkeypatch):
    """A record without the field is a miss."""
    _fake_lookup(monkeypatch, {"session_id": "s-absent"})

    assert project_workspace.resolve_project_workspace(session_id="s-absent") is None


def test_unparseable_output_yields_none(monkeypatch):
    """A non-JSON document is a miss instead of an exception."""
    _fake_lookup(monkeypatch, "not json at all")

    assert project_workspace.resolve_project_workspace(session_id="s-bad") is None


def test_non_object_payload_yields_none(monkeypatch):
    """A JSON array is not a session record."""
    _fake_lookup(monkeypatch, [{"project_workspace": "/persisted/ws"}])

    assert project_workspace.resolve_project_workspace(session_id="s-array") is None


def test_empty_output_yields_none(monkeypatch):
    """No output is a miss."""
    _fake_lookup(monkeypatch, "")

    assert project_workspace.resolve_project_workspace(session_id="s-silent") is None


def test_missing_command_degrades_to_none(monkeypatch):
    """An unavailable command must degrade instead of failing the caller."""
    monkeypatch.setattr(project_workspace, "_resolve_lookup_command", lambda: None)

    assert project_workspace.resolve_project_workspace(session_id="s-nocmd") is None


def test_timeout_degrades_to_none(monkeypatch):
    """A timeout must degrade instead of failing the caller."""
    monkeypatch.setattr(
        project_workspace, "_resolve_lookup_command", lambda: "/fake/session_info",
    )

    def slow(cmd):
        """Simulate a command that exceeds its deadline."""
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(project_workspace, "_run_lookup_command", slow)

    assert project_workspace.resolve_project_workspace(session_id="s-slow") is None


def test_missing_executable_degrades_to_none(monkeypatch):
    """A vanished executable must degrade instead of raising."""
    monkeypatch.setattr(
        project_workspace, "_resolve_lookup_command", lambda: "/fake/session_info",
    )

    def gone(cmd):
        """Simulate an executable that disappeared after discovery."""
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(project_workspace, "_run_lookup_command", gone)

    assert project_workspace.resolve_project_workspace(session_id="s-gone") is None


def test_session_identity_comes_from_the_environment(monkeypatch):
    """The runtime session identity is used when no identity is passed."""
    calls = []
    _fake_lookup(monkeypatch, {"project_workspace": "/persisted/ws"}, calls)
    monkeypatch.setenv("SESSION_ID", "s-runtime")

    assert project_workspace.resolve_project_workspace() == "/persisted/ws"
    assert calls == [["/fake/session_info", "--json", "s-runtime"]]


def test_successful_lookup_is_cached(monkeypatch):
    """A hit is cached, so a repeated resolution does not spawn the command."""
    calls = []
    _fake_lookup(monkeypatch, {"project_workspace": "/persisted/ws"}, calls)

    first = project_workspace.resolve_project_workspace(session_id="s-cache")
    second = project_workspace.resolve_project_workspace(session_id="s-cache")

    assert first == second == "/persisted/ws"
    assert len(calls) == 1


def test_miss_is_not_cached(monkeypatch):
    """A miss is not cached, so a record created later is still observable."""
    calls = []
    _fake_lookup(monkeypatch, {"error_code": "session_not_found"}, calls)

    assert project_workspace.resolve_project_workspace(session_id="s-late") is None

    _fake_lookup(monkeypatch, {"project_workspace": "/persisted/late"}, calls)

    assert project_workspace.resolve_project_workspace(session_id="s-late") == "/persisted/late"
    assert len(calls) == 2


def test_lookup_cache_is_bounded(monkeypatch):
    """The cache must not grow without limit in a long-lived process."""
    monkeypatch.setattr(project_workspace, "_LOOKUP_CACHE_MAX_ENTRIES", 3)
    _fake_lookup(monkeypatch, {"project_workspace": "/persisted/ws"})

    for index in range(10):
        assert project_workspace.resolve_project_workspace(
            session_id=f"s-bounded-{index}"
        ) == "/persisted/ws"

    assert len(project_workspace._LOOKUP_CACHE) <= 3


def test_command_is_discovered_through_path(monkeypatch):
    """A command on PATH is preferred over the project fallback."""
    monkeypatch.setattr(
        project_workspace.shutil, "which", lambda name: "/usr/bin/topsailai_session_info",
    )

    assert project_workspace._resolve_lookup_command() == "/usr/bin/topsailai_session_info"


def test_command_falls_back_to_the_project_bin_directory(monkeypatch):
    """A minimal PATH must not silently disable the fallback."""
    monkeypatch.setattr(project_workspace.shutil, "which", lambda name: None)

    resolved = project_workspace._resolve_lookup_command()

    assert resolved is not None
    assert resolved.endswith(os.path.join("bin", "topsailai_session_info"))
    assert os.path.isfile(resolved)


def test_command_is_none_when_nothing_is_available(monkeypatch, tmp_path):
    """An absent command is reported as None rather than a broken path."""
    monkeypatch.setattr(project_workspace.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        project_workspace.os.path, "isfile", lambda path: False,
    )

    assert project_workspace._resolve_lookup_command() is None


def test_timeout_kills_the_whole_process_group(monkeypatch, tmp_path):
    """A timeout must not leave the grandchild worker running.

    The command is a dispatcher wrapper, so the real worker is a grandchild.
    Killing only the direct child would report a clean timeout while the worker
    keeps consuming CPU.
    """
    pidfile = tmp_path / "grandchild.pid"
    script = tmp_path / "spawner.sh"
    script.write_text(
        "#!/bin/sh\n"
        f"sleep 300 &\n"
        f"echo $! > {pidfile}\n"
        "wait\n"
    )
    script.chmod(0o755)
    monkeypatch.setattr(project_workspace, "_LOOKUP_TIMEOUT", 1)

    with pytest.raises(subprocess.TimeoutExpired):
        project_workspace._run_lookup_command([str(script)])

    deadline = time.time() + 5
    while not pidfile.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert pidfile.exists(), "the grandchild never started"

    grandchild = int(pidfile.read_text().strip())
    deadline = time.time() + 5
    alive = True
    while time.time() < deadline:
        try:
            os.kill(grandchild, 0)
        except OSError:
            alive = False
            break
        time.sleep(0.05)

    assert not alive, f"grandchild {grandchild} survived the timeout"
