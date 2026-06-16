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
def api_client() -> Generator[requests.Session, None, None]:
    """Create a requests session for API tests."""
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
