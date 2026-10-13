"""Point-local metadata observer entry. Author: DawsonLin."""

from topsailai.hooks.points.context.summary_events_observer.observer import main as observe


def main(*, hook_context):
    """Delegate the captured point entry to the shared validated recorder."""
    return observe(hook_context=hook_context)
