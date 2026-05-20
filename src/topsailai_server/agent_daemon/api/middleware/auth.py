"""
  Author: km2
  Email: lin_dongsen@126.com
  Created: 2026-05-04
  Purpose: Authentication and authorization dependencies for agent_daemon API.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Header, HTTPException, Request, Depends

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.configer.env_config import get_config
from topsailai_server.agent_daemon.storage.api_key_manager.base import ApiKeyData

# Global reference to API key storage (set by app.py)
_api_key_storage = None

DUMMY_API_KEY = ApiKeyData(
    api_key_id="dummy",
    api_key="dummy",
    name="dummy",
    role="admin",
    rate_limit=0,
    is_active=True,
    create_time=datetime.now(),
    update_time=datetime.now(),
)


def set_dependencies(api_key_storage):
    """Set the API key storage dependency (called by app.py)."""
    global _api_key_storage
    _api_key_storage = api_key_storage


def _extract_api_key_from_request(request: Request) -> Optional[str]:
    """
    Extract the API key value from the request headers.

    Supports two authentication methods:
    1. X-API-Key header (takes precedence)
    2. Authorization: Bearer <token> header

    Args:
        request: The incoming HTTP request.

    Returns:
        The API key value if found, otherwise None.
    """
    # First, check X-API-Key header (takes precedence)
    api_key_value = request.headers.get("X-API-Key")
    if api_key_value:
        return api_key_value

    # Fallback: check Authorization header for Bearer token
    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            bearer_token = parts[1]
            if bearer_token:
                return bearer_token

    return None


async def get_current_api_key(
    request: Request,
) -> ApiKeyData:
    """
    Validate the API key from request headers and return the corresponding ApiKeyData.

    Supports both X-API-Key and Authorization: Bearer <token> headers.
    X-API-Key takes precedence over Authorization: Bearer.

    Args:
        request: The incoming HTTP request.

    Returns:
        ApiKeyData: The validated API key data.

    Raises:
        HTTPException: 401 if the header is missing or the key is invalid/inactive.
    """
    if not get_config().api_key_enabled:
        logger.debug("API key authentication is disabled, returning dummy key")
        return DUMMY_API_KEY

    api_key_value = _extract_api_key_from_request(request)
    if not api_key_value:
        logger.warning("API request missing API key (X-API-Key or Authorization: Bearer)")
        raise HTTPException(status_code=401, detail="Missing API key")

    if _api_key_storage is None:
        logger.error("API key storage not initialized", stack_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    api_key_data = _api_key_storage.get_api_key_by_value(api_key_value)
    if not api_key_data:
        logger.warning("Invalid API key: %s", api_key_value[:8])
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not api_key_data.is_active:
        logger.warning("Inactive API key: %s", api_key_value[:8])
        raise HTTPException(status_code=401, detail="Inactive API key")

    logger.debug("Authenticated API key: %s", api_key_data.api_key_id)
    return api_key_data


async def require_admin(
    api_key: ApiKeyData = Depends(get_current_api_key)
) -> ApiKeyData:
    """
    Ensure the current API key has admin role.

    Args:
        api_key: The authenticated API key data.

    Returns:
        ApiKeyData: The admin API key data.

    Raises:
        HTTPException: 403 if the key is not an admin key.
    """
    if not get_config().api_key_enabled:
        return DUMMY_API_KEY

    if api_key.role != 'admin':
        logger.warning("Admin access denied for API key: %s", api_key.api_key_id)
        raise HTTPException(status_code=403, detail="Admin access required")
    return api_key


async def check_session_permission(
    request: Request,
    api_key: ApiKeyData = Depends(get_current_api_key)
) -> None:
    """
    Check if the API key has permission to access the requested session.

    This dependency extracts session_id from path parameters or query parameters.
    For endpoints where session_id is in the request body, use verify_session_permission().

    Admin keys are granted access to all sessions.
    User keys must have an explicit binding in api_key_session table.

    Args:
        request: The incoming HTTP request.
        api_key: The authenticated API key data.

    Raises:
        HTTPException: 403 if access is denied.
    """
    if not get_config().api_key_enabled:
        return

    session_id = request.path_params.get('session_id') or request.query_params.get('session_id')
    if not session_id:
        # No session_id to check, skip permission check
        return

    verify_session_permission(api_key, session_id)


def verify_session_permission(api_key: ApiKeyData, session_id: str) -> None:
    """
    Verify that the API key has permission to access the given session.

    This helper is used by route handlers when session_id comes from the request body.

    Args:
        api_key: The authenticated API key data.
        session_id: The session ID to check.

    Raises:
        HTTPException: 403 if access is denied.
    """
    if not get_config().api_key_enabled:
        return

    if api_key.role == 'admin':
        return

    if _api_key_storage is None:
        logger.error("API key storage not initialized", stack_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    if not _api_key_storage.is_session_bound(api_key.api_key_id, session_id):
        logger.warning(
            "Access denied: API key %s to session %s",
            api_key.api_key_id, session_id
        )
        raise HTTPException(
            status_code=403,
            detail="Access denied to session: %s" % session_id
        )

    logger.debug(
        "Access granted: API key %s to session %s",
        api_key.api_key_id, session_id
    )


async def check_rate_limit(
    request: Request,
    api_key: ApiKeyData = Depends(get_current_api_key)
) -> None:
    """
    Check if the API key has exceeded its rate limit for message sending.

    This dependency extracts session_id from path parameters or query parameters.
    For endpoints where session_id is in the request body, use verify_rate_limit().

    Rate limit of 0 means unlimited.

    Args:
        request: The incoming HTTP request.
        api_key: The authenticated API key data.

    Raises:
        HTTPException: 429 if rate limit is exceeded.
    """
    if not get_config().api_key_enabled:
        return

    if api_key.rate_limit == 0:
        return

    session_id = request.path_params.get('session_id') or request.query_params.get('session_id')
    if not session_id:
        return

    verify_rate_limit(api_key, session_id)


def verify_rate_limit(api_key: ApiKeyData, session_id: str) -> None:
    """
    Verify that the API key has not exceeded its rate limit.

    This helper is used by route handlers when session_id comes from the request body.
    After a successful check, a rate limit log entry is recorded.

    Args:
        api_key: The authenticated API key data.
        session_id: The session ID being accessed.

    Raises:
        HTTPException: 429 if rate limit is exceeded.
    """
    if not get_config().api_key_enabled:
        return

    if api_key.rate_limit == 0:
        return

    if _api_key_storage is None:
        logger.error("API key storage not initialized", stack_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    since = datetime.now() - timedelta(seconds=60)
    count = _api_key_storage.count_rate_limit(
        api_key.api_key_id, 'receive_message', since
    )

    if count >= api_key.rate_limit:
        logger.warning(
            "Rate limit exceeded for API key %s: %d/%d per minute",
            api_key.api_key_id, count, api_key.rate_limit
        )
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded: %d messages per minute" % api_key.rate_limit
        )

    # Log the rate limit entry after successful check
    _api_key_storage.log_rate_limit(
        api_key.api_key_id, session_id, 'receive_message'
    )
    logger.debug(
        "Rate limit check passed for API key %s: %d/%d",
        api_key.api_key_id, count + 1, api_key.rate_limit
    )
