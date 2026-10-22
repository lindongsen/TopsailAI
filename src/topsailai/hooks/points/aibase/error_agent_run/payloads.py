"""Detached metadata for the Agent2LLM run-error Hook Point. Author: DawsonLin."""

from topsailai.hooks.points.aibase.agent_run_payloads import build_payload as _build_payload


def build_payload(*, operation_id, agent_name, step_call, error):
    """Build bounded metadata without exposing exception details."""
    return _build_payload(
        point_name="hook__aibase__error__agent_run", outcome="error",
        operation_id=operation_id, agent_name=agent_name, step_call=step_call,
        error=error,
    )


__all__ = ["build_payload"]
