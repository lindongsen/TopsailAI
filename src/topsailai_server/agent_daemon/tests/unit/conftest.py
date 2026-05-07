"""Global test fixtures for unit tests."""
import pytest
from unittest.mock import patch
from datetime import datetime
from topsailai_server.agent_daemon.storage.api_key_manager.base import ApiKeyData


def _make_default_admin_key():
    """Create a default admin API key for testing."""
    return ApiKeyData(
        api_key_id="test-admin-id",
        api_key="test-admin-key",
        name="Test Admin",
        role="admin",
        rate_limit=0,
        is_active=True,
        create_time=datetime.now(),
        update_time=datetime.now()
    )


@pytest.fixture(autouse=True)
def mock_auth_dependency():
    """Mock auth dependency for all unit tests.
    
    Provides a default admin API key so legacy tests don't need to
    explicitly provide X-API-Key headers.
    
    Patches create_app to inject auth dependency overrides into the
    FastAPI app after creation.
    """
    from topsailai_server.agent_daemon.api.app import create_app as original_create_app
    from topsailai_server.agent_daemon.api.middleware.auth import (
        get_current_api_key,
        check_session_permission,
        check_rate_limit,
    )
    
    default_admin_key = _make_default_admin_key()
    
    def _patched_create_app(*args, **kwargs):
        app = original_create_app(*args, **kwargs)
        app.dependency_overrides[get_current_api_key] = lambda: default_admin_key
        app.dependency_overrides[check_session_permission] = lambda: None
        app.dependency_overrides[check_rate_limit] = lambda: None
        return app
    
    with patch("topsailai_server.agent_daemon.api.app.create_app", _patched_create_app):
        yield
