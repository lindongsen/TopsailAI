"""Agent2LLM run-error Hook Point entry. Author: DawsonLin."""

from topsailai.hooks.points.aibase.error_agent_run.point import NAME, POINT


def hook__aibase__error__agent_run(**payload):
    """Forward detached metadata to the direct-entry executor."""
    from topsailai.hooks import invoke_hook_point

    try:
        return invoke_hook_point(NAME, **payload)
    except (
        __import__("topsailai.ai_base.exception", fromlist=["HardInterruptError"]).HardInterruptError,
        __import__("topsailai.ai_base.llm_control.control_runtime", fromlist=["LLMRequestedRetryError"]).LLMRequestedRetryError,
    ):
        raise
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Agent run Hook failed point=%s operation_id=%s",
            NAME, payload.get("operation_id"),
        )
        return None


__all__ = ["NAME", "POINT", "hook__aibase__error__agent_run"]
