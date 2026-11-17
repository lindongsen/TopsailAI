"""Real HTTP/SSE harness for the opening-observation release BDD.

The release is a post-step of summarization: it runs only after the summary
result has been constructed, so the summary LLM still received the observation
and its content survives inside the summary. A skipped summarization never
reaches it.

These scenarios drive the production summarization path over a real loopback
provider and a real SQLite database, so the client, transport, summary
reconstruction, in-memory release and persisted deletion all stay inside the
assertion boundary. The provider-side request count proves the summary really
ran, and the persisted rows prove the release survives a reload.

Author: DawsonLin
"""

from __future__ import annotations

import json
import threading
import urllib.request
from typing import Any

from topsailai.ai_base.agent_base import AgentRun
from topsailai.ai_base.llm_pool.openai_client_pool import default_openai_client_pool
from topsailai.context import ctx_manager
from topsailai.context.session_manager.__base import SessionData
from topsailai.context.session_manager.sql import SessionSQLAlchemy
from topsailai.tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM
from topsailai.workspace.context.base import ContextRuntimeBase
from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

SESSION_ID = "opening-observation"

# The release ratio variable, named once so a scenario can unset it to exercise
# the built-in default instead of an explicit value.
RELEASE_RATIO_ENV = "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO"

# A startup observation large enough to exceed the release ratio by a wide
# margin, so the scenario does not depend on an exact token count.
LARGE_OBSERVATION_TEXT = "startup context " * 400

# A startup observation far below the release ratio, which must stay pinned.
SMALL_OBSERVATION_TEXT = "startup"

# A startup observation whose measured block is exactly 304 tokens. Paired with a
# 1000-token budget it sits on the inclusive boundary at ratio 0.304, which is the
# only way to prove the comparison is ``<=`` and not ``<``.
BOUNDARY_OBSERVATION_TEXT = "startup context " * 130

# A startup observation whose measured block is 525 tokens: above 0.3 of a
# 1000-token budget but below the 0.8 default, so it separates the two ratios.
MID_OBSERVATION_TEXT = "startup context " * 250

# The marker the mock provider returns, so a scenario can tell whether the
# summary is already present in a list or in storage at a given moment.
SUMMARY_MARKER = "SUMMARY TEXT"

SUMMARY_REPLY = json.dumps(
    [{"step_name": "final_answer", "raw_text": SUMMARY_MARKER}]
)


class OpeningObservationReleaseScenario:
    """Own one real-HTTP release scenario and all of its evidence."""

    def __init__(self, monkeypatch: Any, tmp_path: Any):
        """Initialize isolated configuration for one scenario."""
        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path
        self.server = None
        self.thread: threading.Thread | None = None
        self.agent: AgentRun | None = None
        self.owner: ContextRuntimeData | None = None
        self.storage: SessionSQLAlchemy | None = None
        self.warnings: list[str] = []
        self.events: list[tuple[str, dict]] = []
        self.summary_result: Any = None
        self.agent_runtime: ContextRuntimeAgent2LLM | None = None
        self.release_calls: list[dict] = []
        self._configure_environment()

    def _configure_environment(self) -> None:
        """Configure only the loopback provider and deterministic runtime flags."""
        values = {
            "OPENAI_API_KEY": "bdd-test-key",
            "OPENAI_MODEL": "opening-observation-mock",
            "LLM_RESPONSE_STREAM": "0",
            "TOPSAILAI_CONTEXT_SUMMARY_MODE": "runtime",
            "TOPSAILAI_CONTEXT_SUMMARY_PROCESSOR": "agent_llm_model",
            "TOPSAILAI_INTERACTIVE_MODE": "0",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
            "TOPSAILAI_MODEL_SETTINGS": "",
            "TOPSAILAI_USE_TOOL_CALLS": "0",
            "TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES": "",
            "TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP": "0",
            "TOPSAILAI_CONTEXT_MESSAGES_TAIL_OFFSET_TO_KEEP": "0",
            "TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT": "256000",
            "TOPSAILAI_CONTEXT_LOAD_USER_MD_ENABLED": "0",
            # Session retention would re-inject the whole session and make the
            # compressible set empty, which would skip the summary entirely.
            "TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES": "0",
            # Task retention is disabled so the intrinsic head holds only the
            # opening observation. The normal summary path then deletes the task
            # and the assistant message, which makes a later user-role tool
            # observation adjacent to the startup observation. That adjacency is
            # exactly the shape that used to widen the persisted deletion.
            "TOPSAILAI_CTX_SUMMARY_KEEP_FIRST_TASK_MESSAGE": "0",
            "TOPSAILAI_PRINT_TOOL_STAT": "0",
            "DEBUG": "0",
        }
        for key, value in values.items():
            self.monkeypatch.setenv(key, value)
        self.monkeypatch.setattr(
            "topsailai.workspace.llm_shell.record_project_history",
            lambda _sid: None,
        )

    def start(
        self,
        ratio: str | None = "0.3",
        token_threshold: str = "1000",
        observation_text: str = LARGE_OBSERVATION_TEXT,
        include_tool_observation: bool = False,
    ) -> None:
        """Start the provider, the database and the production runtime.

        ``ratio=None`` leaves the release ratio variable unset, which is the only
        way to exercise the built-in default instead of an explicit value.
        """
        if ratio is None:
            self.monkeypatch.delenv(RELEASE_RATIO_ENV, raising=False)
        else:
            self.monkeypatch.setenv(RELEASE_RATIO_ENV, ratio)
        self.monkeypatch.setenv(
            "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD", token_threshold
        )
        # The agent layer reads its own threshold, so it must be set too or the
        # agent-layer scenario would measure a different budget than the
        # user-facing one and the two could not be compared.
        self.monkeypatch.setenv(
            "TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD", token_threshold
        )
        self._start_server()
        self._start_storage()
        self._start_runtime()
        self._seed(
            observation_text=observation_text,
            include_tool_observation=include_tool_observation,
        )
        self._capture_observability()
        # The ordering is only observable at the instant the release runs, so the
        # wrapper is installed for every scenario instead of being opt-in.
        self.record_release_calls()

    def _start_server(self) -> None:
        """Start one loopback provider that answers the summary request."""
        config = MockServerConfig(
            port=0,
            request_body_capacity=16,
            reply=SUMMARY_REPLY,
            stream_chunks=(SUMMARY_REPLY,),
        )
        self.server = create_server(config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        base_url = f"http://{host}:{port}/v1"
        self.monkeypatch.setenv("OPENAI_API_BASE", base_url)
        self.monkeypatch.setenv("OPENAI_BASE_URL", base_url)

    def _start_storage(self) -> None:
        """Bind both persistence boundaries to one scenario-owned database."""
        self.storage = SessionSQLAlchemy(f"sqlite:///{self.tmp_path / 'release.db'}")
        assert self.storage.create_session(SessionData(SESSION_ID))
        self.monkeypatch.setattr(
            ctx_manager, "get_session_manager", lambda: self.storage
        )
        self.monkeypatch.setattr(
            ctx_manager, "get_managers_by_env", lambda: [self.storage.chat_history]
        )

    def _start_runtime(self) -> None:
        """Build the production agent and the user-facing runtime."""
        self.agent = AgentRun(
            system_prompt="Keep the user task and safety constraints.",
            tools={},
            agent_name="OpeningObservationBDD",
        )
        self.owner = ContextRuntimeData()
        self.owner.ai_agent = self.agent
        self.owner.session_id = SESSION_ID

    def _seed(self, observation_text: str, include_tool_observation: bool) -> None:
        """Seed the persisted conversation the summary will consume."""
        assert self.storage is not None
        messages = [
            {
                "role": "user",
                "content": {
                    "step_name": "observation",
                    "raw_text": observation_text,
                },
            },
            {
                "role": "user",
                "content": {"step_name": "task", "raw_text": "do the work"},
            },
            {"role": "assistant", "content": "work details " * 200},
        ]
        if include_tool_observation:
            # A tool result without a tool_call_id is stored as a user-role
            # observation, so it is indistinguishable from startup context by
            # shape alone and only contiguity separates it.
            messages.append(
                {
                    "role": "user",
                    "content": {
                        "step_name": "observation",
                        "raw_text": "tool output",
                    },
                }
            )
        for message in messages:
            self.storage.chat_history.add_session_message(
                message, session_id=SESSION_ID
            )

    def reseed(self, observation_text: str) -> None:
        """Replace the seeded conversation with a different observation size."""
        assert self.storage is not None
        for record in self.storage.get_messages_by_session(SESSION_ID):
            self.storage.chat_history.del_messages(record.msg_id, SESSION_ID)
        self._seed(observation_text=observation_text, include_tool_observation=False)

    def append_tool_observation(self) -> None:
        """Append a tool result that is stored as a user-role observation."""
        assert self.storage is not None
        self.storage.chat_history.add_session_message(
            {
                "role": "user",
                "content": {"step_name": "observation", "raw_text": "tool output"},
            },
            session_id=SESSION_ID,
        )

    def _capture_observability(self) -> None:
        """Capture the warning and the event the release must emit."""
        original_warning = None
        from topsailai.utils import print_tool

        original_warning = print_tool.print_warning

        def capture_warning(text, *args, **kwargs):
            """Record the warning text and forward to the real printer."""
            self.warnings.append(str(text))
            return original_warning(text, *args, **kwargs)

        self.monkeypatch.setattr(print_tool, "print_warning", capture_warning)

        import topsailai.events as events_module

        original_event = events_module.record_event

        def capture_event(event_type, payload=None, **kwargs):
            """Record the event and forward to the real collector."""
            self.events.append((event_type, dict(payload or {})))
            return original_event(event_type, payload, **kwargs)

        self.monkeypatch.setattr(events_module, "record_event", capture_event)

    def run_summary(self, force: bool = True) -> None:
        """Run the production user-facing summarization path.

        ``force=False`` reproduces a skipped summarization: the feasibility check
        rejects the request before any summary is generated, so the release is
        never reached and the observation must stay untouched.
        """
        assert self.storage is not None
        assert self.owner is not None
        loaded = self.storage.retrieve_messages(SESSION_ID)
        self.owner.messages = list(loaded)
        self.owner.ai_agent.messages = list(loaded)
        self.summary_result = self.owner.summarize_messages_for_processed(
            messages=list(loaded), force=force
        )

    def run_agent_summary(self, force: bool = True) -> None:
        """Run the production agent-layer summarization path.

        This exercises the ``agent2llm.py`` call site, which is a different
        reconstruction than the user-facing one: it rebuilds
        ``ai_agent.messages`` from the work-memory position instead of
        ``self.messages``, and it reads its own token threshold. A scenario that
        only drives the user-facing path cannot prove this call site runs.
        """
        assert self.storage is not None
        assert self.owner is not None
        loaded = self.storage.retrieve_messages(SESSION_ID)
        self.owner.messages = list(loaded)
        self.owner.ai_agent.messages = list(loaded)
        self.agent_runtime = ContextRuntimeAgent2LLM()
        self.agent_runtime.ai_agent = self.owner.ai_agent
        self.agent_runtime.messages = list(loaded)
        self.agent_runtime.session_id = SESSION_ID
        self.summary_result = self.agent_runtime.summarize_messages_for_processing(
            force=force
        )

    def run_in_memory_summary(self, force: bool = True) -> None:
        """Run the user-facing path without a session, which is the memory branch.

        With no ``session_id`` the reconstruction takes the ``else`` branch of
        ``summarize_messages_for_processed``. Without a session ``self.messages``
        *is* the session, so the summary must be applied to it before the
        observation is released from it. That is the second ``ctx_runtime.py``
        call site, and it must not touch storage.
        """
        assert self.storage is not None
        assert self.owner is not None
        loaded = self.storage.retrieve_messages(SESSION_ID)
        self.owner.messages = list(loaded)
        self.owner.ai_agent.messages = list(loaded)
        self.owner.session_id = ""
        self.summary_result = self.owner.summarize_messages_for_processed(
            messages=list(loaded), force=force
        )

    def memory_step_names(self) -> list[str]:
        """Return the step name of each in-memory message, or ``plain``."""
        assert self.owner is not None
        return self._step_names(self.owner.messages)

    def agent_memory_step_names(self) -> list[str]:
        """Return the step name of each agent-layer message, or ``plain``."""
        assert self.owner is not None
        return self._step_names(self.owner.ai_agent.messages)

    @staticmethod
    def _step_names(messages: list) -> list[str]:
        """Return the step name of each message, or ``plain`` when absent."""
        names = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, dict) and "step_name" in content:
                names.append(content["step_name"])
            else:
                names.append("plain")
        return names

    def persisted_texts(self) -> list[str]:
        """Return the raw persisted message text of every stored row."""
        assert self.storage is not None
        return [row.message for row in self.storage.get_messages_by_session(SESSION_ID)]

    def persisted_row_count(self) -> int:
        """Return how many rows the session still holds."""
        return len(self.persisted_texts())

    def observation_survives_in_memory(self) -> bool:
        """Return whether any in-memory message is still an observation."""
        return "observation" in self.memory_step_names()

    def observation_survives_in_agent_memory(self) -> bool:
        """Return whether any agent-layer message is still an observation."""
        return "observation" in self.agent_memory_step_names()

    def observation_survives_in_storage(self) -> bool:
        """Return whether any persisted row is still an observation."""
        return any("observation" in text for text in self.persisted_texts())

    def tool_observation_survives_in_storage(self) -> bool:
        """Return whether the later user-role tool result is still stored."""
        return any("tool output" in text for text in self.persisted_texts())

    def startup_observation_survives_in_storage(self) -> bool:
        """Return whether the startup observation is still stored."""
        return any("startup" in text for text in self.persisted_texts())

    def release_warnings(self) -> list[str]:
        """Return only the warnings that report a release."""
        return [text for text in self.warnings if "released opening observation" in text]

    def release_events(self) -> list[dict]:
        """Return only the events that report a release."""
        return [
            payload
            for event_type, payload in self.events
            if event_type == "context.summary.opening_observation_released"
        ]

    def record_release_calls(self) -> None:
        """Record the state observed at the moment the release is invoked.

        The persist-before-delete ordering is not observable in the final state:
        both orders converge on the same end result, so a final-state assertion
        cannot distinguish them. It is only observable at the instant the release
        runs, which is what this wrapper captures.

        The wrapper targets ``ContextRuntimeBase`` because all three call sites
        inherit the method from there. Patching a subclass would miss the agent
        layer, whose release is inherited rather than defined locally.
        """
        original = ContextRuntimeBase.release_opening_observation_after_summary
        scenario = self

        def wrapper(runtime, messages, token_threshold=0, session_id=""):
            """Record call-time state, then forward to the real release.

            ``runtime`` is the context object, not the scenario, so every
            observation is taken through the captured ``scenario``.
            """
            scenario.release_calls.append(
                {
                    "session_id": session_id,
                    "summary_in_released_list": scenario._contains_summary(messages),
                    "summary_in_storage": scenario._summary_in_storage(),
                    "released_is_owner_messages": messages
                    is getattr(runtime, "messages", None),
                    "released_is_agent_messages": messages
                    is getattr(getattr(runtime, "ai_agent", None), "messages", None),
                }
            )
            return original(runtime, messages, token_threshold, session_id)

        self.monkeypatch.setattr(
            ContextRuntimeBase, "release_opening_observation_after_summary", wrapper
        )

    @staticmethod
    def _contains_summary(messages: list) -> bool:
        """Return whether the list already carries the summary marker."""
        for message in messages:
            text = message if isinstance(message, str) else json.dumps(message)
            if SUMMARY_MARKER in text:
                return True
        return False

    def _summary_in_storage(self) -> bool:
        """Return whether the summary is already persisted."""
        return any(SUMMARY_MARKER in text for text in self.persisted_texts())

    def summary_in_memory(self) -> bool:
        """Return whether the summary is present in the in-memory session."""
        assert self.owner is not None
        return self._contains_summary(self.owner.messages)

    def summary_in_storage(self) -> bool:
        """Return whether the summary is present in the persisted session."""
        return self._summary_in_storage()

    def fail_summary_write(self) -> None:
        """Make the summary write report failure without raising.

        ``add_session_message`` returns a bool, so a failed write is a ``False``
        return rather than an exception. Patching the module-level function is
        the only way to exercise the suppression guard through the real path.
        """
        self.monkeypatch.setattr(
            ctx_manager, "add_session_message", lambda *args, **kwargs: False
        )

    def release_call_count(self) -> int:
        """Return how many times the release was invoked."""
        return len(self.release_calls)

    def last_release_call(self) -> dict:
        """Return the state recorded at the most recent release invocation."""
        assert self.release_calls, "the release was never invoked"
        return self.release_calls[-1]

    def provider_request_count(self) -> int:
        """Return how many requests actually reached the provider."""
        assert self.server is not None
        host, port = self.server.server_address
        with urllib.request.urlopen(
            f"http://{host}:{port}/debug/state", timeout=5
        ) as response:
            state = json.load(response)
        return len(state["request_bodies"])

    def close(self) -> None:
        """Close the agent, the database, the exact server and its thread."""
        if self.agent is not None:
            self.agent.close()
        if self.storage is not None:
            self.storage.chat_history.engine.dispose()
            self.storage.engine.dispose()
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise AssertionError("opening-observation BDD server thread did not stop")
        default_openai_client_pool.close_all()
