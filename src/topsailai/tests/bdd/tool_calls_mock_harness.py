"""Real-HTTP harness for tool-call persistence and request normalization BDD."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from topsailai.ai_base.agent_base import AgentRun
from topsailai.ai_base.agent_types.react import Step4ReAct
from topsailai.ai_base.llm_hooks.hook_before_chat import tool_call_pairing
from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.prompt_base import PromptBase
from topsailai.context.chat_history_manager.__base import ChatHistoryMessageData
from topsailai.context.chat_history_manager.sql import ChatHistorySQLAlchemy
from topsailai.tools.base import init as tool_registry
from topsailai.workspace.llm_shell import LLMChat
from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM
from topsailai.workspace.context.agent import ContextRuntimeAIAgent
from tests.mock.llm_mock_server import MockServerConfig, create_server

LOGGER = logging.getLogger("tests.bdd.tool_calls_normalization")
LEGACY_CALL_ID = "fc_bdd_legacy"
LEGACY_REPR = (
    "ChatCompletionMessageFunctionToolCall(id='fc_bdd_legacy', "
    "function=Function(arguments='ARGS-SENTINEL-XYZ', name='safe_tool'), "
    "type='function')"
)
RESULT_SENTINEL = "RESULT-SENTINEL-XYZ"
UNOWNED_MISSING_ID_RESULT = "UNOWNED-MISSING-ID-XYZ"
UNOWNED_BLANK_ID_RESULT = "UNOWNED-BLANK-ID-XYZ"
PAIRED_RESULT = "PAIRED-RESULT-XYZ"
OBSERVATION_TEXT = "OBSERVATION-TEXT-XYZ"


class SDKToolCallFixture:
    """SDK-like object whose public serializer provides plain tool-call data."""

    def __init__(self, payload: dict[str, Any]):
        """Store one serializable tool-call payload."""
        self.payload = payload

    def model_dump(self) -> dict[str, Any]:
        """Return the SDK-compatible plain mapping."""
        return dict(self.payload)



class RecordingStep4ReAct(Step4ReAct):
    """Record the first parsed provider response before executing its steps."""

    def __init__(self, scenario: "ToolCallsScenario"):
        """Store the scenario that owns the observed parsed response."""
        super().__init__()
        self.scenario = scenario

    def _execute(self, step, tools, response, index, rsp_msg_obj=None, **kwargs):
        """Capture the first response and then execute normal ReAct behavior."""
        if self.scenario.first_parsed_response is None:
            self.scenario.first_parsed_response = json.loads(json.dumps(response))
        return super()._execute(
            step,
            tools,
            response,
            index,
            rsp_msg_obj=rsp_msg_obj,
            **kwargs,
        )


class SummaryAgentFixture:
    """Provide the minimal real Agent2LLM summarization contract."""

    def __init__(self, model: LLMModel, messages: list[dict[str, Any]]):
        """Attach a real model and mutable runtime messages."""
        self.llm_model = model
        self.messages = list(messages)
        self.agent_type = "react"

    @staticmethod
    def get_work_memory_first_position() -> int:
        """Treat the complete fixture message list as working memory."""
        return 0

@dataclass
class ServerOwner:
    """Own one scenario-local mock server and its exact serving thread."""

    server: Any
    thread: threading.Thread

    @classmethod
    def start(
        cls,
        tool_calls: tuple[dict[str, Any], ...] | None = None,
        tool_call_content: str | None = None,
        reply: str | None = None,
    ) -> "ServerOwner":
        """Start one mock server on an operating-system-assigned port."""
        scripted = (tool_calls,) if tool_calls is not None else None
        reply = reply or json.dumps([{"step_name": "final_answer", "raw_text": "done"}])
        config = MockServerConfig(
            port=0,
            reply=reply,
            request_body_capacity=16,
            stream_chunks=(reply,),
            tool_call_responses=scripted,
            tool_call_response_content=tool_call_content,
        )
        server = create_server(config)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return cls(server=server, thread=thread)

    @property
    def base_url(self) -> str:
        """Return the OpenAI-compatible base URL for this server."""
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1"

    def state(self) -> dict[str, Any]:
        """Read the actual server-side debug state over HTTP."""
        host, port = self.server.server_address
        with urllib.request.urlopen(f"http://{host}:{port}/debug/state") as response:
            return json.load(response)

    def close(self) -> None:
        """Stop only this scenario's server and wait for its thread to exit."""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise AssertionError("scenario mock-server thread did not stop")


class ToolCallsScenario:
    """Scenario-scoped state and lifecycle for the normalization BDD suite."""

    def __init__(self, tmp_path: Path, monkeypatch: Any):
        """Create isolated storage, environment, and a private mock server."""
        self.tmp_path = tmp_path
        self.monkeypatch = monkeypatch
        self.database_path = tmp_path / "tool-calls-normalization.sqlite"
        self.conn = f"sqlite:///{self.database_path}"
        self.server_owner = ServerOwner.start()
        self.scripted_tool_names: list[str] = []
        self.tool_call_response_content: str | None = None
        self.first_parsed_response: list[dict[str, Any]] | None = None
        self.dangling_call_id: str | None = None
        self.seeded_malformed = False
        self.native_framework_produced = False
        self.native_legacy_repr: str | None = None
        self.native_call_id: str | None = None
        self.hook_marker: Path | None = None
        self.ordinary_expected: list[tuple[str, str]] = []
        self.hook_module_name: str | None = None
        self.result: Any = None
        self.error: Exception | None = None
        self.agent: AgentRun | None = None
        self.agents: list[AgentRun] = []
        self.summary_agent: SummaryAgentFixture | None = None
        self.summary_before_count: int | None = None
        self.summary_after_count: int | None = None
        self.summary_answer: str | None = None
        self._registered_tools: dict[str, Any] = {}
        self._configure_environment()

    def _configure_environment(self) -> None:
        """Configure only explicit test values and the loopback provider endpoint."""
        values = {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "mock-model",
            "LLM_RESPONSE_STREAM": "0",
            "TOPSAILAI_USE_TOOL_CALLS": "0",
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
            "TOPSAILAI_AUTO_SESSION_NAME_ENABLED": "0",
            "TOPSAILAI_PRINT_TOOL_STAT": "0",
            "TOPSAILAI_ENABLE_PARALLEL_TOOL_CALLS": "0",
            "TOPSAILAI_CONTEXT_SUMMARY_MODE": "runtime",
            "TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES": "0",
            "TOPSAILAI_CTX_SUMMARY_KEEP_FIRST_TASK_MESSAGE": "0",
            "TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP": "0",
            "TOPSAILAI_CONTEXT_MESSAGES_TAIL_OFFSET_TO_KEEP": "0",
            "DEBUG": "0",
            "CONTEXT_HISTORY_MANAGERS": "",
        }
        for key, value in values.items():
            self.monkeypatch.setenv(key, value)
        self._point_client_at_server()

    def _point_client_at_server(self) -> None:
        """Point both supported OpenAI endpoint variables at the private server."""
        self.monkeypatch.setenv("OPENAI_API_BASE", self.server_owner.base_url)
        self.monkeypatch.setenv("OPENAI_BASE_URL", self.server_owner.base_url)

    def manager(self) -> ChatHistorySQLAlchemy:
        """Return a fresh public history manager for this scenario database."""
        return ChatHistorySQLAlchemy(self.conn)

    @staticmethod
    def structured_call(call_id: str = "call_bdd_seed") -> dict[str, Any]:
        """Build one valid structured tool call."""
        return {
            "id": call_id,
            "type": "function",
            "function": {"name": "safe_tool", "arguments": '{"value":"seed"}'},
        }

    def seed_structured(self, session_id: str) -> None:
        """Persist an SDK-like tool call and its paired result through public APIs."""
        manager = self.manager()
        call = SDKToolCallFixture(self.structured_call())
        manager.add_session_message(
            {"role": "assistant", "content": None, "tool_calls": [call]},
            session_id=session_id,
        )
        manager.add_session_message(
            {"role": "tool", "content": "seed-result", "tool_call_id": "call_bdd_seed"},
            session_id=session_id,
        )
        manager.engine.dispose()

    def seed_dangling_human_decision(self, session_id: str) -> None:
        """Persist one native human decision call without its tool output."""
        self.dangling_call_id = f"call_bdd_human_{session_id}"
        manager = self.manager()
        manager.add_session_message(
            {
                "role": "assistant",
                "content": "Approval is required.",
                "tool_calls": [SDKToolCallFixture({
                    "id": self.dangling_call_id,
                    "type": "function",
                    "function": {
                        "name": "human_tool-ask_decision",
                        "arguments": json.dumps({"question": "Proceed?"}),
                    },
                })],
            },
            session_id=session_id,
        )
        manager.engine.dispose()

    def seed_tool_results_without_ids(self, session_id: str) -> None:
        """Persist malformed tool results with absent and blank owner ids."""
        manager = self.manager()
        raw_messages = [
            {"role": "tool", "content": "missing-id-result"},
            {"role": "tool", "content": "blank-id-result", "tool_call_id": ""},
        ]
        for message in raw_messages:
            manager.add_message(
                ChatHistoryMessageData(json.dumps(message), None, session_id)
            )
        reloaded = manager.retrieve_messages(session_id)
        manager.engine.dispose()
        assert len(reloaded) == 2, "malformed tool-result fixtures were not persisted"

    def seed_legacy(self, session_id: str) -> None:
        """Persist the exact pre-fix malformed shape without direct SQL writes."""
        manager = self.manager()
        raw_messages = [
            {"role": "assistant", "content": None, "tool_calls": [LEGACY_REPR]},
            {
                "role": "tool",
                "content": RESULT_SENTINEL,
                "tool_call_id": LEGACY_CALL_ID,
            },
        ]
        for message in raw_messages:
            manager.add_message(
                ChatHistoryMessageData(json.dumps(message), None, session_id)
            )
        reloaded = manager.retrieve_messages(session_id)
        self.seeded_malformed = any(
            message.get("tool_calls") == [LEGACY_REPR] for message in reloaded
        )
        manager.engine.dispose()
        assert self.seeded_malformed, "legacy fixture was not present before the request"

    def seed_paired_and_unowned_results(self, session_id: str) -> None:
        """Persist one valid native pair plus two unowned tool results.

        The valid pair proves the request boundary does not over-drop when
        native tool calls are disabled, while the unowned results prove the
        stricter orphan predicate is mode-independent rather than native-only.
        """
        manager = self.manager()
        manager.add_session_message(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [SDKToolCallFixture(self.structured_call())],
            },
            session_id=session_id,
        )
        raw_messages = [
            {
                "role": "tool",
                "content": PAIRED_RESULT,
                "tool_call_id": "call_bdd_seed",
            },
            {"role": "tool", "content": UNOWNED_MISSING_ID_RESULT},
            {"role": "tool", "content": UNOWNED_BLANK_ID_RESULT, "tool_call_id": ""},
        ]
        for message in raw_messages:
            manager.add_message(
                ChatHistoryMessageData(json.dumps(message), None, session_id)
            )
        reloaded = manager.retrieve_messages(session_id)
        manager.engine.dispose()
        self.seeded_malformed = any(
            not message.get("tool_call_id") for message in reloaded
            if message.get("role") == "tool"
        )
        assert self.seeded_malformed, "unowned tool-result fixtures were not persisted"

    def prove_earlier_sites_skipped_in_non_native_mode(self) -> None:
        """Prove both mode-gated earlier sites are inert while native mode is off.

        This expresses the true half of the Human's premise as an observable
        assertion: the producer helper and the pre-chat hook both return the
        input untouched when ``TOPSAILAI_USE_TOOL_CALLS=0``, and the producer
        helper starts dropping once native mode is enabled.
        """
        orphans = [
            {"role": "tool", "content": UNOWNED_MISSING_ID_RESULT},
            {"role": "tool", "content": UNOWNED_BLANK_ID_RESULT, "tool_call_id": ""},
        ]
        self.monkeypatch.setenv("TOPSAILAI_USE_TOOL_CALLS", "0")
        producer_kept = ContextRuntimeAIAgent._drop_orphaned_tool_messages(
            list(orphans)
        )
        hook_kept = tool_call_pairing.hook_execute(list(orphans))
        assert producer_kept == orphans, producer_kept
        assert hook_kept == orphans, hook_kept

        self.monkeypatch.setenv("TOPSAILAI_USE_TOOL_CALLS", "1")
        producer_dropped = ContextRuntimeAIAgent._drop_orphaned_tool_messages(
            list(orphans)
        )
        assert producer_dropped == [], producer_dropped
        self.monkeypatch.setenv("TOPSAILAI_USE_TOOL_CALLS", "0")

    def seed_ordinary_non_native(self, session_id: str) -> None:
        """Persist tool-free non-native traffic including a textual observation.

        ``OBSERVATION_TEXT`` mirrors how non-native ReAct carries a tool result:
        an ordinary user message rather than a ``role="tool"`` message, so the
        sanitizer must leave it untouched.
        """
        manager = self.manager()
        raw_messages = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {
                "role": "user",
                "content": OBSERVATION_TEXT,
                "step_name": "observation",
                "raw_text": OBSERVATION_TEXT,
            },
            {"role": "assistant", "content": "second answer"},
        ]
        self.ordinary_expected = [
            (message["role"], message["content"]) for message in raw_messages
        ]
        for message in raw_messages:
            manager.add_message(
                ChatHistoryMessageData(json.dumps(message), None, session_id)
            )
        reloaded = manager.retrieve_messages(session_id)
        manager.engine.dispose()
        assert len(reloaded) == len(raw_messages), "ordinary fixtures were not persisted"

    def install_replacement_hook(self, module_name: str) -> None:
        """Install a real importable replacement hook with an execution marker."""
        hook_dir = self.tmp_path / "hooks"
        hook_dir.mkdir()
        self.hook_marker = hook_dir / "hook-ran.marker"
        module_path = hook_dir / f"{module_name}.py"
        module_path.write_text(
            "from pathlib import Path\n"
            f"MARKER = Path({str(self.hook_marker)!r})\n"
            f"MALFORMED = {LEGACY_REPR!r}\n"
            "def hook_execute(content):\n"
            "    MARKER.write_text(MALFORMED, encoding='utf-8')\n"
            "    return list(content) + "
            "[{'role': 'assistant', 'content': None, 'tool_calls': [MALFORMED]}]\n",
            encoding="utf-8",
        )
        sys.path.insert(0, str(hook_dir))
        self.hook_module_name = module_name
        self.monkeypatch.setenv("TOPSAILAI_HOOK_BEFORE_LLM_CHAT", module_name)

    def script_tool_calls(self, names: str) -> None:
        """Configure one native response containing the requested tool names."""
        self.scripted_tool_names = [name.strip() for name in names.split(",") if name.strip()]
        assert self.scripted_tool_names

    def script_mixed_tool_response(self) -> None:
        """Configure native calls with thought and final-answer text in one response."""
        self.script_tool_calls("safe_tool")
        self.tool_call_response_content = json.dumps([
            {"step_name": "thought", "raw_text": "approval analysis"},
            {"step_name": "final_answer", "raw_text": "premature answer"},
        ])

    def script_existing_action_with_native_call(self) -> None:
        """Configure an existing action, premature final, and native tool call."""
        self.script_tool_calls("safe_tool")
        self.tool_call_response_content = json.dumps([
            {"step_name": "action"},
            {"step_name": "final_answer", "raw_text": "premature answer"},
        ])

    def script_existing_action_without_native_call(self) -> None:
        """Configure a plain provider response containing one existing action."""
        reply = json.dumps([{"step_name": "action", "raw_text": "plain action"}])
        self.server_owner.close()
        self.server_owner = ServerOwner.start(reply=reply)
        self._point_client_at_server()

    def _restart_scripted_server(self) -> None:
        """Replace the scenario's plain server with its scripted tool-call server."""
        if not self.scripted_tool_names:
            return
        calls = tuple(
            {
                "id": f"call_bdd_runtime_{index}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps({"value": index})},
            }
            for index, name in enumerate(self.scripted_tool_names, start=1)
        )
        self.server_owner.close()
        self.server_owner = ServerOwner.start(
            calls,
            tool_call_content=self.tool_call_response_content,
        )
        self._point_client_at_server()

    def _loaded_history(self, session_id: str) -> list[dict[str, Any]]:
        """Reload persisted messages through a fresh manager instance."""
        manager = self.manager()
        messages = manager.retrieve_messages(session_id)
        manager.engine.dispose()
        return messages

    def _run_llm_chat(self, session_id: str, message: str) -> None:
        """Continue persisted history through the real OpenAI HTTP client."""
        prompt = PromptBase("You are a BDD test assistant.")
        prompt.messages.extend(self._loaded_history(session_id))
        prompt.add_user_message(message, need_print=False)
        model = LLMModel()
        chat = LLMChat(prompt, model)
        self.result = chat.chat(message="", need_print=False, need_env_message=False)


    def summarize_and_continue(self, session_id: str) -> None:
        """Force real Agent2LLM summarization, then send the rebuilt context."""
        messages = self._loaded_history(session_id)
        messages.append({"role": "user", "content": "continue after summarization"})
        model = LLMModel()
        self.summary_agent = SummaryAgentFixture(model, messages)
        runtime = ContextRuntimeAgent2LLM()
        runtime.ai_agent = self.summary_agent
        runtime.messages = []
        self.summary_before_count = len(self.summary_agent.messages)
        try:
            self.summary_answer = runtime.summarize_messages_for_processing(force=True)
            self.summary_after_count = len(self.summary_agent.messages)
            assert self.summary_answer, "real summarization returned no answer"
            assert self.summary_after_count < self.summary_before_count

            prompt = PromptBase("You are a BDD continuation assistant.")
            prompt.messages.extend(self.summary_agent.messages)
            prompt.add_user_message("continue with the rebuilt context", need_print=False)
            chat = LLMChat(prompt, model)
            self.result = chat.chat(message="", need_print=False, need_env_message=False)
        except Exception as error:  # noqa: BLE001 - scenario asserts exact outcome
            self.error = error
    @staticmethod
    def _safe_tool(value: Any = "") -> str:
        """Return one harmless deterministic tool result."""
        return f"SAFE-{value}"

    @staticmethod
    def _other_tool(value: Any = "") -> str:
        """Return a second harmless deterministic tool result."""
        return f"OTHER-{value}"

    def _register_tools(self) -> dict[str, Any]:
        """Register temporary tools and remember every displaced registry entry."""
        tools = {"safe_tool": self._safe_tool, "other_tool": self._other_tool}
        for name, function in tools.items():
            if name not in self._registered_tools:
                self._registered_tools[name] = tool_registry.TOOLS.get(name)
            tool_registry.TOOLS[name] = function
        return tools

    def _run_agent(self, session_id: str, message: str) -> AgentRun:
        """Complete a real native tool-call loop against the private HTTP server."""
        tools = self._register_tools()
        history = self._loaded_history(session_id)
        self.monkeypatch.setenv("TOPSAILAI_USE_TOOL_CALLS", "1")
        self.monkeypatch.setenv("TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES", "")
        agent = AgentRun(
            system_prompt="You are a BDD tool agent.",
            tools=tools,
            agent_name="BDDToolCalls",
        )
        agent.hooks_after_init_prompt.append(
            lambda current_agent: current_agent.messages.extend(history)
        )
        self.agent = agent
        self.agents.append(agent)
        self.result = agent.run(RecordingStep4ReAct(self), message)
        return agent

    def reproduce_native_incident(self) -> None:
        """Produce a native pair, persist its legacy degradation, then replay it."""
        self.script_tool_calls("safe_tool")
        self._restart_scripted_server()
        try:
            producer = self._run_agent("bdd_tc_native_producer", "call the safe tool")
            assistant = next(
                message for message in producer.messages if message.get("tool_calls")
            )
            tool_result = next(
                message
                for message in producer.messages
                if message.get("role") == "tool"
            )
            native_call = assistant["tool_calls"][0]
            self.native_call_id = native_call.id
            assert tool_result.get("tool_call_id") == self.native_call_id
            self.native_framework_produced = True
            self.native_legacy_repr = str(native_call)

            manager = self.manager()
            degraded_assistant = dict(assistant)
            degraded_assistant["tool_calls"] = [self.native_legacy_repr]
            for message in (degraded_assistant, dict(tool_result)):
                manager.add_message(
                    ChatHistoryMessageData(
                        json.dumps(message), None, "bdd_tc_native_replay"
                    )
                )
            reloaded = manager.retrieve_messages("bdd_tc_native_replay")
            manager.engine.dispose()
            self.seeded_malformed = any(
                message.get("tool_calls") == [self.native_legacy_repr]
                for message in reloaded
            )
            assert self.seeded_malformed, "native degradation was not persisted"
            assert any(
                message.get("role") == "tool"
                and message.get("tool_call_id") == self.native_call_id
                for message in reloaded
            ), "native tool result was not persisted"
            self._run_agent("bdd_tc_native_replay", "continue after persistence")
        except Exception as error:  # noqa: BLE001 - scenario asserts exact outcome
            self.error = error

    def continue_with_model(self, session_id: str, message: str, model: str) -> None:
        """Continue persisted dangling history after selecting another model."""
        self.monkeypatch.setenv("OPENAI_MODEL", model)
        self.continue_conversation(session_id, message)

    def recover_session(self, session_id: str, message: str) -> None:
        """Reload dangling history through a fresh manager before continuing."""
        recovered = self._loaded_history(session_id)
        assert any(message.get("tool_calls") for message in recovered), recovered
        self.continue_conversation(session_id, message)

    def continue_conversation(self, session_id: str, message: str) -> None:
        """Drive either a normal chat or a native tool loop and retain failures."""
        self._restart_scripted_server()
        try:
            if self.scripted_tool_names:
                self._run_agent(session_id, message)
            else:
                self._run_llm_chat(session_id, message)
        except Exception as error:  # noqa: BLE001 - scenario asserts exact outcome
            self.error = error

    def state(self) -> dict[str, Any]:
        """Return the server's actual captured request state."""
        return self.server_owner.state()

    def received_messages(self) -> list[dict[str, Any]]:
        """Flatten messages from every parsed server-received request body."""
        messages: list[dict[str, Any]] = []
        for record in self.state()["request_bodies"]:
            body = record.get("body")
            if isinstance(body, dict):
                messages.extend(body.get("messages", []))
        return messages

    def close(self) -> None:
        """Release model state, temporary registrations, imports, DB, and server."""
        for agent in self.agents:
            agent.llm_model.tokenStat.flag_running = False
        if self.summary_agent is not None:
            self.summary_agent.llm_model.tokenStat.flag_running = False
        for name, previous in self._registered_tools.items():
            if previous is None:
                tool_registry.TOOLS.pop(name, None)
            else:
                tool_registry.TOOLS[name] = previous
        if self.hook_module_name:
            sys.modules.pop(self.hook_module_name, None)
            hook_dir = str(self.tmp_path / "hooks")
            while hook_dir in sys.path:
                sys.path.remove(hook_dir)
        self.server_owner.close()
