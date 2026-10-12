"""Centralized declaration alias for before_summary_generate_agent2llm.

Author: DawsonLin
"""

from topsailai.hooks.points.context.summary_contracts import BEFORE_GENERATE_AGENT2LLM

NAME = BEFORE_GENERATE_AGENT2LLM.name
POINT = BEFORE_GENERATE_AGENT2LLM.declaration

__all__ = ["NAME", "POINT"]
