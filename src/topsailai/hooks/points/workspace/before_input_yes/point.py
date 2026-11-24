"""Observe one yes/no confirmation before delegating to its reader.

Author: DawsonLin
"""

from topsailai.hooks.contracts import EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointDeclaration

NAME = "hook__workspace__before__input_yes"
POINT = HookPointDeclaration(
    name=NAME,
    definition=EventDefinition(
        name=NAME, major_version=1,
        payload_schema={
            "type": "object", "required": ["tips"],
            "properties": {"tips": {"type": "string"}},
        },
        payload_limit_bytes=8192,
    ),
    phase="before", mode="sync", owner="workspace.input_tool",
    failure_policy="report", latency_budget_ms=1_000,
)

__all__ = ["NAME", "POINT"]
