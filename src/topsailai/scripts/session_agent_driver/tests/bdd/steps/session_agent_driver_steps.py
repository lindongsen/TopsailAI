"""Step definitions for the session agent driver BDD scenarios.

Every step text is prefixed with the words ``driver`` / ``session`` /
``analysis agent`` so it cannot collide with the project-root BDD suites in
``tests/bdd/steps`` (pytest-bdd silently lets identically-parsed steps
override each other).
"""

from __future__ import annotations

import pytest
from pytest_bdd import given, then, when

from tests.bdd.harness import (
    TARGET_SESSION,
    run_driver,
)
from plugins.tools.exit_process import is_exit_requested


@pytest.fixture
def ctx() -> dict:
    """Per-scenario state: scripted status sequence and agent action."""
    return {
        "status_sequence": [],
        "agent_action": "inject",
        "result": None,
    }


@given("a target session waiting for input")
def target_waiting_for_input(ctx: dict) -> None:
    """The session is alive and holds its pipe; the driver will analyze it."""
    ctx["status_sequence"] = ["input", "input", "idle"]


@given("a target session whose process has exited")
def target_process_exited(ctx: dict) -> None:
    """The session process is gone; the driver must exit."""
    ctx["status_sequence"] = ["idle"]


@given("a target session that is running")
def target_running(ctx: dict) -> None:
    """The session is alive but not waiting for input; the driver waits."""
    ctx["status_sequence"] = ["running", "idle"]


@given("an analysis agent that decides to inject input")
def agent_decides_inject(ctx: dict) -> None:
    """The scripted analysis agent calls inject_input during its run."""
    ctx["agent_action"] = "inject"


@given("an analysis agent that decides the goal is complete")
def agent_decides_exit(ctx: dict) -> None:
    """The scripted analysis agent calls exit_process during its run."""
    ctx["agent_action"] = "exit"


@given("an analysis agent whose injection fails")
def agent_injection_fails(ctx: dict) -> None:
    """The scripted analysis agent raises AgentEndProcess during its run."""
    ctx["agent_action"] = "fail"


@when("the driver runs one polling cycle")
def driver_runs_cycle(ctx: dict) -> None:
    """Run the real driver loop with the scripted boundaries."""
    ctx["result"] = run_driver(ctx["status_sequence"], ctx["agent_action"])


@when("the driver checks the session status")
def driver_checks_status(ctx: dict) -> None:
    """Run the real driver loop; the first status decides the outcome."""
    ctx["result"] = run_driver(ctx["status_sequence"], ctx["agent_action"])


@then("the target session receives the injected input")
def target_receives_input(ctx: dict) -> None:
    """The analysis agent delivered input through the inject_input tool."""
    _code, stub = ctx["result"]
    assert stub.injected_content is not None
    assert "input injected" in stub.injected_content


@then("the driver continues polling")
def driver_continues(ctx: dict) -> None:
    """The driver loop exits normally (code 0) after the scripted sequence."""
    code, _stub = ctx["result"]
    assert code == 0


@then("the driver requests exit")
def driver_requests_exit(ctx: dict) -> None:
    """The exit_process tool set the shared exit flag."""
    assert is_exit_requested()


@then("the driver stops polling")
def driver_stops(ctx: dict) -> None:
    """The driver loop terminated because the exit flag was set."""
    code, _stub = ctx["result"]
    assert code == 0
    assert is_exit_requested()


@then("the driver exits its polling loop")
def driver_exits_loop(ctx: dict) -> None:
    """The driver loop terminated normally on the idle status."""
    code, _stub = ctx["result"]
    assert code == 0


@then("the analysis agent shuts down completely")
def agent_shuts_down(ctx: dict) -> None:
    """The analysis agent ran and was aborted by AgentEndProcess."""
    _code, stub = ctx["result"]
    assert stub.run_called


@then("the driver does not start an analysis agent")
def driver_no_agent(ctx: dict) -> None:
    """No analysis agent ran while the session was running."""
    _code, stub = ctx["result"]
    assert not stub.run_called
