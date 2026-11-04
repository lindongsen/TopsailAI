"""Local pre-request rejection behavior; no LLM interaction. Author: DawsonLin."""

import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from pytest_bdd import given, when, then, scenarios

from topsailai.ai_base.exception import ContextWindowLimitError
from tests.unit.test_topsailai_workspace_agent_agent_shell_base_llm_retry import (
    agent_chat,
    _run_patches,
)
from tests.unit.test_topsailai_workspace_agent_terminal_outcome import run_chat

scenarios("features/context_terminal_outcome.feature")


@pytest.fixture
def protection_session(agent_chat, tmp_path):
    """Keep actual metadata and captured session storage scenario-owned."""
    meta = tmp_path / "session.meta"
    meta.write_text(json.dumps({"status": "running"}), encoding="utf-8")
    saved = []
    agent_chat.ctx_runtime_data.add_session_message.side_effect = (
        lambda role, content: saved.append((role, content))
    )
    error = ContextWindowLimitError("safe_tokens=226289, send_limit=226000")
    agent_chat.ai_agent.run.side_effect = error
    with ExitStack() as stack:
        for item in _run_patches():
            stack.enter_context(item)
        for target in ("get_agent_step_call", "process_service"):
            stack.enter_context(patch(
                "topsailai.workspace.agent.agent_shell_base." + target,
                return_value=MagicMock(),
            ))
        stack.enter_context(patch(
            "topsailai.workspace.session_meta.get_session_meta_path", return_value=str(meta),
        ))
        yield {"chat": agent_chat, "meta": meta, "saved": saved, "error": error}


@given("a session whose agent is rejected by context protection")
def rejected_session(protection_session):
    """Start with metadata that has not yet reached a terminal state."""
    assert json.loads(protection_session["meta"].read_text())["status"] == "running"


@when("the session runs the rejected turn")
def run_rejected_session(protection_session, capsys):
    """Run the real chat boundary and capture its user-visible result."""
    protection_session["answer"] = run_chat(protection_session["chat"], need_interactive=False)
    protection_session["output"] = capsys.readouterr().out


@then("the session metadata records error rather than completed")
def error_metadata(protection_session):
    """Verify the actual atomic metadata writer published the error."""
    meta = json.loads(protection_session["meta"].read_text())
    assert meta["status"] == "error"
    assert meta["end_ts"]


@then("the termination reason is displayed and saved once")
def retained_reason(protection_session):
    """The operator and session history receive the same explicit reason."""
    answer = "Task terminated: " + str(protection_session["error"])
    assert protection_session["answer"] == answer
    assert protection_session["output"].count(answer) == 1
    assert protection_session["saved"] == [("assistant", answer)]


@then("no completion hooks run for the rejected turn")
def no_completion(protection_session):
    """Failure observation is distinct from successful turn completion."""
    chat = protection_session["chat"]
    chat.call_hooks_post_fail_run.assert_called_once_with(protection_session["error"])
    chat.call_hooks_post_succ_run.assert_not_called()
    chat.call_hook_for_final_answer.assert_not_called()
