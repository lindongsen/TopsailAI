"""Publish repeated LLM failures into Agent Runtime Data."""

from topsailai.ai_base.llm_control.retry_runtime_state import (
    observe_retry_attempt_error,
)


def main(**payload):
    """Publish or update the request-scoped retry state at its threshold."""
    return observe_retry_attempt_error(
        payload.get("operation_id") or "",
        payload.get("error_category") or "unknown",
    )


__all__ = ["main"]
