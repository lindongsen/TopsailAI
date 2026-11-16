"""Message shape reference for storage-versus-runtime comparison.

Purpose: make the two message shapes explicit so nobody compares them naively.

A message travels through three distinct shapes, and only the last two are
ever compared with each other:

1. ``PersistedMessageRecord`` - the database row object. Its ``message``
   attribute is a JSON *string*, not a dict.
2. ``PersistedMessageDict`` - the dict produced after that JSON string is
   parsed. For every non-system message the persistence layer has already
   injected a ``create_time`` key that the runtime never creates.
3. ``RuntimeMessageDict`` - the dict held in ``self.messages`` and
   ``ai_agent.messages``. It carries business fields only.

The trap: ``PersistedMessageDict`` and ``RuntimeMessageDict`` look almost
identical, so ``==`` appears to work. It does not. A message that was loaded
from storage at turn start carries ``create_time``; a message created during
the current turn does not. Comparing the two shapes therefore fails for
exactly the newest message, which is the one a summarizer most needs to
identify.

These classes are documentation only. They are intentionally not instantiated
by production code: their value is the field list and the docstring, which
state the difference at the place a future reader will look. Do not delete
them merely because nothing imports them.

Safe comparison: project both sides through
``utils.history_replay_message.history_replay_semantic_projection`` and
compare the projections, never the raw dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PersistedMessageRecord:
    """One database row, as returned by ``get_messages_by_session``.

    ``message`` is a JSON string. Parse it before reading any field; treating
    it as a dict silently yields string operations instead of field access.
    """

    msg_id: str
    session_id: str
    message: str
    msg_size: int = 0
    message_content: str = ""
    create_time: object = None
    access_time: object = None
    access_count: object = None


@dataclass
class PersistedMessageDict:
    """The parsed dict form of a stored message.

    Produced by ``retrieve_messages``, which parses each row's JSON string.
    ``create_time`` is present for every non-system message because
    ``add_session_message`` injects it before writing. System messages are
    stored without it.

    This shape is NOT equal to ``RuntimeMessageDict`` even when both describe
    the same logical message.
    """

    role: str
    content: object = None
    create_time: str = ""
    name: str = ""
    tool_calls: list = field(default_factory=list)
    tool_call_id: str = ""
    function_call: object = None


@dataclass
class RuntimeMessageDict:
    """The in-memory dict held by the context runtime and the agent.

    Carries business fields only. A message loaded from storage at turn start
    may still carry ``create_time`` because it was copied from the persisted
    shape; a message created during the current turn never does. That
    asymmetry is the reason raw equality is unsafe.
    """

    role: str
    content: object = None
    name: str = ""
    tool_calls: list = field(default_factory=list)
    tool_call_id: str = ""
    function_call: object = None


@dataclass
class MessageComparisonRule:
    """The only supported way to decide whether two messages are the same.

    Compare semantic projections, never raw dicts. Storage metadata such as
    ``create_time`` is excluded by the projection, so a freshly created
    message and its persisted counterpart compare equal.
    """

    semantic_fields: tuple = (
        "role",
        "content",
        "name",
        "tool_calls",
        "tool_call_id",
        "function_call",
    )
    excluded_storage_fields: tuple = (
        "create_time",
        "access_time",
        "access_count",
        "msg_id",
        "msg_size",
    )
