"""Centralized declaration alias for after_summary_apply_agent2llm.

Author: DawsonLin
"""

from topsailai.hooks.points.context.summary_contracts import AFTER_APPLY_AGENT2LLM

NAME = AFTER_APPLY_AGENT2LLM.name
POINT = AFTER_APPLY_AGENT2LLM.declaration

__all__ = ["NAME", "POINT"]
