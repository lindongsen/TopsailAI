"""Detached metadata for the Agent2LLM run-start Hook Point. Author: DawsonLin."""

from topsailai.hooks.points.aibase.agent_run_payloads import build_payload as _build_payload


def build_payload(*, operation_id, agent_name, step_call, user_input):
    """Build bounded metadata without exposing business content."""
    return _build_payload(
        point_name="hook__aibase__before__agent_run", outcome="before",
        operation_id=operation_id, agent_name=agent_name, step_call=step_call,
        user_input=user_input,
    )


__all__ = ["build_payload"]
