"""Explicit input catalog composition, without runtime registration.

Author: DawsonLin
"""

from topsailai.hooks.hook_point_catalog import HookPointCatalog
from topsailai.hooks.points.workspace.before_input_message import POINT

INPUT_DECLARATIONS = (POINT,)


def create_input_catalog() -> HookPointCatalog:
    """Own the input declaration without activating execution sources."""
    return HookPointCatalog(INPUT_DECLARATIONS)


INPUT_CATALOG = create_input_catalog()

__all__ = ["INPUT_CATALOG", "INPUT_DECLARATIONS", "create_input_catalog"]
