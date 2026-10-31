"""Session category configuration and validation."""

import logging
import re
from collections.abc import Mapping

logger = logging.getLogger(__name__)
SESSION_CATEGORY_ENV = "TOPSAILAI_SESSION_CATEGORY"
_SESSION_CATEGORY_PATTERN = re.compile(r"[a-z0-9_]+")


def resolve_session_category(session_category: str) -> str:
    """Return a valid session category or an empty string."""
    if session_category == "":
        return ""
    if isinstance(session_category, str) and _SESSION_CATEGORY_PATTERN.fullmatch(session_category):
        return session_category
    logger.error("Invalid %s value %r; expected lowercase letters, digits, or underscores", SESSION_CATEGORY_ENV, session_category)
    return ""


def load_session_category(environ: Mapping[str, str]) -> str:
    """Load and validate the session category from a supplied environment mapping."""
    return resolve_session_category(environ.get(SESSION_CATEGORY_ENV, ""))
