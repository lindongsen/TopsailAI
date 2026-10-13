"""BDD coverage for instruction views and ordered transport messages."""

from pathlib import Path
import json

import pytest
from pytest_bdd import given, scenarios, then, when

from tests.bdd.instruction_message_integrity_assertions import (
    assert_message_manifest,
    ordered_markers,
    parse_agent_messages,
    parse_history_roles_and_content,
)
from tests.bdd.session_name_startup_context_harness import SessionNameStartupScenario

scenarios("features/instruction_message_integrity.feature")


@pytest.fixture
def integrity_scenario(bdd_tmp_path: Path, monkeypatch):
    """Create and close one fresh real Agent integrity scenario."""
    scenario = SessionNameStartupScenario(monkeypatch, bdd_tmp_path, agent_type="react", integrity=True)
    try:
        yield scenario
    finally:
        scenario.close()


@given("a fresh Agent integrity scenario with naming disabled")
def given_integrity_scenario(integrity_scenario):
    """Use the fresh real Agent and loopback mock provider."""
    return integrity_scenario


@when("the Agent completes one real turn and the operator inspects messages")
def when_integrity_turn_completes(integrity_scenario):
    """Run the child and retain its bounded observation report."""
    integrity_scenario.run()


def _items(report, checkpoint):
    """Return exactly one instruction observation for a named checkpoint."""
    matches = [item["items"] for item in report["snapshots"] if item["checkpoint"] == checkpoint]
    assert len(matches) == 1, f"checkpoint {checkpoint!r} count {len(matches)} != 1"
    return matches[0]

def _by_command(items):
    """Index one checkpoint's observations by slash command."""
    return {item["command"]: item for item in items}


def _semantic_messages(messages):
    """Compare persisted messages without volatile storage metadata."""
    return [{key: message[key] for key in ("role", "content") if key in message} for message in messages]


def _assert_instruction_group(items, commands=("/agent.messages", "/ctx.history")):
    """Require successful real dispatch and cache identity for expected instructions."""
    observations = _by_command(items)
    assert set(observations) == set(commands)
    assert all(item["consumed"] and item["cache_identity"] for item in observations.values())
    return observations

@then("the instruction reports and mock request preserve the expected order")
def then_integrity_is_preserved(integrity_scenario):
    """Assert independent instruction, history, purity, and HTTP observations."""
    scenario = integrity_scenario
    report = scenario.integrity_report()
    pre = _assert_instruction_group(_items(report, "A_pre"), ("/agent.messages",))
    post = _assert_instruction_group(_items(report, "A_post"))
    history_view = _assert_instruction_group(_items(report, "H_post"), ("/ctx.history",))
    purity_before = _assert_instruction_group(_items(report, "purity_before"))
    purity_after = _assert_instruction_group(_items(report, "purity_after"))
    assert report["handler_counts"] == {"/agent.messages": 1, "/ctx.history": 1}

    all_markers = [
        "BDD_PLAN_EXPLICIT_CONTEXT_MARKER",
        "BDD_PLAN_USER_MD_MARKER",
        "BDD_PLAN_TURN_ONE_TOKEN",
        "BDD_PLAN_ANSWER_ONE_TOKEN",
    ]
    startup = {"role": "user", "markers": all_markers[:2], "all_markers": all_markers}
    task = {"role": "user", "markers": [all_markers[2]], "all_markers": all_markers}
    answer = {"role": "assistant", "markers": [all_markers[3]], "all_markers": all_markers}
    runtime_pre = [message for message in parse_agent_messages(pre["/agent.messages"]["stdout"]) if message.get("role") != "system"]
    runtime_post = [message for message in parse_agent_messages(post["/agent.messages"]["stdout"]) if message.get("role") != "system"]
    assert_message_manifest(runtime_pre, [startup, task])
    assert_message_manifest(runtime_post, [startup, task, answer])
    assert_message_manifest(runtime_post, [startup, task, answer])

    history = parse_history_roles_and_content(history_view["/ctx.history"]["stdout"])
    history_messages = [{"role": role, "content": content} for role, content in history]
    assert_message_manifest(history_messages, [startup, task, answer])

    wire = scenario.state()["request_bodies"][0]["body"]["messages"]
    assert_message_manifest(wire, [
        {"role": "system", "markers": [], "all_markers": all_markers},
        startup,
        task,
    ])
    assert all_markers[3] not in scenario.request_texts()[0]

    assert report["pre_inspection_runtime"] == report["before_runtime"]
    assert _semantic_messages(report["pre_inspection_session"]) == _semantic_messages(report["before_session"])
    assert report["before_runtime"] == report["after_runtime"]
    assert _semantic_messages(report["before_session"]) == _semantic_messages(report["after_session"])
    assert _semantic_messages(report["session_messages"]) == _semantic_messages(report["after_session"])
    assert post["/agent.messages"]["stdout"] == purity_before["/agent.messages"]["stdout"]
    assert post["/agent.messages"]["stdout"] == purity_after["/agent.messages"]["stdout"]
    assert history_view["/ctx.history"]["stdout"] == purity_before["/ctx.history"]["stdout"]
    assert history_view["/ctx.history"]["stdout"] == purity_after["/ctx.history"]["stdout"]
    for item in (*purity_before.values(), *purity_after.values()):
        assert item["command"] not in json.dumps(report["session_messages"], ensure_ascii=False)
        assert item["command"] not in scenario.request_texts()[0]

    state = scenario.state()
    assert state["total_requests"] == 1
    assert state["dropped_request_body_count"] == 0
    assert len(state["request_bodies"]) == 1
    assert all(record["parsed"] for record in state["request_bodies"])




@pytest.fixture
def reset_two_turn_scenario(bdd_tmp_path: Path, monkeypatch):
    """Create a real two-turn reset-mode scenario."""
    scenario = SessionNameStartupScenario(monkeypatch, bdd_tmp_path, agent_type="react", integrity=True, multi_turn=True)
    monkeypatch.setenv("TOPSAILAI_AGENT2LLM_KEEP_MESSAGES_ACROSS_TURNS", "0")
    scenario.expected_keep_messages_across_turns = False
    try:
        yield scenario
    finally:
        scenario.close()


@pytest.fixture
def persist_two_turn_scenario(bdd_tmp_path: Path, monkeypatch):
    """Create a real two-turn persistence-mode scenario."""
    scenario = SessionNameStartupScenario(monkeypatch, bdd_tmp_path, agent_type="react", integrity=True, multi_turn=True)
    monkeypatch.setenv("TOPSAILAI_AGENT2LLM_KEEP_MESSAGES_ACROSS_TURNS", "1")
    scenario.expected_keep_messages_across_turns = True
    try:
        yield scenario
    finally:
        scenario.close()


@given("a fresh two-turn Agent integrity scenario in reset mode", target_fixture="two_turn_scenario")
def given_two_turn_reset(reset_two_turn_scenario):
    """Provide the reset-mode two-turn scenario."""
    return reset_two_turn_scenario


@given("a fresh two-turn Agent integrity scenario in persist mode", target_fixture="two_turn_scenario")
def given_two_turn_persist(persist_two_turn_scenario):
    """Provide the persistence-mode two-turn scenario."""
    return persist_two_turn_scenario


@when("the Agent completes two real turns on the configured session")
def when_two_turns_complete(two_turn_scenario):
    """Run both turns in the selected child scenario."""
    two_turn_scenario.run()


@then("both turn reports preserve the expected order without duplicate injection")
def then_two_turns_preserve_order(two_turn_scenario):
    """Validate the two completed instruction projections."""
    report = two_turn_scenario.integrity_report()
    assert report["keep_messages_across_turns"] is two_turn_scenario.expected_keep_messages_across_turns
    assert len(report["agent_identities"]) == 1
    _assert_two_turn_report(two_turn_scenario)


@pytest.fixture
def rebuilt_bdd_scenario(bdd_tmp_path: Path, monkeypatch):
    """Create the reconstructed-agent BDD scenario."""
    scenario = SessionNameStartupScenario(
        monkeypatch, bdd_tmp_path, agent_type="react", integrity=True,
        multi_turn=True, rebuild=True,
    )
    monkeypatch.setenv("TOPSAILAI_AGENT2LLM_KEEP_MESSAGES_ACROSS_TURNS", "0")
    try:
        yield scenario
    finally:
        scenario.close()


@given("a fresh rebuilt-Agent integrity scenario")
def given_rebuilt_agent(rebuilt_bdd_scenario):
    """Provide the rebuilt-agent scenario."""
    return rebuilt_bdd_scenario


@when("the Agent completes two real turns using rebuilt instances")
def when_rebuilt_turns_complete(rebuilt_bdd_scenario):
    """Run two turns with a newly constructed AgentChat for turn two."""
    rebuilt_bdd_scenario.run()


@then("the rebuilt Agent preserves history and cache identity")
def then_rebuilt_agent_preserves_history(rebuilt_bdd_scenario):
    """Validate rebuilt identity, persisted history, and transport count."""
    report = rebuilt_bdd_scenario.integrity_report()
    assert report["keep_messages_across_turns"] is False
    assert len(report["agent_identities"]) == 2
    assert report["agent_identities"][0] != report["agent_identities"][1]
    assert report["user_open_count"] == 1
    assert len([item for item in report["snapshots"] if item["checkpoint"] == "A_pre1"]) == 1
    assert len([item for item in report["snapshots"] if item["checkpoint"] == "A_pre2"]) == 1
    _assert_two_turn_report(rebuilt_bdd_scenario)

def _assert_two_turn_report(scenario):
    """Assert independent reports and exact captured request cardinality."""
    report = scenario.integrity_report()
    state = scenario.state()
    assert report["user_open_count"] == 1
    pre_expected = {
        1: _multi_turn_manifest(1, include_second=False)[:-1],
        2: _multi_turn_manifest(2, include_second=True)[:-1],
    }
    for turn in (1, 2):
        pre = _by_command(_items(report, f"A_pre{turn}"))["/agent.messages"]
        pre_runtime = [message for message in parse_agent_messages(pre["stdout"]) if message.get("role") != "system"]
        assert_message_manifest(pre_runtime, pre_expected[turn])
        post = _by_command(_items(report, f"A_post{turn}"))
        history = _by_command(_items(report, f"H_post{turn}"))["/ctx.history"]
        runtime = [message for message in parse_agent_messages(post["/agent.messages"]["stdout"]) if message.get("role") != "system"]
        expected = _multi_turn_manifest(turn, include_second=turn == 2)
        assert_message_manifest(runtime, expected)
        history_messages = [{"role": role, "content": content} for role, content in parse_history_roles_and_content(history["stdout"])]
        assert_message_manifest(history_messages, expected)
    assert len(state["request_bodies"]) == 2
    assert state["dropped_request_body_count"] == 0
    assert all(record["parsed"] for record in state["request_bodies"])
    wires = [record["body"]["messages"] for record in state["request_bodies"]]
    wire_one = [message for message in wires[0] if message.get("role") != "system"]
    wire_two = [message for message in wires[1] if message.get("role") != "system"]
    assert_message_manifest(wire_one, _multi_turn_manifest(1, include_second=False)[:-1])
    assert_message_manifest(wire_two, _multi_turn_manifest(2, include_second=True)[:-1])
    assert "BDD_PLAN_ANSWER_ONE_TOKEN" not in json.dumps(wires[0], ensure_ascii=False)
    assert "BDD_PLAN_ANSWER_TWO_TOKEN" not in json.dumps(wires[1], ensure_ascii=False)


def _multi_turn_manifest(turn, include_second=False):
    """Build the independent expected semantic conversation for a turn."""
    markers = [
        "BDD_PLAN_EXPLICIT_CONTEXT_MARKER", "BDD_PLAN_USER_MD_MARKER",
        "BDD_PLAN_TURN_ONE_TOKEN", "BDD_PLAN_ANSWER_ONE_TOKEN",
        "BDD_PLAN_TURN_TWO_TOKEN", "BDD_PLAN_ANSWER_TWO_TOKEN",
    ]
    entries = [
        {"role": "user", "markers": markers[:2], "all_markers": markers},
        {"role": "user", "markers": [markers[2]], "all_markers": markers},
        {"role": "assistant", "markers": [markers[3]], "all_markers": markers},
    ]
    if include_second:
        entries.extend([
            {"role": "user", "markers": [markers[4]], "all_markers": markers},
            {"role": "assistant", "markers": [markers[5]], "all_markers": markers},
        ])
    return entries
