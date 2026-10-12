"""Centralized declaration alias for after_summary_apply_user2agent.

Author: DawsonLin
"""

from topsailai.hooks.points.context.summary_contracts import AFTER_APPLY_USER2AGENT

NAME = AFTER_APPLY_USER2AGENT.name
POINT = AFTER_APPLY_USER2AGENT.declaration

__all__ = ["NAME", "POINT"]
