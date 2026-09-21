"""Tests for JEV Agent2LLM context export."""

import copy
from types import SimpleNamespace

import pytest

from topsailai.tools.jev_tool_utils.context import JevContextError, build_state


def call(call_id, name="demo", arguments='{"x":1}'):
    """Build one native tool-call declaration."""
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def test_exports_roles_pairs_and_redacts_without_mutation():
    """Eligible paired history is exported safely and source remains intact."""
    key = "private-key"
    messages = [
        {"role": "system", "content": "hidden"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "", "tool_calls": [call("c1")]},
        {"role": "tool", "tool_call_id": "c1", "name": "demo", "content": {"authorization": "Bearer abc", "result": key}},
        {"role": "assistant", "content": "done"},
        {"role": "assistant", "content": "", "tool_calls": [call("active", "jev_tool-evaluate")]},
    ]
    original = copy.deepcopy(messages)
    state = build_state(SimpleNamespace(messages=messages), key, 50, 60000)
    exported = state["agent2llm_messages"]
    assert [item["role"] for item in exported] == ["user", "assistant", "tool", "assistant"]
    assert exported[2]["content"] == {"authorization": "***", "result": "***"}
    assert messages == original


def test_drops_orphan_and_incomplete_groups():
    """Tool messages are exported only in complete declaration groups."""
    messages = [
        {"role": "user", "content": "start"},
        {"role": "tool", "tool_call_id": "none", "content": "orphan"},
        {"role": "assistant", "content": "", "tool_calls": [call("a"), call("b")]},
        {"role": "tool", "tool_call_id": "a", "content": "partial"},
        {"role": "assistant", "content": "end"},
    ]
    state = build_state(SimpleNamespace(messages=messages), "key", 50, 60000)
    assert state == {"agent2llm_messages": [{"role": "user", "content": "start"}, {"role": "assistant", "content": "end"}]}


def test_message_limit_keeps_tool_group_atomic():
    """Message limits never retain only part of a tool group."""
    messages = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "", "tool_calls": [call("a")]},
        {"role": "tool", "tool_call_id": "a", "content": "result"},
    ]
    state = build_state(SimpleNamespace(messages=messages), "key", 2, 60000)
    assert [message["role"] for message in state["agent2llm_messages"]] == ["assistant", "tool"]


def test_character_limit_truncates_newest_content():
    """One oversized newest unit is marked and bounded."""
    state = build_state(
        SimpleNamespace(messages=[{"role": "user", "content": "x" * 1000}]),
        "key", 10, 180,
    )
    message = state["agent2llm_messages"][0]
    assert message["truncated"] is True
    assert "[truncated]" in message["content"]

@pytest.mark.parametrize("agent", [None, SimpleNamespace(messages=[]), SimpleNamespace(messages=[{"role": "system", "content": "only"}])])
def test_requires_eligible_runtime_context(agent):
    """Missing or fully excluded context is unavailable."""
    with pytest.raises(JevContextError):
        build_state(agent, "key", 50, 60000)


class DumpMessage:
    """Provide a model_dump-compatible runtime message."""

    def model_dump(self):
        """Return the plain runtime representation."""
        return {"role": "user", "content": "from model dump"}


class DictMessage:
    """Provide a dict-compatible runtime message."""

    def dict(self):
        """Return the plain runtime representation."""
        return {"role": "assistant", "content": "from dict"}


class AttributeMessage:
    """Provide an attribute-based runtime message."""

    role = "user"
    content = "from attributes"


class BrokenDumpMessage:
    """Fall back from a failing model dump to attributes."""

    role = "assistant"
    content = "fallback"

    def model_dump(self):
        """Simulate an adapter serialization failure."""
        raise RuntimeError("broken")


def test_normalizes_json_and_object_like_messages():
    """Runtime JSON strings and supported object adapters are exported."""
    messages = [
        '{"role":"user","content":"from json"}',
        DumpMessage(),
        DictMessage(),
        AttributeMessage(),
        BrokenDumpMessage(),
        "not-json",
        object(),
    ]
    state = build_state(SimpleNamespace(messages=messages), "key", 20, 60000)
    assert [item["content"] for item in state["agent2llm_messages"]] == [
        "from json", "from model dump", "from dict", "from attributes", "fallback"
    ]


def test_redacts_bearer_text_nested_lists_and_named_secrets():
    """Recognizable credentials are removed recursively from exported values."""
    messages = [{
        "role": "user",
        "content": {
            "items": ["Authorization: Bearer token-value", {"access-token": "abc"}],
            "plain": "configured-key",
        },
    }]
    state = build_state(SimpleNamespace(messages=messages), "configured-key", 10, 60000)
    content = state["agent2llm_messages"][0]["content"]
    assert content == {"items": ["Authorization: Bearer ***", {"access-token": "***"}], "plain": "***"}


def test_normalizes_unsupported_and_non_finite_content():
    """Unsupported runtime values become bounded JSON-safe markers."""
    messages = [{
        "role": "user",
        "content": {
            "binary": b"secret-bytes",
            "opaque": object(),
            "not_a_number": float("nan"),
            "tuple": ("kept", object()),
        },
    }]
    state = build_state(SimpleNamespace(messages=messages), "key", 10, 60000)
    content = state["agent2llm_messages"][0]["content"]
    assert content == {
        "binary": "[unsupported-bytes]",
        "opaque": "[unsupported-object]",
        "not_a_number": "[unsupported-non-finite-number]",
        "tuple": ["kept", "[unsupported-object]"],
    }


def test_character_limit_removes_old_units_before_truncation():
    """Character limits discard oldest units while retaining the newest evidence."""
    messages = [
        {"role": "user", "content": "old" * 100},
        {"role": "assistant", "content": "new"},
    ]
    state = build_state(SimpleNamespace(messages=messages), "key", 10, 100)
    assert state["agent2llm_messages"] == [{"role": "assistant", "content": "new"}]


def test_tiny_character_limit_fails_closed():
    """A limit smaller than the irreducible envelope is rejected."""
    with pytest.raises(JevContextError, match="context_limit_too_small"):
        build_state(
            SimpleNamespace(messages=[{"role": "user", "content": "x" * 100}]),
            "key", 10, 70,
        )


def test_oversized_tool_group_remains_paired_and_bounded():
    """Oversized tool arguments and results stay paired within the character cap."""
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [call("a", arguments="x" * 1000)]},
        {"role": "tool", "tool_call_id": "a", "content": "y" * 1000},
    ]
    state = build_state(SimpleNamespace(messages=messages), "key", 10, 300)
    serialized = __import__("json").dumps(state, ensure_ascii=False, separators=(",", ":"))
    assert len(serialized) <= 300
    assert [item["role"] for item in state["agent2llm_messages"]] == ["assistant", "tool"]
