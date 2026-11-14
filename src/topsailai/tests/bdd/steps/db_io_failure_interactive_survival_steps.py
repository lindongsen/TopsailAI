"""BDD steps for surviving a database write failure. Author: DawsonLin.

Every scenario drives the real ``AgentChat`` turn loop and the real database
write-failure policy. Only the collaborators outside the behavior under test are
replaced: the provider call, the runtime input channel, and the session metadata
store. The failure itself is a real ``OperationalError`` carrying a real SQLite
primary result code, so the policy classifies it exactly as production does.

The process-terminating seam is observed, never executed: ``os._exit`` is
replaced by a recorder so a scenario can assert the exit code without killing
the test runner.
"""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from pytest_bdd import given, parsers, then, when
from sqlalchemy.exc import OperationalError
from topsailai.workspace.agent.agent_shell_base import AgentChat


def _sqlite_error(code: int, message: str = "database or disk is full"):
    """Build an OperationalError carrying a real SQLite primary result code."""
    orig = sqlite3.OperationalError(message)
    orig.sqlite_errorcode = code
    return OperationalError("stmt", {}, orig)


class _ExitRecorder:
    """Record a process-terminating attempt instead of performing it."""

    def __init__(self):
        self.codes = []

    def __call__(self, code=1):
        self.codes.append(code)


@pytest.fixture
def bdd_state():
    """Carry one scenario's observable outcome."""
    return {}


@pytest.fixture
def bdd_chat():
    """Build a real AgentChat whose collaborators outside the behavior are isolated."""
    hook_instruction = MagicMock()
    ctx_rt_aiagent = MagicMock()
    ctx_rt_instruction = MagicMock()
    ai_agent = MagicMock()
    ai_agent.agent_type = "react"
    ai_agent.agent_name = "bdd-db-io-agent"
    ai_agent.hooks_after_init_prompt = []
    ai_agent.hooks_after_new_session = []
    ai_agent.hooks_pre_chat = []
    ai_agent.messages = []
    ctx_runtime_data = MagicMock()
    ctx_runtime_data.session_id = "bdd-db-io-session"
    ctx_runtime_data.session_data = None
    ctx_rt_aiagent.ai_agent = ai_agent
    ctx_rt_aiagent.ctx_runtime_data = ctx_runtime_data

    with (
        patch("topsailai.workspace.agent.hooks.base.init.get_hooks", return_value=[]),
        patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent"),
    ):
        chat = AgentChat(
            hook_instruction=hook_instruction,
            ctx_rt_aiagent=ctx_rt_aiagent,
            ctx_rt_instruction=ctx_rt_instruction,
        )

    chat._start_control_server = MagicMock()
    chat._stop_control_server = MagicMock()
    chat.call_hooks_pre_run = MagicMock()
    chat.call_hooks_post_fail_run = MagicMock()
    chat.call_hooks_post_succ_run = MagicMock()
    chat.call_hook_for_final_answer = MagicMock()
    chat.hook_for_answer = MagicMock()
    chat.hook_build_answer = MagicMock(side_effect=lambda answer, **_: answer)
    return chat


def _run_patches(*, runtime_input=None):
    """Return patches that isolate one AgentChat execution."""
    env_values = {
        "TOPSAILAI_INTERACTIVE_MODE": True,
        "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
        "TOPSAILAI_ENABLE_SESSION_LOCK": False,
        "TOPSAILAI_PRINT_TOOL_STAT": False,
    }
    return (
        patch(
            "topsailai.workspace.agent.agent_shell_base.env_tool.EnvReaderInstance.check_bool",
            side_effect=lambda key, default: env_values.get(key, default),
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.env_tool.is_debug_mode",
            return_value=False,
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.env_tool.is_need_print",
            return_value=False,
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.get_agent_runtime_input",
            return_value=runtime_input,
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.get_agent_step_call",
            return_value=MagicMock(),
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.update_session_meta_status",
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.input_yes",
            return_value=False,
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.thread_tool.is_main_thread",
            return_value=True,
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.input_message",
            side_effect=EOFError(),
        ),
    )


def _execute(chat, *, need_interactive, times, runtime_input=None):
    """Run one AgentChat turn with the isolated patch set applied."""
    patches = _run_patches(runtime_input=runtime_input)
    exit_recorder = _ExitRecorder()
    with (
        patches[0], patches[1], patches[2], patches[3],
        patches[4], patches[5] as meta_status, patches[6], patches[7],
        patches[8],
        patch("os._exit", exit_recorder),
        patch("sys.stdout.flush") as stdout_flush,
        patch("sys.stderr.flush") as stderr_flush,
    ):
        result = chat._run(
            message="request that cannot be persisted",
            times=times,
            need_interactive=need_interactive,
        )
    return {
        "result": result,
        "exit_codes": exit_recorder.codes,
        "meta_status": meta_status,
        "stdout_flush": stdout_flush,
        "stderr_flush": stderr_flush,
    }


@given("an interactive agent session whose database write fails")
def interactive_session_with_failing_write(bdd_chat, bdd_state):
    """Arm a real database write failure on an interactive session."""
    bdd_chat.ai_agent.run.side_effect = _sqlite_error(13)
    bdd_state["chat"] = bdd_chat
    bdd_state["input_mock"] = MagicMock()
    bdd_state["input_mock"].side_effect = EOFError()


@given("a non-interactive agent session whose database write fails")
def non_interactive_session_with_failing_write(bdd_chat, bdd_state):
    """Arm a real database write failure on a non-interactive session."""
    bdd_chat.ai_agent.run.side_effect = _sqlite_error(13)
    bdd_state["chat"] = bdd_chat


@given("an interactive agent session whose database write fails in a worker thread")
def worker_thread_session_with_failing_write(bdd_chat, bdd_state):
    """Arm a real database write failure observed from a worker thread."""
    bdd_chat.ai_agent.run.side_effect = _sqlite_error(5, "database is locked")
    bdd_state["chat"] = bdd_chat
    bdd_state["input_mock"] = MagicMock()
    bdd_state["input_mock"].side_effect = EOFError()


@when("the turn is abandoned")
def abandon_one_turn(bdd_state):
    """Execute one turn that cannot persist its result."""
    chat = bdd_state["chat"]
    interactive = "input_mock" in bdd_state
    bdd_state["outcome"] = _execute(
        chat,
        need_interactive=interactive,
        times=1,
        runtime_input=bdd_state.get("input_mock"),
    )


@when(parsers.parse("{count:d} consecutive turns fail to persist"))
def abandon_consecutive_turns(bdd_state, count):
    """Execute several turns that each fail to persist."""
    chat = bdd_state["chat"]
    outcomes = []
    for _ in range(count):
        chat.ai_agent.run.side_effect = _sqlite_error(13)
        outcomes.append(
            _execute(
                chat,
                need_interactive=True,
                times=0,
                runtime_input=bdd_state["input_mock"],
            )
        )
    bdd_state["outcome"] = outcomes[-1]
    bdd_state["outcomes"] = outcomes


@when("the turn is abandoned in a worker thread")
def abandon_turn_in_worker_thread(bdd_state):
    """Execute one turn while the caller is a worker thread."""
    chat = bdd_state["chat"]
    patches = _run_patches(runtime_input=bdd_state["input_mock"])
    exit_recorder = _ExitRecorder()
    with (
        patches[0], patches[1], patches[2], patches[3],
        patches[4], patches[5] as meta_status, patches[6], patches[8],
        patch(
            "topsailai.workspace.agent.agent_shell_base.thread_tool.is_main_thread",
            return_value=False,
        ),
        patch("os._exit", exit_recorder),
    ):
        result = chat._run(
            message="request that cannot be persisted",
            times=1,
            need_interactive=True,
        )
    bdd_state["outcome"] = {
        "result": result,
        "exit_codes": exit_recorder.codes,
        "meta_status": meta_status,
        "worker_thread": True,
    }


@then("the session returns to the input prompt")
def session_returns_to_prompt(bdd_state):
    """The abandoned turn must hand control back to the input channel."""
    outcome = bdd_state["outcome"]
    assert outcome["exit_codes"] == [], "an interactive session must not exit"
    assert outcome["result"] == "failed due to abort by Human"


@then("the process is still alive")
def process_is_alive(bdd_state):
    """No process-terminating call may be observed."""
    assert bdd_state["outcome"]["exit_codes"] == []


@then("the session metadata is retained")
def metadata_is_retained(bdd_state):
    """The metadata must survive the failure path, never be removed.

    A retained record means the session is still owned by a live process, so no
    path that keeps the session alive may finalize it as ``error``. A worker
    thread abandons only its own turn while the owning interactive session keeps
    running, and an interactive main thread returns to the prompt instead of
    ending the session. Only the non-interactive fallback exit finalizes the
    record, and that path asserts it through its own step.
    """
    outcome = bdd_state["outcome"]
    meta_status = outcome["meta_status"]
    error_calls = [
        call for call in meta_status.call_args_list if call.args and call.args[0] == "error"
    ]
    assert error_calls == [], (
        "a live session must not be finalized as error: " f"{error_calls}"
    )


@then("the session returns to the input prompt after every failure")
def session_returns_to_prompt_every_time(bdd_state):
    """Every consecutive failure must hand control back to the input channel."""
    for outcome in bdd_state["outcomes"]:
        assert outcome["exit_codes"] == []
        assert outcome["result"] == "failed due to abort by Human"


@then("the run reports an explicit failure answer")
def run_reports_failure_answer(bdd_state):
    """A non-interactive caller must receive a diagnosable failure answer."""
    result = bdd_state["outcome"]["result"]
    assert "Task terminated" in result
    assert "database or disk is full" in result


@then("the process exits with a non-zero code")
def process_exits_non_zero(bdd_state):
    """A lost write must never look like success to the caller."""
    assert bdd_state["outcome"]["exit_codes"] == [1]


@then("the session metadata records an error")
def metadata_records_error(bdd_state):
    """The metadata must record the error before the fallback exit."""
    meta_status = bdd_state["outcome"]["meta_status"]
    meta_status.assert_any_call("error", "bdd-db-io-session")


@then("the stdout artifact keeps the failure evidence")
def stdout_keeps_evidence(bdd_state):
    """Both streams must be flushed before the fallback exit."""
    outcome = bdd_state["outcome"]
    assert outcome["stdout_flush"].called
    assert outcome["stderr_flush"].called


@then("the worker thread does not terminate the process")
def worker_thread_does_not_exit(bdd_state):
    """A worker thread must abandon only its own turn."""
    outcome = bdd_state["outcome"]
    assert outcome["exit_codes"] == []
    assert "Task terminated" in outcome["result"]
