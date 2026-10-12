"""Centralized declaration alias for after_summary_generate_agent2llm.

Author: DawsonLin
"""

from topsailai.hooks.points.context.summary_contracts import AFTER_GENERATE_AGENT2LLM

NAME = AFTER_GENERATE_AGENT2LLM.name
POINT = AFTER_GENERATE_AGENT2LLM.declaration

__all__ = ["NAME", "POINT"]
