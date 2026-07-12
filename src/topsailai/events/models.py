"""
Event data model for the TopsailAI event module.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


def _json_default(obj: Any) -> Any:
    """Fallback serializer for objects that are not JSON-serializable by default."""
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except UnicodeDecodeError:
            return obj.hex()
    if isinstance(obj, Exception):
        return f"{type(obj).__name__}: {obj}"
    try:
        return str(obj)
    except Exception:
        return "<unserializable>"


@dataclass
class Event:
    """
    A single event recorded by the agent.

    Attributes:
        event_type: Dot-separated event type, e.g. "tool_call.start".
        timestamp: UTC datetime when the event was created.
        session_id: Optional session identifier.
        payload: Arbitrary event-specific data.
        trace_id: Optional correlation/trace identifier.
        source: Optional source component, e.g. "ai_base.tool".
        event_id: Unique event identifier.
    """

    event_type: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    session_id: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None
    source: Optional[str] = None
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event to a plain dictionary."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    def to_json_line(self) -> str:
        """Serialize the event to a single JSON line."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default,
        )

    def to_json(self) -> str:
        """Alias for to_json_line() for backward compatibility with tests."""
        return self.to_json_line()
