"""Inject recovery guidance after consecutive null LLM responses."""

from topsailai.ai_base.llm_control.null_response_recovery import observe_attempt_error


def main(**payload):
    """Observe one failed attempt and inject ``continue`` when the streak fires."""
    return observe_attempt_error(
        payload.get("operation_id") or "",
        payload.get("error_category") or "",
    )


__all__ = ["main"]
