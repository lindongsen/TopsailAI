"""LLM chat attempt after declaration. Author: DawsonLin."""

from topsailai.hooks.contracts import EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointDeclaration
from topsailai.hooks.points.aibase.llm_chat_attempt_payloads import COMMON_PROPERTIES

NAME = "hook__aibase__after__llm_chat_attempt"
PROPERTIES = dict(COMMON_PROPERTIES)
PROPERTIES["duration_sec"] = {"type": "number"}

POINT = HookPointDeclaration(
    name=NAME,
    definition=EventDefinition(
        name=NAME, major_version=1,
        payload_schema={
            "type": "object", "properties": PROPERTIES,
            "required": list(PROPERTIES),
        },
        payload_limit_bytes=8192,
    ),
    phase="success", mode="sync", owner="ai_base.llm_chat_attempt",
    failure_policy="report", latency_budget_ms=1_000,
)

__all__ = ["NAME", "POINT"]
