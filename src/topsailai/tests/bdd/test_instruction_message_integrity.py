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
    """Return instruction observations for one named checkpoint."""
    return next(item["items"] for item in report["snapshots"] if item["checkpoint"] == checkpoint)


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

