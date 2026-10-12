"""Explicit summary catalog composition without runtime activation.

Author: DawsonLin
"""

from topsailai.hooks.hook_point_catalog import HookPointCatalog
from topsailai.hooks.points.context.before_summary_generate_user2agent import POINT as BEFORE_GENERATE_USER2AGENT
from topsailai.hooks.points.context.before_summary_generate_agent2llm import POINT as BEFORE_GENERATE_AGENT2LLM
from topsailai.hooks.points.context.after_summary_generate_user2agent import POINT as AFTER_GENERATE_USER2AGENT
from topsailai.hooks.points.context.after_summary_generate_agent2llm import POINT as AFTER_GENERATE_AGENT2LLM
from topsailai.hooks.points.context.after_summary_apply_user2agent import POINT as AFTER_APPLY_USER2AGENT
from topsailai.hooks.points.context.after_summary_apply_agent2llm import POINT as AFTER_APPLY_AGENT2LLM
from topsailai.hooks.points.context.error_summary_generate_user2agent import POINT as ERROR_GENERATE_USER2AGENT
from topsailai.hooks.points.context.error_summary_generate_agent2llm import POINT as ERROR_GENERATE_AGENT2LLM
from topsailai.hooks.points.context.error_summary_apply_user2agent import POINT as ERROR_APPLY_USER2AGENT
from topsailai.hooks.points.context.error_summary_apply_agent2llm import POINT as ERROR_APPLY_AGENT2LLM

PHASE_ONE_DECLARATIONS = (
    BEFORE_GENERATE_USER2AGENT,
    BEFORE_GENERATE_AGENT2LLM,
    AFTER_APPLY_USER2AGENT,
    AFTER_APPLY_AGENT2LLM,
    ERROR_GENERATE_USER2AGENT,
    ERROR_GENERATE_AGENT2LLM,
    ERROR_APPLY_USER2AGENT,
    ERROR_APPLY_AGENT2LLM,
)
PHASE_TWO_DECLARATIONS = (AFTER_GENERATE_USER2AGENT, AFTER_GENERATE_AGENT2LLM)


def create_summary_catalog() -> HookPointCatalog:
    """Own exactly eight eligible declarations without registration or dispatch."""
    return HookPointCatalog(PHASE_ONE_DECLARATIONS)


SUMMARY_CATALOG = create_summary_catalog()

__all__ = ["SUMMARY_CATALOG", "create_summary_catalog", "PHASE_TWO_DECLARATIONS"]
