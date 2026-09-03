"""Real-HTTP harness for LLM request-statistics BDD."""

from __future__ import annotations

import json
import threading
import urllib.request
from typing import Any
from unittest.mock import MagicMock

from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.ai_base.llm_base import LLMModel
from topsailai.context import llm_request_stat as request_stat_module
from topsailai.utils import state_visualizer as state_visualizer_module


class LLMRequestStatScenario:
    """Own one real-client request and its private mock provider."""

    def __init__(self, monkeypatch: Any):
        """Start the provider and configure an isolated real client."""
        self.monkeypatch = monkeypatch
        self.server = create_server(MockServerConfig(port=0, reply="Mock response"))
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="bdd-llm-request-stat-server",
            daemon=True,
        )
        self.server_thread.start()
        self.visible_output: list[str] = []
        self.print_info = MagicMock(side_effect=self.visible_output.append)
        monkeypatch.setattr(request_stat_module, "print_info", self.print_info)
        monkeypatch.setattr(
            state_visualizer_module, "print_info", self.print_info
        )
        base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        values = {
            "OPENAI_API_BASE": base_url,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_API_KEY": "mock",
            "OPENAI_MODEL": "topsailai-mock",
            "LLM_RESPONSE_STREAM": "0",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
        }
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        self.model = LLMModel()
        self.stat = self.model.llm_request_stat
        self.before = self.stat.get_request_stat_info()
        self.after: dict[str, int] | None = None
        self.response = None

    def _replace_server(self, config: MockServerConfig) -> None:
        """Replace the scenario-owned provider and point new clients at it."""
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        if self.server_thread.is_alive():
            raise AssertionError("previous request-stat mock-server thread did not stop")
        self.server = create_server(config)
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="bdd-llm-request-stat-server",
            daemon=True,
        )
        self.server_thread.start()
        base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        self.monkeypatch.setenv("OPENAI_API_BASE", base_url)
        self.monkeypatch.setenv("OPENAI_BASE_URL", base_url)

    def send_invalid_request(self) -> None:
        """Send a real request whose provider response has empty content."""
        self.model.close()
        self._replace_server(MockServerConfig(port=0, reply=""))
        self.model = LLMModel()
        self.stat = self.model.llm_request_stat
        self.before = self.stat.get_request_stat_info()
        try:
            self.send_request()
        except Exception as error:  # noqa: BLE001 - the scenario expects invalid content
            self.error = error
            self.after = self.stat.get_request_stat_info()

    def send_unknown_native_tool(self) -> None:
        """Run a real native tool loop with an intentionally unknown tool."""
        self.model.close()
        self._replace_server(MockServerConfig(
            port=0,
            reply='[{"step_name": "final_answer", "raw_text": "done"}]',
            tool_call_responses=(({
                "id": "call_bdd_unknown",
                "type": "function",
                "function": {"name": "unknown_bdd_tool", "arguments": "{}"},
            },),),
        ))
        self.monkeypatch.setenv("TOPSAILAI_USE_TOOL_CALLS", "1")
        self.monkeypatch.setenv("TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES", "")
        from topsailai.ai_base.agent_base import AgentRun
        from topsailai.ai_base.agent_types.react import Step4ReAct

        agent = AgentRun(
            system_prompt="You are a BDD tool agent.",
            tools={"known_bdd_tool": lambda: "ok"},
            agent_name="BDDRequestStat",
        )
        self.agent = agent
        self.stat = agent.llm_request_stat
        self.before = self.stat.get_request_stat_info()
        agent.run(Step4ReAct(), "call the unknown tool")
        self.after = self.stat.get_request_stat_info()

    def send_request(self) -> None:
        """Send one request through the real OpenAI-compatible client."""
        self.response = self.model.call_llm_model([
            {"role": "user", "content": "count this real request"}
        ])
        self.after = self.stat.get_request_stat_info()

    def state(self) -> dict[str, Any]:
        """Read the provider's actual request state over HTTP."""
        url = f"http://127.0.0.1:{self.server.server_port}/debug/state"
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.load(response)

    def close(self) -> None:
        """Stop only this scenario's server and runtime workers."""
        agent = getattr(self, "agent", None)
        if agent is not None:
            agent.close()
        self.model.close()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        if self.server_thread.is_alive():
            raise AssertionError("LLM request-stat mock-server thread did not stop")
