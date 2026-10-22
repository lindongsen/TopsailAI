"""Detached metadata for the Agent2LLM run-success Hook Point. Author: DawsonLin."""

from topsailai.hooks.points.aibase.agent_run_payloads import build_payload as _build_payload


def build_payload(*, operation_id, agent_name, step_call, result,
                  pending_native_tool_responses_cleared=False):
    """Build bounded metadata without exposing the returned value."""
    return _build_payload(
        point_name="hook__aibase__after__agent_run", outcome="success",
        operation_id=operation_id, agent_name=agent_name, step_call=step_call,
        result=result,
        pending_native_tool_responses_cleared=pending_native_tool_responses_cleared,
    )


__all__ = ["build_payload"]
