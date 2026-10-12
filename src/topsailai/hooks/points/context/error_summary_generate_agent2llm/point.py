"""Centralized declaration alias for error_summary_generate_agent2llm.

Author: DawsonLin
"""

from topsailai.hooks.points.context.summary_contracts import ERROR_GENERATE_AGENT2LLM

NAME = ERROR_GENERATE_AGENT2LLM.name
POINT = ERROR_GENERATE_AGENT2LLM.declaration

__all__ = ["NAME", "POINT"]
