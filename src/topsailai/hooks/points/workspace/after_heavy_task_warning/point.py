"""Heavy-task advisory warning declaration.

Author: DawsonLin
"""

from topsailai.hooks.contracts import EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointDeclaration

NAME = "hook__workspace__after__heavy_task_warning"

# Metadata only: the advisory prompt text and the agent object never enter the
# payload, so an observer cannot leak conversation content.
PROPERTIES = {
    "schema_version": {"type": "integer"},
    "continuous_summary_times": {"type": "integer"},
    "threshold": {"type": "integer"},
}

POINT = HookPointDeclaration(
    name=NAME,
    definition=EventDefinition(
        name=NAME, major_version=1,
        payload_schema={
            "type": "object", "properties": PROPERTIES,
            "required": list(PROPERTIES),
        },
        payload_limit_bytes=256,
    ),
    phase="success", mode="sync", owner="workspace.heavy_task",
    failure_policy="report", latency_budget_ms=1_000,
)

__all__ = ["NAME", "POINT"]
