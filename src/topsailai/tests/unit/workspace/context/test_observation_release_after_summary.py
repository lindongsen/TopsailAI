"""
Unit tests for the post-summary opening-observation release.

The release is a post-step: it runs only after summarization has completed and
the result has already been constructed. A skipped summarization never reaches
it, which is intentional because there is no summary to compensate for the
removed content.

Author: DawsonLin
Created: 2026-11-16
"""

import json
from unittest.mock import MagicMock, patch

import pytest


OBSERVATION = {
    "role": "user",
    "content": {"step_name": "observation", "raw_text": "startup context"},
}
TASK = {
    "role": "user",
    "content": {"step_name": "task", "raw_text": "do the work"},
}
ASSISTANT = {"role": "assistant", "content": "working"}
TOOL_RESULT = {
    "role": "user",
    "content": {"step_name": "observation", "raw_text": "tool output"},
}


def _runtime():
    """Build a minimal runtime exposing only what the release needs."""
    from topsailai.workspace.context.base import ContextRuntimeBase

    runtime = ContextRuntimeBase.__new__(ContextRuntimeBase)
    runtime.ai_agent = MagicMock()
    runtime.ai_agent.llm_model.model_name = "test-model"
    runtime.ai_agent.llm_model.max_tokens = 1000
    runtime.session_id = ""
    return runtime


def _patch_tokens(runtime, tokens):
    """Make every token measurement return a fixed value."""
    runtime._get_current_tokens = MagicMock(return_value=tokens)


def _patch_budget(runtime, budget):
    """Make the budget resolution return a fixed value."""
    runtime._get_observation_release_budget = MagicMock(return_value=budget)


# =============================================================================
# Ratio configuration
# =============================================================================

class TestReleaseRatio:
    """The ratio must be environment-configurable with a safe default."""

    def test_default_ratio_is_0_3(self, monkeypatch):
        monkeypatch.delenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", raising=False
        )
        assert _runtime()._get_observation_release_ratio() == 0.3

    def test_custom_ratio_is_used(self, monkeypatch):
        monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "0.75"
        )
        assert _runtime()._get_observation_release_ratio() == 0.75

    def test_zero_disables_release(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "0")
        assert _runtime()._get_observation_release_ratio() == 0.0

    def test_negative_disables_release(self, monkeypatch):
        monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "-1"
        )
        assert _runtime()._get_observation_release_ratio() == 0.0

    def test_above_one_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "1.5"
        )
        assert _runtime()._get_observation_release_ratio() == 0.3

    def test_non_numeric_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "abc"
        )
        assert _runtime()._get_observation_release_ratio() == 0.3

    def test_one_is_allowed(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "1")
        assert _runtime()._get_observation_release_ratio() == 1.0


# =============================================================================
# Opening span detection
# =============================================================================

class TestOpeningObservationSpan:
    """Only the leading contiguous observation block may be released."""

    def test_detects_leading_block(self):
        messages = [OBSERVATION, OBSERVATION, TASK, ASSISTANT]
        assert _runtime()._opening_observation_span(messages) == (0, 2)

    def test_skips_leading_system_messages(self):
        messages = [{"role": "system", "content": "sys"}, OBSERVATION, TASK]
        assert _runtime()._opening_observation_span(messages) == (1, 2)

    def test_no_leading_observation(self):
        messages = [TASK, ASSISTANT]
        assert _runtime()._opening_observation_span(messages) == (0, 0)

    def test_tool_result_observation_is_not_leading(self):
        """A tool result also carries step_name=observation but must not match."""
        messages = [OBSERVATION, TASK, ASSISTANT, TOOL_RESULT]
        assert _runtime()._opening_observation_span(messages) == (0, 1)

    def test_json_string_shape_is_detected(self):
        """The persisted shape is a JSON string, not a dict."""
        messages = [json.dumps(OBSERVATION), json.dumps(TASK)]
        assert _runtime()._opening_observation_span(messages) == (0, 1)

    def test_empty_list(self):
        assert _runtime()._opening_observation_span([]) == (0, 0)


# =============================================================================
# Release decision
# =============================================================================

class TestReleaseDecision:
    """The observation is released only above the configured ratio."""

    def test_releases_when_above_ratio(self, monkeypatch):
        monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "0.3"
        )
        runtime = _runtime()
        _patch_tokens(runtime, 400)
        _patch_budget(runtime, 1000)
        messages = [OBSERVATION, TASK, ASSISTANT]

        removed = runtime.release_opening_observation_after_summary(messages)

        assert removed == 1
        assert messages == [TASK, ASSISTANT]

    def test_keeps_when_below_ratio(self, monkeypatch):
        monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "0.3"
        )
        runtime = _runtime()
        _patch_tokens(runtime, 100)
        _patch_budget(runtime, 1000)
        messages = [OBSERVATION, TASK, ASSISTANT]

        removed = runtime.release_opening_observation_after_summary(messages)

        assert removed == 0
        assert messages == [OBSERVATION, TASK, ASSISTANT]

    def test_equal_to_ratio_is_kept(self, monkeypatch):
        """The comparison is strictly greater, so equality does not release."""
        monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "0.5"
        )
        runtime = _runtime()
        _patch_tokens(runtime, 500)
        _patch_budget(runtime, 1000)
        messages = [OBSERVATION, TASK]

        assert runtime.release_opening_observation_after_summary(messages) == 0

    def test_ratio_zero_keeps_observation(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "0")
        runtime = _runtime()
        _patch_tokens(runtime, 999999)
        _patch_budget(runtime, 1000)
        messages = [OBSERVATION, TASK]

        assert runtime.release_opening_observation_after_summary(messages) == 0
        assert messages == [OBSERVATION, TASK]

    def test_zero_budget_keeps_observation(self, monkeypatch):
        monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "0.3"
        )
        runtime = _runtime()
        _patch_tokens(runtime, 999999)
        _patch_budget(runtime, 0)
        messages = [OBSERVATION, TASK]

        assert runtime.release_opening_observation_after_summary(messages) == 0

    def test_no_observation_is_a_noop(self, monkeypatch):
        monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "0.3"
        )
        runtime = _runtime()
        _patch_tokens(runtime, 999999)
        _patch_budget(runtime, 1000)
        messages = [TASK, ASSISTANT]

        assert runtime.release_opening_observation_after_summary(messages) == 0
        assert messages == [TASK, ASSISTANT]

    def test_removes_only_the_leading_block(self, monkeypatch):
        """A later tool-result observation must survive the release."""
        monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "0.3"
        )
        runtime = _runtime()
        _patch_tokens(runtime, 400)
        _patch_budget(runtime, 1000)
        messages = [OBSERVATION, OBSERVATION, TASK, ASSISTANT, TOOL_RESULT]

        removed = runtime.release_opening_observation_after_summary(messages)

        assert removed == 2
        assert messages == [TASK, ASSISTANT, TOOL_RESULT]

    def test_persisted_json_string_shape_is_released(self, monkeypatch):
        monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "0.3"
        )
        runtime = _runtime()
        _patch_tokens(runtime, 400)
        _patch_budget(runtime, 1000)
        messages = [json.dumps(OBSERVATION), json.dumps(TASK)]

        removed = runtime.release_opening_observation_after_summary(messages)

        assert removed == 1
        assert messages == [json.dumps(TASK)]


# =============================================================================
# Budget resolution
# =============================================================================

class TestReleaseBudget:
    """The budget is the smaller of the layer threshold and the safe limit."""

    def test_uses_threshold_when_smaller(self):
        runtime = _runtime()
        runtime._compute_context_limits = MagicMock(return_value=(512000, 473808, 511000))
        assert runtime._get_observation_release_budget(128000) == 128000

    def test_uses_safe_limit_when_smaller(self):
        runtime = _runtime()
        runtime._compute_context_limits = MagicMock(return_value=(512000, 473808, 511000))
        assert runtime._get_observation_release_budget(500000) == 473808

    def test_zero_when_nothing_available(self):
        runtime = _runtime()
        runtime._compute_context_limits = MagicMock(return_value=None)
        assert runtime._get_observation_release_budget(0) == 0

    def test_threshold_only_when_limits_unavailable(self):
        runtime = _runtime()
        runtime._compute_context_limits = MagicMock(return_value=None)
        assert runtime._get_observation_release_budget(64000) == 64000


# =============================================================================
# Persisted deletion
# =============================================================================

class TestPersistedDeletion:
    """The persisted rows must be removed, or the reload resurrects them."""

    def _raw(self, msg_id, message):
        record = MagicMock()
        record.msg_id = msg_id
        record.message = json.dumps(message)
        return record

    def test_deletes_leading_observation_rows(self):
        runtime = _runtime()
        raw = [
            self._raw("id0", OBSERVATION),
            self._raw("id1", TASK),
            self._raw("id2", ASSISTANT),
        ]
        with patch(
            "topsailai.workspace.context.base.ctx_manager.get_messages_by_session",
            return_value=raw,
        ), patch(
            "topsailai.workspace.context.base.ctx_manager.del_session_messages"
        ) as del_mock:
            removed = runtime._delete_persisted_opening_observation("sess-1")

        assert removed == 1
        del_mock.assert_called_once_with("sess-1", ["id0"])

    def test_deletes_by_identity_not_by_length(self):
        """A leading system row must not shift the deleted identifiers."""
        runtime = _runtime()
        raw = [
            self._raw("id0", {"role": "system", "content": "sys"}),
            self._raw("id1", OBSERVATION),
            self._raw("id2", TASK),
        ]
        with patch(
            "topsailai.workspace.context.base.ctx_manager.get_messages_by_session",
            return_value=raw,
        ), patch(
            "topsailai.workspace.context.base.ctx_manager.del_session_messages"
        ) as del_mock:
            removed = runtime._delete_persisted_opening_observation("sess-1")

        assert removed == 1
        del_mock.assert_called_once_with("sess-1", ["id1"])

    def test_no_rows_is_a_noop(self):
        runtime = _runtime()
        with patch(
            "topsailai.workspace.context.base.ctx_manager.get_messages_by_session",
            return_value=[],
        ), patch(
            "topsailai.workspace.context.base.ctx_manager.del_session_messages"
        ) as del_mock:
            assert runtime._delete_persisted_opening_observation("sess-1") == 0
        del_mock.assert_not_called()

    def test_no_leading_observation_is_a_noop(self):
        runtime = _runtime()
        raw = [self._raw("id0", TASK), self._raw("id1", ASSISTANT)]
        with patch(
            "topsailai.workspace.context.base.ctx_manager.get_messages_by_session",
            return_value=raw,
        ), patch(
            "topsailai.workspace.context.base.ctx_manager.del_session_messages"
        ) as del_mock:
            assert runtime._delete_persisted_opening_observation("sess-1") == 0
        del_mock.assert_not_called()

    def test_release_deletes_rows_when_session_id_present(self, monkeypatch):
        monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "0.3"
        )
        runtime = _runtime()
        _patch_tokens(runtime, 400)
        _patch_budget(runtime, 1000)
        runtime._delete_persisted_opening_observation = MagicMock(return_value=1)
        messages = [OBSERVATION, TASK]

        runtime.release_opening_observation_after_summary(
            messages, session_id="sess-1"
        )

        runtime._delete_persisted_opening_observation.assert_called_once_with("sess-1")

    def test_release_skips_deletion_without_session_id(self, monkeypatch):
        monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "0.3"
        )
        runtime = _runtime()
        _patch_tokens(runtime, 400)
        _patch_budget(runtime, 1000)
        runtime._delete_persisted_opening_observation = MagicMock(return_value=1)
        messages = [OBSERVATION, TASK]

        runtime.release_opening_observation_after_summary(messages)

        runtime._delete_persisted_opening_observation.assert_not_called()


# =============================================================================
# Call sites
# =============================================================================

class TestCallSites:
    """The release must run only after a summary result was constructed."""

    def test_agent2llm_calls_release_after_reconstruction(self):
        import inspect
        from topsailai.workspace.context import agent2llm

        source = inspect.getsource(agent2llm)
        assert "release_opening_observation_after_summary" in source
        # The call must follow the identity-change log, which is the last step
        # of reconstruction, so the result is already complete.
        log_index = source.index("_log_summarize_message_identity_changes")
        release_index = source.index("release_opening_observation_after_summary")
        assert release_index > log_index

    def test_ctx_runtime_calls_release_in_both_branches(self):
        import inspect
        from topsailai.workspace.context import ctx_runtime

        source = inspect.getsource(ctx_runtime)
        assert source.count("release_opening_observation_after_summary") == 2

    def test_persisted_branch_releases_before_reload(self):
        """The reload would resurrect the observation, so order matters."""
        import inspect
        from topsailai.workspace.context import ctx_runtime

        source = inspect.getsource(ctx_runtime)
        release_index = source.index("release_opening_observation_after_summary")
        reload_index = source.index("self.reset_messages()", release_index)
        assert release_index < reload_index

    def test_skipped_summary_never_releases(self):
        """A skipped summarization returns before any release call."""
        import inspect
        from topsailai.workspace.context import agent2llm

        source = inspect.getsource(agent2llm)
        no_answer_index = source.index("NO ANSWER")
        release_index = source.index("release_opening_observation_after_summary")
        assert no_answer_index < release_index


# =============================================================================
# Observability: print, log and event
# =============================================================================

class TestReleaseObservability:
    """Every message-changing behavior must print, log and record an event."""

    def _prepare(self, monkeypatch, tokens=400, budget=1000):
        monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RELEASE_RATIO", "0.3"
        )
        runtime = _runtime()
        _patch_tokens(runtime, tokens)
        _patch_budget(runtime, budget)
        return runtime

    def test_release_prints_a_warning(self, monkeypatch):
        """A rare release is reported with print_warning, not a step print."""
        runtime = self._prepare(monkeypatch)
        messages = [OBSERVATION, TASK]
        with patch(
            "topsailai.workspace.context.base.print_tool.print_warning"
        ) as warn_mock:
            runtime.release_opening_observation_after_summary(messages)

        warn_mock.assert_called_once()
        text = warn_mock.call_args[0][0]
        assert "released opening observation" in text
        assert "removed=1" in text
        assert "block_tokens=400" in text
        assert "budget=1000" in text

    def test_no_warning_when_nothing_is_released(self, monkeypatch):
        """A kept observation must not produce a warning."""
        runtime = self._prepare(monkeypatch, tokens=100)
        messages = [OBSERVATION, TASK]
        with patch(
            "topsailai.workspace.context.base.print_tool.print_warning"
        ) as warn_mock:
            assert runtime.release_opening_observation_after_summary(messages) == 0

        warn_mock.assert_not_called()

    def test_release_records_an_event(self, monkeypatch):
        """The in-memory removal must leave an auditable event."""
        runtime = self._prepare(monkeypatch)
        messages = [OBSERVATION, TASK]
        with patch("topsailai.events.record_event") as event_mock:
            runtime.release_opening_observation_after_summary(
                messages, session_id="sess-1"
            )

        event_mock.assert_called_once()
        event_type, payload = event_mock.call_args[0][0], event_mock.call_args[0][1]
        assert event_type == "context.summary.opening_observation_released"
        assert payload["removed_messages"] == 1
        assert payload["block_tokens"] == 400
        assert payload["budget_tokens"] == 1000
        assert payload["ratio"] == 0.3
        assert payload["session_id"] == "sess-1"
        assert payload["persisted"] is False

    def test_persisted_deletion_records_its_own_event(self):
        """The persisted removal is reported separately from the memory one."""
        runtime = _runtime()
        raw = [
            MagicMock(msg_id="id0", message=json.dumps(OBSERVATION)),
            MagicMock(msg_id="id1", message=json.dumps(TASK)),
        ]
        with patch(
            "topsailai.workspace.context.base.ctx_manager.get_messages_by_session",
            return_value=raw,
        ), patch(
            "topsailai.workspace.context.base.ctx_manager.del_session_messages"
        ), patch(
            "topsailai.workspace.context.base.print_tool.print_warning"
        ) as warn_mock, patch(
            "topsailai.events.record_event"
        ) as event_mock:
            runtime._delete_persisted_opening_observation("sess-1")

        warn_mock.assert_called_once()
        assert "removed_rows=1" in warn_mock.call_args[0][0]
        event_mock.assert_called_once()
        payload = event_mock.call_args[0][1]
        assert payload["removed_messages"] == 1
        assert payload["persisted"] is True

    def test_event_failure_does_not_interrupt_the_release(self, monkeypatch):
        """Event recording is best-effort and must never break summarization."""
        runtime = self._prepare(monkeypatch)
        messages = [OBSERVATION, TASK]
        with patch(
            "topsailai.events.record_event", side_effect=RuntimeError("boom")
        ):
            removed = runtime.release_opening_observation_after_summary(messages)

        assert removed == 1
        assert messages == [TASK]
