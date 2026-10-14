"""Semantic message projection for history replay merging."""

from __future__ import annotations


HISTORY_REPLAY_SEMANTIC_FIELDS = (
    "role",
    "content",
    "name",
    "tool_calls",
    "tool_call_id",
    "function_call",
)


def history_replay_semantic_projection(message):
    """Project a message to its replay-semantic top-level business fields.

    This helper is limited to history-replay merge boundaries. Nested values
    are preserved intact, while storage and transport metadata at the top
    level is excluded from semantic comparison.
    """
    if not isinstance(message, dict):
        return message
    return {
        key: message[key]
        for key in HISTORY_REPLAY_SEMANTIC_FIELDS
        if key in message
    }
