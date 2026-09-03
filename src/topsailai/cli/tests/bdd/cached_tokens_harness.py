"""In-process driver for cached-token behavior against the LLM mock server."""

from __future__ import annotations

import ast
import threading
from dataclasses import replace
from types import MethodType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from topsailai.ai_base.llm_base import LLMModel
from topsailai.context.session_manager.__base import SessionData
from topsailai.context.session_manager.sql import SessionSQLAlchemy
from topsailai.context.token import TokenStat
from topsailai.tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM


class _HarnessAgent:
    """Provide the minimal real context-runtime contract needed by summarization."""

    def __init__(self, model: LLMModel, messages: list[dict[str, Any]]):
        """Attach a real model and mutable Agent2LLM messages."""
        self.llm_model = model
        self.messages = list(messages)
        self.agent_type = "react"

    @staticmethod
    def get_work_memory_first_position() -> int:
        """Treat the complete harness message list as working memory."""
        return 0


class CachedTokensHarness:
    """Drive real HTTP requests and the real Agent2LLM summary rebuild path."""

    def __init__(self, monkeypatch):
        """Start an isolated mock endpoint and construct the real LLM client."""
        self.monkeypatch = monkeypatch
        self.server = create_server(MockServerConfig(port=0, reply="Mock summary"))
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="bdd-llm-mock-server",
            daemon=True,
        )
        self.server_thread.start()
        base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        monkeypatch.setenv("OPENAI_API_BASE", base_url)
        monkeypatch.setenv("OPENAI_BASE_URL", base_url)
        monkeypatch.setenv("OPENAI_API_KEY", "mock")
        monkeypatch.setenv("OPENAI_MODEL", "topsailai-mock")
        monkeypatch.setenv("LLM_RESPONSE_STREAM", "0")
        monkeypatch.setenv("TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED", "0")
        monkeypatch.setenv("TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES", "0")
        monkeypatch.setenv("TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP", "0")
        monkeypatch.setenv("TOPSAILAI_CONTEXT_MESSAGES_TAIL_OFFSET_TO_KEEP", "0")
        self.model = LLMModel()
        self.messages: list[dict[str, Any]] = []
        self.last_response = None
        self.last_summary_message_count: int | None = None
        self.last_snapshot: dict[str, Any] | None = None
        self.session_manager: SessionSQLAlchemy | None = None
        self.session_id: str | None = None
        self.session_stats: list[TokenStat] = []

    @staticmethod
    def stable_messages() -> list[dict[str, Any]]:
        """Return a conversation with a stable leading system and task prefix."""
        return [
            {"role": "system", "content": "cache behavior system prompt"},
            {
                "role": "user",
                "content": {"step_name": "task", "raw_text": "analyze cache behavior"},
            },
            {"role": "assistant", "content": "first result"},
            {"role": "user", "content": "continue"},
        ]

    def set_cache_usage_reporting(self, enabled: bool) -> None:
        """Control whether the mock Provider reports cache usage details."""
        self.server.config = replace(self.server.config, report_cache_usage=enabled)

    def request(self, messages: list[dict[str, Any]]) -> int | None:
        """Send one non-streaming request and retain observable output order."""
        self.messages = list(messages)
        output_events: list[tuple[str, Any]] = []
        original_send = self.model.send_content
        original_print = self.model.tokenStat.print_token_stat

        def _record_response(content: str) -> None:
            """Record response output while preserving the production sender path."""
            output_events.append(("response", content))
            original_send(content)

        def _record_token_summary() -> None:
            """Record TokenStat output while preserving the production print path."""
            output_events.append(("token_summary", None))
            original_print()

        with patch.object(self.model, "send_content", side_effect=_record_response), patch.object(
            self.model.tokenStat,
            "print_token_stat",
            side_effect=_record_token_summary,
        ):
            self.last_response, _ = self.model.call_llm_model(self.messages)
        self.last_output_events = output_events
        return self.model.tokenStat.current_cached_tokens

    def summarize(self) -> str | None:
        """Rebuild Agent2LLM context while replacing only summary generation."""
        agent = _HarnessAgent(self.model, self.messages)
        runtime = ContextRuntimeAgent2LLM()
        runtime.ai_agent = agent
        runtime.messages = [self.messages[0]] if self.messages else []

        summary_message = {"role": "assistant", "content": "Mock summary"}
        summary_chat = SimpleNamespace(
            prompt_ctl=SimpleNamespace(messages=[summary_message])
        )

        def _deterministic_summary(_runtime, _messages):
            """Return a deterministic summary while preserving the rebuild logic."""
            return summary_chat, "Mock summary"

        runtime._summarize_messages = MethodType(_deterministic_summary, runtime)
        answer = runtime.summarize_messages_for_processing(force=True)
        self.messages = list(agent.messages)
        self.last_summary_message_count = len(self.messages) if answer else None
        return answer

    def emit_snapshot(self, token_stat: TokenStat | None = None) -> dict[str, Any]:
        """Capture and parse the dictionary emitted by display-only TokenStat output."""
        stat = token_stat or self.model.tokenStat
        with patch("topsailai.context.token.print_info") as mock_print:
            stat.print_token_stat()
        message = mock_print.call_args.args[0]
        prefix = "[TokenStat] "
        assert message.startswith(prefix)
        self.last_snapshot = ast.literal_eval(message[len(prefix):])
        return self.last_snapshot

    def feed_first_byte(self, samples: list[float]) -> None:
        """Feed first-byte latency samples directly into the real TokenStat."""
        for sample in samples:
            self.model.tokenStat.add_first_byte(sample)

    def enable_session(self, session_id: str) -> None:
        """Create one real in-memory session shared by multiple TokenStat agents."""
        self.monkeypatch.setenv("SESSION_ID", session_id)
        self.session_id = session_id
        self.session_manager = SessionSQLAlchemy("sqlite:///:memory:")
        self.session_manager.create_session(
            SessionData(session_id=session_id, task="TokenStat BDD accumulation")
        )

    def request_with_session(self, messages: list[dict[str, Any]]) -> int | None:
        """Send a real HTTP request and persist its usage to the real session store."""
        assert self.session_manager is not None
        with patch(
            "topsailai.context.ctx_manager.get_session_manager",
            return_value=self.session_manager,
        ):
            return self.request(messages)

    def report_session_delta(self, tokens: int, cached_tokens: int) -> None:
        """Emit one agent's token delta into the shared session totals."""
        assert self.session_manager is not None
        stat = TokenStat(f"bdd-session-agent-{len(self.session_stats) + 1}", lifetime=0)
        stat.current_count = tokens
        stat.current_cached_tokens = cached_tokens
        self.session_stats.append(stat)
        with patch(
            "topsailai.context.ctx_manager.get_session_manager",
            return_value=self.session_manager,
        ), patch("topsailai.context.token.print_info"):
            stat.output_token_stat()

    def session_token_totals(self) -> tuple[int, int] | None:
        """Return combined token totals for the active shared session."""
        assert self.session_manager is not None
        assert self.session_id is not None
        return self.session_manager.get_session_token_totals(self.session_id)

    def session_token_usage(self) -> dict[str, int] | None:
        """Return prompt, cached, and completion totals for the active session."""
        assert self.session_manager is not None
        assert self.session_id is not None
        return self.session_manager.get_session_token_usage(self.session_id)

    @property
    def cached_tokens(self) -> int | None:
        """Return the currently observable cached-token statistic."""
        return self.model.tokenStat.current_cached_tokens

    @property
    def uncached_tokens(self) -> int | None:
        """Return the currently observable uncached-token statistic."""
        return self.model.tokenStat.uncached_tokens

    def response_cached_tokens(self) -> int:
        """Return cached tokens reported by the mock response for the last request."""
        return self.last_response.usage.prompt_tokens_details.cached_tokens

    def response_prompt_tokens(self) -> int:
        """Return total prompt tokens reported for the most recent request."""
        return self.last_response.usage.prompt_tokens

    def last_cache_result(self) -> dict[str, int]:
        """Return the mock server's cache metadata for the most recent request."""
        return self.server.prompt_cache.state()["requests"][-1]

    def response_completion_tokens(self) -> int:
        """Return completion tokens reported for the most recent request."""
        return self.last_response.usage.completion_tokens

    def request_state(self) -> dict[str, Any]:
        """Return server-side request accounting and captured request bodies."""
        state = self.server.prompt_cache.state()
        state.update(self.server.request_body_capture.state())
        return state

    def response_precedes_token_summary(self) -> bool:
        """Return whether response output preceded the user-visible token summary."""
        names = [name for name, _value in self.last_output_events]
        return names == ["response", "token_summary"]

    def run_one_shot_agent_chat(self) -> None:
        """Run one AgentChat turn backed by a real mock-server LLM request."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat

        output: list[str] = []
        runtime_agent = MagicMock()
        runtime_data = MagicMock()
        runtime_data.session_id = ""
        runtime_data.session_data = None
        runtime_data.messages = []
        runtime_agent.ctx_runtime_data = runtime_data

        ai_agent = MagicMock()
        ai_agent.agent_name = "BDD Agent"
        ai_agent.agent_type = "react"
        ai_agent.llm_model = self.model
        ai_agent.messages = self.stable_messages()

        def _run_agent(_step_call, message: str) -> str:
            """Send the AgentChat message through the real LLM client."""
            messages = list(ai_agent.messages)
            messages.append({"role": "user", "content": message})
            response, _ = self.model.call_llm_model(messages)
            return response.choices[0].message.content

        ai_agent.run.side_effect = _run_agent
        runtime_agent.ai_agent = ai_agent
        instruction = MagicMock()

        with patch(
            "topsailai.workspace.agent.hooks.base.init.get_hooks",
            return_value=[],
        ), patch(
            "topsailai.workspace.agent.agent_shell_base.env_tool.is_need_print",
            return_value=True,
        ), patch(
            "topsailai.workspace.agent.agent_shell_base.env_tool.is_debug_mode",
            return_value=False,
        ), patch(
            "topsailai.workspace.agent.agent_shell_base.env_tool.is_interactive_mode",
            return_value=False,
        ), patch(
            "topsailai.workspace.agent.agent_shell_base.tool_stat.get_agent_tool_stat"
        ) as mock_tool_stat, patch.object(
            self.model, "send_content"
        ), patch.object(
            self.model.tokenStat, "print_token_stat"
        ), patch.object(
            AgentChat, "_start_control_server"
        ), patch(
            "builtins.print", side_effect=lambda *args, **_kwargs: output.append(
                " ".join(str(arg) for arg in args)
            )
        ):
            mock_tool_stat.return_value.export_json.return_value = "{}"
            chat = AgentChat(
                hook_instruction=MagicMock(),
                ctx_rt_aiagent=runtime_agent,
                ctx_rt_instruction=instruction,
            )
            self.one_shot_answer = chat.run(message="one-shot request", times=1)

        self.one_shot_output = output
        self.one_shot_reset_count = runtime_data.reset_messages.call_count

    def one_shot_answer_precedes_summary_once(self) -> bool:
        """Return whether the one-shot answer precedes one final token summary."""
        answer_indexes = [
            index for index, value in enumerate(self.one_shot_output)
            if value == self.one_shot_answer
        ]
        summary_indexes = [
            index for index, value in enumerate(self.one_shot_output)
            if value.startswith("total_prompt_tokens :")
        ]
        return (
            len(answer_indexes) == 1
            and len(summary_indexes) == 1
            and answer_indexes[0] < summary_indexes[0]
            and self.one_shot_reset_count == 0
        )

    def close(self) -> None:
        """Stop the exact server and TokenStat threads created by this harness."""
        self.model.tokenStat.flag_running = False
        for stat in self.session_stats:
            stat.flag_running = False
        if self.session_manager is not None:
            self.session_manager.engine.dispose()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)
