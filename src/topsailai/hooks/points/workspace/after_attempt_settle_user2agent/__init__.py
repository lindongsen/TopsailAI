"""Observe attempt settlement, NOT execution success; outcome expresses success.

Author: DawsonLin
"""
NAME = "hook__workspace__after__attempt_settle_user2agent"


def hook__workspace__after__attempt_settle_user2agent(
    *, agent_chat, outcome, attempt=None,
):
    """Run after the attempt result is settled, NOT only after successful execution."""
    from topsailai.hooks import invoke_hook_point

    return invoke_hook_point(
        NAME, agent_chat=agent_chat, outcome=outcome, attempt=attempt,
    )
