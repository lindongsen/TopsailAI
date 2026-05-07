"""
  Author: km2
  Email: lin_dongsen@126.com
  Created: 2026-05-04
  Purpose: API key management routes - FastAPI implementation
"""

import secrets
from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage
from topsailai_server.agent_daemon.storage.api_key_manager.base import ApiKeyData
from topsailai_server.agent_daemon.api.utils import ApiResponse, success_response, error_response
from topsailai_server.agent_daemon.api.middleware.auth import require_admin


# Router
router = APIRouter(prefix="/api/v1/apikey", tags=["api_key"])

# Global dependencies (set by app.py)
_api_key_storage = None
def set_dependencies(session_storage, message_storage, worker_manager):
    """Set dependencies for the routes (called by app.py)"""
    global _api_key_storage
    _api_key_storage = session_storage


def get_storage() -> Storage:
    """Get Storage instance"""
    if _api_key_storage is None:
        raise RuntimeError("Storage not initialized")
    return Storage(_api_key_storage.engine)


# Request/Response Models
class CreateApiKeyRequest(BaseModel):
    """Request model for creating an API key"""
    name: str
    role: str = "user"
    rate_limit: int = 0
    session_ids: Optional[List[str]] = None


class BindSessionsRequest(BaseModel):
    """Request model for binding sessions to an API key"""
    session_ids: List[str]


class ApiKeyResponse(BaseModel):
    """Response model for an API key"""
    api_key_id: str
    api_key: str
    name: str
    role: str
    rate_limit: int
    is_active: bool
    create_time: datetime
    update_time: datetime


class ApiKeyListResponse(BaseModel):
    """Response model for listing API keys"""
    api_keys: List[ApiKeyResponse]
    total: int


def _generate_api_key() -> str:
    """Generate a secure random API key string."""
    return secrets.token_hex(32)


def _generate_api_key_id() -> str:
    """Generate a unique API key ID."""
    return "ak_" + secrets.token_hex(8)


@router.post("", response_model=ApiResponse)
async def create_api_key(
    request: CreateApiKeyRequest,
    storage: Storage = Depends(get_storage),
    admin_key: ApiKeyData = Depends(require_admin)
) -> ApiResponse:
    """
    Create a new API key.

    Only admin keys can create new API keys.
    Auto-generates a secure random api_key value.
    If role is 'user' and session_ids are provided, binds them immediately.

    Args:
        request: CreateApiKeyRequest with name, role, rate_limit, and optional session_ids
    """
    try:
        # Validate role
        if request.role not in ("admin", "user"):
            logger.warning("Invalid role for API key creation: %s", request.role)
            return error_response(message="Role must be 'admin' or 'user'")

        # Generate API key ID and value
        api_key_id = _generate_api_key_id()
        api_key_value = _generate_api_key()

        # Create API key data
        now = datetime.now()
        api_key_data = ApiKeyData(
            api_key_id=api_key_id,
            api_key=api_key_value,
            name=request.name,
            role=request.role,
            rate_limit=request.rate_limit,
            is_active=True,
            create_time=now,
            update_time=now
        )

        # Save to storage
        success = storage.api_key.create_api_key(api_key_data)
        if not success:
            logger.error("Failed to create API key in storage")
            return error_response(message="Failed to create API key")

        # Bind sessions if provided and role is user
        if request.role == "user" and request.session_ids:
            storage.api_key.bind_sessions(api_key_id, request.session_ids)
            logger.info("Bound %d sessions to new API key: %s", len(request.session_ids), api_key_id)

        logger.info("Created API key: %s, role=%s, by admin=%s",
                   api_key_id, request.role, admin_key.api_key_id)

        return success_response(
            data=api_key_data.__dict__,
            message="API key created successfully"
        )

    except Exception as e:
        logger.exception("Error creating API key: %s", e)
        return error_response(message="Failed to create API key: %s" % str(e))


@router.get("", response_model=ApiResponse)
async def list_api_keys(
    offset: int = 0,
    limit: int = 1000,
    storage: Storage = Depends(get_storage),
    admin_key: ApiKeyData = Depends(require_admin)
) -> ApiResponse:
    """
    List all API keys.

    Only admin keys can list all API keys.

    Args:
        offset: Pagination offset
        limit: Maximum number of keys to return
    """
    try:
        api_keys = storage.api_key.list_api_keys()
        total = len(api_keys)

        # Apply pagination
        paginated_keys = api_keys[offset:offset + limit]

        # Convert to response format
        key_list = []
        for key in paginated_keys:
            key_list.append(ApiKeyResponse(
                api_key_id=key.api_key_id,
                api_key=key.api_key,
                name=key.name,
                role=key.role,
                rate_limit=key.rate_limit,
                is_active=key.is_active,
                create_time=key.create_time,
                update_time=key.update_time
            ))

        logger.debug("Listed %d API keys (total: %d)", len(key_list), total)
        return success_response(
            data={
                "api_keys": [k.model_dump() for k in key_list],
                "total": total
            }
        )

    except Exception as e:
        logger.exception("Error listing API keys: %s", e)
        return error_response(message="Failed to list API keys: %s" % str(e))


@router.delete("/{api_key_id}", response_model=ApiResponse)
async def delete_api_key(
    api_key_id: str,
    storage: Storage = Depends(get_storage),
    admin_key: ApiKeyData = Depends(require_admin)
) -> ApiResponse:
    """
    Delete an API key and its related bindings and rate limit logs.

    Only admin keys can delete API keys.

    Args:
        api_key_id: The API key ID to delete
    """
    try:
        # Check if the key exists
        existing = storage.api_key.get_api_key_by_id(api_key_id)
        if not existing:
            logger.warning("API key not found for deletion: %s", api_key_id)
            return error_response(message="API key not found", code=404)

        # Prevent deleting the last admin key
        if existing.role == "admin":
            all_keys = storage.api_key.list_api_keys()
            admin_count = sum(1 for k in all_keys if k.role == "admin" and k.is_active)
            if admin_count <= 1:
                logger.warning("Cannot delete the last admin API key: %s", api_key_id)
                return error_response(message="Cannot delete the last admin API key")

        # Delete the API key (cascades to bindings and logs)
        success = storage.api_key.delete_api_key(api_key_id)
        if not success:
            logger.error("Failed to delete API key: %s", api_key_id)
            return error_response(message="Failed to delete API key")

        logger.info("Deleted API key: %s, by admin=%s", api_key_id, admin_key.api_key_id)
        return success_response(message="API key deleted successfully")

    except Exception as e:
        logger.exception("Error deleting API key: %s", e)
        return error_response(message="Failed to delete API key: %s" % str(e))


@router.post("/{api_key_id}/sessions", response_model=ApiResponse)
async def bind_sessions(
    api_key_id: str,
    request: BindSessionsRequest,
    storage: Storage = Depends(get_storage),
    admin_key: ApiKeyData = Depends(require_admin)
) -> ApiResponse:
    """
    Bind sessions to a user API key.

    Only admin keys can bind sessions.
    The target API key must exist and be a user key (not admin).

    Args:
        api_key_id: The API key ID to bind sessions to
        request: BindSessionsRequest with list of session_ids
    """
    try:
        # Check if the key exists
        existing = storage.api_key.get_api_key_by_id(api_key_id)
        if not existing:
            logger.warning("API key not found for binding: %s", api_key_id)
            return error_response(message="API key not found", code=404)

        # Only user keys can have session bindings
        if existing.role == "admin":
            logger.warning("Cannot bind sessions to admin API key: %s", api_key_id)
            return error_response(message="Cannot bind sessions to admin API key")

        # Bind sessions
        success = storage.api_key.bind_sessions(api_key_id, request.session_ids)
        if not success:
            logger.error("Failed to bind sessions to API key: %s", api_key_id)
            return error_response(message="Failed to bind sessions")

        logger.info("Bound %d sessions to API key: %s, by admin=%s",
                   len(request.session_ids), api_key_id, admin_key.api_key_id)

        return success_response(
            data={"bound_sessions": request.session_ids},
            message="Sessions bound successfully"
        )

    except Exception as e:
        logger.exception("Error binding sessions: %s", e)
        return error_response(message="Failed to bind sessions: %s" % str(e))


@router.delete("/{api_key_id}/sessions", response_model=ApiResponse)
async def unbind_sessions(
    api_key_id: str,
    request: BindSessionsRequest,
    storage: Storage = Depends(get_storage),
    admin_key: ApiKeyData = Depends(require_admin)
) -> ApiResponse:
    """
    Unbind sessions from a user API key.

    Only admin keys can unbind sessions.

    Args:
        api_key_id: The API key ID to unbind sessions from
        request: BindSessionsRequest with list of session_ids to unbind
    """
    try:
        # Check if the key exists
        existing = storage.api_key.get_api_key_by_id(api_key_id)
        if not existing:
            logger.warning("API key not found for unbinding: %s", api_key_id)
            return error_response(message="API key not found", code=404)

        # Unbind sessions
        success = storage.api_key.unbind_sessions(api_key_id, request.session_ids)
        if not success:
            logger.error("Failed to unbind sessions from API key: %s", api_key_id)
            return error_response(message="Failed to unbind sessions")

        logger.info("Unbound %d sessions from API key: %s, by admin=%s",
                   len(request.session_ids), api_key_id, admin_key.api_key_id)

        return success_response(
            data={"unbound_sessions": request.session_ids},
            message="Sessions unbound successfully"
        )

    except Exception as e:
        logger.exception("Error unbinding sessions: %s", e)
        return error_response(message="Failed to unbind sessions: %s" % str(e))
