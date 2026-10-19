"""Offer a settled attempt without retaining live payloads. Author: DawsonLin."""


def main(*, agent_chat, outcome, attempt=None):
    """Deliver once if authorized; ordinary statistics failures are best effort."""
    if attempt is None:
        return False
    try:
        if not attempt.binding.settle_authorized(agent_chat.ai_agent):
            return False
        return attempt.deliver()
    except Exception:
        return False
