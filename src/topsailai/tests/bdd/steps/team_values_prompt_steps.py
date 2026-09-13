"""Unique BDD steps for Team-level shared values prompts.

Author: DawsonLin
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.team_values_prompt_harness import (
    AI_TEAM_HEADING,
    BASE_MARKER,
    MEMBER_MARKER,
    OUTPUT_REQUIREMENT,
    TEAM_MARKER,
    TeamValuesPromptScenario,
)


@pytest.fixture
def team_values_prompt_ctx():
    """Hold the scenario created by its Given step and close it afterward."""
    context = {"scenario": None}
    yield context
    scenario = context["scenario"]
    if scenario is not None:
        scenario.close()


def _create_scenario(
    context: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    shared_state: str,
) -> TeamValuesPromptScenario:
    """Create exactly one private Team prompt scenario."""
    scenario = TeamValuesPromptScenario(monkeypatch, tmp_path, shared_state)
    context["scenario"] = scenario
    assert scenario.server_thread.is_alive()
    return scenario


@given("a direct Member team with non-empty shared values and a private mock LLM server")
def given_direct_member_team(
    team_values_prompt_ctx,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Provide a direct Member with shared and private prompt layers."""
    return _create_scenario(
        team_values_prompt_ctx, monkeypatch, tmp_path, "present"
    )


@given("a plugin-precomposed Member team and a private mock LLM server")
def given_plugin_precomposed_team(
    team_values_prompt_ctx,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Provide a Team whose Manager output will simulate plugin precomposition."""
    return _create_scenario(
        team_values_prompt_ctx, monkeypatch, tmp_path, "present"
    )


@given(
    parsers.parse(
        "a direct Member team whose shared values are {shared_values_state} "
        "and a private mock LLM server"
    )
)
def given_compatible_shared_values_team(
    team_values_prompt_ctx,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    shared_values_state: str,
):
    """Provide a Team with an absent or empty optional shared values file."""
    assert shared_values_state in {"missing", "empty"}
    return _create_scenario(
        team_values_prompt_ctx,
        monkeypatch,
        tmp_path,
        shared_values_state,
    )


@given("a direct Member team with unreadable shared values and a private mock LLM server")
def given_unreadable_shared_values_team(
    team_values_prompt_ctx,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Provide an existing shared-values path that cannot be read as a file."""
    return _create_scenario(
        team_values_prompt_ctx, monkeypatch, tmp_path, "unreadable"
    )


@when("the direct Member Agent sends one real LLM request")
def when_direct_member_agent_sends(team_values_prompt_ctx):
    """Exercise direct Member composition through the production Agent client."""
    team_values_prompt_ctx["scenario"].send_direct_agent()


@when("the plugin-precomposed Member sends one real LLM request")
def when_plugin_precomposed_member_sends(team_values_prompt_ctx):
    """Exercise simulated plugin precomposition through a real Agent request."""
    team_values_prompt_ctx["scenario"].send_plugin_precomposed_agent()


@when("the Member sends one real LLM request with precomposed explicitly false")
def when_explicit_false_member_sends(team_values_prompt_ctx):
    """Exercise explicit direct composition despite matching plugin provenance."""
    team_values_prompt_ctx["scenario"].send_explicit_false_agent()


@when("independent prompt segments with the same AI Team heading are sent")
def when_same_heading_segments_are_sent(team_values_prompt_ctx):
    """Exercise distinct user prompt segments without content deduplication."""
    team_values_prompt_ctx["scenario"].send_same_heading_segments_agent()


@when("Team Agent and Team Chat each send one real LLM request")
def when_team_agent_and_chat_send(team_values_prompt_ctx):
    """Exercise canonical Member context through Agent and Chat LLM clients."""
    team_values_prompt_ctx["scenario"].send_agent_and_chat()


@when("the direct Member prompt is resolved")
def when_unreadable_member_prompt_resolves(team_values_prompt_ctx):
    """Resolve the prompt and retain its expected pre-I/O failure."""
    team_values_prompt_ctx["scenario"].resolve_unreadable_prompt()


@then(parsers.parse("the Team values mock server received exactly {count:d} completion requests"))
def then_server_received_request_count(team_values_prompt_ctx, count: int):
    """Assert the exact provider request count and captured-body cardinality."""
    state = team_values_prompt_ctx["scenario"].state()
    assert state["total_requests"] == count, state
    assert len(state["request_bodies"]) == count, state
    assert all(record["parsed"] for record in state["request_bodies"]), state


@then("the captured system prompt contains the shared Team marker exactly once")
def then_system_prompt_contains_shared_marker_once(team_values_prompt_ctx):
    """Assert the provider received one and only one shared Team segment."""
    prompts = team_values_prompt_ctx["scenario"].system_prompts()
    assert len(prompts) == 1
    assert prompts[0].count(TEAM_MARKER) == 1


@then("the captured system prompt contains the AI Team heading exactly once")
def then_system_prompt_contains_ai_team_heading_once(team_values_prompt_ctx):
    """Assert plugin precomposition does not duplicate the built-in heading."""
    prompts = team_values_prompt_ctx["scenario"].system_prompts()
    assert len(prompts) == 1
    assert prompts[0].count(AI_TEAM_HEADING) == 1


@then(parsers.parse("the captured system prompt contains the AI Team heading exactly {count:d} times"))
def then_system_prompt_contains_ai_team_heading_count(
    team_values_prompt_ctx,
    count: int,
):
    """Assert the exact count of a same-named user-controlled heading."""
    prompts = team_values_prompt_ctx["scenario"].system_prompts()
    assert len(prompts) == 1
    headings = [line for line in prompts[0].splitlines() if line.startswith("# ")]
    assert headings.count(AI_TEAM_HEADING) == count, headings


@then("every captured level-one heading is unique")
def then_every_level_one_heading_is_unique(team_values_prompt_ctx):
    """Assert framework composition emits no duplicate Markdown H1 headings."""
    prompts = team_values_prompt_ctx["scenario"].system_prompts()
    assert prompts
    for prompt in prompts:
        headings = [line for line in prompt.splitlines() if line.startswith("# ")]
        assert headings
        assert len(headings) == len(set(headings)), headings


@then("the captured system prompt contains both same-heading policy markers")
def then_same_heading_policy_markers_are_preserved(team_values_prompt_ctx):
    """Assert no independent user-controlled prompt segment was deleted."""
    prompts = team_values_prompt_ctx["scenario"].system_prompts()
    assert len(prompts) == 1
    assert "BDD_BASE_SAME_HEADING_POLICY" in prompts[0]
    assert "BDD_SHARED_SAME_HEADING_POLICY" in prompts[0]


@then("both captured system prompts contain the same shared Team marker once")
def then_both_system_prompts_share_marker_once(team_values_prompt_ctx):
    """Assert Agent and Chat receive equivalent unique shared context."""
    prompts = team_values_prompt_ctx["scenario"].system_prompts()
    assert len(prompts) == 2
    assert all(prompt.count(TEAM_MARKER) == 1 for prompt in prompts)


@then("the Team Chat output requirement follows its canonical Member system prompt")
def then_chat_output_requirement_is_final(team_values_prompt_ctx):
    """Assert Chat appends its output requirement after equal Member context."""
    agent_prompt, chat_prompt = team_values_prompt_ctx["scenario"].system_prompts()
    assert OUTPUT_REQUIREMENT not in agent_prompt
    assert OUTPUT_REQUIREMENT in chat_prompt
    canonical_start = chat_prompt.index(BASE_MARKER)
    canonical_member_end = chat_prompt.index(MEMBER_MARKER) + len(MEMBER_MARKER)
    output_requirement_start = chat_prompt.index("# Output Required")
    assert output_requirement_start > canonical_member_end
    chat_canonical = chat_prompt[canonical_start:canonical_member_end]
    agent_start = agent_prompt.index(BASE_MARKER)
    agent_end = agent_prompt.index(MEMBER_MARKER) + len(MEMBER_MARKER)
    assert chat_canonical == agent_prompt[agent_start:agent_end]


@then("the captured system prompt omits the shared Team marker")
def then_system_prompt_omits_shared_marker(team_values_prompt_ctx):
    """Assert compatibility requests contain no synthetic shared segment."""
    prompts = team_values_prompt_ctx["scenario"].system_prompts()
    assert len(prompts) == 1
    assert TEAM_MARKER not in prompts[0]


@then("shared Team prompt resolution fails closed")
def then_shared_prompt_resolution_fails_closed(team_values_prompt_ctx):
    """Assert an existing unreadable values path aborts prompt resolution."""
    error = team_values_prompt_ctx["scenario"].error
    assert isinstance(error, (IsADirectoryError, PermissionError)), error
