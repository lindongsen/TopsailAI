"""Real-HTTP harness for Team-level shared values BDD.

Author: DawsonLin
"""

from __future__ import annotations

import json
import os
import threading
import urllib.request
from pathlib import Path
from typing import Any

from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.ai_base.agent_base import AgentRun
from topsailai.ai_base.agent_types.react import Step4ReAct
from topsailai.ai_team import manager, member_agent
from topsailai.ai_team.role import get_member_prompt
from topsailai.workspace.llm_shell import get_llm_chat

BASE_MARKER = "# BDD Base System\nBDD_BASE_SYSTEM_MARKER"
AI_TEAM_HEADING = "# AI Team"
RUNTIME_MARKER = f"{AI_TEAM_HEADING}\nBDD_RUNTIME_TEAM_MARKER"
TEAM_MARKER = "# BDD Shared Team Values\nBDD_SHARED_TEAM_VALUES_MARKER"
MEMBER_MARKER = "# BDD Member Private Values\nBDD_MEMBER_PRIVATE_MARKER"
USER_MESSAGE = "Verify the Team prompt over the provider boundary."
OUTPUT_REQUIREMENT = "Directly output the content without any formatting."


class TeamValuesPromptScenario:
    """Own one Team prompt fixture, real clients, and private mock provider."""

    def __init__(self, monkeypatch: Any, tmp_path: Path, shared_state: str):
        """Create the Team directory and configure one loopback provider."""
        self.monkeypatch = monkeypatch
        self.team_path = tmp_path / "team"
        self.team_path.mkdir()
        (self.team_path / "member-a.member").write_text(
            "BDD Member inventory", encoding="utf-8"
        )
        (self.team_path / "member-a.values").write_text(
            MEMBER_MARKER, encoding="utf-8"
        )
        if shared_state == "present":
            (self.team_path / "team.values").write_text(
                TEAM_MARKER, encoding="utf-8"
            )
        elif shared_state == "empty":
            (self.team_path / "team.values").write_text("", encoding="utf-8")
        elif shared_state == "unreadable":
            (self.team_path / "team.values").mkdir()

        response = json.dumps([
            {"step_name": "final_answer", "raw_text": "BDD response"}
        ])
        self.server = create_server(MockServerConfig(
            port=0,
            reply=response,
            stream_chunks=(response,),
        ))
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="bdd-team-values-prompt-server",
            daemon=True,
        )
        self.server_thread.start()
        self.clients: list[Any] = []
        self.error: Exception | None = None
        self._configure_environment()

    def _configure_environment(self) -> None:
        """Point production clients and Team resolution at scenario resources."""
        base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        values = {
            "OPENAI_API_BASE": base_url,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_API_KEY": "mock-team-values",
            "OPENAI_MODEL": "topsailai-team-values",
            "LLM_RESPONSE_STREAM": "0",
            "SYSTEM_PROMPT": BASE_MARKER,
            "TOPSAILAI_TEAM_PATH": str(self.team_path),
            "TOPSAILAI_TEAM_PROMPT": RUNTIME_MARKER,
            "TOPSAILAI_USE_TOOL_CALLS": "0",
            "TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES": "",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
            "TOPSAILAI_MODEL_SETTINGS": "",
        }
        for key, value in values.items():
            self.monkeypatch.setenv(key, value)
        self.monkeypatch.delenv("TOPSAILAI_TEAM_PROMPT_CONTENT", raising=False)
        manager.g_members.clear()

    def _close_client(self, client: Any) -> None:
        """Close one exact client immediately after its provider request."""
        client.close()
        self.clients.remove(client)

    def _send_agent_prompt(self, system_prompt: str) -> None:
        """Send one prompt through the production Agent2LLM HTTP path."""
        agent = AgentRun(
            system_prompt=system_prompt,
            tools={},
            agent_name="BDDTeamMember",
        )
        self.clients.append(agent)
        try:
            agent.run(Step4ReAct(), USER_MESSAGE)
        finally:
            self._close_client(agent)

    def _send_chat_prompt(self, system_prompt: str, more_prompt: str = "") -> None:
        """Send one prompt through the production direct-chat HTTP path."""
        chat = get_llm_chat(
            message=USER_MESSAGE,
            session_id="",
            system_prompt=system_prompt,
            more_prompt=more_prompt,
            need_stdout=False,
            need_input_message=False,
            need_print_session=False,
            need_print_message=False,
        )
        self.clients.append(chat)
        try:
            chat.chat(need_print=False, need_env_message=False)
        finally:
            self._close_client(chat)

    def send_direct_agent(self) -> None:
        """Resolve a direct Member prompt and send one real Agent request."""
        prompt = member_agent.get_system_prompt("member-a")
        self._send_agent_prompt(prompt)

    def send_plugin_precomposed_agent(self) -> None:
        """Simulate the plugin subprocess contract through the Member CLI."""
        import importlib

        manager.generate_system_prompt()
        plugin_prompt = (
            os.environ["TOPSAILAI_TEAM_PROMPT_CONTENT"]
            + "\n"
            + get_member_prompt("member-a")
        )
        prompt_file = self.team_path / "plugin-system-prompt.md"
        prompt_file.write_text(plugin_prompt, encoding="utf-8")
        self.monkeypatch.setenv("SYSTEM_PROMPT", str(prompt_file))
        self.monkeypatch.setenv("TOPSAILAI_SYSTEM_PROMPT", str(prompt_file))
        cli_path = Path(__file__).resolve().parents[2] / "cli"
        self.monkeypatch.syspath_prepend(str(cli_path))
        team_agent = importlib.import_module("team_agent")
        self.monkeypatch.setattr(team_agent, "get_member_name", lambda: "member-a")
        self.monkeypatch.setattr(team_agent, "get_agent_chat", self._get_agent_chat)
        team_agent.main()

    def send_explicit_false_agent(self) -> None:
        """Override matching plugin provenance and compose Team layers directly."""
        prompt_file = self.team_path / "explicit-false-system-prompt.md"
        prompt_file.write_text(BASE_MARKER, encoding="utf-8")
        self.monkeypatch.setenv("SYSTEM_PROMPT", str(prompt_file))
        self.monkeypatch.setenv("TOPSAILAI_SYSTEM_PROMPT", str(prompt_file))
        self.monkeypatch.setenv(
            "TOPSAILAI_TEAM_PROMPT_CONTENT", "PRECOMPOSED_PROVENANCE_MARKER"
        )
        prompt = member_agent.get_system_prompt(
            "member-a", team_prompt_precomposed=False
        )
        self._send_agent_prompt(prompt)

    def send_same_heading_segments_agent(self) -> None:
        """Send distinct user-controlled segments that share one heading text."""
        base_prompt = self.team_path / "same-heading-base.md"
        base_prompt.write_text(
            f"{AI_TEAM_HEADING}\nBDD_BASE_SAME_HEADING_POLICY",
            encoding="utf-8",
        )
        (self.team_path / "team.values").write_text(
            f"{AI_TEAM_HEADING}\nBDD_SHARED_SAME_HEADING_POLICY",
            encoding="utf-8",
        )
        self.monkeypatch.setenv("SYSTEM_PROMPT", str(base_prompt))
        self.monkeypatch.setenv("TOPSAILAI_TEAM_PROMPT", "")
        prompt = member_agent.get_system_prompt(
            "member-a", team_prompt_precomposed=False
        )
        self._send_agent_prompt(prompt)

    def send_agent_and_chat(self) -> None:
        """Drive Team Agent and Team Chat prompt semantics over real HTTP."""
        import importlib

        cli_path = Path(__file__).resolve().parents[2] / "cli"
        self.monkeypatch.syspath_prepend(str(cli_path))
        team_agent = importlib.import_module("team_agent")
        team_chat = importlib.import_module("team_chat")
        self.monkeypatch.setattr(team_agent, "get_member_name", lambda: "member-a")
        self.monkeypatch.setattr(team_chat, "get_member_name", lambda: "member-a")
        self.monkeypatch.setattr(team_agent, "get_agent_chat", self._get_agent_chat)
        self.monkeypatch.setattr(team_chat, "get_llm_chat", self._get_team_llm_chat)
        team_agent.main()
        team_chat.main()

    def _get_agent_chat(self, **kwargs: Any) -> Any:
        """Create a production AgentChat while preserving CLI arguments."""
        from topsailai.workspace.agent_shell import get_agent_chat

        kwargs.update({
            "message": USER_MESSAGE,
            "session_id": "",
            "need_project_workspace_lock": False,
        })
        chat = get_agent_chat(**kwargs)
        self.clients.append(chat.ai_agent)
        return chat

    def _get_team_llm_chat(self, **kwargs: Any) -> Any:
        """Create a production LLMChat while preserving Team Chat prompts."""
        kwargs.update({
            "message": USER_MESSAGE,
            "session_id": "",
            "need_stdout": False,
            "need_input_message": False,
            "need_print_session": False,
            "need_print_message": False,
        })
        chat = get_llm_chat(**kwargs)
        self.clients.append(chat)
        return chat

    def resolve_unreadable_prompt(self) -> None:
        """Resolve an unreadable shared path without issuing provider I/O."""
        try:
            member_agent.get_system_prompt("member-a")
        except Exception as error:  # noqa: BLE001 - the scenario asserts fail-closed
            self.error = error

    def state(self) -> dict[str, Any]:
        """Read captured provider requests over the real debug endpoint."""
        url = f"http://127.0.0.1:{self.server.server_port}/debug/state"
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.load(response)

    def system_prompts(self) -> list[str]:
        """Return system-message text from every captured provider request."""
        prompts = []
        for record in self.state()["request_bodies"]:
            system_messages = [
                message["content"]
                for message in record["body"]["messages"]
                if message.get("role") == "system"
            ]
            prompts.append("\n".join(system_messages))
        return prompts

    def close(self) -> None:
        """Close all clients, then stop this scenario's exact server thread."""
        for client in reversed(self.clients):
            client.close()
        self.clients.clear()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        manager.g_members.clear()
        if self.server_thread.is_alive():
            raise AssertionError("Team values mock-server thread did not stop")
