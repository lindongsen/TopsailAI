"""Declaration for the Agent2LLM run-error Hook Point. Author: DawsonLin."""

from topsailai.hooks.contracts import EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointDeclaration

NAME = "hook__aibase__error__agent_run"
POINT = HookPointDeclaration(
    name=NAME,
    definition=EventDefinition(
        name=NAME, major_version=1,
        payload_schema={
            "type": "object",
            "properties": {
                "schema_version": {"type": "integer"},
                "operation_id": {"type": "string"},
                "point_name": {"type": "string"},
                "outcome": {"type": "string"},
                "agent_layer": {"type": "string"},
                "agent_name_present": {"type": "boolean"},
                "step_call_type": {"type": "string"},
                "error_category": {"type": "string"},
                "failed_stage": {"type": "string"},
                "partial_run_possible": {"type": "boolean"},
            },
            "required": [
                "schema_version", "operation_id", "point_name", "outcome",
                "agent_layer", "agent_name_present", "step_call_type",
                "error_category", "failed_stage", "partial_run_possible",
            ],
        },
        payload_limit_bytes=8192,
    ),
    phase="error", mode="sync", owner="ai_base.agent_run",
    failure_policy="report", latency_budget_ms=1_000,
)

__all__ = ["NAME", "POINT"]
