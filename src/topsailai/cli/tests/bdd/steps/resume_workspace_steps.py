"""Step definitions for resuming a session in its persisted project workspace.

The scenarios drive the real resume boundary in ``cli_topsailai.project_scope``
with a fake spawn seam, so the workspace validation, the environment export and
the environment restoration are all inside the assertion boundary. Only the
child process itself is replaced, because a real driver would start an agent.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from pytest_bdd import given, parsers, then, when

from cli_topsailai import project_scope


WORKSPACE_ENV = "TOPSAILAI_PROJECT_WORKSPACE"


class FakeChild:
    """Stand-in for a launched driver process."""

    def __init__(self) -> None:
        """Record a stable process identity for the launch receipt."""
        self.pid = 4242

    def wait(self) -> int:
        """Report a clean child exit."""
        return 0


@pytest.fixture
def resume_context(tmp_path: Path) -> dict[str, Any]:
    """Provide scenario-local workspaces, records and launch observations."""
    home = tmp_path / "resume-home"
    home.mkdir()
    caller = tmp_path / "caller"
    caller.mkdir()
    return {
        "home": home,
        "caller": caller,
        "records": {},
        "workspaces": {},
        "launches": [],
        "status": None,
        "original_cwd": os.getcwd(),
        "original_workspace": os.environ.get(WORKSPACE_ENV),
    }


def _fake_spawn(context: dict[str, Any]):
    """Build a spawn seam that records the launch instead of starting a driver."""

    def spawn(argv, **kwargs):
        """Record the argv, working directory and environment of one launch."""
        context["launches"].append(
            {
                "argv": argv,
                "cwd": kwargs.get("cwd"),
                "env": dict(kwargs.get("env") or {}),
            }
        )
        return FakeChild()

    return spawn


def _resume(context: dict[str, Any], session_id: str) -> int:
    """Run the real resume boundary for one persisted session."""
    record = context["records"][session_id]
    return project_scope.resume_session_result(
        session_id,
        query=lambda _sid: [record],
        emit_status=False,
        driver="topsailai_agent_plan_tasks",
        spawn=_fake_spawn(context),
        home=str(context["home"]),
    )


@given("an isolated resume home and caller directory")
def isolated_environment(resume_context: dict[str, Any]) -> None:
    """Confirm the scenario uses an isolated home and caller directory."""
    assert resume_context["home"] != Path.home()
    assert resume_context["caller"].is_dir()


@given(parsers.parse('a persisted session "{session_id}" whose workspace is "{name}"'))
def persisted_session(resume_context: dict[str, Any], session_id: str, name: str) -> None:
    """Create a workspace directory and a record pointing at it."""
    workspace = resume_context["caller"] / name
    workspace.mkdir()
    resume_context["workspaces"][session_id] = workspace
    resume_context["records"][session_id] = {
        "session_id": session_id,
        "project_workspace": str(workspace),
    }


@given(parsers.parse('a persisted session "{session_id}" whose workspace is empty'))
def persisted_session_without_workspace(
    resume_context: dict[str, Any], session_id: str
) -> None:
    """Record a session that has no persisted workspace."""
    resume_context["records"][session_id] = {
        "session_id": session_id,
        "project_workspace": "",
    }


@given(parsers.parse('a persisted session "{session_id}" whose workspace is missing'))
def persisted_session_with_missing_workspace(
    resume_context: dict[str, Any], session_id: str
) -> None:
    """Record a workspace path that does not exist on disk."""
    resume_context["records"][session_id] = {
        "session_id": session_id,
        "project_workspace": str(resume_context["caller"] / "never-created"),
    }


@given(parsers.parse('a persisted session "{session_id}" whose workspace is relative'))
def persisted_session_with_relative_workspace(
    resume_context: dict[str, Any], session_id: str
) -> None:
    """Record a workspace path that is not absolute."""
    resume_context["records"][session_id] = {
        "session_id": session_id,
        "project_workspace": "relative/project",
    }

@given("the caller has no workspace variable")
def caller_without_workspace(resume_context: dict[str, Any], monkeypatch) -> None:
    """Remove the workspace variable and record the resulting caller state."""
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)
    # The baseline is captured here, after the caller state is established, so
    # the assertion compares against the state the resume must preserve rather
    # than against whatever the ambient test environment happened to export.
    resume_context["original_workspace"] = os.environ.get(WORKSPACE_ENV)


@when(parsers.parse('I resume session "{session_id}"'))
def resume_session(resume_context: dict[str, Any], session_id: str, monkeypatch) -> None:
    """Resume the session and capture the status code."""
    monkeypatch.setattr(project_scope, "session_liveness", lambda *_a, **_k: "idle")
    # The control channel is a separate contract with its own tests. A fake
    # spawn cannot publish a socket, so the confirmation seam is replaced here
    # and the scenario keeps asserting the workspace export and restoration.
    monkeypatch.setattr(
        project_scope,
        "_confirm_resumed_startup",
        lambda *_a, **_k: {
            "startup_confirmed": True,
            "startup_pid": 4242,
            "startup_reason": "test_seam",
        },
    )
    monkeypatch.chdir(resume_context["caller"])
    resume_context["status"] = _resume(resume_context, session_id)


@then("the resume succeeds")
def resume_succeeds(resume_context: dict[str, Any]) -> None:
    """Require a successful resume status."""
    assert resume_context["status"] == 0


@then(parsers.parse("the resume fails with status {expected:d}"))
def resume_fails_with_status(resume_context: dict[str, Any], expected: int) -> None:
    """Require the documented refusal status."""
    assert resume_context["status"] == expected


@then("the launched child ran in the persisted workspace")
def child_ran_in_workspace(resume_context: dict[str, Any]) -> None:
    """Require the child working directory to be the persisted workspace."""
    launches = resume_context["launches"]
    assert len(launches) == 1
    session_id = next(iter(resume_context["workspaces"]))
    expected = str(resume_context["workspaces"][session_id])
    assert launches[0]["cwd"] == expected


@then("the launched child received the persisted workspace variable")
def child_received_workspace_variable(resume_context: dict[str, Any]) -> None:
    """Require the child environment to carry the persisted workspace."""
    launches = resume_context["launches"]
    assert len(launches) == 1
    session_id = next(iter(resume_context["workspaces"]))
    expected = str(resume_context["workspaces"][session_id])
    assert launches[0]["env"].get(WORKSPACE_ENV) == expected


@then("no child was launched")
def no_child_launched(resume_context: dict[str, Any]) -> None:
    """Require that a refused resume never starts a child."""
    assert resume_context["launches"] == []


@then("the caller has no workspace variable")
def caller_workspace_restored(resume_context: dict[str, Any]) -> None:
    """Require the caller environment to be restored after the launch."""
    assert os.environ.get(WORKSPACE_ENV) == resume_context["original_workspace"]
