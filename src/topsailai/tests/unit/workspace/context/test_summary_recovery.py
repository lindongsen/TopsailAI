"""Conditional observation recovery contracts. Author: DawsonLin."""

import copy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from topsailai.workspace.context.ctx_runtime import ContextRuntimeData
from topsailai.workspace.context.summary_recovery import (
    RecoveryConfig, load_recovery_config, select_recovery,
    startup_observations,
)
from topsailai.workspace.context.summary_recovery_runtime import (
    prepare_recovery, apply_recovery, unchanged_recovery,
)


def message(role, text, step=None):
    """Build both raw-content and structured production messages."""
    return {"role": role, "content": {"step_name": step, "raw_text": text} if step else text}


def count(messages):
    """Use deterministic token units for exact arithmetic boundaries."""
    return sum(len(str(item["content"])) for item in messages)


def fixture_owner(enabled=True):
    """Create an explicitly configured runtime without process configuration."""
    owner = ContextRuntimeData(RecoveryConfig(enabled))
    owner.messages = [message("user", "x" * 1000, "observation"), message("user", "do work", "task")]
    owner.ai_agent = SimpleNamespace(
        messages=[message("system", "rules")] + copy.deepcopy(owner.messages),
        llm_model=SimpleNamespace(model_name="test", max_tokens=10),
        get_work_memory_first_position=lambda: 1,
        runtime=SimpleNamespace(token_stat=SimpleNamespace(add_msgs=Mock())),
    )
    owner._get_current_tokens = count
    owner._compute_context_limits = lambda *args: None
    owner._get_user2agent_summary_token_reserve = lambda: 20
    owner._get_agent2llm_summary_token_reserve = lambda: 20
    owner._check_dynamic_summary_feasibility = lambda *args: (True, "", None, None)
    return owner


def test_recovery_enabled_by_default():
    """Absent configuration and the shipped template must enable recovery."""
    from pathlib import Path

    assert RecoveryConfig().enabled is True
    assert load_recovery_config({}, Mock()) == RecoveryConfig(True, 0.7)
    template = Path(__file__).resolve().parents[4] / "env_template"
    assert "TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RECOVERY_ENABLED=1" in template.read_text()


@pytest.mark.parametrize("raw", ["0", "false", "invalid", "", None])
def test_disabled_config(raw):
    """Disabled configuration must never inspect a malformed ratio."""
    config = load_recovery_config({"TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RECOVERY_ENABLED": raw,
                                  "TOPSAILAI_CONTEXT_SUMMARY_RECOVERY_RATIO": object()}, Mock())
    assert config == RecoveryConfig(False)


@pytest.mark.parametrize("raw", ["nan", "inf", "0", "1", "oops", None])
def test_invalid_ratio(raw):
    """External invalid values warn and retain the conservative default."""
    log = Mock()
    assert load_recovery_config({"TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RECOVERY_ENABLED": "YES",
                                 "TOPSAILAI_CONTEXT_SUMMARY_RECOVERY_RATIO": raw}, log) == RecoveryConfig(True)
    log.warning.assert_called_once()


@pytest.mark.parametrize("ratio", [True, 0, 1, float("nan"), "0.7"])
def test_explicit_invalid_ratio(ratio):
    """Explicit typed injection must reject invalid values."""
    with pytest.raises(ValueError):
        RecoveryConfig(True, ratio)


def test_budget_edges_and_no_token_budget():
    """Exact fit is allowed, overflow rejected, and no threshold disables recovery."""
    owner = fixture_owner()
    session = owner.messages
    runtime = owner.ai_agent.messages
    normal = session
    kwargs = dict(config=RecoveryConfig(True, .5), session=session, runtime=runtime,
                  normal=normal, threshold=200, safe_limit=None, reserve=10,
                  count=lambda values: 1000 if session[0] in values else 90, layer="user2agent")
    assert select_recovery(**kwargs) is not None
    assert select_recovery(**(kwargs | {"reserve": 11})) is None
    assert select_recovery(**(kwargs | {"threshold": 0, "safe_limit": 200})) is None
    assert select_recovery(**(kwargs | {"normal": [session[-1]]})) is None
    assert select_recovery(**(kwargs | {"config": RecoveryConfig(False)})) is None


def test_requirements_and_later_observations_are_protected():
    """Only the opening block is removable; later real inputs survive."""
    owner = fixture_owner()
    owner.messages += [message("user", "never delete"), message("user", "later", "observation")]
    owner.ai_agent.messages = [message("system", "rules")] + owner.messages
    plan = select_recovery(RecoveryConfig(True), owner.messages, owner.ai_agent.messages,
                           owner.messages, 1000, None, 20, count, "user2agent")
    assert plan is not None
    assert owner.messages[0] not in plan.session_keep
    assert all(value in plan.session_keep for value in owner.messages[1:])
    assert startup_observations(owner.messages) == (owner.messages[0],)


@pytest.mark.parametrize("layer", ["user2agent", "agent2llm"])
def test_prepare_apply_and_session_isolation(monkeypatch, layer):
    """One successful decision removes both copies and suppresses identical retry."""
    monkeypatch.setenv(f"TOPSAILAI_{layer.upper()}_TOKEN_SUMMARIZE_THRESHOLD", "1000")
    owner = fixture_owner()
    original = owner.messages[0]
    plan = prepare_recovery(owner, layer, owner.messages, 0, 0, True)
    assert plan is not None
    assert apply_recovery(owner, plan, message("assistant", "compact summary"))
    assert original not in owner.messages and original not in owner.ai_agent.messages
    assert unchanged_recovery(owner)
    owner.ai_agent.messages.append(message("assistant", "new work"))
    assert not unchanged_recovery(owner)
    assert not unchanged_recovery(fixture_owner())
    owner.summary_recovery_config = RecoveryConfig(False)
    assert not unchanged_recovery(owner)


def test_context_change_and_oversized_result(monkeypatch):
    """Mutated generation input and oversized output never remove originals."""
    monkeypatch.setenv("TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD", "1000")
    owner = fixture_owner()
    plan = prepare_recovery(owner, "user2agent", owner.messages, 0, 0)
    before = copy.deepcopy(owner.messages)
    assert not apply_recovery(owner, plan, message("assistant", "huge" * 1000))
    assert owner.messages == before and unchanged_recovery(owner)
    owner.ai_agent.messages[0]["content"] = "changed"
    with pytest.raises(RuntimeError, match="changed"):
        apply_recovery(owner, plan, message("assistant", "small"))
    assert owner.messages == before


@pytest.mark.parametrize("layer", ["user2agent", "agent2llm"])
def test_real_entrypoint_and_generation_failure(monkeypatch, layer):
    """Both decorated owners consume the same plan; generation failure retains input."""
    monkeypatch.setenv(f"TOPSAILAI_{layer.upper()}_TOKEN_SUMMARIZE_THRESHOLD", "1000")
    owner = fixture_owner()
    original = copy.deepcopy(owner.messages)
    chat = SimpleNamespace(prompt_ctl=SimpleNamespace(messages=[message("assistant", "summary")]))
    owner._summarize_messages = Mock(return_value=(chat, None))
    method = owner.summarize_messages_for_processed if layer == "user2agent" else owner.summarize_messages_for_processing
    assert method(messages=owner.messages, force=True) is None
    assert owner.messages == original
    assert original[0] in owner._summarize_messages.call_args.args[0]
    owner._summarize_messages.return_value = (chat, "summary")
    assert method(messages=owner.messages, force=True) == "summary"
    assert original[0] not in owner.messages and original[0] not in owner.ai_agent.messages


def test_disabled_entrypoint_preserves_legacy(monkeypatch):
    """Disabled policy never plans or suppresses an existing summary."""
    owner = fixture_owner(False)
    owner._can_summarize_user2agent_messages = Mock(return_value=(False, 100))
    monkeypatch.setattr("topsailai.workspace.context.summary_recovery_runtime.select_recovery",
                        Mock(side_effect=AssertionError("disabled planner called")))
    assert owner.summarize_messages_for_processed(messages=owner.messages) is None
    owner._can_summarize_user2agent_messages.assert_called_once()


def test_storage_reload(monkeypatch):
    """Persist survivors once and expose partial-write failures without memory loss."""
    from topsailai.workspace.context import summary_recovery_runtime as integration
    monkeypatch.setenv("TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD", "1000")
    owner = fixture_owner()
    owner.session_id = "test"
    records = [SimpleNamespace(msg_id=str(i), message=msg) for i, msg in enumerate(owner.messages)]

    def read(session_id, for_raw=False):
        """Return the owned storage in the requested existing API shape."""
        return list(records) if for_raw else [item.message for item in records]

    def add(session_id, summary):
        """Append one summary record before deleting owned old IDs."""
        records.append(SimpleNamespace(msg_id="new", message=summary))
        return True

    def delete(session_id, ids):
        """Delete only exact selected IDs, preserving unrelated survivors."""
        records[:] = [item for item in records if item.msg_id not in ids]
        return True

    monkeypatch.setattr(integration.ctx_manager, "get_messages_by_session", read)
    monkeypatch.setattr(integration.ctx_manager, "add_session_message", add)
    monkeypatch.setattr(integration.ctx_manager, "del_session_messages", delete)
    plan = prepare_recovery(owner, "user2agent", owner.messages, 0, 0)
    assert apply_recovery(owner, plan, message("assistant", "summary"))
    owner.reset_messages()
    assert all("x" * 1000 not in str(item) for item in owner.messages)
    assert records[0].msg_id == "1"


def test_native_group_budget_and_retention():
    """Selecting a tool result retains its owner and budgets the complete group."""
    owner = fixture_owner()
    call = {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "type": "function", "function": {"name": "read", "arguments": "{}"}}]}
    result = {"role": "tool", "content": "file", "tool_call_id": "c"}
    runtime = owner.ai_agent.messages + [call, result]
    plan = select_recovery(RecoveryConfig(True), owner.messages, runtime,
                           owner.messages + [result], 1000, None, 20, count, "agent2llm")
    assert plan is not None
    assert call in plan.runtime_keep and result in plan.runtime_keep
    assert plan.candidate_tokens == count(list(plan.runtime_keep))


@pytest.mark.parametrize("failure", ["add", "delete", "changed"])
def test_storage_failures_keep_memory(monkeypatch, failure):
    """Storage rejection leaves active originals and exposes partial persistence."""
    from topsailai.workspace.context import summary_recovery_runtime as integration
    monkeypatch.setenv("TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD", "1000")
    owner = fixture_owner()
    owner.session_id = "test"
    before = copy.deepcopy(owner.messages)
    records = [SimpleNamespace(msg_id=str(i), message=msg) for i, msg in enumerate(owner.messages)]
    if failure == "changed":
        records = records[:-1]
    monkeypatch.setattr(integration.ctx_manager, "get_messages_by_session", lambda *args, **kwargs: records)
    add = Mock(return_value=failure != "add")
    delete = Mock(return_value=False)
    monkeypatch.setattr(integration.ctx_manager, "add_session_message", add)
    monkeypatch.setattr(integration.ctx_manager, "del_session_messages", delete)
    plan = prepare_recovery(owner, "user2agent", owner.messages, 0, 0)
    with pytest.raises(RuntimeError):
        apply_recovery(owner, plan, message("assistant", "summary"))
    assert owner.messages == before and not unchanged_recovery(owner)
    assert add.call_count == (failure != "changed")
    assert delete.call_count == (failure == "delete")


def test_disabled_agent2llm_entrypoint(monkeypatch):
    """Disabled Agent2LLM follows its legacy short-context path."""
    owner = fixture_owner(False)
    monkeypatch.setattr("topsailai.workspace.context.agent2llm.prepare_recovery",
                        Mock(side_effect=AssertionError("disabled planner called")))
    owner._summarize_messages = Mock(side_effect=AssertionError("short context summarized"))
    assert owner.summarize_messages_for_processing(messages=owner.messages) is None


def test_constructor_explicit_priority(monkeypatch):
    """Process configuration is parsed once and explicit injection takes priority."""
    monkeypatch.setenv("TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RECOVERY_ENABLED", "1")
    monkeypatch.setenv("TOPSAILAI_CONTEXT_SUMMARY_RECOVERY_RATIO", "0.6")
    owner = ContextRuntimeData()
    assert owner.summary_recovery_config == RecoveryConfig(True, .6)
    assert ContextRuntimeData(RecoveryConfig(False)).summary_recovery_config == RecoveryConfig(False)
    monkeypatch.setenv("TOPSAILAI_CONTEXT_SUMMARY_RECOVERY_RATIO", "0.8")
    assert owner.summary_recovery_config.ratio == .6


def test_prepare_refuses_unsafe_or_incomplete_inputs(monkeypatch):
    """Missing source coverage, dynamic rejection and excessive survivors fail closed."""
    monkeypatch.setenv("TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD", "1000")
    owner = fixture_owner()
    assert prepare_recovery(owner, "user2agent", owner.messages[:-1], 0, 0) is None
    owner.ai_agent.messages = owner.ai_agent.messages[:-1]
    assert prepare_recovery(owner, "user2agent", owner.messages, 0, 0) is None
    owner = fixture_owner()
    owner._check_dynamic_summary_feasibility = lambda *args: (False, "unsafe input", None, None)
    assert prepare_recovery(owner, "user2agent", owner.messages, 0, 0) is None
    owner = fixture_owner()
    owner.ai_agent.messages[0]["content"] = "large rules" * 100
    assert prepare_recovery(owner, "user2agent", owner.messages, 0, 0) is None


def test_no_opening_observation_and_observation_only():
    """Ordinary user input and the sole latest observation cannot be removed."""
    task = message("user", "do work", "task")
    observation = message("user", "x" * 1000, "observation")
    for messages in ([task], [observation]):
        assert select_recovery(RecoveryConfig(True), messages, messages, messages,
                               100, None, 20, count, "user2agent") is None


def test_repeated_later_observation_is_not_deleted():
    """Content equality cannot turn later user input into startup provenance."""
    owner = fixture_owner()
    owner.messages.append(copy.deepcopy(owner.messages[0]))
    owner.messages.append(message("user", "latest instruction"))
    owner.ai_agent.messages = list(owner.messages)
    assert select_recovery(RecoveryConfig(True), owner.messages, owner.ai_agent.messages,
                           owner.messages, 1000, None, 20, count, "user2agent") is None


def test_cross_layer_lower_trigger_limits_recovery(monkeypatch):
    """Updating both layers must leave room below the smaller active trigger."""
    monkeypatch.setenv("TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD", "1000")
    monkeypatch.setenv("TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD", "500")
    owner = fixture_owner()
    plan = prepare_recovery(owner, "agent2llm", owner.messages, 0, 0, True)
    assert plan is not None and plan.budget == 350
    assert not apply_recovery(owner, plan, message("assistant", "s" * 350))
    assert owner.messages[0] in owner.ai_agent.messages
