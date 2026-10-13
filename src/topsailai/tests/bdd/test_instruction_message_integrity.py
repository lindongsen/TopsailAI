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
    assert_system_context,
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
    """Compare persisted messages without documented volatile timestamps."""
    return [
        {key: value for key, value in message.items() if key != "create_time"}
        for message in messages
    ]


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


def _naming_manifest(turn, include_second=False):
    """Build the exact two-turn manifest for automatic naming traffic."""
    markers = [
        "BDD_PLAN_EXPLICIT_CONTEXT_MARKER", "BDD_PLAN_USER_MD_MARKER",
        "BDD_PLAN_TURN_ONE_TOKEN", "safe response",
        "BDD_PLAN_TURN_TWO_TOKEN",
    ]
    entries = [
        {"role": "user", "markers": markers[:2], "all_markers": markers},
        {"role": "user", "markers": [markers[2]], "all_markers": markers},
        {"role": "assistant", "markers": [markers[3]], "all_markers": markers},
    ]
    if include_second:
        entries.append({"role": "user", "markers": [markers[4]], "all_markers": markers})
    return entries


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


@pytest.fixture
def naming_react_scenario(bdd_tmp_path: Path, monkeypatch):
    """Create the React automatic-naming integrity scenario."""
    scenario = SessionNameStartupScenario(monkeypatch, bdd_tmp_path, agent_type="react", integrity=True, multi_turn=True, unit3_case="naming_react")
    try:
        yield scenario
    finally:
        scenario.close()


@pytest.fixture
def naming_plan_scenario(bdd_tmp_path: Path, monkeypatch):
    """Create the plan automatic-naming integrity scenario."""
    scenario = SessionNameStartupScenario(monkeypatch, bdd_tmp_path, agent_type="plan_and_execute", integrity=True, multi_turn=True, unit3_case="naming_plan")
    try:
        yield scenario
    finally:
        scenario.close()


@given("a fresh react Agent integrity naming scenario", target_fixture="unit3_active")
def given_unit3_react_naming(naming_react_scenario):
    """Provide the React naming-mode integrity scenario."""
    return naming_react_scenario


@given("a fresh plan Agent integrity naming scenario", target_fixture="unit3_active")
def given_unit3_plan_naming(naming_plan_scenario):
    """Provide the plan naming-mode integrity scenario."""
    return naming_plan_scenario


@when("the Agent completes the naming scenario turns")
def when_unit3_naming(unit3_active):
    """Run the naming scenario through the real child Agent."""
    unit3_active.run()


@then("naming traffic is isolated and business messages remain ordered")
def then_unit3_naming(unit3_active):
    """Check disjoint naming traffic and ordered business request manifests."""
    state = unit3_active.state()
    classified = []
    for record in state["request_bodies"]:
        text = json.dumps(record["body"], ensure_ascii=False)
        is_naming = "naming assistant" in text.lower()
        is_business = (
            "BDD_PLAN_EXPLICIT_CONTEXT_MARKER" in text
            and ("BDD_PLAN_TURN_ONE_TOKEN" in text or "BDD_PLAN_TURN_TWO_TOKEN" in text)
        )
        assert is_naming != is_business, f"mixed or unknown request: {text}"
        classified.append((record, "naming" if is_naming else "business"))
    naming = [record for record, kind in classified if kind == "naming"]
    business = [record for record, kind in classified if kind == "business"]
    assert len(naming) == 1
    assert len(business) == 2
    assert all(record["parsed"] for record in state["request_bodies"])
    assert state["total_requests"] == 3
    assert state["dropped_request_body_count"] == 0
    naming_text = json.dumps(naming[0]["body"], ensure_ascii=False)
    assert "BDD_PLAN_EXPLICIT_CONTEXT_MARKER" not in naming_text
    assert "BDD_PLAN_USER_MD_MARKER" not in naming_text
    assert "BDD_PLAN_SESSION_NAME" not in naming_text
    ordered_business = sorted(
        business, key=lambda item: "BDD_PLAN_TURN_TWO_TOKEN" in json.dumps(item["body"], ensure_ascii=False)
    )
    naming_markers = [
        "BDD_PLAN_EXPLICIT_CONTEXT_MARKER", "BDD_PLAN_USER_MD_MARKER",
        "BDD_PLAN_TURN_ONE_TOKEN", "BDD_PLAN_TURN_TWO_TOKEN",
        "safe response",
    ]
    assert_message_manifest(
        [m for m in ordered_business[0]["body"]["messages"] if m.get("role") != "system"],
        [
            {"role": "user", "markers": naming_markers[:2], "all_markers": naming_markers},
            {"role": "user", "markers": [naming_markers[2]], "all_markers": naming_markers},
        ],
    )
    assert_message_manifest(
        [m for m in ordered_business[1]["body"]["messages"] if m.get("role") != "system"],
        [
            {"role": "user", "markers": naming_markers[:2], "all_markers": naming_markers},
            {"role": "user", "markers": [naming_markers[2]], "all_markers": naming_markers},
            {"role": "assistant", "markers": [naming_markers[4]], "all_markers": naming_markers},
            {"role": "user", "markers": [naming_markers[3]], "all_markers": naming_markers},
        ],
    )
    report = unit3_active.integrity_report()
    expected = {
        "A_pre1": _naming_manifest(1)[:-1],
        "A_post1": _naming_manifest(1),
        "H_post1": _naming_manifest(1),
        "A_pre2": _naming_manifest(2, include_second=True),
        "A_post2": _naming_manifest(2, include_second=True) + [{"role": "assistant", "markers": ["safe response"], "all_markers": ["BDD_PLAN_EXPLICIT_CONTEXT_MARKER", "BDD_PLAN_USER_MD_MARKER", "BDD_PLAN_TURN_ONE_TOKEN", "safe response", "BDD_PLAN_TURN_TWO_TOKEN"]}],
        "H_post2": _naming_manifest(2, include_second=True) + [{"role": "assistant", "markers": ["safe response"], "all_markers": ["BDD_PLAN_EXPLICIT_CONTEXT_MARKER", "BDD_PLAN_USER_MD_MARKER", "BDD_PLAN_TURN_ONE_TOKEN", "safe response", "BDD_PLAN_TURN_TWO_TOKEN"]}],
    }
    for checkpoint, manifest in expected.items():
        messages = _by_command(_items(report, checkpoint))
        command = "/agent.messages" if checkpoint.startswith("A_") else "/ctx.history"
        if command == "/agent.messages":
            observed = [message for message in parse_agent_messages(messages[command]["stdout"]) if message.get("role") != "system"]
        else:
            observed = [{"role": role, "content": content} for role, content in parse_history_roles_and_content(messages[command]["stdout"])]
        assert_message_manifest(observed, manifest)
    persisted = json.dumps(report["session_messages"], ensure_ascii=False)
    assert "Generate a concise session name" not in persisted
    assert "BDD_PLAN_SESSION_NAME" not in persisted
    assert report["session_name"]
    assert "Generate a concise session name" not in report["session_name"]
    assert report["user_open_count"] == 1
    assert unit3_active.wait_entered.exists()
    assert unit3_active.started.exists()
    assert unit3_active.wait_released.exists()
    assert not unit3_active.process.stderr


@pytest.fixture
def unit3_disabled_scenario(bdd_tmp_path: Path, monkeypatch):
    """Create the disabled USER.md scenario."""
    scenario = SessionNameStartupScenario(monkeypatch, bdd_tmp_path, agent_type="react", integrity=True, multi_turn=False, unit3_case="user_md_disabled")
    try:
        yield scenario
    finally:
        scenario.close()


@given("a fresh disabled USER.md Agent integrity scenario", target_fixture="unit3_disabled")
def given_unit3_disabled(unit3_disabled_scenario):
    """Provide the disabled USER.md scenario."""
    return unit3_disabled_scenario


@when("the Agent completes the disabled USER.md turn")
def when_unit3_disabled(unit3_disabled):
    """Run the disabled USER.md turn."""
    unit3_disabled.run()


@then("explicit startup context remains and USER.md is absent")
def then_unit3_disabled(unit3_disabled):
    """Assert explicit context survives while USER.md is absent."""
    report = unit3_disabled.integrity_report()
    assert report["user_open_count"] == 0
    assert report["startup_context_consumed"] is True
    assert report["context_user_message_after"] == ""
    assert report["handler_counts"] == {"/agent.messages": 1, "/ctx.history": 1}
    state = unit3_disabled.state()
    assert state["total_requests"] == 1
    assert len(state["request_bodies"]) == 1
    wire = state["request_bodies"][0]["body"]["messages"]
    assert_message_manifest([message for message in wire if message.get("role") != "system"], [
        {"role": "user", "markers": ["BDD_PLAN_EXPLICIT_CONTEXT_MARKER"], "all_markers": ["BDD_PLAN_EXPLICIT_CONTEXT_MARKER", "BDD_PLAN_USER_MD_MARKER", "BDD_PLAN_TURN_ONE_TOKEN"]},
        {"role": "user", "markers": ["BDD_PLAN_TURN_ONE_TOKEN"], "all_markers": ["BDD_PLAN_EXPLICIT_CONTEXT_MARKER", "BDD_PLAN_USER_MD_MARKER", "BDD_PLAN_TURN_ONE_TOKEN"]},
    ])
    disabled_manifest = [
        {"role": "user", "markers": ["BDD_PLAN_EXPLICIT_CONTEXT_MARKER"], "all_markers": ["BDD_PLAN_EXPLICIT_CONTEXT_MARKER", "BDD_PLAN_USER_MD_MARKER", "BDD_PLAN_TURN_ONE_TOKEN", "BDD_PLAN_ANSWER_ONE_TOKEN"]},
        {"role": "user", "markers": ["BDD_PLAN_TURN_ONE_TOKEN"], "all_markers": ["BDD_PLAN_EXPLICIT_CONTEXT_MARKER", "BDD_PLAN_USER_MD_MARKER", "BDD_PLAN_TURN_ONE_TOKEN", "BDD_PLAN_ANSWER_ONE_TOKEN"]},
    ]
    for checkpoint in ("A_pre1", "A_post1"):
        messages = _by_command(_items(report, checkpoint))
        runtime = [m for m in parse_agent_messages(messages["/agent.messages"]["stdout"]) if m.get("role") != "system"]
        assert_message_manifest(runtime, disabled_manifest if checkpoint == "A_pre1" else disabled_manifest + [{"role": "assistant", "markers": ["BDD_PLAN_ANSWER_ONE_TOKEN"], "all_markers": disabled_manifest[0]["all_markers"]}])
        for item in messages.values():
            assert "BDD_PLAN_USER_MD_MARKER" not in item["stdout"]
    history = parse_history_roles_and_content(_by_command(_items(report, "A_post1"))["/ctx.history"]["stdout"])
    assert_message_manifest([{"role": role, "content": content} for role, content in history], disabled_manifest + [{"role": "assistant", "markers": ["BDD_PLAN_ANSWER_ONE_TOKEN"], "all_markers": disabled_manifest[0]["all_markers"]}])
    assert "BDD_PLAN_EXPLICIT_CONTEXT_MARKER" in unit3_disabled.request_texts()[0]
    assert "BDD_PLAN_USER_MD_MARKER" not in unit3_disabled.request_texts()[0]


@pytest.fixture
def unit3_tool_scenario(bdd_tmp_path: Path, monkeypatch):
    """Create the tool-prompt replay scenario."""
    scenario = SessionNameStartupScenario(monkeypatch, bdd_tmp_path, agent_type="react", integrity=True, multi_turn=True, unit3_case="tool_prompt")
    try:
        yield scenario
    finally:
        scenario.close()


@given("a fresh tool-prompt Agent integrity scenario", target_fixture="unit3_tool")
def given_unit3_tool(unit3_tool_scenario):
    """Provide the tool-prompt replay scenario."""
    return unit3_tool_scenario


@when("the Agent completes the tool-prompt turns")
def when_unit3_tool(unit3_tool):
    """Run two turns with the real tool prompt path."""
    unit3_tool.run()


@then("the tool marker remains system-only and is not persisted")
def then_unit3_tool(unit3_tool):
    """Assert tool prompt cardinality and role at runtime and wire boundaries."""
    report = unit3_tool.integrity_report()
    for snapshot in report["snapshots"]:
        for item in snapshot["items"]:
            if item["command"] != "/agent.messages":
                continue
            messages = parse_agent_messages(item["stdout"])
            assert sum(str(message.get("content", "")).count("TOOL_SYSTEM_TOKEN") for message in messages) == 1
            assert all("TOOL_SYSTEM_TOKEN" not in str(message.get("content", "")) for message in messages if message.get("role") != "system")
    for record in unit3_tool.state()["request_bodies"]:
        messages = record["body"]["messages"]
        assert sum(str(message.get("content", "")).count("TOOL_SYSTEM_TOKEN") for message in messages) == 1
        assert all("TOOL_SYSTEM_TOKEN" not in str(message.get("content", "")) for message in messages if message.get("role") != "system")
    assert all("TOOL_SYSTEM_TOKEN" not in str(message.get("content", "")) for message in report["session_messages"])
    tool_state = unit3_tool.state()
    assert tool_state["total_requests"] == 2
    assert tool_state["dropped_request_body_count"] == 0
    assert len(tool_state["request_bodies"]) == 2
    assert all(record["parsed"] for record in tool_state["request_bodies"])
    for checkpoint in ("A_pre1", "A_post1", "A_pre2", "A_post2"):
        assert len([item for item in report["snapshots"] if item["checkpoint"] == checkpoint]) == 1
    _assert_two_turn_report(unit3_tool)


@pytest.fixture
def unit3_history_scenario(bdd_tmp_path: Path, monkeypatch):
    """Create the history-slice scenario."""
    scenario = SessionNameStartupScenario(monkeypatch, bdd_tmp_path, agent_type="react", integrity=True, multi_turn=True, unit3_case="history_slice")
    try:
        yield scenario
    finally:
        scenario.close()


@given("a fresh history-slice Agent integrity scenario", target_fixture="unit3_history")
def given_unit3_history(unit3_history_scenario):
    """Provide the history slice scenario."""
    return unit3_history_scenario


@when("the Agent completes the history-slice turns")
def when_unit3_history(unit3_history):
    """Run the turns and real history instructions."""
    unit3_history.run()


@then("the history slice matches positions one through three without mutation")
def then_unit3_history(unit3_history):
    """Assert the slice is exact and inspection leaves state unchanged."""
    report = unit3_history.integrity_report()
    before = _by_command(_items(report, "H_before_slice"))["/ctx.history"]
    after = _by_command(_items(report, "H_after_slice"))["/ctx.history"]
    slice_item = _by_command(_items(report, "A_slice"))["/ctx.history 1:3"]
    full = parse_history_roles_and_content(before["stdout"])
    sliced = parse_history_roles_and_content(slice_item["stdout"])
    assert [(role, content.rstrip("\n=" ).rstrip()) for role, content in sliced] == [
        (role, content.rstrip("\n=" ).rstrip()) for role, content in full[1:3]
    ]
    assert after["stdout"] == before["stdout"]
    assert _semantic_messages(report["session_before_slice"]) == _semantic_messages(report["session_after_slice"])
    assert report["request_count_before_slice"] == report["request_count_after_slice"]
    assert report["request_count_before_slice"] == 2
    assert [index for index, _ in enumerate(sliced, 1)] == [1, 2]


@pytest.fixture
def native_tool_scenario(bdd_tmp_path: Path, monkeypatch):
    """Create the real native tool-call integrity scenario."""
    scenario = SessionNameStartupScenario(monkeypatch, bdd_tmp_path, agent_type="react", integrity=False, native_tool=True)
    try:
        yield scenario
    finally:
        scenario.close()


@given("a fresh native-tool Agent integrity scenario", target_fixture="native_tool")
def given_native_tool(native_tool_scenario):
    """Provide the native tool scenario."""
    return native_tool_scenario


@when("the Agent performs one real native tool turn")
def when_native_tool(native_tool):
    """Run one real native tool turn through the child process."""
    native_tool.run()


@then("native declaration result and final answer remain ordered and final-only history is preserved")
def then_native_tool(native_tool):
    """Assert native wire/runtime pairing and final-only persisted history."""
    from tests.bdd.instruction_message_integrity_assertions import assert_native_tool_group, assert_native_wire_group
    report = native_tool.integrity_report()
    state = native_tool.state()
    assert state["total_requests"] == 2
    assert state["dropped_request_body_count"] == 0
    assert len(state["request_bodies"]) == 2
    assert all(record["parsed"] for record in state["request_bodies"])
    assert report["request_count"] == report["after_request_count"] == 2
    assert report["before_request_count"] == 2
    assert report["tool_state"] == {"count": 1, "arguments": [{"value": "BDD_NATIVE_ARGUMENT_TOKEN"}]}
    assert report["handler_counts"] == {"/agent.messages": 1, "/ctx.history": 1}
    assert report["user_open_count"] == 1
    assert report["before_runtime"] == report["after_runtime"]
    assert _semantic_messages(report["before_session"]) == _semantic_messages(report["after_session"])

    pre = _assert_instruction_group(_items(report, "A_pre"), ("/agent.messages",))["/agent.messages"]
    post = _assert_instruction_group(_items(report, "A_post"), ("/agent.messages",))["/agent.messages"]
    history = _assert_instruction_group(_items(report, "H_post"), ("/ctx.history",))["/ctx.history"]
    purity_before = _assert_instruction_group(_items(report, "purity_before"))
    purity_after = _assert_instruction_group(_items(report, "purity_after"))
    assert all(purity_before[key]["stdout"] == purity_after[key]["stdout"] for key in purity_before)

    all_markers = ["BDD_PLAN_EXPLICIT_CONTEXT_MARKER", "BDD_PLAN_USER_MD_MARKER", "BDD_NATIVE_TASK_TOKEN", "BDD_NATIVE_RESULT_TOKEN", "BDD_NATIVE_ANSWER_TOKEN"]
    startup = {"role": "user", "markers": all_markers[:2], "all_markers": all_markers}
    task = {"role": "user", "markers": [all_markers[2]], "all_markers": all_markers}
    raw_pre = parse_agent_messages(pre["stdout"])
    raw_post = parse_agent_messages(post["stdout"])
    assert_system_context(raw_pre, all_markers, expected_markers=["BDD_SYSTEM_CONTEXT_MARKER"], expected_count=2)
    assert_system_context(raw_post, all_markers, expected_markers=["BDD_SYSTEM_CONTEXT_MARKER"], expected_count=2)
    runtime_pre = [m for m in raw_pre if m.get("role") != "system"]
    runtime_post = [m for m in raw_post if m.get("role") != "system"]
    assert_message_manifest(runtime_pre, [startup, task])
    assert_message_manifest(runtime_post[:2], [startup, task])
    assert_native_tool_group(runtime_post[1:], task_marker="BDD_NATIVE_TASK_TOKEN", tool_name="safe_native_tool", call_id="call_bdd_integrity_native", argument={"value": "BDD_NATIVE_ARGUMENT_TOKEN"}, result_marker="BDD_NATIVE_RESULT_TOKEN", final_marker="BDD_NATIVE_ANSWER_TOKEN", result_content='{\n  "raw_text": "BDD_NATIVE_RESULT_TOKEN",\n  "step_name": "observation"\n}')

    history_messages = [{"role": role, "content": content} for role, content in parse_history_roles_and_content(history["stdout"])]
    assert_message_manifest(history_messages, [startup, task, {"role": "assistant", "markers": ["BDD_NATIVE_ANSWER_TOKEN"], "all_markers": all_markers}])
    raw_persisted = report["session_messages"]
    for message in raw_persisted:
        assert "tool_calls" not in message and "tool_call_id" not in message
    persisted = _semantic_messages(raw_persisted)
    assert_message_manifest(persisted, [startup, task, {"role": "assistant", "markers": ["BDD_NATIVE_ANSWER_TOKEN"], "all_markers": all_markers}])
    persisted_text = json.dumps(raw_persisted, ensure_ascii=False)
    for marker in ("call_bdd_integrity_native", "BDD_NATIVE_ARGUMENT_TOKEN", "BDD_NATIVE_RESULT_TOKEN", "/agent.messages", "/ctx.history"):
        assert marker not in persisted_text

    bodies = [record["body"] for record in state["request_bodies"]]
    assert_system_context(bodies[0]["messages"], all_markers, expected_markers=["BDD_SYSTEM_CONTEXT_MARKER"], expected_count=1)
    assert_system_context(bodies[1]["messages"], all_markers, expected_markers=["BDD_SYSTEM_CONTEXT_MARKER"], expected_count=1)
    w1 = [m for m in bodies[0]["messages"] if m.get("role") != "system"]
    w2 = [m for m in bodies[1]["messages"] if m.get("role") != "system"]
    assert_message_manifest(w1, [startup, task])
    assert bodies[0]["tools"][0]["function"]["name"] == "safe_native_tool"
    assert bodies[0]["tools"][0]["function"]["parameters"]["type"] == "object"
    assert bodies[0]["tools"][0]["function"]["parameters"]["properties"]["value"]["type"] == "string"
    assert bodies[0]["tools"][0]["function"]["parameters"]["required"] == ["value"]
    assert_message_manifest(w2[:2], [startup, task])
    assert_native_wire_group(w2[1:], task_marker="BDD_NATIVE_TASK_TOKEN", tool_name="safe_native_tool", call_id="call_bdd_integrity_native", argument={"value": "BDD_NATIVE_ARGUMENT_TOKEN"}, result_marker="BDD_NATIVE_RESULT_TOKEN", result_content="topsailai.observation\nBDD_NATIVE_RESULT_TOKEN")
    assert "BDD_NATIVE_ANSWER_TOKEN" not in json.dumps(bodies[1], ensure_ascii=False)
    assert pre["command"] == "/agent.messages" and post["command"] == "/agent.messages" and history["command"] == "/ctx.history"
