"""Deterministic harness for summarize watermark BDD scenarios."""

from __future__ import annotations

import json
from types import SimpleNamespace

from topsailai.workspace.context.base import ContextRuntimeBase
from topsailai.workspace.context.ctx_runtime import ContextRuntimeData


class TokenStatStub:
    """Expose cached token usage without invoking an LLM."""

    def __init__(self, tokens: int = 0) -> None:
        self.current_tokens = tokens

    def add_msgs(self, messages, reset_cached_tokens=False) -> None:
        """Accept production token-stat refreshes without invoking tokenization."""
        return None


class ModelStub:
    """Provide the model fields consumed by context runtime code."""

    def __init__(self, maximum: int = 1000, max_tokens: int = 100) -> None:
        self.model_name = "bdd-model"
        self.max_tokens = max_tokens
        self.tokenStat = TokenStatStub()


class AgentStub:
    """Provide the minimum agent interface needed by runtime methods."""

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.llm_model = ModelStub()
        self.agent_type = "react"

    def get_work_memory_first_position(self) -> int:
        """Return the first non-system position used by summarization."""
        return 0


class SummarizeWatermarkHarness:
    """Build deterministic runtime objects and expose observable results."""

    def __init__(self, monkeypatch) -> None:
        self.monkeypatch = monkeypatch
        self.agent = AgentStub()
        self.runtime = ContextRuntimeData()
        self.runtime.init("", self.agent)
        self.base = ContextRuntimeBase()
        self.base.init("", self.agent)
        self.trace: dict = {}
        self.set_defaults()
        self.freeze_quantity_randomness()

    def freeze_quantity_randomness(self) -> None:
        """Freeze quantity randomization at the first configured candidate."""
        import topsailai.workspace.context.base as base_module

        self.monkeypatch.setattr(
            base_module.random, "choice", lambda values: values[0]
        )

    def set_defaults(self) -> None:
        """Set isolated defaults for all unrelated trigger paths."""
        values = {
            "TOPSAILAI_MODEL_MAX_CONTEXT_MAP": json.dumps({"bdd-model": 1000}),
            "TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT": "0",
            "TOPSAILAI_CONTEXT_LOW_WATERMARK_RATIO": "0.73",
            "TOPSAILAI_CONTEXT_HIGH_WATERMARK_RATIO": "0.93",
            "TOPSAILAI_CONTEXT_SUMMARY_OP_MARGIN": "100",
            "TOPSAILAI_CONTEXT_TOKEN_SAFETY_COEF": "1.0",
            "TOPSAILAI_CONTEXT_SUMMARY_MODE": "message",
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "0",
            "TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD": "0",
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "0",
            "TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD": "0",
            "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "0",
            "TOPSAILAI_AGENT2LLM_DUP_TOOL_CALL_SUMMARIZE_THRESHOLD": "0",
            "TOPSAILAI_REALTIME_TOKEN_CALCULATION": "0",
        }
        for key, value in values.items():
            self.monkeypatch.setenv(key, value)

    @staticmethod
    def parse_value(value: str):
        """Convert Gherkin numeric and non-finite literals to Python values."""
        lowered = value.strip().lower()
        if lowered == "null":
            return None
        if lowered == "nan":
            return float("nan")
        if lowered in {"inf", "+inf", "infinity", "+infinity"}:
            return float("inf")
        if lowered in {"-inf", "-infinity"}:
            return float("-inf")
        return float(value) if any(c in lowered for c in ".e") else int(value)

    def classify(self, tokens: int | None = None):
        """Classify a deterministic token snapshot."""
        result = self.base._classify_context_watermark(
            current_tokens=tokens,
            model_name="bdd-model",
            max_tokens=self.agent.llm_model.max_tokens,
        )
        self.trace["watermark"] = result
        return result

    def estimate(self, raw_tokens: int):
        """Estimate safe tokens with the production coefficient logic."""
        value = self.base._estimate_safe_tokens(raw_tokens)
        self.trace["safe_tokens"] = value
        return value

    def compute_limits(self):
        """Compute model-aware send and summary-safe limits."""
        value = self.base._compute_context_limits("bdd-model", 100)
        self.trace["limits"] = value
        return value

    def set_user_messages(self, count: int) -> None:
        """Create distinct User2Agent messages for quantity checks."""
        self.runtime.messages = [
            {"role": "assistant", "content": str(i)} for i in range(count)
        ]

    def set_agent_messages(self, count: int) -> None:
        """Create distinct Agent2LLM messages for quantity checks."""
        self.agent.messages = [
            {"role": "assistant", "content": str(i)} for i in range(count)
        ]

    def set_cached_tokens(self, tokens: int) -> None:
        """Set the cached TokenStat value used by non-realtime checks."""
        self.agent.llm_model.tokenStat.current_tokens = tokens

    def evaluate_session_retention(self, agent_count: int, session_count: int) -> None:
        """Drive real Agent2LLM retention logic without invoking an LLM."""
        self.set_agent_messages(agent_count)
        self.set_user_messages(session_count)
        self.trace["retention"] = None
        self.trace["retention_error"] = None

        def capture_feasibility(messages, head, tail, need_session, **kwargs):
            self.trace["retention"] = "kept" if need_session else "dropped"
            return False, None

        self.monkeypatch.setattr(
            self.runtime, "_can_summarize_agent2llm_messages", capture_feasibility
        )
        try:
            self.runtime.summarize_messages_for_processing(force=True)
        except Exception as error:
            self.trace["retention_error"] = error

    def evaluate_session_retention_expect_error(
        self, agent_count: int, session_count: int
    ) -> None:
        """Drive retention logic and retain an exception for a BDD assertion."""
        self.set_agent_messages(agent_count)
        self.set_user_messages(session_count)
        try:
            self.runtime.summarize_messages_for_processing(force=True)
        except Exception as error:
            self.trace["retention_error"] = error

    def current_tokens(self, explicit: bool = False):
        """Read cached or realtime token usage and retain the result."""
        messages = self.agent.messages if explicit else None
        if explicit:
            import topsailai.workspace.context.base as base_module
            value = base_module.count_tokens(str(messages))
        else:
            value = self.base._get_current_tokens(messages)
        self.trace["current_tokens"] = value
        return value


    def build_real_pre_chat_hook(self, classifications, processing_answer="summary"):
        """Build AgentChatBase and return its real registered pre-chat closure."""
        from unittest.mock import Mock, patch

        from topsailai.workspace.agent.agent_chat_base import AgentChatBase

        self.agent.agent_name = "bdd-agent"
        self.agent.hooks_after_init_prompt = []
        self.agent.hooks_after_new_session = []
        self.agent.hooks_pre_chat = []
        self.runtime.messages = [{"role": "user", "content": "task"}]
        self.runtime._classify_context_watermark = Mock(
            side_effect=classifications
        )
        self.runtime.is_need_summarize_for_processed = Mock(return_value=False)
        self.runtime.is_need_summarize_for_processing = Mock(return_value=False)
        self.runtime.summarize_messages_for_processed = Mock(
            return_value="session-summary"
        )
        self.runtime.summarize_messages_for_processing = Mock(
            return_value=processing_answer
        )
        bridge = SimpleNamespace(
            ai_agent=self.agent,
            ctx_runtime_data=self.runtime,
        )

        with (
            patch(
                "topsailai.workspace.agent.hooks.base.init.get_hooks",
                return_value=[],
            ),
            patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent"),
        ):
            AgentChatBase(
                hook_instruction=Mock(),
                ctx_rt_aiagent=bridge,
                ctx_rt_instruction=Mock(),
            )
        return self.agent.hooks_pre_chat[0]

    def run_real_pre_chat_hook(self, classifications, processing_answer="summary"):
        """Invoke the real pre-chat closure and record its outcome."""
        hook = self.build_real_pre_chat_hook(classifications, processing_answer)
        try:
            hook(self.agent)
        except Exception as error:
            self.trace["pre_chat_error"] = error
        else:
            self.trace["pre_chat_error"] = None
        self.trace["pre_chat_runtime"] = self.runtime


    def evaluate_min_extra(self, agent_count: int, session_count: int, minimum: int, force: bool) -> None:
        """Drive the real minimum-extra guard with a stubbed summary boundary."""
        from unittest.mock import Mock, patch

        self.monkeypatch.setenv("TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD", "100")
        self.monkeypatch.setenv("TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO", "1.0")
        self.monkeypatch.setenv("TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES", str(minimum))
        self.set_agent_messages(agent_count)
        self.set_user_messages(session_count)
        self.runtime._first_position = 0
        self.runtime._can_summarize_agent2llm_messages = Mock(return_value=(True, agent_count))
        summary_message = {"role": "assistant", "content": "summary"}
        fake_chat = SimpleNamespace(prompt_ctl=SimpleNamespace(messages=[summary_message]))
        with patch.object(
            self.runtime,
            "_summarize_messages",
            return_value=(fake_chat, "summary"),
        ), patch.object(self.agent.llm_model.tokenStat, "add_msgs"), patch.object(
            self.runtime, "_get_current_tokens", return_value=1
        ):
            try:
                self.trace["min_extra_result"] = self.runtime.summarize_messages_for_processing(force=force)
            except Exception as error:
                self.trace["min_extra_error"] = error
            else:
                self.trace["min_extra_error"] = None
            self.trace["min_extra_summary_called"] = self.runtime._summarize_messages.called


    def evaluate_feasibility(
        self,
        input_tokens: int,
        preserved_tokens: int,
        reserve: int,
        maximum: int = 1000,
        margin: int = 100,
    ) -> None:
        """Evaluate the real dynamic summary-feasibility boundary."""
        self.monkeypatch.setenv(
            "TOPSAILAI_MODEL_MAX_CONTEXT_MAP",
            json.dumps({"bdd-model": maximum}),
        )
        self.monkeypatch.setenv("TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT", "0")
        self.monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OP_MARGIN", str(margin)
        )
        self.monkeypatch.setenv("TOPSAILAI_CONTEXT_TOKEN_SAFETY_COEF", "1.0")
        self.agent.llm_model.model_name = "bdd-model"
        self.agent.llm_model.max_tokens = 0
        self.monkeypatch.setattr(
            self.base, "_get_current_tokens", lambda messages=None: input_tokens
        )
        self.trace["feasibility"] = self.base._check_dynamic_summary_feasibility(
            [{"role": "user", "content": "summary input"}],
            preserved_tokens,
            reserve,
        )


    def evaluate_agent_profitability_force(self) -> None:
        """Compare ordinary, forced, and hard-denied Agent2LLM feasibility."""
        from unittest.mock import patch

        messages = [
            {"role": "assistant", "content": "compressible-1"},
            {"role": "assistant", "content": "compressible-2"},
        ]
        self.agent.messages = messages
        self.runtime.messages = []
        self.monkeypatch.setenv(
            "TOPSAILAI_CTX_SUMMARY_KEEP_FIRST_TASK_MESSAGE", "0"
        )
        self.monkeypatch.setenv(
            "TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD", "1000"
        )
        self.monkeypatch.setenv(
            "TOPSAILAI_AGENT2LLM_SUMMARY_TOKEN_RESERVE", "50"
        )

        def token_count(selected=None, realtime=False):
            return 100 if selected is self.agent.messages else 50

        with patch.object(self.runtime, "_get_current_tokens", token_count), patch.object(
            self.runtime,
            "_check_dynamic_summary_feasibility",
            return_value=(True, "", 100, 900),
        ):
            self.trace["ordinary_profitability"] = (
                self.runtime._can_summarize_agent2llm_messages(
                    messages, 0, 0, False, force=False
                )[0]
            )
            self.trace["forced_profitability"] = (
                self.runtime._can_summarize_agent2llm_messages(
                    messages, 0, 0, False, force=True
                )[0]
            )

        with patch.object(self.runtime, "_get_current_tokens", token_count), patch.object(
            self.runtime,
            "_check_dynamic_summary_feasibility",
            return_value=(False, "summary_input_exceeds_safe_limit", 901, 900),
        ):
            self.trace["forced_hard_feasibility"] = (
                self.runtime._can_summarize_agent2llm_messages(
                    messages, 0, 0, False, force=True
                )[0]
            )

    def resolve_summary_head(self, keep_first_task: bool) -> None:
        """Resolve the real intrinsic summary head for a task-bearing prefix."""
        messages = [
            {"role": "system", "content": "system"},
            {
                "role": "user",
                "content": {"step_name": "observation", "content": "context"},
            },
            {
                "role": "user",
                "content": {"step_name": "task", "content": "task"},
            },
            {"role": "assistant", "content": "work"},
        ]
        self.monkeypatch.setenv(
            "TOPSAILAI_CTX_SUMMARY_KEEP_FIRST_TASK_MESSAGE",
            "1" if keep_first_task else "0",
        )
        self.trace["summary_head"] = self.base._get_summary_head_messages(messages)

    def rebuild_agent_messages(
        self,
        keep_session: bool,
        head_offset: int,
        tail_offset: int,
    ) -> None:
        """Run real Agent2LLM reconstruction with the external LLM stubbed."""
        from unittest.mock import Mock, patch

        system = {"role": "system", "content": "system-head"}
        observation = {
            "role": "user",
            "content": {"step_name": "observation", "content": "startup"},
        }
        middle = {"role": "assistant", "content": "middle"}
        internal_user = {"role": "user", "content": "internal-user"}
        tail = {"role": "assistant", "content": "tail"}
        session_marker = {"role": "assistant", "content": "session-marker"}
        session_user = {"role": "user", "content": "session-human"}
        summary = {"role": "assistant", "content": "summary"}
        agent_messages = [system, observation, middle, internal_user, tail]
        self.agent.messages = agent_messages[:]
        self.runtime.messages = [session_marker, session_user]
        self.monkeypatch.setenv(
            "TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES",
            "1" if keep_session else "0",
        )
        self.monkeypatch.setenv(
            "TOPSAILAI_CTX_SUMMARY_KEEP_FIRST_TASK_MESSAGE", "0"
        )
        self.monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_MESSAGES_TAIL_OFFSET_TO_KEEP", str(tail_offset)
        )
        self.monkeypatch.setenv(
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD", "100"
        )
        self.monkeypatch.setenv(
            "TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO", "1.0"
        )
        fake_chat = SimpleNamespace(prompt_ctl=SimpleNamespace(messages=[summary]))
        with patch.object(
            self.runtime,
            "_can_summarize_agent2llm_messages",
            return_value=(True, 100),
        ), patch.object(
            self.runtime,
            "_summarize_messages",
            return_value=(fake_chat, "summary"),
        ), patch.object(
            self.runtime,
            "_get_current_tokens",
            return_value=50,
        ), patch.object(
            self.agent.llm_model.tokenStat,
            "add_msgs",
            Mock(),
        ):
            self.runtime.summarize_messages_for_processing(
                head_offset_to_keep=head_offset,
                force=True,
            )
        self.trace["rebuilt_messages"] = self.agent.messages
        self.trace["rebuild_objects"] = {
            "head": agent_messages[:head_offset],
            "tail": agent_messages[-tail_offset:] if tail_offset else [],
            "session_marker": session_marker,
            "session_user": session_user,
            "internal_user": internal_user,
        }
