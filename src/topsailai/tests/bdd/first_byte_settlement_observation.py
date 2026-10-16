"""Exact EOF and late-read observations for first-byte ownership settlement."""

from topsailai.ai_base.llm_control.exception import LLMProviderReadError
from topsailai.ai_base.llm_control.response_ownership import AttemptResponseOwner


def observe_eof(observations):
    """Wrap real EOF publication without changing its return value or outcome."""
    original = AttemptResponseOwner.publish_eof

    def publish(owner, *, phase="first_item"):
        """Retain rejected EOF on the exact registered first-item owner."""
        accepted = original(owner, phase=phase)
        if phase == "first_item" and id(owner) in observations:
            observations[id(owner)]["eof_rejected"] = not accepted
        return accepted

    return publish


def is_late_read(observation):
    """Accept an exact retained abandoned-primary read error, not disposal failure."""
    owner = observation["owner"]
    return (
        observation["ordinal"] == 1
        and owner._abandoned
        and owner.disposal_error is None
        and isinstance(owner.close_error, LLMProviderReadError)
        and any(error is owner.close_error for error in observation["late_errors"])
    )
