"""
Pytest configuration and shared fixtures for ACS integration tests.
"""

import asyncio
import json
import os
import time
import uuid
from typing import AsyncGenerator, Generator

import nats
import pytest
import pytest_asyncio
import requests

from .mock_agent_server import MockAgentServer

# Test configuration
TEST_SERVER_HOST = "127.0.0.1"
TEST_SERVER_PORT = 7370
TEST_NATS_URL = os.environ.get("ACS_NATS_SERVERS", "nats://127.0.0.1:4222")


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def base_url() -> str:
    """Return the base URL for the ACS server."""
    return f"http://{TEST_SERVER_HOST}:{TEST_SERVER_PORT}"

@pytest.fixture(scope="function")
def api_client(admin_token: str) -> Generator[requests.Session, None, None]:
    """Create a requests session for API tests, authenticated as admin."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    session.headers.update({"Authorization": f"Bearer {admin_token}"})
    yield session
    session.close()


@pytest.fixture(scope="function")
def unauthenticated_client() -> Generator[requests.Session, None, None]:
    """Create a requests session with no authentication."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    yield session
    session.close()
@pytest.fixture(scope="function")
def unique_id() -> str:
    """Generate a unique identifier for test isolation."""
    return str(uuid.uuid4())[:8]
@pytest.fixture(scope="function")
def server_url(base_url: str) -> str:
    """Return the server URL."""
    return base_url


@pytest.fixture(scope="function")
def test_group(api_client: requests.Session, server_url: str, unique_id: str) -> dict:
    """Create a test group and return its data."""
    group_data = {
        "group_name": f"Test Group {unique_id}",
        "group_context": f"Test context for {unique_id}",
        "group_key": ""
    }

    response = api_client.post(f"{server_url}/api/v1/groups", json=group_data)
    assert response.status_code == 201, f"Failed to create group: {response.text}"

    data = response.json()
    yield data

    # Cleanup: delete the group
    api_client.delete(f"{server_url}/api/v1/groups/{data['group_id']}")


@pytest.fixture(scope="function")
def test_group_with_key(api_client: requests.Session, server_url: str, unique_id: str) -> dict:
    """Create a test group with a secret key."""
    group_data = {
        "group_name": f"Secret Group {unique_id}",
        "group_context": "Private group",
        "group_key": "my-secret-key"
    }

    response = api_client.post(f"{server_url}/api/v1/groups", json=group_data)
    assert response.status_code == 201, f"Failed to create group: {response.text}"

    data = response.json()
    yield data

    # Cleanup
    api_client.delete(f"{server_url}/api/v1/groups/{data['group_id']}")


@pytest.fixture(scope="function")
def test_member(api_client: requests.Session, server_url: str, test_group: dict, unique_id: str) -> dict:
    """Create a test user member in the test group."""
    member_data = {
        "member_id": f"user-{unique_id}",
        "member_name": f"Test_User_{unique_id}",
        "member_description": "A test user",
        "member_type": "user"
    }

    response = api_client.post(
        f"{server_url}/api/v1/groups/{test_group['group_id']}/members",
        json=member_data
    )
    assert response.status_code == 201, f"Failed to add member: {response.text}"

    data = response.json()
    yield data

    # Cleanup: remove member
    api_client.delete(
        f"{server_url}/api/v1/groups/{test_group['group_id']}/members/{data['member_id']}"
    )


@pytest.fixture(scope="function")
def test_agent_member(api_client: requests.Session, server_url: str, test_group: dict, unique_id: str) -> dict:
    """Create a test agent member in the test group."""
    agent_interface = {
        "adaptor": "topsailai_agent",
        "environments": {
            "ACS_AGENT_API_BASE": f"http://{TEST_SERVER_HOST}:{TEST_SERVER_PORT}",
            "ACS_AGENT_API_KEY": "test-key",
            "ACS_AGENT_API_AUTH": "bearer"
        },
        "timeout_chat": 30
    }

    member_data = {
        "member_id": f"agent-{unique_id}",
        "member_name": f"Test_Agent_{unique_id}",
        "member_description": "A test agent",
        "member_type": "worker-agent",
        "member_interface": json.dumps(agent_interface)
    }

    response = api_client.post(
        f"{server_url}/api/v1/groups/{test_group['group_id']}/members",
        json=member_data
    )
    assert response.status_code == 201, f"Failed to add agent: {response.text}"

    data = response.json()
    yield data

    # Cleanup
    api_client.delete(
        f"{server_url}/api/v1/groups/{test_group['group_id']}/members/{data['member_id']}"
    )


@pytest.fixture(scope="function")
def test_manager_agent(api_client: requests.Session, server_url: str, test_group: dict, unique_id: str) -> dict:
    """Create a test manager agent member in the test group."""
    agent_interface = {
        "adaptor": "topsailai_agent",
        "environments": {
            "ACS_AGENT_API_BASE": f"http://{TEST_SERVER_HOST}:{TEST_SERVER_PORT}",
            "ACS_AGENT_API_KEY": "test-key",
            "ACS_AGENT_API_AUTH": "bearer"
        },
        "timeout_chat": 30
    }

    member_data = {
        "member_id": f"manager-{unique_id}",
        "member_name": f"Manager_Agent_{unique_id}",
        "member_description": "A manager agent",
        "member_type": "manager-agent",
        "member_interface": json.dumps(agent_interface)
    }

    response = api_client.post(
        f"{server_url}/api/v1/groups/{test_group['group_id']}/members",
        json=member_data
    )
    assert response.status_code == 201, f"Failed to add manager agent: {response.text}"

    data = response.json()
    yield data

    # Cleanup
    api_client.delete(
        f"{server_url}/api/v1/groups/{test_group['group_id']}/members/{data['member_id']}"
    )


@pytest.fixture(scope="function")
def test_message(api_client: requests.Session, server_url: str, test_group: dict, test_member: dict) -> dict:
    """Create a test message in the test group."""
    message_data = {
        "message_text": "Hello, this is a test message!",
        "sender_id": test_member["member_id"],
        "sender_type": "user"
    }

    response = api_client.post(
        f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
        json=message_data
    )
    assert response.status_code == 201, f"Failed to create message: {response.text}"

    data = response.json()
    yield data

    # Cleanup: delete message
    api_client.delete(
        f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{data['message_id']}"
    )


@pytest.fixture(scope="function")
def mock_agent() -> Generator[MockAgentServer, None, None]:
    """Start a mock agent server for testing agent interactions."""
    agent = MockAgentServer(host=TEST_SERVER_HOST, port=TEST_SERVER_PORT + 1)
    agent.start()

    # Wait for server to be ready
    time.sleep(0.5)

    yield agent

    agent.stop()


@pytest_asyncio.fixture(scope="function")
async def nats_client() -> AsyncGenerator[nats.NATS, None]:
    """Create a NATS client connection."""
    nc = await nats.connect(TEST_NATS_URL)
    yield nc
    await nc.close()


@pytest_asyncio.fixture(scope="function")
async def nats_jetstream(nats_client: nats.NATS) -> AsyncGenerator:
    """Create a NATS JetStream context."""
    js = nats_client.jetstream()
    yield js


# ---------------------------------------------------------------------------
# Account / API key test helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = "/TopsailAI/src/topsailai_server/agent_community"


def _read_token(env_var: str, file_name: str) -> str | None:
    """Read an API key token from environment or the server-generated file."""
    token = os.environ.get(env_var)
    if token:
        return token.strip()
    token_path = os.path.join(PROJECT_ROOT, file_name)
    if os.path.exists(token_path):
        with open(token_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None


@pytest.fixture(scope="session")
def admin_token() -> str:
    """Return the admin API key token generated by the server on bootstrap."""
    token = _read_token("ACS_ACCOUNT_ADMIN_API_KEY", "ACS_ACCOUNT_ADMIN_API_KEY.acs")
    if not token:
        pytest.skip(
            "Admin API key not available. "
            "Start the ACS server or set ACS_ACCOUNT_ADMIN_API_KEY."
        )
    return token


@pytest.fixture(scope="session")
def manager_token() -> str | None:
    """Return the manager API key token if available."""
    return _read_token("ACS_ACCOUNT_MANAGER_API_KEY", "ACS_ACCOUNT_MANAGER_API_KEY.acs")


@pytest.fixture(scope="function")
def admin_client(api_client: requests.Session, admin_token: str) -> requests.Session:
    """Return a requests session authenticated with the admin API key."""
    api_client.headers.update({"Authorization": f"Bearer {admin_token}"})
    yield api_client


@pytest.fixture(scope="function")
def manager_client(api_client: requests.Session, manager_token: str | None) -> requests.Session | None:
    """Return a requests session authenticated with the manager API key."""
    if not manager_token:
        yield None
        return
    api_client.headers.update({"Authorization": f"Bearer {manager_token}"})
    yield api_client

@pytest.fixture(scope="function")
def test_account(admin_client: requests.Session, server_url: str, unique_id: str) -> dict:
    """Create a temporary user account and clean it up after the test."""
    account_data = {
        "account_name": f"Test User {unique_id}",
        "account_description": "Temporary integration test account",
        "role": "user",
        "login_name": f"test_user_{unique_id}",
        "login_password": "TestPass123!",
    }

    response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
    assert response.status_code == 201, f"Failed to create test account: {response.text}"
    account = response.json()

    yield account

    # Cleanup: soft-delete the account and any API keys created for it.
    admin_client.delete(f"{server_url}/api/v1/accounts/{account['account_id']}")


@pytest.fixture(scope="function")
def test_account_with_api_key(admin_client: requests.Session, server_url: str, test_account: dict) -> tuple[dict, str]:
    """Create a temporary API key for the test account and return (account, token)."""
    key_data = {"api_key_name": "integration-test-key", "role": "user"}
    response = admin_client.post(
        f"{server_url}/api/v1/accounts/{test_account['account_id']}/api-keys",
        json=key_data,
    )
    assert response.status_code == 201, f"Failed to create API key: {response.text}"
    result = response.json()
    return test_account, result["token"]


def check_server_available(base_url: str) -> bool:
    """Return True if the ACS server is reachable on the health endpoint."""
    try:
        response = requests.get(f"{base_url}/healthz", timeout=2)
        return response.status_code == 200
    except requests.RequestException:
        return False


@pytest.fixture(scope="session", autouse=True)
def require_server(base_url: str):
    """Skip all integration tests if the ACS server is not running."""
    if not check_server_available(base_url):
        pytest.skip(f"ACS server is not reachable at {base_url}. Skipping integration tests.")
