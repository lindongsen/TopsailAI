"""API key management routes for agent_daemon."""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request as FastAPIRequest
from pydantic import BaseModel, Field
from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.api.middleware.auth import (
    get_current_api_key,
    require_admin,
    check_session_permission,
    verify_session_permission,
    check_rate_limit,
    verify_rate_limit,
    ApiKeyData
)
from topsailai_server.agent_daemon.storage.api_key_manager import (
    ApiKeyData as StorageApiKeyData,
    ApiKeySessionData,
    ApiKeyEnvironData
)

# Router
router = APIRouter(prefix="/api/v1/apikey", tags=["apikey"])

# Dependencies (set by set_dependencies)
_session_storage = None
_message_storage = None
_worker_manager = None
_api_key_storage = None


def set_dependencies(session_storage, message_storage, worker_manager):
    """Set storage and worker dependencies for the router."""
    global _session_storage, _message_storage, _worker_manager, _api_key_storage
    _session_storage = session_storage
    _message_storage = message_storage
    _worker_manager = worker_manager
    # api_key_storage is set via auth middleware
    from topsailai_server.agent_daemon.api.middleware.auth import _api_key_storage as auth_api_key_storage
    _api_key_storage = auth_api_key_storage


# Request/Response Models
class CreateApiKeyRequest(BaseModel):
    """Request model for creating an API key."""
    name: str = Field(..., description="Human-readable name for the key")
    role: str = Field(default="user", description="Role: 'admin' or 'user'")
    rate_limit: Optional[int] = Field(default=None, description="Max messages per minute, 0=unlimited")
    session_ids: Optional[list] = Field(default=None, description="Sessions to bind (user role only)")


class CreateApiKeyResponse(BaseModel):
    """Response model for creating an API key."""
    api_key_id: str
    api_key: str
    name: str
    role: str
    rate_limit: int
    is_active: bool
    create_time: datetime
    update_time: datetime


class BindSessionsRequest(BaseModel):
    """Request model for binding sessions to an API key."""
    session_ids: list = Field(..., description="List of session IDs to bind")


class UnbindSessionsRequest(BaseModel):
    """Request model for unbinding sessions from an API key."""
    session_ids: list = Field(..., description="List of session IDs to unbind")


class SetEnvironRequest(BaseModel):
    """Request model for setting an environment variable for an API key."""
    key: str = Field(..., description="Environment variable name")
    value: str = Field(..., description="Environment variable value")


# Routes
@router.post("", response_model=dict)
async def create_api_key(
    request: CreateApiKeyRequest,
    current_key: ApiKeyData = Depends(require_admin)
):
    """Create a new API key. Admin only."""
    # Validate role
    if request.role not in ("admin", "user"):
        return {"code": 400, "data": None, "message": "Invalid role. Must be 'admin' or 'user'"}

    # Validate rate_limit
    if request.rate_limit is not None and request.rate_limit < 0:
        return {"code": 400, "data": None, "message": "rate_limit must be >= 0"}

    # Set default rate_limit based on role
    if request.rate_limit is None:
        rate_limit = 0 if request.role == "admin" else 60
    else:
        rate_limit = request.rate_limit

    # Generate API key ID and value
    import secrets
    api_key_id = "ak_" + secrets.token_hex(8)
    api_key_value = secrets.token_hex(32)

    now = datetime.now()
    api_key_data = StorageApiKeyData(
        api_key_id=api_key_id,
        api_key=api_key_value,
        name=request.name,
        role=request.role,
        rate_limit=rate_limit,
        is_active=True,
        create_time=now,
        update_time=now
    )

    _api_key_storage.create_api_key(api_key_data)

    # Bind sessions if provided (only for user role)
    if request.role == "user" and request.session_ids:
        for session_id in request.session_ids:
            binding = ApiKeySessionData(
                api_key_id=api_key_id,
                session_id=session_id,
                create_time=now
            )
            _api_key_storage.bind_session(binding)

    logger.info("API key created: %s (role=%s)", api_key_id, request.role)

    return {
        "code": 0,
        "data": CreateApiKeyResponse(
            api_key_id=api_key_id,
            api_key=api_key_value,
            name=request.name,
            role=request.role,
            rate_limit=rate_limit,
            is_active=True,
            create_time=now,
            update_time=now
        ),
        "message": "API key created successfully"
    }


@router.get("", response_model=dict)
async def list_api_keys(
    session_id: Optional[str] = None,
    current_key: ApiKeyData = Depends(get_current_api_key)
):
    """List API keys. Admin sees all keys; user sees only their own key."""
    if current_key.role == "admin":
        if session_id:
            api_keys_with_details = _api_key_storage.list_api_keys_by_session_id(session_id)
        else:
            api_keys_with_details = _api_key_storage.list_api_keys_with_details()
    else:
        # User role: can only query their own key
        if session_id:
            if not _api_key_storage.is_session_bound(current_key.api_key_id, session_id):
                raise HTTPException(
                    status_code=403,
                    detail="Access denied to session: %s" % session_id
                )
        api_keys_with_details = _api_key_storage.get_api_key_with_details(current_key.api_key_id)
        api_keys_with_details = [api_keys_with_details] if api_keys_with_details else []

    api_keys = []
    for item in api_keys_with_details:
        key_dict = item["api_key"].to_dict()
        key_dict["sessions"] = item["session_ids"]
        key_dict["environs"] = [env.to_dict() for env in item["environs"]]
        api_keys.append(key_dict)
    return {
        "code": 0,
        "data": {
            "api_keys": api_keys,
            "total": len(api_keys)
        },
        "message": "OK"
    }


@router.delete("/{api_key_id}", response_model=dict)
async def delete_api_key(
    api_key_id: str,
    current_key: ApiKeyData = Depends(require_admin)
):
    """Delete an API key. Admin only."""
    api_key = _api_key_storage.get_api_key_by_id(api_key_id)
    if not api_key:
        return {"code": 404, "data": None, "message": "API key not found"}

    # Prevent deleting the last admin key
    if api_key.role == "admin":
        admin_count = _api_key_storage.count_admin_api_keys()
        if admin_count <= 1:
            return {"code": 400, "data": None, "message": "Cannot delete the last admin API key"}

    _api_key_storage.delete_api_key(api_key_id)
    logger.info("API key deleted: %s", api_key_id)

    return {
        "code": 0,
        "data": None,
        "message": "API key deleted successfully"
    }


@router.post("/{api_key_id}/sessions", response_model=dict)
async def bind_sessions(
    api_key_id: str,
    request: BindSessionsRequest,
    current_key: ApiKeyData = Depends(require_admin)
):
    """Bind sessions to a user API key. Admin only."""
    api_key = _api_key_storage.get_api_key_by_id(api_key_id)
    if not api_key:
        return {"code": 404, "data": None, "message": "API key not found"}

    if api_key.role == "admin":
        return {"code": 400, "data": None, "message": "Cannot bind sessions to admin API key"}

    now = datetime.now()
    bound_sessions = []
    for session_id in request.session_ids:
        binding = ApiKeySessionData(
            api_key_id=api_key_id,
            session_id=session_id,
            create_time=now
        )
        _api_key_storage.bind_session(binding)
        bound_sessions.append(session_id)

    logger.info("Sessions bound to API key %s: %s", api_key_id, bound_sessions)

    return {
        "code": 0,
        "data": {"bound_sessions": bound_sessions},
        "message": "Sessions bound successfully"
    }


@router.delete("/{api_key_id}/sessions", response_model=dict)
async def unbind_sessions(
    api_key_id: str,
    request: UnbindSessionsRequest,
    current_key: ApiKeyData = Depends(require_admin)
):
    """Unbind sessions from a user API key. Admin only."""
    api_key = _api_key_storage.get_api_key_by_id(api_key_id)
    if not api_key:
        return {"code": 404, "data": None, "message": "API key not found"}

    unbound_sessions = []
    for session_id in request.session_ids:
        _api_key_storage.unbind_session(api_key_id, session_id)
        unbound_sessions.append(session_id)

    logger.info("Sessions unbound from API key %s: %s", api_key_id, unbound_sessions)

    return {
        "code": 0,
        "data": {"unbound_sessions": unbound_sessions},
        "message": "Sessions unbound successfully"
    }


@router.post("/{api_key_id}/environs", response_model=dict)
async def set_api_key_environ(
    api_key_id: str,
    request: SetEnvironRequest,
    current_key: ApiKeyData = Depends(require_admin)
):
    """
    Set an environment variable for an API key.
    Creates a new entry if the key does not exist, updates it otherwise.
    Admin only.
    """
    api_key = _api_key_storage.get_api_key_by_id(api_key_id)
    if not api_key:
        return {"code": 404, "data": None, "message": "API key not found"}

    _api_key_storage.create_api_key_environ(
        api_key_id=api_key_id,
        key=request.key,
        value=request.value
    )

    # Fetch the created/updated record to return in response
    environ_data = _api_key_storage.get_api_key_environ_by_api_key_id_and_key(
        api_key_id=api_key_id,
        key=request.key
    )

    logger.info(
        "Environment variable set for API key %s: %s=%s",
        api_key_id, request.key, request.value
    )

    return {
        "code": 0,
        "data": environ_data.to_dict(),
        "message": "Environment variable set successfully"
    }

@router.get("/{api_key_id}/environs", response_model=dict)
async def list_api_key_environs(
    api_key_id: str,
    current_key: ApiKeyData = Depends(require_admin)
):
    """List all environment variables for an API key. Admin only."""
    api_key = _api_key_storage.get_api_key_by_id(api_key_id)
    if not api_key:
        return {"code": 404, "data": None, "message": "API key not found"}

    environs = _api_key_storage.get_api_key_environs_by_api_key_id(api_key_id)

    return {
        "code": 0,
        "data": {
            "environs": [env.to_dict() for env in environs],
            "total": len(environs)
        },
        "message": "OK"
    }


@router.delete("/{api_key_id}/environs/{key}", response_model=dict)
async def delete_api_key_environ(
    api_key_id: str,
    key: str,
    current_key: ApiKeyData = Depends(require_admin)
):
    """Delete an environment variable for an API key. Admin only."""
    api_key = _api_key_storage.get_api_key_by_id(api_key_id)
    if not api_key:
        return {"code": 404, "data": None, "message": "API key not found"}

    deleted = _api_key_storage.delete_api_key_environ(api_key_id, key)
    if not deleted:
        return {"code": 404, "data": None, "message": "Environment variable not found"}

    logger.info(
        "Environment variable deleted for API key %s: %s",
        api_key_id, key
    )

    return {
        "code": 0,
        "data": None,
        "message": "Environment variable deleted successfully"
    }
