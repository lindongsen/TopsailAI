"""Real-HTTP harness for tool prompt message-role behavior."""

import json
import threading
import urllib.request
from pathlib import Path
from typing import Any

from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.ai_base.agent_base import AgentRun
from topsailai.ai_base.agent_types.react import Step4ReAct
from topsailai.tools import skill_tool, story_memory_tool, subagent_tool
from topsailai.tools.base import init as tool_registry
from topsailai.workspace import session_meta


TOOL_STARTUP_MARKER = "BDD-TOOL-STARTUP-CONTEXT-ONLY-IN-SYSTEM"
NESTED_STARTUP_MARKER = "BDD-NESTED-STARTUP-CONTEXT-ONLY-IN-SYSTEM"
TEST_TMP_DIR = Path(__file__).resolve().parents[2] / ".tmp"


class ToolPromptMessageRoleScenario:
    """Own one agent request and its private mock provider."""

    def __init__(self, monkeypatch: Any):
        """Start the provider and configure an isolated real client."""
        self.monkeypatch = monkeypatch
        self.server = create_server(MockServerConfig(
            port=0,
            reply='[{"step_name": "final_answer", "raw_text": "done"}]',
        ))
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="bdd-tool-prompt-message-role-server",
            daemon=True,
        )
        self.server_thread.start()
        base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        values = {
            "OPENAI_API_BASE": base_url,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_API_KEY": "mock",
            "OPENAI_MODEL": "topsailai-mock",
            "LLM_RESPONSE_STREAM": "0",
            "TOPSAILAI_USE_TOOL_CALLS": "0",
            "TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES": "",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
        }
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        self.original_skill_prompt = skill_tool.PROMPT
        skill_tool.PROMPT = skill_tool.PROMPT_SKILL + TOOL_STARTUP_MARKER
        self.agent = AgentRun(
            system_prompt="You are a BDD prompt-role agent.",
            tools={"skill_tool-probe": lambda: "unused"},
            agent_name="BDDToolPromptRole",
        )

    def send_task(self) -> None:
        """Run one task through the agent and real OpenAI-compatible client."""
        self.agent.run(Step4ReAct(), "complete the prompt-role scenario")

    def state(self) -> dict[str, Any]:
        """Read the provider's captured request state over HTTP."""
        url = f"http://127.0.0.1:{self.server.server_port}/debug/state"
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.load(response)

    def request_messages(self) -> list[dict[str, Any]]:
        """Return messages from the scenario's only completion request."""
        return self.state()["request_bodies"][0]["body"]["messages"]

    def close(self) -> None:
        """Stop only this scenario's agent and mock server."""
        skill_tool.PROMPT = self.original_skill_prompt
        self.agent.close()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        if self.server_thread.is_alive():
            raise AssertionError("tool prompt mock-server thread did not stop")


class ManagerSubagentPromptMessageRoleScenario:
    """Own one real Manager-to-Subagent delegation and mock provider."""

    def __init__(self, monkeypatch: Any):
        """Start the provider and configure isolated nested agents."""
        self.monkeypatch = monkeypatch
        tool_call = {
            "id": "call_bdd_delegate",
            "type": "function",
            "function": {
                "name": "subagent_tool-call_assistant",
                "arguments": json.dumps({"task": "complete the delegated BDD task"}),
            },
        }
        self.server = create_server(MockServerConfig(
            port=0,
            reply='[{"step_name": "final_answer", "raw_text": "done"}]',
            request_body_capacity=8,
            tool_call_responses=((tool_call,), None, None),
        ))
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="bdd-manager-subagent-prompt-role-server",
            daemon=True,
        )
        self.server_thread.start()
        base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        values = {
            "OPENAI_API_BASE": base_url,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_API_KEY": "mock",
            "OPENAI_MODEL": "topsailai-mock",
            "LLM_RESPONSE_STREAM": "0",
            "TOPSAILAI_USE_TOOL_CALLS": "1",
            "TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES": "",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
            "TOPSAILAI_AGENT2LLM_KEEP_MESSAGES_ACROSS_TURNS": "1",
            "TOPSAILAI_AUTO_SESSION_NAME_ENABLED": "0",
            "TOPSAILAI_ENABLE_SESSION_TEE_OUT": "0",
            "TOPSAILAI_INTERACTIVE_MODE": "0",
            "TOPSAILAI_PRINT_TOOL_STAT": "0",
            "CONTEXT_HISTORY_MANAGERS": "",
            "DEBUG": "0",
        }
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("TOPSAILAI_TASK_ID", raising=False)
        monkeypatch.setattr(
            session_meta,
            "FOLDER_WORKSPACE_TASK",
            str(TEST_TMP_DIR),
        )
        monkeypatch.setattr(subagent_tool, "get_session_id", lambda: "")
        monkeypatch.setattr(subagent_tool, "get_task_id", lambda: "")

        self.original_story_prompt = story_memory_tool.PROMPT
        story_memory_tool.PROMPT = (
            self.original_story_prompt + "\n" + NESTED_STARTUP_MARKER
        )
        self.original_subagents = dict(subagent_tool.g_subagents)
        subagent_tool.g_subagents.clear()
        self.original_tools = {
            "story_memory_tool-read_memory": tool_registry.TOOLS.get(
                "story_memory_tool-read_memory"
            ),
            "subagent_tool-call_assistant": tool_registry.TOOLS.get(
                "subagent_tool-call_assistant"
            ),
        }
        tool_registry.TOOLS["story_memory_tool-read_memory"] = (
            story_memory_tool.read_memory
        )
        tool_registry.TOOLS["subagent_tool-call_assistant"] = (
            subagent_tool.call_assistant
        )
        self.main_agent = subagent_tool.MainAgent(agent_name="BDDManager")
        self.result = None

    def delegate_task(self) -> None:
        """Run one real Manager tool loop that creates a real Subagent."""
        self.result = self.main_agent.plan_agent.run(
            message="delegate this task to a subagent",
            times=1,
            need_session_lock=False,
            need_interactive=False,
            need_save_answer=False,
        )

    def state(self) -> dict[str, Any]:
        """Read the provider's captured request state over HTTP."""
        url = f"http://127.0.0.1:{self.server.server_port}/debug/state"
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.load(response)

    def request_message_groups(self) -> list[list[dict[str, Any]]]:
        """Return messages grouped by Manager and Subagent HTTP request."""
        return [
            record["body"]["messages"]
            for record in self.state()["request_bodies"]
        ]

    def close(self) -> None:
        """Restore globals and stop only scenario-owned agents and server."""
        story_memory_tool.PROMPT = self.original_story_prompt
        for name, previous in self.original_tools.items():
            if previous is None:
                tool_registry.TOOLS.pop(name, None)
            else:
                tool_registry.TOOLS[name] = previous
        created_subagents = [
            agent_chat
            for task_id, agent_chat in subagent_tool.g_subagents.items()
            if self.original_subagents.get(task_id) is not agent_chat
        ]
        for agent_chat in created_subagents:
            agent_chat._stop_control_server()
            agent_chat.ai_agent.close()
        subagent_tool.g_subagents.clear()
        subagent_tool.g_subagents.update(self.original_subagents)
        self.main_agent.plan_agent.ai_agent.close()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        if self.server_thread.is_alive():
            raise AssertionError("nested tool prompt mock-server thread did not stop")
