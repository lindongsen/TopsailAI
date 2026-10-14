"""BDD acceptance tests for metadata-aware history replay."""
from __future__ import annotations

import json
import os
from pathlib import Path
import pytest
from pytest_bdd import given, scenarios, then, when
from tests.bdd.history_replay_metadata_harness import MetadataScenario
from tests.bdd.instruction_message_integrity_assertions import (
    parse_agent_messages, parse_history_roles_and_content,
)

scenarios("features/history_replay_metadata.feature")

@pytest.fixture
def metadata_scenario(bdd_tmp_path: Path, monkeypatch):
    """Create and close one ordinary real scenario."""
    scenario = MetadataScenario(bdd_tmp_path, monkeypatch)
    try: yield scenario
    finally: scenario.close()

@pytest.fixture
def native_metadata_scenario(bdd_tmp_path: Path, monkeypatch):
    """Create and close one native real scenario."""
    scenario = MetadataScenario(bdd_tmp_path, monkeypatch, native=True)
    try: yield scenario
    finally: scenario.close()

@given("a real two-turn persist metadata scenario")
def given_metadata(metadata_scenario): return metadata_scenario

@given("a real two-turn native persist metadata scenario")
def given_native_metadata(native_metadata_scenario): return native_metadata_scenario

@when("the Agent completes both turns")
def when_metadata_turns_complete(request):
    """Run the same AgentChat instance for both turns."""
    name = "metadata_scenario" if "metadata_scenario" in request.fixturenames else "native_metadata_scenario"
    scenario = request.getfixturevalue(name)
    request.node.metadata_report = scenario.run(pre_fix=os.environ.get("BDD_PRE_FIX") == "1")
    request.node.metadata_scenario = scenario


def _item(report, checkpoint, command, turn=None):
    items = [item for snapshot in report["snapshots"] if snapshot["checkpoint"] == checkpoint
             and (turn is None or snapshot.get("turn") == turn)
             for item in snapshot["items"] if item["command"] == command]
    if len(items) != 1:
        raise AssertionError(f"expected one {checkpoint} turn={turn} {command}, got {len(items)}")
    return items[0]


def _wire_messages(state):
    assert state["dropped_request_body_count"] == 0
    assert all(record["parsed"] for record in state["request_bodies"])
    return [record["body"]["messages"] for record in state["request_bodies"]]


def _message_text(message):
    content = message.get("content", "")
    if isinstance(content, str):
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError:
            return content
        return json.dumps(decoded, ensure_ascii=False)
    return json.dumps(content, ensure_ascii=False)


def _assert_clean_manifest(messages, required, forbidden=(), counts=None):
    """Require every manifest marker once unless explicitly overridden."""
    text = "\n".join(_message_text(message) for message in messages if message.get("role") != "system")
    expected_counts = {marker: 1 for marker in required}
    if counts:
        expected_counts.update(counts)
    for marker, expected_count in expected_counts.items():
        assert text.count(marker) == expected_count, (marker, expected_count, text)
    for marker in forbidden:
        assert marker not in text, (marker, text)


def test_manifest_override_does_not_hide_required_duplicate():
    """An explicit answer count must not disable task-marker validation."""
    messages = [{"role": "user", "content": "BDD_METADATA_TURN_ONE BDD_METADATA_TURN_ONE BDD_METADATA_ANSWER"}]
    with pytest.raises(AssertionError, match="BDD_METADATA_TURN_ONE"):
        _assert_clean_manifest(
            messages,
            ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ANSWER"],
            counts={"BDD_METADATA_ANSWER": 2},
        )


def _agent_content(role, markers):
    """Build complete expected provider message content for fixture markers."""
    marker = markers[0]
    raw_marker = marker + r"\n" if marker == "BDD_METADATA_TURN_TWO_TOKEN" else marker
    if role == "user":
        return json.dumps({"raw_text": raw_marker, "step_name": "task"}, ensure_ascii=False)
    if role == "assistant":
        step_name = "action" if marker == "BDD_METADATA_ACTION" else "final_answer"
        return json.dumps([{"raw_text": raw_marker, "step_name": step_name}], ensure_ascii=False)
    if role == "tool":
        return "topsailai.observation\n" + marker
    raise AssertionError(f"unsupported manifest role: {role}")


def _history_content(role, markers):
    """Build stable expected human-history content for fixture markers."""
    marker = markers[0]
    if marker == "BDD_METADATA_TURN_TWO_TOKEN":
        marker += r"\n"
    if role == "user":
        return "topsailai.task\n" + marker
    if role == "assistant":
        prefix = "topsailai.action" if marker == "BDD_METADATA_ACTION" else "topsailai.final_answer"
        return prefix + "\n" + marker
    return marker


def test_manifest_rejects_corrupted_content_with_unchanged_marker():
    """A marker-preserving content mutation must fail the exact manifest."""
    expected = _manifest_items([("user", ["BDD_METADATA_TURN_ONE"])])
    corrupted = [{"role": "user", "content": _agent_content("user", ["BDD_METADATA_TURN_ONE"]) + " CORRUPTED"}]
    with pytest.raises(AssertionError, match="CORRUPTED|BDD_METADATA_TURN_ONE"):
        _assert_exact_manifest(corrupted, expected, ["BDD_METADATA_TURN_ONE"])


def test_ordinary_wire_manifest_rejects_corrupted_content_with_unchanged_marker():
    """A marker-preserving ordinary wire mutation must fail the exact manifest."""
    expected = _ordinary_wire_manifest_items([("user", ["BDD_METADATA_TURN_ONE"])])
    corrupted = [{"role": "user", "content": "topsailai.task\nBDD_METADATA_TURN_ONE CORRUPTED"}]
    with pytest.raises(AssertionError, match="CORRUPTED|BDD_METADATA_TURN_ONE"):
        _assert_exact_manifest(corrupted, expected, ["BDD_METADATA_TURN_ONE"])


def _assert_exact_manifest(messages, expected, known_markers):
    actual = [message for message in messages if message.get("role") != "system"]
    expected_marker_counts = {marker: sum(item.get("markers", []).count(marker) for item in expected) for marker in known_markers}
    actual_text = "\n".join(_message_text(message) for message in actual)
    for marker, expected_count in expected_marker_counts.items():
        assert actual_text.count(marker) == expected_count, (marker, expected_count, actual_text)
    assert len(actual) == len(expected), (actual, expected)
    for index, (message, item) in enumerate(zip(actual, expected)):
        assert message.get("role") == item["role"], (index, message, item)
        content = _message_text(message)
        assert content == item["content"], (index, content, item["content"])
        markers = [marker for marker in known_markers if marker in content]
        assert markers == item.get("markers", []), (index, markers, item)


def _assert_history_manifest(history, expected, known_markers):
    """Require exact ordered roles and complete history content."""
    assert len(history) == len(expected), (history, expected)
    for index, ((role, content), item) in enumerate(zip(history, expected)):
        assert role == item["role"], (index, role, item)
        separator = "\n\n" + "=" * 80
        normalized_content = content.rsplit(separator, 1)[0]
        assert normalized_content == item["history_content"], (index, normalized_content, item["history_content"])
        for marker in known_markers:
            assert normalized_content.count(marker) == item.get("markers", []).count(marker), (index, marker, normalized_content)
        assert [marker for marker in known_markers if marker in normalized_content] == item.get("markers", []), (index, normalized_content, item)


def _manifest_items(sequence):
    """Build independent complete provider and history expectations."""
    return [
        {
            "role": role,
            "markers": markers,
            "content": _agent_content(role, markers),
            "history_content": _history_content(role, markers),
        }
        for role, markers in sequence
    ]


def _ordinary_manifest(checkpoint, turn):
    """Build complete ordinary Agent2LLM manifests."""
    if turn == 1:
        sequence = [("user", ["BDD_METADATA_TURN_ONE"])]
        if checkpoint != "A_pre":
            sequence.append(("assistant", ["BDD_METADATA_ANSWER"]))
        return _manifest_items(sequence)
    sequence = [
        ("user", ["BDD_METADATA_TURN_ONE"]),
        ("assistant", ["BDD_METADATA_ANSWER"]),
        ("user", ["BDD_METADATA_TURN_TWO_TOKEN"]),
    ]
    if checkpoint != "A_pre":
        sequence.append(("assistant", ["BDD_METADATA_ANSWER"]))
    if checkpoint == "H_post":
        sequence = [
            ("user", ["BDD_METADATA_TURN_ONE"]),
            ("assistant", ["BDD_METADATA_ANSWER"]),
            ("user", ["BDD_METADATA_TURN_TWO_TOKEN"]),
            ("assistant", ["BDD_METADATA_ANSWER"]),
        ]
    return _manifest_items(sequence)


def _native_manifest_items(sequence):
    """Build explicit native Agent2LLM JSON-serialized content expectations."""
    items = _manifest_items(sequence)
    answer_index = 0
    for item in items:
        marker = item["markers"][0]
        if item["role"] == "tool":
            item["content"] = json.dumps(
                {"raw_text": marker, "step_name": "observation"}, ensure_ascii=False
            )
        elif item["role"] == "assistant" and marker == "BDD_METADATA_ANSWER":
            answer_index += 1
            if answer_index == 2:
                # The persisted session copy of the turn-1 final answer is plain text.
                item["content"] = "BDD_METADATA_ANSWER"
    return items


def _native_wire_manifest_items(sequence):
    """Build complete native wire expectations in display serialized form."""
    items = _manifest_items(sequence)
    answer_index = 0
    for item in items:
        marker = item["markers"][0]
        if item["role"] == "tool":
            item["content"] = "topsailai.observation\n" + marker
        elif item["role"] in ("user", "assistant"):
            item["content"] = item["history_content"]
        if item["role"] == "assistant" and marker == "BDD_METADATA_ANSWER":
            answer_index += 1
            if answer_index > 1:
                item["content"] = "BDD_METADATA_ANSWER"
    return items


def _ordinary_wire_manifest_items(sequence):
    """Build complete ordinary wire expectations in display serialized form."""
    items = _manifest_items(sequence)
    for item in items:
        # Ordinary wire messages use the same display form as human history.
        item["content"] = item["history_content"]
    return items
def _native_manifest(checkpoint, turn):
    """Build independent native runtime manifests for each checkpoint."""
    if turn == 1:
        if checkpoint == "A_pre":
            sequence = [("user", ["BDD_METADATA_TURN_ONE"])]
        else:
            sequence = [
                ("user", ["BDD_METADATA_TURN_ONE"]),
                ("assistant", ["BDD_METADATA_ACTION"]),
                ("tool", ["BDD_METADATA_RESULT"]),
                ("assistant", ["BDD_METADATA_ANSWER"]),
            ]
    else:
        # Agent2LLM keeps the turn-1 ReAct history across turns.
        sequence = [
            ("user", ["BDD_METADATA_TURN_ONE"]),
            ("assistant", ["BDD_METADATA_ACTION"]),
            ("tool", ["BDD_METADATA_RESULT"]),
            ("assistant", ["BDD_METADATA_ANSWER"]),
            ("assistant", ["BDD_METADATA_ANSWER"]),
            ("user", ["BDD_METADATA_TURN_TWO_TOKEN"]),
        ]
        if checkpoint == "A_post":
            sequence.append(("assistant", ["BDD_METADATA_ANSWER"]))
    return _native_manifest_items(sequence)


def _native_history_manifest(checkpoint, turn):
    """Build complete native final-only history expectations."""
    if turn == 1:
        sequence = [
            ("user", ["BDD_METADATA_TURN_ONE"]),
            ("assistant", ["BDD_METADATA_ANSWER"]),
        ]
    else:
        sequence = [
            ("user", ["BDD_METADATA_TURN_ONE"]),
            ("assistant", ["BDD_METADATA_ANSWER"]),
            ("user", ["BDD_METADATA_TURN_TWO_TOKEN"]),
            ("assistant", ["BDD_METADATA_ANSWER"]),
        ]
    items = _manifest_items(sequence)
    for item in items:
        if item["role"] == "assistant":
            # Native persists only the plain final text, without a display prefix.
            item["history_content"] = item["markers"][0]
    return items
def _assert_instruction_purity(report):
    for snapshot in report["snapshots"]:
        for item in snapshot["items"]:
            assert item["consumed"]
            assert item["messages_before"] == item["messages_after"]
            assert item["session_before"] == item["session_after"]
            assert item["request_count_before"] == item["request_count_after"]
            if item["command"] == "/agent.messages":
                assert item["cache_identity"]
@then("persisted metadata reaches the second merge and history remains exact")
def then_metadata_is_replayed(request):
    report, scenario = request.node.metadata_report, request.node.metadata_scenario
    loaded = report["raw_loaded"]
    assert len(loaded) == 2 and any("storage_revision" in m for m in loaded[0])
    assert report["runtime_before_reload"] != loaded[0]
    assert report["merge_entry"] == loaded[0]
    assert len(report["merge_entries"]) >= 2
    state = scenario.state(); wires = _wire_messages(state)
    assert state["total_requests"] == 2
    _assert_exact_manifest(wires[0], _ordinary_wire_manifest_items([("user", ["BDD_METADATA_TURN_ONE"])]), ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ANSWER", "BDD_METADATA_TURN_TWO_TOKEN"])
    _assert_exact_manifest(wires[1], _ordinary_wire_manifest_items([("user", ["BDD_METADATA_TURN_ONE"]), ("assistant", ["BDD_METADATA_ANSWER"]), ("user", ["BDD_METADATA_TURN_TWO_TOKEN"])]), ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ANSWER", "BDD_METADATA_TURN_TWO_TOKEN"])
    assert sum(json.dumps(w).count("BDD_METADATA_TURN_ONE") for w in wires) == 2
    expected = {("A_pre", 1): ["BDD_METADATA_TURN_ONE"],
                ("A_post", 1): ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ANSWER"],
                ("H_post", 1): ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ANSWER"],
                ("A_pre", 2): ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ANSWER", "BDD_METADATA_TURN_TWO_TOKEN"],
                ("A_post", 2): ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ANSWER", "BDD_METADATA_TURN_TWO_TOKEN"],
                ("H_post", 2): ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ANSWER", "BDD_METADATA_TURN_TWO_TOKEN"]}
    for (checkpoint, turn), markers in expected.items():
        if checkpoint != "H_post":
            messages = parse_agent_messages(_item(report, checkpoint, "/agent.messages", turn)["stdout"])
            _assert_exact_manifest(messages, _ordinary_manifest(checkpoint, turn), ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ANSWER", "BDD_METADATA_TURN_TWO_TOKEN"])
        if checkpoint != "A_pre":
            history = parse_history_roles_and_content(_item(report, checkpoint, "/ctx.history", turn)["stdout"])
            expected_history = _ordinary_manifest(checkpoint, turn)
            _assert_history_manifest(history, expected_history, ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ANSWER", "BDD_METADATA_TURN_TWO_TOKEN"])
    _assert_instruction_purity(report)

@then("native pairing remains exact after metadata replay")
def then_native_metadata_is_replayed(request):
    report, scenario = request.node.metadata_report, request.node.metadata_scenario
    loaded = report["raw_loaded"]
    assert len(loaded) == 2 and any("storage_revision" in m for m in loaded[0])
    assert report["runtime_before_reload"] != loaded[0]
    assert report["merge_entry"] == loaded[0]
    state = scenario.state(); wires = _wire_messages(state)
    assert state["total_requests"] == 3
    assert report["tool_count"] == 1
    declarations = tool_messages = 0
    for index, messages in enumerate(wires):
        if index == 0:
            expected_wire = _native_wire_manifest_items([("user", ["BDD_METADATA_TURN_ONE"])])
        elif index == 1:
            expected_wire = _native_wire_manifest_items([("user", ["BDD_METADATA_TURN_ONE"]), ("assistant", ["BDD_METADATA_ACTION"]), ("tool", ["BDD_METADATA_RESULT"])])
        else:
            expected_wire = _native_wire_manifest_items([("user", ["BDD_METADATA_TURN_ONE"]), ("assistant", ["BDD_METADATA_ACTION"]), ("tool", ["BDD_METADATA_RESULT"]), ("assistant", ["BDD_METADATA_ANSWER"]), ("assistant", ["BDD_METADATA_ANSWER"]), ("user", ["BDD_METADATA_TURN_TWO_TOKEN"])])
        _assert_exact_manifest(messages, expected_wire, ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ACTION", "BDD_METADATA_RESULT", "BDD_METADATA_ANSWER", "BDD_METADATA_TURN_TWO_TOKEN"])
        calls = [(i, m) for i, m in enumerate(messages) if m.get("tool_calls")]
        tools = [(i, m) for i, m in enumerate(messages) if m.get("role") == "tool"]
        if index == 0:
            assert not calls and not tools
        else:
            assert len(calls) == len(tools) == 1
            i, declaration = calls[0]; j, result = tools[0]
            assert j == i + 1
            call = declaration["tool_calls"][0]
            assert call["id"] == result["tool_call_id"] == report["tool_call_id"]
            assert call["type"] == "function"
            assert call["function"]["name"] == report["tool_name"]
            assert json.loads(call["function"]["arguments"]) == {"value": report["tool_argument"]}
            assert result["content"] == report["tool_result"]
            declarations += 1; tool_messages += 1
    assert declarations == tool_messages == 2
    expected = {("A_pre", 1): ["BDD_METADATA_TURN_ONE"],
                ("A_post", 1): ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ACTION", "BDD_METADATA_RESULT", "BDD_METADATA_ANSWER"],
                ("H_post", 1): ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ANSWER"],
                ("A_pre", 2): ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ANSWER", "BDD_METADATA_TURN_TWO_TOKEN"],
                ("A_post", 2): ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ANSWER", "BDD_METADATA_TURN_TWO_TOKEN"],
                ("H_post", 2): ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ANSWER", "BDD_METADATA_TURN_TWO_TOKEN"]}
    for (checkpoint, turn), markers in expected.items():
        if checkpoint != "H_post":
            messages = parse_agent_messages(_item(report, checkpoint, "/agent.messages", turn)["stdout"])
            _assert_exact_manifest(messages, _native_manifest(checkpoint, turn), ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ACTION", "BDD_METADATA_RESULT", "BDD_METADATA_ANSWER", "BDD_METADATA_TURN_TWO_TOKEN"])
        if checkpoint != "A_pre":
            history = parse_history_roles_and_content(_item(report, checkpoint, "/ctx.history", turn)["stdout"])
            _assert_history_manifest(
                history,
                _native_history_manifest(checkpoint, turn),
                ["BDD_METADATA_TURN_ONE", "BDD_METADATA_ANSWER", "BDD_METADATA_TURN_TWO_TOKEN"],
            )
    _assert_instruction_purity(report)
