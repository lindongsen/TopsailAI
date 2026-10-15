"""Harness for the session agent driver BDD scenarios.

The harness drives the real driver polling loop (``session_agent_driver.main``)
with the external boundaries stubbed:

- ``check_session_status`` returns a scripted status sequence.
- ``get_agent_chat`` returns a scripted analysis-agent stub whose ``run``
  performs one observable action: inject input, request exit, or raise
  ``AgentEndProcess`` (injection failure).
- ``get_session_info`` returns a fixed session-info dictionary.
- ``cleanup_analysis_session`` is a no-op.
- ``time.sleep`` is a no-op so scenarios run instantly.
- ``inject_input``'s transport (``execute_runtime_request``) is stubbed to
  succeed, so the real tool function runs end-to-end without a real session.

No real LLM, no real topsailai session, and no real FIFO pipe are involved;
the scenarios assert on the driver's observable behavior only.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import session_agent_driver as sad  # noqa: E402
from ai_base.agent_types.exception import AgentEndProcess  # noqa: E402
from plugins.tools import inject_input as inject_input_module  # noqa: E402
from plugins.tools.exit_process import exit_process  # noqa: E402
from plugins.tools.inject_input import inject_input  # noqa: E402

TARGET_SESSION = "bdd-target-session"
INJECTED_CONTENT = "continue please"


class _OkResult:
    """Fake runtime-request result that reports success."""

    ok = True
    error_code = None
    message = "ok"


class AnalysisAgentStub:
    """Fake analysis agent whose ``run`` performs one scripted action."""

    def __init__(self, action: str) -> None:
        self.action = action  # "inject" | "exit" | "fail"
        self.run_called = False
        self.injected_content: str | None = None

    def run(self, times: int = 1, need_interactive: bool = False) -> None:
        """Perform the scripted action, mirroring a real analysis agent."""
        self.run_called = True
        if self.action == "inject":
            self.injected_content = inject_input(TARGET_SESSION, INJECTED_CONTENT)
        elif self.action == "exit":
            exit_process(TARGET_SESSION)
        elif self.action == "fail":
            raise AgentEndProcess(
                f"inject_input failed for session {TARGET_SESSION}: pipe closed"
            )


def run_driver(status_sequence: list[str], agent_action: str) -> tuple[int, AnalysisAgentStub]:
    """Run the real driver loop with stubbed boundaries.

    Args:
        status_sequence: Scripted return values for ``check_session_status``.
        agent_action: Scripted analysis-agent action ("inject", "exit", "fail").

    Returns:
        (exit_code, agent_stub) so scenarios can assert on the outcome.
    """
    agent_stub = AnalysisAgentStub(agent_action)
    session_info = {
        "session_id": TARGET_SESSION,
        "pid": 4242,
        "status": "input",
        "project_workspace": "/tmp/bdd-workspace",
        "created_at": "2026-10-12T00:00:00",
    }
    with mock.patch.object(sad, "check_session_status", side_effect=status_sequence), \
            mock.patch.object(sad, "get_session_info", return_value=session_info), \
            mock.patch.object(sad, "_session_snapshot", return_value=([
                {"pid": session_info["pid"], "ctime": session_info["created_at"],
                 "status": "input", "is_task": False}], "input")), \
            mock.patch.object(sad, "get_agent_chat", return_value=agent_stub), \
            mock.patch.object(sad, "cleanup_analysis_session", return_value=None), \
            mock.patch.object(sad.time, "sleep", return_value=None), \
            mock.patch.object(
                inject_input_module, "execute_runtime_request", return_value=_OkResult()
            ):
        code = sad.main(["--session", TARGET_SESSION, "--poll-interval", "1"])
    return code, agent_stub
