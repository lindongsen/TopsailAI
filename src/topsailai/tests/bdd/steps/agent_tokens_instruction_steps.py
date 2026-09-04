"""Unique BDD steps for the `/agent.tokens` instruction."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pytest_bdd import given, then, when

from topsailai.utils.instruction_tool import HookInstruction
from topsailai.workspace.context.base import ContextWatermarkResult
from topsailai.workspace.context.instruction import ContextRuntimeInstructions


@pytest.fixture
def agent_tokens_ctx():
    """Store the isolated local instruction scenario state."""
    return {}


@given("an active agent tokens instruction with distinct runtime and session messages")
def given_active_agent_tokens_instruction(agent_tokens_ctx):
    """Create canonical Agent2LLM and User2Agent message layers."""
    agent = SimpleNamespace(
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "runtime"},
        ],
        llm_model=SimpleNamespace(model_name="bdd-model", max_tokens=1000),
    )
    watermark = ContextWatermarkResult(
        level="NORMAL",
        current_tokens=2500,
        safe_tokens=2625,
        model_max_context=10000,
        max_tokens=1000,
        summary_safe_limit=8000,
        send_limit=9000,
        low_limit=5840,
        high_limit=7440,
    )
    runtime = SimpleNamespace(
        ai_agent=agent,
        messages=[{"role": "user", "content": "persisted"}],
        session_id="bdd-session",
        del_session_message_by_ids=MagicMock(),
        _get_current_tokens=MagicMock(side_effect=[2500, 500]),
        _classify_context_watermark=MagicMock(return_value=watermark),
    )
    runtime_instructions = ContextRuntimeInstructions(runtime)
    agent_tokens_ctx["hook"] = HookInstruction(
        file_input_completions="",
        instructions=runtime_instructions.instructions,
    )


@when("the operator invokes the registered agent tokens instruction")
def when_operator_invokes_agent_tokens_instruction(agent_tokens_ctx):
    """Invoke the command through the slash-instruction boundary."""
    agent_tokens_ctx["report"] = agent_tokens_ctx["hook"].call_instruction(
        "/agent.tokens"
    )


@then("the agent tokens report shows both current message layers")
def then_agent_tokens_report_shows_both_layers(agent_tokens_ctx):
    """Assert distinct runtime and session counts are visible."""
    report = agent_tokens_ctx["report"]
    assert "Agent2LLM:\n  Messages: 2\n  Estimated tokens: 2,500" in report
    assert "User2Agent:\n  Messages: 1\n  Estimated tokens: 500" in report


@then("the agent tokens report shows configured context capacity")
def then_agent_tokens_report_shows_context_capacity(agent_tokens_ctx):
    """Assert model limits and operational usage are visible."""
    report = agent_tokens_ctx["report"]
    assert "Model: bdd-model" in report
    assert "Model maximum: 10,000" in report
    assert "Completion reserve: 1,000" in report
    assert "Input send limit: 9,000" in report
    assert "Agent2LLM usage: 27.8%" in report
    assert "Watermark: NORMAL" in report
