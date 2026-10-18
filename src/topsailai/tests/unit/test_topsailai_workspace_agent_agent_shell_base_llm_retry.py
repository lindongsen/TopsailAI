"""Unit tests for LLM retry control at the User2Agent boundary."""

from contextlib import nullcontext
from unittest.mock import MagicMock, call, patch

import pytest

from topsailai.ai_base.exception import (
    LLMBackToChatError,
    LLMRetryExhaustedError,
)
from topsailai.ai_base.llm_control.control_runtime import LLMControlledInterruptError
from topsailai.workspace.agent.agent_shell_base import AgentChat


@pytest.fixture
def agent_chat():
    """Build an AgentChat with isolated runtime collaborators."""
    hook_instruction = MagicMock()
    ctx_rt_aiagent = MagicMock()
    ctx_rt_instruction = MagicMock()
    ai_agent = MagicMock()
    ai_agent.agent_type = "react"
    ai_agent.agent_name = "retry-agent"
    ai_agent.hooks_after_init_prompt = []
    ai_agent.hooks_after_new_session = []
    ai_agent.hooks_pre_chat = []
    ai_agent.messages = []
    ctx_runtime_data = MagicMock()
    ctx_runtime_data.session_id = "retry-session"
    ctx_runtime_data.session_data = None
    ctx_rt_aiagent.ai_agent = ai_agent
    ctx_rt_aiagent.ctx_runtime_data = ctx_runtime_data

    with (
        patch(
            "topsailai.workspace.agent.hooks.base.init.get_hooks",
            return_value=[],
        ),
        patch(
            "topsailai.workspace.agent.agent_chat_base.set_ai_agent",
        ),
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


def _run_patches(*, runtime_input=None, input_messages=()):
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
            "topsailai.workspace.agent.agent_shell_base.input_message",
            side_effect=input_messages,
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.task_tool.ctxm_process_task",
            side_effect=lambda _task: nullcontext(),
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.lock_tool.ctxm_void",
            side_effect=lambda **_: nullcontext({}),
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.terminal_title.refresh_terminal_title",
        ),
    )


@pytest.mark.parametrize("signal_type", [LLMBackToChatError, LLMControlledInterruptError])
def test_back_discards_old_message_and_runs_only_fresh_non_empty_input(agent_chat, signal_type):
    """Back must abandon the failed message before another Agent run starts."""
    back_error = signal_type(
        attempts=18,
        manual_cycle_count=0,
        last_error=RuntimeError("busy"),
        retry_reason="busy",
    )
    agent_chat.ai_agent.run.side_effect = [back_error, "fresh answer"]
    failure_hook = agent_chat.call_hooks_post_fail_run
    success_hook = agent_chat.call_hooks_post_succ_run
    final_hook = agent_chat.call_hook_for_final_answer
    built_turns = []

    def build_message(*, message, curr_count):
        built_turns.append((message, curr_count))
        return message

    patches = _run_patches(
        runtime_input=MagicMock(),
        input_messages=("   ", "continue", "fresh request"),
    )
    with (
        patches[0], patches[1], patches[2], patches[3],
        patches[4] as input_mock, patches[5], patches[6], patches[7],
        patch(
            "topsailai.workspace.agent.agent_shell_base.get_agent_step_call",
            return_value=MagicMock(),
        ),
    ):
        result = agent_chat._run(
            message="old request",
            times=1,
            func_build_message=build_message,
            need_interactive=True,
        )

    assert result == "fresh answer"
    assert agent_chat.ai_agent.run.call_count == 2
    assert [item.args[1] for item in agent_chat.ai_agent.run.call_args_list] == [
        "old request",
        "fresh request",
    ]
    assert built_turns == [("old request", 1), ("fresh request", 1)]
    assert input_mock.call_count == 3
    failure_hook.assert_called_once_with(back_error)
    success_hook.assert_called_once_with()
    final_hook.assert_called_once_with()
    assert agent_chat.interrupted is False
    assert agent_chat.last_message == "fresh answer"
    agent_chat.ctx_runtime_data.add_session_message.assert_not_called()
    agent_chat.ctx_runtime_data.del_session_messages.assert_not_called()


@pytest.mark.parametrize("interruption", [EOFError(), KeyboardInterrupt()])
def test_back_fresh_input_interruption_terminates_without_replaying_old_turn(
    agent_chat, interruption
):
    """Fresh-input interruption after Back terminates without success effects."""
    back_error = LLMBackToChatError(
        attempts=18,
        manual_cycle_count=0,
        last_error=RuntimeError("busy"),
        retry_reason="busy",
    )
    agent_chat.ai_agent.run.side_effect = back_error
    patches = _run_patches(
        runtime_input=MagicMock(),
        input_messages=(interruption,),
    )
    with (
        patches[0], patches[1], patches[2], patches[3],
        patches[4] as input_mock, patches[5], patches[6], patches[7],
        patch(
            "topsailai.workspace.agent.agent_shell_base.get_agent_step_call",
            return_value=MagicMock(),
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.input_yes",
            return_value=False,
        ) as confirm_abort,
    ):
        result = agent_chat._run(
            message="old request",
            times=0,
            need_interactive=True,
        )

    assert result == "failed due to abort by Human"
    agent_chat.ai_agent.run.assert_called_once()
    assert agent_chat.ai_agent.run.call_args.args[1] == "old request"
    input_mock.assert_called_once_with(hook=agent_chat.hook_instruction)
    confirm_abort.assert_called_once_with("Agent Session Continue [yes/no] ")
    assert agent_chat.call_hooks_post_fail_run.call_count == 2
    assert agent_chat.call_hooks_post_fail_run.call_args_list[0] == call(back_error)
    assert isinstance(
        agent_chat.call_hooks_post_fail_run.call_args_list[1].args[0],
        KeyboardInterrupt,
    )
    agent_chat.call_hooks_post_succ_run.assert_not_called()
    agent_chat.call_hook_for_final_answer.assert_not_called()
    agent_chat.hook_build_answer.assert_not_called()
    agent_chat.ctx_rt_aiagent.add_session_message.assert_not_called()
    agent_chat.ctx_runtime_data.add_session_message.assert_not_called()
    agent_chat.ctx_runtime_data.reset_messages.assert_not_called()


def test_retry_policy_enables_back_only_for_interactive_continuous_chat(agent_chat):
    """Only a resolved interactive continuous run may expose Back to chat."""
    captured_policies = []

    def capture_step_call(*, kwargs, agent_type):
        captured_policies.append(kwargs["llm_retry_policy"])
        return MagicMock()

    agent_chat.ai_agent.run.return_value = "answer"
    runtime_input = MagicMock()
    patches = _run_patches(runtime_input=runtime_input)
    with (
        patches[0], patches[1], patches[2], patches[3], patches[4],
        patches[5], patches[6], patches[7],
        patch(
            "topsailai.workspace.agent.agent_shell_base.get_agent_step_call",
            side_effect=capture_step_call,
        ),
    ):
        agent_chat._run(
            message="finite request",
            times=1,
            need_interactive=True,
        )

    finite_policy = captured_policies.pop()
    assert finite_policy.interactive_enabled is True
    assert finite_policy.allow_back_to_chat is False
    assert finite_policy.input_func is runtime_input


def test_retry_policy_allows_back_for_interactive_continuous_chat(agent_chat):
    """A resolved interactive continuous run may expose Back to chat."""
    captured = {}
    exhausted = LLMRetryExhaustedError(
        attempts=18,
        manual_cycle_count=0,
        last_error=RuntimeError("busy"),
        retry_reason="busy",
    )

    def capture_step_call(*, kwargs, agent_type):
        captured.update(kwargs)
        return MagicMock()

    agent_chat.ai_agent.run.side_effect = exhausted
    runtime_input = MagicMock()
    patches = _run_patches(runtime_input=runtime_input)
    with (
        patches[0], patches[1], patches[2], patches[3], patches[4],
        patches[5], patches[6], patches[7],
        patch(
            "topsailai.workspace.agent.agent_shell_base.get_agent_step_call",
            side_effect=capture_step_call,
        ),
    ):
        with pytest.raises(LLMRetryExhaustedError):
            agent_chat._run(
                message="continuous request",
                times=0,
                need_interactive=True,
            )

    policy = captured["llm_retry_policy"]
    assert policy.interactive_enabled is True
    assert policy.allow_back_to_chat is True
    assert policy.input_func is runtime_input


def test_explicit_non_interactive_overrides_interactive_environment(agent_chat):
    """Explicit False must disable every LLM retry interaction decision."""
    captured = {}

    def capture_step_call(*, kwargs, agent_type):
        captured.update(kwargs)
        return MagicMock()

    agent_chat.ai_agent.run.return_value = "answer"
    runtime_input = MagicMock()
    patches = _run_patches(runtime_input=runtime_input)
    with (
        patches[0], patches[1], patches[2],
        patches[3] as runtime_input_lookup, patches[4], patches[5],
        patches[6], patches[7],
        patch(
            "topsailai.workspace.agent.agent_shell_base.get_agent_step_call",
            side_effect=capture_step_call,
        ),
    ):
        agent_chat._run(
            message="request",
            times=1,
            need_interactive=False,
        )

    policy = captured["llm_retry_policy"]
    assert captured["flag_interactive"] is False
    assert policy.interactive_enabled is False
    assert policy.allow_back_to_chat is False
    assert policy.input_func is None
    runtime_input_lookup.assert_not_called()
    runtime_input.assert_not_called()


def test_back_waiting_for_input_does_not_change_session_meta(agent_chat):
    """Back waiting for a fresh message keeps session metadata running."""
    back_error = LLMBackToChatError(
        attempts=18,
        manual_cycle_count=0,
        last_error=RuntimeError("busy"),
        retry_reason="busy",
    )
    observed_meta_calls = []

    def fresh_input(*, hook):
        assert hook is agent_chat.hook_instruction
        assert observed_meta_calls == []
        return "fresh request"

    agent_chat.ai_agent.run.side_effect = [back_error, "fresh answer"]
    patches = _run_patches(runtime_input=MagicMock())
    with (
        patches[0], patches[1], patches[2], patches[3],
        patch(
            "topsailai.workspace.agent.agent_shell_base.input_message",
            side_effect=fresh_input,
        ),
        patches[5], patches[6], patches[7],
        patch(
            "topsailai.workspace.agent.agent_shell_base.get_agent_step_call",
            return_value=MagicMock(),
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.update_session_meta_status",
            side_effect=lambda *args: observed_meta_calls.append(args),
        ),
    ):
        result = agent_chat.run(
            message="old request",
            times=1,
            need_interactive=True,
        )

    assert result == "fresh answer"
    assert observed_meta_calls == [("completed", "retry-session")]


def test_terminal_retry_exhaustion_marks_session_error(agent_chat):
    """Terminal LLM retry exhaustion propagates and marks session metadata error."""
    exhausted = LLMRetryExhaustedError(
        attempts=18,
        manual_cycle_count=0,
        last_error=RuntimeError("busy"),
        retry_reason="busy",
    )
    agent_chat.ai_agent.run.side_effect = exhausted
    patches = _run_patches(runtime_input=None)
    with (
        patches[0], patches[1], patches[2], patches[3], patches[4],
        patches[5], patches[6], patches[7],
        patch(
            "topsailai.workspace.agent.agent_shell_base.get_agent_step_call",
            return_value=MagicMock(),
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.update_session_meta_status",
        ) as update_meta,
    ):
        with pytest.raises(LLMRetryExhaustedError) as raised:
            agent_chat.run(
                message="request",
                times=1,
                need_interactive=False,
            )

    assert raised.value is exhausted
    assert update_meta.call_args_list == [call("error", "retry-session")]
    agent_chat.call_hooks_post_succ_run.assert_not_called()
    agent_chat.call_hook_for_final_answer.assert_not_called()
    agent_chat.ctx_runtime_data.add_session_message.assert_not_called()


@pytest.mark.parametrize("operation", ["hard_interrupt", "force_retry"])
@pytest.mark.parametrize("replace_owner", [False, True])
def test_control_socket_http_returns_to_actual_chat_input(agent_chat, monkeypatch, tmp_path, operation, replace_owner):
    """Drive actual turn abandonment over socket and HTTP without catching its signal."""
    import os
    import threading
    from uuid import uuid4
    from tests.mock.llm_mock_server import MockServerConfig, create_server
    from tests.bdd.test_llm_first_byte_control import send
    from topsailai.ai_base.llm_base import LLMModel
    from topsailai.workspace.control_channel.handler import ControlHandlerRegistry
    from topsailai.workspace.control_channel.protocol import ControlContext
    from topsailai.workspace.control_channel.server import ControlServer
    from topsailai.workspace.control_handlers import register_control_handlers

    server = create_server(MockServerConfig(
        first_chunk_delays=(15, 0),
        stream_response_chunks=(("STALE",), ("FRESH",)),
    ))
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    base = f"http://127.0.0.1:{server.server_port}/v1"
    for key, value in {
        "OPENAI_API_BASE": base, "OPENAI_BASE_URL": base,
        "OPENAI_API_KEY": "mock-only", "OPENAI_MODEL": "control-chat-mock",
        "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
        "TOPSAILAI_EVENTS_ENABLED": "0",
        "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
    }.items():
        monkeypatch.setenv(key, value)
    model = LLMModel()
    prior_route = None
    if replace_owner:
        from topsailai.ai_base.llm_control.control_runtime import ControlRoute
        from topsailai.ai_base.llm_control.attempt_control import AttemptTarget
        prior_route = ControlRoute("previous", os.getpid(), object(), interrupt_supported=True)
        prior_route.generation = 7
        prior_route.target = AttemptTarget(prior_route.binding_id, 7, uuid4().hex, uuid4().hex)
        agent_chat._llm_control_route = prior_route
    agent_chat.ai_agent.llm_model = model
    outputs = []
    model.send_content = outputs.append
    registry = ControlHandlerRegistry()
    register_control_handlers(registry)
    root = next(parent for parent in tmp_path.parents if parent.name == ".tmp")
    path = str(root / (uuid4().hex[:10] + ".sock"))
    from topsailai.workspace.agent.agent_shell_base import resolve_session_id_for_files
    channel = ControlServer(path, registry, ControlContext(
        session_id=resolve_session_id_for_files(agent_chat.ctx_runtime_data), pid=os.getpid(), agent_chat=agent_chat,
    ), timeout=0.1)
    channel.start()
    commands = []
    failures = []

    def operator():
        """Wait for real first-fetch I/O before sending exact-target control."""
        try:
            assert server.lifecycle_capture.wait_for_request(1)
            assert server.lifecycle_capture.wait_for_phase(1, "first_item")
            view = send(path, {"operation": "status"})
            assert view["status"] == "ok", view
            if prior_route is not None:
                from dataclasses import asdict
                current = agent_chat._llm_control_route
                assert current is not prior_route
                assert prior_route.closed
                assert current.generation == 8
                assert current.binding_id != prior_route.binding_id
                rejected = send(path, {
                    "operation": operation, "target": asdict(prior_route.target),
                })
                assert rejected["status"] == "error", rejected
                assert view["result"]["target"]["binding_id"] == current.binding_id
            commands.append(send(path, {
                "operation": operation, "target": view["result"]["target"],
            }))
            assert commands[-1]["status"] == "ok", commands[-1]
        except BaseException as error:
            failures.append(error)
            server.lifecycle_capture.request_handle(1).release_delay()

    operator_thread = threading.Thread(target=operator, daemon=True)
    messages = []

    def run_agent(step_call, message):
        """Use the production LLM retry/call path inside actual AgentChat routing."""
        messages.append(message)
        return model.chat([{"role": "user", "content": message}], for_stream=True, for_raw=True)

    agent_chat.ai_agent.run.side_effect = run_agent
    patches = _run_patches(runtime_input=MagicMock(), input_messages=("fresh request",))
    try:
        operator_thread.start()
        with (
            patches[0], patches[1], patches[2], patches[3], patches[4],
            patches[5], patches[6], patches[7],
            patch("topsailai.workspace.agent.agent_shell_base.get_agent_step_call", return_value=MagicMock()),
        ):
            result = agent_chat._run(message="old request", times=1, need_interactive=True)
            assert result == "FRESH", (commands, failures, agent_chat._llm_control_route.view())
        assert failures == []
        assert commands[0]["result"]["state"] == "queued"
        assert messages == (["old request", "fresh request"] if operation == "hard_interrupt" else ["old request"])
        assert agent_chat.call_hooks_post_fail_run.call_count == (operation == "hard_interrupt")
        agent_chat.call_hooks_post_succ_run.assert_called_once()
        agent_chat.call_hook_for_final_answer.assert_called_once()
        agent_chat.ctx_runtime_data.add_session_message.assert_not_called()
        agent_chat.ctx_runtime_data.del_session_messages.assert_not_called()
        records = server.request_body_capture.state()["request_bodies"]
        assert len(records) == 2
        assert records[0]["body"]["messages"][-1]["content"] == "old request"
        assert records[1]["body"]["messages"][-1]["content"] == ("fresh request" if operation == "hard_interrupt" else "old request")
        if operation == "force_retry":
            assert records[0]["body"] == records[1]["body"]
        assert not any("STALE" in item for item in outputs)
    finally:
        for number in (1, 2):
            try:
                server.lifecycle_capture.request_handle(number).release_delay()
            except KeyError:
                pass
        operator_thread.join(5)
        channel.stop()
        server.shutdown()
        server.server_close()
        serving.join(5)
        route = getattr(agent_chat, "_llm_control_route", None)
        if route is not None:
            from topsailai.ai_base.llm_control.control_recovery import RECOVERY_POOL
            with RECOVERY_POOL.lock:
                leases = tuple(RECOVERY_POOL.leases.values())
            for lease in leases:
                if lease.target.binding_id != route.binding_id or lease.owner is None:
                    continue
                owner = lease.owner
                for worker in (owner.create_thread, owner.fetch_thread, owner.cleanup_thread):
                    if worker is not None:
                        worker.join(5)
            route.reconcile()
        model.release_all_llm_models()
    assert not operator_thread.is_alive()
    assert not serving.is_alive()
