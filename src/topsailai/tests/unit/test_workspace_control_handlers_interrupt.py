"""
Unit tests for control-channel interrupt handlers.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-04
Purpose: Verify hard, soft, and clear interrupt handlers
"""

import json

from topsailai.workspace.control_channel.protocol import ControlContext, ControlRequest
from topsailai.workspace.control_handlers.interrupt import (
    ClearInterruptHandler,
    HardInterruptHandler,
    SoftInterruptHandler,
)


def test_hard_interrupt_writes_flag(tmp_path):
    """Hard interrupt writes the target flag and returns the request id."""
    context = ControlContext(session_id="session", pid=123, task_folder=str(tmp_path))
    response = HardInterruptHandler().handle(
        ControlRequest(request_id="hard-1", action="hard_interrupt"),
        context,
    )

    assert response.status == "ok"
    assert response.request_id == "hard-1"
    assert (tmp_path / "session.123.session.agent2llm_interrupt.flag").read_text() == "1"


def test_soft_interrupt_appends_jsonl_message(tmp_path):
    """Soft interrupt appends a consumable Agent2LLM message."""
    context = ControlContext(session_id="session", pid=123, task_folder=str(tmp_path))
    response = SoftInterruptHandler().handle(
        ControlRequest(
            request_id="soft-1",
            action="soft_interrupt",
            payload={"message": "summarize now"},
        ),
        context,
    )

    assert response.status == "ok"
    records = (tmp_path / "session.123.session.agent2llm_inject_messages.jsonl").read_text().splitlines()
    assert len(records) == 1
    assert json.loads(records[0])["content"] == "summarize now"


def test_clear_interrupt_removes_flag(tmp_path):
    """Clear interrupt removes an existing flag."""
    flag_path = tmp_path / "session.123.session.agent2llm_interrupt.flag"
    flag_path.write_text("1")
    context = ControlContext(session_id="session", pid=123, task_folder=str(tmp_path))

    response = ClearInterruptHandler().handle(
        ControlRequest(request_id="clear-1", action="clear_interrupt"),
        context,
    )

    assert response.status == "ok"
    assert response.result["removed"] is True
    assert not flag_path.exists()


def test_interrupt_handler_preserves_request_id_on_validation_error(tmp_path):
    """Validation failures must remain correlated to the original request."""
    response = HardInterruptHandler().handle(
        ControlRequest(request_id="bad-1", action="hard_interrupt"),
        ControlContext(pid=123, task_folder=str(tmp_path)),
    )

    assert response.status == "ok"
    assert response.request_id == "bad-1"
    assert response.result["session_id"] == "topsailai"
