"""Centralized declaration alias for before_summary_generate_user2agent.

Author: DawsonLin
"""

from topsailai.hooks.points.context.summary_contracts import BEFORE_GENERATE_USER2AGENT

NAME = BEFORE_GENERATE_USER2AGENT.name
POINT = BEFORE_GENERATE_USER2AGENT.declaration

__all__ = ["NAME", "POINT"]
