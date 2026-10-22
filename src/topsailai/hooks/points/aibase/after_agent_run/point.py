"""Declaration for the Agent2LLM run-success Hook Point. Author: DawsonLin."""

from topsailai.hooks.contracts import EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointDeclaration

NAME = "hook__aibase__after__agent_run"
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
                "result_kind": {"type": "string"},
                "result_present": {"type": "boolean"},
                "pending_native_tool_responses_cleared": {"type": "boolean"},
            },
            "required": [
                "schema_version", "operation_id", "point_name", "outcome",
                "agent_layer", "agent_name_present", "step_call_type",
                "result_kind", "result_present",
                "pending_native_tool_responses_cleared",
            ],
        },
        payload_limit_bytes=8192,
    ),
    phase="success", mode="sync", owner="ai_base.agent_run",
    failure_policy="report", latency_budget_ms=1_000,
)
