"""Terminal protection outcome regressions. Author: DawsonLin."""

import inspect
from contextlib import ExitStack
from unittest.mock import MagicMock, call, patch

import pytest

from topsailai.ai_base.exception import ContextWindowLimitError, HeavyTaskError
from topsailai.workspace.agent.agent_shell_base import AgentChat
from topsailai.workspace.context.base import ContextRuntimeBase
from tests.unit.test_topsailai_workspace_agent_agent_shell_base_llm_retry import (
    agent_chat,
    _run_patches,
)


@pytest.fixture
def terminal_runtime(agent_chat):
    """Isolate process services and external input for terminal boundary checks."""
    with ExitStack() as stack:
        for item in _run_patches():
            stack.enter_context(item)
        stack.enter_context(patch(
            "topsailai.workspace.agent.agent_shell_base.get_agent_step_call",
            return_value=MagicMock(),
        ))
        service = stack.enter_context(patch(
            "topsailai.workspace.agent.agent_shell_base.process_service",
        ))
        meta = stack.enter_context(patch(
            "topsailai.workspace.agent.agent_shell_base.update_session_meta_status",
        ))
        yield agent_chat, meta, service


def run_chat(chat, **kwargs):
    """Execute the production run boundary without its unrelated stdout tee."""
    return inspect.unwrap(AgentChat.run)(chat, message="task", times=1, **kwargs)


@pytest.mark.parametrize("error_type", [ContextWindowLimitError, HeavyTaskError])
@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("save", [False, True])
def test_terminal_outcome_is_error_and_reason_is_visible(
    terminal_runtime, capsys, error_type, interactive, save,
):
    """Every protection exit is visible, persisted by policy and never successful."""
    chat, meta, service = terminal_runtime
    error = error_type("capacity protection")
    chat.ai_agent.run.side_effect = error

    result = run_chat(chat, need_interactive=interactive, need_save_answer=save)

    assert result == "Task terminated: capacity protection"
    assert chat.last_message == result
    assert capsys.readouterr().out.count(result) == 1
    assert meta.call_args_list == [call("error", "retry-session")]
    if save:
        chat.ctx_runtime_data.add_session_message.assert_called_once_with("assistant", result)
    else:
        chat.ctx_runtime_data.add_session_message.assert_not_called()
    chat.call_hooks_post_fail_run.assert_called_once_with(error)
    chat.call_hooks_post_succ_run.assert_not_called()
    chat.call_hook_for_final_answer.assert_not_called()
    chat.ctx_runtime_data.reset_messages.assert_not_called()
    chat.ai_agent.run.assert_called_once()
    chat.ai_agent.close.assert_called_once_with()
    chat._stop_control_server.assert_called_once_with()
    service.return_value.bind.return_value.close.assert_called_once_with()


def test_next_run_does_not_inherit_terminal_failure(terminal_runtime):
    """Reusing a controller resets its outcome instead of mislabeling success."""
    chat, meta, _ = terminal_runtime
    chat.ai_agent.run.side_effect = [ContextWindowLimitError("capacity"), "finished"]
    run_chat(chat, need_interactive=False)
    assert run_chat(chat, need_interactive=False) == "finished"
    assert meta.call_args_list == [
        call("error", "retry-session"), call("completed", "retry-session"),
    ]
    chat.call_hooks_post_succ_run.assert_called_once_with()
    chat.call_hook_for_final_answer.assert_called_once_with()


def test_incident_summary_diagnostic_reports_adjusted_count():
    """The safety-adjusted rejection is explicit even if raw input fits."""
    runtime = object.__new__(ContextRuntimeBase)
    runtime.ai_agent = MagicMock()
    with (
        patch.object(ContextRuntimeBase, "session_id", new="incident", create=True),
        patch.object(runtime, "_compute_context_limits", return_value=(256000, 217808, 226000)),
        patch.object(runtime, "_get_current_tokens", return_value=215513),
        patch("topsailai.workspace.context.base.env_tool.EnvReaderInstance.get", return_value=1.05),
        patch("topsailai.workspace.context.base.logger.warning") as warning,
    ):
        result = runtime._check_dynamic_summary_feasibility([], 134855, 4096)
    assert result == (False, "summary_input_exceeds_safe_limit", 215513, 217808)
    assert warning.call_args.args[1:] == (215513, 226289, 217808, "incident")


def test_hard_guard_includes_the_actual_safety_adjusted_count():
    """The raised failure explains why raw input below the limit was blocked."""
    from tests.unit.test_topsailai_workspace_agent_agent_chat_base_context_guard import (
        _build_agent_chat, _watermark,
    )
    from topsailai.workspace.context.base import CONTEXT_WATERMARK_HARD

    watermark = _watermark(CONTEXT_WATERMARK_HARD, 215513, send_limit=226000)
    watermark.safe_tokens = 226289
    _, runtime, ai_agent = _build_agent_chat([watermark, watermark], processing_answer=None)
    runtime.summarize_messages_for_processed.return_value = None
    with pytest.raises(ContextWindowLimitError) as raised:
        ai_agent.hooks_pre_chat[0](ai_agent)
    assert "current_tokens=215513, safe_tokens=226289, send_limit=226000" in str(raised.value)
