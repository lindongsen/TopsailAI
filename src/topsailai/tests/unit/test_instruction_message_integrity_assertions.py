"""Unit tests for the independent instruction-message oracle."""

import json

import pytest

from tests.bdd.instruction_message_integrity_assertions import (
    assert_message_manifest,
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
