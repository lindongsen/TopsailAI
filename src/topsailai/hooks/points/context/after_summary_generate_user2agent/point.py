"""Centralized declaration alias for after_summary_generate_user2agent.

Author: DawsonLin
"""

from topsailai.hooks.points.context.summary_contracts import AFTER_GENERATE_USER2AGENT

NAME = AFTER_GENERATE_USER2AGENT.name
POINT = AFTER_GENERATE_USER2AGENT.declaration

__all__ = ["NAME", "POINT"]
