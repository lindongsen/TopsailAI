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
from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.prompt_base import PromptBase
from topsailai.context.chat_history_manager.__base import ChatHistoryMessageData
from topsailai.context.chat_history_manager.sql import ChatHistorySQLAlchemy
from topsailai.tools.base import init as tool_registry
from topsailai.workspace.llm_shell import LLMChat
from tests.mock.llm_mock_server import MockServerConfig, create_server

LOGGER = logging.getLogger("tests.bdd.tool_calls_normalization")
LEGACY_CALL_ID = "fc_bdd_legacy"
LEGACY_REPR = (
    "ChatCompletionMessageFunctionToolCall(id='fc_bdd_legacy', "
    "function=Function(arguments='ARGS-SENTINEL-XYZ', name='safe_tool'), "
    "type='function')"
)
RESULT_SENTINEL = "RESULT-SENTINEL-XYZ"


class SDKToolCallFixture:
    """SDK-like object whose public serializer provides plain tool-call data."""

    def __init__(self, payload: dict[str, Any]):
        """Store one serializable tool-call payload."""
        self.payload = payload

    def model_dump(self) -> dict[str, Any]:
        """Return the SDK-compatible plain mapping."""
        return dict(self.payload)


@dataclass
class ServerOwner:
    """Own one scenario-local mock server and its exact serving thread."""

    server: Any
    thread: threading.Thread

    @classmethod
    def start(cls, tool_calls: tuple[dict[str, Any], ...] | None = None) -> "ServerOwner":
        """Start one mock server on an operating-system-assigned port."""
        scripted = (tool_calls,) if tool_calls is not None else None
        reply = json.dumps([{"step_name": "final_answer", "raw_text": "done"}])
        config = MockServerConfig(
            port=0,
            reply=reply,
            request_body_capacity=16,
            stream_chunks=(reply,),
            tool_call_responses=scripted,
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
        self.seeded_malformed = False
        self.hook_marker: Path | None = None
        self.hook_module_name: str | None = None
        self.result: Any = None
        self.error: Exception | None = None
        self.agent: AgentRun | None = None
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
        self.server_owner = ServerOwner.start(calls)
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
            self._registered_tools[name] = tool_registry.TOOLS.get(name)
            tool_registry.TOOLS[name] = function
        return tools

    def _run_agent(self, session_id: str, message: str) -> None:
        """Complete a real native tool-call loop against the private HTTP server."""
        tools = self._register_tools()
        history = self._loaded_history(session_id)
        self.monkeypatch.setenv("TOPSAILAI_USE_TOOL_CALLS", "1")
        self.agent = AgentRun(
            system_prompt="You are a BDD tool agent.",
            tools=tools,
            agent_name="BDDToolCalls",
        )
        self.agent.hooks_after_init_prompt.append(
            lambda agent: agent.messages.extend(history)
        )
        self.result = self.agent.run(Step4ReAct(), message)

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
        if self.agent is not None:
            self.agent.llm_model.tokenStat.flag_running = False
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
