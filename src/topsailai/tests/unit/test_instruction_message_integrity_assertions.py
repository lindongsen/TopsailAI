"""Unit tests for the independent instruction-message oracle."""

import json

import pytest

from tests.bdd.instruction_message_integrity_assertions import (
    assert_message_manifest,
    assert_system_context,
    parse_agent_messages,
    parse_history_roles_and_content,
)


def _report(messages, count=None):
    """Build an agent.messages report fixture."""
    if count is None:
        count = len(messages)
    return json.dumps(messages) + f"\n\n---\n\nTotalCount: {count}\n"


def test_parse_valid_report_and_reject_footer_mismatch():
    """The parser accepts a valid footer and rejects an inconsistent count."""
    messages = [{"role": "user", "content": "TOKEN"}]
    assert parse_agent_messages(_report(messages)) == messages
    with pytest.raises(AssertionError, match="footer count"):
        parse_agent_messages(_report(messages, count=2))


def test_manifest_rejects_wrong_order_and_missing_content():
    """The manifest checks exact positions, roles, and marker content."""
    manifest = [
        {"role": "user", "markers": ["FIRST"], "all_markers": ["FIRST", "SECOND"]},
        {"role": "assistant", "markers": ["SECOND"], "all_markers": ["SECOND"]},
    ]
    with pytest.raises(AssertionError):
        assert_message_manifest([
            {"role": "user", "content": "SECOND"},
            {"role": "assistant", "content": "FIRST"},
        ], manifest)
    with pytest.raises(AssertionError):
        assert_message_manifest([
            {"role": "user", "content": "FIRST"},
            {"role": "assistant", "content": ""},
        ], manifest)


def test_system_context_requires_leading_fixture_controlled_context():
    """System context must lead, contain the expected fixture marker, and be nonempty."""
    valid = [
        {"role": "system", "content": "BDD_SYSTEM_CONTEXT_MARKER"},
        {"role": "system", "content": "additional context"},
        {"role": "user", "content": "task"},
    ]
    assert_system_context(
        valid,
        ["task"],
        expected_markers=["BDD_SYSTEM_CONTEXT_MARKER"],
        expected_count=2,
    )
    with pytest.raises(AssertionError, match="leading"):
        assert_system_context(
            [valid[2], valid[0], valid[1]],
            ["task"],
            expected_markers=["BDD_SYSTEM_CONTEXT_MARKER"],
            expected_count=2,
        )
    with pytest.raises(AssertionError, match="fixture markers"):
        assert_system_context(
            [{"role": "system", "content": "replacement"}, valid[1], valid[2]],
            ["task"],
            expected_markers=["BDD_SYSTEM_CONTEXT_MARKER"],
            expected_count=2,
        )


def test_manifest_rejects_duplicate_marker_within_one_content():
    """A repeated fixture marker is not silently collapsed."""
    manifest = [{"role": "user", "markers": ["TOKEN"], "all_markers": ["TOKEN"]}]
    with pytest.raises(AssertionError):
        assert_message_manifest([{"role": "user", "content": "TOKEN TOKEN"}], manifest)


def test_cross_request_replay_is_checked_per_request_not_globally():
    """The same persisted fixture is valid when independently checked in two requests."""
    manifest = [{"role": "user", "markers": ["TOKEN"], "all_markers": ["TOKEN"]}]
    message = [{"role": "user", "content": "TOKEN"}]
    assert_message_manifest(message, manifest)
    assert_message_manifest(message, manifest)


def test_manifest_rejects_reversed_markers_within_one_content_block():
    """Marker order is checked by content position, not manifest order."""
    manifest = [{"role": "user", "markers": ["FIRST", "SECOND"], "all_markers": ["FIRST", "SECOND"]}]
    with pytest.raises(AssertionError):
        assert_message_manifest([{"role": "user", "content": "SECOND FIRST"}], manifest)


def test_manifest_rejects_duplicate_complete_message_block():
    """An unexpected duplicate message changes the exact projection length."""
    manifest = [{"role": "user", "markers": ["TOKEN"], "all_markers": ["TOKEN"]}]
    with pytest.raises(AssertionError):
        assert_message_manifest([{"role": "user", "content": "TOKEN"}, {"role": "user", "content": "TOKEN"}], manifest)


def test_history_parser_requires_numbered_formatted_blocks():
    """History parsing consumes formatted headers and rejects numbering gaps."""
    block = "Show history messages session\n#1 - Role: USER - Words: 1 - Tokens: 1\n" + "=" * 80 + "\nTOKEN\n"
    assert parse_history_roles_and_content(block) == [("user", "TOKEN")]
    with pytest.raises(AssertionError):
        parse_history_roles_and_content(block.replace("#1", "#2"))


def _native_group():
    """Return one valid native tool group fixture."""
    return [
        {"role": "user", "content": "BDD_NATIVE_TASK_TOKEN"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_bdd_integrity_native", "type": "function",
            "function": {"name": "safe_native_tool", "arguments": '{"value":"BDD_NATIVE_ARGUMENT_TOKEN"}'},
        }]},
        {"role": "tool", "content": '{\n  "raw_text": "BDD_NATIVE_RESULT_TOKEN",\n  "step_name": "observation"\n}', "tool_call_id": "call_bdd_integrity_native"},
        {"role": "assistant", "content": "BDD_NATIVE_ANSWER_TOKEN"},
    ]


def _native_kwargs():
    """Return exact native fixture expectations."""
    return dict(task_marker="BDD_NATIVE_TASK_TOKEN", tool_name="safe_native_tool", call_id="call_bdd_integrity_native", argument={"value": "BDD_NATIVE_ARGUMENT_TOKEN"}, result_marker="BDD_NATIVE_RESULT_TOKEN", result_content='{\n  "raw_text": "BDD_NATIVE_RESULT_TOKEN",\n  "step_name": "observation"\n}')


def test_native_tool_pairing_oracle_accepts_complete_group_and_replay():
    """A complete native group is valid in independent observation lists."""
    from tests.bdd.instruction_message_integrity_assertions import assert_native_tool_group
    assert_native_tool_group(_native_group(), **_native_kwargs())
    assert_native_tool_group(_native_group(), **_native_kwargs())


@pytest.mark.parametrize("mutator", [
    pytest.param(lambda group: group[:1] + group[2:], id="missing-declaration"),
    pytest.param(lambda group: [group[0], group[1], group[3]], id="missing-result"),
    pytest.param(lambda group: [group[0], group[1], group[1], group[2], group[3]], id="duplicate-declaration"),
    pytest.param(lambda group: [group[0], group[1], group[2], group[2], group[3]], id="duplicate-result"),
    pytest.param(lambda group: [group[0], group[1], {**group[2], "tool_call_id": "wrong"}, group[3]], id="id-mismatch"),
    pytest.param(lambda group: [group[0], group[1], {**group[2], "content": "BDD_NATIVE_RESULT_TOKEN extra"}, group[3]], id="wrong-result-serialization"),
    pytest.param(lambda group: [group[0], {**group[1], "tool_calls": [{**group[1]["tool_calls"][0], "function": {"name": "wrong", "arguments": '{"value":"BDD_NATIVE_ARGUMENT_TOKEN"}'}}]}, group[2], group[3]], id="wrong-name"),
    pytest.param(lambda group: [group[0], {**group[1], "tool_calls": [{**group[1]["tool_calls"][0], "function": {"name": "safe_native_tool", "arguments": '{"value":"wrong"}'}}]}, group[2], group[3]], id="wrong-arguments"),
    pytest.param(lambda group: [group[0], group[2], group[1], group[3]], id="wrong-order"),
    pytest.param(lambda group: [group[1], group[0], group[2], group[3]], id="task-group-order"),
])
def test_native_tool_pairing_oracle_rejects_invalid_groups(mutator):
    """Each native pairing defect is rejected independently."""
    from tests.bdd.instruction_message_integrity_assertions import assert_native_tool_group
    with pytest.raises(AssertionError):
        assert_native_tool_group(mutator(_native_group()), **_native_kwargs())
