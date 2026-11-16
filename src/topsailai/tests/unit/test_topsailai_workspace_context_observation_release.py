"""
Unit tests for the opening-observation release gate.

The gate allows the opening user observation to be summarized away once it
occupies more than a configured ratio of the usable input budget. Below that
ratio the observation stays pinned, which preserves the historical behavior.

Author: DawsonLin
Created: 2026-11-16
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM
from topsailai.workspace.context.base import ContextRuntimeBase
from topsailai.workspace.context.ctx_runtime import ContextRuntimeData


RATIO_ENV = "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO"
AGENT2LLM_THRESHOLD_ENV = "TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD"
USER2AGENT_THRESHOLD_ENV = "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD"
MODEL_MAP_ENV = "TOPSAILAI_MODEL_MAX_CONTEXT_MAP"

MODEL_NAME = "release-gate-model"
MODEL_MAX_CONTEXT = 100000
MODEL_MAX_TOKENS = 1000
LAYER_THRESHOLD = 1000

# 20000 characters is roughly 5000 tokens, far above 0.3 * 1000.
BIG_OBSERVATION_TEXT = "x" * 20000
SMALL_OBSERVATION_TEXT = "tiny"


def make_observation(text):
    """Build an opening observation message in the runtime dict shape."""
    return {
        "role": "user",
        "content": {"step_name": "observation", "raw_text": text},
    }


def make_task(text="do it"):
    """Build a task message in the runtime dict shape."""
    return {"role": "user", "content": {"step_name": "task", "raw_text": text}}


def make_assistant(text="ok"):
    """Build an assistant message."""
    return {"role": "assistant", "content": text}


def label(message):
    """Return a short label identifying one message for assertions."""
    content = message["content"]
    if isinstance(content, str):
        return content
    return content.get("step_name")


def build_runtime(runtime_class, messages):
    """Create a runtime whose model limits and messages are deterministic."""
    runtime = runtime_class()
    runtime.ai_agent = MagicMock()
    runtime.ai_agent.llm_model.model_name = MODEL_NAME
    runtime.ai_agent.llm_model.max_tokens = MODEL_MAX_TOKENS
    runtime.messages = list(messages)
    return runtime


@pytest.fixture
def release_env(monkeypatch):
    """Configure a small budget so a large observation crosses the ratio."""
    monkeypatch.setenv(RATIO_ENV, "0.3")
    monkeypatch.setenv(AGENT2LLM_THRESHOLD_ENV, str(LAYER_THRESHOLD))
    monkeypatch.setenv(USER2AGENT_THRESHOLD_ENV, str(LAYER_THRESHOLD))
    monkeypatch.setenv(
        MODEL_MAP_ENV, json.dumps({MODEL_NAME: MODEL_MAX_CONTEXT})
    )
    return monkeypatch


class TestReleaseRatioConfiguration:
    """The ratio must be environment-configurable with a safe fallback."""

    def test_default_ratio_is_used_when_unset(self, monkeypatch):
        """An unset variable falls back to the documented default."""
        monkeypatch.delenv(RATIO_ENV, raising=False)

        assert ContextRuntimeBase()._get_observation_release_ratio() == 0.3

    def test_configured_ratio_is_read(self, monkeypatch):
        """A configured value inside (0, 1] is honored exactly."""
        monkeypatch.setenv(RATIO_ENV, "0.55")

        assert ContextRuntimeBase()._get_observation_release_ratio() == 0.55

    def test_zero_disables_the_gate(self, monkeypatch):
        """A non-positive value disables the gate instead of releasing."""
        monkeypatch.setenv(RATIO_ENV, "0")

        assert ContextRuntimeBase()._get_observation_release_ratio() == 0.0

    def test_negative_disables_the_gate(self, monkeypatch):
        """A negative value also disables the gate."""
        monkeypatch.setenv(RATIO_ENV, "-1")

        assert ContextRuntimeBase()._get_observation_release_ratio() == 0.0

    def test_ratio_above_one_falls_back_to_default(self, monkeypatch):
        """A ratio above 1 is meaningless and falls back to the default."""
        monkeypatch.setenv(RATIO_ENV, "1.5")

        assert ContextRuntimeBase()._get_observation_release_ratio() == 0.3

    def test_non_numeric_ratio_falls_back_to_default(self, monkeypatch):
        """A non-numeric value falls back to the default."""
        monkeypatch.setenv(RATIO_ENV, "not-a-number")

        assert ContextRuntimeBase()._get_observation_release_ratio() == 0.3


class TestObservationSpan:
    """Only the leading contiguous observation block may be released."""

    def test_span_covers_leading_block_after_system_prefix(self):
        """A system prefix is skipped and the whole opening block is covered."""
        messages = [
            {"role": "system", "content": "system"},
            make_observation("one"),
            make_observation("two"),
            make_task(),
        ]

        assert ContextRuntimeBase()._opening_observation_span(messages) == (1, 3)

    def test_span_stops_at_first_non_observation(self):
        """A later observation is not part of the opening block."""
        messages = [
            make_observation("one"),
            make_assistant(),
            make_observation("two"),
        ]

        assert ContextRuntimeBase()._opening_observation_span(messages) == (0, 1)

    def test_span_is_empty_without_observation(self):
        """No opening observation yields an empty span."""
        messages = [make_task(), make_assistant()]

        assert ContextRuntimeBase()._opening_observation_span(messages) == (0, 0)

    def test_span_accepts_persisted_json_string_shape(self):
        """The persisted JSON-string shape is recognized identically."""
        messages = [
            json.dumps(make_observation("one")),
            json.dumps(make_task()),
        ]

        assert ContextRuntimeBase()._opening_observation_span(messages) == (0, 1)


class TestReleaseBudget:
    """The budget is the smaller of the layer threshold and the safe limit."""

    def test_budget_uses_layer_threshold_when_smaller(self, release_env):
        """A small layer threshold wins over a large model context."""
        runtime = build_runtime(ContextRuntimeAgent2LLM, [])

        assert runtime._get_observation_release_budget() == LAYER_THRESHOLD

    def test_budget_uses_safe_limit_when_threshold_is_larger(self, monkeypatch):
        """A threshold larger than the safe limit cannot inflate the budget."""
        monkeypatch.setenv(RATIO_ENV, "0.3")
        monkeypatch.setenv(AGENT2LLM_THRESHOLD_ENV, "900000")
        monkeypatch.setenv(
            MODEL_MAP_ENV, json.dumps({MODEL_NAME: MODEL_MAX_CONTEXT})
        )
        runtime = build_runtime(ContextRuntimeAgent2LLM, [])

        budget = runtime._get_observation_release_budget()

        assert budget < 900000
        assert budget > 0

    def test_budget_is_zero_without_any_denominator(self, monkeypatch):
        """No threshold and no model limit keeps the gate disabled."""
        monkeypatch.setenv(RATIO_ENV, "0.3")
        monkeypatch.setenv(AGENT2LLM_THRESHOLD_ENV, "0")
        monkeypatch.delenv(MODEL_MAP_ENV, raising=False)
        runtime = build_runtime(ContextRuntimeAgent2LLM, [])

        assert runtime._get_observation_release_budget() == 0


class TestGateDecision:
    """The gate fires only when the observation exceeds the ratio."""

    def test_large_observation_is_released(self, release_env):
        """An observation above the ratio is released."""
        runtime = build_runtime(
            ContextRuntimeAgent2LLM,
            [make_observation(BIG_OBSERVATION_TEXT), make_task(), make_assistant()],
        )

        assert runtime._should_release_opening_observation(runtime.messages) is True

    def test_small_observation_is_retained(self, release_env):
        """An observation below the ratio stays pinned."""
        runtime = build_runtime(
            ContextRuntimeAgent2LLM,
            [make_observation(SMALL_OBSERVATION_TEXT), make_task(), make_assistant()],
        )

        assert runtime._should_release_opening_observation(runtime.messages) is False

    def test_disabled_ratio_never_releases(self, release_env):
        """A disabled gate keeps even a huge observation pinned."""
        release_env.setenv(RATIO_ENV, "0")
        runtime = build_runtime(
            ContextRuntimeAgent2LLM,
            [make_observation(BIG_OBSERVATION_TEXT), make_task(), make_assistant()],
        )

        assert runtime._should_release_opening_observation(runtime.messages) is False

    def test_raised_ratio_keeps_the_same_observation(self, release_env):
        """Raising the ratio above the measured share closes the gate."""
        release_env.setenv(RATIO_ENV, "1")
        release_env.setenv(AGENT2LLM_THRESHOLD_ENV, "100000")
        runtime = build_runtime(
            ContextRuntimeAgent2LLM,
            [make_observation(BIG_OBSERVATION_TEXT), make_task(), make_assistant()],
        )

        assert runtime._should_release_opening_observation(runtime.messages) is False


class TestHeadPolicy:
    """Both head branches must honor the gate."""

    def test_head_drops_released_observation(self, release_env):
        """The task-inclusive branch drops a released observation."""
        runtime = build_runtime(
            ContextRuntimeAgent2LLM,
            [make_observation(BIG_OBSERVATION_TEXT), make_task(), make_assistant()],
        )

        head = runtime._get_summary_head_messages(
            runtime.messages, keep_first_task=True
        )

        assert [label(message) for message in head] == ["task"]

    def test_head_keeps_retained_observation(self, release_env):
        """The same branch keeps an observation below the ratio."""
        runtime = build_runtime(
            ContextRuntimeAgent2LLM,
            [make_observation(SMALL_OBSERVATION_TEXT), make_task(), make_assistant()],
        )

        head = runtime._get_summary_head_messages(
            runtime.messages, keep_first_task=True
        )

        assert [label(message) for message in head] == ["observation", "task"]

    def test_observation_only_head_drops_released_observation(self, release_env):
        """The observation-only branch drops a released observation."""
        runtime = build_runtime(
            ContextRuntimeAgent2LLM,
            [make_observation(BIG_OBSERVATION_TEXT), make_task(), make_assistant()],
        )

        head = runtime._get_summary_head_messages(
            runtime.messages, keep_first_task=False
        )

        assert head == []

    def test_observation_only_head_keeps_retained_observation(self, release_env):
        """The observation-only branch keeps an observation below the ratio."""
        runtime = build_runtime(
            ContextRuntimeAgent2LLM,
            [make_observation(SMALL_OBSERVATION_TEXT), make_task(), make_assistant()],
        )

        head = runtime._get_summary_head_messages(
            runtime.messages, keep_first_task=False
        )

        assert [label(message) for message in head] == ["observation"]


class TestAgent2LLMPartitions:
    """Session retention must not re-add the released observation."""

    def test_released_observation_becomes_compressible(self, release_env):
        """A released observation leaves the preserved set entirely."""
        runtime = build_runtime(
            ContextRuntimeAgent2LLM,
            [make_observation(BIG_OBSERVATION_TEXT), make_task(), make_assistant()],
        )

        preserved, compressible = runtime._build_agent2llm_summary_partitions(
            runtime.messages, 0, 0, True
        )

        assert "observation" not in [label(message) for message in preserved]
        assert [label(message) for message in compressible] == ["observation"]

    def test_retained_observation_stays_preserved(self, release_env):
        """A retained observation keeps the historical preserved set."""
        runtime = build_runtime(
            ContextRuntimeAgent2LLM,
            [make_observation(SMALL_OBSERVATION_TEXT), make_task(), make_assistant()],
        )

        preserved, compressible = runtime._build_agent2llm_summary_partitions(
            runtime.messages, 0, 0, True
        )

        assert [label(message) for message in preserved] == [
            "observation",
            "task",
            "ok",
        ]
        assert compressible == []

    def test_last_user_message_observation_is_not_re_added(self, release_env):
        """The last user message must not resurrect a released observation."""
        runtime = build_runtime(
            ContextRuntimeAgent2LLM,
            [make_observation(BIG_OBSERVATION_TEXT), make_assistant(), make_assistant()],
        )
        assert runtime.last_user_message is runtime.messages[0]

        preserved, compressible = runtime._build_agent2llm_summary_partitions(
            runtime.messages, 0, 0, True
        )

        assert "observation" not in [label(message) for message in preserved]
        assert "observation" in [label(message) for message in compressible]


class TestUser2AgentPartitions:
    """The User2Agent layer must apply the same gate."""

    def test_released_observation_becomes_compressible(self, release_env):
        """A released observation leaves the preserved set entirely."""
        runtime = build_runtime(
            ContextRuntimeData,
            [make_observation(BIG_OBSERVATION_TEXT), make_task(), make_assistant()],
        )

        preserved, compressible = runtime._build_user2agent_summary_partitions(
            runtime.messages, 0, 0
        )

        assert "observation" not in [label(message) for message in preserved]
        assert "observation" in [label(message) for message in compressible]

    def test_retained_observation_stays_preserved(self, release_env):
        """A retained observation keeps the historical preserved set."""
        runtime = build_runtime(
            ContextRuntimeData,
            [make_observation(SMALL_OBSERVATION_TEXT), make_task(), make_assistant()],
        )

        preserved, compressible = runtime._build_user2agent_summary_partitions(
            runtime.messages, 0, 0
        )

        assert [label(message) for message in preserved] == ["observation", "task"]
        assert [label(message) for message in compressible] == ["ok"]

    def test_last_user_message_observation_is_not_re_added(self, release_env):
        """The reverse last-user scan must skip a released observation."""
        runtime = build_runtime(
            ContextRuntimeData,
            [make_observation(BIG_OBSERVATION_TEXT), make_assistant(), make_assistant()],
        )

        preserved, compressible = runtime._build_user2agent_summary_partitions(
            runtime.messages, 0, 0
        )

        assert "observation" not in [label(message) for message in preserved]
        assert "observation" in [label(message) for message in compressible]


class TestDropIsPositional:
    """Removal must target positions, not matching content."""

    def test_later_identical_text_is_not_dropped(self, release_env):
        """A later message repeating the startup text survives the drop."""
        observation = make_observation(BIG_OBSERVATION_TEXT)
        repeated = {"role": "assistant", "content": BIG_OBSERVATION_TEXT}
        runtime = build_runtime(
            ContextRuntimeAgent2LLM, [observation, make_task(), repeated]
        )

        dropped = runtime._drop_opening_observation(runtime.messages)

        assert [label(message) for message in dropped] == ["task", BIG_OBSERVATION_TEXT]

    def test_closed_gate_returns_the_group_unchanged(self, release_env):
        """A closed gate must not alter the group at all."""
        runtime = build_runtime(
            ContextRuntimeAgent2LLM,
            [make_observation(SMALL_OBSERVATION_TEXT), make_task(), make_assistant()],
        )
        original = list(runtime.messages)

        dropped = runtime._drop_opening_observation(runtime.messages)

        assert dropped == original

    def test_single_message_group_is_judged_by_the_whole_context(self, release_env):
        """A one-message group uses the reference context for the decision."""
        runtime = build_runtime(
            ContextRuntimeAgent2LLM,
            [make_observation(BIG_OBSERVATION_TEXT), make_task(), make_assistant()],
        )

        dropped = runtime._drop_opening_observation(
            [runtime.messages[0]], reference_messages=runtime.messages
        )

        assert dropped == []


class TestPersistentDeletion:
    """The persistence path must delete the released observation from storage.

    This is the path that actually removes rows from the database. A length-based
    prefix slice would keep the observation and delete the task instead, so the
    observation would survive in storage and reload on the next turn while every
    in-memory assertion still passed.
    """

    def _run_summarize(self, monkeypatch, messages, raw_messages):
        """Drive summarize_messages_for_processed through the session branch."""
        from topsailai.workspace.context import ctx_runtime as ctx_runtime_module

        mock_ctx_manager = MagicMock()
        mock_ctx_manager.get_messages_by_session.return_value = raw_messages
        monkeypatch.setattr(ctx_runtime_module, "ctx_manager", mock_ctx_manager)

        runtime = build_runtime(ContextRuntimeData, messages)
        runtime.session_id = "release-gate-session"

        llm_chat = MagicMock()
        llm_chat.prompt_ctl.messages = [{"role": "assistant", "content": "Summary"}]

        monkeypatch.setattr(
            runtime, "_summarize_messages", lambda *a, **k: (llm_chat, "Summary")
        )
        monkeypatch.setattr(
            runtime, "_can_summarize_user2agent_messages", lambda *a, **k: (True, 100)
        )
        monkeypatch.setattr(
            runtime, "_get_head_offset_to_keep_in_summary", lambda *a, **k: 0
        )
        monkeypatch.setattr(
            runtime, "_get_tail_offset_to_keep_in_summary", lambda *a, **k: 0
        )
        monkeypatch.setattr(runtime, "reset_messages", lambda *a, **k: None)

        runtime.summarize_messages_for_processed(messages=messages, force=True)
        return mock_ctx_manager

    def _raw_messages(self, messages):
        """Wrap messages in persisted-record doubles carrying stable ids."""
        raw_messages = []
        for index, message in enumerate(messages):
            raw_message = MagicMock()
            raw_message.msg_id = f"id{index}"
            raw_message.message = message
            raw_messages.append(raw_message)
        return raw_messages

    def _deleted_ids(self, mock_ctx_manager):
        """Collect every message id passed to del_session_messages."""
        deleted_ids = []
        for call_args in mock_ctx_manager.del_session_messages.call_args_list:
            deleted_ids.extend(call_args[0][1])
        return deleted_ids

    def test_released_observation_is_deleted_from_storage(self, release_env):
        """The released observation row is deleted and the task row survives."""
        messages = [
            make_observation(BIG_OBSERVATION_TEXT),
            make_task(),
            make_assistant(),
        ]
        raw_messages = self._raw_messages(messages)

        mock_ctx_manager = self._run_summarize(release_env, messages, raw_messages)

        deleted_ids = self._deleted_ids(mock_ctx_manager)
        assert "id0" in deleted_ids
        assert "id1" not in deleted_ids

    def test_retained_observation_is_not_deleted_from_storage(self, release_env):
        """A retained observation keeps the historical deletion behavior."""
        messages = [
            make_observation(SMALL_OBSERVATION_TEXT),
            make_task(),
            make_assistant(),
        ]
        raw_messages = self._raw_messages(messages)

        mock_ctx_manager = self._run_summarize(release_env, messages, raw_messages)

        deleted_ids = self._deleted_ids(mock_ctx_manager)
        assert "id0" not in deleted_ids
        assert "id1" not in deleted_ids
        assert "id2" in deleted_ids

    def test_released_observation_is_not_kept_as_last_user_message(self, release_env):
        """The last-user rule must not resurrect the released observation row."""
        messages = [
            make_observation(BIG_OBSERVATION_TEXT),
            make_assistant(),
            make_assistant(),
        ]
        raw_messages = self._raw_messages(messages)

        mock_ctx_manager = self._run_summarize(release_env, messages, raw_messages)

        deleted_ids = self._deleted_ids(mock_ctx_manager)
        assert "id0" in deleted_ids
