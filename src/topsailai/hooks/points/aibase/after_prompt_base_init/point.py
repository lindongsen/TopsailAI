"""Declaration for the PromptBase initialization completion Hook Point.

Author: DawsonLin
"""

from topsailai.hooks.contracts import EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointDeclaration

NAME = "hook__aibase__after__prompt_base_init"
POINT = HookPointDeclaration(
    name=NAME,
    definition=EventDefinition(
        name=NAME, major_version=1,
        payload_schema={"type": "object", "properties": {}},
        payload_limit_bytes=128,
    ),
    phase="success", mode="sync", owner="ai_base.prompt_base",
    failure_policy="report", latency_budget_ms=1_000,
)

__all__ = ["NAME", "POINT"]
