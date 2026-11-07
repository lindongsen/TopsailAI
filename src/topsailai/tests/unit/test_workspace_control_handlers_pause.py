"""
Unit tests for control-channel pause handlers.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-07
Purpose: Verify pause marker creation, payload normalization and clearing
"""

import json

from topsailai.workspace.control_channel.protocol import ControlContext, ControlRequest
from topsailai.workspace.control_handlers.pause import (
    DEFAULT_PAUSE_ANSWER,
    DEFAULT_PAUSE_PROMPT,
    ClearPauseHandler,
    PauseHandler,
    build_pause_payload,
)


def _context(tmp_path):
    """Build a control context that targets a temporary task folder."""
    return ControlContext(session_id="session", pid=123, task_folder=str(tmp_path))


def test_pause_writes_json_marker(tmp_path):
    """Pause writes a JSON marker and reports acceptance, not completion."""
    response = PauseHandler().handle(
        ControlRequest(request_id="pause-1", action="pause"),
        _context(tmp_path),
    )

    assert response.status == "ok"
    assert response.request_id == "pause-1"
    assert response.result["state"] == "pause_requested"
    marker = tmp_path / "session.123.session.agent2llm_pause.flag"
    payload = json.loads(marker.read_text())
    assert payload["prompt"] == DEFAULT_PAUSE_PROMPT
    assert payload["default"] == DEFAULT_PAUSE_ANSWER
    assert payload["timeout_seconds"] == 0.0


def test_pause_marker_is_consumable_json_with_custom_fields(tmp_path):
    """Custom prompt, timeout and default survive into the marker payload."""
    response = PauseHandler().handle(
        ControlRequest(
            request_id="pause-2",
            action="pause",
            payload={
                "reason": "operator check",
                "prompt": "Resume? ",
                "timeout_seconds": 30,
                "default": "interrupt",
            },
        ),
        _context(tmp_path),
    )

    assert response.status == "ok"
    payload = json.loads(
        (tmp_path / "session.123.session.agent2llm_pause.flag").read_text()
    )
    assert payload == {
        "reason": "operator check",
        "prompt": "Resume? ",
        "timeout_seconds": 30.0,
        "default": "interrupt",
    }


def test_pause_rejects_invalid_payload_values(tmp_path):
    """Malformed payload values fall back to safe defaults instead of failing."""
    response = PauseHandler().handle(
        ControlRequest(
            request_id="pause-3",
            action="pause",
            payload={
                "prompt": "   ",
                "timeout_seconds": "soon",
                "default": "maybe",
                "reason": 42,
            },
        ),
        _context(tmp_path),
    )

    assert response.status == "ok"
    payload = json.loads(
        (tmp_path / "session.123.session.agent2llm_pause.flag").read_text()
    )
    assert payload["prompt"] == DEFAULT_PAUSE_PROMPT
    assert payload["timeout_seconds"] == 0.0
    assert payload["default"] == DEFAULT_PAUSE_ANSWER
    assert payload["reason"] == ""


def test_pause_overwrites_existing_marker(tmp_path):
    """A repeated pause request replaces the marker instead of stacking prompts."""
    marker = tmp_path / "session.123.session.agent2llm_pause.flag"
    marker.write_text(json.dumps({"prompt": "first", "default": "continue"}))

    PauseHandler().handle(
        ControlRequest(
            request_id="pause-4", action="pause", payload={"prompt": "second"}
        ),
        _context(tmp_path),
    )

    payload = json.loads(marker.read_text())
    assert payload["prompt"] == "second"
    assert len(list(tmp_path.glob("*.agent2llm_pause.flag"))) == 1


def test_pause_leaves_no_temporary_file(tmp_path):
    """Atomic publication must not leave a staging file behind."""
    PauseHandler().handle(
        ControlRequest(request_id="pause-5", action="pause"),
        _context(tmp_path),
    )

    assert list(tmp_path.glob("*.tmp")) == []


def test_clear_pause_removes_marker(tmp_path):
    """Clear pause removes an existing marker."""
    marker = tmp_path / "session.123.session.agent2llm_pause.flag"
    marker.write_text("{}")

    response = ClearPauseHandler().handle(
        ControlRequest(request_id="clear-1", action="clear_pause"),
        _context(tmp_path),
    )

    assert response.status == "ok"
    assert response.result["removed"] is True
    assert not marker.exists()


def test_clear_pause_is_idempotent(tmp_path):
    """Clearing without a marker reports removed false and stays successful."""
    response = ClearPauseHandler().handle(
        ControlRequest(request_id="clear-2", action="clear_pause"),
        _context(tmp_path),
    )

    assert response.status == "ok"
    assert response.result["removed"] is False


def test_pause_preserves_request_id_on_validation_error(tmp_path):
    """Validation failures remain correlated to the original request."""
    response = PauseHandler().handle(
        ControlRequest(request_id="bad-1", action="pause"),
        ControlContext(pid=123, task_folder=str(tmp_path)),
    )

    assert response.status == "ok"
    assert response.request_id == "bad-1"
    assert response.result["session_id"] == "topsailai"


def test_build_pause_payload_ignores_non_dict_payload():
    """A non-dict payload cannot break marker construction."""
    request = ControlRequest(request_id="pause-6", action="pause")
    request.payload = ["unexpected"]

    payload = build_pause_payload(request)

    assert payload["prompt"] == DEFAULT_PAUSE_PROMPT
    assert payload["default"] == DEFAULT_PAUSE_ANSWER
